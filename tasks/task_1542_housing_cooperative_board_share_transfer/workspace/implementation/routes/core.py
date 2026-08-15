"""Cooperatives, logical clock, units, shareholders, share ledger."""
from flask import Blueprint, request

import domain as D
from db import STORE
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_BUSINESS_CONSTRAINT,
    ERR_SHARES_MISMATCH,
    ERR_CROSS_ENTITY_VIOLATION,
)
from middleware import ctx, require_role, ALL_ROLES
from response import ok, ok_list
from util import (
    get_body, req_str, req_int, opt_int, opt_enum, req_dt, pagination, START_UTC,
)

bp = Blueprint("core", __name__)

READ_ALL = list(ALL_ROLES)


def list_response(kind, cid, filters):
    """filters: list of (field, raw_value, is_int); None raw values are skipped."""
    items = D.all_of(kind, cid)
    for field, raw, is_int in filters:
        if raw is None:
            continue
        if is_int:
            try:
                iv = int(raw)
            except (TypeError, ValueError):
                raise ApiError(ERR_INVALID_REQUEST, "Invalid filter value for %s" % field, 400)
            items = [e for e in items if e.get(field) == iv]
        else:
            items = [e for e in items if str(e.get(field)) == raw]
    total = len(items)
    limit, offset = pagination()
    page = items[offset:offset + limit]
    return ok_list([D.ser(e) for e in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Cooperatives
# ---------------------------------------------------------------------------

@bp.post("/cooperatives")
def create_cooperative():
    uid, role = ctx()
    require_role(role, ["PlatformAdmin"])
    body = get_body()
    name = req_str(body, "name")
    address = req_str(body, "address")
    principal = req_int(body, "underlying_mortgage_principal_cents")
    rate = req_int(body, "underlying_mortgage_rate_bps")
    coop = D.make(
        "cooperatives", None,
        name=name,
        address=address,
        total_shares=0,
        underlying_mortgage_principal_cents=principal,
        underlying_mortgage_rate_bps=rate,
        flip_tax_policy=opt_enum(body, "flip_tax_policy", ["GROSS_PERCENT", "PER_SHARE"], "GROSS_PERCENT"),
        flip_tax_percent_bps=opt_int(body, "flip_tax_percent_bps", 200),
        flip_tax_per_share_cents=opt_int(body, "flip_tax_per_share_cents", 50000),
        sublet_policy_years_max=opt_int(body, "sublet_policy_years_max", 2),
        sublet_policy_gap_years=opt_int(body, "sublet_policy_gap_years", 1),
        arrears_late_fee_flat_cents=opt_int(body, "arrears_late_fee_flat_cents", 5000),
        arrears_interest_rate_bps=opt_int(body, "arrears_interest_rate_bps", 600),
        arrears_grace_days=opt_int(body, "arrears_grace_days", 10),
        arrears_termination_threshold_cents=opt_int(body, "arrears_termination_threshold_cents", 1000000),
        annual_meeting_quorum_percent_bps=opt_int(body, "annual_meeting_quorum_percent_bps", 5000),
        current_utc=START_UTC,
    )
    return ok(D.ser(coop), 201)


@bp.get("/cooperatives")
def list_cooperatives():
    uid, role = ctx()
    require_role(role, ["PlatformAdmin"])
    items = D.all_of("cooperatives")
    total = len(items)
    limit, offset = pagination()
    page = items[offset:offset + limit]
    return ok_list([D.ser(e) for e in page], total, limit, offset)


@bp.get("/cooperatives/<cid>")
def get_cooperative(cid):
    uid, role = ctx()
    require_role(role, READ_ALL)
    coop = D.get_coop(cid)
    return ok(D.ser(coop))


@bp.post("/cooperatives/<cid>/_clock/set_current_utc")
def set_clock(cid):
    uid, role = ctx()
    require_role(role, ["PlatformAdmin"])
    coop = D.get_coop(cid)
    body = get_body()
    to = req_dt(body, "to_iso8601")
    D.advance_clock(coop, to)
    return ok(D.ser(coop))


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

@bp.post("/cooperatives/<cid>/units")
def create_unit(cid):
    uid, role = ctx()
    require_role(role, ["PlatformAdmin", "BoardOfficer"])
    coop = D.get_coop(cid)
    body = get_body()
    label = req_str(body, "unit_label")
    shares = req_int(body, "shares_allocated")
    if shares <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "shares_allocated must be > 0", 400)
    unit = D.make(
        "units", coop,
        cooperative_id=cid,
        unit_label=label,
        shares_allocated=shares,
        occupancy_status="OWNER_OCCUPIED",
        last_sublet_end_date=None,
    )
    # INV-SHARES: total_shares tracks the sum of allocations; bump the aggregate version.
    coop["total_shares"] += shares
    D.bump_coop(coop)
    return ok(D.ser(unit), 201)


@bp.get("/cooperatives/<cid>/units")
def list_units(cid):
    uid, role = ctx()
    require_role(role, READ_ALL)
    D.get_coop(cid)
    return list_response("units", cid, [])


@bp.get("/cooperatives/<cid>/units/<uid>")
def get_unit(cid, uid):
    user_id, role = ctx()
    require_role(role, READ_ALL)
    D.get_coop(cid)
    unit = D.get_scoped("units", uid, cid, "Unit")
    return ok(D.ser(unit))


# ---------------------------------------------------------------------------
# Shareholders
# ---------------------------------------------------------------------------

@bp.post("/cooperatives/<cid>/shareholders")
def create_shareholder(cid):
    uid, role = ctx()
    require_role(role, ["PlatformAdmin", "BoardOfficer", "ManagingAgent"])
    coop = D.get_coop(cid)
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    dup = any(
        s for s in STORE["shareholders"].values()
        if s["cooperative_id"] == cid and s["email"] == email
    )
    if dup:
        raise ApiError(ERR_BUSINESS_CONSTRAINT, "email must be unique within the cooperative", 422)
    sh = D.make(
        "shareholders", coop,
        cooperative_id=cid,
        full_name=full_name,
        email=email,
        standing="GOOD_STANDING",
        arrears_balance_cents=0,
    )
    return ok(D.ser(sh), 201)


@bp.get("/cooperatives/<cid>/shareholders")
def list_shareholders(cid):
    uid, role = ctx()
    require_role(role, ["PlatformAdmin", "BoardOfficer", "BoardMember", "ManagingAgent"])
    D.get_coop(cid)
    return list_response("shareholders", cid, [
        ("standing", request.args.get("standing"), False),
    ])


@bp.get("/cooperatives/<cid>/shareholders/<sid>")
def get_shareholder(cid, sid):
    uid, role = ctx()
    require_role(role, READ_ALL)
    D.get_coop(cid)
    sh = D.get_scoped("shareholders", sid, cid, "Shareholder")
    return ok(D.ser(sh))


# ---------------------------------------------------------------------------
# Share ledger
# ---------------------------------------------------------------------------

@bp.post("/cooperatives/<cid>/share-ledger-entries")
def create_ledger_entry(cid):
    uid, role = ctx()
    require_role(role, ["PlatformAdmin", "BoardOfficer"])
    coop = D.get_coop(cid)
    body = get_body()
    unit_id = req_str(body, "unit_id")
    shareholder_id = req_str(body, "shareholder_id")
    shares_held = req_int(body, "shares_held")
    unit = STORE["units"].get(unit_id)
    if unit is None or unit["cooperative_id"] != cid:
        raise ApiError(ERR_CROSS_ENTITY_VIOLATION, "Referenced unit does not exist", 422)
    sh = STORE["shareholders"].get(shareholder_id)
    if sh is None or sh["cooperative_id"] != cid:
        raise ApiError(ERR_CROSS_ENTITY_VIOLATION, "Referenced shareholder does not exist", 422)
    # Conservation: after insert, ACTIVE entries must sum exactly to shares_allocated.
    current = sum(
        e["shares_held"]
        for e in STORE["share_ledger_entries"].values()
        if e["cooperative_id"] == cid and e["unit_id"] == unit_id and e["entry_status"] == "ACTIVE"
    )
    if current + shares_held != unit["shares_allocated"]:
        raise ApiError(
            ERR_SHARES_MISMATCH,
            "Sum of ACTIVE shares_held (%d) would not equal shares_allocated (%d)"
            % (current + shares_held, unit["shares_allocated"]),
            422,
        )
    now = coop["current_utc"]
    entry = D.make(
        "share_ledger_entries", coop,
        cooperative_id=cid,
        unit_id=unit_id,
        shareholder_id=shareholder_id,
        shares_held=shares_held,
        entry_status="ACTIVE",
        effective_at=now,
    )
    return ok(D.ser(entry), 201)


@bp.get("/cooperatives/<cid>/share-ledger-entries")
def list_ledger_entries(cid):
    uid, role = ctx()
    require_role(role, READ_ALL)
    D.get_coop(cid)
    return list_response("share_ledger_entries", cid, [
        ("unit_id", request.args.get("unit_id"), False),
        ("shareholder_id", request.args.get("shareholder_id"), False),
        ("entry_status", request.args.get("entry_status"), False),
    ])


@bp.get("/cooperatives/<cid>/share-ledger-entries/<eid>")
def get_ledger_entry(cid, eid):
    uid, role = ctx()
    require_role(role, READ_ALL)
    D.get_coop(cid)
    e = D.get_scoped("share_ledger_entries", eid, cid, "ShareLedgerEntry")
    return ok(D.ser(e))
