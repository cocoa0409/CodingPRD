"""Window-fee tests: the inclusive 48h free-cancel boundary on reschedule, the
no-show cancel band, and the compensating ledger invariant (net refund == quote
minus fee).
"""
from test_helpers import (
    get_success_data, validate_success,
    make_customer_headers,
    setup_booking_world, create_one_time_booking,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _ledger_for(api, booking_id, kind=None):
    params = {"booking_id": booking_id}
    if kind:
        params["kind"] = kind
    return api.list_ledger_entries(ADMIN, params=params).json()["data"]


# ===========================================================================
# Queue A — Rule 6: boundary_precision_check (free-cancel @ 48h on reschedule)
# ===========================================================================
def test_reschedule_at_exactly_48h_incurs_no_fee(api):
    """PRD §3.5: "The boundary is inclusive on the free side: if at least 48
    hours remain, there is no fee."

    With the clock at 2026-06-08T09:00:00Z and start at 2026-06-10T09:00:00Z
    (exactly 48h), a reschedule charges change_fee_cents == 0.

    Design: Difficulty/boundary_precision_check/free_cancel_hours_inclusive_boundary_on_reschedule
    """
    world = setup_booking_world(home_size="STUDIO", clock="2026-06-08T09:00:00Z", loyalty_count=0)
    booking = create_one_time_booking(world, scheduled_start="2026-06-10T09:00:00Z")
    cust_hdr = make_customer_headers(world["customer"]["id"])
    # reschedule to a far-future instant; the fee is keyed off the ORIGINAL hours-to-start
    data = validate_success(
        api.reschedule_booking(booking["id"], {"scheduled_start": "2026-06-25T09:00:00Z"}, cust_hdr)
    )
    assert data["change_fee_cents"] == 0, \
        f"Expected change_fee_cents 0 at exactly 48h (inclusive free side), got {data['change_fee_cents']}"


def test_reschedule_inside_late_band_charges_flat_fee(api):
    """PRD §3.5: "If fewer than 48 hours but at least 12 hours remain, the visit
    is in the late band"
    PRD §3.5: "For a reschedule, the fee in either the late band or the no-show
    band is a flat 1500 cents and is never a percentage."

    With the clock at 2026-06-09T09:00:00Z and start at 2026-06-10T09:00:00Z
    (24h, late band), a reschedule charges a flat change_fee_cents 1500 — one
    band inside the 48h boundary.

    Design: Difficulty/boundary_precision_check/free_cancel_hours_inclusive_boundary_on_reschedule
    """
    world = setup_booking_world(home_size="STUDIO", clock="2026-06-09T09:00:00Z", loyalty_count=0)
    booking = create_one_time_booking(world, scheduled_start="2026-06-10T09:00:00Z")
    cust_hdr = make_customer_headers(world["customer"]["id"])
    data = validate_success(
        api.reschedule_booking(booking["id"], {"scheduled_start": "2026-06-25T09:00:00Z"}, cust_hdr)
    )
    assert data["change_fee_cents"] == 1500, \
        f"Expected flat 1500 reschedule fee inside late band, got {data['change_fee_cents']}"


# ===========================================================================
# Queue A — Rule 9: compensating_invariant (cancel refund nets quote minus fee)
# ===========================================================================
def test_cancel_refund_conserves_charge_minus_fee_late_band(api):
    """PRD §3.5: "in the late band it is 25 percent of the booking's
    `quoted_price_cents`"
    PRD §2.9: "When a booking is cancelled, the refund credits the full
    `quoted_price_cents` back, and any assessed window fee is recorded as a
    separate negative `CHANGE_FEE` entry, so the net refund equals the quoted
    price minus the window fee"

    An 18000 TWO_BR DEEP_CLEAN CLEANER booking cancelled 24h before start (late
    band) yields REFUND 18000, CHANGE_FEE -4500, change_fee_cents 4500, net 13500.

    Design: Difficulty/compensating_invariant/cancel_refund_conserves_customer_charge_minus_fee
    """
    world = setup_booking_world(home_size="TWO_BR", clock="2026-06-09T09:00:00Z", loyalty_count=0)
    booking = create_one_time_booking(
        world, scheduled_start="2026-06-10T09:00:00Z",
        add_ons=["DEEP_CLEAN"], supplies_provided_by="CLEANER",
    )
    assert booking["quoted_price_cents"] == 18000
    cust_hdr = make_customer_headers(world["customer"]["id"])
    cancelled = validate_success(api.cancel_booking(booking["id"], cust_hdr))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["change_fee_cents"] == 4500, \
        f"Expected change_fee_cents 4500 (25% of 18000), got {cancelled['change_fee_cents']}"

    refunds = _ledger_for(api, booking["id"], "REFUND")
    fees = _ledger_for(api, booking["id"], "CHANGE_FEE")
    assert any(e["amount_cents"] == 18000 for e in refunds), \
        f"Expected a REFUND of 18000, got {refunds}"
    assert any(e["amount_cents"] == -4500 for e in fees), \
        f"Expected a CHANGE_FEE of -4500, got {fees}"
    net = sum(e["amount_cents"] for e in refunds) + sum(e["amount_cents"] for e in fees)
    assert net == 13500, f"Expected net refund 13500 (18000 - 4500), got {net}"


def test_cancel_outside_window_full_refund_no_fee(api):
    """PRD §3.5: "Outside the window — 48 hours or more out — both reschedule and
    cancellation incur no fee."
    PRD §2.9: "When a booking is cancelled, the refund credits the full
    `quoted_price_cents` back"

    A STUDIO 6000 booking cancelled far from start (no fee) refunds the full 6000
    with no CHANGE_FEE entry, so the net equals the original charge exactly.

    Design: Difficulty/compensating_invariant/cancel_refund_conserves_customer_charge_minus_fee
    """
    world = setup_booking_world(home_size="STUDIO", clock="2026-06-01T00:00:00Z", loyalty_count=0)
    booking = create_one_time_booking(world, scheduled_start="2026-06-20T09:00:00Z")
    assert booking["quoted_price_cents"] == 6000
    cust_hdr = make_customer_headers(world["customer"]["id"])
    cancelled = validate_success(api.cancel_booking(booking["id"], cust_hdr))
    assert cancelled["change_fee_cents"] == 0, \
        f"Expected change_fee_cents 0 outside window, got {cancelled['change_fee_cents']}"
    refunds = _ledger_for(api, booking["id"], "REFUND")
    fees = _ledger_for(api, booking["id"], "CHANGE_FEE")
    assert any(e["amount_cents"] == 6000 for e in refunds), f"Expected REFUND 6000, got {refunds}"
    assert len(fees) == 0, f"Expected no CHANGE_FEE entry outside window, got {fees}"


# ===========================================================================
# Queue B — Corner: calculations (no-show cancel band)
# ===========================================================================
def test_cancel_fee_noshow_band_is_fifty_percent(api):
    """PRD §3.5: "if fewer than 12 hours remain — which includes any instant at
    or after the start time — the visit is in the no-show band"
    PRD §3.5: "in the no-show band it is 50 percent of `quoted_price_cents`, in
    each case rounded half-up to whole cents."

    An 18000 booking cancelled 6h before start charges change_fee_cents 9000.

    Design: Corner/calculations/cancel_fee_noshow_band_boundary
    """
    world = setup_booking_world(home_size="TWO_BR", clock="2026-06-10T03:00:00Z", loyalty_count=0)
    booking = create_one_time_booking(
        world, scheduled_start="2026-06-10T09:00:00Z",
        add_ons=["DEEP_CLEAN"], supplies_provided_by="CLEANER",
    )
    assert booking["quoted_price_cents"] == 18000
    cust_hdr = make_customer_headers(world["customer"]["id"])
    cancelled = validate_success(api.cancel_booking(booking["id"], cust_hdr))
    assert cancelled["change_fee_cents"] == 9000, \
        f"Expected change_fee_cents 9000 (50% no-show of 18000), got {cancelled['change_fee_cents']}"
