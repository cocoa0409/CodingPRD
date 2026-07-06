"""Corner queue — errors section.

Excluded stub: delivery_slot_conflict — owned by difficulty rule 8
instance A in test_08.
SKIPPED (silence pattern applied): stale_order_version_on_reserve —
after a cancel the order is CANCELLED, and PRD §3.9 firmly places the
state check (priority 6) BEFORE OCC (priority 7), so a PRD-only reader
would return ERR_INVALID_STATE, not ERR_STALE_ORDER_VERSION. The
instance therefore fails the unique-derivability condition of the
PRD-first Core rule.
"""
from test_helpers import (
    validate_error, api_client, ApiErrorId,
    make_store_manager_headers, make_store_clerk_headers,
)
from test_helpers.fixtures import (
    set_clock, create_customer, create_sku_with_stock, create_sku,
    setup_draft_order, create_event_package, create_event_booking,
    restock_sku,
)


def test_event_cancel_within_7_days_returns_cancel_too_late():
    """PRD §3.8: "Cancelling an event booking transitions HELD or
    CONFIRMED to CANCELLED, but only while event_date minus the server
    clock is at least seven days; a later cancellation attempt is
    rejected with ERR_EVENT_CANCEL_TOO_LATE."

    Design: Corner/errors/event_cancel_too_late_within_7_days
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=5)
    pkg = create_event_package(base_price_cents=30000, deposit_pct=0.20,
                                 min_lead_days=3)
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    # event_date only 3 days away → cancel is < 7 days.
    booking = create_event_booking(order["id"], pkg["id"],
                                    "2026-06-18T18:00:00Z")
    resp = api_client.cancel_event_booking(
        booking["id"], make_store_clerk_headers()
    )
    validate_error(resp, ApiErrorId.ERR_EVENT_CANCEL_TOO_LATE)


def test_stale_sku_version_on_clearance_returns_412():
    """PRD §2.11: "Applying clearance to a SKU requires the payload to
    carry expected_sku_version as a non-optional input field, matching
    the current version of the target Sku. If the SKU has been repriced
    or unclearanced since the client last read it, the request is
    rejected with ERR_STALE_SKU_VERSION and HTTP 412 — the caller's
    chosen clearance_pct was picked against a stale unit_price_cents."

    Design: Corner/errors/stale_sku_version_on_clearance
    """
    sku_v1 = create_sku(unit_price_cents=500, category="DECOR")
    # Another writer bumps version by restocking.
    sku_v2 = restock_sku(sku_v1["id"], 5)
    assert sku_v2["version"] > sku_v1["version"]
    # Client attempts clearance with the pre-restock version.
    resp = api_client.clearance_sku(
        sku_v1["id"],
        {"pct": 0.20, "expected_sku_version": sku_v1["version"]},
        make_store_manager_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_SKU_VERSION)
