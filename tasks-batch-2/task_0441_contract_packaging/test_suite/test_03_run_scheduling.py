"""Scheduling a run: recipe-approval gate, projected window, reservation, and
the line/crew overlap collision checks with their differing interval semantics.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_customer, create_component, create_recipe, add_bom_line,
    create_production_line, create_crew, build_approved_recipe,
    setup_basic_scenario, schedule_run,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import RECEIVER, SCHEDULER, QA
from test_helpers.constants import RANDOM_UUID


# ---------------------------------------------------------------------------
# Queue A — cross_entity_state_dependency / run_start_requires_recipe_approved
# (scheduling against a non-APPROVED recipe)
# ---------------------------------------------------------------------------

def test_schedule_against_pending_recipe_rejected(api):
    """PRD 3.3: "The referenced recipe must be `APPROVED`; scheduling against a recipe in any other state is rejected with `ERR_RECIPE_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/run_start_requires_recipe_approved
    """
    customer = create_customer()
    almond = create_component(customer["id"], "ALMOND", "Almonds", "INGREDIENT")
    pouch = create_component(customer["id"], "POUCH", "Pouch", "PACKAGING")
    recipe = create_recipe(customer["id"])
    add_bom_line(recipe["id"], almond["id"], recipe["version"])
    # Adding a BOM line bumps the recipe version (PRD 3.2), so the second add
    # must carry the recipe's current version.
    recipe = validate_success(api.get_recipe(recipe["id"], SCHEDULER))
    add_bom_line(recipe["id"], pouch["id"], recipe["version"], qty_per_unit=1)
    # Submit only — leaves the recipe in PENDING_APPROVAL, never approved.
    validate_success(api.submit_recipe(recipe["id"], SCHEDULER))
    line = create_production_line()
    crew = create_crew()

    resp = api.schedule_run(
        {"recipe_id": recipe["id"], "line_id": line["id"], "crew_id": crew["id"],
         "planned_units": 100, "scheduled_start": "2026-06-01T08:00:00Z"},
        SCHEDULER,
    )
    validate_error(resp, ApiErrorId.ERR_RECIPE_NOT_APPROVED.value)


def test_schedule_against_draft_recipe_rejected(api):
    """PRD 3.3: "The referenced recipe must be `APPROVED`; scheduling against a recipe in any other state is rejected with `ERR_RECIPE_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/run_start_requires_recipe_approved
    """
    customer = create_customer()
    recipe = create_recipe(customer["id"])  # stays DRAFT
    line = create_production_line()
    crew = create_crew()

    resp = api.schedule_run(
        {"recipe_id": recipe["id"], "line_id": line["id"], "crew_id": crew["id"],
         "planned_units": 100, "scheduled_start": "2026-06-01T08:00:00Z"},
        SCHEDULER,
    )
    validate_error(resp, ApiErrorId.ERR_RECIPE_NOT_APPROVED.value)


# ---------------------------------------------------------------------------
# Queue A — cross_entity_state_dependency / recipe_retire_blocked_by_live_production_run
# ---------------------------------------------------------------------------

def test_retire_blocked_by_live_scheduled_run(api):
    """PRD 3.2: "Retirement requires that the recipe currently be `APPROVED` and that no production run referencing it is still live — that is, no referencing run is in `SCHEDULED`, `RUNNING`, or `PENDING_QA`. A retire that violates the state precondition is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/recipe_retire_blocked_by_live_production_run
    """
    scenario = setup_basic_scenario()
    schedule_run(scenario["recipe"]["id"], scenario["line"]["id"],
                 scenario["crew"]["id"])

    resp = api.retire_recipe(scenario["recipe"]["id"], SCHEDULER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_recipe(scenario["recipe"]["id"], SCHEDULER))
    assert after["status"] == "APPROVED", (
        f"a blocked retire must leave the recipe APPROVED, got {after['status']}"
    )


def test_retire_allowed_when_no_live_run(api):
    """PRD 3.2: "a `Scheduler` may retire an approved recipe, moving `APPROVED` to the terminal `RETIRED` and incrementing the recipe's `version` by one."

    Design: Difficulty/cross_entity_state_dependency/recipe_retire_blocked_by_live_production_run
    """
    customer = create_customer()
    almond = create_component(customer["id"], "ALMOND", "Almonds", "INGREDIENT")
    pouch = create_component(customer["id"], "POUCH", "Pouch", "PACKAGING")
    recipe = build_approved_recipe(customer["id"], almond["id"], pouch["id"])
    # No production run references this recipe.

    retired = validate_success(api.retire_recipe(recipe["id"], SCHEDULER))
    assert retired["status"] == "RETIRED", (
        f"an APPROVED recipe with no live run must retire, got {retired['status']}"
    )


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap / line_overlap_half_open_backtoback_allowed_overlap_rejected
# ---------------------------------------------------------------------------

def _two_crew_line_scenario():
    """Approved recipe + line + two buffer-free crews; lots not needed (no start)."""
    customer = create_customer()
    almond = create_component(customer["id"], "ALMOND", "Almonds", "INGREDIENT")
    pouch = create_component(customer["id"], "POUCH", "Pouch", "PACKAGING")
    recipe = build_approved_recipe(customer["id"], almond["id"], pouch["id"])
    line = create_production_line()  # rated 50 u/h => 100 units = 120 min window
    crew1 = create_crew(name="Crew 1", rest_buffer_minutes=0)
    crew2 = create_crew(name="Crew 2", rest_buffer_minutes=0)
    return recipe, line, crew1, crew2


def test_line_backtoback_allowed_half_open(api):
    """PRD 3.3: "Because the interval is half-open, a new run whose start equals another run's end is allowed — exact back-to-back is fine on a line."

    Design: Difficulty/resource_temporal_overlap/line_overlap_half_open_backtoback_allowed_overlap_rejected
    """
    recipe, line, crew1, crew2 = _two_crew_line_scenario()
    schedule_run(recipe["id"], line["id"], crew1["id"],
                 scheduled_start="2026-06-01T08:00:00Z")  # window 08:00-10:00

    run2 = validate_success(
        api.schedule_run(
            {"recipe_id": recipe["id"], "line_id": line["id"], "crew_id": crew2["id"],
             "planned_units": 100, "scheduled_start": "2026-06-01T10:00:00Z"},
            SCHEDULER,
        ),
        expected_status=201,
    )
    assert run2["scheduled_start"] == "2026-06-01T10:00:00.000Z", (
        f"back-to-back run must be created at 10:00, got {run2['scheduled_start']}"
    )


def test_line_overlap_rejected(api):
    """PRD 3.3: "the new run's half-open window must not overlap the half-open window of any non-terminal run already on the same line ... A violation is rejected with `ERR_LINE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/line_overlap_half_open_backtoback_allowed_overlap_rejected
    """
    recipe, line, crew1, crew2 = _two_crew_line_scenario()
    schedule_run(recipe["id"], line["id"], crew1["id"],
                 scheduled_start="2026-06-01T08:00:00Z")  # window 08:00-10:00

    resp = api.schedule_run(
        {"recipe_id": recipe["id"], "line_id": line["id"], "crew_id": crew2["id"],
         "planned_units": 100, "scheduled_start": "2026-06-01T09:59:00Z"},
        SCHEDULER,
    )
    validate_error(resp, ApiErrorId.ERR_LINE_OVERLAP.value)


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap / crew_overlap_closed_buffer_rejects_backtoback
# ---------------------------------------------------------------------------

def test_crew_backtoback_rejected_closed_buffer(api):
    """PRD 3.3: "Because the buffered interval is closed and includes its endpoints, exact back-to-back is rejected for a crew, the opposite of the line rule. A violation is rejected with `ERR_CREW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/crew_overlap_closed_buffer_rejects_backtoback
    """
    customer = create_customer()
    almond = create_component(customer["id"], "ALMOND", "Almonds", "INGREDIENT")
    pouch = create_component(customer["id"], "POUCH", "Pouch", "PACKAGING")
    recipe = build_approved_recipe(customer["id"], almond["id"], pouch["id"])
    line_a = create_production_line(name="Line A")
    line_b = create_production_line(name="Line B")
    crew = create_crew(name="Day Crew", rest_buffer_minutes=15)
    # Run 1 on Line A 08:00-10:00 with the crew.
    schedule_run(recipe["id"], line_a["id"], crew["id"],
                 scheduled_start="2026-06-01T08:00:00Z")

    # Run 2 on a different line, same crew, exactly back-to-back at 10:00:
    # falls inside [08:00-15m, 10:00+15m] => crew collision.
    resp = api.schedule_run(
        {"recipe_id": recipe["id"], "line_id": line_b["id"], "crew_id": crew["id"],
         "planned_units": 100, "scheduled_start": "2026-06-01T10:00:00Z"},
        SCHEDULER,
    )
    validate_error(resp, ApiErrorId.ERR_CREW_OVERLAP.value)


def test_crew_gap_beyond_buffer_allowed(api):
    """PRD 3.3: "it expands the run's window by the crew's `rest_buffer_minutes` on each side, forming the closed interval from `scheduled_start` minus the buffer through `scheduled_end` plus the buffer ... and that buffered closed window must not overlap any non-terminal run already on the same crew."

    Design: Difficulty/resource_temporal_overlap/crew_overlap_closed_buffer_rejects_backtoback
    """
    customer = create_customer()
    almond = create_component(customer["id"], "ALMOND", "Almonds", "INGREDIENT")
    pouch = create_component(customer["id"], "POUCH", "Pouch", "PACKAGING")
    recipe = build_approved_recipe(customer["id"], almond["id"], pouch["id"])
    line_a = create_production_line(name="Line A")
    line_b = create_production_line(name="Line B")
    crew = create_crew(name="Day Crew", rest_buffer_minutes=15)
    schedule_run(recipe["id"], line_a["id"], crew["id"],
                 scheduled_start="2026-06-01T08:00:00Z")  # window 08:00-10:00, +/-15m

    # Start at 10:31 — its window 10:31-12:31, padded [10:16, 12:46], clears run1
    # under any reading of the closed-buffer rule (run1 raw end 10:00, padded end
    # 10:15 both precede 10:16), so no crew collision and the run is created.
    run2 = validate_success(
        api.schedule_run(
            {"recipe_id": recipe["id"], "line_id": line_b["id"], "crew_id": crew["id"],
             "planned_units": 100, "scheduled_start": "2026-06-01T10:31:00Z"},
            SCHEDULER,
        ),
        expected_status=201,
    )
    assert run2["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Queue B — calculations / project_run_window_no_changeover_equal_profiles
# ---------------------------------------------------------------------------

def test_run_window_no_changeover_equal_profiles(api):
    """PRD 3.3: "when the two sets are equal the run follows back-to-back with no changeover and zero changeover minutes are added. The `scheduled_end` is the `scheduled_start` advanced by the sum of the applicable changeover minutes and the run minutes"

    Design: Corner/calculations/project_run_window_no_changeover_equal_profiles
    """
    # Fresh line residue [] == allergen-free recipe profile [] => no changeover.
    customer = create_customer()
    almond = create_component(customer["id"], "ALMOND", "Almonds", "INGREDIENT")
    pouch = create_component(customer["id"], "POUCH", "Pouch", "PACKAGING")
    recipe = build_approved_recipe(customer["id"], almond["id"], pouch["id"])
    line = create_production_line(changeover_minutes=30)  # 50 u/h
    crew = create_crew()

    run = validate_success(
        api.schedule_run(
            {"recipe_id": recipe["id"], "line_id": line["id"], "crew_id": crew["id"],
             "planned_units": 100, "scheduled_start": "2026-06-01T08:00:00Z"},
            SCHEDULER,
        ),
        expected_status=201,
    )
    # 100 units / 50 uph = 2h = 120 min; no changeover; end == 10:00.
    assert run["scheduled_end"] == "2026-06-01T10:00:00.000Z", (
        f"equal profiles skip changeover: end must be 10:00, got {run['scheduled_end']}"
    )


# ---------------------------------------------------------------------------
# Queue B — state_machines / newly_created_run_initial_state_scheduled
# ---------------------------------------------------------------------------

def test_new_run_initial_state_scheduled(api):
    """PRD 3.3: "The run is created in `SCHEDULED`, the initial state of a run's lifecycle"

    Design: Corner/state_machines/newly_created_run_initial_state_scheduled
    """
    customer = create_customer()
    almond = create_component(customer["id"], "ALMOND", "Almonds", "INGREDIENT")
    pouch = create_component(customer["id"], "POUCH", "Pouch", "PACKAGING")
    recipe = build_approved_recipe(customer["id"], almond["id"], pouch["id"])
    line = create_production_line()
    crew = create_crew()

    run = validate_success(
        api.schedule_run(
            {"recipe_id": recipe["id"], "line_id": line["id"], "crew_id": crew["id"],
             "planned_units": 100, "scheduled_start": "2026-06-01T08:00:00Z"},
            SCHEDULER,
        ),
        expected_status=201,
    )
    assert run["status"] == "SCHEDULED", (
        f"a freshly scheduled run must start SCHEDULED, got {run['status']}"
    )


# ---------------------------------------------------------------------------
# Queue B — validations / schedule_run_nonexistent_crew_not_found
# ---------------------------------------------------------------------------

def test_schedule_run_nonexistent_crew_not_found(api):
    """PRD 2.6: "a create that names a `customer_id`, `component_id`, `recipe_id`, `line_id`, or `crew_id` that does not exist is rejected with `ERR_NOT_FOUND`."

    Design: Corner/validations/schedule_run_nonexistent_crew_not_found
    """
    customer = create_customer()
    almond = create_component(customer["id"], "ALMOND", "Almonds", "INGREDIENT")
    pouch = create_component(customer["id"], "POUCH", "Pouch", "PACKAGING")
    recipe = build_approved_recipe(customer["id"], almond["id"], pouch["id"])
    line = create_production_line()

    resp = api.schedule_run(
        {"recipe_id": recipe["id"], "line_id": line["id"],
         "crew_id": RANDOM_UUID, "planned_units": 100,
         "scheduled_start": "2026-06-01T08:00:00Z"},
        SCHEDULER,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Queue B — consistency_model / reservation_visible_immediately_after_schedule
# ---------------------------------------------------------------------------

def test_reservation_visible_immediately_after_schedule(api):
    """PRD 3.3: "Reservation ... raises each bill-of-materials component's `reserved_qty` by the quantity the run will eventually need and recomputes each affected component's `on_hand_qty`."

    Design: Corner/consistency_model/reservation_visible_immediately_after_schedule
    """
    # ALMOND qty_per_unit 2, scrap 5%, planned 100 => required 210; lot 500.
    scenario = setup_basic_scenario(almond_qty=2, almond_scrap=5, almond_received=500)
    schedule_run(scenario["recipe"]["id"], scenario["line"]["id"],
                 scenario["crew"]["id"], planned_units=100)

    comp = validate_success(api.get_component(scenario["almond"]["id"], SCHEDULER))
    assert float(comp["reserved_qty"]) == 210.000, (
        f"reserved_qty must reflect the scrap-inflated draw 210, "
        f"got {comp['reserved_qty']}"
    )
    assert float(comp["on_hand_qty"]) == 290.000, (
        f"on_hand_qty must drop to 500-210=290, got {comp['on_hand_qty']}"
    )
