"""Radiological work permits, the dose ledger and ALARA posture (PRD 3.7)."""
from flask import Blueprint, request

import calc
import lookup
import projections
from auth import ALL_ROLES, authorize
from calc import dec, q2
from db import all_rows, create_row, store, touch
from errors import api_error
from response import ok, paginated, parse_pagination
from serializers import serialize
from validators import F, body

bp = Blueprint("rwp", __name__)


@bp.route("/work-orders/<work_order_id>/rwps", methods=["POST"])
@authorize("RadProtectionPlanner")
def draft_rwp(work_order_id):
    work_order = lookup.work_order(work_order_id)
    payload = body([
        F("rad_area_id", "str"),
        F("worker_count", "int", ge=1),
        F("shielding_factor", "num", ge=0, le="0.95"),
        F("planned_start_offset_hours", "num", ge=0),
        F("planned_duration_hours", "num", gt=0),
    ])
    area = lookup.rad_area(payload["rad_area_id"])

    per_worker, collective, contingency, committed, alara_required = calc.rwp_doses(
        area["dose_rate_mrem_per_hr"], payload["planned_duration_hours"],
        payload["shielding_factor"], payload["worker_count"])

    permit = create_row(store.rwps, {
        "outage_id": work_order["outage_id"],
        "work_order_id": work_order["id"],
        "rad_area_id": area["id"],
        "worker_count": payload["worker_count"],
        "shielding_factor": payload["shielding_factor"],
        "planned_start_offset_hours": q2(payload["planned_start_offset_hours"]),
        "planned_duration_hours": q2(payload["planned_duration_hours"]),
        "per_worker_dose_mrem": per_worker,
        "collective_dose_mrem": collective,
        "contingency_dose_mrem": contingency,
        "committed_dose_mrem": committed,
        "alara_review_required": alara_required,
        "alara_review_reference": None,
        "actual_dose_mrem": None,
        "status": "DRAFT",
        "void_reason": None,
    })
    return ok(serialize(permit), 201)


@bp.route("/rwps/<row_id>", methods=["GET"])
@authorize(*ALL_ROLES)
def get_rwp(row_id):
    return ok(serialize(lookup.rwp(row_id)))


@bp.route("/rwps", methods=["GET"])
@authorize(*ALL_ROLES)
def list_rwps():
    limit, offset = parse_pagination(request.args)
    rows = all_rows(store.rwps)
    for key in ("outage_id", "work_order_id", "rad_area_id", "status"):
        wanted = request.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r[key] == wanted]
    return paginated(rows, limit, offset, serialize)


def _buffered_window(permit, area):
    start = dec(permit["planned_start_offset_hours"])
    end = (start + dec(permit["planned_duration_hours"])
           + dec(area["survey_buffer_hours"]))
    return start, end


def _check_window(permit, area):
    """Half-open windows: exact adjacency is admitted."""
    start, end = _buffered_window(permit, area)
    for other in all_rows(store.rwps):
        if other["id"] == permit["id"]:
            continue
        if other["rad_area_id"] != permit["rad_area_id"]:
            continue
        if other["status"] != "APPROVED":
            continue
        other_start, other_end = _buffered_window(other, area)
        if start < other_end and other_start < end:
            raise api_error("ERR_RAD_AREA_WINDOW_CONFLICT",
                            "The buffered window overlaps another approved permit.")


@bp.route("/rwps/<row_id>/approve", methods=["POST"])
@authorize("RadProtectionManager")
def approve_rwp(row_id):
    permit = lookup.rwp(row_id)
    payload = body([F("alara_review_reference", "str", required=False, default=None,
                      nullable=True, min_len=1, max_len=64)])
    if permit["status"] != "DRAFT":
        raise api_error("ERR_RWP_STATE_INVALID",
                        "Approval requires the permit to be in DRAFT.")
    outage = store.outages[permit["outage_id"]]
    if outage["status"] not in ("SCOPE_LOCKED", "EXECUTION"):
        raise api_error("ERR_OUTAGE_STATE_INVALID",
                        "Committing dose requires the outage to be SCOPE_LOCKED or EXECUTION.")
    work_order = store.work_orders[permit["work_order_id"]]
    if work_order["status"] != "APPROVED":
        raise api_error("ERR_WORK_ORDER_NOT_APPROVED",
                        "The covering work order is not APPROVED.")
    if outage["alara_posture"] == "SUSPENDED":
        raise api_error("ERR_ALARA_POSTURE_SUSPENDED",
                        "The outage dose posture is suspended.")
    if permit["alara_review_required"] and payload["alara_review_reference"] is None:
        raise api_error("ERR_ALARA_REVIEW_REQUIRED",
                        "This permit requires an ALARA review reference.")
    area = store.rad_areas[permit["rad_area_id"]]
    _check_window(permit, area)
    if dec(permit["committed_dose_mrem"]) > dec(outage["dose_budget_remaining_mrem"]):
        raise api_error("ERR_DOSE_BUDGET_EXCEEDED",
                        "The permit's committed dose exceeds the remaining dose budget.")

    previous_posture = outage["alara_posture"]
    if payload["alara_review_reference"] is not None:
        permit["alara_review_reference"] = payload["alara_review_reference"]
    permit["status"] = "APPROVED"
    touch(permit)

    projections.append_dose_transaction(permit, "COMMIT",
                                        permit["committed_dose_mrem"], "RWP_APPROVED")
    projections.recompute_dose(outage, previous_posture)
    touch(outage)
    return ok(serialize(permit))


@bp.route("/rwps/<row_id>/close", methods=["POST"])
@authorize("RadProtectionPlanner", "RadProtectionManager")
def close_rwp(row_id):
    permit = lookup.rwp(row_id)
    payload = body([F("actual_dose_mrem", "num", ge=0)])
    if permit["status"] != "APPROVED":
        raise api_error("ERR_RWP_STATE_INVALID",
                        "Closing requires the permit to be in APPROVED.")
    outage = store.outages[permit["outage_id"]]
    if outage["status"] not in ("EXECUTION", "STARTUP"):
        raise api_error("ERR_OUTAGE_STATE_INVALID",
                        "Closing requires the outage to be in EXECUTION or STARTUP.")

    previous_posture = outage["alara_posture"]
    actual = q2(payload["actual_dose_mrem"])
    committed = dec(permit["committed_dose_mrem"])
    permit["actual_dose_mrem"] = actual
    permit["status"] = "CLOSED"
    touch(permit)

    if actual < committed:
        projections.append_dose_transaction(permit, "RELEASE", committed - actual,
                                           "RWP_CLOSED_UNDERRUN")
    elif actual > committed:
        projections.append_dose_transaction(permit, "COMMIT", actual - committed,
                                           "RWP_CLOSED_OVERRUN")

    projections.recompute_dose(outage, previous_posture)
    touch(outage)
    return ok(serialize(permit))


@bp.route("/rwps/<row_id>/void", methods=["POST"])
@authorize("RadProtectionManager")
def void_rwp(row_id):
    permit = lookup.rwp(row_id)
    payload = body([F("void_reason", "str", min_len=1, max_len=500)])
    if permit["status"] not in ("DRAFT", "HELD_FOR_ALARA", "APPROVED"):
        raise api_error("ERR_RWP_STATE_INVALID",
                        "Voiding requires DRAFT, HELD_FOR_ALARA or APPROVED.")
    outage = store.outages[permit["outage_id"]]
    previous_posture = outage["alara_posture"]
    was_approved = permit["status"] == "APPROVED"

    permit["void_reason"] = payload["void_reason"]
    permit["status"] = "VOIDED"
    touch(permit)

    if was_approved:
        projections.append_dose_transaction(permit, "RELEASE",
                                            permit["committed_dose_mrem"],
                                            "RWP_VOIDED")
        projections.recompute_dose(outage, previous_posture)
        touch(outage)
    return ok(serialize(permit))


@bp.route("/rwps/<row_id>/dose-transactions", methods=["GET"])
@authorize(*ALL_ROLES)
def list_dose_transactions(row_id):
    permit = lookup.rwp(row_id)
    limit, offset = parse_pagination(request.args)
    rows = projections.dose_transactions_of_rwp(permit["id"])
    wanted = request.args.get("direction")
    if wanted is not None:
        rows = [r for r in rows if r["direction"] == wanted]
    return paginated(rows, limit, offset, serialize)
