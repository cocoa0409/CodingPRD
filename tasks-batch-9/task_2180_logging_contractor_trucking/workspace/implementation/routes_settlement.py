"""Settlement statements: compile, submit, approve, dispute, revise and pay."""

from flask import Blueprint, request

import calc
import derive
from core import (
    D,
    body,
    created,
    db,
    endpoint,
    fail,
    new_record,
    num,
    ok,
    ordered,
    paginated,
    req_date,
    req_int,
    req_str,
    rhu_int,
    to_date,
    tons,
    touch,
)

bp = Blueprint("settlement", __name__)

LOAD_LINE_TYPES = ("HAUL", "FUEL_SURCHARGE", "DEMURRAGE", "REJECT_DEDUCTION")


def eligible_loads(statement):
    """PRD 3.9 -- the whole eligibility filter, ordered by created_at ascending."""
    period_start = to_date(statement["period_start"])
    period_end = to_date(statement["period_end"])
    result = []
    for load in db.loads.values():
        if load.get("haul_contractor_id") != statement["haul_contractor_id"]:
            continue
        if load["settlement_status"] != "ACCRUED":
            continue
        if load["dispatch_status"] not in ("DELIVERED", "REJECTED"):
            continue
        if load.get("settlement_event_on") is None:
            continue
        event_on = to_date(load["settlement_event_on"])
        if not (period_start <= event_on <= period_end):
            continue
        result.append(load)
    return ordered(result)


def route_distance(load):
    route = db.haul_routes.get(load["haul_route_id"])
    return route["distance_miles"] if route else None


def compile_statement(statement):
    """calculations.settlement_statement_rollup -- pinned emission and money order."""
    lines = []
    for load in eligible_loads(statement):
        distance = route_distance(load)
        if load["dispatch_status"] == "DELIVERED":
            ticket = derive.certified_ticket_for_load(load["id"])
            line_tons = ticket["net_tons"] if ticket else None
            lines.append(
                {
                    "line_type": "HAUL",
                    "load_id": load["id"],
                    "tons": line_tons,
                    "distance_miles": distance,
                    "amount_cents": load["line_haul_cents"]
                    + load["incentive_cents"]
                    - load["regrade_adjustment_cents"],
                }
            )
            lines.append(
                {
                    "line_type": "FUEL_SURCHARGE",
                    "load_id": load["id"],
                    "tons": line_tons,
                    "distance_miles": distance,
                    "amount_cents": load["fuel_surcharge_cents"],
                }
            )
            if load["demurrage_cents"] > 0:
                lines.append(
                    {
                        "line_type": "DEMURRAGE",
                        "load_id": load["id"],
                        "tons": line_tons,
                        "distance_miles": distance,
                        "amount_cents": load["demurrage_cents"],
                    }
                )
        else:
            lines.append(
                {
                    "line_type": "REJECT_DEDUCTION",
                    "load_id": load["id"],
                    "tons": load["estimated_net_tons"],
                    "distance_miles": distance,
                    "amount_cents": -calc.reject_deduction_cents(load["provisional_haul_pay_cents"]),
                }
            )

    gross_pay_cents = sum(
        l["amount_cents"] for l in lines if l["line_type"] in ("HAUL", "FUEL_SURCHARGE", "DEMURRAGE")
    )
    reject_deduction_cents = abs(
        sum(l["amount_cents"] for l in lines if l["line_type"] == "REJECT_DEDUCTION")
    )
    score = derive.period_to_date_compliance_score(
        statement["haul_contractor_id"], statement["period_start"], statement["period_end"]
    )
    holdback_pct = calc.holdback_pct_for(score)
    settleable_base_cents = gross_pay_cents - reject_deduction_cents
    holdback_cents = rhu_int(D(settleable_base_cents) * holdback_pct)
    if lines:
        lines.append(
            {
                "line_type": "INSURANCE_HOLDBACK",
                "load_id": None,
                "tons": None,
                "distance_miles": None,
                "amount_cents": -holdback_cents,
            }
        )
    else:
        holdback_cents = 0
    deduction_cents = reject_deduction_cents + holdback_cents
    net_pay_cents = gross_pay_cents - deduction_cents

    statement["lines"] = lines
    statement["compliance_score_at_compile"] = score
    statement["holdback_pct"] = holdback_pct
    statement["gross_pay_cents"] = gross_pay_cents
    statement["reject_deduction_cents"] = reject_deduction_cents
    statement["holdback_cents"] = holdback_cents
    statement["deduction_cents"] = deduction_cents
    statement["net_pay_cents"] = net_pay_cents


def attached_load_ids(statement):
    seen = []
    for line in statement["lines"]:
        if line["line_type"] in LOAD_LINE_TYPES and line["load_id"] not in seen:
            seen.append(line["load_id"])
    return seen


# ---------------------------------------------------------------------------
@bp.route("/settlement-statements", methods=["POST"])
@endpoint("SettlementAccountant")
def create_settlement_statement(caller):
    payload = body()
    contractor_id = req_str(payload, "haul_contractor_id")
    period_start = req_date(payload, "period_start")
    period_end = req_date(payload, "period_end")
    expected_version = req_int(payload, "expected_haul_contractor_version")
    if period_end < period_start:
        fail("ERR_VALIDATION", "period_end must be on or after period_start")
    contractor = db.haul_contractors.get(contractor_id)
    if contractor is None:
        fail("ERR_HAUL_CONTRACTOR_NOT_FOUND", "no haul contractor %s" % contractor_id)
    if expected_version != contractor["version"]:
        fail(
            "ERR_STALE_HAUL_CONTRACTOR_VERSION",
            "expected_haul_contractor_version does not match the carrier's version",
        )
    overlapping_drafts = []
    for existing in ordered(list(db.settlement_statements.values())):
        if existing["haul_contractor_id"] != contractor_id:
            continue
        if to_date(existing["period_start"]) > period_end or to_date(existing["period_end"]) < period_start:
            continue
        if existing["status"] in ("DRAFT", "VOID"):
            if existing["status"] == "DRAFT":
                overlapping_drafts.append(existing)
            continue
        fail("ERR_PERIOD_OVERLAP", "another statement for this carrier covers an intersecting period")
    for draft in overlapping_drafts:
        draft["lines"] = []
        draft["gross_pay_cents"] = 0
        draft["reject_deduction_cents"] = 0
        draft["holdback_cents"] = 0
        draft["deduction_cents"] = 0
        draft["net_pay_cents"] = 0
        draft["status"] = "VOID"
        touch(draft)

    rec = new_record()
    rec.update(
        {
            "haul_contractor_id": contractor_id,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "status": "DRAFT",
            "compiled_by_user_id": caller.user_id,
            "approved_by_user_id": None,
            "compliance_score_at_compile": None,
            "holdback_pct": None,
            "lines": [],
            "gross_pay_cents": 0,
            "reject_deduction_cents": 0,
            "holdback_cents": 0,
            "deduction_cents": 0,
            "net_pay_cents": 0,
            "dispute_reason": None,
            "payment_reference": None,
        }
    )
    db.settlement_statements[rec["id"]] = rec
    compile_statement(rec)
    touch(contractor)
    return created(derive.settlement_statement_json(rec))


@bp.route("/settlement-statements/<id>", methods=["GET"])
@endpoint("PlatformAdmin", "SettlementAccountant", "SafetyOfficer", "HaulContractor")
def get_settlement_statement(caller, id):
    rec = db.settlement_statements.get(id)
    if rec is None:
        fail("ERR_SETTLEMENT_STATEMENT_NOT_FOUND", "no settlement statement %s" % id)
    return ok(derive.settlement_statement_json(rec))


@bp.route("/settlement-statements", methods=["GET"])
@endpoint("PlatformAdmin", "SettlementAccountant", "SafetyOfficer", "HaulContractor")
def list_settlement_statements(caller):
    records = ordered(list(db.settlement_statements.values()))
    for key in ("haul_contractor_id", "status"):
        value = request.args.get(key)
        if value is not None:
            records = [r for r in records if r[key] == value]
    return paginated(records, derive.settlement_statement_json)


@bp.route("/settlement-statements/<id>/submit", methods=["POST"])
@endpoint("SettlementAccountant")
def submit_settlement_statement(caller, id):
    rec = db.settlement_statements.get(id)
    if rec is None:
        fail("ERR_SETTLEMENT_STATEMENT_NOT_FOUND", "no settlement statement %s" % id)
    if rec["status"] not in ("DRAFT", "REVISED"):
        fail("ERR_INVALID_STATEMENT_STATE", "only a DRAFT or REVISED statement may be submitted")
    if not rec["lines"]:
        fail("ERR_NO_SETTLEABLE_LOADS", "the statement has no lines")
    rec["status"] = "SUBMITTED"
    touch(rec)
    for load_id in attached_load_ids(rec):
        load = db.loads.get(load_id)
        if load is not None and load["settlement_status"] == "ACCRUED":
            load["settlement_status"] = "STATEMENTED"
            touch(load)
    return ok(derive.settlement_statement_json(rec))


@bp.route("/settlement-statements/<id>/approve", methods=["POST"])
@endpoint("SettlementAccountant")
def approve_settlement_statement(caller, id):
    rec = db.settlement_statements.get(id)
    if rec is None:
        fail("ERR_SETTLEMENT_STATEMENT_NOT_FOUND", "no settlement statement %s" % id)
    # Segregation of duties shares the ownership rung, above the state rung.
    if caller.user_id == rec["compiled_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the compiler may not approve the statement")
    if rec["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATEMENT_STATE", "only a SUBMITTED statement may be approved")
    rec["status"] = "APPROVED"
    rec["approved_by_user_id"] = caller.user_id
    touch(rec)
    return ok(derive.settlement_statement_json(rec))


@bp.route("/settlement-statements/<id>/dispute", methods=["POST"])
@endpoint("SettlementAccountant", "HaulContractor")
def dispute_settlement_statement(caller, id):
    payload = body()
    dispute_reason = req_str(payload, "dispute_reason", 1, 1000)
    rec = db.settlement_statements.get(id)
    if rec is None:
        fail("ERR_SETTLEMENT_STATEMENT_NOT_FOUND", "no settlement statement %s" % id)
    if caller.role == "HaulContractor" and caller.user_id != rec["haul_contractor_id"]:
        fail("ERR_CONTRACTOR_NOT_OWNER", "the statement belongs to a different carrier")
    if rec["status"] not in ("SUBMITTED", "APPROVED"):
        fail("ERR_INVALID_STATEMENT_STATE", "only a SUBMITTED or APPROVED statement may be disputed")
    rec["status"] = "DISPUTED"
    rec["dispute_reason"] = dispute_reason
    rec["approved_by_user_id"] = None
    touch(rec)
    return ok(derive.settlement_statement_json(rec))


@bp.route("/settlement-statements/<id>/revise", methods=["POST"])
@endpoint("SettlementAccountant")
def revise_settlement_statement(caller, id):
    payload = body()
    req_str(payload, "note", min_len=0, max_len=1000, required=False)
    rec = db.settlement_statements.get(id)
    if rec is None:
        fail("ERR_SETTLEMENT_STATEMENT_NOT_FOUND", "no settlement statement %s" % id)
    if rec["status"] != "DISPUTED":
        fail("ERR_INVALID_STATEMENT_STATE", "only a DISPUTED statement may be revised")
    for load_id in attached_load_ids(rec):
        load = db.loads.get(load_id)
        if load is not None and load["settlement_status"] == "STATEMENTED":
            load["settlement_status"] = "ACCRUED"
            touch(load)
    rec["status"] = "REVISED"
    compile_statement(rec)
    touch(rec)
    return ok(derive.settlement_statement_json(rec))


@bp.route("/settlement-statements/<id>/pay", methods=["POST"])
@endpoint("SettlementAccountant")
def pay_settlement_statement(caller, id):
    payload = body()
    payment_reference = req_str(payload, "payment_reference", 1, 200)
    rec = db.settlement_statements.get(id)
    if rec is None:
        fail("ERR_SETTLEMENT_STATEMENT_NOT_FOUND", "no settlement statement %s" % id)
    if rec["status"] != "APPROVED":
        fail("ERR_INVALID_STATEMENT_STATE", "only an APPROVED statement may be paid")
    rec["status"] = "PAID"
    rec["payment_reference"] = payment_reference
    touch(rec)
    for load_id in attached_load_ids(rec):
        load = db.loads.get(load_id)
        if load is not None and load["settlement_status"] == "STATEMENTED":
            load["settlement_status"] = "PAID"
            touch(load)
    contractor = db.haul_contractors.get(rec["haul_contractor_id"])
    if contractor is not None:
        touch(contractor)
    return ok(derive.settlement_statement_json(rec))
