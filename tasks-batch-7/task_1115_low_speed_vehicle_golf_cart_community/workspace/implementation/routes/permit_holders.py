"""PermitHolder endpoints: self-registration, reads, eligibility state machine,
wallet deposits (OCC-guarded), revocation cascade."""
from flask import Blueprint

import db
from db import touch
from errors import err_not_found, err_invalid_state, err_stale_version
from middleware import (get_caller, require_role, check_holder_ownership,
                        check_holder_path_ownership)
from response import ok_object, ok_list
from services import calc, validate as v
from services import engine
from services.serializers import base_entity, permit_holder_view

bp = Blueprint("permit_holders", __name__)

READ_ROLES = ["PlatformAdmin", "CommunityAdmin", "Inspector", "EnforcementOfficer", "PermitHolder"]
LIST_ROLES = ["PlatformAdmin", "CommunityAdmin", "EnforcementOfficer"]
ADMIN_ROLES = ["CommunityAdmin"]


@bp.post("/api/permit-holders")
def create_permit_holder():
    data = v.body()
    # Stage 1: schema
    community_id = v.require_str(data, "community_id")
    full_name = v.require_str(data, "full_name")
    birth_date = v.require_date(data, "birth_date")
    license_class = v.require_enum(data, "driver_license_class", {"NONE", "STANDARD", "MOTORCYCLE"})
    # Stage 2: auth — Anonymous allowed here without headers
    caller = get_caller(allow_anonymous=True)
    # Stage 3: role
    require_role(caller, ["Anonymous", "CommunityAdmin"])
    # Stage 4: existence (body FKs in declared order)
    community = db.communities.get(community_id)
    if community is None:
        raise err_not_found("Community not found")

    h = base_entity()
    h.update({
        "community_id": community_id,
        "full_name": full_name,
        "birth_date": birth_date.isoformat(),
        "driver_license_class": license_class,
        "eligibility_status": "PENDING_VERIFICATION",
        "compliance_status": "GOOD_STANDING",
        "points_balance": 0,
        "wallet_balance_cents": 0,
    })
    db.permit_holders[h["id"]] = h
    return ok_object(permit_holder_view(h), 201)


@bp.get("/api/permit-holders/<hid>")
def get_permit_holder(hid):
    caller = get_caller()
    require_role(caller, READ_ROLES)
    check_holder_path_ownership(caller, hid)
    h = db.permit_holders.get(hid)
    if h is None:
        raise err_not_found("PermitHolder not found")
    return ok_object(permit_holder_view(h))


@bp.get("/api/permit-holders")
def list_permit_holders():
    caller = get_caller()
    require_role(caller, LIST_ROLES)
    limit, offset = v.pagination_args()
    community_id = None
    from flask import request
    if "community_id" in request.args:
        community_id = request.args.get("community_id")
        if not isinstance(community_id, str) or community_id == "":
            from errors import err_validation
            raise err_validation("community_id filter must be a string")
    rows = list(db.permit_holders.values())
    if community_id is not None:
        rows = [h for h in rows if h["community_id"] == community_id]
    rows = v.sorted_by_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return ok_list([permit_holder_view(h) for h in page], limit, offset, total)


def _load_holder_for_action(hid, caller):
    require_role(caller, ADMIN_ROLES)
    h = db.permit_holders.get(hid)
    if h is None:
        raise err_not_found("PermitHolder not found")
    return h


@bp.post("/api/permit-holders/<hid>/verify-eligibility")
def verify_eligibility(hid):
    caller = get_caller()
    h = _load_holder_for_action(hid, caller)
    # Stage 5: state
    if h["eligibility_status"] != "PENDING_VERIFICATION":
        raise err_invalid_state("Holder is not PENDING_VERIFICATION")
    # Stage 6: safety gates — age then license
    community = db.communities.get(h["community_id"])
    birth = db.parse_date(h["birth_date"])
    age = calc.age_years(birth, db.now().date())
    if age < community["min_driver_age"]:
        from errors import err_underage
        raise err_underage()
    if h["driver_license_class"] == "NONE":
        from errors import err_license
        raise err_license()
    h["eligibility_status"] = "ELIGIBLE"
    touch(h)
    return ok_object(permit_holder_view(h))


@bp.post("/api/permit-holders/<hid>/suspend")
def suspend_holder(hid):
    caller = get_caller()
    h = _load_holder_for_action(hid, caller)
    if h["eligibility_status"] != "ELIGIBLE":
        raise err_invalid_state("Holder is not ELIGIBLE")
    h["eligibility_status"] = "SUSPENDED"
    touch(h)
    return ok_object(permit_holder_view(h))


@bp.post("/api/permit-holders/<hid>/reinstate")
def reinstate_holder(hid):
    caller = get_caller()
    h = _load_holder_for_action(hid, caller)
    if h["eligibility_status"] != "SUSPENDED":
        raise err_invalid_state("Holder is not SUSPENDED")
    h["eligibility_status"] = "ELIGIBLE"
    touch(h)
    return ok_object(permit_holder_view(h))


@bp.post("/api/permit-holders/<hid>/revoke")
def revoke_holder(hid):
    caller = get_caller()
    h = _load_holder_for_action(hid, caller)
    if h["eligibility_status"] not in ("ELIGIBLE", "SUSPENDED"):
        raise err_invalid_state("Holder is not ELIGIBLE or SUSPENDED")
    h["eligibility_status"] = "REVOKED"
    touch(h)
    # Cascade: every registration in ACTIVE/RENEWAL_PENDING/SUSPENDED -> REVOKED,
    # each revocation revoking its ACTIVE route passes.
    for reg in list(db.registrations.values()):
        if reg["holder_id"] == h["id"] and reg["status"] in ("ACTIVE", "RENEWAL_PENDING", "SUSPENDED"):
            engine.revoke_registration(reg)
    return ok_object(permit_holder_view(h))


@bp.post("/api/permit-holders/<hid>/wallet/deposits")
def wallet_deposit(hid):
    data = v.body()
    # Stage 1: schema
    amount = v.require_int(data, "amount_cents", 1, None)
    if "expected_permit_holder_version" not in data:
        from errors import err_validation
        raise err_validation("Field 'expected_permit_holder_version' is required")
    expected = v.require_int(data, "expected_permit_holder_version")
    # Stage 2-3
    caller = get_caller()
    require_role(caller, ["PermitHolder"])
    check_holder_path_ownership(caller, hid)
    # Stage 4
    h = db.permit_holders.get(hid)
    if h is None:
        raise err_not_found("PermitHolder not found")
    # Stage 5: OCC
    if expected != h["version"]:
        raise err_stale_version()
    h["wallet_balance_cents"] += amount
    touch(h)
    return ok_object(permit_holder_view(h))
