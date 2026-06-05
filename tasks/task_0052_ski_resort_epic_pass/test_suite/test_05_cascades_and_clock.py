"""Deep cascades: refund approval (depth-3: request -> pass -> buddy tickets) and
the seasonal-clock auto-expiry (depth-2: clock -> pass -> buddy tickets).
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    fixtures,
)

ADMIN = TEST_USERS["network_admin_headers"]
OPS = TEST_USERS["resort_ops_headers"]
REFUND = TEST_USERS["refund_admin_headers"]


def test_refund_approve_depth3_cascade(api):
    """PRD §3.5: "the referenced pass cascades from `ACTIVE` to `REFUNDED`. That
    pass transition itself cancels every still-`RESERVED` buddy ticket of the pass
    and recomputes the pass's `buddy_tickets_remaining`, and the pass's `version`
    increments by one."

    Design: Difficulty/transitive_cascade/refund_approve_depth3_cascade
    """
    fixtures.set_clock(api, "2026-01-12T08:00:00Z")
    product = fixtures.create_product(
        api, tier="LOCAL", price_cents=6000, buddy_ticket_allotment=2,
        buddy_ticket_price_cents=2000, ikon_interchange_enabled=False,
    )
    resort = fixtures.create_resort(api, name="Heavenly", home_network="EPIC", gate_count=2)
    issued = fixtures.issue_pass(api, product["id"], holder_name="Cascade Holder")
    token = issued["magnetic_token"]
    fixtures.activate_pass(api, issued["id"])
    bt1 = fixtures.reserve_buddy(api, issued["id"], resort["id"], "2026-01-13", guest_name="G1")
    bt2 = fixtures.reserve_buddy(api, issued["id"], resort["id"], "2026-01-14", guest_name="G2")
    validate_success(
        api.scan_pass(issued["id"], {"resort_id": resort["id"], "presented_token": token}, OPS),
        201,
    )
    rr = fixtures.open_refund(api, issued["id"], reason="INJURY")
    pass_now = fixtures.get_pass(api, issued["id"], headers=REFUND)
    approved = validate_success(
        fixtures.approve_refund(api, rr["id"], pass_now["version"]), 200
    )
    assert approved["status"] == "APPROVED"
    pass_after = fixtures.get_pass(api, issued["id"], headers=REFUND)
    assert pass_after["status"] == "REFUNDED", "approve cascades pass ACTIVE->REFUNDED"
    assert validate_success(api.get_buddy_ticket(bt1["id"], OPS), 200)["status"] == "CANCELLED"
    assert validate_success(api.get_buddy_ticket(bt2["id"], OPS), 200)["status"] == "CANCELLED"
    assert pass_after["buddy_tickets_remaining"] == 2, \
        "cancelling both RESERVED tickets recomputes remaining to full allotment 2"


def test_refund_approve_cascade_terminates_pass_and_single_buddy(api):
    """PRD §3.5: "the referenced pass cascades from `ACTIVE` to `REFUNDED`. That
    pass transition itself cancels every still-`RESERVED` buddy ticket of the pass
    and recomputes the pass's `buddy_tickets_remaining`".

    Design: Difficulty/transitive_cascade/refund_approve_depth3_cascade
    """
    fixtures.set_clock(api, "2026-01-13T08:00:00Z")
    product = fixtures.create_product(
        api, tier="LOCAL", price_cents=4000, buddy_ticket_allotment=1,
        buddy_ticket_price_cents=1000, ikon_interchange_enabled=False,
    )
    resort = fixtures.create_resort(api, name="Heavenly2", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="Cascade Holder 2")
    fixtures.activate_pass(api, issued["id"])
    bt = fixtures.reserve_buddy(api, issued["id"], resort["id"], "2026-01-14", guest_name="G1")
    assert fixtures.get_pass(api, issued["id"])["buddy_tickets_remaining"] == 0
    rr = fixtures.open_refund(api, issued["id"], reason="INJURY")
    pass_now = fixtures.get_pass(api, issued["id"], headers=REFUND)
    validate_success(fixtures.approve_refund(api, rr["id"], pass_now["version"]), 200)
    pass_after = fixtures.get_pass(api, issued["id"], headers=REFUND)
    assert pass_after["status"] == "REFUNDED"
    assert validate_success(api.get_buddy_ticket(bt["id"], OPS), 200)["status"] == "CANCELLED", \
        "the single RESERVED buddy ticket is cancelled by the refund cascade"
    assert pass_after["buddy_tickets_remaining"] == 1, \
        "remaining recomputed back to the full allotment 1 after the cancel"


def test_clock_advance_past_season_end_expiry_depth2_cascade(api):
    """PRD §3.6: "When the clock is set to a date later than the configured
    season-end date, every pass that is currently `ACTIVE` auto-transitions from
    `ACTIVE` to `EXPIRED`. Each such auto-expiry is a system-actor transition that
    cascades exactly like a suspension or refund: every still-`RESERVED` buddy
    ticket of the expiring pass moves to `CANCELLED`, the pass's
    `buddy_tickets_remaining` is recomputed, and the pass's `version` increments by
    one."

    Design: Difficulty/transitive_cascade/clock_advance_expiry_depth2_cascade
    """
    fixtures.set_clock(api, "2026-04-01T08:00:00Z")
    product = fixtures.create_product(
        api, tier="LOCAL", price_cents=5000, buddy_ticket_allotment=1,
        buddy_ticket_price_cents=1500, ikon_interchange_enabled=False,
    )
    resort = fixtures.create_resort(api, name="Stowe", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="Expiry Holder")
    fixtures.activate_pass(api, issued["id"])
    bt = fixtures.reserve_buddy(api, issued["id"], resort["id"], "2026-04-02", guest_name="G1")
    # Advance well past any single ski season's end.
    fixtures.set_clock(api, "2027-06-01T08:00:00Z")
    pass_after = fixtures.get_pass(api, issued["id"])
    assert pass_after["status"] == "EXPIRED", "clock past season end auto-expires the ACTIVE pass"
    assert validate_success(api.get_buddy_ticket(bt["id"], OPS), 200)["status"] == "CANCELLED"
    assert pass_after["buddy_tickets_remaining"] == 1, \
        "the expiring pass's RESERVED ticket cancels, recomputing remaining to allotment 1"


def test_clock_expiry_is_system_triggered_from_active(api):
    """PRD §3.6: "When the clock is set to a date later than the configured
    season-end date, every pass that is currently `ACTIVE` auto-transitions from
    `ACTIVE` to `EXPIRED`. Each such auto-expiry is a system-actor transition".

    Design: Difficulty/transitive_cascade/clock_advance_expiry_depth2_cascade
    """
    fixtures.set_clock(api, "2026-03-15T08:00:00Z")
    product = fixtures.create_product(api, tier="FULL_EPIC", price_cents=8000)
    issued = fixtures.issue_pass(api, product["id"], holder_name="Expiry Holder 2")
    active = fixtures.activate_pass(api, issued["id"])
    assert active["status"] == "ACTIVE"
    # No buddy tickets here — isolate the pass-level auto-expiry itself.
    fixtures.set_clock(api, "2027-06-01T08:00:00Z")
    pass_after = fixtures.get_pass(api, issued["id"])
    assert pass_after["status"] == "EXPIRED", \
        "advancing the clock past season end auto-transitions the ACTIVE pass to EXPIRED"
    assert pass_after["version"] > active["version"], \
        "the auto-expiry is a mutation that increments the pass version"
