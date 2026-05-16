"""FairHearing routes (PRD §3.6)."""

from flask import Blueprint

from core.auth import require_roles
from core.clock import CLOCK
from core.envelope import success_object
from core.errors import raise_error
from core.store import STORE, lock
from core.timeutils import parse_iso
from services.mutations import bump
from services.projections import project_fair_hearing


bp = Blueprint("fair_hearings", __name__)


@bp.route("/fair-hearings/<fair_hearing_id>", methods=["GET"])
@require_roles("IntakeWorker", "EligibilityCaseworker", "AppealsOfficer", "PolicyAdmin")
def get_fair_hearing(fair_hearing_id):
    row = STORE.fair_hearings.get(fair_hearing_id)
    if row is None:
        raise_error("ERR_NOT_FOUND", "FairHearing not found")
    return success_object(project_fair_hearing(row))


@bp.route("/fair-hearings/<fair_hearing_id>/hold", methods=["POST"])
@require_roles("AppealsOfficer")
def hold_fair_hearing(fair_hearing_id):
    row = STORE.fair_hearings.get(fair_hearing_id)
    if row is None:
        raise_error("ERR_NOT_FOUND", "FairHearing not found")
    if row["status"] != "SCHEDULED":
        raise_error("ERR_INVALID_STATE", "FairHearing must be SCHEDULED to hold")
    try:
        start_dt = parse_iso(row["scheduled_start"], "scheduled_start")
    except Exception:
        raise_error("ERR_INVALID_REQUEST", "Invalid scheduled_start")
    if CLOCK.now() < start_dt:
        raise_error("ERR_HEARING_NOT_DUE", "clock_now is before scheduled_start")
    with lock():
        row["status"] = "HELD"
        bump(row)
        appeal = STORE.appeals.get(row["appeal_id"])
        if appeal is not None and appeal["status"] == "HEARING_SCHEDULED":
            appeal["status"] = "UNDER_REVIEW"
            bump(appeal)
    return success_object(project_fair_hearing(row))
