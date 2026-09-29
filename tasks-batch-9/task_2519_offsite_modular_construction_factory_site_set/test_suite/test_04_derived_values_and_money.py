"""Derived quantities: envelope tiers, compatibility points, money and postures.

Almost nothing interesting in this system is stored by the caller. A module's
shipping envelope class falls out of its own three dimensions against two tiers
of ceilings; a load's permit fee and escort obligation fall out of the widest
module aboard and the length of the route; a design revision's compatibility
score is one hundred minus four additive penalty weights; a lender's draw
amount rounds once per module, once for the deposit rate and once for
retainage; a defect charge splits by discovery-phase presumption with the field
side absorbing the remainder; and a project's permit posture and phase are both
full re-scans of their children with a normative branch order.

The tests below pin those numbers at their thresholds and one unit either side
of them, and they check that a recomputation genuinely re-reads live state
rather than replaying a figure captured earlier.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_WEATHER_EXPOSURE_LIMIT
from test_helpers.assertions import (
    assert_cents,
    assert_module_dimensions,
    assert_two_decimal_value,
    expected_compatibility_score,
)
from test_helpers.test_users import (
    AUTHORITY_HAVING_JURISDICTION,
    DESIGN_ENGINEER_SUBMITTER,
    LENDER_DRAW_ADMINISTRATOR,
    PROGRAM_ADMIN,
    STATE_PROGRAM_OFFICER,
    TRANSPORT_COORDINATOR,
    WARRANTY_ADJUDICATOR,
)


# ─── Shared preconditions ─────────────────────────────────────────────────────
@pytest.fixture
def project_awaiting_its_first_modules(api):
    """A plant and a project with one DRAFT revision to detail modules against.

    Classifying a shipping envelope reads nothing but the module's own numbers,
    so the revision is deliberately left unfrozen.
    """
    world = fx.world_plant_and_project(api)
    world.package = fx.create_design_package(
        api, world.project_id, world.project["version"]
    )
    return world


def _declare_module(world, module_code, set_sequence_index, **envelope):
    """Create one module of the fixture's project with a stated envelope."""
    return validate_success(
        world.api.create_module(
            f.module_payload(
                world.project_id,
                world.package_id,
                module_code,
                set_sequence_index,
                **envelope,
            ),
            world.factory_manager,
        ),
        201,
    )


# ─── The shipping envelope width ceiling ──────────────────────────────────────
@pytest.mark.parametrize(
    "width_in, expected_class",
    [(191, "STANDARD"), (192, "STANDARD"), (193, "OVERWIDTH")],
)
def test_a_module_stays_standard_up_to_one_hundred_ninety_two_inches_wide(
    project_awaiting_its_first_modules, width_in, expected_class
):
    """PRD §3.4: "Otherwise, if `width_in` is greater than 192 inches — sixteen feet — or `height_in` is greater than 162 inches, or `gross_weight_lb` is greater than 80,000 pounds, then `envelope_class` is `OVERWIDTH`."
    PRD §3.4: "Every comparison is strictly greater-than against the ceiling, so a module measuring exactly 192 inches wide, exactly 162 inches high and weighing exactly 80,000 pounds is still `STANDARD`."

    Design: Corner/calculations/envelope_class_threshold_triplet_at_the_standard_width_ceiling
    """
    world = project_awaiting_its_first_modules

    module = _declare_module(
        world,
        f"W-{width_in}",
        1,
        width_in=width_in,
        length_in=720,
        height_in=156,
        gross_weight_lb=76600,
    )

    # One inch below the ceiling, exactly at it, and one inch past it.
    assert module["envelope_class"] == expected_class, (
        f"a {width_in} inch module should classify as {expected_class}, "
        f"got {module['envelope_class']}"
    )


def test_a_very_long_module_at_the_width_ceiling_is_still_a_standard_envelope(
    project_awaiting_its_first_modules,
):
    """PRD §3.4: "The `length_in` measurement never affects the class at all; it exists only to feed route-survey judgement downstream."
    PRD §3.4: "Otherwise it is `STANDARD`."

    Design: Corner/calculations/envelope_class_threshold_triplet_at_the_standard_width_ceiling
    """
    world = project_awaiting_its_first_modules

    # 900 inches long — seventy-five feet — but exactly at the width ceiling.
    module = _declare_module(
        world,
        "W-192",
        1,
        width_in=192,
        length_in=900,
        height_in=156,
        gross_weight_lb=76600,
    )

    assert module["envelope_class"] == "STANDARD"
    assert module["length_in"] == 900


# ─── The tier ladder read widest-first ────────────────────────────────────────
@pytest.mark.parametrize(
    "height_in, expected_class",
    [(162, "STANDARD"), (174, "OVERWIDTH"), (175, "SUPERLOAD")],
)
def test_module_height_climbs_the_tier_ladder_from_standard_to_superload(
    project_awaiting_its_first_modules, height_in, expected_class
):
    """PRD §3.4: "The tiers are evaluated widest-first, so that a single dimension breaching the overwidth ceiling classifies the whole module as a superload."
    PRD §3.4: "If `width_in` is greater than 216 inches — eighteen feet — or `height_in` is greater than 174 inches, or `gross_weight_lb` is greater than 120,000 pounds, then `envelope_class` is `SUPERLOAD`."
    PRD §3.4: "Every comparison is strictly greater-than against the ceiling, so a module measuring exactly 192 inches wide, exactly 162 inches high and weighing exactly 80,000 pounds is still `STANDARD`."

    Design: Corner/calculations/envelope_class_evaluates_the_widest_tier_first_on_height
    """
    world = project_awaiting_its_first_modules

    # Width 180 and weight 76,600 are both standard, so height decides alone.
    module = _declare_module(
        world,
        f"H-{height_in}",
        1,
        width_in=180,
        length_in=600,
        height_in=height_in,
        gross_weight_lb=76600,
    )

    assert module["envelope_class"] == expected_class, (
        f"a {height_in} inch high module should classify as {expected_class}, "
        f"got {module['envelope_class']}"
    )


@pytest.mark.parametrize(
    "gross_weight_lb, expected_class",
    [(79999, "STANDARD"), (80000, "STANDARD"), (80001, "OVERWIDTH")],
)
def test_gross_weight_crosses_into_overwidth_one_pound_past_eighty_thousand(
    project_awaiting_its_first_modules, gross_weight_lb, expected_class
):
    """PRD §3.4: "The **shipping envelope class** is classified at creation and re-read whenever the module's dimensions or weight are restated, and it is a pure function of the module alone with no aggregation."
    PRD §3.4: "Otherwise, if `width_in` is greater than 192 inches — sixteen feet — or `height_in` is greater than 162 inches, or `gross_weight_lb` is greater than 80,000 pounds, then `envelope_class` is `OVERWIDTH`."

    Design: Corner/calculations/envelope_class_evaluates_the_widest_tier_first_on_height
    """
    world = project_awaiting_its_first_modules

    module = _declare_module(
        world,
        f"G-{gross_weight_lb}",
        1,
        width_in=180,
        length_in=600,
        height_in=156,
        gross_weight_lb=gross_weight_lb,
    )

    assert module["envelope_class"] == expected_class, (
        f"a {gross_weight_lb} lb module should classify as {expected_class}, "
        f"got {module['envelope_class']}"
    )


# ─── Which modules the work-in-progress basis admits ──────────────────────────
@pytest.fixture
def a_plant_floor_with_one_module_never_scheduled(api):
    """Three modules of one project: one off the line, one half way, one idle.

    M-01 has run all six stations, M-02 stands at station 2 of 6, and M-03 has
    never claimed a takt window at all.
    """
    world = fx.world_with_module(api)
    fx.add_module(world, "M-02", 2)
    fx.add_module(world, "M-03", 3)
    fx.schedule_slot(world, "M-01", "2026-09-02T14:00:00Z")
    fx.advance_stations(world, "M-01", 6)
    fx.schedule_slot(world, "M-02", "2026-09-03T14:00:00Z")
    fx.advance_stations(world, "M-02", 2)
    return world


def test_a_module_that_never_claimed_a_takt_window_is_left_out_of_the_deposit_basis(
    a_plant_floor_with_one_module_never_scheduled,
):
    """PRD §3.9: "Under `WIP_DEPOSIT`, the basis is every module of the project whose `production_status` is `SLOTTED`, `IN_LINE` or `LINE_COMPLETE` and whose `qc_status` is not `HOLD`; each such module contributes its station-progress earned value as defined in §3.4 — the plant's `wip_unit_value_cents` pro-rated by completed stations — and a module that has never left the plant contributes normally."
    PRD §3.9: "`basis_module_count` is the number of modules in the basis and `basis_earned_cents` is the sum of those already-rounded per-module terms."
    PRD §3.9: "Under `WIP_DEPOSIT`, `requested_cents` is `basis_earned_cents` multiplied by the project's `deposit_pct` — 20 percent of work in progress by default — rounded half up to a whole cent."

    Design: Corner/calculations/wip_basis_input_set_filtering_excludes_planned_modules
    """
    world = a_plant_floor_with_one_module_never_scheduled

    draw = validate_success(
        world.api.create_draw_request(
            f.draw_request_payload(world.project_id, world.agency_id, "WIP_DEPOSIT", 1),
            LENDER_DRAW_ADMINISTRATOR,
        ),
        201,
    )

    # Only M-01 and M-02 qualify: 8,750,000 plus 2,916,667 for station 2 of 6.
    assert draw["basis_module_count"] == 2
    assert_cents(draw["basis_earned_cents"], 11666667, "basis_earned_cents")
    # 11,666,667 x 0.20 is 2,333,333.4, which rounds down to 2,333,333.
    assert_cents(draw["requested_cents"], 2333333, "requested_cents")
    assert draw["status"] == "DRAFT"


def test_a_planned_module_has_earned_nothing_while_a_half_built_one_has(
    a_plant_floor_with_one_module_never_scheduled,
):
    """PRD §3.4: "When the module's `production_status` is `SLOTTED`, `IN_LINE` or `LINE_COMPLETE` *and* its `qc_status` is not `HOLD`, the earned value is the plant's `wip_unit_value_cents` multiplied by the module's `station_index`, divided by the plant's `station_count`, and rounded half up to a whole cent."
    PRD §3.4: "In every other case — a module still `PLANNED`, or any module under an agency hold — the earned value is 0."

    Design: Corner/calculations/wip_basis_input_set_filtering_excludes_planned_modules
    """
    world = a_plant_floor_with_one_module_never_scheduled

    off_the_line = world.refresh_module("M-01")
    half_way = world.refresh_module("M-02")
    never_scheduled = world.refresh_module("M-03")

    assert_module_dimensions(off_the_line, production_status="LINE_COMPLETE")
    assert_cents(off_the_line["wip_earned_cents"], 8750000, "M-01 wip_earned_cents")
    assert_module_dimensions(half_way, production_status="IN_LINE")
    # 8,750,000 x 2 / 6 is 2,916,666.67, which rounds half up to 2,916,667.
    assert_cents(half_way["wip_earned_cents"], 2916667, "M-02 wip_earned_cents")
    assert_module_dimensions(never_scheduled, production_status="PLANNED")
    assert_cents(never_scheduled["wip_earned_cents"], 0, "M-03 wip_earned_cents")


# ─── Retainage on an exact half cent ──────────────────────────────────────────
@pytest.fixture
def a_deposit_draw_against_one_half_built_module(api):
    """One module standing at station 2 of 6, with a DRAFT deposit draw open."""
    world = fx.world_with_module(api)
    fx.schedule_slot(world, "M-01", "2026-09-02T14:00:00Z")
    fx.advance_stations(world, "M-01", 2)
    draw = fx.create_draw(
        world.api, world.project_id, world.agency_id, "WIP_DEPOSIT", 1
    )
    return world, draw


def test_retainage_on_an_exact_half_cent_is_withheld_rounded_up(
    a_deposit_draw_against_one_half_built_module,
):
    """PRD §3.9: "`retainage_held_cents` is `certified_cents` multiplied by the project's `retainage_pct` — 5 percent by default — rounded half up to a whole cent."
    PRD §3.9: "`net_funded_cents` is `certified_cents` minus `retainage_held_cents`."
    PRD §2.8: "Wherever a monetary result is derived by multiplication or division, the result is rounded **half up** to a whole cent."

    Design: Corner/calculations/draw_retainage_precision_rounds_the_half_cent_up
    """
    world, draw = a_deposit_draw_against_one_half_built_module

    certified = validate_success(
        world.api.certify_draw(
            draw["id"], f.certify_payload(), LENDER_DRAW_ADMINISTRATOR
        )
    )

    assert_cents(certified["certified_basis_cents"], 2916667, "certified_basis_cents")
    assert_cents(certified["certified_cents"], 583333, "certified_cents")
    # 583,333 x 0.05 is exactly 29,166.65, which must round up, not truncate.
    assert_cents(certified["retainage_held_cents"], 29167, "retainage_held_cents")
    assert_cents(certified["net_funded_cents"], 554166, "net_funded_cents")


def test_the_certified_deposit_lands_on_the_projects_work_in_progress_ledger(
    a_deposit_draw_against_one_half_built_module,
):
    """PRD §3.9: "A successful certification moves `status` from `DRAFT` to `CERTIFIED`, stamps `certified_at` with the current clock instant, adds `certified_cents` to the project's `wip_certified_cents`, and increments both the draw's and the project's `version`."
    PRD §2.8: "Alongside it, `funded_to_date_cents` accumulates `net_funded_cents` over the project's draws in status `FUNDED`."

    Design: Corner/calculations/draw_retainage_precision_rounds_the_half_cent_up
    """
    world, draw = a_deposit_draw_against_one_half_built_module

    certified = validate_success(
        world.api.certify_draw(
            draw["id"], f.certify_payload(), LENDER_DRAW_ADMINISTRATOR
        )
    )

    assert certified["status"] == "CERTIFIED"
    project = world.refresh_project()
    assert_cents(project["wip_certified_cents"], 583333, "wip_certified_cents")
    # Certifying is not funding, so nothing has been released yet.
    assert_cents(project["funded_to_date_cents"], 0, "funded_to_date_cents")


# ─── Certification re-reads the plant floor ───────────────────────────────────
def test_a_terminating_station_advance_refreshes_the_draft_draws_provisional_ask(
    a_deposit_draw_against_one_half_built_module,
):
    """PRD §3.9: "Both `basis_earned_cents` and `requested_cents` are refreshed on every event that changes what the basis would contain while the draw is still in `DRAFT`: an intermediate or terminating station advance, a delivery, a quality hold arriving, and a hold being cleared all recompute them."
    PRD §3.9: "Under `WIP_DEPOSIT`, `requested_cents` is `basis_earned_cents` multiplied by the project's `deposit_pct` — 20 percent of work in progress by default — rounded half up to a whole cent."

    Design: Corner/calculations/draw_certification_recomputes_from_live_module_state
    """
    world, draw = a_deposit_draw_against_one_half_built_module

    # Station 2 of 6 at the moment the lender opened the draw.
    at_request = get_success_data(
        world.api.get_draw_request(draw["id"], LENDER_DRAW_ADMINISTRATOR)
    )
    assert_cents(at_request["basis_earned_cents"], 2916667, "basis_earned_cents")
    assert_cents(at_request["requested_cents"], 583333, "requested_cents")

    fx.advance_stations(world, "M-01", 4)

    after_the_line = get_success_data(
        world.api.get_draw_request(draw["id"], LENDER_DRAW_ADMINISTRATOR)
    )
    assert_cents(after_the_line["basis_earned_cents"], 8750000, "basis_earned_cents")
    assert_cents(after_the_line["requested_cents"], 1750000, "requested_cents")


def test_certifying_the_draw_reruns_the_basis_against_live_module_state(
    a_deposit_draw_against_one_half_built_module,
):
    """PRD §3.9: "The whole basis computation is then **re-run from live module state and never copied** from the provisional figures."
    PRD §3.9: "`certified_cents` is `certified_basis_cents` multiplied by the project's `deposit_pct` and rounded half up to a whole cent under `WIP_DEPOSIT`, and is equal to `certified_basis_cents` under `MILESTONE_SET`."
    PRD §3.9: "`net_funded_cents` is `certified_cents` minus `retainage_held_cents`."

    Design: Corner/calculations/draw_certification_recomputes_from_live_module_state
    """
    world, draw = a_deposit_draw_against_one_half_built_module
    # The module walks off the end of the line between request and certification.
    fx.advance_stations(world, "M-01", 4)

    certified = validate_success(
        world.api.certify_draw(
            draw["id"], f.certify_payload(), LENDER_DRAW_ADMINISTRATOR
        )
    )

    assert_cents(certified["certified_basis_cents"], 8750000, "certified_basis_cents")
    assert_cents(certified["certified_cents"], 1750000, "certified_cents")
    assert_cents(certified["retainage_held_cents"], 87500, "retainage_held_cents")
    assert_cents(certified["net_funded_cents"], 1662500, "net_funded_cents")

    module = world.refresh_module("M-01")
    assert_module_dimensions(module, production_status="LINE_COMPLETE")
    assert_cents(module["wip_earned_cents"], 8750000, "wip_earned_cents")


# ─── The load's fee tier, escort obligation and survey axis ───────────────────
@pytest.fixture
def a_two_state_load_and_two_released_modules(api):
    """A WA-then-OR load, empty, with a standard and a very wide module ready.

    M-01 is 180 inches wide and M-02 is 220 inches wide, so the second module
    alone carries the load over the superload width ceiling of 216 inches.
    """
    world = fx.world_qc_released_module(api)
    fx.add_module(world, "M-02", 2, width_in=220)
    fx.schedule_slot(world, "M-02", "2026-09-03T14:00:00Z")
    fx.advance_stations(world, "M-02", world.factory["station_count"])
    fx.release_quality(world, "M-02")
    world.shipment = fx.create_shipment(api, world.project_id, ["WA", "OR"])
    return world


def test_a_standard_load_is_fee_free_however_many_states_it_crosses(
    a_two_state_load_and_two_released_modules,
):
    """PRD §3.6: "The permit fee follows from a class multiplier: the multiplier is 0 for a `STANDARD` load, 2 for an `OVERWIDTH` load and 5 for a `SUPERLOAD`."
    PRD §3.6: "Because the standard multiplier is zero, a standard load is fee-free no matter how many states the route crosses."
    PRD §3.6: "The shipment's `max_envelope_class` is the widest `envelope_class` among the modules currently aboard, ordering the classes `STANDARD` below `OVERWIDTH` below `SUPERLOAD`, and it is `STANDARD` whenever the load is empty."

    Design: Corner/calculations/shipment_fee_tier_escalates_from_standard_to_superload_on_the_second_load
    """
    world = a_two_state_load_and_two_released_modules
    assert_cents(world.shipment["permit_fee_cents"], 0, "empty load permit_fee_cents")

    loaded = validate_success(
        world.api.load_module(
            world.shipment_id,
            f.load_module_payload(world.module_id("M-01"), world.shipment["version"]),
            TRANSPORT_COORDINATOR,
        )
    )

    # Two route states multiplied by a zero class multiplier is still zero.
    assert loaded["max_envelope_class"] == "STANDARD"
    assert_cents(loaded["permit_fee_cents"], 0, "permit_fee_cents")
    assert loaded["escort_required"] is False
    assert loaded["route_survey_state"] == "NOT_REQUIRED"
    assert loaded["status"] == "DRAFT"


def test_a_superload_module_reprices_the_whole_load_and_forces_a_route_survey(
    a_two_state_load_and_two_released_modules,
):
    """PRD §3.6: "`permit_fee_cents` is then a base state permit fee of $250.00 — that is 25,000 cents — multiplied by the number of entries in `route_state_codes`, multiplied again by that class multiplier."
    PRD §3.6: "`escort_required` becomes true when `max_envelope_class` is `SUPERLOAD`, and also when `max_envelope_class` is `OVERWIDTH` and the route crosses two or more states; otherwise it is false, and whenever it is false the shipment's `escort_confirmed` is forced back to false as well."
    PRD §3.6: "When a load in `route_survey_state` `NOT_REQUIRED` acquires a module that raises `max_envelope_class` to `OVERWIDTH` or `SUPERLOAD`, the survey axis moves from `NOT_REQUIRED` to `REQUIRED` and the fee and escort obligation are recomputed; if the transport axis was still at `DRAFT`, it moves in the same operation from `DRAFT` to `SURVEY_REQUIRED`."

    Design: Corner/calculations/shipment_fee_tier_escalates_from_standard_to_superload_on_the_second_load
    """
    world = a_two_state_load_and_two_released_modules
    world.shipment = fx.load_module(
        world.api, world.shipment_id, world.module_id("M-01"), world.shipment["version"]
    )

    loaded = validate_success(
        world.api.load_module(
            world.shipment_id,
            f.load_module_payload(world.module_id("M-02"), world.shipment["version"]),
            TRANSPORT_COORDINATOR,
        )
    )

    assert world.refresh_module("M-02")["envelope_class"] == "SUPERLOAD"
    assert loaded["max_envelope_class"] == "SUPERLOAD"
    # 25,000 cents x 2 route states x the superload multiplier of 5.
    assert_cents(loaded["permit_fee_cents"], 250000, "permit_fee_cents")
    assert loaded["escort_required"] is True
    assert loaded["escort_confirmed"] is False
    assert loaded["route_survey_state"] == "REQUIRED"
    assert loaded["status"] == "SURVEY_REQUIRED"
    assert loaded["loaded_module_count"] == 2


# ─── Every declared penalty lands on the compatibility score ──────────────────
@pytest.fixture
def a_revision_carrying_all_four_penalties(api):
    """A DRAFT revision that trips every penalty source at once.

    The project plans 4 modules; this revision splits the building into 3, has
    one unresolved connection clash, two uncoordinated field scope items and
    connection detailing only taken as far as the factory.
    """
    world = fx.world_plant_and_project(api)
    world.package = fx.create_design_package(
        api,
        world.project_id,
        world.project["version"],
        module_split_count=3,
        connection_detail_state="FACTORY_DETAILED",
        open_connection_conflicts=1,
        field_scope_items_open=2,
    )
    return world


def test_all_four_declared_penalties_are_charged_against_the_new_revision(
    a_revision_carrying_all_four_penalties,
):
    """PRD §3.2: "Each unresolved module-to-module connection clash counted in `open_connection_conflicts` contributes 8 penalty points."
    PRD §3.2: "Each uncoordinated site-built scope item counted in `field_scope_items_open` contributes 5 penalty points."
    PRD §3.2: "The maturity of connection detailing contributes a fixed penalty by state: 40 points while `connection_detail_state` is `NOT_STARTED`, 15 points at `FACTORY_DETAILED`, 5 points at `FIELD_COORDINATED`, and nothing at `COMPLETE`."
    PRD §3.2: "Finally, any disagreement between the revision's `module_split_count` and the project's `planned_module_count` contributes 10 penalty points for each module of difference, measured as the absolute size of the gap regardless of which number is larger."

    Design: Corner/calculations/compatibility_penalty_applies_every_declared_weight_then_re_scores_on_submit
    """
    world = a_revision_carrying_all_four_penalties

    # 8 for the clash, 10 for two field items, 15 for FACTORY_DETAILED and 10
    # for the one module of split difference: a 43 point penalty in total.
    assert world.package["factory_compatibility_score"] == 57
    assert world.package["factory_compatibility_score"] == expected_compatibility_score(
        1, 2, "FACTORY_DETAILED", 3, 4
    )
    assert world.package["freeze_state"] == "DRAFT"
    assert world.package["revision_round"] == 0


def test_restating_every_detailing_field_on_submit_rescores_the_revision(
    a_revision_carrying_all_four_penalties,
):
    """PRD §3.2: "The submitter may optionally restate `module_split_count`, `open_connection_conflicts`, `field_scope_items_open` and `connection_detail_state` in the payload, and may attach a `review_note`."
    PRD §3.2: "On success the package's `factory_compatibility_score` is recomputed, `revision_round` increases by 1 — which is what makes the two visits to `IN_REVIEW` in a revision cycle distinguishable, since the counter is 0 while a package has never been submitted — `submitted_by_user_id` is set to the submitting engineer's `X-User-ID`, and the package's `version` increments."
    PRD §3.2: "The `factory_compatibility_score` is then 100 minus the accumulated penalty, floored at 0 so it never goes negative, and it is stored as an integer in the range 0 through 100."

    Design: Corner/calculations/compatibility_penalty_applies_every_declared_weight_then_re_scores_on_submit
    """
    world = a_revision_carrying_all_four_penalties

    submitted = validate_success(
        world.api.submit_design_package(
            world.package_id,
            f.submit_payload(
                module_split_count=4,
                open_connection_conflicts=0,
                field_scope_items_open=0,
                connection_detail_state="COMPLETE",
            ),
            DESIGN_ENGINEER_SUBMITTER,
        )
    )

    # Every penalty source is now clean, so the score is the unpenalised 100.
    assert submitted["factory_compatibility_score"] == 100
    assert submitted["freeze_state"] == "IN_REVIEW"
    assert submitted["revision_round"] == 1
    assert submitted["module_split_count"] == 4
    assert submitted["connection_detail_state"] == "COMPLETE"
    # Restating the split on the revision does not restate the project's plan.
    assert world.refresh_project()["planned_module_count"] == 4


# ─── The field side absorbs the defect rounding remainder ─────────────────────
@pytest.fixture
def a_site_set_defect_costing_an_awkward_amount(api):
    """One module and an open claim for 1,234,567 cents found while setting.

    A quarter of that repair cost is 308,641.75 cents, so the factory share
    cannot be paid in whole cents without leaving a remainder behind.
    """
    world = fx.world_with_module(api)
    claim = validate_success(
        api.create_defect_claim(
            f.defect_claim_payload(
                world.module_id("M-01"),
                discovered_phase="SITE_SET",
                repair_cost_cents=1234567,
            ),
            world.superintendent,
        ),
        201,
    )
    return world, claim


def test_an_unadjudicated_claim_names_no_responsible_party_and_charges_nothing(
    a_site_set_defect_costing_an_awkward_amount,
):
    """PRD §3.8: "A new claim is persisted with `status` `OPEN`, `responsibility` `UNDETERMINED`, `adjudication_round` 0, all four of `factory_share_pct`, `field_share_pct`, `factory_charge_cents` and `field_charge_cents` at 0, `warranty_bucket` at its default of `SPLIT`, `adjudicated_by_user_id` and `dispute_note` null, and `version` 1."

    Design: Corner/calculations/defect_charge_remainder_lands_on_the_field_side
    """
    _world, claim = a_site_set_defect_costing_an_awkward_amount

    assert claim["status"] == "OPEN"
    assert claim["responsibility"] == "UNDETERMINED"
    assert claim["warranty_bucket"] == "SPLIT"
    assert claim["adjudication_round"] == 0
    assert_two_decimal_value(claim["factory_share_pct"], 0.00, "factory_share_pct")
    assert_two_decimal_value(claim["field_share_pct"], 0.00, "field_share_pct")
    assert_cents(claim["factory_charge_cents"], 0, "factory_charge_cents")
    assert_cents(claim["field_charge_cents"], 0, "field_charge_cents")
    assert claim["adjudicated_by_user_id"] is None


def test_the_field_charge_absorbs_the_remainder_the_factory_rounding_left(
    a_site_set_defect_costing_an_awkward_amount,
):
    """PRD §3.8: "The presumption table is fixed: a defect discovered in the `FACTORY` phase puts `factory_share_pct` at 100.00, one discovered in `TRANSIT` puts it at 50.00, one discovered in `SITE_SET` puts it at 25.00, and one discovered in `POST_SET` puts it at 0.00."
    PRD §3.8: "`factory_charge_cents` is the claim's `repair_cost_cents` multiplied by `factory_share_pct`, divided by 100, rounded half up to a whole cent."
    PRD §3.8: "`field_charge_cents` is `repair_cost_cents` minus `factory_charge_cents`, which makes the field charge absorb the rounding remainder so that the two charges always sum exactly to the repair cost."

    Design: Corner/calculations/defect_charge_remainder_lands_on_the_field_side
    """
    world, claim = a_site_set_defect_costing_an_awkward_amount

    adjudicated = validate_success(
        world.api.adjudicate_defect_claim(
            claim["id"], f.adjudicate_payload(), WARRANTY_ADJUDICATOR
        )
    )

    assert adjudicated["status"] == "ADJUDICATED"
    assert adjudicated["adjudication_round"] == 1
    assert_two_decimal_value(adjudicated["factory_share_pct"], 25.00, "factory_share_pct")
    assert_two_decimal_value(adjudicated["field_share_pct"], 75.00, "field_share_pct")
    # 308,641.75 rounds half up to 308,642, and the field takes what is left.
    assert_cents(adjudicated["factory_charge_cents"], 308642, "factory_charge_cents")
    assert_cents(adjudicated["field_charge_cents"], 925925, "field_charge_cents")
    assert (
        adjudicated["factory_charge_cents"] + adjudicated["field_charge_cents"]
        == 1234567
    )


def test_a_shared_allocation_moves_neither_of_the_modules_defect_counters(
    a_site_set_defect_costing_an_awkward_amount,
):
    """PRD §3.8: "`responsibility` is `FACTORY` when `factory_share_pct` is exactly 100.00, `FIELD` when it is exactly 0.00, and `SHARED` at every value in between."
    PRD §3.8: "`warranty_bucket` follows directly: `FACTORY_WARRANTY` when responsibility is `FACTORY`, `FIELD_WARRANTY` when it is `FIELD`, and `SPLIT` when it is `SHARED`."
    PRD §3.8: "Finally, and strictly *after* the allocation has been computed, the module's counters are updated — `defect_count_factory` increases by 1 when responsibility landed on `FACTORY`, and `defect_count_field` increases by 1 when it landed on `FIELD` — so that an adjudication never feeds its own evidence back into itself."

    Design: Corner/calculations/defect_charge_remainder_lands_on_the_field_side
    """
    world, claim = a_site_set_defect_costing_an_awkward_amount

    adjudicated = validate_success(
        world.api.adjudicate_defect_claim(
            claim["id"], f.adjudicate_payload(), WARRANTY_ADJUDICATOR
        )
    )

    assert adjudicated["responsibility"] == "SHARED"
    assert adjudicated["warranty_bucket"] == "SPLIT"

    # A 25/75 split lands on neither side, so neither counter may move.
    module = world.refresh_module("M-01")
    assert module["defect_count_factory"] == 0
    assert module["defect_count_field"] == 0


# ─── The posture walks both tracks to a fixed point ───────────────────────────
def _file_application(world, track, scope):
    """File one permit application, leaving it undecided."""
    return validate_success(
        world.api.create_permit(
            f.permit_payload(world.project_id, track, scope), PROGRAM_ADMIN
        ),
        201,
    )


def _approve(world, permit, officer):
    """Have the officer of the matching track approve one application."""
    return validate_success(
        world.api.decide_permit(
            permit["id"], f.permit_decision_payload("APPROVE"), officer
        )
    )


@pytest.fixture
def four_applications_on_file_across_both_tracks(api):
    """A frozen revision plus both state and both local applications, undecided.

    Nothing has been decided, so none of the five facts the posture reads is
    live yet.
    """
    world = fx.world_frozen_design(api)
    applications = {
        "PLAN_REVIEW": _file_application(world, "STATE_MODULAR_PROGRAM", "PLAN_REVIEW"),
        "INSIGNIA": _file_application(world, "STATE_MODULAR_PROGRAM", "INSIGNIA"),
        "SET": _file_application(world, "LOCAL_AHJ", "SET"),
        "OCCUPANCY": _file_application(world, "LOCAL_AHJ", "OCCUPANCY"),
    }
    return world, applications


def test_applications_that_are_merely_on_file_leave_the_project_dual_blocked(
    four_applications_on_file_across_both_tracks,
):
    """PRD §3.3: "A track-and-scope pair counts as *live* when the project has a permit record with that `track` and that `scope` whose `status` is `APPROVED` and whose `expires_at` is either null or strictly later than the current clock instant."
    PRD §3.3: "Records in `DENIED`, `SUBMITTED`, `UNDER_REVIEW`, `CONDITIONS_ISSUED` or `EXPIRED` contribute nothing at all."
    PRD §3.3: "If none of those match, `permit_posture` is `DUAL_BLOCKED`."

    Design: Corner/calculations/permit_posture_propagates_to_a_fixed_point_across_both_tracks
    """
    world, applications = four_applications_on_file_across_both_tracks

    for scope, application in applications.items():
        assert application["status"] == "SUBMITTED", f"{scope} should be undecided"
    assert world.refresh_project()["permit_posture"] == "DUAL_BLOCKED"


def test_state_plan_review_on_its_own_clears_the_state_track_and_pins_the_revision(
    four_applications_on_file_across_both_tracks,
):
    """PRD §3.3: "Otherwise, if state plan review is live and the site side is not cleared, it is `STATE_CLEARED_ONLY`."
    PRD §3.3: "On success, an approval whose `scope` is `PLAN_REVIEW` sets `pinned_package_id` to the `id` of the project's single frozen design package."

    Design: Corner/calculations/permit_posture_propagates_to_a_fixed_point_across_both_tracks
    """
    world, applications = four_applications_on_file_across_both_tracks

    approved = _approve(world, applications["PLAN_REVIEW"], STATE_PROGRAM_OFFICER)

    assert approved["status"] == "APPROVED"
    assert approved["pinned_package_id"] == world.package_id
    assert world.refresh_project()["permit_posture"] == "STATE_CLEARED_ONLY"


def test_insignia_stacked_on_plan_review_still_reports_only_the_state_track(
    four_applications_on_file_across_both_tracks,
):
    """PRD §3.3: "An approval whose `scope` is `INSIGNIA` instead sets `insignia_count_issued` to the project's `planned_module_count`, releasing one insignia label per planned module."
    PRD §3.3: "Otherwise, if state plan review is live and the site side is not cleared, it is `STATE_CLEARED_ONLY`."
    PRD §3.3: "Every approval re-derives the project's `permit_posture` and increments the project's `version` alongside the record's."

    Design: Corner/calculations/permit_posture_propagates_to_a_fixed_point_across_both_tracks
    """
    world, applications = four_applications_on_file_across_both_tracks
    _approve(world, applications["PLAN_REVIEW"], STATE_PROGRAM_OFFICER)

    insignia = _approve(world, applications["INSIGNIA"], STATE_PROGRAM_OFFICER)

    # Both state facts are live now, but neither local permit is.
    assert insignia["insignia_count_issued"] == 4
    assert world.refresh_project()["permit_posture"] == "STATE_CLEARED_ONLY"


def test_the_local_permits_walk_the_posture_up_to_occupancy_cleared(
    four_applications_on_file_across_both_tracks,
):
    """PRD §3.3: "Otherwise, if the local set permit, state plan review and state insignia are all live, it is `SET_CLEARED`."
    PRD §3.3: "If local occupancy, the local set permit, state plan review and state insignia are **all** live, `permit_posture` is `OCCUPANCY_CLEARED`."
    PRD §3.3: "The branches below are evaluated in exactly this order and the first one that matches wins; the ordering is normative, not a presentation choice."

    Design: Corner/calculations/permit_posture_propagates_to_a_fixed_point_across_both_tracks
    """
    world, applications = four_applications_on_file_across_both_tracks
    _approve(world, applications["PLAN_REVIEW"], STATE_PROGRAM_OFFICER)
    _approve(world, applications["INSIGNIA"], STATE_PROGRAM_OFFICER)

    _approve(world, applications["SET"], AUTHORITY_HAVING_JURISDICTION)
    assert world.refresh_project()["permit_posture"] == "SET_CLEARED"

    _approve(world, applications["OCCUPANCY"], AUTHORITY_HAVING_JURISDICTION)
    assert world.refresh_project()["permit_posture"] == "OCCUPANCY_CLEARED"


# ─── The phase ladder reports its first matching branch ───────────────────────
@pytest.fixture
def a_permitted_load_still_standing_at_the_plant(api):
    """One finished module aboard a permitted single-state load, not yet away.

    Three of the phase branches can match this project at once — a module off
    the line, a frozen revision, and shortly a load on the road — so the order
    the branches are read in is observable.
    """
    world = fx.world_loaded_module(api)
    world.shipment = get_success_data(
        api.record_route_survey(
            world.shipment_id, f.route_survey_payload(), TRANSPORT_COORDINATOR
        )
    )
    return world


def test_a_finished_module_reports_production_even_though_the_design_is_frozen(
    a_permitted_load_still_standing_at_the_plant,
):
    """PRD §3.7: "**Project phase** is derived by a full re-scan of the project's design packages, modules and shipments, never by an increment, and the branches below are evaluated in order with the first match winning."
    PRD §3.7: "Otherwise, if any module of the project has `production_status` `IN_LINE` or `LINE_COMPLETE`, `phase` is `IN_PRODUCTION`."
    PRD §3.7: "Otherwise, if any design package of the project has `freeze_state` `FROZEN` or `SUPERSEDED`, `phase` is `DESIGN_FROZEN`."

    Design: Corner/calculations/project_phase_projection_reports_the_first_matching_branch
    """
    world = a_permitted_load_still_standing_at_the_plant

    # The design-frozen branch matches too, but it is read after production.
    assert world.refresh_package()["freeze_state"] == "FROZEN"
    assert_module_dimensions(world.refresh_module("M-01"), production_status="LINE_COMPLETE")
    assert world.shipment["status"] == "PERMITTED"
    assert world.refresh_project()["phase"] == "IN_PRODUCTION"


def test_putting_the_load_on_the_road_lifts_the_phase_over_the_lower_branches(
    a_permitted_load_still_standing_at_the_plant,
):
    """PRD §3.7: "Otherwise, if any shipment of the project has `status` `DISPATCHED` or `DELIVERED`, `phase` is `SHIPPING`."
    PRD §3.7: "Otherwise, if any module of the project has `site_status` `SET` or `CONNECTED`, `phase` is `SETTING`."
    PRD §3.6: "On success `status` moves from `PERMITTED` to `DISPATCHED`, `dispatched_at` is stamped with the current clock instant, every module aboard moves its `site_status` from `LOADED` to `IN_TRANSIT`, the project's `phase` is re-derived up to `SHIPPING`, and the shipment, every module aboard and the project all take `version` increments."

    Design: Corner/calculations/project_phase_projection_reports_the_first_matching_branch
    """
    world = a_permitted_load_still_standing_at_the_plant

    dispatched = validate_success(
        world.api.dispatch_shipment(world.shipment_id, {}, TRANSPORT_COORDINATOR)
    )

    assert dispatched["status"] == "DISPATCHED"
    # Nothing is on the foundation, so the setting branch above cannot match.
    assert_module_dimensions(world.refresh_module("M-01"), site_status="IN_TRANSIT")
    assert world.refresh_project()["phase"] == "SHIPPING"


# ─── The weather exposure limit, to the minute ────────────────────────────────
@pytest.fixture
def three_delivered_modules_ready_to_land(api):
    """Three released modules delivered to a site cleared for setting.

    Each lift is planned into its own window well clear of the others, and the
    clock stands at 08:00 on the first of September, so the exposure of the
    first module set is measured from exactly that instant.
    """
    world = fx.world_qc_released_module(api)
    for code, index, slot_start in (
        ("M-02", 2, "2026-09-03T14:00:00Z"),
        ("M-03", 3, "2026-09-04T14:00:00Z"),
    ):
        fx.add_module(world, code, index)
        fx.schedule_slot(world, code, slot_start)
        fx.advance_stations(world, code, world.factory["station_count"])
        fx.release_quality(world, code)

    world.shipment = fx.create_shipment(api, world.project_id)
    for code in ("M-01", "M-02", "M-03"):
        world.shipment = fx.load_module(
            api, world.shipment_id, world.module_id(code), world.shipment["version"]
        )
    get_success_data(
        api.record_route_survey(
            world.shipment_id, f.route_survey_payload(), TRANSPORT_COORDINATOR
        )
    )
    get_success_data(api.dispatch_shipment(world.shipment_id, {}, TRANSPORT_COORDINATOR))
    world.shipment = get_success_data(
        api.deliver_shipment(world.shipment_id, {}, TRANSPORT_COORDINATOR)
    )

    fx.clear_the_site_for_setting(world)
    for code, start, end in (
        ("M-01", "2026-09-10T09:00:00Z", "2026-09-10T09:45:00Z"),
        ("M-02", "2026-09-10T12:00:00Z", "2026-09-10T12:45:00Z"),
        ("M-03", "2026-09-10T15:00:00Z", "2026-09-10T15:45:00Z"),
    ):
        fx.plan_pick(world, code, start, end)
    return world


def _land_on_the_foundation(world, module_code):
    """Execute the planned lift for one module."""
    module = validate_success(
        world.api.execute_set(world.module_id(module_code), {}, world.superintendent)
    )
    world.modules[module_code] = module
    return module


def test_a_module_open_for_exactly_the_shift_limit_is_still_compliant(
    three_delivered_modules_ready_to_land,
):
    """PRD §3.7: "A successful set stamps `set_at` with the current clock instant, resets the module's `exposure_open_hours` to 0 because the exposure clock starts now, increases the project's `modules_set_count` by 1, re-derives the project's `phase` up to `SETTING`, and increments both the module's and the project's `version`."
    PRD §3.7: "While the module's `site_status` is `SET` and its `connected_at` is still null, `exposure_open_hours` is the difference between the current logical clock instant and `set_at`, taken in whole minutes, divided by 60, and rounded half up to two decimal places."
    PRD §3.7: "The project's `weather_exposure_limit_hours` — 8.0 hours by default, which is one working shift of exposure — is compared with a strict greater-than, so a module sitting at exactly 8.00 hours is still compliant."

    Design: Corner/calculations/module_exposure_hours_decay_boundary_at_the_weather_limit
    """
    world = three_delivered_modules_ready_to_land

    landed = _land_on_the_foundation(world, "M-01")
    assert_module_dimensions(landed, site_status="SET")
    assert_two_decimal_value(landed["exposure_open_hours"], 0.00, "exposure_open_hours")

    fx.set_clock(world.api, "2026-09-01T16:00:00Z")

    # Eight hours to the minute: 480 minutes divided by 60 is exactly 8.00.
    open_module = world.refresh_module("M-01")
    assert_two_decimal_value(
        open_module["exposure_open_hours"], 8.00, "exposure_open_hours"
    )


def test_the_next_module_lands_while_the_open_one_sits_exactly_at_the_limit(
    three_delivered_modules_ready_to_land,
):
    """PRD §3.7: "Weather exposure across the whole site is checked: no already-set, not-yet-connected module of the project may have an `exposure_open_hours` greater than the project's `weather_exposure_limit_hours`, because open modules must be closed in before another one is landed; a breach is `ERR_WEATHER_EXPOSURE_LIMIT`."
    PRD §2.10: "Every module whose `site_status` is `SET` and whose `connected_at` is still null has its `exposure_open_hours` recomputed against the new instant."

    Design: Corner/calculations/module_exposure_hours_decay_boundary_at_the_weather_limit
    """
    world = three_delivered_modules_ready_to_land
    _land_on_the_foundation(world, "M-01")
    fx.set_clock(world.api, "2026-09-01T16:00:00Z")

    second = _land_on_the_foundation(world, "M-02")

    assert_module_dimensions(second, site_status="SET")
    assert_two_decimal_value(second["exposure_open_hours"], 0.00, "exposure_open_hours")
    assert world.refresh_project()["modules_set_count"] == 2


def test_one_minute_past_the_limit_shuts_the_site_to_the_next_lift(
    three_delivered_modules_ready_to_land,
):
    """PRD §3.7: "Weather exposure across the whole site is checked: no already-set, not-yet-connected module of the project may have an `exposure_open_hours` greater than the project's `weather_exposure_limit_hours`, because open modules must be closed in before another one is landed; a breach is `ERR_WEATHER_EXPOSURE_LIMIT`."
    PRD §3.7: "**Weather exposure** is the number of hours a set module has stood open, and it is recomputed on set execution, on connection closeout, on every clock advance, and on any read of the module or of the project's set-readiness view."

    Design: Corner/calculations/module_exposure_hours_decay_boundary_at_the_weather_limit
    """
    world = three_delivered_modules_ready_to_land
    _land_on_the_foundation(world, "M-01")
    fx.set_clock(world.api, "2026-09-01T16:00:00Z")
    _land_on_the_foundation(world, "M-02")

    fx.set_clock(world.api, "2026-09-01T16:01:00Z")

    # 481 minutes divided by 60 is 8.0166..., which rounds half up to 8.02.
    assert_two_decimal_value(
        world.refresh_module("M-01")["exposure_open_hours"], 8.02, "exposure_open_hours"
    )

    validate_error(
        world.api.execute_set(world.module_id("M-03"), {}, world.superintendent),
        ERR_WEATHER_EXPOSURE_LIMIT,
    )

    assert_module_dimensions(world.refresh_module("M-03"), site_status="DELIVERED")
    assert world.refresh_project()["modules_set_count"] == 2


def test_closing_the_connections_freezes_the_exposure_where_it_stood(
    three_delivered_modules_ready_to_land,
):
    """PRD §3.7: "Closing connections stamps `connected_at` with the current clock instant and freezes `exposure_open_hours` at the elapsed span between `set_at` and `connected_at`."
    PRD §3.7: "Once the module's `site_status` is `CONNECTED`, the value freezes as the difference between `connected_at` and `set_at`, again in whole minutes divided by 60 and rounded half up to two decimals."
    PRD §3.7: "The weather gate is a disjunction rather than a hard stop: the module's `exposure_open_hours`, recomputed at the current instant, must be less than the project's `weather_exposure_limit_hours`, **or** the project's `forecast_precip_probability_pct` must be below 40, so a module that has stood open too long may still be closed in while the forecast is dry."

    Design: Corner/calculations/module_exposure_hours_decay_boundary_at_the_weather_limit
    """
    world = three_delivered_modules_ready_to_land
    _land_on_the_foundation(world, "M-01")
    fx.set_clock(world.api, "2026-09-01T16:01:00Z")

    # Past the limit, but the forecast is dry, so the closeout is admitted.
    closed = validate_success(
        world.api.close_connections(
            world.module_id("M-01"),
            f.close_connections_payload(True),
            world.superintendent,
        )
    )

    assert_module_dimensions(closed, site_status="CONNECTED")
    assert_two_decimal_value(closed["exposure_open_hours"], 8.02, "exposure_open_hours")

    # A whole further day on the clock cannot move a frozen exposure figure.
    fx.set_clock(world.api, "2026-09-02T08:00:00Z")
    assert_two_decimal_value(
        world.refresh_module("M-01")["exposure_open_hours"], 8.02, "exposure_open_hours"
    )
