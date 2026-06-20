"""Policyholder endpoints (PRD §3.1)."""
from flask import Blueprint

from db import STORE, new_id, common_fields
from middleware import authenticate, authorize
from response import object_response
from services import common, serialize, lookup

bp = Blueprint("policyholders", __name__)


@bp.route("/policyholders", methods=["POST"])
def create_policyholder():
    caller = authenticate()
    authorize(caller, ["Underwriter"])
    body = common.get_json_body()
    full_name = common.require_str(body, "full_name")
    state_code = common.require_str(body, "state_code")
    date_of_birth = common.require_str(body, "date_of_birth")
    medicaid = common.optional_bool(body, "medicaid_state_eligible", False)

    rid = new_id()
    rec = {
        "id": rid,
        "full_name": full_name,
        "state_code": state_code,
        "date_of_birth": date_of_birth,
        "medicaid_state_eligible": medicaid,
    }
    rec.update(common_fields(STORE.next_seq()))
    STORE.policyholders[rid] = rec
    return object_response(serialize.policyholder(rec), 201)


@bp.route("/policyholders/<rid>", methods=["GET"])
def get_policyholder(rid):
    caller = authenticate()
    authorize(caller, ["Underwriter", "ClaimsExaminer", "Policyholder"])
    rec = lookup.policyholder_or_404(rid)
    return object_response(serialize.policyholder(rec), 200)
