from flask import Blueprint, request

import errors
from errors import err
from db import db
from models import make_common, touch, serialize
from clock import parse_iso8601
from middleware import get_identity, require_role
from helpers import (get_json_body, lookup, parse_pagination, paginate,
                     sort_by_created, require_tenant_owns_lease)
from response import success, list_response
from services import calc, domain
from datetime import timedelta

bp = Blueprint("auctions", __name__)

TERMINAL = ("SOLD", "REDEEMED", "CANCELLED")


def _outstanding_as_of(lease_id):
    """Outstanding sum (total - amount_paid) over OPEN/PARTIAL/OVERDUE invoices."""
    return domain.outstanding_for_lease(lease_id)


def _accruing_redemption(lease_id):
    return _outstanding_as_of(lease_id) + calc.LIEN_ADMIN_COST_CENTS


def _serialize_auction(ap):
    data = serialize(ap)
    # GET returns the accruing-today redemption amount.
    data["redemption_amount_cents"] = _accruing_redemption(ap["lease_id"])
    return data


@bp.post("/auction-proceedings")
def open_proceeding():
    _, role = get_identity()
    require_role(role, {"LienAdministrator"})
    body = get_json_body()

    lease_id = body.get("lease_id")
    if not isinstance(lease_id, str) or not lease_id:
        raise err(errors.ERR_INVALID_REQUEST, "lease_id is required")
    lease = lookup(db.leases, lease_id, "lease")

    if "expected_lease_version" not in body or body["expected_lease_version"] is None:
        raise err(errors.ERR_INVALID_REQUEST, "expected_lease_version is required")
    expected = body["expected_lease_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err(errors.ERR_INVALID_REQUEST, "expected_lease_version must be an integer")

    # State check (must be PRE_LIEN).
    if lease["status"] != "PRE_LIEN":
        raise err(errors.ERR_INVALID_STATE, "Lease must be PRE_LIEN to open a proceeding")

    # Window: days_past_due >= lien_default_days.
    facility = db.facilities.get(lease["facility_id"])
    if lease.get("days_past_due", 0) < facility["lien_default_days"]:
        raise err(errors.ERR_WINDOW_NOT_ELAPSED, "Lease has not reached the lien default window")

    # Existing non-terminal proceeding?
    for ap in db.auction_proceedings.values():
        if ap["lease_id"] == lease_id and ap["status"] not in TERMINAL:
            raise err(errors.ERR_PROCEEDING_EXISTS, "A non-terminal proceeding already exists")

    # OCC.
    if expected != lease["version"]:
        raise err(errors.ERR_STALE_VERSION, "expected_lease_version does not match lease version")

    clock = db.clock.now()
    ap = make_common()
    ap.update({
        "lease_id": lease_id,
        "status": "NOTICE_SENT",
        "notice_sent_date": clock,
        "lien_filed_date": None,
        "scheduled_sale_date": None,
        "redemption_amount_cents": _accruing_redemption(lease_id),
        "sale_proceeds_cents": None,
        "surplus_cents": None,
        "_lien_date_snapshot": None,
    })
    db.auction_proceedings[ap["id"]] = ap

    lease["status"] = "LIEN"
    touch(lease)  # increments version by 1

    return success(_serialize_auction(ap), 201)


@bp.get("/auction-proceedings/<auction_id>")
def get_proceeding(auction_id):
    user_id, role = get_identity()
    ap = lookup(db.auction_proceedings, auction_id, "auction proceeding")
    lease = db.leases.get(ap["lease_id"])
    if lease is not None:
        require_tenant_owns_lease(user_id, role, lease)
    return success(_serialize_auction(ap), 200)


@bp.get("/auction-proceedings")
def list_proceedings():
    user_id, role = get_identity()
    limit, offset = parse_pagination()
    items = list(db.auction_proceedings.values())
    lease_id = request.args.get("lease_id")
    status = request.args.get("status")
    if lease_id is not None:
        items = [a for a in items if a["lease_id"] == lease_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if role == "Tenant":
        owned = {l["id"] for l in db.leases.values() if l["tenant_id"] == user_id}
        items = [a for a in items if a["lease_id"] in owned]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_response([_serialize_auction(a) for a in page], total, limit, offset)


@bp.post("/auction-proceedings/<auction_id>/file-lien")
def file_lien(auction_id):
    _, role = get_identity()
    require_role(role, {"LienAdministrator"})
    ap = lookup(db.auction_proceedings, auction_id, "auction proceeding")

    if ap["status"] != "NOTICE_SENT":
        raise err(errors.ERR_INVALID_STATE, "Proceeding must be NOTICE_SENT to file lien")

    clock = db.clock.now()
    if clock < ap["notice_sent_date"] + timedelta(days=14):
        raise err(errors.ERR_WINDOW_NOT_ELAPSED, "Statutory notice period has not elapsed")

    ap["status"] = "LIEN_FILED"
    ap["lien_filed_date"] = clock
    # Freeze lien-date redemption snapshot (excludes post-lien late fees).
    ap["_lien_date_snapshot"] = _outstanding_as_of(ap["lease_id"]) + calc.LIEN_ADMIN_COST_CENTS
    touch(ap)
    return success(_serialize_auction(ap), 200)


@bp.post("/auction-proceedings/<auction_id>/schedule")
def schedule_sale(auction_id):
    _, role = get_identity()
    require_role(role, {"LienAdministrator"})
    ap = lookup(db.auction_proceedings, auction_id, "auction proceeding")
    body = get_json_body()

    if ap["status"] != "LIEN_FILED":
        raise err(errors.ERR_INVALID_STATE, "Proceeding must be LIEN_FILED to schedule")

    raw = body.get("scheduled_sale_date")
    sale_date = parse_iso8601(raw) if raw is not None else None
    if sale_date is None:
        raise err(errors.ERR_INVALID_REQUEST, "scheduled_sale_date is required and must be ISO 8601")

    if sale_date < ap["lien_filed_date"] + timedelta(days=14):
        raise err(errors.ERR_WINDOW_NOT_ELAPSED, "scheduled_sale_date must be >= lien_filed_date + 14 days")

    ap["scheduled_sale_date"] = sale_date
    ap["status"] = "SCHEDULED"
    touch(ap)

    lease = db.leases.get(ap["lease_id"])
    if lease is not None:
        lease["status"] = "AUCTION_SCHEDULED"
        touch(lease)

    return success(_serialize_auction(ap), 200)


@bp.post("/auction-proceedings/<auction_id>/complete-sale")
def complete_sale(auction_id):
    _, role = get_identity()
    require_role(role, {"LienAdministrator"})
    ap = lookup(db.auction_proceedings, auction_id, "auction proceeding")
    body = get_json_body()

    if ap["status"] != "SCHEDULED":
        raise err(errors.ERR_INVALID_STATE, "Proceeding must be SCHEDULED to complete sale")

    proceeds = body.get("sale_proceeds_cents")
    if isinstance(proceeds, bool) or not isinstance(proceeds, int):
        raise err(errors.ERR_INVALID_REQUEST, "sale_proceeds_cents must be an integer")
    if proceeds <= 0:
        raise err(errors.ERR_BALANCE_NOT_CLEARED, "sale_proceeds_cents must be > 0")

    lease = db.leases.get(ap["lease_id"])
    clock = db.clock.now()

    # Surplus waterfall: bucket1 rent/climate/insurance, bucket2 late fees, bucket3 lien admin.
    nonfee_outstanding = 0
    fee_outstanding = 0
    for inv in domain.lease_open_invoices(ap["lease_id"]):
        nonfee = inv["base_amount_cents"] + inv["climate_amount_cents"] + inv["insurance_amount_cents"]
        paid = inv["amount_paid_cents"]
        nonfee_unpaid = max(0, nonfee - paid)
        total_unpaid = inv["total_amount_cents"] - paid
        fee_unpaid = max(0, total_unpaid - nonfee_unpaid)
        nonfee_outstanding += nonfee_unpaid
        fee_outstanding += fee_unpaid

    remaining = proceeds
    b1 = min(remaining, nonfee_outstanding); remaining -= b1
    b2 = min(remaining, fee_outstanding); remaining -= b2
    b3 = min(remaining, calc.LIEN_ADMIN_COST_CENTS); remaining -= b3
    surplus = remaining

    ap["status"] = "SOLD"
    ap["sale_proceeds_cents"] = proceeds
    ap["surplus_cents"] = surplus
    touch(ap)

    if lease is not None:
        # Settle balance to zero via AUCTION_SETTLEMENT ledger entry.
        prior_balance = lease["balance_cents"]
        if prior_balance != 0:
            domain.append_ledger(lease, "AUCTION_SETTLEMENT", -prior_balance, "AUCTION", ap["id"])
        else:
            domain.append_ledger(lease, "AUCTION_SETTLEMENT", 0, "AUCTION", ap["id"])
        lease["balance_cents"] = 0
        lease["status"] = "AUCTIONED"
        lease["end_date"] = clock
        touch(lease)

        unit = db.units.get(lease["unit_id"])
        if unit is not None:
            unit["status"] = "AVAILABLE"
            unit["current_lease_id"] = None
            touch(unit)
            domain.recompute_occupied(unit["facility_id"])

        for p in db.insurance_policies.values():
            if p["lease_id"] == lease["id"] and p["status"] in ("ACTIVE", "LAPSED"):
                p["status"] = "CANCELLED"
                p["coverage_end"] = clock
                touch(p)

    return success(_serialize_auction(ap), 200)


@bp.post("/auction-proceedings/<auction_id>/redeem")
def redeem(auction_id):
    user_id, role = get_identity()
    require_role(role, {"Tenant"})
    ap = lookup(db.auction_proceedings, auction_id, "auction proceeding")
    lease = db.leases.get(ap["lease_id"])
    if lease is not None:
        require_tenant_owns_lease(user_id, role, lease)

    if ap["status"] not in ("NOTICE_SENT", "LIEN_FILED", "SCHEDULED"):
        raise err(errors.ERR_INVALID_STATE, "Proceeding is not in a redeemable state")
    if lease is not None and lease["status"] not in ("LIEN", "AUCTION_SCHEDULED"):
        raise err(errors.ERR_INVALID_STATE, "Lease is not in a redeemable state")

    if lease is not None and lease["balance_cents"] != 0:
        raise err(errors.ERR_BALANCE_NOT_CLEARED, "Balance must be cleared to redeem")

    ap["status"] = "REDEEMED"
    touch(ap)
    if lease is not None:
        lease["status"] = "ACTIVE"
        lease["days_past_due"] = 0
        touch(lease)

    return success(_serialize_auction(ap), 200)


@bp.post("/auction-proceedings/<auction_id>/cancel")
def cancel_proceeding(auction_id):
    _, role = get_identity()
    require_role(role, {"LienAdministrator"})
    ap = lookup(db.auction_proceedings, auction_id, "auction proceeding")

    if ap["status"] not in ("NOTICE_SENT", "LIEN_FILED"):
        raise err(errors.ERR_INVALID_STATE, "Only NOTICE_SENT or LIEN_FILED proceedings can be cancelled")

    ap["status"] = "CANCELLED"
    touch(ap)

    lease = db.leases.get(ap["lease_id"])
    if lease is not None and lease["status"] in ("LIEN", "AUCTION_SCHEDULED") and lease["balance_cents"] == 0:
        lease["status"] = "ACTIVE"
        touch(lease)

    return success(_serialize_auction(ap), 200)
