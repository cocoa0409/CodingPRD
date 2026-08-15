"""Fine assessment endpoints: list, get, notice, pay, waive."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles
from response import ok, paginate
from services import core
from validation import parse_body, require_path_entity

bp = Blueprint("fines", __name__)


@bp.get("/v1/fine-assessments")
def list_fines():
    get_context()
    rows = list(store.fines.values())
    rows = paginate.filter(rows, "building_id")
    rows = paginate.filter(rows, "cycle_id")
    rows = paginate.filter(rows, "status")
    rows = paginate.filter(rows, "fine_type")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/v1/fine-assessments/<fine_id>")
def get_fine(fine_id):
    get_context()
    fine = require_path_entity(store.fines, fine_id)
    return ok(fine)


@bp.post("/v1/fine-assessments/<fine_id>/notice")
def notice_fine(fine_id):
    get_context()
    require_roles(["ComplianceOfficer"])
    fine = require_path_entity(store.fines, fine_id)
    if fine["status"] != "ASSESSED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only an ASSESSED fine can be noticed")
    fine["status"] = "NOTICED"
    fine["noticed_at"] = db.LOGICAL_CLOCK
    if fine["fine_type"] == "LATE_SUBMISSION":
        # FINAL variant: days from the effective deadline to verification,
        # or to notice when the report is still unverified.
        cycle = store.cycles.get(fine["cycle_id"])
        report = core.report_for(fine["building_id"], fine["cycle_id"])
        deadline = core.effective_deadline(fine["building_id"], cycle)
        end = report["verified_at"] if (report and report.get("verified_at")) else fine["noticed_at"]
        final_days = core.whole_days_between(end, deadline)
        fine["final_amount_cents"] = (min(final_days, cycle["late_fine_cap_days"])
                                      * cycle["late_fine_daily_rate_cents"])
    else:
        fine["final_amount_cents"] = fine["provisional_amount_cents"]
    db.touch(fine)
    building = store.buildings.get(fine["building_id"])
    if building is not None:
        core.recompute_owner_exposure(building["owner_id"])
    return ok(fine)


@bp.post("/v1/fine-assessments/<fine_id>/pay")
def pay_fine(fine_id):
    uid, _ = get_context()
    require_roles(["BuildingOwner"])
    fine = require_path_entity(store.fines, fine_id)
    building = store.buildings.get(fine["building_id"])
    if building is None or building["owner_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "BuildingOwner does not own this fine's building")
    body = parse_body({"paid_amount_cents": ("integer", True, None)}, allow_empty=False)
    if fine["status"] != "NOTICED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a NOTICED fine can be paid")
    if body["paid_amount_cents"] != fine["final_amount_cents"]:
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH", 422,
                       "paid_amount_cents must equal final_amount_cents exactly")
    fine["status"] = "PAID"
    fine["paid_at"] = db.LOGICAL_CLOCK
    db.touch(fine)
    core.recompute_owner_exposure(building["owner_id"])
    return ok(fine)


@bp.post("/v1/fine-assessments/<fine_id>/waive")
def waive_fine(fine_id):
    get_context()
    require_roles(["ComplianceOfficer"])
    fine = require_path_entity(store.fines, fine_id)
    body = parse_body({"waive_reason": ("string", True, None)}, allow_empty=False)
    if fine["status"] not in ("ASSESSED", "NOTICED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only an ASSESSED or NOTICED fine can be waived")
    fine["status"] = "WAIVED"
    fine["waive_reason"] = body["waive_reason"]
    db.touch(fine)
    building = store.buildings.get(fine["building_id"])
    if building is not None:
        core.recompute_owner_exposure(building["owner_id"])
    return ok(fine)
