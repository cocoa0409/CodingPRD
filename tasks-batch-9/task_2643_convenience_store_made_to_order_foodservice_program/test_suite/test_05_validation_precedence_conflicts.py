"""Which error wins when one request breaks two rules at once.

The validation pipeline is a fixed sequence, so a request that violates a
state gate and a temporal gate must report the state gate; a request that
violates a safety gate and a scheduling gate must report the safety gate.
Each test here forces both violations at once and pins the single error_id
the contract allows.
"""

import test_helpers as H
from test_helpers import factories as F
from test_helpers import fixtures as X

CLOCK_LUNCH = "2026-08-01T11:00:00Z"
CLOCK_AFTER_WINDOW = "2026-08-01T14:00:00Z"
WINDOW_START = "2026-08-01T13:00:00Z"
WINDOW_END = "2026-08-01T13:30:00Z"

CLOCK_BREAKFAST = "2026-08-01T08:00:00Z"
BAKE_START_FIRST = "2026-08-01T08:00:00Z"
BAKE_START_SECOND = "2026-08-01T09:00:00Z"
OCCUPANCY_END_FIRST = "2026-08-01T12:40:00Z"


def _placed_preorder_then_window_elapses(api):
    """A placed preorder whose 13:00-13:30 window is behind a 14:00 clock."""
    store = X.setup_store_open_for_lunch(api, CLOCK_LUNCH)
    hoagie = X.create_hoagie(api)
    order = X.create_draft_preorder(api, store["id"], WINDOW_START, WINDOW_END)
    X.add_order_line(api, order["id"], hoagie["id"], 1)
    placed = X.place_order(api, order["id"])
    assert placed["production_status"] == "PLACED"
    X.set_clock(api, CLOCK_AFTER_WINDOW)
    return store, hoagie, placed


def _impaired_unit_with_a_planned_pan_in_slot_one(api):
    """Slot 1 booked until 12:40 by a PLANNED pan, and the case impaired.

    The pan is left in ``PLANNED`` on purpose: the impairment sweep only
    touches holding stock, so the slot stays booked while the unit is out of
    service and both violations survive into the trigger request.
    """
    X.set_clock(api, CLOCK_BREAKFAST)
    store = X.create_store(api)
    unit = X.create_bakery_case(api, store["id"], slot_count=2)
    pretzel = X.create_pretzel(api)
    batch_a = X.create_planned_batch(
        api,
        store["id"],
        pretzel["id"],
        unit["id"],
        slot_index=1,
        planned_qty=40,
        bake_start_at=BAKE_START_FIRST,
    )
    reading = X.log_temperature(api, unit["id"], 120, H.KITCHEN_ASSOCIATE_HEADERS)
    return store, unit, pretzel, batch_a, reading


def _conflicting_plan_payload(store, pretzel, unit):
    return F.production_batch_payload(
        store["id"],
        pretzel["id"],
        unit["id"],
        slot_index=1,
        planned_qty=24,
        bake_start_at=BAKE_START_SECOND,
    )


def test_second_place_on_a_placed_order_reports_the_state_gate_not_the_window(api):
    """The state gate outranks the elapsed-window gate on a repeated commit.

    "Validation is a fixed pipeline and the **first** failure wins; later
    checks are never reached and never reported." State-transition legality
    sits at step 11 - "State-transition legality on every state-transition
    endpoint — `ERR_ORDER_NOT_DRAFT`" - while the elapsed-window refusal is a
    domain rule reached only later, at the step that says "Onward, the domain
    rules in exactly this order — this is the tie-breaking sequence whenever a
    single request would fail more than one of them".

    Design: Difficulty/priority_pair_validation_conflict/place_on_already_placed_order_with_elapsed_window_yields_order_not_draft
    """
    store, hoagie, placed = _placed_preorder_then_window_elapses(api)

    response = api.place_order(placed["id"], {}, H.STORE_TERMINAL_HEADERS)

    H.validate_error(response, H.ApiErrorId.ERR_ORDER_NOT_DRAFT.value, 409)
    assert response.json()["data"]["error_id"] != H.ApiErrorId.ERR_PICKUP_WINDOW_ELAPSED.value


def test_refused_second_place_leaves_both_order_axes_untouched(api):
    """A rejected commit is a no-op on the order it was aimed at.

    The order was committed once, so "The order's `production_status` must
    still be `DRAFT`, otherwise `ERR_ORDER_NOT_DRAFT`" refuses the repeat, and
    the refusal must not disturb the row: the production axis stays `PLACED`
    and the money axis stays where the first commit left it, since "A new
    order opens with a `production_status` of `DRAFT` on the kitchen axis and
    a `settlement_status` of `UNPAID` on the money axis" and nothing since has
    authorized tender.

    Design: Difficulty/priority_pair_validation_conflict/place_on_already_placed_order_with_elapsed_window_yields_order_not_draft
    """
    store, hoagie, placed = _placed_preorder_then_window_elapses(api)

    response = api.place_order(placed["id"], {}, H.STORE_TERMINAL_HEADERS)
    H.validate_error(response, H.ApiErrorId.ERR_ORDER_NOT_DRAFT.value, 409)

    after = X.read_order(api, placed["id"])
    assert after["production_status"] == "PLACED"
    assert after["settlement_status"] == "UNPAID"


def test_temporal_window_gate_still_fires_once_the_state_gate_is_satisfied(api):
    """With the state gate passed, the same clock trips a window gate.

    A draft order carrying the identical 13:00-13:30 window under the same
    14:00 clock reaches the window family, where "A `MOBILE_PREORDER` order
    requires that its `pickup_window_start` be at least 15 minutes after the
    current logical clock" and "Either shortfall reports
    `ERR_PREORDER_LEAD_TIME_TOO_SHORT` (HTTP 422)" - which the pipeline ranks
    ahead of the elapsed-window refusal in "the pickup-window family in the
    order `ERR_PICKUP_WINDOW_NOT_ALLOWED`, `ERR_PICKUP_WINDOW_REQUIRED`,
    `ERR_PICKUP_WINDOW_INVALID`, `ERR_PREORDER_LEAD_TIME_TOO_SHORT`,
    `ERR_PICKUP_WINDOW_ELAPSED`". The state gate was therefore the only thing
    standing between the repeated commit and this branch.

    Design: Difficulty/priority_pair_validation_conflict/place_on_already_placed_order_with_elapsed_window_yields_order_not_draft
    """
    store, hoagie, placed = _placed_preorder_then_window_elapses(api)

    fresh = X.create_draft_preorder(api, store["id"], WINDOW_START, WINDOW_END)
    X.add_order_line(api, fresh["id"], hoagie["id"], 1)

    response = api.place_order(fresh["id"], {}, H.STORE_TERMINAL_HEADERS)

    H.validate_error(response, H.ApiErrorId.ERR_PREORDER_LEAD_TIME_TOO_SHORT.value, 422)
    still_draft = X.read_order(api, fresh["id"])
    assert still_draft["production_status"] == "DRAFT"


def test_planning_into_an_impaired_case_reports_safety_before_slot_conflict(api):
    """The out-of-service posture outranks the booked slot.

    Slot 1 is booked until "the computed `occupancy_end_at`, which is the
    `bake_start_at` advanced by the item's `bake_minutes`, then by the item's
    `hold_minutes`, and then by a mandatory sanitation window of 15 minutes",
    and the case is out of service because "A unit in `OPERATIONAL` goes
    `OPERATIONAL → IMPAIRED`, and its `consecutive_out_of_range_count`
    increases by one, reaching 1". The pipeline resolves the double violation
    through the domain-rule sequence "`ERR_ORDER_EMPTY`, then
    `ERR_DAYPART_PLAN_NOT_PUBLISHED`, then `ERR_ORDER_NOT_AUTHORIZED`, then
    `ERR_HOLDING_UNIT_NOT_OPERATIONAL`", which precedes
    `ERR_UNIT_SLOT_CONFLICT` further down the same list.

    Design: Difficulty/priority_pair_validation_conflict/batch_plan_into_impaired_unit_reports_safety_error_before_slot_conflict
    """
    store, unit, pretzel, batch_a, reading = _impaired_unit_with_a_planned_pan_in_slot_one(api)
    assert batch_a["occupancy_end_at"] == OCCUPANCY_END_FIRST
    assert reading["in_range"] is False

    response = api.create_production_batch(
        _conflicting_plan_payload(store, pretzel, unit), H.KITCHEN_ASSOCIATE_HEADERS
    )

    H.validate_error(response, H.ApiErrorId.ERR_HOLDING_UNIT_NOT_OPERATIONAL.value, 409)
    assert response.json()["data"]["error_id"] != H.ApiErrorId.ERR_UNIT_SLOT_CONFLICT.value


def test_impairment_does_not_sweep_a_pan_that_is_only_planned(api):
    """A pan still waiting for the oven keeps its slot through an impairment.

    "Every production batch in that unit whose status is `HOLDING` and whose
    `reserved_qty` is zero goes `HOLDING → DISCARDED`" - a pan in `PLANNED`
    matches neither condition, so it survives the escalation with all five
    counters where they started: "A newly planned batch opens in `PLANNED`
    with every quantity counter at 0". That is why the slot booking is still
    live once the case is put back in service.

    Design: Difficulty/priority_pair_validation_conflict/batch_plan_into_impaired_unit_reports_safety_error_before_slot_conflict
    """
    store, unit, pretzel, batch_a, reading = _impaired_unit_with_a_planned_pan_in_slot_one(api)

    impaired = X.read_holding_unit(api, unit["id"])
    assert impaired["status"] == "IMPAIRED"
    assert impaired["consecutive_out_of_range_count"] == 1

    untouched = X.read_batch(api, batch_a["id"])
    assert untouched["status"] == "PLANNED"
    assert untouched["baked_qty"] == 0
    assert untouched["remaining_qty"] == 0
    assert untouched["discarded_qty"] == 0
    assert untouched["occupancy_end_at"] == OCCUPANCY_END_FIRST


def test_clearing_the_case_exposes_the_slot_conflict_that_was_there_all_along(api):
    """The lower-ranked violation surfaces once the safety gate is satisfied.

    A verified corrective action "returns the unit to service by driving it
    `IMPAIRED → OPERATIONAL` or `LOCKED_OUT → OPERATIONAL`, resets the unit's
    `consecutive_out_of_range_count` to zero"; a shift lead may do it because
    "A `ShiftLead` may verify an action for an impaired unit" and the acting
    id differs from the associate who took the reading, as required by "the
    acting `X-User-ID` must differ from the `logged_by_user_id` recorded on
    the underlying reading". Replaying the identical plan then hits the
    interval rule: a 09:00 start falls strictly before the 12:40 end bound, so
    "A new batch is refused with `ERR_UNIT_SLOT_CONFLICT` (HTTP 409)".

    Design: Difficulty/priority_pair_validation_conflict/batch_plan_into_impaired_unit_reports_safety_error_before_slot_conflict
    """
    store, unit, pretzel, batch_a, reading = _impaired_unit_with_a_planned_pan_in_slot_one(api)
    first = api.create_production_batch(
        _conflicting_plan_payload(store, pretzel, unit), H.KITCHEN_ASSOCIATE_HEADERS
    )
    H.validate_error(first, H.ApiErrorId.ERR_HOLDING_UNIT_NOT_OPERATIONAL.value, 409)

    action = X.open_corrective_action(api, reading["id"], H.SHIFT_LEAD_HEADERS)
    verified = X.verify_corrective_action(api, action["id"], H.SHIFT_LEAD_HEADERS)
    assert verified["status"] == "VERIFIED"

    restored = X.read_holding_unit(api, unit["id"])
    assert restored["status"] == "OPERATIONAL"
    assert restored["consecutive_out_of_range_count"] == 0

    second = api.create_production_batch(
        _conflicting_plan_payload(store, pretzel, unit), H.KITCHEN_ASSOCIATE_HEADERS
    )

    H.validate_error(second, H.ApiErrorId.ERR_UNIT_SLOT_CONFLICT.value, 409)
    assert X.read_batch(api, batch_a["id"])["status"] == "PLANNED"
