"""Cross-entity gates, interval conventions and conserved quantities.

Three families of PRD rules are exercised here. First, decisions that are assembled
from facts living on several different records at once: a controlled-access grant
activation reads the Project's security dimension, the Investigator's posture and the
Disclosure's independent management-plan dimension, and an award activation reads the
project's blocker list built from personnel, disclosures and training assignments.
Second, the two deliberately opposite interval conventions -- travel windows are closed
and controlled-area windows are half-open. Third, quantities the PRD declares conserved:
a project's active grant headcount across a suspend/re-clear cycle, and an investigator's
per-row-rounded committed effort percentage across an add/remove cycle.
"""

import pytest

from test_helpers import (
    ADMIN,
    RSO,
    ApiErrorId,
    acknowledge_plan,
    add_disclosure_item,
    add_personnel,
    assign_and_complete_training,
    assign_training,
    begin_review,
    certify_disclosure,
    clear_project_security,
    create_access_grant,
    create_disclosure,
    create_investigator,
    create_organization,
    create_project,
    create_travel,
    get_success_data,
    issue_plan,
    make_investigator_headers,
    read_access_grant,
    read_disclosure,
    read_disclosure_item,
    read_investigator,
    read_project,
    read_travel,
    require_plan,
    set_award_status,
    set_grant_status,
    set_item_status,
    setup_area_access_ready,
    setup_committed_effort,
    submit_disclosure,
    submit_travel,
    validate_error,
    validate_success,
)

# --------------------------------------------------------------------------- #
# Module-private setup helpers
# --------------------------------------------------------------------------- #


def _setup_talent_program_grant(clear_security: bool = True) -> dict:
    """One investigator who is ready for controlled-area access on a capacity-1
    project, plus a SUBMITTED disclosure carrying a single paid `TALENT_PROGRAM`
    item on an `SDN` organization, plus a `REQUESTED` grant over
    [2026-09-01, 2026-12-01).

    The item is still `DECLARED`, so it contributes nothing to `risk_score` yet and
    the investigator's posture is `CLEAR` at the end of setup.
    """
    organization = create_organization(
        legal_name="Crest Talent Institute",
        country_code="CN",
        org_type="TALENT_PROGRAM",
        own_designation="SDN",
        designated_on="2025-02-01T00:00:00Z",
    )
    investigator = create_investigator(
        full_name="Omar Petrov",
        home_department="Electrical Engineering",
        institutional_base_effort_pct=0,
    )
    project = create_project(
        title="RF Hardware Enclave",
        agency_code="DOD",
        sensitivity_level="RESTRICTED",
        award_amount_cents=180_000_000,
        period_start="2026-09-01T00:00:00Z",
        period_end="2029-08-31T00:00:00Z",
        controlled_area_capacity=1,
    )
    personnel = add_personnel(
        project["id"],
        investigator["id"],
        role_on_project="PI",
        committed_person_months=2.00,
    )
    assign_and_complete_training(
        investigator["id"], course_code="CONTROLLED_AREA_SAFETY"
    )
    disclosure = create_disclosure(investigator["id"])
    item = add_disclosure_item(
        disclosure["id"],
        organization["id"],
        investigator_id=investigator["id"],
        item_type="TALENT_PROGRAM",
        annual_effort_hours=0,
        is_paid=True,
    )
    submit_disclosure(disclosure["id"], investigator["id"])
    if clear_security:
        clear_project_security(project["id"])
    grant = create_access_grant(
        project["id"],
        investigator["id"],
        valid_from="2026-09-01T00:00:00Z",
        valid_until="2026-12-01T00:00:00Z",
    )
    return {
        "organization": organization,
        "investigator": investigator,
        "project": project,
        "personnel": personnel,
        "disclosure": disclosure,
        "item": item,
        "grant": grant,
    }


def _setup_award_pending_two_blockers() -> dict:
    """A project at `award_status` `ACTIVATION_PENDING` with security `CLEARED`, an
    `ACTIVE` PI whose disclosure is still `DRAFT`, and one project-scoped
    `EXPORT_CONTROL` assignment sitting at `ASSIGNED`.
    """
    investigator = create_investigator(
        full_name="Pia Quintero",
        home_department="Civil Engineering",
        institutional_base_effort_pct=0,
    )
    project = create_project(
        title="Resilient Bridge Monitoring",
        agency_code="NSF",
        sensitivity_level="STANDARD",
        award_amount_cents=40_000_000,
        period_start="2026-09-01T00:00:00Z",
        period_end="2028-08-31T00:00:00Z",
        controlled_area_capacity=0,
    )
    personnel = add_personnel(
        project["id"],
        investigator["id"],
        role_on_project="PI",
        committed_person_months=1.50,
    )
    assignment = assign_training(
        investigator["id"],
        course_code="EXPORT_CONTROL",
        due_on="2026-12-31T00:00:00Z",
        required_for_project_id=project["id"],
    )
    disclosure = create_disclosure(investigator["id"])
    clear_project_security(project["id"])
    set_award_status(project["id"], "ACTIVATION_PENDING")
    return {
        "investigator": investigator,
        "project": project,
        "personnel": personnel,
        "assignment": assignment,
        "disclosure": disclosure,
    }


def _setup_adjacent_trips() -> dict:
    """One investigator with a `SUBMITTED` trip over the closed window
    [2026-09-01, 2026-09-10] and a second trip still in `DRAFT` that departs
    exactly on the first trip's `return_on`.
    """
    investigator = create_investigator(
        full_name="Rui Sato",
        home_department="Economics",
        institutional_base_effort_pct=0,
    )
    first = create_travel(
        investigator["id"],
        destination_country_code="JP",
        depart_on="2026-09-01T00:00:00Z",
        return_on="2026-09-10T00:00:00Z",
        purpose="CONFERENCE",
        carries_institutional_device=False,
    )
    second = create_travel(
        investigator["id"],
        destination_country_code="JP",
        depart_on="2026-09-10T00:00:00Z",
        return_on="2026-09-20T00:00:00Z",
        purpose="COLLABORATION",
        carries_institutional_device=False,
    )
    submit_travel(first["id"], investigator["id"])
    return {
        "investigator": investigator,
        "first": first,
        "second": second,
    }


def _setup_two_touching_active_grants() -> dict:
    """A capacity-1 controlled area holding two `ACTIVE` grants whose half-open
    windows merely touch: [2026-09-01, 2026-09-10) and [2026-09-10, 2026-09-20).

    A third investigator on the same project is left free of grants so a straddling
    window can be requested against the same capacity.
    """
    project, investigators, personnel_rows = setup_area_access_ready(
        controlled_area_capacity=1,
        sensitivity_level="CONTROLLED",
        investigator_count=3,
        title="Secure Materials Bay",
        agency_code="DOD",
        award_amount_cents=80_000_000,
        period_start="2026-09-01T00:00:00Z",
        period_end="2028-08-31T00:00:00Z",
    )
    grant_a = create_access_grant(
        project["id"],
        investigators[0]["id"],
        valid_from="2026-09-01T00:00:00Z",
        valid_until="2026-09-10T00:00:00Z",
    )
    grant_a = set_grant_status(grant_a["id"], "ACTIVE")
    grant_b = create_access_grant(
        project["id"],
        investigators[1]["id"],
        valid_from="2026-09-10T00:00:00Z",
        valid_until="2026-09-20T00:00:00Z",
    )
    return {
        "project": project,
        "investigators": investigators,
        "personnel_rows": personnel_rows,
        "grant_a": grant_a,
        "grant_b": grant_b,
    }


def _setup_two_active_grants_capacity_two() -> dict:
    """A capacity-2 controlled area with two `ACTIVE` grants over the same window,
    so `active_grant_count` is 2 and `controlled_area_posture` is `RESTRICTED`.
    """
    project, investigators, personnel_rows = setup_area_access_ready(
        controlled_area_capacity=2,
        sensitivity_level="CONTROLLED",
        investigator_count=2,
        title="Directed Energy Bay",
        agency_code="DOD",
        award_amount_cents=150_000_000,
        period_start="2026-09-01T00:00:00Z",
        period_end="2029-08-31T00:00:00Z",
    )
    grant_a = create_access_grant(
        project["id"],
        investigators[0]["id"],
        valid_from="2026-09-01T00:00:00Z",
        valid_until="2026-12-01T00:00:00Z",
    )
    grant_b = create_access_grant(
        project["id"],
        investigators[1]["id"],
        valid_from="2026-09-01T00:00:00Z",
        valid_until="2026-12-01T00:00:00Z",
    )
    grant_a = set_grant_status(grant_a["id"], "ACTIVE")
    grant_b = set_grant_status(grant_b["id"], "ACTIVE")
    return {
        "project": project,
        "investigators": investigators,
        "grant_a": grant_a,
        "grant_b": grant_b,
    }


def _setup_three_active_rows_and_a_proposed_fourth() -> dict:
    """One investigator holding three `ACTIVE` personnel rows of 1.00 committed
    person-month each -- `committed_effort_pct` 24.99 -- plus a fourth identical row
    still in `PROPOSED`.
    """
    investigator, projects, rows = setup_committed_effort(
        project_count=3, committed_person_months=1.00, institutional_base_effort_pct=0
    )
    fourth_project = create_project(title="Survey Methods Four", agency_code="NIH")
    fourth_row = add_personnel(
        fourth_project["id"],
        investigator["id"],
        role_on_project="SENIOR_PERSONNEL",
        committed_person_months=1.00,
        activate=False,
    )
    return {
        "investigator": investigator,
        "projects": projects,
        "rows": rows,
        "fourth_project": fourth_project,
        "fourth_row": fourth_row,
    }


# --------------------------------------------------------------------------- #
# Grant activation reads three different entities
# --------------------------------------------------------------------------- #


def test_grant_activation_is_refused_while_project_security_is_pending_clearance(api):
    """PRD §3.7: "The project's `security_status` must be `CLEARED`, else `ERR_PROJECT_NOT_CLEARED`."

    Design: Difficulty/cross_entity_state_dependency/grant_activation_depends_on_project_security_and_investigator_posture_and_plan
    """
    scenario = _setup_talent_program_grant(clear_security=False)
    grant = scenario["grant"]
    project = read_project(scenario["project"]["id"])
    assert project["security_status"] == "PENDING_CLEARANCE"

    # Nothing on the investigator blocks access: the DECLARED item scores nothing yet.
    investigator = read_investigator(scenario["investigator"]["id"])
    assert investigator["risk_score"] == 0
    assert investigator["disclosure_posture"] == "CLEAR"

    response = api.set_access_grant_status(grant["id"], {"to_status": "ACTIVE"}, RSO)
    validate_error(
        response, ApiErrorId.ERR_PROJECT_NOT_CLEARED.value, expected_status=409
    )

    assert read_access_grant(grant["id"])["status"] == "REQUESTED"
    assert read_project(scenario["project"]["id"])["active_grant_count"] == 0


def test_grant_activation_is_refused_while_investigator_posture_is_restricted(api):
    """PRD §3.7: "That investigator's `disclosure_posture` must be `CLEAR` or `REVIEW_REQUIRED`, else `ERR_INVESTIGATOR_POSTURE_BLOCKS_ACCESS`."

    Design: Difficulty/cross_entity_state_dependency/grant_activation_depends_on_project_security_and_investigator_posture_and_plan
    """
    scenario = _setup_talent_program_grant(clear_security=True)
    grant = scenario["grant"]
    assert read_project(scenario["project"]["id"])["security_status"] == "CLEARED"

    # A paid TALENT_PROGRAM item on an SDN counterparty: 30 * 3.0 + 5 = 95 points,
    # capped at 60 for the item subtotal, which is exactly the RESTRICTED floor.
    begin_review(scenario["disclosure"]["id"])
    set_item_status(scenario["item"]["id"], "VERIFIED")
    assert read_disclosure_item(scenario["item"]["id"])["item_risk_points"] == 95

    investigator = read_investigator(scenario["investigator"]["id"])
    assert investigator["risk_score"] == 60
    assert investigator["disclosure_posture"] == "RESTRICTED"

    response = api.set_access_grant_status(grant["id"], {"to_status": "ACTIVE"}, RSO)
    validate_error(
        response,
        ApiErrorId.ERR_INVESTIGATOR_POSTURE_BLOCKS_ACCESS.value,
        expected_status=409,
    )

    assert read_project(scenario["project"]["id"])["active_grant_count"] == 0


def test_acknowledged_plan_credit_lets_the_same_grant_activation_succeed(api):
    """PRD §3.4: "It sets `plan_acknowledged_at` to the current logical clock; because an acknowledged plan is now in force, the investigator's `risk_score` is recomputed and the mitigation credit of 20 points applies while the logical clock remains before `plan_expires_on`; and because `risk_score` changed, `disclosure_posture` is recomputed."

    Design: Difficulty/cross_entity_state_dependency/grant_activation_depends_on_project_security_and_investigator_posture_and_plan
    """
    scenario = _setup_talent_program_grant(clear_security=True)
    grant = scenario["grant"]
    disclosure_id = scenario["disclosure"]["id"]
    investigator_id = scenario["investigator"]["id"]

    begin_review(disclosure_id)
    set_item_status(scenario["item"]["id"], "VERIFIED")
    assert read_investigator(investigator_id)["disclosure_posture"] == "RESTRICTED"

    # The plan dimension is a third entity's state: 60 - 20 = 40 crosses back below
    # the RESTRICTED floor of 60 while staying at or above the REVIEW floor of 30.
    require_plan(disclosure_id)
    issue_plan(
        disclosure_id,
        plan_effort_cap_pct=100,
        plan_required_actions=["REDUCE_OUTSIDE_EFFORT", "QUARTERLY_ATTESTATION"],
        plan_effective_from="2026-08-01T00:00:00Z",
        plan_expires_on="2027-08-01T00:00:00Z",
    )
    acknowledge_plan(disclosure_id, investigator_id)

    assert read_disclosure(disclosure_id)["plan_status"] == "PLAN_ACKNOWLEDGED"
    investigator = read_investigator(investigator_id)
    assert investigator["risk_score"] == 40
    assert investigator["disclosure_posture"] == "REVIEW_REQUIRED"

    response = api.set_access_grant_status(grant["id"], {"to_status": "ACTIVE"}, RSO)
    validate_success(response, expected_status=200)
    assert get_success_data(response)["status"] == "ACTIVE"

    project = read_project(scenario["project"]["id"])
    assert project["active_grant_count"] == 1
    assert project["controlled_area_posture"] == "RESTRICTED"


# --------------------------------------------------------------------------- #
# Award activation reads the project's assembled blocker list
# --------------------------------------------------------------------------- #


def test_award_activation_names_the_first_blocker_in_the_fixed_order(api):
    """PRD §3.9: "The resulting list is always ordered by the fixed sequence `SECURITY_NOT_CLEARED`, `DISCLOSURE_NOT_CERTIFIED`, `TRAINING_INCOMPLETE`, `SUBAWARD_BLOCKED`, `SUPPORT_INCONSISTENT`, `PERSONNEL_MISSING_PI`, `INVESTIGATOR_SUSPENDED` — never in the order the conditions happened to be discovered — and no code appears twice even when several rows trigger it."

    Design: Difficulty/cross_entity_state_dependency/project_activation_depends_on_disclosure_then_training_in_blocker_order
    """
    scenario = _setup_award_pending_two_blockers()
    project = read_project(scenario["project"]["id"])
    assert project["award_status"] == "ACTIVATION_PENDING"
    assert project["activation_blockers"] == [
        "DISCLOSURE_NOT_CERTIFIED",
        "TRAINING_INCOMPLETE",
    ]

    response = api.set_award_status(project["id"], {"to_status": "ACTIVE"}, ADMIN)
    validate_error(
        response, ApiErrorId.ERR_ACTIVATION_BLOCKED.value, expected_status=409
    )
    assert read_project(project["id"])["award_status"] == "ACTIVATION_PENDING"


def test_certifying_the_disclosure_leaves_only_the_training_blocker(api):
    """PRD §3.4: "On success, `certified_at` is set to the current logical clock; every item still in `DECLARED` transitions to `VERIFIED`; because those items have entered the scoring set, the investigator's `outside_effort_pct`, `total_commitment_pct` and `risk_score` are recomputed; because `risk_score` changed, `disclosure_posture` is recomputed; and `activation_blockers` are recomputed for every project on which that investigator holds an `ACTIVE` personnel row, since certification is what removes `DISCLOSURE_NOT_CERTIFIED` from those lists."

    Design: Difficulty/cross_entity_state_dependency/project_activation_depends_on_disclosure_then_training_in_blocker_order
    """
    scenario = _setup_award_pending_two_blockers()
    project_id = scenario["project"]["id"]
    disclosure_id = scenario["disclosure"]["id"]

    submit_disclosure(disclosure_id, scenario["investigator"]["id"])
    begin_review(disclosure_id)
    certified = certify_disclosure(disclosure_id)
    assert certified["review_status"] == "CERTIFIED"
    assert certified["completeness_score"] == 100
    assert certified["completeness_tier"] == "A"

    # The disclosure blocker is gone; the project-scoped course is still outstanding.
    assert read_project(project_id)["activation_blockers"] == ["TRAINING_INCOMPLETE"]

    response = api.set_award_status(project_id, {"to_status": "ACTIVE"}, ADMIN)
    validate_error(
        response, ApiErrorId.ERR_ACTIVATION_BLOCKED.value, expected_status=409
    )
    assert read_project(project_id)["award_status"] == "ACTIVATION_PENDING"


def test_completing_the_project_course_empties_the_blocker_list_and_activates_the_award(
    api,
):
    """PRD §3.9: "Moving `ACTIVATION_PENDING → ACTIVE` requires `activation_blockers` to be empty, else `ERR_ACTIVATION_BLOCKED`, whose message names the first code in the ordered list — which is why the ordering above is fixed rather than incidental; on success it recomputes `open_incident_count` and `controlled_area_posture`."

    Design: Difficulty/cross_entity_state_dependency/project_activation_depends_on_disclosure_then_training_in_blocker_order
    """
    scenario = _setup_award_pending_two_blockers()
    project_id = scenario["project"]["id"]
    investigator_id = scenario["investigator"]["id"]
    disclosure_id = scenario["disclosure"]["id"]

    submit_disclosure(disclosure_id, investigator_id)
    begin_review(disclosure_id)
    certify_disclosure(disclosure_id)

    completion = api.complete_training_assignment(
        scenario["assignment"]["id"], make_investigator_headers(investigator_id)
    )
    validate_success(completion, expected_status=200)
    assert get_success_data(completion)["status"] == "COMPLETED"
    assert read_project(project_id)["activation_blockers"] == []

    response = api.set_award_status(project_id, {"to_status": "ACTIVE"}, ADMIN)
    validate_success(response, expected_status=200)
    assert get_success_data(response)["award_status"] == "ACTIVE"


# --------------------------------------------------------------------------- #
# Travel windows are closed intervals
# --------------------------------------------------------------------------- #


def test_trip_departing_on_an_existing_trip_return_instant_conflicts(api):
    """PRD §3.7: "Because the interval is closed, mere adjacency is a conflict: a new trip departing exactly on an existing trip's `return_on` is rejected, since a traveller cannot return and depart at the same instant."

    Design: Difficulty/resource_temporal_overlap/travel_windows_are_closed_so_adjacent_trips_conflict
    """
    scenario = _setup_adjacent_trips()
    investigator_id = scenario["investigator"]["id"]
    assert read_travel(scenario["first"]["id"])["status"] == "SUBMITTED"

    response = api.set_travel_status(
        scenario["second"]["id"],
        {"to_status": "SUBMITTED"},
        make_investigator_headers(investigator_id),
    )
    validate_error(
        response, ApiErrorId.ERR_TRAVEL_WINDOW_CONFLICT.value, expected_status=409
    )
    assert read_travel(scenario["second"]["id"])["status"] == "DRAFT"


def test_cancelling_the_earlier_trip_releases_the_closed_window(api):
    """PRD §3.7: "`SUBMITTED → CANCELLED` and `DRAFT → CANCELLED` are the traveller's own acts, requiring only that `X-User-ID` match the registration's investigator, else `ERR_NOT_RESOURCE_OWNER`; cancelling out of `SUBMITTED` releases the window so that a previously conflicting registration can now be submitted."

    Design: Difficulty/resource_temporal_overlap/travel_windows_are_closed_so_adjacent_trips_conflict
    """
    scenario = _setup_adjacent_trips()
    investigator_headers = make_investigator_headers(scenario["investigator"]["id"])

    blocked = api.set_travel_status(
        scenario["second"]["id"], {"to_status": "SUBMITTED"}, investigator_headers
    )
    validate_error(
        blocked, ApiErrorId.ERR_TRAVEL_WINDOW_CONFLICT.value, expected_status=409
    )

    cancelled = api.set_travel_status(
        scenario["first"]["id"], {"to_status": "CANCELLED"}, investigator_headers
    )
    validate_success(cancelled, expected_status=200)
    assert get_success_data(cancelled)["status"] == "CANCELLED"

    response = api.set_travel_status(
        scenario["second"]["id"], {"to_status": "SUBMITTED"}, investigator_headers
    )
    validate_success(response, expected_status=200)
    resubmitted = get_success_data(response)
    assert resubmitted["status"] == "SUBMITTED"
    # No destination, host, project or posture flag applies and no device is carried.
    assert resubmitted["risk_flag_count"] == 0
    assert resubmitted["device_requirement_tier"] == "NONE"
    assert resubmitted["briefing_required"] is False


# --------------------------------------------------------------------------- #
# Controlled-area windows are half-open intervals
# --------------------------------------------------------------------------- #


def test_grant_starting_on_another_grants_valid_until_activates_against_capacity_one(
    api,
):
    """PRD §3.7: "Capacity is projected over **half-open** windows running from `valid_from` up to but excluding `valid_until`, which is deliberately the opposite convention from travel: two grants that merely touch do not overlap."

    Design: Difficulty/resource_temporal_overlap/area_windows_are_half_open_so_adjacent_grants_coexist
    """
    scenario = _setup_two_touching_active_grants()
    assert read_access_grant(scenario["grant_a"]["id"])["status"] == "ACTIVE"

    response = api.set_access_grant_status(
        scenario["grant_b"]["id"], {"to_status": "ACTIVE"}, RSO
    )
    validate_success(response, expected_status=200)
    activated = get_success_data(response)
    assert activated["status"] == "ACTIVE"
    # The touching window never overlaps, so the candidate is the only holder.
    assert activated["peak_concurrency_at_request"] == 1

    project = read_project(scenario["project"]["id"])
    assert project["active_grant_count"] == 2
    assert project["controlled_area_posture"] == "RESTRICTED"


def test_grant_straddling_two_half_open_windows_exceeds_area_capacity(api):
    """PRD §3.7: "The check fails only on strictly greater: a peak exactly equal to the project's `controlled_area_capacity` is admissible, and a peak of one more than the capacity is refused with `ERR_AREA_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/area_windows_are_half_open_so_adjacent_grants_coexist
    """
    scenario = _setup_two_touching_active_grants()
    set_grant_status(scenario["grant_b"]["id"], "ACTIVE")

    # [2026-09-05, 2026-09-15) genuinely overlaps both touching windows, so the
    # sweep finds an occupancy of 2 against a controlled_area_capacity of 1.
    straddling = create_access_grant(
        scenario["project"]["id"],
        scenario["investigators"][2]["id"],
        valid_from="2026-09-05T00:00:00Z",
        valid_until="2026-09-15T00:00:00Z",
    )
    assert straddling["peak_concurrency_at_request"] == 2

    response = api.set_access_grant_status(
        straddling["id"], {"to_status": "ACTIVE"}, RSO
    )
    validate_error(
        response, ApiErrorId.ERR_AREA_CAPACITY_EXCEEDED.value, expected_status=409
    )
    assert read_access_grant(straddling["id"])["status"] == "REQUESTED"

    project = read_project(scenario["project"]["id"])
    assert project["active_grant_count"] == 2
    assert project["controlled_area_posture"] == "RESTRICTED"


# --------------------------------------------------------------------------- #
# The grant headcount is a conserved quantity
# --------------------------------------------------------------------------- #


def test_project_suspension_drives_the_grant_headcount_to_zero(api):
    """PRD §3.6: "Suspension then transitions every access grant on the project whose `status` is `REQUESTED` or `ACTIVE` to `SUSPENDED` with a `status_reason` of `PROJECT_SUSPENDED`; because grants left `ACTIVE`, the project's `active_grant_count` is recomputed; because that count changed, `controlled_area_posture` is recomputed; and `activation_blockers` are recomputed, where `SECURITY_NOT_CLEARED` now enters the list."

    Design: Difficulty/compensating_invariant/grant_headcount_returns_to_two_after_suspend_and_conditional_restore
    """
    scenario = _setup_two_active_grants_capacity_two()
    project_id = scenario["project"]["id"]
    before = read_project(project_id)
    assert before["active_grant_count"] == 2
    assert before["controlled_area_posture"] == "RESTRICTED"

    response = api.set_security_status(project_id, {"to_status": "SUSPENDED"}, RSO)
    validate_success(response, expected_status=200)

    for key in ("grant_a", "grant_b"):
        grant = read_access_grant(scenario[key]["id"])
        assert grant["status"] == "SUSPENDED"
        assert grant["status_reason"] == "PROJECT_SUSPENDED"

    after = read_project(project_id)
    assert after["active_grant_count"] == 0
    assert after["controlled_area_posture"] == "LOCKED_DOWN"
    assert "SECURITY_NOT_CLEARED" in after["activation_blockers"]


def test_reclearance_restores_the_grant_headcount_to_two(api):
    """PRD §3.6: "On success `security_status_reason` becomes `OFFICER_ACTION`, and a **conditional** restore runs: every access grant on the project whose `status` is `SUSPENDED` **and** whose `status_reason` is exactly `PROJECT_SUSPENDED` is revisited in ascending `created_at` order, and each one either returns to `ACTIVE` if the capacity projection still admits it, or else transitions to `REVOKED` with a `status_reason` of `CAPACITY_UNAVAILABLE`."

    Design: Difficulty/compensating_invariant/grant_headcount_returns_to_two_after_suspend_and_conditional_restore
    """
    scenario = _setup_two_active_grants_capacity_two()
    project_id = scenario["project"]["id"]

    suspended = api.set_security_status(project_id, {"to_status": "SUSPENDED"}, RSO)
    validate_success(suspended, expected_status=200)
    assert read_project(project_id)["active_grant_count"] == 0

    response = api.set_security_status(project_id, {"to_status": "CLEARED"}, RSO)
    validate_success(response, expected_status=200)
    recleared = get_success_data(response)
    assert recleared["security_status"] == "CLEARED"
    assert recleared["security_status_reason"] == "OFFICER_ACTION"

    # Both grants carried PROJECT_SUSPENDED and the capacity of 2 still admits both.
    for key in ("grant_a", "grant_b"):
        grant = read_access_grant(scenario[key]["id"])
        assert grant["status"] == "ACTIVE"
        assert grant["status_reason"] == "NONE"

    after = read_project(project_id)
    assert after["active_grant_count"] == 2
    assert after["controlled_area_posture"] == "RESTRICTED"


# --------------------------------------------------------------------------- #
# committed_effort_pct is a conserved rounded percentage
# --------------------------------------------------------------------------- #


def test_activating_a_fourth_identical_row_raises_committed_effort_to_33_32(api):
    """PRD §2.6: "An investigator's `committed_effort_pct` is the sum, over their personnel rows in `ACTIVE` status, of each row's `committed_person_months` divided by 12 months, multiplied by 100, and rounded half up to two decimal places at that point."

    Design: Difficulty/compensating_invariant/committed_effort_percentage_returns_to_24_99_after_add_and_remove
    """
    scenario = _setup_three_active_rows_and_a_proposed_fourth()
    investigator_id = scenario["investigator"]["id"]

    before = read_investigator(investigator_id)
    assert before["committed_effort_pct"] == pytest.approx(24.99, abs=0.01)
    assert before["total_commitment_pct"] == pytest.approx(24.99, abs=0.01)

    response = api.set_personnel_status(
        scenario["fourth_row"]["id"], {"to_status": "ACTIVE"}, ADMIN
    )
    validate_success(response, expected_status=200)
    assert get_success_data(response)["status"] == "ACTIVE"

    # Four rows of 8.33 apiece, each rounded before the sum is taken.
    after = read_investigator(investigator_id)
    assert after["committed_effort_pct"] == pytest.approx(33.32, abs=0.01)
    assert after["total_commitment_pct"] == pytest.approx(33.32, abs=0.01)
    assert after["overcommitment_pct"] == pytest.approx(0.00, abs=0.01)
    assert after["disclosure_posture"] == "CLEAR"


def test_removing_the_fourth_row_returns_committed_effort_to_24_99(api):
    """PRD §3.2: "Removing an `ACTIVE` row — `ACTIVE → REMOVED`, with `to_status` set to `REMOVED` — carries no preconditions and recomputes `committed_effort_pct`, `total_commitment_pct` and `overcommitment_pct` so that the conserved effort quantity returns to exactly its pre-activation value; it then revokes every access grant belonging to that same project and investigator whose `status` is `REQUESTED`, `ACTIVE` or `SUSPENDED`, stamping each with a `status_reason` of `PERSONNEL_REMOVED`; because grants left `ACTIVE`, the project's `active_grant_count` is recomputed and then its `controlled_area_posture`; and finally `activation_blockers` are recomputed."

    Design: Difficulty/compensating_invariant/committed_effort_percentage_returns_to_24_99_after_add_and_remove
    """
    scenario = _setup_three_active_rows_and_a_proposed_fourth()
    investigator_id = scenario["investigator"]["id"]
    fourth_row_id = scenario["fourth_row"]["id"]

    activated = api.set_personnel_status(
        fourth_row_id, {"to_status": "ACTIVE"}, ADMIN
    )
    validate_success(activated, expected_status=200)
    assert read_investigator(investigator_id)["committed_effort_pct"] == pytest.approx(
        33.32, abs=0.01
    )

    response = api.set_personnel_status(
        fourth_row_id, {"to_status": "REMOVED"}, ADMIN
    )
    validate_success(response, expected_status=200)
    assert get_success_data(response)["status"] == "REMOVED"

    # Back to the sum of three rounded 8.33 terms -- no drift to 24.98 or 25.00.
    after = read_investigator(investigator_id)
    assert after["committed_effort_pct"] == pytest.approx(24.99, abs=0.01)
    assert after["total_commitment_pct"] == pytest.approx(24.99, abs=0.01)
    assert after["overcommitment_pct"] == pytest.approx(0.00, abs=0.01)
    assert after["disclosure_posture"] == "CLEAR"

    for row in scenario["rows"]:
        assert get_success_data(api.get_personnel(row["id"], ADMIN))["status"] == "ACTIVE"
