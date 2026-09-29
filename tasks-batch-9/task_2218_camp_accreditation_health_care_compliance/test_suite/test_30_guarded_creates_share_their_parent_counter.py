"""The three guarded creates pin a parent row rather than an endpoint, so a version spent filing a
written plan is already stale for opening a cycle, and every refusal leaves the supersede cascade
unexecuted."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import cycle_payload, visit_payload, written_plan_payload
from test_helpers.test_users import OFFICER_ONE_HEADERS, make_camp_director_headers
from test_helpers.types import (
    AssignmentStatus,
    CampType,
    Certification,
    CycleStatus,
    HealthStaffingLevel,
    PlanType,
    PopulationServed,
    StandardDomain,
    TeamRole,
    VisitStatus,
    WrittenPlanStatus,
)
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

OCC_STANDARDS = [
    fx.universal_mandatory_standard(
        "SU.1", domain=StandardDomain.SUPERVISION, scoring_weight=1
    )
]


def _a_camp_whose_version_is_read_only_once(api):
    """One camp, one published edition, one visitor - and a single captured camp version."""
    fx.reset_clock(api)
    camp = fx.register_camp(
        api,
        name="Occ Camp",
        camp_type=CampType.DAY,
        state_code="OH",
        population_served=PopulationServed.YOUTH_ONLY,
        health_staffing_level=HealthStaffingLevel.RN_ONSITE,
    )
    edition, _standards = fx.publish_edition_with_standards(api, "ACA-2026-OCC", OCC_STANDARDS)
    visitor = fx.add_visitor(
        api, "Occ Visitor", certifications=[Certification.LEAD_VISITOR]
    )
    return {
        "camp_id": camp["id"],
        "set_id": edition["id"],
        "visitor_id": visitor["id"],
        "camp_v1": camp["version"],
    }


def _file_health_care_plan(api, world, body_ref, expected_camp_version):
    return api.create_written_plan(
        written_plan_payload(
            world["camp_id"],
            PlanType.HEALTH_CARE,
            expected_camp_version,
            body_ref=body_ref,
            effective_date="2026-06-01",
            expires_at="2027-05-31",
            physician_reviewed=True,
        ),
        make_camp_director_headers(world["camp_id"]),
    )


def _open_cycle_attempt(api, world, expected_camp_version):
    return api.create_cycle(
        cycle_payload(world["camp_id"], world["set_id"], expected_camp_version, 2026),
        OFFICER_ONE_HEADERS,
    )


def _open_visit_attempt(api, cycle_id, expected_cycle_version, window):
    return api.create_visit(
        visit_payload(
            cycle_id,
            expected_cycle_version,
            window_start_date=window[0],
            window_end_date=window[1],
        ),
        OFFICER_ONE_HEADERS,
    )


def test_the_version_a_plan_filing_spends_is_stale_for_the_very_next_filing(api):
    """PRD §2.6: "Filing a written plan likewise requires `expected_camp_version` as a
    non-optional input field, and a mismatch with the camp's current `version` is rejected with
    `ERR_STALE_CAMP_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/all_three_declared_occ_writes_refuse_a_stale_parent_view_and_accept_the_refreshed_one
    """
    world = _a_camp_whose_version_is_read_only_once(api)

    plan_a = validate_success(
        _file_health_care_plan(api, world, "HC-PLAN-A", world["camp_v1"]), 201
    )
    assert fx.read_camp(api, world["camp_id"])["version"] == world["camp_v1"] + 1

    refused = _file_health_care_plan(api, world, "HC-PLAN-B", world["camp_v1"])
    validate_error(refused, ApiErrorId.STALE_CAMP_VERSION, 412)
    # A 412 answers with the error envelope and never with the parent it refused to touch.
    assert set(refused.json()["data"]) == {"error_id", "message"}
    # The supersede never ran.
    assert fx.read_plan(api, plan_a["id"])["status"] == WrittenPlanStatus.SUBMITTED

    camp_v2 = fx.read_camp(api, world["camp_id"])["version"]
    plan_b = validate_success(
        _file_health_care_plan(api, world, "HC-PLAN-B", camp_v2), 201
    )
    assert fx.read_plan(api, plan_a["id"])["status"] == WrittenPlanStatus.SUPERSEDED
    assert plan_b["supersedes_plan_id"] == plan_a["id"]


def test_the_cycle_create_inherits_the_staleness_through_the_shared_camp_counter(api):
    """PRD §2.6: "Note that the guarded creates themselves advance the pinned parent: opening a
    cycle increments the camp's `version` by one, filing a plan increments the camp's `version` by
    one, and creating a visit increments the cycle's `version` by one. A client issuing two such
    creates in sequence must therefore re-read the parent between them."

    Design: Corner/cross_cutting_complexity_layers/all_three_declared_occ_writes_refuse_a_stale_parent_view_and_accept_the_refreshed_one
    """
    world = _a_camp_whose_version_is_read_only_once(api)
    validate_success(_file_health_care_plan(api, world, "HC-PLAN-A", world["camp_v1"]), 201)
    camp_v2 = fx.read_camp(api, world["camp_id"])["version"]
    validate_success(_file_health_care_plan(api, world, "HC-PLAN-B", camp_v2), 201)

    # The version the plan filing spent is refused on a different endpoint entirely.
    validate_error(
        _open_cycle_attempt(api, world, camp_v2), ApiErrorId.STALE_CAMP_VERSION, 412
    )
    assert validate_paginated(api.list_cycles({}, OFFICER_ONE_HEADERS))[1]["total_count"] == 0
    assert (
        validate_paginated(api.list_evaluations({}, OFFICER_ONE_HEADERS))[1]["total_count"] == 0
    )

    camp_v3 = fx.read_camp(api, world["camp_id"])["version"]
    cycle = validate_success(_open_cycle_attempt(api, world, camp_v3), 201)
    assert cycle["status"] == CycleStatus.SELF_ASSESSMENT
    assert cycle["applicable_standard_count"] == 1
    assert cycle["applicable_mandatory_count"] == 1


def test_a_stale_cycle_view_leaves_the_standing_visit_and_its_seat_untouched(api):
    """PRD §2.6: "Creating a visit requires `expected_cycle_version` as a non-optional input
    field, carrying the client's last observed `version` of the target `AccreditationCycle`. A
    mismatch with the cycle's current `version` is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP
    412)."

    Design: Corner/cross_cutting_complexity_layers/all_three_declared_occ_writes_refuse_a_stale_parent_view_and_accept_the_refreshed_one
    """
    world = _a_camp_whose_version_is_read_only_once(api)
    cycle = validate_success(_open_cycle_attempt(api, world, world["camp_v1"]), 201)
    cycle_v1 = cycle["version"]

    first_visit = validate_success(
        _open_visit_attempt(api, cycle["id"], cycle_v1, ("2026-08-10", "2026-08-16")), 201
    )
    # The create bumped the parent cycle, which is what makes cycle_v1 stale below.
    assert fx.read_cycle(api, cycle["id"])["version"] == cycle_v1 + 1
    seat = fx.seat_visitor(
        api,
        first_visit["id"],
        world["visitor_id"],
        TeamRole.LEAD,
        "2026-08-10",
        "2026-08-12",
    )

    validate_error(
        _open_visit_attempt(api, cycle["id"], cycle_v1, ("2026-08-18", "2026-08-24")),
        ApiErrorId.STALE_CYCLE_VERSION,
        412,
    )
    # The guarded cascade did not run at any of its three levels.
    assert fx.read_visit(api, first_visit["id"])["status"] == VisitStatus.DRAFT
    assert fx.read_assignment(api, seat["id"])["status"] == AssignmentStatus.ASSIGNED
    assert fx.read_visitor(api, world["visitor_id"])["committed_travel_days"] == 3


def test_the_refreshed_cycle_view_runs_the_rescind_and_returns_the_ledger_to_zero(api):
    """PRD §2.6: "Creating a visit for a cycle that already carries a `DRAFT` or `SCHEDULED` visit
    rescinds that visit and withdraws its seats, so a stale cycle view means the client's picture
    of the standing visit and its seated team is wrong."

    Design: Corner/cross_cutting_complexity_layers/all_three_declared_occ_writes_refuse_a_stale_parent_view_and_accept_the_refreshed_one
    """
    world = _a_camp_whose_version_is_read_only_once(api)
    cycle = validate_success(_open_cycle_attempt(api, world, world["camp_v1"]), 201)

    first_visit = validate_success(
        _open_visit_attempt(api, cycle["id"], cycle["version"], ("2026-08-10", "2026-08-16")),
        201,
    )
    seat = fx.seat_visitor(
        api,
        first_visit["id"],
        world["visitor_id"],
        TeamRole.LEAD,
        "2026-08-10",
        "2026-08-12",
    )
    assert fx.read_visitor(api, world["visitor_id"])["committed_travel_days"] == 3

    cycle_v2 = fx.read_cycle(api, cycle["id"])["version"]
    second_visit = validate_success(
        _open_visit_attempt(api, cycle["id"], cycle_v2, ("2026-08-18", "2026-08-24")), 201
    )
    assert second_visit["status"] == VisitStatus.DRAFT
    assert fx.read_visit(api, first_visit["id"])["status"] == VisitStatus.RESCINDED
    assert fx.read_assignment(api, seat["id"])["status"] == AssignmentStatus.WITHDRAWN
    assert fx.read_visitor(api, world["visitor_id"])["committed_travel_days"] == 0
