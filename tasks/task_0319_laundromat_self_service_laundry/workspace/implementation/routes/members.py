"""Member, Reload, redeem, and member-scoped list endpoints (PRD §3.4)."""
from flask import Blueprint, request

from db import db, stamp_create, touch
from errors import (
    err,
    ERR_DUPLICATE_PHONE,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_MEMBER_NOT_ACTIVE,
    ERR_INSUFFICIENT_POINTS,
    ERR_INVALID_STATE,
)
from middleware import get_identity, require_roles
from response import object_response, array_response
from services.common import (
    get_body,
    require_fields,
    require_int,
    require_str,
    require_enum,
    parse_pagination,
    paginate,
    get_or_404,
    require_active_plan,
    write_ledger,
    open_shift_for,
)
from services.calc import reload_bonus_cents
from services.shift_calc import recompute_and_touch
from services.serialize import view

bp = Blueprint("members", __name__)

MEMBER_STATUSES = {"ACTIVE", "SUSPENDED", "CLOSED"}


def _phone_in_use(phone, exclude_id=None):
    for m in db.members.values():
        if m["id"] == exclude_id:
            continue
        if m["status"] != "CLOSED" and m["phone"] == phone:
            return True
    return False


@bp.post("/members")
def create_member():
    _, role = get_identity()
    require_roles(role, {"Manager", "Attendant"})
    body = get_body()
    require_fields(body, ["full_name", "phone", "card_token"])
    full_name = require_str(body["full_name"], "full_name")
    phone = require_str(body["phone"], "phone")
    card_token = require_str(body["card_token"], "card_token")
    with db.lock:
        # ERR_DUPLICATE_PHONE: phone unique among non-CLOSED members.
        if _phone_in_use(phone):
            raise err(ERR_DUPLICATE_PHONE, "Phone already in use by a non-closed member")
        member = {
            "full_name": full_name,
            "phone": phone,
            "card_token": card_token,
            "wallet_cents": 0,
            "loyalty_points": 0,
            "free_wash_credits": 0,
            "lifetime_spend_cents": 0,
            "status": "ACTIVE",
        }
        stamp_create(member)
        db.members[member["id"]] = member
    return object_response(view(member), status=201)


@bp.get("/members")
def list_members():
    _, role = get_identity()
    require_roles(role, {"Manager", "Attendant"})
    limit, offset = parse_pagination()
    status = request.args.get("status")
    phone = request.args.get("phone")
    items = list(db.members.values())
    if status is not None:
        items = [m for m in items if m["status"] == status]
    if phone is not None:
        items = [m for m in items if m["phone"] == phone]
    window, total = paginate(items, limit, offset)
    return array_response([view(m) for m in window], limit, offset, total)


@bp.get("/members/<member_id>")
def get_member(member_id):
    _, role = get_identity()
    require_roles(role, {"Manager", "Attendant", "Member"})
    member = get_or_404(db.members, member_id, "Member")
    return object_response(view(member))


@bp.patch("/members/<member_id>")
def update_member(member_id):
    _, role = get_identity()
    require_roles(role, {"Manager"})
    with db.lock:
        member = get_or_404(db.members, member_id, "Member")
        body = get_body()
        new_status = body.get("status")
        new_name = body.get("full_name")
        new_phone = body.get("phone")
        if new_status is not None:
            require_enum(new_status, MEMBER_STATUSES, "status")
        if new_name is not None:
            require_str(new_name, "full_name")
        if new_phone is not None:
            require_str(new_phone, "phone")
            # Maintain phone uniqueness among non-CLOSED members.
            target_status = new_status if new_status is not None else member["status"]
            if target_status != "CLOSED" and _phone_in_use(new_phone, exclude_id=member_id):
                raise err(ERR_DUPLICATE_PHONE, "Phone already in use by a non-closed member")
        if new_status is not None:
            member["status"] = new_status
        if new_name is not None:
            member["full_name"] = new_name
        if new_phone is not None:
            member["phone"] = new_phone
        touch(member)
    return object_response(view(member))


@bp.post("/members/<member_id>/reloads")
def create_reload(member_id):
    user_id, role = get_identity()
    require_roles(role, {"Member", "Attendant"})
    with db.lock:
        member = get_or_404(db.members, member_id, "Member")
        body = get_body()
        require_fields(body, ["tender", "principal_cents"])
        tender = body["tender"]
        require_enum(tender, {"CASH", "CARD", "APP"}, "tender")
        principal = require_int(body["principal_cents"], "principal_cents", gt=0)
        # Ownership (priority 5): a Member may reload only their own wallet.
        if role == "Member" and user_id != member_id:
            raise err(ERR_FORBIDDEN, "Member may only reload their own wallet")
        # Pricing requires an ACTIVE plan.
        plan = require_active_plan()
        # Member must be ACTIVE.
        if member["status"] != "ACTIVE":
            raise err(ERR_MEMBER_NOT_ACTIVE, "Member is not ACTIVE")

        bonus, credited = reload_bonus_cents(plan, principal)

        # Shift stamping: CASH reload taken by an Attendant with an OPEN shift.
        shift_id = None
        if tender == "CASH" and role == "Attendant":
            shift = open_shift_for(user_id)
            if shift is not None:
                shift_id = shift["id"]

        reload_txn = {
            "member_id": member_id,
            "shift_id": shift_id,
            "tender": tender,
            "principal_cents": principal,
            "bonus_cents": bonus,
            "credited_cents": credited,
            "status": "POSTED",
        }
        stamp_create(reload_txn)
        db.reloads[reload_txn["id"]] = reload_txn

        member["wallet_cents"] += credited
        touch(member)

        if shift_id is not None:
            recompute_and_touch(db.shifts[shift_id])

    return object_response(view(reload_txn), status=201)


@bp.get("/members/<member_id>/reloads")
def list_member_reloads(member_id):
    _, role = get_identity()
    require_roles(role, {"Manager", "Attendant", "Member"})
    get_or_404(db.members, member_id, "Member")
    limit, offset = parse_pagination()
    items = [r for r in db.reloads.values() if r["member_id"] == member_id]
    window, total = paginate(items, limit, offset)
    return array_response([view(r) for r in window], limit, offset, total)


@bp.get("/members/<member_id>/vends")
def list_member_vends(member_id):
    _, role = get_identity()
    require_roles(role, {"Manager", "Attendant", "Member"})
    get_or_404(db.members, member_id, "Member")
    limit, offset = parse_pagination()
    items = [v for v in db.vends.values() if v.get("member_id") == member_id]
    window, total = paginate(items, limit, offset)
    return array_response([view(v) for v in window], limit, offset, total)


@bp.get("/members/<member_id>/loyalty-ledger")
def list_member_ledger(member_id):
    _, role = get_identity()
    require_roles(role, {"Manager", "Attendant", "Member"})
    get_or_404(db.members, member_id, "Member")
    limit, offset = parse_pagination()
    items = [e for e in db.loyalty_ledger.values() if e["member_id"] == member_id]
    window, total = paginate(items, limit, offset)
    return array_response([view(e) for e in window], limit, offset, total)


@bp.post("/members/<member_id>/redeem")
def redeem(member_id):
    user_id, role = get_identity()
    require_roles(role, {"Member", "Attendant"})
    with db.lock:
        member = get_or_404(db.members, member_id, "Member")
        # Ownership (priority 5).
        if role == "Member" and user_id != member_id:
            raise err(ERR_FORBIDDEN, "Member may only redeem their own account")
        plan = require_active_plan()
        # Member must be ACTIVE.
        if member["status"] != "ACTIVE":
            raise err(ERR_MEMBER_NOT_ACTIVE, "Member is not ACTIVE")
        threshold = plan["loyalty_redeem_threshold_points"]
        if member["loyalty_points"] < threshold:
            raise err(ERR_INSUFFICIENT_POINTS, "Insufficient loyalty points to redeem")
        member["loyalty_points"] -= threshold
        member["free_wash_credits"] += 1
        touch(member)
        write_ledger(member, "REDEMPTION", -threshold, None)
    return object_response(view(member))
