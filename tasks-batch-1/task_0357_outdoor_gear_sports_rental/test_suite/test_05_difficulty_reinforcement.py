"""Second-angle tests for the depth (Difficulty) instances.

Each test below pins a DISTINCT observable facet of the same §1.8 instance asserted
in test_01–test_03 (a different field, boundary neighbour, or side effect), so every
Difficulty instance carries >= 2 independent assertions. Every assertion is traceable
to a verbatim PRD sentence.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId, TEST_USERS, make_renter_headers,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["shop_admin_headers"]
AGENT = TEST_USERS["rental_agent_headers"]


# ===========================================================================
# dual_variant_calc — second angle: the Customer-domain dual variant
# ===========================================================================

def test_customer_standing_provisional_clear_then_final_suspended_on_loss(api):
    """PRD §3.2: "At check-in, a **provisional** standing is computed from the
    just-created assessment whose `status` is `ASSESSED`, before any loss has been
    ledgered, so the open loss balance may still read 0 even when a loss occurred."
    PRD §3.2: "At settlement, a **final** standing is computed after the `LOSS_FEE` and
    `DAMAGE_FEE` ledger entries have been posted; the freshly posted unsettled loss can
    flip a customer who looked clear at check-in into `SUSPENDED`."
    PRD §3.2: "`open_loss_balance_cents` is the sum of the `amount_cents` of the
    customer's `LOSS_FEE` ledger entries that remain unsettled (`settled` is false)."

    Design: Difficulty/dual_variant_calc/customer_standing_provisional_clear_then_final_suspended_on_loss
    """
    s = fx.setup_picked_up_reservation(category="KAYAK", clock="2026-04-02T09:00:00Z",
                                       pickup_at="2026-04-02T09:00:00Z",
                                       due_at="2026-04-02T11:00:00Z", checkout_rating="GOOD",
                                       reservation_overrides={"damage_waiver_opted": False},
                                       customer_overrides={"email": "lee@x.com", "skill_level": "EXPERT"},
                                       asset_tag="KAY-2")
    res_id = s["reservation"]["id"]
    cust_id = s["customer"]["id"]
    fx.set_clock("2026-04-02T10:30:00Z")
    fx.checkin_reservation(res_id, "LOST")
    # Provisional: loss not yet ledgered -> open loss balance reads 0.
    after_checkin = validate_success(api.get_customer(cust_id, AGENT))
    assert after_checkin["open_loss_balance_cents"] == 0

    fx.settle_reservation(res_id)
    after_settle = validate_success(api.get_customer(cust_id, AGENT))
    assert after_settle["open_loss_balance_cents"] == 20000
    assert after_settle["standing"] == "SUSPENDED"


def test_customer_standing_final_loss_fee_ledger_is_unsettled(api):
    """PRD §3.8: "The system posts a `RENTAL_CHARGE` ledger entry for the rental portion
    together with `LATE_FEE` and `DAMAGE_FEE`/`LOSS_FEE` entries as applicable, each
    entry recording its `reservation_id`, its denormalized `customer_id`, an
    `entry_type`, a signed `amount_cents` (holds and charges positive, refunds
    negative), and a `settled` flag that starts false"
    PRD §3.2: "`open_loss_balance_cents` is the sum of the `amount_cents` of the
    customer's `LOSS_FEE` ledger entries that remain unsettled (`settled` is false)."

    The settle-side driver of the final SUSPENDED standing: the posted LOSS_FEE entry is
    a positive unsettled charge, distinct from the standing/balance read above.

    Design: Difficulty/dual_variant_calc/customer_standing_provisional_clear_then_final_suspended_on_loss
    """
    s = fx.setup_picked_up_reservation(category="KAYAK", clock="2026-04-02T09:00:00Z",
                                       pickup_at="2026-04-02T09:00:00Z",
                                       due_at="2026-04-02T11:00:00Z", checkout_rating="GOOD",
                                       reservation_overrides={"damage_waiver_opted": False},
                                       customer_overrides={"email": "lee2@x.com", "skill_level": "EXPERT"},
                                       asset_tag="KAY-2B")
    res_id = s["reservation"]["id"]
    fx.set_clock("2026-04-02T10:30:00Z")
    fx.checkin_reservation(res_id, "LOST")
    fx.settle_reservation(res_id)
    entries = fx.get_ledger_for_reservation(res_id)
    loss_entries = [e for e in entries if e["entry_type"] == "LOSS_FEE"]
    assert len(loss_entries) == 1
    assert loss_entries[0]["amount_cents"] == 20000
    assert loss_entries[0]["settled"] is False


def test_rental_provisional_total_independent_of_late_at_quote(api):
    """PRD §3.3: "and it is forward-looking — no late or damage charge is included."

    A second-angle check on the provisional vs final divergence: at quote time, even a
    window that will later overrun records a quoted_total_cents with no late component.

    Design: Difficulty/dual_variant_calc/rental_cost_provisional_vs_final_diverges_on_actual_window
    """
    fx.set_clock("2026-04-01T09:00:00Z")
    s = fx.setup_catalog(category="KAYAK", asset_tag="KAY-1C",
                         customer_overrides={"email": "dana3@x.com", "skill_level": "INTERMEDIATE"})
    res = fx.create_reservation(s["customer"]["id"], s["gear_unit"]["id"], s["gear_unit"]["version"],
                                "2026-04-01T09:00:00Z", "2026-04-01T11:00:00Z", actor=AGENT)
    # late_fee_cents is 0 / final_total_cents null until RETURNED.
    assert res["quoted_total_cents"] == 2000
    assert res["late_fee_cents"] == 0
    assert res["final_total_cents"] is None


# ===========================================================================
# combinatorial_formula — second angles
# ===========================================================================

def test_rate_tier_seasonal_flat_chosen_for_long_window(api):
    """PRD §3.3: "the seasonal base is `seasonal_flat_cents` flat regardless of span."
    PRD §3.3: "The chosen base is the smallest of these three, and `quoted_rate_basis`
    records which tier produced it"

    A long multi-day window makes the flat seasonal tier cheapest, exercising the
    >=3-input min from a different winner than the HOURLY tie case.

    Design: Difficulty/combinatorial_formula/rate_tier_min_selection_three_inputs_nonlinear
    """
    fx.set_clock("2026-05-01T08:00:00Z")
    s = fx.setup_catalog(category="SUP", asset_tag="SUP-1L",
                         gear_type_overrides={"name": "Cruiser L", "size_label": "11ft"},
                         customer_overrides={"email": "sam2@x.com", "skill_level": "EXPERT"})
    # 10-day window: span_days=10 -> daily base 3000*10=30000; seasonal flat 20000 cheapest.
    res = fx.create_reservation(s["customer"]["id"], s["gear_unit"]["id"], s["gear_unit"]["version"],
                                "2026-05-01T08:00:00Z", "2026-05-11T08:00:00Z", actor=AGENT)
    assert res["quoted_rate_basis"] == "SEASONAL"
    assert res["quoted_total_cents"] == 20000


def test_addons_no_bundle_discount_under_two_packages(api):
    """PRD §3.4: "A bundle condition holds when the reservation carries at least 2
    `PACKAGE` add-on lines; when it holds, every line's snapshotted `price_cents` is
    multiplied by 0.95, a 5% bundle discount."

    A single PACKAGE line is below the bundle threshold, so its price is undiscounted —
    the complementary boundary to the two-line discounted case.

    Design: Difficulty/combinatorial_formula/addons_round_per_line_then_sum_not_sum_then_round
    """
    fx.set_clock("2026-05-02T08:00:00Z")
    s = fx.setup_catalog(category="SUP", asset_tag="SUP-2S",
                         gear_type_overrides={"name": "Race S", "size_label": "14ft"},
                         customer_overrides={"email": "ivy2@x.com", "skill_level": "EXPERT"})
    ao = fx.create_addon(kind="PACKAGE", category="SUP", name="Dry Bag", price_cents=333)
    cust_id = s["customer"]["id"]
    res = fx.create_reservation(cust_id, s["gear_unit"]["id"], s["gear_unit"]["version"],
                                "2026-05-02T08:00:00Z", "2026-05-02T10:00:00Z", actor=AGENT)
    get_success_data(api.attach_addon(res["id"], {"addon_id": ao["id"]}, AGENT))
    final = validate_success(api.get_reservation(res["id"], AGENT))
    # Single PACKAGE: no discount -> 333; rental 2000 + 333 = 2333.
    assert final["quoted_total_cents"] == 2333


# ===========================================================================
# non_linear_state_machine — second angles
# ===========================================================================

def test_confirm_leaves_lifecycle_confirmed_independent_of_unit(api):
    """PRD §3.5: "When a renter is satisfied with the quote, confirming the reservation
    advances it from `QUOTED` to `CONFIRMED`."
    PRD §3.3: "the unit transitions from `AVAILABLE` to `RESERVED`"

    Confirm advances the lifecycle dimension while the unit stays RESERVED — the two
    parallel axes hold distinct values simultaneously.

    Design: Difficulty/non_linear_state_machine/reservation_parallel_lifecycle_and_payment_dimensions
    """
    s = fx.setup_confirmed_reservation(category="SUP", clock="2026-05-03T08:00:00Z",
                                       pickup_at="2026-05-03T08:00:00Z",
                                       due_at="2026-05-03T10:00:00Z",
                                       customer_overrides={"email": "ana2@x.com", "skill_level": "EXPERT"},
                                       asset_tag="SUP-3B")
    assert s["reservation"]["lifecycle_status"] == "CONFIRMED"
    unit = validate_success(api.get_gear_unit(s["gear_unit"]["id"], AGENT))
    assert unit["availability"] == "RESERVED"


def test_gear_unit_reservable_again_after_full_cycle(api):
    """PRD §3.8: "it returns from `INSPECTING` to `AVAILABLE` when its `condition` is
    `GOOD` or `WORN`"
    PRD §3.3: "A reservation may only be created when the unit's `availability` reads
    `AVAILABLE`"

    After a clean cycle the unit is AVAILABLE again and a fresh reservation succeeds,
    proving the availability machine loops rather than terminating.

    Design: Difficulty/non_linear_state_machine/gear_unit_condition_cycle_returns_to_available
    """
    s = fx.setup_returned_reservation(category="SUP", clock="2026-05-04T08:00:00Z",
                                      pickup_at="2026-05-04T08:00:00Z",
                                      due_at="2026-05-04T10:00:00Z",
                                      return_clock="2026-05-04T09:30:00Z",
                                      checkin_rating="GOOD", asset_tag="SUP-4B")
    fx.settle_reservation(s["reservation"]["id"])
    unit = validate_success(api.get_gear_unit(s["gear_unit"]["id"], AGENT))
    # A new reservation on the recycled unit succeeds (unit re-entered AVAILABLE).
    res2 = fx.create_reservation(s["customer"]["id"], s["gear_unit"]["id"], unit["version"],
                                 "2026-05-04T12:00:00Z", "2026-05-04T14:00:00Z", actor=AGENT)
    assert res2["lifecycle_status"] == "QUOTED"


# ===========================================================================
# transitive_cascade — second angles
# ===========================================================================

def test_loss_checkin_creates_assessment_linked_to_checkin_report(api):
    """PRD §3.6: "The third computation creates a **damage assessment** from the
    check-in report, linked through `checkin_report_id`, with `status` `ASSESSED`."
    PRD §3.6: "If the check-in rating is `LOST`, the `outcome` is `LOSS`"

    The assessment born of the LOST check-in is ASSESSED and carries the loss outcome —
    the first cascade link, distinct from the unit-retire and customer-suspend links.

    Design: Difficulty/transitive_cascade/loss_checkin_cascade_depth3_retire_unit_and_suspend_customer
    """
    s = fx.setup_picked_up_reservation(category="SKI", clock="2026-05-05T08:00:00Z",
                                       pickup_at="2026-05-05T08:00:00Z",
                                       due_at="2026-05-05T10:00:00Z", checkout_rating="GOOD",
                                       reservation_overrides={"damage_waiver_opted": False},
                                       customer_overrides={"email": "cy2@x.com", "skill_level": "EXPERT"},
                                       asset_tag="SKI-1B")
    res_id = s["reservation"]["id"]
    fx.set_clock("2026-05-05T09:30:00Z")
    fx.checkin_reservation(res_id, "LOST")
    assessment = fx.get_assessment_for_reservation(res_id)
    assert assessment["status"] == "ASSESSED"
    assert assessment["outcome"] == "LOSS"
    assert assessment["waiver_applied"] is False


def test_cancel_cascade_clears_active_reservation_pointer(api):
    """PRD §3.9: "releases the unit by moving its `availability` from `RESERVED` back to
    `AVAILABLE` and clearing `active_reservation_id`."
    PRD §3.9: "the `payment_status` moves to `REFUNDED`."

    The cancel cascade's second observable effect — the unit's denormalized
    active_reservation_id back-pointer is cleared, distinct from the deposit refund.

    Design: Difficulty/transitive_cascade/cancel_cascade_depth2_release_unit_and_refund_deposit
    """
    s = fx.setup_confirmed_reservation(category="SKI", clock="2026-05-06T08:00:00Z",
                                       pickup_at="2026-05-06T08:00:00Z",
                                       due_at="2026-05-06T10:00:00Z",
                                       customer_overrides={"email": "del2@x.com", "skill_level": "EXPERT"},
                                       asset_tag="SKI-2B")
    fx.cancel_reservation(s["reservation"]["id"], actor=AGENT)
    unit = validate_success(api.get_gear_unit(s["gear_unit"]["id"], AGENT))
    assert unit["active_reservation_id"] is None
    assert unit["availability"] == "AVAILABLE"


# ===========================================================================
# priority_pair_validation_conflict — second angles
# ===========================================================================

def test_settle_after_reassess_succeeds_once_dispute_cleared(api):
    """PRD §3.7: "settlement of the parent reservation is blocked until the dispute is
    resolved."
    PRD §3.8: "It is gated on the assessment having `status` `ASSESSED` and the unit
    being in `INSPECTING`"
    PRD §3.8: "On success the `payment_status` moves from `DEPOSIT_HELD` to `SETTLED`,
    and the assessment's own `status` moves from `ASSESSED` to `SETTLED`."

    Once the ShopAdmin reassesses the dispute back to ASSESSED, the blocking condition
    lifts and settle proceeds — confirming the dispute block was the sole obstacle.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_settle_disputed_before_anything_else
    """
    s = fx.setup_disputed_assessment(category="SKI", clock="2026-05-07T08:00:00Z",
                                     pickup_at="2026-05-07T08:00:00Z",
                                     due_at="2026-05-07T10:00:00Z",
                                     return_clock="2026-05-07T09:30:00Z",
                                     checkin_rating="DAMAGED", asset_tag="SKI-3B")
    disputed = s["assessment"]
    get_success_data(api.reassess_damage_assessment(
        disputed["id"], {"expected_damage_assessment_version": disputed["version"]}, ADMIN))
    settled = validate_success(api.settle_reservation(s["reservation"]["id"], AGENT))
    assert settled["payment_status"] == "SETTLED"


def test_referential_addon_category_mismatch_returns_unit_not_available(api):
    """PRD §3.4: "The add-on's `category` must match the unit's gear type category, or
    the attach is rejected with `ERR_UNIT_NOT_AVAILABLE`."

    The competing referential failure (priority 5) on a separate add-on attach surfaces
    ERR_UNIT_NOT_AVAILABLE, proving the safety and referential categories are distinct
    and independently reachable.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_lesson_required_before_availability_check
    """
    fx.set_clock("2026-05-08T08:30:00Z")
    s = fx.setup_catalog(category="SKI", asset_tag="SKI-4B",
                         customer_overrides={"email": "fay2@x.com", "skill_level": "EXPERT"})
    # Add-on in a DIFFERENT category than the SKI unit's gear type.
    ao = fx.create_addon(kind="PACKAGE", category="KAYAK", name="Wrong Cat", price_cents=500)
    res = fx.create_reservation(s["customer"]["id"], s["gear_unit"]["id"], s["gear_unit"]["version"],
                                "2026-05-08T09:00:00Z", "2026-05-08T11:00:00Z", actor=AGENT)
    resp = api.attach_addon(res["id"], {"addon_id": ao["id"]}, AGENT)
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_AVAILABLE.value)


# ===========================================================================
# boundary_precision_check — second angles (X+1 / non-empty neighbour)
# ===========================================================================

def test_late_fee_one_minute_past_grace_is_charged(api):
    """PRD §3.6: "Otherwise the late hours are the minutes from the grace deadline to
    `returned_at` divided by 60 and rounded up to a whole number, and `late_fee_cents`
    is `late_fee_cents_per_hour` times that started-hour count."

    The X+1 neighbour of the on-time boundary: one minute past grace_end charges a full
    started hour, confirming the boundary is exclusive on the late side.

    Design: Difficulty/boundary_precision_check/late_fee_exactly_at_grace_boundary_is_on_time
    """
    s = fx.setup_picked_up_reservation(category="SUP", clock="2026-05-09T08:00:00Z",
                                       pickup_at="2026-05-09T08:00:00Z",
                                       due_at="2026-05-09T10:00:00Z", asset_tag="SUP-5B")
    fx.set_clock("2026-05-09T10:16:00Z")
    final = validate_success(
        api.checkin_reservation(s["reservation"]["id"], {"condition_rating": "GOOD"}, AGENT))
    assert final["late_fee_cents"] == 800


def test_non_empty_addon_set_adds_subtotal_to_quote(api):
    """PRD §3.3: "The provisional grand total stored as `quoted_total_cents` is the
    rental amount plus the waiver amount plus the add-ons subtotal (§3.4)"
    PRD §3.4: "the line's `price_cents` is snapshotted from the add-on at attach time."

    The non-empty neighbour of the zero-add-on case: attaching one add-on adds its
    price to the quoted total, so the subtotal is no longer zero.

    Design: Difficulty/boundary_precision_check/empty_addon_set_quote_excludes_addons_subtotal_zero
    """
    fx.set_clock("2026-05-10T08:00:00Z")
    s = fx.setup_catalog(category="SUP", asset_tag="SUP-6B",
                         customer_overrides={"email": "hal2@x.com", "skill_level": "EXPERT"})
    ao = fx.create_addon(kind="PACKAGE", category="SUP", name="Single Pkg", price_cents=500)
    res = fx.create_reservation(s["customer"]["id"], s["gear_unit"]["id"], s["gear_unit"]["version"],
                                "2026-05-10T08:00:00Z", "2026-05-10T10:00:00Z", actor=AGENT)
    get_success_data(api.attach_addon(res["id"], {"addon_id": ao["id"]}, AGENT))
    final = validate_success(api.get_reservation(res["id"], AGENT))
    # rental 2000 + single add-on 500 = 2500.
    assert final["quoted_total_cents"] == 2500


# ===========================================================================
# cross_entity_state_dependency — second angles
# ===========================================================================

def test_checkout_sets_picked_up_timestamp_from_clock(api):
    """PRD §3.6: "Checkout advances the reservation from `CONFIRMED` to `PICKED_UP`,
    stamps `picked_up_at` with the current clock, moves the unit's `availability` from
    `RESERVED` to `CHECKED_OUT`"

    A second observable of the Reservation->GearUnit checkout dependency: picked_up_at
    is stamped, distinct from the lifecycle/availability assertions.

    Design: Difficulty/cross_entity_state_dependency/checkout_requires_gear_unit_reserved
    """
    s = fx.setup_confirmed_reservation(category="KAYAK", clock="2026-05-11T08:00:00Z",
                                       pickup_at="2026-05-11T08:00:00Z",
                                       due_at="2026-05-11T10:00:00Z",
                                       customer_overrides={"email": "ida2@x.com", "skill_level": "EXPERT"},
                                       asset_tag="KAY-3B")
    res = validate_success(
        api.checkout_reservation(s["reservation"]["id"], {"condition_rating": "GOOD"}, AGENT))
    assert res["lifecycle_status"] == "PICKED_UP"
    assert res["picked_up_at"] is not None


def test_suspended_customer_standing_driven_by_open_loss_balance(api):
    """PRD §3.2: "it is `SUSPENDED` whenever the open loss balance is greater than 0
    **or** the strike total is at least 4"
    PRD §3.2: "`open_loss_balance_cents` is the sum of the `amount_cents` of the
    customer's `LOSS_FEE` ledger entries that remain unsettled (`settled` is false)."

    The Reservation->Customer dependency's driver: the suspended standing co-exists with
    a positive open_loss_balance_cents, the underlying cause of the confirm block.

    Design: Difficulty/cross_entity_state_dependency/confirm_blocked_when_customer_suspended
    """
    s = fx.setup_suspended_customer(category="KAYAK", clock="2026-05-12T08:00:00Z",
                                    asset_tag1="KAY-4B")
    customer = validate_success(api.get_customer(s["customer"]["id"], AGENT))
    assert customer["standing"] == "SUSPENDED"
    assert customer["open_loss_balance_cents"] > 0


# ===========================================================================
# resource_temporal_overlap — second angles
# ===========================================================================

def test_lesson_slot_non_intersecting_interval_admits(api):
    """PRD §3.4: "**Slot capacity** is enforced by counting the existing non-cancelled
    `ReservationAddOn` lines for the same `addon_id` whose closed slot interval
    intersects the requested closed interval"
    PRD §3.4: "Each attachment becomes a `ReservationAddOn` line carrying its own
    `reservation_id`, and the line's `price_cents` is snapshotted from the add-on at
    attach time."

    The complementary case to the touching-endpoint collision: a clearly disjoint slot
    on the same capacity-1 add-on is admitted, so the rejection is specific to overlap.

    Design: Difficulty/resource_temporal_overlap/lesson_slot_capacity_closed_interval_touch_collides
    """
    fx.set_clock("2026-05-15T07:00:00Z")
    gt = fx.create_gear_type(category="SKI", name="Lesson Ski 2", size_label="160cm")
    rc = fx.create_rate_card(gt["id"])
    unit1 = fx.create_gear_unit(gt["id"], rc["id"], asset_tag="SKI-6B")
    unit2 = fx.create_gear_unit(gt["id"], rc["id"], asset_tag="SKI-7B")
    ao = fx.create_addon(kind="LESSON", category="SKI", name="Private Ski Lesson 2",
                         price_cents=5000, capacity_per_slot=1)
    cust = fx.create_customer(actor=AGENT, email="lou2@x.com", skill_level="INTERMEDIATE")
    res1 = fx.create_reservation(cust["id"], unit1["id"], unit1["version"],
                                 "2026-05-15T10:00:00Z", "2026-05-15T14:00:00Z", actor=AGENT)
    get_success_data(api.attach_addon(res1["id"], {
        "addon_id": ao["id"], "slot_start_at": "2026-05-15T10:00:00Z",
        "slot_end_at": "2026-05-15T11:00:00Z"}, AGENT))
    res2 = fx.create_reservation(cust["id"], unit2["id"], unit2["version"],
                                 "2026-05-15T10:00:00Z", "2026-05-15T14:00:00Z", actor=AGENT)
    # Slot [12:00,13:00] is disjoint from held [10:00,11:00] -> admitted.
    line = validate_success(api.attach_addon(res2["id"], {
        "addon_id": ao["id"], "slot_start_at": "2026-05-15T12:00:00Z",
        "slot_end_at": "2026-05-15T13:00:00Z"}, AGENT), expected_status=201)
    assert line["addon_id"] == ao["id"]


# ===========================================================================
# compensating_invariant — second angles
# ===========================================================================

def test_cancel_deposit_refund_flips_payment_to_refunded(api):
    """PRD §3.9: "If the reservation's `payment_status` was `DEPOSIT_HELD`, a
    `DEPOSIT_REFUND` ledger entry is written for the negative deposit amount and the
    `payment_status` moves to `REFUNDED`."

    The money-conservation invariant's payment-dimension side: the compensating refund
    moves payment_status to REFUNDED, complementing the net-zero ledger assertion.

    Design: Difficulty/compensating_invariant/cancel_deposit_money_conservation_nets_zero
    """
    s = fx.setup_confirmed_reservation(category="KAYAK", clock="2026-05-16T08:00:00Z",
                                       pickup_at="2026-05-16T08:00:00Z",
                                       due_at="2026-05-16T10:00:00Z",
                                       customer_overrides={"email": "moe2@x.com", "skill_level": "EXPERT"},
                                       asset_tag="KAY-7B")
    cancelled = validate_success(api.cancel_reservation(s["reservation"]["id"], AGENT))
    assert cancelled["payment_status"] == "REFUNDED"


def test_cancel_returns_unit_to_reservable_state(api):
    """PRD §3.9: "releases the unit by moving its `availability` from `RESERVED` back to
    `AVAILABLE` and clearing `active_reservation_id`."
    PRD §3.3: "A reservation may only be created when the unit's `availability` reads
    `AVAILABLE`"

    The inventory-conservation invariant's reusability side: after cancel the released
    unit can be reserved again, proving the AVAILABLE count is genuinely restored.

    Design: Difficulty/compensating_invariant/cancel_inventory_count_conservation_unit_returns_to_available
    """
    fx.set_clock("2026-05-17T08:00:00Z")
    s = fx.setup_catalog(category="KAYAK", asset_tag="KAY-8B",
                         gear_type_overrides={"name": "Fishing 2", "size_label": "L"},
                         customer_overrides={"email": "nia2@x.com", "skill_level": "EXPERT"})
    res = fx.create_reservation(s["customer"]["id"], s["gear_unit"]["id"], s["gear_unit"]["version"],
                                "2026-05-17T08:00:00Z", "2026-05-17T10:00:00Z", actor=AGENT)
    fx.cancel_reservation(res["id"], actor=AGENT)
    unit = validate_success(api.get_gear_unit(s["gear_unit"]["id"], AGENT))
    res2 = fx.create_reservation(s["customer"]["id"], s["gear_unit"]["id"], unit["version"],
                                 "2026-05-17T12:00:00Z", "2026-05-17T14:00:00Z", actor=AGENT)
    assert res2["lifecycle_status"] == "QUOTED"
