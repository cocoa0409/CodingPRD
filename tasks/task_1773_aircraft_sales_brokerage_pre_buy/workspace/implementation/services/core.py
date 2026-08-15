"""Record lifecycle: creation, mutation touch, serialization.

Common fields (PRD 2.4): id (UUID), created_at / updated_at (ISO 8601 UTC,
three fractional digits), version (starts at 1, +1 on every mutation,
including mutations produced by automatic cascades, PRD 2.7).
"""
from decimal import Decimal

import db as dbmod
from util import new_id, now_ts

PUBLIC_FIELDS = {
    "facilities": [
        "id", "name", "airport_code", "turnaround_buffer_minutes",
        "created_at", "updated_at", "version",
    ],
    "listings": [
        "id", "tail_number", "make", "model", "year", "total_time_hours",
        "asking_price_usd", "seller_name", "market_value_estimate_usd",
        "valuation_status", "status", "created_at", "updated_at", "version",
    ],
    "buyers": [
        "id", "full_name", "email", "qualification_status",
        "qualified_budget_usd", "proof_of_funds_ref",
        "created_at", "updated_at", "version",
    ],
    "comps": [
        "id", "make", "model", "year", "sale_price_usd", "sale_date",
        "total_time_hours", "comp_status", "source_listing_id",
        "created_at", "updated_at", "version",
    ],
    "lois": [
        "id", "listing_id", "buyer_id", "offer_price_usd",
        "current_price_usd", "deposit_amount_usd", "dual_agency",
        "disclosure_status", "buyer_acked", "seller_acked", "status",
        "created_at", "updated_at", "version",
    ],
    "transactions": [
        "id", "loi_id", "listing_id", "buyer_id", "agreed_price_usd",
        "dual_agency", "status", "logbook_complete",
        "registration_docs_complete", "tax_planning_notes",
        "credits_total_usd", "commission_amount_usd",
        "settlement_buyer_due_usd", "settlement_seller_net_usd",
        "termination_reason", "created_at", "updated_at", "version",
    ],
    "escrows": [
        "id", "transaction_id", "escrow_ref", "deposit_amount_usd", "status",
        "funding_reference", "released_usd", "refunded_usd", "forfeited_usd",
        "created_at", "updated_at", "version",
    ],
    "bookings": [
        "id", "transaction_id", "facility_id", "start_at", "end_at", "status",
        "created_at", "updated_at", "version",
    ],
    "discrepancies": [
        "id", "transaction_id", "inspection_booking_id", "description",
        "severity", "estimated_cost_usd", "proposed_credit_usd",
        "credit_amount_usd", "resolution", "status",
        "created_at", "updated_at", "version",
    ],
}


def new_record(collection, fields):
    ts = now_ts()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": dbmod.next_seq(),
    }
    rec.update(fields)
    dbmod.db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    """Refresh updated_at and bump version by one (one per mutation event)."""
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 1) + 1


def serialize(collection, rec):
    out = {}
    for field in PUBLIC_FIELDS[collection]:
        value = rec.get(field)
        if isinstance(value, Decimal):
            # Monetary values render as numbers with at most two decimals.
            value = float(value)
        out[field] = value
    return out


def list_page(collection, filters):
    """Filter -> sort by creation order -> paginate -> serialize.

    filters: iterable of query-param names matched by exact string equality.
    """
    from flask import request

    from response import success_list
    from validate import page_params

    items = list(dbmod.db[collection].values())
    for param in filters:
        value = request.args.get(param)
        if value is not None:
            items = [r for r in items if r.get(param) == value]
    items.sort(key=lambda r: r["_seq"])
    total = len(items)
    limit, offset = page_params()
    page = items[offset:offset + limit]
    return success_list(
        [serialize(collection, r) for r in page], limit, offset, total
    )
