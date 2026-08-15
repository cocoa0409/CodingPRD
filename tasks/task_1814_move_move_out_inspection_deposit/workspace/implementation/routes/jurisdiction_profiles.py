"""JurisdictionProfile endpoints (PRD §2.10, §3.1)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_DUPLICATE_JURISDICTION_CODE
from middleware import authorized
from response import success_object
from routes.helpers import get_one
from services.core import new_record, public
from validate import get_body, req_bool, req_enum, req_int, req_str

bp = Blueprint("jurisdiction_profiles", __name__)


@bp.post("/pm/jurisdiction-profiles")
def create_jurisdiction_profile():
    authorized(["ManagerAdmin"])
    body = get_body()
    fields = {
        "code": req_str(body, "code"),
        "deposit_return_deadline_days": req_int(body, "deposit_return_deadline_days", non_negative=True),
        "dispute_window_days": req_int(body, "dispute_window_days", non_negative=True),
        "interest_required": req_bool(body, "interest_required"),
        "annual_interest_rate_bp": req_int(body, "annual_interest_rate_bp", non_negative=True),
        "interest_basis": req_enum(body, "interest_basis", ("ACTUAL_DAYS", "WHOLE_YEARS")),
        "stale_check_days": req_int(body, "stale_check_days", non_negative=True),
        "small_claims_cap_cents": req_int(body, "small_claims_cap_cents", non_negative=True),
        "bad_faith_multiplier": req_int(body, "bad_faith_multiplier", non_negative=True),
        "lock_change_allowed": req_bool(body, "lock_change_allowed"),
        "allow_actual_cost_charge": req_bool(body, "allow_actual_cost_charge"),
    }
    # Priority 8: uniqueness of the jurisdiction code.
    if any(p["code"] == fields["code"] for p in db["jurisdiction_profiles"].values()):
        raise_error(ERR_DUPLICATE_JURISDICTION_CODE,
                    f"jurisdiction code already exists: {fields['code']}")
    rec = new_record("jurisdiction_profiles", fields)
    return success_object(public(rec), status=201)


@bp.get("/pm/jurisdiction-profiles/<rid>")
def get_jurisdiction_profile(rid):
    return get_one("jurisdiction_profiles", rid)
