"""Care-plan endpoints (PRD §3.4)."""
from flask import Blueprint, request

import errors
from db import STORE, new_id, common_fields, touch
from middleware import authenticate, authorize
from response import object_response, array_response
from services import common, serialize, lookup, calc

bp = Blueprint("care_plans", __name__)

CARE_SETTINGS = {"NURSING_HOME", "ASSISTED_LIVING", "HOME_HEALTH", "ADULT_DAY", "INFORMAL"}


@bp.route("/care-plans", methods=["POST"])
def create_care_plan():
    caller = authenticate()
    authorize(caller, ["CareAssessor"])
    body = common.get_json_body()
    policy_id = common.require_str(body, "policy_id")
    provider_id = common.require_str(body, "provider_id")
    care_setting = common.require_enum(body, "care_setting", CARE_SETTINGS)
    lookup.policy_or_404(policy_id)
    lookup.provider_or_404(provider_id)

    rid = new_id()
    rec = {
        "id": rid,
        "policy_id": policy_id,
        "provider_id": provider_id,
        "care_setting": care_setting,
        "authored_by_id": caller.user_id,
        "status": "DRAFT",
    }
    rec.update(common_fields(STORE.next_seq()))
    STORE.care_plans[rid] = rec
    return object_response(serialize.care_plan(rec), 201)


@bp.route("/care-plans", methods=["GET"])
def list_care_plans():
    caller = authenticate()
    authorize(caller, ["CareAssessor", "ClaimsExaminer", "Underwriter"])
    records = list(STORE.care_plans.values())
    policy_id = request.args.get("policy_id")
    provider_id = request.args.get("provider_id")
    if policy_id is not None:
        records = [r for r in records if r["policy_id"] == policy_id]
    if provider_id is not None:
        records = [r for r in records if r["provider_id"] == provider_id]
    records = lookup.sorted_by_created(records)
    page, limit, offset, total = common.paginate(records)
    return array_response([serialize.care_plan(r) for r in page], limit, offset, total)


@bp.route("/care-plans/<rid>", methods=["GET"])
def get_care_plan(rid):
    caller = authenticate()
    authorize(caller, ["CareAssessor", "ClaimsExaminer", "Underwriter"])
    rec = lookup.care_plan_or_404(rid)
    return object_response(serialize.care_plan(rec), 200)


@bp.route("/care-plans/<rid>/activate", methods=["POST"])
def activate_care_plan(rid):
    caller = authenticate()
    authorize(caller, ["CareAssessor"])
    cp = lookup.care_plan_or_404(rid)
    if cp["status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Care plan not DRAFT")

    provider = STORE.providers[cp["provider_id"]]
    # Business-referential checks after state: eligibility + setting/type match.
    if provider["eligibility_status"] != "ELIGIBLE":
        raise errors.err(errors.ERR_PROVIDER_NOT_ELIGIBLE, "Provider not eligible")
    expected_type = calc.SETTING_TO_PROVIDER_TYPE.get(cp["care_setting"])
    if expected_type != provider["provider_type"]:
        raise errors.err(errors.ERR_CARE_SETTING_MISMATCH, "Care setting incompatible")

    # Supersede any other ACTIVE plan for the same policy.
    for other in STORE.care_plans.values():
        if (other["id"] != rid and other["policy_id"] == cp["policy_id"]
                and other["status"] == "ACTIVE"):
            other["status"] = "SUPERSEDED"
            touch(other)

    cp["status"] = "ACTIVE"
    touch(cp)
    return object_response(serialize.care_plan(cp), 200)


@bp.route("/care-plans/<rid>/close", methods=["POST"])
def close_care_plan(rid):
    caller = authenticate()
    authorize(caller, ["CareAssessor"])
    cp = lookup.care_plan_or_404(rid)
    if cp["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Care plan not ACTIVE")
    cp["status"] = "CLOSED"
    touch(cp)
    return object_response(serialize.care_plan(cp), 200)
