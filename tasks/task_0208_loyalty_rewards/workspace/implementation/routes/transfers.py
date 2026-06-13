"""Partner transfers + transfer blackouts. Conversion, FIFO burn, compensation,
blackout overlap/buffer + coverage gate. (PRD §3.8)"""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (err, ERR_PROGRAM_NOT_ACTIVE, ERR_MEMBER_NOT_ACTIVE,
                    ERR_PARTNER_PAUSED, ERR_TRANSFER_BLACKED_OUT,
                    ERR_INVALID_TRANSFER_BLOCK, ERR_INSUFFICIENT_POINTS,
                    ERR_STALE_MEMBER_VERSION, ERR_INVALID_STATE,
                    ERR_INVALID_WINDOW, ERR_BLACKOUT_OVERLAP, ERR_INVALID_REQUEST)
from middleware import require_roles
from response import success
from services import serialize, ledger
from services.helpers import (get_json_body, require_str, require_int, opt_int,
                              parse_iso, fmt_iso, paginate)
from services.lookup import (get_member, get_partner, get_transfer, get_blackout,
                             assert_member_owner, assert_partner_owner)

bp = Blueprint("transfers", __name__)

BUFFER = timedelta(minutes=60)


# ---------------------------------------------------------------------------
# Partner transfers (PRD §3.8)
# ---------------------------------------------------------------------------
def _blackout_covers_now(partner_id):
    now = db.current_clock
    for b in db.blackouts.values():
        if b["partner_account_id"] != partner_id:
            continue
        if b["status"] != "SCHEDULED":
            continue
        if parse_iso(b["starts_at"]) <= now <= parse_iso(b["ends_at"]):
            return True
    return False


@bp.post("/partner-transfers")
def create_transfer():
    _, role = require_roles("Member", "ProgramAdmin")
    body = get_json_body()
    member_id = require_str(body, "member_id")
    partner_account_id = require_str(body, "partner_account_id")
    loyalty_points = require_int(body, "loyalty_points")
    expected_member_version = opt_int(body, "expected_member_version", None)

    member = get_member(member_id)
    partner = get_partner(partner_account_id)
    user_id = request.headers.get("X-User-ID")
    assert_member_owner(role, user_id, member_id)
    program = db.programs[member["program_id"]]

    # shape: loyalty_points > 0
    if loyalty_points <= 0:
        raise err(ERR_INVALID_REQUEST, "loyalty_points must be > 0")

    # program-active gate (priority 11)
    if program["status"] != "ACTIVE":
        raise err(ERR_PROGRAM_NOT_ACTIVE, "Program is not ACTIVE")
    # member-active gate (priority 13)
    if member["status"] != "ACTIVE":
        raise err(ERR_MEMBER_NOT_ACTIVE, "Member is not ACTIVE")
    # partner-active gate (priority 14)
    if partner["status"] != "ACTIVE":
        raise err(ERR_PARTNER_PAUSED, "Partner is paused")
    # blackout coverage gate (priority 15)
    if _blackout_covers_now(partner_account_id):
        raise err(ERR_TRANSFER_BLACKED_OUT, "Transfer blacked out")
    # transfer-block constraint (priority 17)
    if loyalty_points % partner["transfer_block_size"] != 0 \
            or loyalty_points < partner["min_transfer_points"]:
        raise err(ERR_INVALID_TRANSFER_BLOCK,
                  "loyalty_points must be a positive multiple of the block size and >= min")

    # fiscal sufficiency (priority 20)
    ledger.recompute_member(member)
    if member["available_points"] < loyalty_points:
        raise err(ERR_INSUFFICIENT_POINTS, "Insufficient available points")

    # OCC last (priority 25)
    if expected_member_version is not None and expected_member_version != member["version"]:
        raise err(ERR_STALE_MEMBER_VERSION, "Member version is stale")

    # Conversion (PRD §3.8 pinned order): tier -> ratio -> floor.
    tier = ledger.tier_for_code(member["program_id"], member["current_tier_code"])
    ratio = tier["transfer_ratio"] if tier else 1.0
    partner_points = ledger.floor_product(loyalty_points, ratio)

    transfer = {
        "member_id": member_id,
        "partner_account_id": partner_account_id,
        "loyalty_points": loyalty_points,
        "partner_points": partner_points,
        "status": "SUBMITTED",
        "expected_member_version": expected_member_version,
    }
    db.stamp_create(transfer)
    db.transfers[transfer["id"]] = transfer

    # Burn FIFO (TRANSFER_OUT rows referencing the transfer).
    ledger.fifo_burn(member, loyalty_points, tx_type="TRANSFER_OUT",
                     ref_transfer_id=transfer["id"])
    ledger.recompute_member(member)
    db.touch(member)  # version advances by 1 (PRD §3.8)
    return success(serialize.transfer_out(transfer), 201)


@bp.get("/partner-transfers/<tid>")
def get_transfer_route(tid):
    _, role = require_roles("ProgramAdmin", "Member", "PartnerOperator")
    t = get_transfer(tid)
    user_id = request.headers.get("X-User-ID")
    assert_member_owner(role, user_id, t["member_id"])
    assert_partner_owner(role, user_id, t["partner_account_id"])
    return success(serialize.transfer_out(t), 200)


@bp.get("/members/<mid>/partner-transfers")
def list_member_transfers(mid):
    _, role = require_roles("ProgramAdmin", "Member")
    get_member(mid)
    user_id = request.headers.get("X-User-ID")
    assert_member_owner(role, user_id, mid)
    status = request.args.get("status")
    items = [t for t in db.transfers.values() if t["member_id"] == mid]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, pg = paginate(items)
    return success([serialize.transfer_out(x) for x in page], 200, pg)


@bp.get("/partners/<pid>/transfers")
def list_partner_transfers(pid):
    _, role = require_roles("ProgramAdmin", "PartnerOperator")
    get_partner(pid)
    user_id = request.headers.get("X-User-ID")
    assert_partner_owner(role, user_id, pid)
    status = request.args.get("status")
    items = [t for t in db.transfers.values() if t["partner_account_id"] == pid]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, pg = paginate(items)
    return success([serialize.transfer_out(x) for x in page], 200, pg)


@bp.post("/partner-transfers/<tid>/settle")
def settle_transfer(tid):
    _, role = require_roles("PartnerOperator")
    t = get_transfer(tid)
    user_id = request.headers.get("X-User-ID")
    assert_partner_owner(role, user_id, t["partner_account_id"])
    partner = db.partners[t["partner_account_id"]]

    if t["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Transfer is not SUBMITTED")
    if partner["status"] != "ACTIVE":
        raise err(ERR_PARTNER_PAUSED, "Partner is paused")
    t["status"] = "SETTLED"
    db.touch(t)
    return success(serialize.transfer_out(t), 200)


@bp.post("/partner-transfers/<tid>/reverse")
def reverse_transfer(tid):
    _, role = require_roles("PartnerOperator", "ProgramAdmin")
    t = get_transfer(tid)
    user_id = request.headers.get("X-User-ID")
    assert_partner_owner(role, user_id, t["partner_account_id"])
    member = db.members[t["member_id"]]

    if t["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Transfer is not SUBMITTED")

    # Compensation: mint TRANSFER_IN_REVERSAL lot of loyalty_points back.
    ledger.mint_lot(member, source_type="TRANSFER_IN_REVERSAL",
                    points=t["loyalty_points"], source_id=t["id"],
                    tx_type="TRANSFER_IN_REVERSAL", ref_transfer_id=t["id"])
    t["status"] = "REVERSED"
    db.touch(t)
    ledger.recompute_member(member)
    db.touch(member)
    return success(serialize.transfer_out(t), 200)


# ---------------------------------------------------------------------------
# Transfer blackouts (PRD §3.8)
# ---------------------------------------------------------------------------
def _blackout_conflicts(partner_id, new_start, new_end):
    """Overlap-or-buffer (closed interval + 60min buffer each side) against
    existing SCHEDULED blackouts on the same partner."""
    for b in db.blackouts.values():
        if b["partner_account_id"] != partner_id:
            continue
        if b["status"] != "SCHEDULED":
            continue
        es = parse_iso(b["starts_at"])
        ee = parse_iso(b["ends_at"])
        if new_start <= ee + BUFFER and es - BUFFER <= new_end:
            return True
    return False


@bp.post("/partners/<pid>/blackouts")
def create_blackout(pid):
    _, role = require_roles("ProgramAdmin", "PartnerOperator")
    partner = get_partner(pid)
    user_id = request.headers.get("X-User-ID")
    assert_partner_owner(role, user_id, pid)
    body = get_json_body()
    starts_at = parse_iso(require_str(body, "starts_at"))
    ends_at = parse_iso(require_str(body, "ends_at"))

    # window validity (priority 10 prerequisite): ends_at >= starts_at
    if ends_at < starts_at:
        raise err(ERR_INVALID_WINDOW, "Blackout ends_at must be >= starts_at")
    # overlap-or-buffer (priority 10)
    if _blackout_conflicts(pid, starts_at, ends_at):
        raise err(ERR_BLACKOUT_OVERLAP, "Blackout overlaps or is within buffer")

    b = {
        "partner_account_id": pid,
        "starts_at": fmt_iso(starts_at),
        "ends_at": fmt_iso(ends_at),
        "status": "SCHEDULED",
    }
    db.stamp_create(b)
    db.blackouts[b["id"]] = b
    return success(serialize.blackout_out(b), 201)


@bp.get("/blackouts/<bid>")
def get_blackout_route(bid):
    _, role = require_roles("ProgramAdmin", "PartnerOperator")
    b = get_blackout(bid)
    user_id = request.headers.get("X-User-ID")
    assert_partner_owner(role, user_id, b["partner_account_id"])
    return success(serialize.blackout_out(b), 200)


@bp.get("/partners/<pid>/blackouts")
def list_blackouts(pid):
    _, role = require_roles("ProgramAdmin", "PartnerOperator")
    get_partner(pid)
    user_id = request.headers.get("X-User-ID")
    assert_partner_owner(role, user_id, pid)
    status = request.args.get("status")
    items = [b for b in db.blackouts.values() if b["partner_account_id"] == pid]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, pg = paginate(items)
    return success([serialize.blackout_out(x) for x in page], 200, pg)


@bp.post("/blackouts/<bid>/cancel")
def cancel_blackout(bid):
    _, role = require_roles("ProgramAdmin", "PartnerOperator")
    b = get_blackout(bid)
    user_id = request.headers.get("X-User-ID")
    assert_partner_owner(role, user_id, b["partner_account_id"])
    if b["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Blackout is not SCHEDULED")
    b["status"] = "CANCELLED"
    db.touch(b)
    return success(serialize.blackout_out(b), 200)
