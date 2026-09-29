"""Independent lifecycles moving past one another on the same building.

A volumetric module carries the factory line, the inspection agency's verdict and
the logistics of the site as three separate stories on one row, and quality can
walk from pending to a conditional release without the line advancing a single
station. A warranty argument cycles once through dispute and then goes final. A
building department can take an application into review and still deny it, and a
denial contributes nothing to what the project is cleared to do. Above all of
them sits the project's phase, which nobody ever writes: it is re-read off the
design revisions, the modules and the loads every time one of them moves, and it
climbs from preconstruction to closeout only as its children do.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_DISPUTE_ROUND_LIMIT,
    ERR_MODULE_NOT_READY_TO_SET,
    ERR_MODULE_NOT_SET,
    ERR_PERMIT_ALREADY_DECIDED,
    ERR_SET_NOT_PERMITTED,
)
from test_helpers.assertions import (
    assert_cents,
    assert_instant,
    assert_module_dimensions,
    assert_two_decimal_value,
)
from test_helpers.test_users import (
    AUTHORITY_HAVING_JURISDICTION,
    PROGRAM_ADMIN,
    WARRANTY_ADJUDICATOR,
)

SINGLE_MODULE_PROJECT = {"planned_module_count": 1}
SINGLE_MODULE_REVISION = {"module_split_count": 1}


@pytest.fixture
def module_two_stations_into_the_line(api):
    """A module standing at station 2 of 6, quality not yet opened.

    The line is what has moved: production is IN_LINE, quality is still PENDING
    and the module has never left the plant.
    """
    world = fx.world_with_module(api)
    fx.schedule_slot(world)
    fx.advance_stations(world, "M-01", 2)
    return world


def test_opening_the_first_inspection_moves_quality_without_moving_the_line(
    module_two_stations_into_the_line,
):
    """PRD §3.5: "And the module must have reached the line: the first record opened against a module moves its `qc_status` from `PENDING` to `IN_PROGRESS`, and that transition requires the module's `production_status` to be `IN_LINE` or `LINE_COMPLETE`."
    PRD §3.5: "A new record is persisted with `result` `PENDING`, `hold_state` `NONE`, `defect_count` 0, `severity_max` 0, `corrective_note`, `recorded_at` and `recorded_by_user_id` all null, and `version` 1; the module's `version` increments when the first record flips its quality dimension."
    PRD §2.9: "A `ModuleUnit` carries three, on one row, advancing independently: `production_status` tracks the factory line, `qc_status` tracks third-party quality, and `site_status` tracks logistics and the site."

    Design: Corner/state_machines/qc_dimension_advances_while_production_status_stays_in_line
    """
    world = module_two_stations_into_the_line

    record = validate_success(
        world.api.create_inspection(
            f.inspection_payload(world.module_id(), world.agency_id, "IN_PLANT"),
            world.inspector,
        ),
        201,
    )

    assert record["result"] == "PENDING"
    assert record["hold_state"] == "NONE"
    assert record["recorded_at"] is None

    module = world.refresh_module()
    assert_module_dimensions(
        module,
        production_status="IN_LINE",
        qc_status="IN_PROGRESS",
        site_status="AT_FACTORY",
    )
    assert module["station_index"] == 2


def test_a_conditional_final_factory_result_leaves_the_module_at_station_two(
    module_two_stations_into_the_line,
):
    """PRD §3.5: "A `CONDITIONAL` recorded on a `FINAL_FACTORY` record moves `qc_status` from `IN_PROGRESS` to `CONDITIONAL_RELEASE` under exactly the same `IN_PLANT` precondition, and likewise increments the module's `version`."
    PRD §3.4: "The first advance from `SLOTTED` moves `production_status` to `IN_LINE`, increases `station_index` by `stations_advanced` capped at the plant's `station_count`, recomputes `wip_earned_cents`, re-derives the project's `phase` from `DESIGN_FROZEN` up to `IN_PRODUCTION`, and increments both the module's and the project's `version`."
    PRD §3.4: "When the module's `production_status` is `SLOTTED`, `IN_LINE` or `LINE_COMPLETE` *and* its `qc_status` is not `HOLD`, the earned value is the plant's `wip_unit_value_cents` multiplied by the module's `station_index`, divided by the plant's `station_count`, and rounded half up to a whole cent."

    Design: Corner/state_machines/qc_dimension_advances_while_production_status_stays_in_line
    """
    world = module_two_stations_into_the_line
    in_plant = fx.open_inspection(
        world.api, world.module_id(), world.agency_id, "IN_PLANT"
    )
    passed = fx.record_result(world.api, in_plant["id"], world.agency_id, "PASS")
    assert passed["result"] == "PASS"

    final = fx.open_inspection(
        world.api, world.module_id(), world.agency_id, "FINAL_FACTORY"
    )
    conditional = validate_success(
        world.api.record_inspection_result(
            final["id"],
            f.inspection_result_payload("CONDITIONAL", 2, 2, corrective_note="punch list open"),
            world.inspector,
        )
    )

    assert conditional["result"] == "CONDITIONAL"

    module = world.refresh_module()
    assert_module_dimensions(
        module,
        production_status="IN_LINE",
        qc_status="CONDITIONAL_RELEASE",
        site_status="AT_FACTORY",
    )
    # Two of six stations of an 8,750,000 cent unit value: 2,916,666.67 rounds up.
    assert module["station_index"] == 2
    assert_cents(module["wip_earned_cents"], 2916667, "wip_earned_cents")


FIRST_DISPUTE_NOTE = "the factory contests the discovery-phase presumption"


@pytest.fixture
def open_factory_defect_claim(api):
    """One module of a plant, carrying an OPEN claim raised in the factory.

    Nothing in the warranty cycle reads the freeze chain, so the revision is
    left in DRAFT and the claim is raised straight against the module.
    """
    world = fx.world_plant_and_project(api)
    world.package = fx.create_design_package(
        api, world.project_id, world.project["version"]
    )
    world.modules["M-01"] = fx.create_module(
        api, world.project_id, world.package_id, world.factory_id, "M-01", 1
    )
    claim = validate_success(
        api.create_defect_claim(
            f.defect_claim_payload(world.module_id(), "FACTORY", 1234567),
            world.factory_manager,
        ),
        201,
    )
    return world, claim


def test_a_disputed_allocation_is_re_adjudicated_on_evidence_in_round_two(
    open_factory_defect_claim,
):
    """PRD §3.8: "The **first** adjudication runs from `OPEN`, moves `status` to `ADJUDICATED`, sets `adjudication_round` to 1, and allocates by **discovery-phase presumption**."
    PRD §3.8: "A successful dispute moves `status` from `ADJUDICATED` to `DISPUTED`, stores the `dispute_note`, and increments the claim's `version`."
    PRD §3.8: "The **second** adjudication runs from `DISPUTED`, moves `status` back to `ADJUDICATED`, sets `adjudication_round` to 2, and discards the presumption table entirely in favour of an **additive evidence score**."

    Design: Corner/state_machines/defect_claim_dispute_cycle_stops_at_round_two
    """
    world, claim = open_factory_defect_claim
    assert claim["status"] == "OPEN"
    assert claim["adjudication_round"] == 0

    first = validate_success(
        world.api.adjudicate_defect_claim(
            claim["id"], f.adjudicate_payload(), WARRANTY_ADJUDICATOR
        )
    )
    assert first["status"] == "ADJUDICATED"
    assert first["adjudication_round"] == 1

    disputed = validate_success(
        world.api.dispute_defect_claim(
            claim["id"], f.dispute_payload(FIRST_DISPUTE_NOTE), world.factory_manager
        )
    )
    assert disputed["status"] == "DISPUTED"
    assert disputed["dispute_note"] == FIRST_DISPUTE_NOTE

    second = validate_success(
        world.api.adjudicate_defect_claim(
            claim["id"], f.adjudicate_payload(), WARRANTY_ADJUDICATOR
        )
    )
    assert second["status"] == "ADJUDICATED"
    assert second["adjudication_round"] == 2


def test_the_first_pass_charges_a_factory_discovery_wholly_to_the_plant(
    open_factory_defect_claim,
):
    """PRD §3.8: "The presumption table is fixed: a defect discovered in the `FACTORY` phase puts `factory_share_pct` at 100.00, one discovered in `TRANSIT` puts it at 50.00, one discovered in `SITE_SET` puts it at 25.00, and one discovered in `POST_SET` puts it at 0.00."
    PRD §3.8: "This variant reads `discovered_phase` and nothing else — inspection evidence, exposure history and connection scope ownership are all ignored on the first pass."
    PRD §3.8: "`responsibility` is `FACTORY` when `factory_share_pct` is exactly 100.00, `FIELD` when it is exactly 0.00, and `SHARED` at every value in between."

    Design: Corner/state_machines/defect_claim_dispute_cycle_stops_at_round_two
    """
    world, claim = open_factory_defect_claim

    first = validate_success(
        world.api.adjudicate_defect_claim(
            claim["id"], f.adjudicate_payload(), WARRANTY_ADJUDICATOR
        )
    )

    assert_two_decimal_value(first["factory_share_pct"], 100.00, "factory_share_pct")
    assert_two_decimal_value(first["field_share_pct"], 0.00, "field_share_pct")
    assert first["responsibility"] == "FACTORY"
    assert first["warranty_bucket"] == "FACTORY_WARRANTY"
    assert_cents(first["factory_charge_cents"], 1234567, "factory_charge_cents")
    assert_cents(first["field_charge_cents"], 0, "field_charge_cents")


def test_the_second_pass_weighs_evidence_into_an_even_split(
    open_factory_defect_claim,
):
    """PRD §3.8: "The factory score gains 6 points when the referenced inspection record's `result` is `FAIL` or `CONDITIONAL`; a further 3 points when that record's `severity_max` is at least 3; and a further 2 points when the module's `defect_count_factory` is strictly greater than its `defect_count_field`."
    PRD §3.8: "The field score gains 4 points when the claim's `discovered_phase` is `SITE_SET` or `POST_SET`; a further 3 points when the module's `site_status` is `SET` or `CONNECTED` and its `exposure_open_hours` is strictly greater than the project's `weather_exposure_limit_hours`; and a further 2 points when the module's `connection_scope_owner` is `FIELD`."
    PRD §3.8: "Otherwise `factory_share_pct` is the factory score multiplied by 100, divided by the sum of the two scores, rounded half up to two decimal places."

    Design: Corner/state_machines/defect_claim_dispute_cycle_stops_at_round_two
    """
    world, claim = open_factory_defect_claim
    validate_success(
        world.api.adjudicate_defect_claim(
            claim["id"], f.adjudicate_payload(), WARRANTY_ADJUDICATOR
        )
    )
    validate_success(
        world.api.dispute_defect_claim(
            claim["id"], f.dispute_payload(FIRST_DISPUTE_NOTE), world.factory_manager
        )
    )

    second = validate_success(
        world.api.adjudicate_defect_claim(
            claim["id"], f.adjudicate_payload(), WARRANTY_ADJUDICATOR
        )
    )

    # No inspection is referenced, so the factory scores only the 2 points for
    # the factory defect the first pass charged to it; the field scores only the
    # 2 points for owning the connection scope. Two against two is 50.00.
    assert_two_decimal_value(second["factory_share_pct"], 50.00, "factory_share_pct")
    assert_two_decimal_value(second["field_share_pct"], 50.00, "field_share_pct")
    assert second["responsibility"] == "SHARED"
    assert second["warranty_bucket"] == "SPLIT"


def test_a_claim_already_re_adjudicated_on_evidence_may_not_be_disputed_again(
    open_factory_defect_claim,
):
    """PRD §3.8: "The claim's `status` must be `ADJUDICATED`, or the attempt is `ERR_CLAIM_NOT_ADJUDICATED`, and its `adjudication_round` must be strictly less than 2, or the attempt is `ERR_DISPUTE_ROUND_LIMIT`: a claim already re-adjudicated on evidence is final and may be disputed no further."
    PRD §3.8: "That closes the adjudication cycle — `ADJUDICATED` to `DISPUTED` and back to `ADJUDICATED` — with the second pass switching the allocation variant."

    Design: Corner/state_machines/defect_claim_dispute_cycle_stops_at_round_two
    """
    world, claim = open_factory_defect_claim
    validate_success(
        world.api.adjudicate_defect_claim(
            claim["id"], f.adjudicate_payload(), WARRANTY_ADJUDICATOR
        )
    )
    validate_success(
        world.api.dispute_defect_claim(
            claim["id"], f.dispute_payload(FIRST_DISPUTE_NOTE), world.factory_manager
        )
    )
    validate_success(
        world.api.adjudicate_defect_claim(
            claim["id"], f.adjudicate_payload(), WARRANTY_ADJUDICATOR
        )
    )

    validate_error(
        world.api.dispute_defect_claim(
            claim["id"],
            f.dispute_payload("the factory appeals a second time"),
            world.factory_manager,
        ),
        ERR_DISPUTE_ROUND_LIMIT,
    )

    final = validate_success(
        world.api.get_defect_claim(claim["id"], WARRANTY_ADJUDICATOR)
    )
    assert final["status"] == "ADJUDICATED"
    assert final["adjudication_round"] == 2
    assert final["dispute_note"] == FIRST_DISPUTE_NOTE


@pytest.fixture
def submitted_local_set_application(api):
    """A freshly filed local authority application for the set operation."""
    world = fx.world_plant_and_project(api)
    permit = validate_success(
        api.create_permit(
            f.permit_payload(world.project_id, "LOCAL_AHJ", "SET"), PROGRAM_ADMIN
        ),
        201,
    )
    return world, permit


def test_the_building_department_can_take_the_application_into_review(
    submitted_local_set_application,
):
    """PRD §3.3: "A filed application starts in `status` `SUBMITTED` with `conditions_count` at 0, `insignia_count_issued` at 0, `pinned_package_id` null, `decided_at` and `decided_by_user_id` null, and `version` at 1."
    PRD §3.3: "`START_REVIEW` moves `status` from `SUBMITTED` to `UNDER_REVIEW` and does nothing further beyond the decision stamps and the version increment."
    PRD §3.3: "Every accepted decision stamps `decided_at` with the current clock instant and `decided_by_user_id` with the deciding officer's `X-User-ID`, and increments the record's `version`."

    Design: Corner/state_machines/permit_under_review_branch_ends_in_denied
    """
    world, permit = submitted_local_set_application
    assert permit["status"] == "SUBMITTED"
    assert permit["conditions_count"] == 0
    assert permit["pinned_package_id"] is None
    assert permit["decided_at"] is None

    reviewing = validate_success(
        world.api.decide_permit(
            permit["id"],
            f.permit_decision_payload("START_REVIEW"),
            AUTHORITY_HAVING_JURISDICTION,
        )
    )

    assert reviewing["status"] == "UNDER_REVIEW"
    assert_instant(reviewing["decided_at"], f.DEFAULT_CLOCK, "decided_at")
    assert reviewing["conditions_count"] == 0
    assert reviewing["pinned_package_id"] is None


def test_an_application_under_review_can_still_be_denied_outright(
    submitted_local_set_application,
):
    """PRD §3.3: "`DENY` moves `status` to `DENIED`, which is terminal."
    PRD §3.3: "Beyond the decision stamps it clears `pinned_package_id` back to null, re-derives the project's `permit_posture`, and increments the project's `version`."
    PRD §3.3: "Records in `DENIED`, `SUBMITTED`, `UNDER_REVIEW`, `CONDITIONS_ISSUED` or `EXPIRED` contribute nothing at all."

    Design: Corner/state_machines/permit_under_review_branch_ends_in_denied
    """
    world, permit = submitted_local_set_application
    validate_success(
        world.api.decide_permit(
            permit["id"],
            f.permit_decision_payload("START_REVIEW"),
            AUTHORITY_HAVING_JURISDICTION,
        )
    )

    denied = validate_success(
        world.api.decide_permit(
            permit["id"],
            f.permit_decision_payload("DENY"),
            AUTHORITY_HAVING_JURISDICTION,
        )
    )

    assert denied["status"] == "DENIED"
    assert denied["pinned_package_id"] is None
    assert_instant(denied["decided_at"], f.DEFAULT_CLOCK, "decided_at")


def test_a_denied_set_application_leaves_the_project_dual_blocked(
    submitted_local_set_application,
):
    """PRD §3.3: "A track-and-scope pair counts as *live* when the project has a permit record with that `track` and that `scope` whose `status` is `APPROVED` and whose `expires_at` is either null or strictly later than the current clock instant."
    PRD §3.3: "If none of those match, `permit_posture` is `DUAL_BLOCKED`."

    Design: Corner/state_machines/permit_under_review_branch_ends_in_denied
    """
    world, permit = submitted_local_set_application
    validate_success(
        world.api.decide_permit(
            permit["id"],
            f.permit_decision_payload("START_REVIEW"),
            AUTHORITY_HAVING_JURISDICTION,
        )
    )
    validate_success(
        world.api.decide_permit(
            permit["id"],
            f.permit_decision_payload("DENY"),
            AUTHORITY_HAVING_JURISDICTION,
        )
    )

    project = validate_success(world.api.get_project(world.project_id, PROGRAM_ADMIN))
    assert project["permit_posture"] == "DUAL_BLOCKED"


def test_no_further_decision_may_be_recorded_against_a_denial(
    submitted_local_set_application,
):
    """PRD §3.3: "The `decision` is one of `START_REVIEW`, `ISSUE_CONDITIONS`, `APPROVE` or `DENY`, and each demands a compatible current `status`; an incompatible pairing, or any decision at all against a record already in `DENIED` or `EXPIRED`, is rejected with `ERR_PERMIT_ALREADY_DECIDED`."

    Design: Corner/state_machines/permit_under_review_branch_ends_in_denied
    """
    world, permit = submitted_local_set_application
    validate_success(
        world.api.decide_permit(
            permit["id"],
            f.permit_decision_payload("START_REVIEW"),
            AUTHORITY_HAVING_JURISDICTION,
        )
    )
    validate_success(
        world.api.decide_permit(
            permit["id"],
            f.permit_decision_payload("DENY"),
            AUTHORITY_HAVING_JURISDICTION,
        )
    )

    validate_error(
        world.api.decide_permit(
            permit["id"],
            f.permit_decision_payload("APPROVE"),
            AUTHORITY_HAVING_JURISDICTION,
        ),
        ERR_PERMIT_ALREADY_DECIDED,
    )

    still_denied = validate_success(
        world.api.get_permit(permit["id"], AUTHORITY_HAVING_JURISDICTION)
    )
    assert still_denied["status"] == "DENIED"


@pytest.fixture
def project_with_a_draft_revision(api):
    """A plant and a project carrying revision R1, still in DRAFT."""
    world = fx.world_plant_and_project(api)
    world.package = fx.create_design_package(
        api, world.project_id, world.project["version"]
    )
    return world


def test_freezing_the_first_revision_lifts_the_project_off_preconstruction(
    project_with_a_draft_revision,
):
    """PRD §3.7: "**Project phase** is derived by a full re-scan of the project's design packages, modules and shipments, never by an increment, and the branches below are evaluated in order with the first match winning."
    PRD §3.7: "Otherwise `phase` is `PRECONSTRUCTION`."
    PRD §3.2: "On success, `reviewed_by_user_id` and `review_note` are recorded, the project's `phase` is re-derived — which lifts a project sitting at `PRECONSTRUCTION` to `DESIGN_FROZEN` when no module has yet reached the line — and both the package's `version` and the project's `version` increment."

    Design: Corner/state_machines/project_phase_is_derived_from_child_entity_states
    """
    world = project_with_a_draft_revision
    before = validate_success(world.api.get_project(world.project_id, PROGRAM_ADMIN))
    assert before["phase"] == "PRECONSTRUCTION"

    frozen = fx.freeze_package(world.api, world.package_id)
    assert frozen["freeze_state"] == "FROZEN"

    after = validate_success(world.api.get_project(world.project_id, PROGRAM_ADMIN))
    assert after["phase"] == "DESIGN_FROZEN"


def test_the_first_module_reaching_the_line_lifts_the_phase_to_in_production(
    project_with_a_draft_revision,
):
    """PRD §3.7: "Otherwise, if any module of the project has `production_status` `IN_LINE` or `LINE_COMPLETE`, `phase` is `IN_PRODUCTION`."
    PRD §3.7: "Otherwise, if any design package of the project has `freeze_state` `FROZEN` or `SUPERSEDED`, `phase` is `DESIGN_FROZEN`."
    PRD §3.4: "The first advance from `SLOTTED` moves `production_status` to `IN_LINE`, increases `station_index` by `stations_advanced` capped at the plant's `station_count`, recomputes `wip_earned_cents`, re-derives the project's `phase` from `DESIGN_FROZEN` up to `IN_PRODUCTION`, and increments both the module's and the project's `version`."

    Design: Corner/state_machines/project_phase_is_derived_from_child_entity_states
    """
    world = project_with_a_draft_revision
    world.package = fx.freeze_package(world.api, world.package_id)
    fx.approve_permit(world.api, world.project_id, "STATE_MODULAR_PROGRAM", "PLAN_REVIEW")
    world.modules["M-01"] = fx.create_module(
        world.api, world.project_id, world.package_id, world.factory_id, "M-01", 1
    )

    # A module holding a takt window has not reached the line yet.
    fx.schedule_slot(world)
    slotted_phase = validate_success(
        world.api.get_project(world.project_id, PROGRAM_ADMIN)
    )
    assert slotted_phase["phase"] == "DESIGN_FROZEN"

    module = validate_success(
        world.api.advance_station(
            world.module_id(), f.advance_payload(1), world.factory_manager
        )
    )
    assert module["production_status"] == "IN_LINE"

    project = validate_success(world.api.get_project(world.project_id, PROGRAM_ADMIN))
    assert project["phase"] == "IN_PRODUCTION"


@pytest.fixture
def module_delivered_with_a_planned_lift(api):
    """A module standing on the site, lift planned, only the state track cleared.

    Plan review is approved and pins the revision the module was built to, but
    no insignia has been released and the local authority has permitted nothing.
    """
    world = fx.world_delivered_module(api)
    fx.plan_pick(world)
    return world


def test_the_state_track_alone_does_not_permit_the_lift(
    module_delivered_with_a_planned_lift,
):
    """PRD §3.7: "The project's `permit_posture` must be `SET_CLEARED` or `OCCUPANCY_CLEARED`, or the attempt is `ERR_SET_NOT_PERMITTED`."
    PRD §3.3: "Setting a module on the foundation requires `permit_posture` to be either `SET_CLEARED` or `OCCUPANCY_CLEARED`, enforced as `ERR_SET_NOT_PERMITTED` — which is to say both tracks must have delivered, the state having approved the design and released insignia and the local authority having permitted the set."
    PRD §3.3: "Otherwise, if state plan review is live and the site side is not cleared, it is `STATE_CLEARED_ONLY`."

    Design: Corner/state_machines/execute_set_is_guarded_by_the_projects_permit_posture
    """
    world = module_delivered_with_a_planned_lift
    project = validate_success(world.api.get_project(world.project_id, PROGRAM_ADMIN))
    assert project["permit_posture"] == "STATE_CLEARED_ONLY"

    validate_error(
        world.api.execute_set(
            world.module_id(),
            {"set_note": "attempt without the local set permit"},
            world.superintendent,
        ),
        ERR_SET_NOT_PERMITTED,
    )

    module = world.refresh_module()
    assert_module_dimensions(module, site_status="DELIVERED")
    assert module["set_at"] is None
    assert world.refresh_project()["modules_set_count"] == 0


def test_releasing_insignia_still_leaves_the_site_side_uncleared(
    module_delivered_with_a_planned_lift,
):
    """PRD §3.3: "From those live pairs the derivation reads five facts — whether state plan review is live, whether state insignia is live, whether the local foundation permit is live, whether the local set permit is live, and whether local occupancy is live — plus one composite: the *site side* counts as cleared when either the local foundation permit or the local set permit is live."
    PRD §3.3: "Otherwise, if state plan review is live and the site side is not cleared, it is `STATE_CLEARED_ONLY`."
    PRD §3.7: "The project's `permit_posture` must be `SET_CLEARED` or `OCCUPANCY_CLEARED`, or the attempt is `ERR_SET_NOT_PERMITTED`."

    Design: Corner/state_machines/execute_set_is_guarded_by_the_projects_permit_posture
    """
    world = module_delivered_with_a_planned_lift
    fx.approve_permit(world.api, world.project_id, "STATE_MODULAR_PROGRAM", "INSIGNIA")

    project = validate_success(world.api.get_project(world.project_id, PROGRAM_ADMIN))
    assert project["permit_posture"] == "STATE_CLEARED_ONLY"

    validate_error(
        world.api.execute_set(
            world.module_id(),
            {"set_note": "insignia released but the site is not permitted"},
            world.superintendent,
        ),
        ERR_SET_NOT_PERMITTED,
    )
    assert_module_dimensions(world.refresh_module(), site_status="DELIVERED")


def test_the_local_set_permit_completes_the_posture_and_the_module_lands(
    module_delivered_with_a_planned_lift,
):
    """PRD §3.3: "Otherwise, if the local set permit, state plan review and state insignia are all live, it is `SET_CLEARED`."
    PRD §3.7: "A successful set stamps `set_at` with the current clock instant, resets the module's `exposure_open_hours` to 0 because the exposure clock starts now, increases the project's `modules_set_count` by 1, re-derives the project's `phase` up to `SETTING`, and increments both the module's and the project's `version`."

    Design: Corner/state_machines/execute_set_is_guarded_by_the_projects_permit_posture
    """
    world = module_delivered_with_a_planned_lift
    fx.clear_the_site_for_setting(world)

    project = validate_success(world.api.get_project(world.project_id, PROGRAM_ADMIN))
    assert project["permit_posture"] == "SET_CLEARED"

    module = validate_success(
        world.api.execute_set(
            world.module_id(),
            {"set_note": "both tracks have delivered"},
            world.superintendent,
        )
    )

    assert_module_dimensions(module, site_status="SET")
    assert_instant(module["set_at"], f.DEFAULT_CLOCK, "set_at")
    assert world.refresh_project()["modules_set_count"] == 1


@pytest.fixture
def one_module_building_landed(api):
    """A one-module building whose single module has been set on the foundation."""
    return fx.world_set_module(
        api,
        project_overrides=SINGLE_MODULE_PROJECT,
        package_overrides=SINGLE_MODULE_REVISION,
    )


@pytest.fixture
def one_module_building_closed_in(api):
    """The same one-module building with its connections closed."""
    return fx.world_connected_module(
        api,
        project_overrides=SINGLE_MODULE_PROJECT,
        package_overrides=SINGLE_MODULE_REVISION,
    )


def test_landing_the_only_module_puts_the_project_into_setting(
    one_module_building_landed,
):
    """PRD §3.7: "Otherwise, if any module of the project has `site_status` `SET` or `CONNECTED`, `phase` is `SETTING`."
    PRD §2.9: "Two counters on `Project` — `modules_set_count` and `modules_connected_count` — are maintained as counts of the project's modules whose `site_status` is `SET` or `CONNECTED`, and whose `site_status` is `CONNECTED`, respectively."

    Design: Corner/state_machines/project_phase_bubbles_up_to_closeout_when_every_module_is_connected
    """
    world = one_module_building_landed
    module = world.refresh_module()
    assert_module_dimensions(module, site_status="SET")
    assert_instant(module["set_at"], f.DEFAULT_CLOCK, "set_at")

    project = validate_success(world.api.get_project(world.project_id, PROGRAM_ADMIN))
    assert project["phase"] == "SETTING"
    assert project["modules_set_count"] == 1
    assert project["modules_connected_count"] == 0


def test_closing_the_last_module_bubbles_the_project_to_closeout(
    one_module_building_closed_in,
):
    """PRD §3.7: "If the project's `planned_module_count` is greater than 0 and its `modules_connected_count` is greater than or equal to that count, `phase` is `CLOSEOUT`; reaching `CLOSEOUT` also re-derives `permit_posture`, since occupancy becomes eligible at that point."
    PRD §3.7: "Closing connections stamps `connected_at` with the current clock instant and freezes `exposure_open_hours` at the elapsed span between `set_at` and `connected_at`."
    PRD §3.7: "It increases the project's `modules_connected_count` by 1 and re-derives both the project's `permit_posture` and its `phase`."

    Design: Corner/state_machines/project_phase_bubbles_up_to_closeout_when_every_module_is_connected
    """
    world = one_module_building_closed_in
    module = world.refresh_module()
    assert_module_dimensions(module, site_status="CONNECTED")
    assert_instant(module["connected_at"], f.DEFAULT_CLOCK, "connected_at")
    # The clock never moved between the set and the closeout.
    assert_two_decimal_value(module["exposure_open_hours"], 0.00, "exposure_open_hours")

    project = validate_success(world.api.get_project(world.project_id, PROGRAM_ADMIN))
    assert project["phase"] == "CLOSEOUT"
    assert project["modules_set_count"] == 1
    assert project["modules_connected_count"] == 1


def test_a_closed_in_module_has_no_onward_move_on_the_site_dimension(
    one_module_building_closed_in,
):
    """PRD §3.7: "`CONNECTED` is terminal on the site dimension."
    PRD §3.7: "The module's `site_status` must be `DELIVERED`, or the attempt is `ERR_MODULE_NOT_READY_TO_SET`."
    PRD §3.7: "The module's `site_status` must be `SET`, or the attempt is `ERR_MODULE_NOT_SET`."

    Design: Corner/state_machines/project_phase_bubbles_up_to_closeout_when_every_module_is_connected
    """
    world = one_module_building_closed_in

    validate_error(
        world.api.execute_set(
            world.module_id(), {"set_note": "set it twice"}, world.superintendent
        ),
        ERR_MODULE_NOT_READY_TO_SET,
    )
    validate_error(
        world.api.close_connections(
            world.module_id(),
            f.close_connections_payload(True),
            world.superintendent,
        ),
        ERR_MODULE_NOT_SET,
    )

    assert_module_dimensions(world.refresh_module(), site_status="CONNECTED")
    project = validate_success(world.api.get_project(world.project_id, PROGRAM_ADMIN))
    assert project["modules_connected_count"] == 1
