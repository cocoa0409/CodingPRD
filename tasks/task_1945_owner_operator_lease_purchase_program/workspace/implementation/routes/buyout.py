"""BuyoutQuote routes."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import clock
import errors
import middleware
from db import db
from response import success
from services.core import (
    base_entity, touch, round_half_up_cents, EARLY_FEE_RATE, QUOTE_TTL_DAYS,
)
from services.serialize import serialize_quote
from routes.leases import escrow_for_lease
from util import get_body, req_str, req_int, req_enum, parse_pagination, paginate

bp = Blueprint("buyout", __name__)

QUOTE_KINDS = {"SCHEDULED", "EARLY"}


def _get_quote_or_404(qid):
    q = db.buyout_quotes.get(qid)
    if q is None:
        raise errors.err(errors.ERR_QUOTE_NOT_FOUND, "BuyoutQuote not found", 404)
    return q


@bp.post("/buyout-quotes")
def create_quote():
    middleware.require_roles({"LeaseAdmin"})
    body = get_body()
    lease_id = req_str(body, "lease_id")
    quote_kind = req_enum(body, "quote_kind", QUOTE_KINDS)
    expected_lease_version = req_int(body, "expected_lease_version")

    lease = db.lease_agreements.get(lease_id)
    if lease is None:
        raise errors.err(errors.ERR_LEASE_NOT_FOUND, "LeaseAgreement not found", 404)

    # Eligibility: lease must be ACTIVE or DEFAULTED; SCHEDULED requires term end reached
    now = clock.now()
    term_end = lease["_start_date"] + timedelta(weeks=lease["term_weeks"])
    if lease["status"] not in ("ACTIVE", "DEFAULTED"):
        raise errors.err(
            errors.ERR_BUYOUT_NOT_ELIGIBLE,
            "Buyout quote requires lease ACTIVE or DEFAULTED",
            422,
        )
    if quote_kind == "SCHEDULED" and now < term_end:
        raise errors.err(
            errors.ERR_BUYOUT_NOT_ELIGIBLE,
            "SCHEDULED quote requires the logical clock to have reached term end",
            422,
        )

    # OCC: expected_lease_version must match
    if expected_lease_version != lease["version"]:
        raise errors.err(
            errors.ERR_STALE_VERSION,
            "expected_lease_version does not match the lease's current version",
            412,
        )

    # Pricing — pinned four-step evaluation order
    days_elapsed = max(0, (now - lease["_start_date"]).days)
    weeks_elapsed = days_elapsed // 7
    remaining_weeks = max(0, lease["term_weeks"] - weeks_elapsed)

    if quote_kind == "SCHEDULED":
        quoted_price_cents = lease["buyout_base_price_cents"]
    else:
        fee = round_half_up_cents(
            Decimal(remaining_weeks) * Decimal(lease["weekly_payment_cents"]) * EARLY_FEE_RATE
        )
        quoted_price_cents = lease["buyout_base_price_cents"] + fee

    arrears_carried_cents = lease["arrears_cents"]
    escrow = escrow_for_lease(lease_id)
    escrow_credit_cents = min(escrow["balance_cents"], quoted_price_cents + arrears_carried_cents)
    amount_due_cents = max(0, quoted_price_cents + arrears_carried_cents - escrow_credit_cents)

    # Supersede prior GENERATED quotes of this lease
    for q in db.buyout_quotes.values():
        if q["lease_id"] == lease_id and q["status"] == "GENERATED":
            q["status"] = "SUPERSEDED"
            touch(q)

    quote = base_entity()
    quote.update({
        "lease_id": lease_id,
        "quote_kind": quote_kind,
        "quoted_price_cents": quoted_price_cents,
        "escrow_credit_cents": escrow_credit_cents,
        "arrears_carried_cents": arrears_carried_cents,
        "amount_due_cents": amount_due_cents,
        "_expires_on": now + timedelta(days=QUOTE_TTL_DAYS),
        "status": "GENERATED",
    })
    db.buyout_quotes[quote["id"]] = quote

    # Quote creation bumps the lease version (the mutation OCC guards)
    touch(lease)

    return success(serialize_quote(quote), "object", 201)


@bp.get("/buyout-quotes")
def list_quotes():
    middleware.require_roles(middleware.ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.buyout_quotes.values())
    lease_filter = request.args.get("lease_id")
    status_filter = request.args.get("status")
    if lease_filter is not None:
        items = [q for q in items if q["lease_id"] == lease_filter]
    if status_filter is not None:
        items = [q for q in items if q["status"] == status_filter]
    items.sort(key=lambda q: (q["created_at"], q["id"]))
    page, pg = paginate(items, limit, offset)
    return success([serialize_quote(q) for q in page], "array", 200, pagination=pg)


@bp.get("/buyout-quotes/<qid>")
def get_quote(qid):
    middleware.require_roles(middleware.ALL_ROLES)
    return success(serialize_quote(_get_quote_or_404(qid)), "object", 200)


@bp.post("/buyout-quotes/<qid>/accept")
def accept_quote(qid):
    user_id, _ = middleware.require_roles({"Driver"})
    q = _get_quote_or_404(qid)
    if q["status"] != "GENERATED":
        raise errors.err(errors.ERR_QUOTE_NOT_GENERATED, "Quote is not GENERATED", 409)
    if clock.now() >= q["_expires_on"]:
        raise errors.err(errors.ERR_QUOTE_EXPIRED, "Quote has expired", 409)
    lease = db.lease_agreements[q["lease_id"]]
    middleware.check_ownership(user_id, lease["owner_operator_id"])
    if lease["status"] not in ("ACTIVE", "DEFAULTED"):
        raise errors.err(errors.ERR_LEASE_NOT_ACTIVE, "Lease must be ACTIVE or DEFAULTED", 409)

    q["status"] = "ACCEPTED"
    touch(q)

    lease["status"] = "COMPLETED"
    touch(lease)

    truck = db.trucks[lease["truck_id"]]
    if truck["status"] == "LEASED":
        truck["status"] = "SOLD"
        touch(truck)

    # Escrow applied to purchase; account closes regardless of remainder
    escrow = escrow_for_lease(lease["id"])
    applied = min(escrow["balance_cents"], q["quoted_price_cents"] + q["arrears_carried_cents"])
    if applied > 0:
        escrow["balance_cents"] -= applied
        escrow["total_applied_cents"] += applied
    escrow["status"] = "CLOSED"
    touch(escrow)

    for lane in db.lane_assignments.values():
        if lane["lease_id"] == lease["id"]:
            if lane["status"] == "ACCEPTED":
                lane["status"] = "COMPLETED"
                touch(lane)
            elif lane["status"] == "OFFERED":
                lane["status"] = "REVOKED"
                touch(lane)

    return success(serialize_quote(q), "object", 200)


@bp.post("/buyout-quotes/<qid>/decline")
def decline_quote(qid):
    user_id, _ = middleware.require_roles({"Driver"})
    q = _get_quote_or_404(qid)
    if q["status"] != "GENERATED":
        raise errors.err(errors.ERR_QUOTE_NOT_GENERATED, "Quote is not GENERATED", 409)
    lease = db.lease_agreements[q["lease_id"]]
    middleware.check_ownership(user_id, lease["owner_operator_id"])
    q["status"] = "DECLINED"
    touch(q)
    return success(serialize_quote(q), "object", 200)
