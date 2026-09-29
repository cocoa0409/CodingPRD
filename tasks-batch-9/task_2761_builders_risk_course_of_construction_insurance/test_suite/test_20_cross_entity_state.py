"""The write target is one entity; the state that gates the write lives on another."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import api_client
from test_helpers import fixtures as fx
from test_helpers.factories import (
    create_policy_payload,
    create_storage_assignment_payload,
)

INELIGIBLE_PROJECT = {
    "name": "Ninth Street Timber Lofts",
    "site_address": "9 Ninth St, Rockvale",
    "construction_type": "FRAME",
    "project_kind": "NEW_CONSTRUCTION",
    "hard_cost_value_cents": 900000000,
    "cat_zone": "WIND_TIER_2",
    "planned_start_date": "2026-09-01T00:00:00Z",
    "projected_completion_date": "2027-05-01T00:00:00Z",
}


def _draft_attempt(project, **overrides):
    payload = create_policy_payload(
        project["id"], project["version"], **overrides)
    return api_client.create_policy(payload, fx.UW)


def test_a_draft_is_refused_until_screening_makes_the_project_eligible():
    """An unscreened project cannot receive a draft even when the parent-version
    declaration is correct, and neither can a project screened out as INELIGIBLE
    — whose submission score is nevertheless on file. Screening the first project
    to grade B flips the same request to a created DRAFT.

    Design: Difficulty/cross_entity_state_dependency/policy_creation_requires_eligible_project_and_rejects_every_other_project_state
    """
    unscreened = fx.submit_project()
    assert unscreened["status"] == "SUBMITTED", unscreened

    ineligible = fx.screen_project(
        fx.submit_project(**INELIGIBLE_PROJECT), engineering_grade="D")
    assert ineligible["status"] == "INELIGIBLE", ineligible
    assert ineligible["submission_risk_score"] is not None, ineligible

    while_submitted = _draft_attempt(unscreened)
    validate_error(while_submitted, "ERR_INVALID_PROJECT_STATE", expected_status=409)

    while_ineligible = _draft_attempt(
        ineligible, term_end_date="2027-05-31T00:00:00Z",
        deductible_tier="STANDARD_25K", limit_cents=1000000000,
        daily_delay_rate_cents=0)
    validate_error(while_ineligible, "ERR_INVALID_PROJECT_STATE", expected_status=409)

    eligible = fx.screen_project(unscreened, engineering_grade="B")
    assert eligible["status"] == "ELIGIBLE", eligible
    policy = get_success_data(_draft_attempt(eligible), expected_status=201)
    assert policy["status"] == "DRAFT", policy


def test_inception_closes_the_project_to_further_drafts():
    """The gate is an equality against ELIGIBLE, not merely "screened": once
    inception has moved the project to UNDER_CONSTRUCTION a second draft is
    refused, so the project keeps exactly the one policy it took in force.

    Design: Difficulty/cross_entity_state_dependency/policy_creation_requires_eligible_project_and_rejects_every_other_project_state
    """
    account = fx.in_force_account()
    project = account.refresh_project()
    assert project["status"] == "UNDER_CONSTRUCTION", project
    assert project["in_force_policy_count"] == 1, project

    while_under_construction = _draft_attempt(
        project, term_start_date="2026-10-01T00:00:00Z",
        term_end_date="2027-07-31T00:00:00Z")
    validate_error(while_under_construction, "ERR_INVALID_PROJECT_STATE",
                   expected_status=409)

    rows, _meta = validate_paginated(api_client.list_project_policies(
        project["id"], fx.UW, params={"limit": 100}))
    assert len(rows) == 1, f"the refused draft must not exist: {rows}"
    assert rows[0]["id"] == account.policy_id, rows


STORAGE_PART_PLAN = (
    ("TEMPORARY_STORAGE", 400000000),
    ("MATERIALS_ON_SITE", 1000000000),
)

SECOND_WINDOW = ("2026-12-05T00:00:00Z", "2027-01-05T00:00:00Z")


def _account_with_committed_facility():
    """500000000 of capacity, 300000000 already committed, no window clash ahead."""
    account = fx.in_force_account(parts=STORAGE_PART_PLAN)
    facility = fx.register_facility(
        name="Northgate Bonded Warehouse", site_code="STG-NORTH-07",
        distance_from_site_miles=42.5, aggregate_capacity_cents=500000000,
        protection_class="SPRINKLERED")
    assert facility["status"] == "ACTIVE", facility
    first = fx.assign_storage(
        account, facility, 300000000, "2026-10-01T00:00:00Z", "2026-12-01T00:00:00Z")
    assert first["status"] == "APPROVED", first
    return account, facility, first


def _second_assignment(account, facility):
    payload = create_storage_assignment_payload(
        account.policy_id, facility["id"], 100000000, *SECOND_WINDOW)
    return api_client.create_storage_assignment(payload, fx.UW)


def test_a_suspended_facility_refuses_new_commitments_but_keeps_the_old_ones():
    """Suspension is a state gate and not a capacity one: the request is refused
    with ERR_FACILITY_SUSPENDED although 200000000 of headroom remains and the
    proposed window overlaps nothing. The assignment already APPROVED against the
    facility is untouched, so its committed value survives the suspension.

    Design: Difficulty/cross_entity_state_dependency/storage_assignment_requires_active_facility_and_rejects_suspended_one
    """
    account, facility, first = _account_with_committed_facility()

    suspended = fx.suspend_facility(facility)
    assert suspended["status"] == "SUSPENDED", suspended
    assert suspended["committed_value_cents"] == 300000000, suspended

    refused = _second_assignment(account, facility)
    validate_error(refused, "ERR_FACILITY_SUSPENDED", expected_status=409)

    held = get_success_data(api_client.get_storage_assignment(first["id"], fx.UW))
    assert held["status"] == "APPROVED", held


def test_reactivating_the_facility_admits_the_identical_commitment():
    """The facility's state cycles rather than advancing, so reinstatement lets
    the identical request through. committed_value_cents is the plain sum over
    APPROVED assignments, 400000000, even though the capacity test never saw a
    peak overlap above 300000000.

    Design: Difficulty/cross_entity_state_dependency/storage_assignment_requires_active_facility_and_rejects_suspended_one
    """
    account, facility, _first = _account_with_committed_facility()
    fx.suspend_facility(facility)
    _second_assignment(account, facility)

    reactivated = fx.reinstate_facility(facility)
    assert reactivated["status"] == "ACTIVE", reactivated

    second = get_success_data(
        _second_assignment(account, facility), expected_status=201)
    assert second["status"] == "APPROVED", second

    final = get_success_data(api_client.get_facility(facility["id"], fx.RE))
    assert final["committed_value_cents"] == 400000000, final

    rows, _meta = validate_paginated(api_client.list_facility_storage_assignments(
        facility["id"], fx.RE, params={"limit": 100}))
    assert len(rows) == 2, f"the refused commitment must not exist: {rows}"


TESTING_PART_PLAN = (
    ("TESTING_COMMISSIONING", 150000000),
    ("MATERIALS_ON_SITE", 1000000000),
)

TESTING_ITEMS = [{"part_type": "TESTING_COMMISSIONING", "gross_loss_cents": 30000000}]
OUTSIDE_ITEMS = [{"part_type": "TESTING_COMMISSIONING", "gross_loss_cents": 8000000}]


def _account_with_scheduled_notice():
    """One notice left SCHEDULED, one claim inside its window and one outside."""
    account = fx.in_force_account(parts=TESTING_PART_PLAN)
    notice = fx.schedule_notice(
        account, "2027-03-01T08:00:00Z", "2027-03-01T17:00:00Z",
        system_type="SPRINKLER_HYDROSTATIC", water_charged=True, hot_work=False)
    assert notice["status"] == "SCHEDULED", notice
    inside = fx.report_claim(
        account, peril="TESTING_FAILURE", loss_date="2027-03-01T12:00:00Z",
        description="Sprinkler charge failure during hydrostatic test")
    outside = fx.report_claim(
        account, peril="TESTING_FAILURE", loss_date="2027-03-05T12:00:00Z",
        description="Second failure four days after the notified window")
    return account, notice, inside, outside


def _adjust(claim, loss_items):
    return api_client.adjust_claim(claim["id"], {
        "outcome": "ADJUST",
        "adjustment_basis": "ACTUAL_LOSS",
        "loss_items": loss_items,
    }, fx.CA)


def test_a_merely_scheduled_notice_does_not_unlock_testing_cover():
    """The coverage condition on the TESTING_COMMISSIONING bucket needs an
    APPROVED notice, so a notice still sitting in SCHEDULED refuses the
    allocation with ERR_TESTING_NOTICE_REQUIRED and leaves the claim untouched.

    Design: Difficulty/cross_entity_state_dependency/testing_commissioning_allocation_requires_approved_notice_covering_the_loss_date
    """
    _account, _notice, inside, _outside = _account_with_scheduled_notice()

    refused = _adjust(inside, TESTING_ITEMS)
    validate_error(refused, "ERR_TESTING_NOTICE_REQUIRED", expected_status=422)

    untouched = get_success_data(api_client.get_claim(inside["id"], fx.CA))
    assert untouched["adjustment_status"] == "REPORTED", untouched
    assert untouched["indemnity_cents"] == 0, untouched


def test_the_approved_notice_is_matched_per_claim_against_its_own_loss_date():
    """Approving the notice lets the identical adjustment through — 30000000 less
    the 10000000 occurrence deductible — while a second claim four days past the
    notified window is still refused, so the notice is matched to each claim's
    loss_date rather than to the policy. Adjustment reserves without eroding.

    Design: Difficulty/cross_entity_state_dependency/testing_commissioning_allocation_requires_approved_notice_covering_the_loss_date
    """
    account, notice, inside, outside = _account_with_scheduled_notice()
    _adjust(inside, TESTING_ITEMS)

    approved = fx.decide_notice(notice, "APPROVE")
    assert approved["status"] == "APPROVED", approved

    adjusted = get_success_data(_adjust(inside, TESTING_ITEMS))
    assert adjusted["indemnity_cents"] == 20000000, adjusted
    assert adjusted["uncovered_cents"] == 10000000, adjusted
    assert adjusted["adjustment_status"] == "ADJUSTED", adjusted

    out_of_window = _adjust(outside, OUTSIDE_ITEMS)
    validate_error(out_of_window, "ERR_TESTING_NOTICE_REQUIRED", expected_status=422)

    still_reported = get_success_data(api_client.get_claim(outside["id"], fx.CA))
    assert still_reported["adjustment_status"] == "REPORTED", still_reported
    assert still_reported["indemnity_cents"] == 0, still_reported

    part = account.refresh_parts()["TESTING_COMMISSIONING"]
    assert part["eroded_cents"] == 0, part
