"""Members: register, get, list, suspend, reactivate, birthday-grant, lots.
Also transactions (ledger reads). (PRD §3.2, §3.5)"""
from flask import Blueprint, request

from db import db
from errors import (err, ERR_PROGRAM_NOT_ACTIVE, ERR_DUPLICATE_EMAIL,
                    ERR_INVALID_STATE, ERR_BIRTHDAY_ALREADY_GRANTED,
                    ERR_NOT_BIRTHDAY, ERR_INVALID_REQUEST)
from middleware import require_roles
from response import success
from services import serialize, ledger
from services.helpers import (get_json_body, require_str, opt_str, validate_mmdd,
                              paginate)
from services.lookup import (get_program, get_member, assert_member_owner,
                             get_transaction, get_or_404)

bp = Blueprint("members", __name__)


@bp.post("/members")
def register_member():
    require_roles("ProgramAdmin", "Member")
    body = get_json_body()
    program_id = require_str(body, "program_id")
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    birth_month_day = validate_mmdd(require_str(body, "birth_month_day"))
    referred_by_member_id = opt_str(body, "referred_by_member_id", None)

    program = get_program(program_id)
    if referred_by_member_id is not None:
        get_member(referred_by_member_id)  # existence (left-to-right)

    # program-active gate (priority 11)
    if program["status"] != "ACTIVE":
        raise err(ERR_PROGRAM_NOT_ACTIVE, "Program is not ACTIVE")

    # unique email within program (priority 6)
    for m in db.members.values():
        if m["program_id"] == program_id and m["email"] == email:
            raise err(ERR_DUPLICATE_EMAIL, "Email already registered in program")

    m = {
        "program_id": program_id,
        "email": email,
        "full_name": full_name,
        "birth_month_day": birth_month_day,
        "referred_by_member_id": referred_by_member_id,
        "current_tier_code": "STANDARD",
        "available_points": 0,
        "projected_points": 0,
        "qualifying_points_window": 0,
        "lifetime_earned_points": 0,
        "status": "ACTIVE",
        "last_birthday_grant_year": None,
    }
    db.stamp_create(m)
    db.members[m["id"]] = m

    # Referral linkage (PRD §3.2): bind the PENDING referral, leave it PENDING.
    if referred_by_member_id is not None:
        for ref in db.referrals.values():
            if (ref["program_id"] == program_id
                    and ref["status"] == "PENDING"
                    and ref["referrer_member_id"] == referred_by_member_id
                    and ref["referee_email"] == email
                    and ref["referee_member_id"] is None):
                ref["referee_member_id"] = m["id"]
                db.touch(ref)
                break

    ledger.recompute_member(m)
    return success(serialize.member_out(m), 201)


@bp.get("/members/<mid>")
def get_member_route(mid):
    _, role = require_roles("ProgramAdmin", "Member")
    m = get_member(mid)
    user_id = request.headers.get("X-User-ID")
    assert_member_owner(role, user_id, mid)
    return success(serialize.member_out(m), 200)


@bp.get("/members")
def list_members():
    require_roles("ProgramAdmin")
    program_id = request.args.get("program_id")
    referred_by = request.args.get("referred_by_member_id")
    items = list(db.members.values())
    if program_id is not None:
        items = [m for m in items if m["program_id"] == program_id]
    if referred_by is not None:
        items = [m for m in items if m["referred_by_member_id"] == referred_by]
    page, pg = paginate(items)
    return success([serialize.member_out(x) for x in page], 200, pg)


@bp.post("/members/<mid>/suspend")
def suspend_member(mid):
    require_roles("ProgramAdmin")
    m = get_member(mid)
    if m["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Member cannot be suspended from its state")
    m["status"] = "SUSPENDED"
    db.touch(m)
    return success(serialize.member_out(m), 200)


@bp.post("/members/<mid>/reactivate")
def reactivate_member(mid):
    require_roles("ProgramAdmin")
    m = get_member(mid)
    if m["status"] != "SUSPENDED":
        raise err(ERR_INVALID_STATE, "Member cannot be reactivated from its state")
    m["status"] = "ACTIVE"
    db.touch(m)
    return success(serialize.member_out(m), 200)


@bp.post("/members/<mid>/birthday-grant")
def birthday_grant(mid):
    require_roles("ProgramAdmin")
    m = get_member(mid)
    program = db.programs[m["program_id"]]
    now = db.current_clock
    current_year = now.year

    # already-granted-this-year guard first (priority 21)
    if m["last_birthday_grant_year"] == current_year:
        raise err(ERR_BIRTHDAY_ALREADY_GRANTED, "Birthday already granted this year")
    # not-birthday guard second (priority 22)
    clock_mmdd = "%02d-%02d" % (now.month, now.day)
    if clock_mmdd != m["birth_month_day"]:
        raise err(ERR_NOT_BIRTHDAY, "Not the member's birthday")

    lot, _tx = ledger.mint_lot(
        m, source_type="BIRTHDAY",
        points=program["birthday_reward_points"],
        source_id=None, tx_type="BIRTHDAY",
    )
    m["last_birthday_grant_year"] = current_year
    ledger.recompute_member(m)
    db.touch(m)  # version advances by 1 (PRD §3.5)
    return success(serialize.lot_out(lot), 201)


@bp.get("/members/<mid>/lots")
def list_lots(mid):
    _, role = require_roles("ProgramAdmin", "Member")
    get_member(mid)
    user_id = request.headers.get("X-User-ID")
    assert_member_owner(role, user_id, mid)
    status = request.args.get("status")
    items = [l for l in db.lots.values() if l["member_id"] == mid]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    page, pg = paginate(items)
    return success([serialize.lot_out(x) for x in page], 200, pg)


# ---------------------------------------------------------------------------
# Transactions (append-only ledger reads)
# ---------------------------------------------------------------------------
@bp.get("/transactions/<tid>")
def get_transaction_route(tid):
    _, role = require_roles("ProgramAdmin", "Member")
    tx = get_transaction(tid)
    user_id = request.headers.get("X-User-ID")
    assert_member_owner(role, user_id, tx["member_id"])
    return success(serialize.transaction_out(tx), 200)


@bp.get("/transactions")
def list_transactions():
    _, role = require_roles("ProgramAdmin", "Member")
    user_id = request.headers.get("X-User-ID")
    member_id = request.args.get("member_id")
    lot_id = request.args.get("lot_id")
    ref_redemption_id = request.args.get("ref_redemption_id")
    ref_transfer_id = request.args.get("ref_transfer_id")
    tx_type = request.args.get("type")

    items = list(db.transactions.values())
    if role == "Member":
        # a member sees only their own ledger
        items = [t for t in items if t["member_id"] == user_id]
    if member_id is not None:
        items = [t for t in items if t["member_id"] == member_id]
    if lot_id is not None:
        items = [t for t in items if t["lot_id"] == lot_id]
    if ref_redemption_id is not None:
        items = [t for t in items if t["ref_redemption_id"] == ref_redemption_id]
    if ref_transfer_id is not None:
        items = [t for t in items if t["ref_transfer_id"] == ref_transfer_id]
    if tx_type is not None:
        items = [t for t in items if t["type"] == tx_type]
    page, pg = paginate(items)
    return success([serialize.transaction_out(x) for x in page], 200, pg)
