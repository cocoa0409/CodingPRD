"""In-memory data store and the logical clock (PRD 2.4).

Every collection starts EMPTY on every boot. Nothing is ever seeded here:
callers construct every entity through the declared API surface.
"""
from datetime import datetime

from util import UTC, dec, days_between, fmt_ts, jnum, new_id, now_wall

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

COLLECTIONS = (
    "events",
    "rights_deals",
    "release_tranches",
    "allocation_blocks",
    "package_products",
    "package_components",
    "clients",
    "bookings",
    "payment_installments",
    "hospitality_builds",
    "on_site_hosts",
    "host_assignments",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_DEFAULT
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def logical_now():
    return db.clock


def set_logical_now(dt):
    db.clock = dt


# --- record lifecycle -------------------------------------------------------


def create_record(collection, fields):
    """Mint a record with the four common properties (PRD 2.4)."""
    stamp = now_wall()
    record = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }
    record.update(fields)
    collection[record["id"]] = record
    return record


def touch(record):
    """A genuine mutation: refresh updated_at and bump version (PRD 2.9)."""
    record["updated_at"] = now_wall()
    record["version"] += 1
    return record


def update_record(record, changes, force=False):
    """Apply `changes`; count it as one mutation when something actually moved."""
    changed = False
    for key, value in changes.items():
        if record.get(key) != value:
            record[key] = value
            changed = True
    if changed or force:
        touch(record)
    return changed


def apply_silent(record, changes):
    """Refresh derived values without recording a mutation (used on pure reads)."""
    changed = False
    for key, value in changes.items():
        if record.get(key) != value:
            record[key] = value
            changed = True
    return changed


def order_key(record):
    """Canonical ordering: created_at ascending; never `id` (PRD 2.5)."""
    return (record["created_at"], record["_seq"])


def sorted_records(records):
    return sorted(records, key=order_key)


def all_of(collection):
    return sorted_records(list(collection.values()))


# --- serialisation ---------------------------------------------------------


def _common(record):
    return {
        "id": record["id"],
        "created_at": fmt_ts(record["created_at"]),
        "updated_at": fmt_ts(record["updated_at"]),
        "version": record["version"],
    }


def event_json(record):
    out = _common(record)
    out.update(
        {
            "name": record["name"],
            "sport": record["sport"],
            "venue_name": record["venue_name"],
            "hospitality_zone_codes": list(record["hospitality_zone_codes"]),
            "event_date": fmt_ts(record["event_date"]),
            "original_event_date": fmt_ts(record["original_event_date"]),
            "status": record["status"],
            "rebook_deadline_at": fmt_ts(record["rebook_deadline_at"]),
            "postponement_count": record["postponement_count"],
            "fulfillment_risk_score": record["fulfillment_risk_score"],
            "risk_posture": record["risk_posture"],
        }
    )
    return out


def rights_deal_json(record):
    out = _common(record)
    out.update(
        {
            "event_id": record["event_id"],
            "rights_holder_name": record["rights_holder_name"],
            "inventory_type": record["inventory_type"],
            "contracted_units": record["contracted_units"],
            "guaranteed_minimum_units": record["guaranteed_minimum_units"],
            "unit_cost_cents": record["unit_cost_cents"],
            "deal_status": record["deal_status"],
            "released_units": record["released_units"],
            "shortfall_units": record["shortfall_units"],
            "unallocated_units": record["unallocated_units"],
            "minimum_liability_cents": record["minimum_liability_cents"],
            "committed_by_user_id": record["committed_by_user_id"],
            "settled_at": fmt_ts(record["settled_at"]),
        }
    )
    return out


def release_tranche_json(record):
    out = _common(record)
    out.update(
        {
            "rights_deal_id": record["rights_deal_id"],
            "promised_units": record["promised_units"],
            "promised_release_at": fmt_ts(record["promised_release_at"]),
            "tranche_state": record["tranche_state"],
            "confirmed_units": record["confirmed_units"],
            "confirmed_at": fmt_ts(record["confirmed_at"]),
            "lapsed_at": fmt_ts(record["lapsed_at"]),
        }
    )
    return out


def allocation_block_json(record):
    out = _common(record)
    out.update(
        {
            "rights_deal_id": record["rights_deal_id"],
            "channel": record["channel"],
            "target_units": record["target_units"],
            "priority_rank": record["priority_rank"],
            "allocated_units": record["allocated_units"],
            "committed_units": record["committed_units"],
            "released_back_units": record["released_back_units"],
            "block_state": record["block_state"],
            "recalled_at": fmt_ts(record["recalled_at"]),
        }
    )
    return out


def package_product_json(record):
    out = _common(record)
    out.update(
        {
            "event_id": record["event_id"],
            "name": record["name"],
            "tier": record["tier"],
            "tickets_per_package": record["tickets_per_package"],
            "hotel_nights": record["hotel_nights"],
            "transport_included": record["transport_included"],
            "min_margin_pct": jnum(record["min_margin_pct"]),
            "package_status": record["package_status"],
            "base_cost_cents": record["base_cost_cents"],
            "component_price_subtotal_cents": record["component_price_subtotal_cents"],
            "list_price_cents": record["list_price_cents"],
            "margin_pct": jnum(record["margin_pct"]),
            "priced_by_user_id": record["priced_by_user_id"],
            "priced_at": fmt_ts(record["priced_at"]),
            "published_by_user_id": record["published_by_user_id"],
            "published_at": fmt_ts(record["published_at"]),
        }
    )
    return out


def package_component_json(record):
    out = _common(record)
    out.update(
        {
            "package_product_id": record["package_product_id"],
            "component_type": record["component_type"],
            "descriptor": record["descriptor"],
            "quantity": record["quantity"],
            "unit_cost_cents": record["unit_cost_cents"],
            "markup_pct": jnum(record["markup_pct"]),
            "sequence_no": record["sequence_no"],
            "line_cost_cents": record["line_cost_cents"],
            "line_price_cents": record["line_price_cents"],
        }
    )
    return out


def client_json(record):
    out = _common(record)
    out.update(
        {
            "name": record["name"],
            "client_type": record["client_type"],
            "credit_limit_cents": record["credit_limit_cents"],
            "client_status": record["client_status"],
            "outstanding_cents": record["outstanding_cents"],
            "overdue_installment_count": record["overdue_installment_count"],
        }
    )
    return out


def booking_json(record):
    out = _common(record)
    out.update(
        {
            "client_id": record["client_id"],
            "package_product_id": record["package_product_id"],
            "allocation_block_id": record["allocation_block_id"],
            "channel": record["channel"],
            "units": record["units"],
            "risk_override_ack": record["risk_override_ack"],
            "gross_price_cents": record["gross_price_cents"],
            "volume_discount_pct": jnum(record["volume_discount_pct"]),
            "discounted_subtotal_cents": record["discounted_subtotal_cents"],
            "partner_commission_cents": record["partner_commission_cents"],
            "guarantee_surcharge_cents": record["guarantee_surcharge_cents"],
            "net_price_cents": record["net_price_cents"],
            "paid_cents": record["paid_cents"],
            "cancellation_fee_cents": record["cancellation_fee_cents"],
            "refund_cents": record["refund_cents"],
            "balance_due_cents": record["balance_due_cents"],
            "settlement_variant": record["settlement_variant"],
            "payment_status": record["payment_status"],
            "fulfillment_status": record["fulfillment_status"],
            "credentials_issued_count": record["credentials_issued_count"],
            "credential_serial_prefix": record["credential_serial_prefix"],
            "itinerary": record["itinerary"],
            "rebook_count": record["rebook_count"],
        }
    )
    return out


def payment_installment_json(record):
    out = _common(record)
    overdue_days = 0
    if record["installment_state"] == "OVERDUE":
        overdue_days = max(0, days_between(record["due_at"], logical_now()))
    out.update(
        {
            "booking_id": record["booking_id"],
            "sequence_no": record["sequence_no"],
            "amount_cents": record["amount_cents"],
            "due_at": fmt_ts(record["due_at"]),
            "installment_kind": record["installment_kind"],
            "installment_state": record["installment_state"],
            "paid_amount_cents": record["paid_amount_cents"],
            "paid_at": fmt_ts(record["paid_at"]),
            "days_overdue": overdue_days,
        }
    )
    return out


def hospitality_build_json(record):
    out = _common(record)
    out.update(
        {
            "event_id": record["event_id"],
            "zone_code": record["zone_code"],
            "service_window_start": fmt_ts(record["service_window_start"]),
            "service_window_end": fmt_ts(record["service_window_end"]),
            "space_units": record["space_units"],
            "catering_covers": record["catering_covers"],
            "staff_count": record["staff_count"],
            "build_cost_cents": record["build_cost_cents"],
            "catering_cost_cents": record["catering_cost_cents"],
            "staffing_cost_cents": record["staffing_cost_cents"],
            "build_state": record["build_state"],
            "approved_by_user_id": record["approved_by_user_id"],
            "total_cost_cents": record["total_cost_cents"],
        }
    )
    return out


def on_site_host_json(record):
    out = _common(record)
    out.update(
        {
            "full_name": record["full_name"],
            "languages": list(record["languages"]),
            "max_concurrent_bookings": record["max_concurrent_bookings"],
            "active_assignment_count": record["active_assignment_count"],
        }
    )
    return out


def host_assignment_json(record):
    out = _common(record)
    out.update(
        {
            "on_site_host_id": record["on_site_host_id"],
            "booking_id": record["booking_id"],
            "hospitality_build_id": record["hospitality_build_id"],
            "shift_start": fmt_ts(record["shift_start"]),
            "shift_end": fmt_ts(record["shift_end"]),
            "assignment_state": record["assignment_state"],
            "released_at": fmt_ts(record["released_at"]),
        }
    )
    return out
