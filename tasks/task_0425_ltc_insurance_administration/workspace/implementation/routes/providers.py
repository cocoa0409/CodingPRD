"""Provider endpoints and the suspend cascade (PRD §3.4, §3.8)."""
from flask import Blueprint

import errors
from db import STORE, new_id, common_fields, touch
from middleware import authenticate, authorize
from response import object_response
from services import common, serialize, lookup, core

bp = Blueprint("providers", __name__)

PROVIDER_TYPES = {
    "NURSING_HOME", "ASSISTED_LIVING", "HOME_HEALTH_AGENCY",
    "ADULT_DAY_CARE", "INFORMAL_CAREGIVER",
}


@bp.route("/providers", methods=["POST"])
def create_provider():
    caller = authenticate()
    authorize(caller, ["CareAssessor"])
    body = common.get_json_body()
    name = common.require_str(body, "name")
    provider_type = common.require_enum(body, "provider_type", PROVIDER_TYPES)
    state_code = common.require_str(body, "state_code")
    license_active = common.optional_bool(body, "license_active", True)

    rid = new_id()
    rec = {
        "id": rid,
        "name": name,
        "provider_type": provider_type,
        "state_code": state_code,
        "license_active": license_active,
        "eligibility_status": "PENDING",
    }
    rec.update(common_fields(STORE.next_seq()))
    STORE.providers[rid] = rec
    return object_response(serialize.provider(rec), 201)


@bp.route("/providers/<rid>", methods=["GET"])
def get_provider(rid):
    caller = authenticate()
    authorize(caller, ["CareAssessor", "ClaimsExaminer", "Underwriter"])
    rec = lookup.provider_or_404(rid)
    return object_response(serialize.provider(rec), 200)


@bp.route("/providers/<rid>/certify", methods=["POST"])
def certify_provider(rid):
    caller = authenticate()
    authorize(caller, ["CareAssessor"])
    prov = lookup.provider_or_404(rid)
    if prov["eligibility_status"] not in ("PENDING", "SUSPENDED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Provider not PENDING/SUSPENDED")
    if prov["license_active"] is not True:
        raise errors.err(errors.ERR_PROVIDER_LICENSE_INACTIVE, "License inactive")
    prov["eligibility_status"] = "ELIGIBLE"
    touch(prov)
    return object_response(serialize.provider(prov), 200)


@bp.route("/providers/<rid>/reject", methods=["POST"])
def reject_provider(rid):
    caller = authenticate()
    authorize(caller, ["CareAssessor"])
    prov = lookup.provider_or_404(rid)
    if prov["eligibility_status"] != "PENDING":
        raise errors.err(errors.ERR_INVALID_STATE, "Provider not PENDING")
    prov["eligibility_status"] = "INELIGIBLE"
    touch(prov)
    return object_response(serialize.provider(prov), 200)


@bp.route("/providers/<rid>/suspend", methods=["POST"])
def suspend_provider(rid):
    caller = authenticate()
    authorize(caller, ["CareAssessor"])
    prov = lookup.provider_or_404(rid)
    if prov["eligibility_status"] != "ELIGIBLE":
        raise errors.err(errors.ERR_INVALID_STATE, "Provider not ELIGIBLE")
    prov["eligibility_status"] = "SUSPENDED"
    touch(prov)

    # Cascade: ACTIVE care plans of this provider -> CLOSED; their non-terminal
    # claims -> VOID (depth-3, PRD §3.8).
    closed_plan_ids = []
    for cp in STORE.care_plans.values():
        if cp["provider_id"] == rid and cp["status"] == "ACTIVE":
            cp["status"] = "CLOSED"
            touch(cp)
            closed_plan_ids.append(cp["id"])

    if closed_plan_ids:
        plan_set = set(closed_plan_ids)
        for claim in STORE.claims.values():
            if claim["care_plan_id"] in plan_set and claim["status"] in core.NON_TERMINAL_CLAIM:
                claim["status"] = "VOID"
                touch(claim)

    return object_response(serialize.provider(prov), 200)
