"""Members: registration, waiver, freeze/unfreeze/withdraw cascades (PRD §3.3)."""
from flask import Blueprint, request

from db import db
from errors import (
    err, ERR_NOT_FOUND, ERR_FK_NOT_FOUND, ERR_INVALID_REQUEST, ERR_DUPLICATE,
    ERR_INVALID_STATE,
)
from middleware import (
    get_identity, require_roles, ROLE_FRONTDESK, ROLE_INSTRUCTOR, ROLE_CHIEF, ROLE_MEMBER,
)
from response import success
from common import (
    get_json_body, require_fields, require_email, parse_pagination, paginate,
    sort_by_created, parse_iso8601,
)
from services.serialize import view, view_list
from services.access import require_version_field, check_occ
from services import domain

bp = Blueprint("members", __name__)
ALL_ROLES = [ROLE_FRONTDESK, ROLE_INSTRUCTOR, ROLE_CHIEF, ROLE_MEMBER]


@bp.post("/dojo/members")
def create_member():
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK])
    body = get_json_body()
    require_fields(body, ["full_name", "email", "date_of_birth"])
    if not isinstance(body["full_name"], str) or not (1 <= len(body["full_name"]) <= 120):
        raise err(ERR_INVALID_REQUEST, "full_name must be 1..120 chars.")
    require_email(body["email"], "email")
    parse_iso8601(body["date_of_birth"])  # validate ISO 8601

    family_id = body.get("family_id", None)
    waiver_signed = body.get("waiver_signed", False)
    if not isinstance(waiver_signed, bool):
        raise err(ERR_INVALID_REQUEST, "waiver_signed must be a boolean.")

    # FK existence (priority 4) before uniqueness (priority 6).
    if family_id is not None:
        if family_id not in db.families:
            raise err(ERR_FK_NOT_FOUND, "family_id references a non-existent family.")

    # Email global uniqueness across members (priority 6).
    for m in db.members.values():
        if m["email"] == body["email"]:
            raise err(ERR_DUPLICATE, "Member email already exists.")

    now = db.now_iso()
    mid = db.new_id()
    member = {
        "id": mid,
        "family_id": family_id,
        "full_name": body["full_name"],
        "email": body["email"],
        "date_of_birth": body["date_of_birth"],
        "account_status": "ACTIVE",
        "waiver_signed": waiver_signed,
        "outstanding_balance_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.members[mid] = member
    if family_id is not None:
        domain.recompute_family_active_member_count(family_id)
    return success(view(member), 201)


@bp.get("/dojo/members/<mid>")
def get_member(mid):
    user_id, role = get_identity()
    require_roles(role, ALL_ROLES)
    member = db.members.get(mid)
    if member is None:
        raise err(ERR_NOT_FOUND, "Member not found.")
    # A Member may only read their own member record.
    if role == ROLE_MEMBER and mid != user_id:
        from errors import ERR_UNAUTHORIZED
        raise err(ERR_UNAUTHORIZED, "Member may only read their own record.")
    return success(view(member), 200)


@bp.get("/dojo/members")
def list_members():
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK])
    limit, offset = parse_pagination()
    family_id = request.args.get("family_id")
    account_status = request.args.get("account_status")
    items = []
    for m in db.members.values():
        if family_id is not None and m.get("family_id") != family_id:
            continue
        if account_status is not None and m["account_status"] != account_status:
            continue
        items.append(m)
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(view_list(page), 200, pagination=meta)


@bp.post("/dojo/members/<mid>/sign-waiver")
def sign_waiver(mid):
    user_id, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK, ROLE_MEMBER])
    member = db.members.get(mid)
    if member is None:
        raise err(ERR_NOT_FOUND, "Member not found.")
    if role == ROLE_MEMBER and mid != user_id:
        from errors import ERR_UNAUTHORIZED
        raise err(ERR_UNAUTHORIZED, "Member may only sign their own waiver.")
    member["waiver_signed"] = True
    domain.touch(member)
    return success(view(member), 200)


def _occ_member(mid, allowed_states):
    """Resolve member, OCC-check, and verify current state is in allowed_states.
    Returns the member."""
    member = db.members.get(mid)
    if member is None:
        raise err(ERR_NOT_FOUND, "Member not found.")
    body = get_json_body()
    supplied = require_version_field(body, "expected_member_version")
    check_occ(supplied, member["version"])
    if member["account_status"] not in allowed_states:
        raise err(ERR_INVALID_STATE, "Member not in a valid state for this transition.")
    return member


@bp.post("/dojo/members/<mid>/freeze")
def freeze_member(mid):
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK])
    member = _occ_member(mid, ["ACTIVE"])
    member["account_status"] = "FROZEN"
    # cascade ACTIVE enrollments -> ON_HOLD
    for enr in db.enrollments.values():
        if enr["member_id"] == mid and enr["status"] == "ACTIVE":
            enr["status"] = "ON_HOLD"
            domain.touch(enr)
    domain.touch(member)  # version bump
    domain.recompute_family_active_member_count(member.get("family_id"))
    return success(view(member), 200)


@bp.post("/dojo/members/<mid>/unfreeze")
def unfreeze_member(mid):
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK])
    member = _occ_member(mid, ["FROZEN"])
    member["account_status"] = "ACTIVE"
    for enr in db.enrollments.values():
        if enr["member_id"] == mid and enr["status"] == "ON_HOLD":
            enr["status"] = "ACTIVE"
            domain.touch(enr)
    domain.touch(member)
    return success(view(member), 200)


@bp.post("/dojo/members/<mid>/withdraw")
def withdraw_member(mid):
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK])
    member = _occ_member(mid, ["ACTIVE", "FROZEN", "SUSPENDED"])
    member["account_status"] = "WITHDRAWN"
    # drop non-terminal enrollments
    for enr in db.enrollments.values():
        if enr["member_id"] == mid and enr["status"] in ("ACTIVE", "ON_HOLD"):
            enr["status"] = "DROPPED"
            domain.touch(enr)
    # terminate ACTIVE/PAST_DUE contracts, BUYOUT if term unmet
    for contract in db.contracts.values():
        if contract["member_id"] == mid and contract["status"] in ("ACTIVE", "PAST_DUE"):
            contract["status"] = "TERMINATED"
            domain.touch(contract)
            if contract["months_billed"] < contract["term_months"]:
                program = db.programs.get(contract["program_id"])
                remaining = contract["term_months"] - contract["months_billed"]
                monthly = domain.recurring_tuition_amount(program, contract["locked_family_discount_pct"])
                amount = domain.buyout_amount(remaining, monthly)
                domain.make_invoice(mid, "BUYOUT", amount, contract_id=contract["id"])
    domain.touch(member)  # version bump
    domain.recompute_family_active_member_count(member.get("family_id"))
    # withdraw raises balance via buyout invoices; reconcile (member already
    # WITHDRAWN so suspend/unsuspend cascades are no-ops on a terminal member).
    member["outstanding_balance_cents"] = domain.member_outstanding_balance(mid)
    return success(view(member), 200)
