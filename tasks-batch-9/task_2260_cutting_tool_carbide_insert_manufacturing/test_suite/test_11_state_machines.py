"""Lifecycles: opening states, legal moves, refused moves and terminal states.

Every entity here has a declared set of transitions, and the interesting cases
are at the edges of that set: the state a row opens in, a move and its
counter-move, a trigger replayed from the state it already produced, a terminal
state that accepts nothing more, and a bounded loop that changes branch on its
last iteration.
"""

from test_helpers import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_grinding_run,
    assert_grinding_wheel,
    assert_powder_blend_batch,
    assert_tool_product,
    assert_wheel_life_conserved,
)
from test_helpers.fixtures import APP, APPROVER, COAT, GEO, MET, OPERATOR_ONE, PLAN
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)


# ─── Opening states ─────────────────────────────────────────────────────────

def test_freshly_created_rows_open_in_their_declared_states(api):
    """A product, a batch, a wheel and a run each open exactly where declared.

    PRD §3.5: "A new product opens at `release_status` `DEVELOPMENT` and
    `supply_status` `UNAVAILABLE`, captures the three pinned revisions from its
    referenced grade, geometry and recipe, computes `engineering_lead_time_days`
    and `expedite_eligible`, and sets `tool_life_index` to null,
    `qualified_workpiece_groups` to the empty list and `open_order_units` to 0."

    PRD §3.1: "The new batch opens at `stage` `BLENDED` with `qc_status`
    `PENDING`, captures `pinned_grade_revision` from the grade's current
    `revision`, and sets `pressed_units`, `sintered_units`, `scrap_units` and
    `remaining_units` all to 0."

    PRD §3.4: "A new wheel opens at `status` `AVAILABLE`, with
    `consumed_life_units` at 0, `remaining_life_units` equal to
    `initial_life_units`, and `dress_count` at 0."

    PRD §3.4: "The run opens at `status` `SCHEDULED` with `consumed_life_units`
    at 0 and `tolerance_class` null."

    Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_states
    """
    state = fx.endmill_product(api)
    batch = validate_success(
        api.create_powder_blend_batch(
            f.powder_blend_batch_payload(state["grade"]["id"]), MET
        ),
        201,
    )
    wheel = fx.grinding_wheel(api, initial_life_units=100000)
    run = validate_success(
        api.create_grinding_run(
            f.grinding_run_payload(wheel["id"], state["product"]["id"], planned_units=5),
            PLAN,
        ),
        201,
    )

    product = state["product"]
    assert_tool_product(product)
    assert product["release_status"] == "DEVELOPMENT", (
        f"the release dimension opens at DEVELOPMENT, got {product['release_status']}"
    )
    assert product["supply_status"] == "UNAVAILABLE", (
        "the supply dimension opens independently at UNAVAILABLE, got "
        f"{product['supply_status']}"
    )
    assert product["tool_life_index"] is None, (
        f"no trial evidence exists yet, got {product['tool_life_index']}"
    )
    assert product["qualified_workpiece_groups"] == [], (
        f"no material has been qualified yet, got {product['qualified_workpiece_groups']}"
    )
    assert product["open_order_units"] == 0, (
        f"no demand has been raised yet, got {product['open_order_units']}"
    )
    assert_powder_blend_batch(batch)
    assert batch["stage"] == "BLENDED", (
        f"the process dimension opens at BLENDED, got {batch['stage']}"
    )
    assert batch["qc_status"] == "PENDING", (
        f"the QC dimension opens at PENDING, got {batch['qc_status']}"
    )
    assert_grinding_wheel(wheel)
    assert wheel["status"] == "AVAILABLE", (
        f"a registered wheel is ready to mount, got {wheel['status']}"
    )
    assert wheel["consumed_life_units"] == 0, (
        f"no abrasive has been spent, got {wheel['consumed_life_units']}"
    )
    assert wheel["remaining_life_units"] == 100000, (
        f"the full declared life is available, got {wheel['remaining_life_units']}"
    )
    assert wheel["dress_count"] == 0, (
        f"the wheel has never been dressed, got {wheel['dress_count']}"
    )
    assert_grinding_run(run)
    assert run["status"] == "SCHEDULED", (
        f"a booked run opens at SCHEDULED, got {run['status']}"
    )
    assert run["consumed_life_units"] == 0, (
        f"booking charges nothing, got {run['consumed_life_units']}"
    )
    assert run["tolerance_class"] is None, (
        f"nothing has been measured yet, got {run['tolerance_class']}"
    )


# ─── A move and its counter-move ────────────────────────────────────────────

def test_a_geometry_walks_release_revise_and_release_again(api):
    """Release does not touch the revision; the revise sends it back to DRAFT at 2.

    PRD §3.2: "A new geometry opens at `status` `DRAFT` with `revision` 1."

    PRD §3.2: "Releasing a geometry moves it `DRAFT` → `RELEASED` and is what
    makes it usable for production tooling."

    PRD §3.2: "Revising a released geometry — changing `chipbreaker_code`,
    `rake_angle_deg`, `nose_radius_mm`, `max_depth_of_cut_mm` or `edge_prep`,
    with a `revision_note` for the record — is permitted only from `RELEASED` and
    returns the geometry to `DRAFT` with `revision` advanced by 1."

    Design: Corner/state_machines/geometry_release_then_revise_round_trip
    """
    geometry = fx.insert_geometry(api)
    assert geometry["revision"] == 1, "precondition: the geometry opens at revision 1"

    released = validate_success(api.release_insert_geometry(geometry["id"], GEO))
    revised = validate_success(
        api.revise_insert_geometry(
            geometry["id"],
            f.revise_geometry_payload(
                nose_radius_mm=0.4, max_depth_of_cut_mm=3.0, edge_prep="SHARP"
            ),
            GEO,
        )
    )
    re_released = validate_success(api.release_insert_geometry(geometry["id"], GEO))

    assert released["status"] == "RELEASED", (
        f"the first release moves DRAFT to RELEASED, got {released['status']}"
    )
    assert released["revision"] == 1, (
        f"releasing is not a revision, so it stays 1, got {released['revision']}"
    )
    assert revised["status"] == "DRAFT", (
        f"a revise returns the geometry to DRAFT, got {revised['status']}"
    )
    assert revised["revision"] == 2, (
        f"the revision advances by exactly 1, got {revised['revision']}"
    )
    assert revised["nose_radius_mm"] == 0.4, (
        f"the restated cutting geometry is stored, got {revised['nose_radius_mm']}"
    )
    assert revised["chipbreaker_code"] == "MF", (
        f"the restated chip breaker is stored, got {revised['chipbreaker_code']}"
    )
    assert re_released["status"] == "RELEASED", (
        f"the second revision can be released in turn, got {re_released['status']}"
    )
    assert re_released["revision"] == 2, (
        f"the second release carries revision 2 forward, got {re_released['revision']}"
    )


# ─── Preconditions on a transition ──────────────────────────────────────────

def test_a_grade_whose_batch_is_only_pressed_cannot_enter_pilot(api):
    """Without a SINTERED and PASSED batch on the current revision there is no pilot.

    PRD §3.1: "Moving a grade from `DRAFT` to `PILOT` requires the grade to be at
    `DRAFT` and requires at least one blend batch on that grade to be
    simultaneously at `stage` `SINTERED`, at `qc_status` `PASSED`, and pinned to
    the grade's *current* `revision`. When no such batch exists, the request is
    rejected with `ERR_NO_PASSED_BATCH`"

    PRD §3.1: "The `qc_status` dimension is untouched by pressing — a pressed
    batch is still `PENDING`, because nothing has yet been measured."

    Design: Corner/state_machines/start_pilot_without_a_passed_batch_rejected
    """
    grade = fx.carbide_grade(api)
    batch = validate_success(
        api.create_powder_blend_batch(f.powder_blend_batch_payload(grade["id"]), MET), 201
    )
    validate_success(api.press_powder_blend_batch(batch["id"], f.press_payload(), MET))

    response = api.start_grade_pilot(grade["id"], MET)

    validate_error(response, ApiErrorId.ERR_NO_PASSED_BATCH, 409)
    grade_after = validate_success(api.get_carbide_grade(grade["id"], MET))
    assert grade_after["status"] == "DRAFT", (
        f"a refused pilot leaves the grade in development, got {grade_after['status']}"
    )
    batch_after = validate_success(api.get_powder_blend_batch(batch["id"], MET))
    assert batch_after["stage"] == "PRESSED", (
        f"the batch is pressed but not sintered, got {batch_after['stage']}"
    )
    assert batch_after["qc_status"] == "PENDING", (
        f"nothing has been measured, so QC is still open, got {batch_after['qc_status']}"
    )


def test_a_deposition_run_cannot_be_closed_out_one_second_early(api):
    """At 11:59:59Z completion is refused; at 12:00:00Z the same payload succeeds.

    PRD §3.3: "Closing out a deposition run requires the run to be `SCHEDULED`,
    otherwise `ERR_INVALID_COATING_RUN_STATE`, and requires the current logical
    UTC time to have reached `window_end`; completing early is rejected with
    `ERR_WINDOW_NOT_ELAPSED`."

    PRD §3.3: "The recipe's `adhesion_class` becomes the lowest, and therefore
    best, `adhesion_hf_class` across the pool, and is null whenever the pool is
    empty."

    PRD §3.3: "The recipe's `is_validated` becomes true if and only if at least
    one run in the pool satisfies both conditions at once: its `adhesion_hf_class`
    is at most 2, and the absolute difference between its `measured_thickness_um`
    and the recipe's `total_thickness_um` is at most 15 percent of
    `total_thickness_um`."

    Design: Corner/state_machines/coating_run_completion_before_window_end_rejected
    """
    recipe = fx.coating_recipe(api)
    run = validate_success(
        api.create_coating_run(
            f.coating_run_payload(
                recipe["id"],
                window_start="2026-08-10T06:00:00Z",
                window_end="2026-08-10T12:00:00Z",
            ),
            COAT,
        ),
        201,
    )
    fx.advance_clock(api, "2026-08-10T11:59:59Z")

    early = api.complete_coating_run(
        run["id"], f.complete_coating_run_payload(), COAT
    )

    validate_error(early, ApiErrorId.ERR_WINDOW_NOT_ELAPSED, 409)
    still_scheduled = validate_success(api.get_coating_run(run["id"], COAT))
    assert still_scheduled["status"] == "SCHEDULED", (
        f"the refused closure leaves the run booked, got {still_scheduled['status']}"
    )
    unproven = validate_success(api.get_coating_recipe(recipe["id"], COAT))
    assert unproven["is_validated"] is False, (
        f"the evidence pool is still empty, got {unproven['is_validated']}"
    )
    assert unproven["adhesion_class"] is None, (
        f"an empty pool leaves the class null, got {unproven['adhesion_class']}"
    )

    fx.advance_clock(api, "2026-08-10T12:00:00Z")
    completed = validate_success(
        api.complete_coating_run(run["id"], f.complete_coating_run_payload(), COAT)
    )

    assert completed["status"] == "COMPLETED", (
        "at exactly the window end the clock has reached it, so the run closes, "
        f"got {completed['status']}"
    )
    proven = validate_success(api.get_coating_recipe(recipe["id"], COAT))
    assert proven["is_validated"] is True, (
        "class 2 adhesion at 3.10 um against a 3.00 um stack is within 15 percent, "
        f"got {proven['is_validated']}"
    )
    assert proven["adhesion_class"] == 2, (
        f"the pool's best class is 2, got {proven['adhesion_class']}"
    )


# ─── Replaying a trigger from the state it already produced ─────────────────

def test_no_action_endpoint_is_idempotent(api):
    """Press, release, start-pilot, dress and close each refuse a second call.

    PRD §2.11: "12. **Subject state permits the transition.** The addressed
    entity is not in a state from which the requested transition is declared →
    the entity's own invalid-state code: `ERR_INVALID_GRADE_STATE`,
    `ERR_INVALID_BATCH_STATE`, `ERR_INVALID_GEOMETRY_STATE`,
    `ERR_INVALID_COATING_RUN_STATE`, `ERR_INVALID_WHEEL_STATE`,
    `ERR_INVALID_GRINDING_RUN_STATE`, `ERR_INVALID_PRODUCT_STATE`,
    `ERR_INVALID_DOSSIER_STATE`, `ERR_INVALID_TRIAL_STATE`,
    `ERR_INVALID_ORDER_STATE`, `ERR_INVALID_JOB_STATE` or
    `ERR_INVALID_CUSTOMER_STATE`. Applies to every action endpoint."

    PRD §3.1: "It requires the batch to be at `stage` `BLENDED` with `qc_status`
    still `PENDING`, and requires `pressed_units` to be at least 1."

    PRD §3.4: "dressing a wheel that is not at `DRESSING` is rejected with
    `ERR_INVALID_WHEEL_STATE`."

    PRD §3.8: "`CLOSED` is terminal and advances the customer's `version` by 1."

    Design: Corner/state_machines/repeated_actions_rejected_from_already_advanced_states
    """
    pilot = fx.pilot_grade_with_passed_batch(api)
    geometry = fx.released_geometry(api)
    wheel = fx.grinding_wheel(api)
    customer = fx.customer(
        api, customer_code="CU-3", name="Gamma Grinding", tier="STANDARD",
        regrind_credit_cents=0,
    )
    validate_success(
        api.close_customer(customer["id"], f.close_customer_payload(), PLAN)
    )

    validate_error(
        api.press_powder_blend_batch(pilot["batch"]["id"], f.press_payload(), MET),
        ApiErrorId.ERR_INVALID_BATCH_STATE,
        409,
    )
    validate_error(
        api.release_insert_geometry(geometry["id"], GEO),
        ApiErrorId.ERR_INVALID_GEOMETRY_STATE,
        409,
    )
    validate_error(
        api.start_grade_pilot(pilot["grade"]["id"], MET),
        ApiErrorId.ERR_INVALID_GRADE_STATE,
        409,
    )
    validate_error(
        api.dress_grinding_wheel(wheel["id"], PLAN, f.dress_wheel_payload()),
        ApiErrorId.ERR_INVALID_WHEEL_STATE,
        409,
    )
    validate_error(
        api.close_customer(customer["id"], f.close_customer_payload(), PLAN),
        ApiErrorId.ERR_INVALID_CUSTOMER_STATE,
        409,
    )


def test_the_refused_replays_leave_every_row_exactly_as_it_stood(api):
    """A second press does not re-press, and a refused dress does not dress.

    PRD §3.1: "Pressing advances the `stage` dimension from `BLENDED` to
    `PRESSED` and records `pressed_units`, the number of green compacts the press
    produced."

    PRD §3.4: "When `dress_count` plus one is at most 3, the wheel moves
    `DRESSING` → `AVAILABLE`, `consumed_life_units` is reset to 0 so that
    `remaining_life_units` returns to the full `initial_life_units`, and
    `dress_count` advances by 1"

    Design: Corner/state_machines/repeated_actions_rejected_from_already_advanced_states
    """
    pilot = fx.pilot_grade_with_passed_batch(api)
    wheel = fx.grinding_wheel(api)

    validate_error(
        api.press_powder_blend_batch(pilot["batch"]["id"], f.press_payload(), MET),
        ApiErrorId.ERR_INVALID_BATCH_STATE,
        409,
    )
    validate_error(
        api.dress_grinding_wheel(wheel["id"], PLAN, f.dress_wheel_payload()),
        ApiErrorId.ERR_INVALID_WHEEL_STATE,
        409,
    )

    batch = validate_success(api.get_powder_blend_batch(pilot["batch"]["id"], MET))
    assert batch["stage"] == "SINTERED", (
        f"the refused press leaves the batch sintered, got {batch['stage']}"
    )
    assert batch["pressed_units"] == 200, (
        f"the press count is not applied twice, got {batch['pressed_units']}"
    )
    wheel_after = validate_success(api.get_grinding_wheel(wheel["id"], PLAN))
    assert wheel_after["dress_count"] == 0, (
        f"a refused dress does not count as a dressing, got {wheel_after['dress_count']}"
    )
    assert wheel_after["consumed_life_units"] == 0, (
        f"nothing was consumed and nothing was reset, got {wheel_after['consumed_life_units']}"
    )
    assert wheel_after["status"] == "AVAILABLE", (
        f"the wheel is still the wheel it was, got {wheel_after['status']}"
    )


# ─── Terminal states ────────────────────────────────────────────────────────

def test_a_voided_grinding_run_accepts_neither_completion_nor_a_second_void(api):
    """VOIDED is terminal, and the wheel it named was never charged.

    PRD §3.4: "Voiding a `SCHEDULED` run does none of that: no wheel life is
    reversed, because none was ever charged, and the only effect beyond the
    terminal `SCHEDULED` → `VOIDED` move is that the cell's occupation window is
    released for another booking."

    PRD §3.4: "Closing out a grinding run requires the run to be `SCHEDULED`,
    requires the logical clock to have reached `window_end` (otherwise
    `ERR_WINDOW_NOT_ELAPSED`), and requires `produced_units` plus `scrap_units` to
    equal `planned_units` exactly (otherwise `ERR_UNIT_COUNT_MISMATCH`)."

    Design: Corner/state_machines/voided_grinding_run_cannot_be_completed
    """
    state = fx.scheduled_grinding_run(
        api, wheel_overrides={"initial_life_units": 100000}, planned_units=5
    )
    validate_success(
        api.void_grinding_run(
            state["run"]["id"], f.void_grinding_run_payload(), PLAN
        )
    )
    fx.advance_clock(api, state["run"]["window_end"])

    complete = api.complete_grinding_run(
        state["run"]["id"],
        f.complete_grinding_run_payload(
            produced_units=5, scrap_units=0, measured_diameter_dev_um=3.0
        ),
        PLAN,
    )
    second_void = api.void_grinding_run(
        state["run"]["id"], f.void_grinding_run_payload(), APPROVER
    )

    validate_error(complete, ApiErrorId.ERR_INVALID_GRINDING_RUN_STATE, 409)
    validate_error(second_void, ApiErrorId.ERR_INVALID_GRINDING_RUN_STATE, 409)
    run = validate_success(api.get_grinding_run(state["run"]["id"], PLAN))
    assert run["status"] == "VOIDED", (
        f"the run stays where the void left it, got {run['status']}"
    )
    assert run["consumed_life_units"] == 0, (
        f"a run voided from SCHEDULED never charged anything, got {run['consumed_life_units']}"
    )
    assert run["tolerance_class"] is None, (
        f"no measurement was ever accepted, got {run['tolerance_class']}"
    )
    wheel = validate_success(api.get_grinding_wheel(state["wheel"]["id"], PLAN))
    assert wheel["consumed_life_units"] == 0, (
        f"the wheel was never charged, got {wheel['consumed_life_units']}"
    )
    assert wheel["remaining_life_units"] == 100000, (
        f"the wheel carries its full life, got {wheel['remaining_life_units']}"
    )
    assert_wheel_life_conserved(wheel)


# ─── Voiding a booking releases the cell ────────────────────────────────────

def test_voiding_a_booking_releases_the_cell_for_the_identical_window(api):
    """The window is refused while the run stands and accepted once it is voided.

    PRD §3.4: "If the requested closed window intersects the closed window of any
    `SCHEDULED` or `COMPLETED` run already in that cell, the booking is rejected
    with `ERR_CELL_DOUBLE_BOOKED`"

    PRD §3.4: "the only effect beyond the terminal `SCHEDULED` → `VOIDED` move is
    that the cell's occupation window is released for another booking."

    Design: Corner/state_machines/void_from_scheduled_frees_the_cell_without_charging_life
    """
    state = fx.scheduled_grinding_run(
        api, wheel_overrides={"initial_life_units": 100000}, planned_units=5
    )
    identical = f.grinding_run_payload(
        state["wheel"]["id"], state["product"]["id"], planned_units=5
    )

    while_busy = api.create_grinding_run(identical, PLAN)
    validate_success(
        api.void_grinding_run(state["run"]["id"], f.void_grinding_run_payload(), PLAN)
    )
    after_void = api.create_grinding_run(identical, PLAN)

    validate_error(while_busy, ApiErrorId.ERR_CELL_DOUBLE_BOOKED, 409)
    rebooked = validate_success(after_void, 201)
    assert rebooked["status"] == "SCHEDULED", (
        f"the freed window is bookable again, got {rebooked['status']}"
    )
    assert rebooked["window_start"] == state["run"]["window_start"], (
        "the replacement occupies the very window the voided run held, got "
        f"{rebooked['window_start']}"
    )
    rows, _meta = validate_paginated(api.list_grinding_runs(PLAN))
    assert len(rows) == 2, (
        f"the refused booking created no row, so only two runs exist, got {len(rows)}"
    )


def test_voiding_a_booking_charges_and_reverses_no_wheel_life_at_all(api):
    """The wheel is untouched by the void, including its version.

    PRD §3.4: "Voiding a `SCHEDULED` run does none of that: no wheel life is
    reversed, because none was ever charged"

    PRD §3.4: "Both paths advance the run's `version`; the completed path also
    advances the wheel's."

    Design: Corner/state_machines/void_from_scheduled_frees_the_cell_without_charging_life
    """
    state = fx.scheduled_grinding_run(
        api, wheel_overrides={"initial_life_units": 100000}, planned_units=5
    )
    before = validate_success(api.get_grinding_wheel(state["wheel"]["id"], PLAN))

    voided = validate_success(
        api.void_grinding_run(state["run"]["id"], f.void_grinding_run_payload(), PLAN)
    )

    assert voided["status"] == "VOIDED", (
        f"a booked run may be voided outright, got {voided['status']}"
    )
    wheel = validate_success(api.get_grinding_wheel(state["wheel"]["id"], PLAN))
    assert wheel["consumed_life_units"] == 0, (
        f"there was nothing to reverse, got {wheel['consumed_life_units']}"
    )
    assert wheel["status"] == "AVAILABLE", (
        f"the wheel never left AVAILABLE, got {wheel['status']}"
    )
    assert wheel["version"] == before["version"], (
        "only the completed void path advances the wheel's version, got "
        f"{wheel['version']} against {before['version']}"
    )


# ─── The approval side-effect set ───────────────────────────────────────────

def test_a_product_cannot_be_released_before_its_dossier_is_approved(api):
    """A SUBMITTED dossier is not an approved one, so release is refused.

    PRD §3.5: "Release is the `QualityApprover`'s decision and is the only path
    from `QUALIFICATION` to `RELEASED`. It requires at least one qualification
    dossier on the product to be `APPROVED` and `tool_life_index` to be non-null —
    a failure of either is `ERR_NO_APPROVED_DOSSIER`"

    PRD §3.7: "Approval does **not** release the product: it stays in
    `QUALIFICATION` and still requires the explicit release described in §3.5."

    Design: Corner/state_machines/dossier_approval_promotes_the_grade_and_writes_the_tool_life_index
    """
    state = fx.submitted_dossier(api)

    response = api.release_tool_product(state["product"]["id"], APPROVER)

    validate_error(response, ApiErrorId.ERR_NO_APPROVED_DOSSIER, 409)
    product = validate_success(api.get_tool_product(state["product"]["id"], APP))
    assert product["release_status"] == "QUALIFICATION", (
        f"the refused release leaves the product in qualification, got {product['release_status']}"
    )
    assert product["tool_life_index"] is None, (
        f"no approval has written the index yet, got {product['tool_life_index']}"
    )


def test_one_approval_writes_the_index_and_qualifies_the_grade(api):
    """The approval fires its side-effect set across the dossier, product and grade.

    PRD §3.7: "`tool_life_index` becomes the unweighted mean of those trials'
    `rated_life_min` values — the sum divided by the trial count, not weighted by
    `units_consumed` — rounded half up to one decimal place, and is null when no
    such trial exists."

    PRD §3.7: "`qualified_workpiece_groups` becomes the distinct
    `workpiece_group` values of those trials, sorted ascending by the alphabetical
    spelling of the enum value."

    PRD §3.7: "It does, however, complete the grade's own qualification: if the
    product's grade is at `PILOT`, the grade moves `PILOT` → `QUALIFIED` in the
    same request."

    Design: Corner/state_machines/dossier_approval_promotes_the_grade_and_writes_the_tool_life_index
    """
    state = fx.submitted_dossier(api)

    dossier = validate_success(
        api.approve_qualification_dossier(
            state["dossier"]["id"], f.approve_dossier_payload(), APPROVER
        )
    )

    assert dossier["status"] == "APPROVED", (
        f"a submitted dossier may be approved, got {dossier['status']}"
    )
    assert dossier["decided_by_user_id"] == "qa-3", (
        f"the deciding approver is recorded, got {dossier['decided_by_user_id']}"
    )
    product = validate_success(api.get_tool_product(state["product"]["id"], APP))
    assert product["tool_life_index"] == 21.7, (
        "the mean of the 20.0-minute P trial and the 23.3-minute M trial is 21.65, "
        f"which rounds half up to 21.7, got {product['tool_life_index']}"
    )
    assert product["qualified_workpiece_groups"] == ["M", "P"], (
        f"the two groups are sorted alphabetically, got {product['qualified_workpiece_groups']}"
    )
    assert product["release_status"] == "QUALIFICATION", (
        f"approval alone does not release the product, got {product['release_status']}"
    )
    grade = validate_success(api.get_carbide_grade(state["grade"]["id"], MET))
    assert grade["status"] == "QUALIFIED", (
        f"the pilot grade is promoted in the same request, got {grade['status']}"
    )


def test_release_after_approval_stocks_the_catalogue_product(api):
    """Once approved, the release moves both product dimensions and counts the grade.

    PRD §3.5: "On release the `supply_status` dimension moves in the same
    request, and it moves differently by class: a `CATALOG` product goes
    `UNAVAILABLE` → `STOCKED`, skipping `MAKE_TO_ORDER` entirely, while a
    `SPECIAL` product goes `UNAVAILABLE` → `MAKE_TO_ORDER` and stops there."

    PRD §3.5: "Lead time and expedite eligibility are recomputed, the grade's
    `qualified_product_count` advances by 1, and both the product's `version` and
    the grade's `version` advance by 1."

    Design: Corner/state_machines/dossier_approval_promotes_the_grade_and_writes_the_tool_life_index
    """
    state = fx.approved_dossier(api)

    product = validate_success(api.release_tool_product(state["product"]["id"], APPROVER))

    assert product["release_status"] == "RELEASED", (
        f"an approved product may be released, got {product['release_status']}"
    )
    assert product["supply_status"] == "STOCKED", (
        f"a catalogue product is stocked on release, got {product['supply_status']}"
    )
    grade = validate_success(api.get_carbide_grade(state["grade"]["id"], MET))
    assert grade["qualified_product_count"] == 1, (
        f"the release counts one qualified product on the grade, got {grade['qualified_product_count']}"
    )


# ─── The rejection side-effect set ──────────────────────────────────────────

def test_a_rejection_sends_the_product_back_to_development(api):
    """Rejection drops the product a state and clears all three pins.

    PRD §3.7: "It requires a `decision_note` rather than accepting an optional
    one, records `decided_by_user_id`, and sends the product back:
    `release_status` moves `QUALIFICATION` → `DEVELOPMENT` and all three of
    `pinned_grade_revision`, `pinned_geometry_revision` and
    `pinned_coating_revision` are set to null, so the product must re-enter
    qualification under a fresh dossier before it can ever be released."

    PRD §3.7: "There is no release, no grade qualification and no index
    recomputation on this branch."

    Design: Corner/state_machines/dossier_rejection_returns_the_product_to_development
    """
    state = fx.submitted_dossier(api)

    dossier = validate_success(
        api.reject_qualification_dossier(
            state["dossier"]["id"], f.reject_dossier_payload(), APPROVER
        )
    )

    assert dossier["status"] == "REJECTED", (
        f"a submitted dossier may be rejected, got {dossier['status']}"
    )
    product = validate_success(api.get_tool_product(state["product"]["id"], APP))
    assert product["release_status"] == "DEVELOPMENT", (
        f"the product is sent back a state, got {product['release_status']}"
    )
    assert product["supply_status"] == "UNAVAILABLE", (
        f"nothing ever moved the supply dimension, got {product['supply_status']}"
    )
    assert product["pinned_grade_revision"] is None, (
        f"the grade pin is cleared, got {product['pinned_grade_revision']}"
    )
    assert product["pinned_geometry_revision"] is None, (
        f"the geometry pin is cleared, got {product['pinned_geometry_revision']}"
    )
    assert product["pinned_coating_revision"] is None, (
        f"the coating pin is cleared, got {product['pinned_coating_revision']}"
    )
    assert product["tool_life_index"] is None, (
        f"no index is written on this branch, got {product['tool_life_index']}"
    )
    assert product["qualified_workpiece_groups"] == [], (
        f"no group is qualified on this branch, got {product['qualified_workpiece_groups']}"
    )
    grade = validate_success(api.get_carbide_grade(state["grade"]["id"], MET))
    assert grade["status"] == "PILOT", (
        f"the grade is not promoted on this branch, got {grade['status']}"
    )
    assert grade["qualified_product_count"] == 0, (
        f"nothing was released, got {grade['qualified_product_count']}"
    )


def test_a_rejected_dossier_cannot_be_approved_and_its_product_cannot_be_released(api):
    """REJECTED is terminal, and DEVELOPMENT is not a state release can start from.

    PRD §3.7: "A rejection is equally terminal but has a deliberately different
    side-effect set."

    PRD §3.5: "Release is the `QualityApprover`'s decision and is the only path
    from `QUALIFICATION` to `RELEASED`."

    Design: Corner/state_machines/dossier_rejection_returns_the_product_to_development
    """
    state = fx.submitted_dossier(api)
    validate_success(
        api.reject_qualification_dossier(
            state["dossier"]["id"], f.reject_dossier_payload(), APPROVER
        )
    )

    late_approve = api.approve_qualification_dossier(
        state["dossier"]["id"], f.approve_dossier_payload(), APPROVER
    )
    release = api.release_tool_product(state["product"]["id"], APPROVER)

    validate_error(late_approve, ApiErrorId.ERR_INVALID_DOSSIER_STATE, 409)
    validate_error(release, ApiErrorId.ERR_INVALID_PRODUCT_STATE, 409)
    dossier = validate_success(
        api.get_qualification_dossier(state["dossier"]["id"], APP)
    )
    assert dossier["status"] == "REJECTED", (
        f"the decision stands, got {dossier['status']}"
    )


# ─── Triggers refused from states that are not their source ─────────────────

def test_an_open_dossier_accepts_neither_approval_nor_rejection(api):
    """A decision may only be taken on a dossier that has been submitted.

    PRD §3.7: "Submitting a dossier is an `ApplicationEngineer` act. It requires
    the dossier to be `OPEN`, the product's `release_status` to still be
    `QUALIFICATION`, and `completed_trial_count` to be at least
    `required_trial_count`"

    PRD §3.7: "An approval moves the dossier `SUBMITTED` → `APPROVED`, which is
    terminal."

    Design: Corner/state_machines/trial_and_dossier_triggers_not_in_their_transition_lists
    """
    state = fx.open_dossier(api, coated=False)

    approve = api.approve_qualification_dossier(
        state["dossier"]["id"], f.approve_dossier_payload(), APPROVER
    )
    reject = api.reject_qualification_dossier(
        state["dossier"]["id"], f.reject_dossier_payload(), APPROVER
    )

    validate_error(approve, ApiErrorId.ERR_INVALID_DOSSIER_STATE, 409)
    validate_error(reject, ApiErrorId.ERR_INVALID_DOSSIER_STATE, 409)
    dossier = validate_success(
        api.get_qualification_dossier(state["dossier"]["id"], APP)
    )
    assert dossier["status"] == "OPEN", (
        f"neither refused decision moved the dossier, got {dossier['status']}"
    )


def test_a_completed_trial_refuses_a_second_well_formed_wear_curve(api):
    """The replacement curve is legal, but completion is only legal from RUNNING.

    PRD §3.6: "The trial must be `RUNNING`, and the supplying batch's `qc_status`
    must still be `PASSED`."

    PRD §3.6: "The curve must hold at least 2 entries, its `minutes` values must
    be strictly increasing, its `vb_um` values must be non-decreasing, and its
    last two `vb_um` values must not be equal; a curve that fails any of those is
    rejected with `ERR_INVALID_WEAR_CURVE`."

    PRD §3.6: "`completed_trial_count` becomes the number of trials on the
    dossier whose `status` is `COMPLETED`, of any verdict, and `passed_trial_count`
    the number of those whose `verdict` is `PASS`."

    Design: Corner/state_machines/trial_and_dossier_triggers_not_in_their_transition_lists
    """
    state = fx.open_dossier(api, coated=False)
    trial = validate_success(
        api.create_machining_trial(
            f.trial_payload(state["dossier"]["id"], state["batch"]["id"]), OPERATOR_ONE
        ),
        201,
    )

    first = validate_success(
        api.complete_machining_trial(
            trial["id"], f.complete_trial_payload(), OPERATOR_ONE
        )
    )
    second = api.complete_machining_trial(
        trial["id"],
        f.complete_trial_payload(
            wear_measurements=[
                {"minutes": 0, "vb_um": 0},
                {"minutes": 10, "vb_um": 200},
                {"minutes": 20, "vb_um": 310},
            ],
            measured_surface_ra_um=1.10,
        ),
        OPERATOR_ONE,
    )

    assert first["status"] == "COMPLETED", (
        f"the first closure succeeds, got {first['status']}"
    )
    assert first["rated_life_min"] == 20.0, (
        "the curve crosses 300 um a third of the way from 18 to 24 minutes, got "
        f"{first['rated_life_min']}"
    )
    assert first["verdict"] == "PASS", (
        f"20.0 minutes and 1.20 um clear the MEDIUM class limits, got {first['verdict']}"
    )
    validate_error(second, ApiErrorId.ERR_INVALID_TRIAL_STATE, 409)
    unchanged = validate_success(api.get_machining_trial(trial["id"], APP))
    assert unchanged["rated_life_min"] == 20.0, (
        f"the refused replacement changes no figure, got {unchanged['rated_life_min']}"
    )
    assert unchanged["measured_surface_ra_um"] == 1.20, (
        f"the recorded roughness stands, got {unchanged['measured_surface_ra_um']}"
    )
    dossier = validate_success(
        api.get_qualification_dossier(state["dossier"]["id"], APP)
    )
    assert dossier["status"] == "OPEN", (
        f"the dossier is still taking trials, got {dossier['status']}"
    )
    assert dossier["completed_trial_count"] == 1, (
        f"exactly one trial has been closed out, got {dossier['completed_trial_count']}"
    )
    assert dossier["composite_score"] == 1.20, (
        "one subscore of 0.6 x (20.0 / 18.0) plus 0.4 x (1.6 / 1.20) is 1.20, got "
        f"{dossier['composite_score']}"
    )


# ─── A bounded loop and the branch it takes on the last turn ────────────────

def _wheel_through_grind_and_dress_cycles(api, cycles: int) -> dict:
    """Runs `cycles` rounds of a 43-tool run, its completion and one dressing.

    Each round charges 43 x 20 = 860 units against a 1000-unit wheel, which drops
    remaining life to 140 and sends the wheel to DRESSING; the dressing that
    follows is the loop's second half. Windows are two hours long and spaced an
    hour apart so the 45-minute setup buffer is always clear.
    """
    state = fx.endmill_product(api)
    state["wheel"] = fx.grinding_wheel(api, wheel_code="WH-2", initial_life_units=1000)
    state["runs"] = []
    state["dressings"] = []
    for cycle in range(cycles):
        start_hour = 6 + 3 * cycle
        run = validate_success(
            api.create_grinding_run(
                f.grinding_run_payload(
                    state["wheel"]["id"],
                    state["product"]["id"],
                    window_start=f"2026-08-12T{start_hour:02d}:00:00Z",
                    window_end=f"2026-08-12T{start_hour + 2:02d}:00:00Z",
                ),
                PLAN,
            ),
            201,
        )
        fx.advance_clock(api, run["window_end"])
        state["runs"].append(
            validate_success(
                api.complete_grinding_run(
                    run["id"],
                    f.complete_grinding_run_payload(
                        produced_units=43, scrap_units=0, measured_diameter_dev_um=4.0
                    ),
                    PLAN,
                )
            )
        )
        state["dressings"].append(
            validate_success(
                api.dress_grinding_wheel(
                    state["wheel"]["id"], PLAN, f.dress_wheel_payload()
                )
            )
        )
    return state


def test_the_first_three_dressings_restore_the_wheel_to_its_full_life(api):
    """Each of the three permitted dressings resets the charge and counts up.

    PRD §3.4: "When `dress_count` plus one is at most 3, the wheel moves
    `DRESSING` → `AVAILABLE`, `consumed_life_units` is reset to 0 so that
    `remaining_life_units` returns to the full `initial_life_units`, and
    `dress_count` advances by 1 — the cycle `AVAILABLE` → `DRESSING` →
    `AVAILABLE` that a wheel walks up to three times."

    PRD §3.4: "Because the charge may push the wheel's `remaining_life_units`
    below the 150-unit dressing threshold, a wheel at `AVAILABLE` whose remaining
    life is now under 150 moves `AVAILABLE` → `DRESSING` in the same request."

    Design: Corner/state_machines/wheel_expires_after_the_maximum_dress_count
    """
    state = _wheel_through_grind_and_dress_cycles(api, 3)

    for index, dressed in enumerate(state["dressings"], start=1):
        assert dressed["status"] == "AVAILABLE", (
            f"dressing {index} of at most three restores the wheel, got {dressed['status']}"
        )
        assert dressed["dress_count"] == index, (
            f"the dressing counter advances by one each time, got {dressed['dress_count']}"
        )
        assert dressed["consumed_life_units"] == 0, (
            f"the charge is reset on this branch, got {dressed['consumed_life_units']}"
        )
        assert dressed["remaining_life_units"] == 1000, (
            f"the full declared life is back, got {dressed['remaining_life_units']}"
        )
    wheel = validate_success(api.get_grinding_wheel(state["wheel"]["id"], PLAN))
    assert wheel["dress_count"] == 3, (
        f"three dressings have been used, got {wheel['dress_count']}"
    )
    assert_wheel_life_conserved(wheel)


def test_the_fourth_dressing_expires_the_wheel_and_keeps_its_charge(api):
    """The same trigger changes branch: EXPIRED, counted, and deliberately not reset.

    PRD §3.4: "When `dress_count` plus one would exceed 3, the same request
    instead moves the wheel `DRESSING` → `EXPIRED`: `dress_count` still advances
    by 1, but `consumed_life_units` is deliberately *not* reset, so the expired
    wheel's remaining life stands as a record of how it ended."

    PRD §3.4: "Then the wheel is charged: the run's own `consumed_life_units` is
    set to `produced_units` plus `scrap_units`, multiplied by the ground product's
    `grind_units_per_tool`, and that figure is added to the wheel's
    `consumed_life_units`."

    Design: Corner/state_machines/wheel_expires_after_the_maximum_dress_count
    """
    state = _wheel_through_grind_and_dress_cycles(api, 4)

    expired = state["dressings"][3]
    assert expired["status"] == "EXPIRED", (
        f"a fourth dressing exceeds the maximum, got {expired['status']}"
    )
    assert expired["dress_count"] == 4, (
        f"the counter still advances on this branch, got {expired['dress_count']}"
    )
    assert expired["consumed_life_units"] == 860, (
        "43 tools at 20 units each is 860, and this branch does not reset it, got "
        f"{expired['consumed_life_units']}"
    )
    assert expired["remaining_life_units"] == 140, (
        f"1000 less 860 stands as the record, got {expired['remaining_life_units']}"
    )
    assert_wheel_life_conserved(expired)


def test_an_expired_wheel_can_neither_be_mounted_nor_dressed_again(api):
    """EXPIRED is terminal: a booking is refused and so is a further dressing.

    PRD §3.4: "A wheel already at `EXPIRED` cannot be mounted at all and the
    booking is rejected with `ERR_WHEEL_EXPIRED`; a wheel at `DRESSING` is
    rejected with `ERR_WHEEL_REQUIRES_DRESSING`, because it has fallen below its
    dressing threshold and has not yet been restored."

    PRD §3.4: "dressing a wheel that is not at `DRESSING` is rejected with
    `ERR_INVALID_WHEEL_STATE`."

    Design: Corner/state_machines/wheel_expires_after_the_maximum_dress_count
    """
    state = _wheel_through_grind_and_dress_cycles(api, 4)

    booking = api.create_grinding_run(
        f.grinding_run_payload(
            state["wheel"]["id"],
            state["product"]["id"],
            cell_id="CELL_B",
            window_start="2026-08-13T06:00:00Z",
            window_end="2026-08-13T08:00:00Z",
            planned_units=10,
        ),
        PLAN,
    )
    dressing = api.dress_grinding_wheel(
        state["wheel"]["id"], PLAN, f.dress_wheel_payload()
    )

    validate_error(booking, ApiErrorId.ERR_WHEEL_EXPIRED, 409)
    validate_error(dressing, ApiErrorId.ERR_INVALID_WHEEL_STATE, 409)
    wheel = validate_success(api.get_grinding_wheel(state["wheel"]["id"], PLAN))
    assert wheel["status"] == "EXPIRED", (
        f"the wheel is finished for good, got {wheel['status']}"
    )
    assert wheel["dress_count"] == 4, (
        f"the refused dressing does not count, got {wheel['dress_count']}"
    )
