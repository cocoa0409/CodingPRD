"""The three capacity axes, the derived posture, unit conservation, and the
lock / cutoff-extension loop on the pre-order window."""
import pytest
from test_helpers import (
    ApiErrorId,
    CLOCK_AT_CUTOFF,
    WINDOW_BATCH_SLOT_CAPACITY_DEFAULT,
    WINDOW_OVEN_HOURS_CAPACITY_DEFAULT,
    WINDOW_UNIT_CAPACITY_DEFAULT,
    add_line,
    add_menu_item,
    api_client,
    assert_offer_window,
    assert_same_instant,
    assert_window_unit_conservation,
    confirm_order,
    create_window,
    instant_plus,
    lock_window,
    open_order,
    read_capacity,
    read_compliance,
    read_line,
    read_order,
    read_window,
    setup_held_order,
    setup_storefront,
    validate_error,
    validate_success,
    window_version,
)


def test_a_new_window_starts_on_its_three_declared_initial_states(api):
    """PRD §3.4: "A new window begins with `window_status` `DRAFT`, `plan_status`
    `UNPLANNED`, `capacity_posture` `OPEN_CAPACITY`, and `cutoff_extension_count`
    at 0."
    PRD §2.9: "`capacity_units` is the count of orderable units the window will
    sell and defaults to 240."

    Design: Corner/state_machines/offer_window_initial_state_on_all_three_axes
    """
    s = setup_storefront(open_window=False, clock=None)
    window = validate_success(
        api.create_offer_window(
            {
                "baker_id": s.baker_id,
                "label": "Fresh window",
                "opens_at": "2026-05-04T00:00:00Z",
                "order_cutoff_at": "2026-05-06T12:00:00Z",
                "production_date": "2026-05-07T06:00:00Z",
                "handoff_date": "2026-05-07T15:00:00Z",
                "handoff_window_end_at": "2026-05-07T19:00:00Z",
            },
            s.bh,
        ),
        201,
    )
    assert_offer_window(window)
    assert window["window_status"] == "DRAFT"
    assert window["plan_status"] == "UNPLANNED"
    assert window["capacity_posture"] == "OPEN_CAPACITY"
    assert window["capacity_units"] == WINDOW_UNIT_CAPACITY_DEFAULT
    assert window["capacity_batch_slots"] == WINDOW_BATCH_SLOT_CAPACITY_DEFAULT
    assert window["capacity_oven_hours"] == pytest.approx(
        WINDOW_OVEN_HOURS_CAPACITY_DEFAULT
    )
    assert window["cutoff_extension_count"] == 0
    assert window["version"] == 1


def test_capacity_read_reports_all_three_axes_for_a_held_line(api):
    """PRD §3.4: "Anyone with an interest in the window may read its computed
    capacity, which recomputes and reports `units_remaining`,
    `batch_slots_remaining`, `oven_hours_remaining`, `capacity_posture`,
    `confirmed_units`, `held_units`, `reserved_units`, `slots_used`, and
    `oven_hours_used`, all as defined in §2.9."
    PRD §2.9: "`slot_count` is that demand divided by the 24 units a slot holds and
    **rounded up** to a whole slot"
    PRD §2.9: "When a menu item's `oven_profile` is `STANDARD`, its oven hours are
    its `slot_count` multiplied by the fixed 1.5 hours a slot costs"

    Design: Corner/endpoints/offer_window_capacity_computed_read_reports_all_three_axes
    """
    s = setup_held_order(quantity=25)
    capacity = validate_success(api.get_offer_window_capacity(s.window_id, s.bh))
    assert capacity["units_remaining"] == 215
    assert capacity["batch_slots_remaining"] == 10
    assert capacity["oven_hours_remaining"] == pytest.approx(15.0)
    assert capacity["slots_used"] == 2
    assert capacity["oven_hours_used"] == pytest.approx(3.0)
    assert capacity["held_units"] == 25
    assert capacity["confirmed_units"] == 0
    assert capacity["reserved_units"] == 0
    assert capacity["capacity_posture"] == "OPEN_CAPACITY"
    # 25 units under the baker's-dozen basis: one block of 13 at 4600 plus 12 at 450.
    assert read_line(s.line_id, s.ch)["line_total_cents"] == 10000


def test_posture_stays_open_capacity_while_a_batch_slot_remains(api):
    """PRD §2.9: "the posture is `CONSTRAINED` when the greatest of those three
    utilisations is at or above 0.80 — the comparison is inclusive — and
    `OPEN_CAPACITY` otherwise."
    PRD §2.9: "`capacity_batch_slots` is the number of slots the oven schedule has
    room for and defaults to 12."

    Design: Difficulty/combinatorial_formula/capacity_posture_nested_max_exhausts_on_slots_while_units_idle
    """
    s = setup_storefront(
        window_overrides={
            "label": "Slot-tight Wed",
            "capacity_units": 240,
            "capacity_batch_slots": 2,
            "capacity_oven_hours": 18.0,
        }
    )
    add_menu_item(s, kind="loaf")
    order = open_order(s.customer_id, s.window_id)
    add_line(order["id"], s.cookie_id, 1, s.customer_id, s.window_id)

    window = read_window(s.window_id, s.ch)
    assert window["capacity_posture"] == "OPEN_CAPACITY", (
        "one of two slots used is a 0.50 slot utilisation, below the 0.80 threshold"
    )
    capacity = read_capacity(s.window_id, s.bh)
    assert capacity["slots_used"] == 1
    assert capacity["batch_slots_remaining"] == 1
    assert capacity["units_remaining"] == 239


def test_posture_reaches_exhausted_on_the_last_slot_while_units_sit_idle(api):
    """PRD §2.9: "The posture is `EXHAUSTED` when remaining units are zero, or
    remaining batch slots are zero, or remaining oven hours are zero or negative."
    PRD §2.9: "Because the three axes interact through that maximum, a single line
    can leave unit utilisation at a fifth of capacity and still drive the posture
    straight to `EXHAUSTED` by consuming the last batch slot."
    PRD §2.9: "When the profile is `LONG_BAKE`, the item's own
    `oven_hours_per_batch` replaces that fixed figure, so the same slot count can
    consume a quite different share of the window's oven capacity."

    Design: Difficulty/combinatorial_formula/capacity_posture_nested_max_exhausts_on_slots_while_units_idle
    """
    s = setup_storefront(
        window_overrides={
            "label": "Slot-tight Wed",
            "capacity_units": 240,
            "capacity_batch_slots": 2,
            "capacity_oven_hours": 18.0,
        }
    )
    add_menu_item(s, kind="loaf")
    order = open_order(s.customer_id, s.window_id)
    add_line(order["id"], s.cookie_id, 1, s.customer_id, s.window_id)
    add_line(order["id"], s.loaf_id, 1, s.customer_id, s.window_id)

    capacity = validate_success(api.get_offer_window_capacity(s.window_id, s.ch))
    assert capacity["units_remaining"] == 238
    assert capacity["batch_slots_remaining"] == 0
    assert capacity["oven_hours_remaining"] == pytest.approx(13.5)
    assert capacity["capacity_posture"] == "EXHAUSTED"
    assert capacity["held_units"] == 2
    assert read_window(s.window_id, s.ch)["capacity_posture"] == "EXHAUSTED"


def test_two_twenty_five_unit_demands_need_four_slots_not_three(api):
    """PRD §2.9: "Rounding up per item rather than on the total matters: 25 units of
    one item and 25 of another need two slots plus two slots, four in all, where
    rounding up a combined fifty units would have suggested three."
    PRD §2.6: "Rung 54: the window's remaining batch slots are at least the
    additional slots the request would require, otherwise
    `ERR_BATCH_SLOT_CAPACITY_EXCEEDED` (422) on line addition and line patching."

    Design: Difficulty/resource_temporal_overlap/batch_slot_ceiling_is_per_menu_item_not_per_window_total
    """
    s = setup_storefront(
        window_overrides={
            "label": "Three slots only",
            "capacity_units": 240,
            "capacity_batch_slots": 3,
            "capacity_oven_hours": 18.0,
        }
    )
    add_menu_item(s, kind="scone")
    order = open_order(s.customer_id, s.window_id)
    add_line(order["id"], s.cookie_id, 25, s.customer_id, s.window_id)

    after_cookie = read_capacity(s.window_id, s.ch)
    assert after_cookie["batch_slots_remaining"] == 1
    assert after_cookie["units_remaining"] == 215

    rejected = api.add_order_line(
        order["id"],
        {
            "menu_item_id": s.scone_id,
            "quantity": 25,
            "expected_offer_window_version": window_version(s.window_id, s.ch),
        },
        s.ch,
    )
    validate_error(rejected, ApiErrorId.ERR_BATCH_SLOT_CAPACITY_EXCEEDED)
    still = read_capacity(s.window_id, s.ch)
    assert still["units_remaining"] == 215, "215 units were still free"
    assert still["oven_hours_remaining"] == pytest.approx(15.0)


def test_a_twenty_four_unit_line_fits_the_last_batch_slot_exactly(api):
    """PRD §2.9: "`slot_count` is that demand divided by the 24 units a slot holds
    and **rounded up** to a whole slot"
    PRD §2.9: "The posture is `EXHAUSTED` when remaining units are zero, or
    remaining batch slots are zero, or remaining oven hours are zero or negative."
    PRD §3.3: "Under the `PER_UNIT` basis a line's total is simply its `quantity`
    multiplied by `unit_price_cents`, and the total rises strictly with quantity."

    Design: Difficulty/resource_temporal_overlap/batch_slot_ceiling_is_per_menu_item_not_per_window_total
    """
    s = setup_storefront(
        window_overrides={
            "label": "Three slots only",
            "capacity_units": 240,
            "capacity_batch_slots": 3,
            "capacity_oven_hours": 18.0,
        }
    )
    add_menu_item(s, kind="scone")
    order = open_order(s.customer_id, s.window_id)
    add_line(order["id"], s.cookie_id, 25, s.customer_id, s.window_id)
    scone_line = add_line(order["id"], s.scone_id, 24, s.customer_id, s.window_id)

    assert scone_line["quantity"] == 24
    assert scone_line["line_total_cents"] == 9600
    capacity = validate_success(api.get_offer_window_capacity(s.window_id, s.ch))
    assert capacity["batch_slots_remaining"] == 0
    assert capacity["units_remaining"] == 191
    assert capacity["oven_hours_remaining"] == pytest.approx(13.5)
    assert capacity["capacity_posture"] == "EXHAUSTED"


def test_a_long_bake_line_can_exhaust_oven_hours_alone(api):
    """PRD §2.6: "Rung 55: the window's remaining oven hours are at least the
    additional oven hours the request would require, otherwise
    `ERR_OVEN_HOURS_CAPACITY_EXCEEDED` (422) on line addition and line patching."
    PRD §2.9: "When the profile is `LONG_BAKE`, the item's own
    `oven_hours_per_batch` replaces that fixed figure, so the same slot count can
    consume a quite different share of the window's oven capacity."

    Design: Corner/validations/oven_hours_capacity_exceeded_while_units_and_slots_are_free
    """
    s = setup_storefront(
        window_overrides={
            "label": "Two oven hours",
            "capacity_units": 240,
            "capacity_batch_slots": 12,
            "capacity_oven_hours": 2.0,
        }
    )
    add_menu_item(s, kind="loaf", key="long")
    order = open_order(s.customer_id, s.window_id)

    rejected = api.add_order_line(
        order["id"],
        {
            "menu_item_id": s.long_id,
            "quantity": 1,
            "expected_offer_window_version": window_version(s.window_id, s.ch),
        },
        s.ch,
    )
    validate_error(rejected, ApiErrorId.ERR_OVEN_HOURS_CAPACITY_EXCEEDED)

    capacity = validate_success(api.get_offer_window_capacity(s.window_id, s.bh))
    assert capacity["units_remaining"] == 240
    assert capacity["batch_slots_remaining"] == 12
    assert capacity["oven_hours_remaining"] == pytest.approx(2.0)
    assert read_order(order["id"], s.ch)["order_status"] == "DRAFT"
    assert read_window(s.window_id, s.ch)["capacity_posture"] == "OPEN_CAPACITY"


def test_window_units_are_conserved_across_the_hold_and_the_confirm(api):
    """PRD §2.10: "A window's `capacity_units` equals its remaining units plus
    `confirmed_units` plus `held_units` plus `reserved_units`, where remaining units
    are computed as in §2.9."
    PRD §3.5: "Adding the first line to a `DRAFT` order moves the order to
    `PENDING_HOLD`, sets `placed_at` to the current instant, sets `hold_expires_at`
    to `placed_at` plus **45 minutes**, adds the line's units to the window's
    `held_units`, recomputes `capacity_posture`, and bumps both the order's and the
    window's `version`."
    PRD §3.5: "moves the order's units out of the window's `held_units` and into
    its `confirmed_units`"

    Design: Difficulty/compensating_invariant/window_unit_conservation_across_hold_confirm_and_cancel
    """
    s = setup_storefront()
    start = read_capacity(s.window_id, s.bh)
    assert start["units_remaining"] == 240

    order = open_order(s.customer_id, s.window_id)
    add_line(order["id"], s.cookie_id, 13, s.customer_id, s.window_id)
    held = read_capacity(s.window_id, s.bh)
    assert (held["units_remaining"], held["confirmed_units"], held["held_units"],
            held["reserved_units"]) == (227, 0, 13, 0)
    assert assert_window_unit_conservation(held) == 240

    confirm_order(order["id"], s.customer_id)
    confirmed = read_capacity(s.window_id, s.bh)
    assert (confirmed["units_remaining"], confirmed["confirmed_units"],
            confirmed["held_units"], confirmed["reserved_units"]) == (227, 13, 0, 0)
    assert assert_window_unit_conservation(confirmed) == 240


def test_cancelling_a_confirmed_order_returns_the_window_to_its_start(api):
    """PRD §3.5: "From `CONFIRMED` — permitted only while the window is still `OPEN`
    and the cutoff still ahead — the `PENDING` lines move to `RELEASED`, the order's
    units are subtracted from `confirmed_units`, `capacity_posture` is recomputed,
    the operator's `annual_gross_sales_cents` is recomputed *downward*"
    PRD §2.10: "A window's `capacity_units` equals its remaining units plus
    `confirmed_units` plus `held_units` plus `reserved_units`, where remaining units
    are computed as in §2.9."

    Design: Difficulty/compensating_invariant/window_unit_conservation_across_hold_confirm_and_cancel
    """
    s = setup_held_order(quantity=13)
    confirm_order(s.order_id, s.customer_id)

    cancelled = validate_success(
        api.cancel_order(s.order_id, s.ch, {"cancel_reason": "customer changed plans"})
    )
    assert cancelled["order_status"] == "CANCELLED"

    after = read_capacity(s.window_id, s.bh)
    assert (after["units_remaining"], after["confirmed_units"], after["held_units"],
            after["reserved_units"]) == (240, 0, 0, 0)
    assert assert_window_unit_conservation(after) == 240
    assert read_compliance(s.baker_id, s.bh)["annual_gross_sales_cents"] == 0


def test_locking_the_window_sweeps_every_live_hold(api):
    """PRD §3.4: "**Locking is the system's largest single sweep.** Every order on
    the window sitting in `PENDING_HOLD` moves to `EXPIRED_HOLD` and each of its
    `PENDING` lines moves to `RELEASED`; every club cycle on the window sitting in
    `RESERVED` moves to `RELEASED` with its `reserved_units` dropping to 0;
    `held_units`, `reserved_units`, and `capacity_posture` are all recomputed; and
    the window's `version` is bumped."
    PRD §3.4: "From `OPEN`, the operator locks the window at cutoff, which is
    permitted only once the current instant has reached `order_cutoff_at`."

    Design: Difficulty/non_linear_state_machine/offer_window_locked_then_reopened_by_cutoff_extension
    """
    s = setup_held_order(quantity=13)
    locked = lock_window(s)
    assert locked["window_status"] == "LOCKED"
    assert locked["held_units"] == 0
    assert read_order(s.order_id, s.ch)["order_status"] == "EXPIRED_HOLD"
    assert read_line(s.line_id, s.ch)["line_status"] == "RELEASED"


def test_the_cutoff_extension_reopens_the_window_without_restoring_the_hold(api):
    """PRD §3.4: "The cutoff extension is available only while `plan_status` is
    still `UNPLANNED` and `cutoff_extension_count` is below 1; it returns
    `window_status` to `OPEN`, sets `order_cutoff_at` to the current instant plus
    **120 minutes** — two hours from *now*, not two hours from the old cutoff —
    increments `cutoff_extension_count`, recomputes `skip_deadline_at` on every club
    cycle attached to the window, and bumps the `version`."
    PRD §3.4: "The re-entry is deliberately lossy: the holds and club reservations
    that the lock released are **not** restored, so capacity is strictly higher
    after the re-open than it was before the lock."

    Design: Difficulty/non_linear_state_machine/offer_window_locked_then_reopened_by_cutoff_extension
    """
    s = setup_held_order(quantity=13)
    lock_window(s)

    reopened = validate_success(api.extend_cutoff(s.window_id, s.bh))
    assert reopened["window_status"] == "OPEN"
    assert_same_instant(
        reopened["order_cutoff_at"],
        instant_plus(CLOCK_AT_CUTOFF, minutes=120),
        "order_cutoff_at after the extension",
    )
    assert reopened["cutoff_extension_count"] == 1
    assert reopened["held_units"] == 0, "the released hold must not be restored"
    assert read_line(s.line_id, s.ch)["line_status"] == "RELEASED"
    assert read_capacity(s.window_id, s.bh)["units_remaining"] == 240


def test_locking_an_already_locked_window_is_refused(api):
    """PRD §2.6: "Rung 19: the target entity's current state on the relevant axis is
    a declared source state of the requested transition, otherwise
    `ERR_INVALID_STATE` (409)."
    PRD §3.4: "From `OPEN`, the operator locks the window at cutoff, which is
    permitted only once the current instant has reached `order_cutoff_at`."

    Design: Corner/state_machines/locking_an_already_locked_window_is_not_idempotent
    """
    s = setup_held_order(quantity=13)
    locked = lock_window(s)
    version_after_lock = locked["version"]

    rejected = api.lock_offer_window(s.window_id, s.bh)
    validate_error(rejected, ApiErrorId.ERR_INVALID_STATE)

    after = read_window(s.window_id, s.bh)
    assert after["version"] == version_after_lock
    assert after["window_status"] == "LOCKED"
