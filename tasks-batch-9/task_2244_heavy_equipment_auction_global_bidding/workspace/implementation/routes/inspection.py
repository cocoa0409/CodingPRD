"""Condition reports and refurbishment orders (PRD 3.3, 3.4)."""
from routes.common import (
    ANY_ROLE, ApiError, Blueprint, C, collection_response, db, endpoint,
    field_bool, field_decimal, field_enum, field_int, field_str, fetch,
    invalid_state, json_body, new_entity, object_response, pagination,
    query_enum, touch,
)
from services.calculations import condition_grade, hour_meter_variance_pct
from services.derive import recompute_consignor

bp = Blueprint("inspection", __name__)


def _report_scores(report):
    return {
        "structural": report["structural_score"],
        "powertrain": report["powertrain_score"],
        "hydraulics": report["hydraulics_score"],
        "tires": report["tires_score"],
    }


def _restamp_grade(report, lot):
    report["hour_meter_variance_pct"] = hour_meter_variance_pct(
        report["observed_hour_meter_reading"], lot["hour_meter_reading"])
    grade_score, band = condition_grade(
        _report_scores(report), report["hour_meter_verified"])
    report["grade_score"] = grade_score
    report["grade_band"] = band


def _score(body, name, required):
    return field_decimal(body, name, required=required, min_value=0,
                         max_value=100, max_decimals=1)


# --------------------------------------------------------------------------
# condition reports
# --------------------------------------------------------------------------
@bp.post("/lots/<lot_id>/condition-reports")
@endpoint("IntakeInspector")
def create_condition_report(actor, lot_id):
    body = json_body()
    structural = _score(body, "structural_score", True)
    powertrain = _score(body, "powertrain_score", True)
    hydraulics = _score(body, "hydraulics_score", True)
    tires = _score(body, "tires_score", True)
    observed = field_int(body, "observed_hour_meter_reading", required=True,
                         min_value=0, max_value=200000)
    verified = field_bool(body, "hour_meter_verified", required=True)
    photo_ref = field_str(body, "hour_meter_photo_ref", nullable=True,
                          default=None)

    lot = fetch(db.lots, lot_id, "ERR_LOT_NOT_FOUND")
    consignment = db.consignments[lot["consignment_id"]]
    # PRD 3.2 / ladder rung 17: "a replay is refused with
    # ERR_DUPLICATE_CONDITION_REPORT" — the replay of a create that already
    # produced a row is reported as the duplicate conflict, not as the generic
    # state conflict the lot has since moved into.
    for existing in db.condition_reports.values():
        if existing["lot_id"] == lot["id"]:
            raise ApiError("ERR_DUPLICATE_CONDITION_REPORT")
    if lot["lifecycle_status"] != "INTAKE":
        raise invalid_state("A condition report may only be filed on an INTAKE lot.")
    if consignment["status"] not in ("SUBMITTED", "INTAKE_ACCEPTED"):
        raise invalid_state(
            "The consignment must be SUBMITTED or INTAKE_ACCEPTED.")

    report = new_entity()
    report.update({
        "lot_id": lot["id"],
        "inspector_user_id": actor.user_id,
        "structural_score": structural,
        "powertrain_score": powertrain,
        "hydraulics_score": hydraulics,
        "tires_score": tires,
        "observed_hour_meter_reading": observed,
        "hour_meter_verified": verified,
        "hour_meter_photo_ref": photo_ref,
        "hour_meter_variance_pct": 0,
        "grade_score": 0,
        "grade_band": "D",
        "status": "DRAFT",
    })
    _restamp_grade(report, lot)
    db.condition_reports[report["id"]] = report

    lot["lifecycle_status"] = "INSPECTED"
    touch(lot)
    return object_response(report, 201)


@bp.get("/lots/<lot_id>/condition-reports")
@endpoint(*ANY_ROLE)
def list_lot_condition_reports(actor, lot_id):
    limit, offset = pagination()
    lot = fetch(db.lots, lot_id, "ERR_LOT_NOT_FOUND")
    rows = [r for r in db.condition_reports.values() if r["lot_id"] == lot["id"]]
    return collection_response(rows, limit, offset)


@bp.get("/condition-reports/<report_id>")
@endpoint(*ANY_ROLE)
def get_condition_report(actor, report_id):
    return object_response(
        fetch(db.condition_reports, report_id, "ERR_CONDITION_REPORT_NOT_FOUND"))


@bp.post("/condition-reports/<report_id>/rescore")
@endpoint("IntakeInspector")
def rescore_condition_report(actor, report_id):
    body = json_body()
    structural = _score(body, "structural_score", False)
    powertrain = _score(body, "powertrain_score", False)
    hydraulics = _score(body, "hydraulics_score", False)
    tires = _score(body, "tires_score", False)
    observed = field_int(body, "observed_hour_meter_reading", min_value=0,
                         max_value=200000, default=None)
    verified = field_bool(body, "hour_meter_verified", default=None)
    photo_present = "hour_meter_photo_ref" in body
    photo_ref = field_str(body, "hour_meter_photo_ref", nullable=True,
                          default=None)

    report = fetch(db.condition_reports, report_id,
                   "ERR_CONDITION_REPORT_NOT_FOUND")
    if report["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT condition report may be rescored.")

    if structural is not None:
        report["structural_score"] = structural
    if powertrain is not None:
        report["powertrain_score"] = powertrain
    if hydraulics is not None:
        report["hydraulics_score"] = hydraulics
    if tires is not None:
        report["tires_score"] = tires
    if observed is not None:
        report["observed_hour_meter_reading"] = observed
    if verified is not None:
        report["hour_meter_verified"] = verified
    if photo_present:
        report["hour_meter_photo_ref"] = photo_ref

    _restamp_grade(report, db.lots[report["lot_id"]])
    touch(report)
    return object_response(report)


@bp.post("/condition-reports/<report_id>/publish")
@endpoint("IntakeInspector")
def publish_condition_report(actor, report_id):
    json_body()
    report = fetch(db.condition_reports, report_id,
                   "ERR_CONDITION_REPORT_NOT_FOUND")
    lot = db.lots[report["lot_id"]]
    consignment = db.consignments[lot["consignment_id"]]

    if report["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT condition report may be published.")
    if lot["lifecycle_status"] != "INSPECTED":
        raise invalid_state("The lot must be INSPECTED to publish its report.")
    if consignment["status"] != "INTAKE_ACCEPTED":
        raise invalid_state("The consignment must be INTAKE_ACCEPTED.")

    orders = [o for o in db.refurbishment_orders.values()
              if o["lot_id"] == lot["id"]]
    if any(o["status"] != "COMPLETED" for o in orders):
        raise ApiError("ERR_REFURBISHMENT_INCOMPLETE")

    report["status"] = "PUBLISHED"
    touch(report)

    lot["lifecycle_status"] = "CATALOG_READY"
    touch(lot)

    # bubble-up: the consignment becomes CATALOGED once every non-withdrawn lot
    # is CATALOG_READY and at least one of them is.
    siblings = [l for l in db.lots.values()
                if l["consignment_id"] == consignment["id"]
                and l["lifecycle_status"] != "WITHDRAWN"]
    if siblings and all(l["lifecycle_status"] == "CATALOG_READY" for l in siblings):
        if consignment["status"] == "INTAKE_ACCEPTED":
            consignment["status"] = "CATALOGED"
            touch(consignment)
            recompute_consignor(db.consignors[consignment["consignor_id"]])
    return object_response(report)


# --------------------------------------------------------------------------
# refurbishment orders
# --------------------------------------------------------------------------
@bp.post("/refurbishment-orders")
@endpoint("IntakeInspector")
def create_refurbishment_order(actor):
    body = json_body()
    lot_id = field_str(body, "lot_id", required=True)
    scope_note = field_str(body, "scope_note", required=True, min_len=3,
                           max_len=500)
    estimated = field_int(body, "estimated_cost_cents", required=True,
                          min_value=0, max_value=100000000)
    lot = fetch(db.lots, lot_id, "ERR_LOT_NOT_FOUND")

    order = new_entity()
    order.update({
        "lot_id": lot["id"],
        "scope_note": scope_note,
        "estimated_cost_cents": estimated,
        "actual_cost_cents": None,
        "qa_note": None,
        "qa_signed_off_by_user_id": None,
        "rework_round": 0,
        "status": "DRAFT",
    })
    db.refurbishment_orders[order["id"]] = order
    return object_response(order, 201)


@bp.get("/lots/<lot_id>/refurbishment-orders")
@endpoint("PlatformAdmin", "Consignor", "IntakeInspector", "AuctionOperator",
          "SettlementOfficer")
def list_lot_refurbishment_orders(actor, lot_id):
    limit, offset = pagination()
    status = query_enum("status", C.REFURB_STATUSES)
    lot = fetch(db.lots, lot_id, "ERR_LOT_NOT_FOUND")
    rows = [o for o in db.refurbishment_orders.values()
            if o["lot_id"] == lot["id"]]
    if status is not None:
        rows = [o for o in rows if o["status"] == status]
    return collection_response(rows, limit, offset)


@bp.get("/refurbishment-orders/<order_id>")
@endpoint("PlatformAdmin", "Consignor", "IntakeInspector", "AuctionOperator",
          "SettlementOfficer")
def get_refurbishment_order(actor, order_id):
    return object_response(
        fetch(db.refurbishment_orders, order_id,
              "ERR_REFURBISHMENT_ORDER_NOT_FOUND"))


@bp.post("/refurbishment-orders/<order_id>/transition")
@endpoint("IntakeInspector")
def transition_refurbishment_order(actor, order_id):
    body = json_body()
    action = field_enum(body, "action", C.REFURB_ACTIONS, required=True)
    actual_cost = field_int(body, "actual_cost_cents", min_value=0,
                            max_value=100000000, default=None)
    qa_note = field_str(body, "qa_note", nullable=True, default=None)

    order = fetch(db.refurbishment_orders, order_id,
                  "ERR_REFURBISHMENT_ORDER_NOT_FOUND")
    lot = db.lots[order["lot_id"]]
    status = order["status"]

    if action == "START":
        if status not in ("DRAFT", "REWORK"):
            raise invalid_state("Work may only start from DRAFT or REWORK.")
        if status == "DRAFT" and lot["lifecycle_status"] != "INSPECTED":
            raise invalid_state("The lot must be INSPECTED before work starts.")
        order["status"] = "IN_PROGRESS"
    elif action == "SUBMIT_QA":
        if status != "IN_PROGRESS":
            raise invalid_state("Only work IN_PROGRESS may be submitted to QA.")
        if actual_cost is None:
            raise invalid_state("actual_cost_cents is required to submit to QA.")
        order["actual_cost_cents"] = actual_cost
        order["status"] = "QA_REVIEW"
    elif action == "QA_REWORK":
        if status != "QA_REVIEW":
            raise invalid_state("Only an order in QA_REVIEW may be sent back.")
        if not qa_note:
            raise invalid_state("qa_note is required to send work back.")
        if order["rework_round"] >= C.MAX_REWORK_ROUNDS:
            raise ApiError("ERR_MAX_REWORK_ROUNDS_EXCEEDED")
        order["rework_round"] += 1
        order["qa_note"] = qa_note
        order["status"] = "REWORK"
    else:  # QA_PASS
        if status != "QA_REVIEW":
            raise invalid_state("Only an order in QA_REVIEW may be passed.")
        if order["actual_cost_cents"] is None:
            raise invalid_state("actual_cost_cents must be recorded before QA pass.")
        report = None
        for candidate in db.condition_reports.values():
            if candidate["lot_id"] == lot["id"]:
                report = candidate
                break
        if report is not None and report["inspector_user_id"] == actor.user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        if qa_note:
            order["qa_note"] = qa_note
        order["qa_signed_off_by_user_id"] = actor.user_id
        order["status"] = "COMPLETED"

    touch(order)
    return object_response(order)
