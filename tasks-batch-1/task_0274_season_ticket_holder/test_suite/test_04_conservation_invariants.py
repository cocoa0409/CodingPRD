"""Compensating-action invariants — cancellation conserves seat inventory and
priority points, and reconciles the parking derived counter
(PRD §3.6, §3.8, §3.12).

The forward action (assign -> SOLD, accrue points, add parking pass) and the
compensating cancel action (release -> AVAILABLE, claw back points, release pass)
leave each conserved quantity at its pre-activation value.
"""
from test_helpers import (
    validate_success,
    setup_active_subscription,
    add_parking_pass,
    create_parking_zone,
    TEST_USERS,
)

_BOX = TEST_USERS["box_office_headers"]


# =========================================================================
# Conserved quantity: Section seat inventory
# =========================================================================
def test_cancel_restores_section_available_seats(api):
    """PRD §3.6: "every `ASSIGNED` `SeatAssignment` becomes `RELEASED`, each released
    seat returns to `AVAILABLE` with its section's `available_seats` incremented,
    and `seat_count` is driven to 0."

    A section with 2 seats has available_seats=2; assigning+activating one drops it
    to 1; cancel restores it to 2 (inventory conserved).

    Design: Difficulty/compensating_invariant/cancel_conserves_section_seat_inventory
    """
    ctx = setup_active_subscription(base_price_cents=200000, section_name="Cons Sec")
    section_id = ctx["section"]["id"]
    # Add a second seat to the section so available_seats started at 2.
    from test_helpers import create_seat
    create_seat(section_id, row_label="T", seat_number=2)
    before = validate_success(api.get_section(section_id, _BOX))
    # one seat SOLD via the active subscription, one AVAILABLE
    assert before["total_seats"] == 2, before["total_seats"]
    assert before["available_seats"] == 1, before["available_seats"]
    validate_success(api.cancel_subscription(ctx["subscription"]["id"], _BOX))
    after = validate_success(api.get_section(section_id, _BOX))
    assert after["available_seats"] == 2, after["available_seats"]


def test_cancel_releases_seat_and_zeroes_seat_count(api):
    """PRD §3.6: "each released seat returns to `AVAILABLE` ... and `seat_count` is
    driven to 0."

    The released seat returns to AVAILABLE and the subscription's seat_count is 0.

    Design: Difficulty/compensating_invariant/cancel_conserves_section_seat_inventory
    """
    ctx = setup_active_subscription(base_price_cents=200000, section_name="Cons Sec2")
    seat_id = ctx["seat"]["id"]
    sub = validate_success(api.cancel_subscription(ctx["subscription"]["id"], _BOX))
    assert sub["seat_count"] == 0, sub["seat_count"]
    seat = validate_success(api.get_seat(seat_id, _BOX))
    assert seat["status"] == "AVAILABLE", seat["status"]


# =========================================================================
# Conserved quantity: Account priority points
# =========================================================================
def test_cancel_claws_back_priority_points(api):
    """PRD §3.6: "the priority points that were granted to the account at this
    subscription's activation and renewals are clawed back by subtracting that
    granted total from the account's `priority_points`, after which the loyalty tier
    is recomputed."
    PRD §3.8: "Because the points granted for a subscription are tracked,
    cancellation can later claw back exactly that granted total."

    Activation accrued 100 points (0->100); cancel claws back exactly 100 (->0).

    Design: Difficulty/compensating_invariant/cancel_conserves_account_priority_points
    """
    ctx = setup_active_subscription(
        base_price_cents=200000, plan_type="FULL", price_multiplier_bps=10000,
        includes_playoffs=False, consecutive_seasons=0, section_name="Pts Sec",
    )
    account_id = ctx["account"]["id"]
    accrued = validate_success(api.get_account(account_id, _BOX))
    assert accrued["priority_points"] == 100, accrued["priority_points"]
    validate_success(api.cancel_subscription(ctx["subscription"]["id"], _BOX))
    after = validate_success(api.get_account(account_id, _BOX))
    assert after["priority_points"] == 0, after["priority_points"]


def test_cancel_recomputes_loyalty_tier_to_bronze(api):
    """PRD §3.6: "the priority points that were granted to the account at this
    subscription's activation and renewals are clawed back by subtracting that
    granted total from the account's `priority_points`, after which the loyalty tier
    is recomputed."
    PRD §3.2: "An account sits at `BRONZE` while its points are below 500."

    After the clawback to 0 points the tier recomputes to BRONZE.

    Design: Difficulty/compensating_invariant/cancel_conserves_account_priority_points
    """
    ctx = setup_active_subscription(
        base_price_cents=200000, plan_type="FULL", price_multiplier_bps=10000,
        includes_playoffs=False, consecutive_seasons=0, section_name="Pts Sec2",
    )
    account_id = ctx["account"]["id"]
    validate_success(api.cancel_subscription(ctx["subscription"]["id"], _BOX))
    after = validate_success(api.get_account(account_id, _BOX))
    assert after["loyalty_tier"] == "BRONZE", after["loyalty_tier"]


# =========================================================================
# Corner — derived-field reconciliation: cancel releases parking add-on
# =========================================================================
def test_cancel_releases_parking_addon_and_reconciles_count(api):
    """PRD §3.6: "every `ACTIVE` `ParkingAddOn` becomes `RELEASED`, decrementing its
    zone's `active_pass_count`."
    PRD §3.12: "Releasing a pass moves its `status` to `RELEASED` and decrements the
    zone's `active_pass_count`; this happens as part of the cancellation cascade in
    §3.6."

    A subscription with one ACTIVE pass (count 1) is cancelled -> pass RELEASED and
    zone active_pass_count back to 0.

    Design: Corner/cross_cutting_complexity_layers/cancel_releases_parking_addon_derived_count_reconciled
    """
    ctx = setup_active_subscription(base_price_cents=200000, section_name="PkCancel Sec")
    zone = create_parking_zone(capacity=10, name="Lot Cancel")
    addon = add_parking_pass(ctx["subscription"]["id"], zone["id"])
    zone_before = validate_success(api.get_parking_zone(zone["id"], _BOX))
    assert zone_before["active_pass_count"] == 1, zone_before["active_pass_count"]
    validate_success(api.cancel_subscription(ctx["subscription"]["id"], _BOX))
    addon_after = validate_success(api.get_parking_addon(addon["id"], _BOX))
    assert addon_after["status"] == "RELEASED", addon_after["status"]
    zone_after = validate_success(api.get_parking_zone(zone["id"], _BOX))
    assert zone_after["active_pass_count"] == 0, zone_after["active_pass_count"]
