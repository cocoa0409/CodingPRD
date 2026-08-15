"""Turn opening, scope finalization, projection computation, and the
estimate add/void conservation invariant."""
from test_helpers import (
    TC,
    ApiErrorId,
    add_scope_item,
    create_property,
    create_unit,
    create_vendor,
    finalize_turn,
    get_item,
    get_turn,
    get_unit,
    open_turn,
    schedule,
    setup_open_turn,
    validate_error,
    validate_success,
)

NOTICE = {"notice_date": "2026-07-28", "move_out_date": "2026-07-31"}


# --- finalize gating (Difficulty: finalize_scope_requires_planned_scope_item)

def test_finalize_without_planned_items_rejected(api):
    """PRD §3.3: "A turn that is not `OPEN` rejects finalization with
    `ERR_INVALID_STATE`, and a turn with no `PLANNED` scope item rejects it
    with `ERR_NO_SCOPE_ITEMS`."

    Design: Difficulty/cross_entity_state_dependency/finalize_scope_requires_planned_scope_item
    """
    prop = create_property()
    unit = create_unit(prop["id"])
    turn = open_turn(unit["id"])

    resp = api.finalize_scope(turn["id"], TC)
    validate_error(resp, ApiErrorId.ERR_NO_SCOPE_ITEMS, 422)
    assert get_turn(turn["id"])["status"] == "OPEN", "turn must stay OPEN"


def test_finalize_locks_budget_and_stamps_dates(api):
    """PRD §3.3: "On success the turn moves `OPEN` → `SCOPED` and, in the same
    atomic step: `approved_budget_cents` is locked to the turn's current
    `estimated_cost_cents` (the sum over its `PLANNED` items); `started_on` is
    stamped with the current logical-clock date; `target_ready_date` is set to
    `started_on` plus the property's `days_to_ready_target` calendar days;
    `projected_ready_date` is computed for the first time; the unit moves from
    `NOTICE` to `IN_TURN`; and the turn's `version` increments by one."
    PRD §2.5: "At startup, before any operator intervention, the logical clock
    reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock
    time on its own."

    Design: Difficulty/cross_entity_state_dependency/finalize_scope_requires_planned_scope_item
    """
    prop = create_property()
    unit = create_unit(prop["id"])
    turn = open_turn(unit["id"])

    validate_error(api.finalize_scope(turn["id"], TC),
                   ApiErrorId.ERR_NO_SCOPE_ITEMS, 422)
    add_scope_item(turn["id"], "REPAIR", 5000)

    finalized = validate_success(api.finalize_scope(turn["id"], TC))
    assert finalized["status"] == "SCOPED"
    assert finalized["approved_budget_cents"] == 5000
    assert finalized["started_on"] == "2026-08-01", "default logical-clock date"
    assert finalized["target_ready_date"] == "2026-08-06", "started + 5 days"
    assert finalized["version"] == turn["version"] + 1
    assert get_unit(unit["id"])["status"] == "IN_TURN"


# --- second turn on a NOTICE unit (Corner: second_turn_on_notice_unit_rejected)

def test_second_turn_on_notice_unit_rejected(api):
    """PRD §3.2: "The unit must be `OCCUPIED` — a unit already in `NOTICE`,
    `IN_TURN`, or `READY` refuses a new turn with `ERR_UNIT_NOT_OCCUPIED`."

    Design: Corner/errors/second_turn_on_notice_unit_rejected
    """
    prop = create_property()
    unit = create_unit(prop["id"])
    open_turn(unit["id"], **NOTICE)
    assert get_unit(unit["id"])["status"] == "NOTICE"

    resp = api.create_turn(
        {"unit_id": unit["id"], "notice_date": "2026-08-01",
         "move_out_date": "2026-08-05"},
        TC,
    )
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_OCCUPIED, 409)
    assert get_unit(unit["id"])["status"] == "NOTICE", "unit state unchanged"


# --- estimate conservation (Difficulty: estimated_cost_add_void_conservation)

def test_add_planned_item_raises_estimated_cost(api):
    """PRD §3.3: "the turn's `estimated_cost_cents` is always the sum of each
    scope item's `estimated_cost_cents` over the items in `PLANNED`,
    `SCHEDULED`, `COMPLETED`, or `FAILED` status — items in `PENDING_APPROVAL`,
    `VOIDED`, or `REJECTED` are excluded — and it is re-derived whenever a
    scope item is created as `PLANNED`, approved, voided, rejected, or failed,
    or when a rework item is auto-created."
    PRD §3.2: "items created while the turn is `OPEN` enter `PLANNED` status
    immediately."

    Design: Difficulty/compensating_invariant/estimated_cost_add_void_conservation
    """
    ctx = setup_open_turn("CLEAN", 7000)
    turn = ctx["turn"]
    assert get_turn(turn["id"])["estimated_cost_cents"] == 7000

    add_scope_item(turn["id"], "REPAIR", 5000)
    assert get_turn(turn["id"])["estimated_cost_cents"] == 12000


def test_void_restores_estimated_cost_exactly(api):
    """PRD §3.5: "Voiding a `PLANNED` item simply moves it to `VOIDED` and
    re-derives the turn's estimate and projection, with commitment risk
    re-evaluated."
    PRD §3.3: "items in `PENDING_APPROVAL`, `VOIDED`, or `REJECTED` are
    excluded" from the estimate.

    Design: Difficulty/compensating_invariant/estimated_cost_add_void_conservation
    """
    ctx = setup_open_turn("CLEAN", 7000)
    turn = ctx["turn"]
    assert get_turn(turn["id"])["estimated_cost_cents"] == 7000

    item_a = add_scope_item(turn["id"], "REPAIR", 5000)
    assert get_turn(turn["id"])["estimated_cost_cents"] == 12000

    voided = validate_success(api.void_scope_item(item_a["id"], TC))
    assert voided["status"] == "VOIDED"
    after = get_turn(turn["id"])
    assert after["estimated_cost_cents"] == 7000, (
        "compensating void restores the aggregate exactly"
    )
    assert get_item(item_a["id"])["status"] == "VOIDED"


# --- multi-input projection (Difficulty: projected_ready_date_multi_input_with_cure_buffer)

def _setup_projection_scenario(api):
    """SCOPED turn (days_to_ready_target 7) with PAINT scheduled
    [2026-08-05, 2026-08-07) plus auto-approved PLANNED CARPET and CLEAN."""
    prop = create_property(days_to_ready_target=7)
    unit = create_unit(prop["id"])
    turn = open_turn(unit["id"])
    paint = add_scope_item(turn["id"], "PAINT", 100000, "full repaint")
    finalize_turn(turn["id"])
    painter = create_vendor("PaintPros", "PAINT")
    schedule(paint["id"], painter["id"], "2026-08-05", "2026-08-07")
    # 400bp then 700bp variance — both within the 1000bp auto-approve band.
    add_scope_item(turn["id"], "CARPET", 4000, "bedroom carpet")
    add_scope_item(turn["id"], "CLEAN", 3000, "final clean")
    return turn


def test_projected_ready_date_anchor_cure_and_standard_days(api):
    """PRD §3.3: "an anchor date begins at the later of the current
    logical-clock date and the latest `end_date` among the turn's vendor
    assignments in `SCHEDULED` or `ACCEPTED` status (the clock date alone when
    no such assignment exists); then each `PLANNED` scope item is processed in
    ascending `sequence_rank` order, ties broken by ascending `created_at`, and
    for each item the anchor advances by that category's standard duration —
    two days for `REPAIR`, two for `PAINT`, and one day each for `CARPET`,
    `CLEAN`, `APPLIANCE`, `FIXTURE`, and `OTHER`."
    PRD §3.3: "before any `PLANNED` `CARPET` item's day is added, if the turn
    still has any `PAINT`-category item whose status is not `COMPLETED`,
    `VOIDED`, `REJECTED`, or `FAILED`, one full cure day is added to the anchor
    first, giving the paint time to cure before carpet is laid."

    Design: Difficulty/combinatorial_formula/projected_ready_date_multi_input_with_cure_buffer
    """
    turn = _setup_projection_scenario(api)
    data = get_turn(turn["id"])
    # anchor = max(2026-08-01, paint end 2026-08-07) = 08-07;
    # CARPET: +1 cure (PAINT is SCHEDULED, not complete) +1 day -> 08-09;
    # CLEAN: +1 day -> 08-10.
    assert data["projected_ready_date"] == "2026-08-10"


def test_target_ready_date_from_started_on_plus_property_target(api):
    """PRD §3.3: "`started_on` is stamped with the current logical-clock date;
    `target_ready_date` is set to `started_on` plus the property's
    `days_to_ready_target` calendar days."
    PRD §2.5: "At startup, before any operator intervention, the logical clock
    reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock
    time on its own."

    Design: Difficulty/combinatorial_formula/projected_ready_date_multi_input_with_cure_buffer
    """
    turn = _setup_projection_scenario(api)
    data = get_turn(turn["id"])
    assert data["started_on"] == "2026-08-01"
    assert data["target_ready_date"] == "2026-08-08", "started + 7 days"
