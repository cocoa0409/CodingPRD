"""Depth tests for the `non_linear_state_machine` and `transitive_cascade` rules.

Every test below translates exactly one non-stub instance of
`SCAFFOLD_DIFFICULTY_DESIGN.yaml`; the trailing `Design:` line of each docstring
names the instance it came from.
"""

from typing import Any, Dict

from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_builder_ledger,
    assert_coverage_ledger,
    assert_home_sampling_state,
    assert_index,
    assert_package_state,
    assert_rater_standing,
    assert_rating_dimensions,
    assert_sample_set_counters,
)
from test_helpers.fixtures import (
    RatingWorld,
    add_sample_member,
    assign_qa_review,
    build_confirmed_world,
    build_sample_world,
    close_sample_set,
    complete_inspection,
    complete_qa_review,
    confirm_rating,
    corrective_actions_of,
    create_home,
    create_sample_set,
    draft_package,
    get_builder,
    get_home,
    get_inspection,
    get_rater,
    get_rating,
    get_sample_set,
    get_subdivision,
    issue_package,
    list_packages,
    record_test,
    review_corrective_action,
    schedule_inspection,
    select_sample_set,
    submit_corrective_action,
)

BIG_3000 = {
    "plan_code": "BIG-3000",
    "conditioned_floor_area_sqft": 3000,
    "conditioned_volume_cuft": 27000,
    "bedrooms": 5,
    "envelope_ua_btu_per_hr_f": 520,
    "design_ach50": 4.00,
    "design_duct_leakage_cfm25_per_100sqft": 4.00,
    "hvac_efficiency_index": 8,
    "pv_capacity_kw_dc": 0,
}

PERF_2400 = {
    "plan_code": "PERF-2400",
    "conditioned_floor_area_sqft": 2400,
    "conditioned_volume_cuft": 21600,
    "bedrooms": 3,
    "envelope_ua_btu_per_hr_f": 336,
    "design_ach50": 3.00,
    "design_duct_leakage_cfm25_per_100sqft": 3.00,
    "hvac_efficiency_index": 5,
    "pv_capacity_kw_dc": 0,
}

LOW_2200 = {
    "plan_code": "LOW-2200",
    "conditioned_floor_area_sqft": 2200,
    "conditioned_volume_cuft": 19800,
    "bedrooms": 3,
    "envelope_ua_btu_per_hr_f": 290,
    "design_ach50": 2.50,
    "design_duct_leakage_cfm25_per_100sqft": 2.50,
    "hvac_efficiency_index": 10,
    "pv_capacity_kw_dc": 0,
}


def _final_checkpoint(
    api: ApiClient,
    rating_id: str,
    inspector_id: str,
    blower_door: float,
    duct_leakage: float,
    *,
    scheduled_start_utc: str = "2026-08-20T09:00:00Z",
    scheduled_end_utc: str = "2026-08-20T11:00:00Z",
) -> Dict[str, Any]:
    inspection = schedule_inspection(
        api,
        rating_id,
        inspector_id,
        checkpoint="FINAL",
        scheduled_start_utc=scheduled_start_utc,
        scheduled_end_utc=scheduled_end_utc,
        air_handler_installed=True,
    )
    record_test(api, inspection["id"], inspector_id, "BLOWER_DOOR", blower_door)
    record_test(api, inspection["id"], inspector_id, "DUCT_LEAKAGE_TOTAL", duct_leakage)
    return complete_inspection(api, inspection["id"], inspector_id)


def _cedar_run_confirmed(api: ApiClient, *, blower_door: float, duct_leakage: float):
    """Three-plan Cedar Run set whose tested home L-1 has been confirmed."""
    world = build_sample_world(
        api,
        member_count=3,
        builder_name="Meridian Homes",
        subdivision_name="Cedar Run",
        utility_program_budget_cents=500000,
        lot_numbers=["L-1", "L-2", "L-3"],
        permit_dates=["2026-08-05", "2026-08-06", "2026-08-07"],
        plan_overrides_per_home=[BIG_3000, PERF_2400, LOW_2200],
        window_start_date="2026-08-01",
        window_end_date="2026-08-31",
    )
    world.sample_set = select_sample_set(api, world.sample_set_id)
    _final_checkpoint(
        api, world.ratings[0]["id"], world.inspector_id, blower_door, duct_leakage
    )
    confirm_rating(api, world.ratings[0]["id"], world.rater_id)
    return world


def _escalation_world(api: ApiClient) -> RatingWorld:
    """A confirmed but FAILING rating whose THRESHOLD_FAILURE action is open."""
    return build_confirmed_world(
        api,
        builder_name="Ridgeline Homes",
        subdivision_name="Thornbury",
        lot_number="L-88",
        blower_door=1200,
        duct_leakage=96,
    )


def _reject_cycle(api: ApiClient, action_id: str, builder_id: str, rounds: int) -> Dict[str, Any]:
    """Run `rounds` submit-then-reject passes over one corrective action."""
    action = {}
    for _ in range(rounds):
        submit_corrective_action(api, action_id, builder_id)
        action = review_corrective_action(api, action_id, "REJECT")
    return action


# ======================================================= non_linear_state_machine
def test_failed_checkpoint_still_advances_the_stage_dimension(api: ApiClient) -> None:
    """A FAILED FINAL checkpoint does not block confirmation: the stage dimension
    reaches `CONFIRMED` while the compliance dimension lands on `FAILING`.

    PRD §3.2: "It carries four dimensions simultaneously and they advance independently of one another."

    Design: Difficulty/non_linear_state_machine/rating_parallel_dimensions_stage_and_compliance_independent
    """
    world = _escalation_world(api)
    inspection = get_inspection(api, world.inspection_id)
    assert inspection["status"] == "FAILED", inspection
    assert inspection["failed_test_count"] == 1, inspection
    rating = get_rating(api, world.rating_id)
    assert_index(rating["confirmed_index"], 46)
    assert rating["compliance_path"] == "NONE", rating
    assert_rating_dimensions(rating, stage="CONFIRMED", compliance_status="FAILING")


def test_qa_assignment_moves_only_the_quality_assurance_dimension(api: ApiClient) -> None:
    """Assigning a review advances `qa_status` alone and leaves the stage,
    compliance and registry dimensions exactly where they stood.

    PRD §3.6: "A successful assignment creates the review with `status` of `ASSIGNED`, a null `result` and a null `findings_note`, and moves the rating's `qa_status` from `NOT_SELECTED` to `QA_SELECTED`."

    Design: Difficulty/non_linear_state_machine/rating_parallel_dimensions_stage_and_compliance_independent
    """
    world = _escalation_world(api)
    review = assign_qa_review(api, world.rating_id, world.qa_designee_id)
    assert review["status"] == "ASSIGNED", review
    assert review["result"] is None, review
    rating = get_rating(api, world.rating_id)
    assert_rating_dimensions(
        rating,
        stage="CONFIRMED",
        compliance_status="FAILING",
        qa_status="QA_SELECTED",
        registry_status="NOT_SUBMITTED",
    )


def test_two_rejections_return_the_action_to_rejected_and_loop(api: ApiClient) -> None:
    """With `attempt_count` at one and then two, each rejection lands on `REJECTED`
    and the builder is free to submit again.

    PRD §3.7: "When `attempt_count` is less than three, the action's `status` becomes `REJECTED` and the builder may submit again, giving the cycle submitted → rejected → submitted."

    Design: Difficulty/non_linear_state_machine/corrective_action_reject_resubmit_cycle_reaches_escalated
    """
    world = _escalation_world(api)
    (action,) = corrective_actions_of(api, world.rating_id)
    assert action["reason"] == "THRESHOLD_FAILURE", action
    assert action["status"] == "OPEN", action
    after_two = _reject_cycle(api, action["id"], world.builder_id, rounds=2)
    assert after_two["status"] == "REJECTED", after_two
    assert after_two["attempt_count"] == 2, after_two
    assert_builder_ledger(get_builder(api, world.builder_id), status="ACTIVE")


def test_third_rejection_escalates_and_suspends_the_builder(api: ApiClient) -> None:
    """The rejection that lands on attempt three does not loop: the action becomes
    terminal `ESCALATED`, stays counted as open and suspends the builder.

    PRD §3.7: "When the rejection lands on the third attempt — `attempt_count` standing at exactly three — the action does not loop again: its `status` becomes `ESCALATED`, which is terminal, it continues to be counted as open so the builder stays sampling-ineligible, and the builder's `status` is set to `SAMPLING_SUSPENDED`."

    Design: Difficulty/non_linear_state_machine/corrective_action_reject_resubmit_cycle_reaches_escalated
    """
    world = _escalation_world(api)
    (action,) = corrective_actions_of(api, world.rating_id)
    escalated = _reject_cycle(api, action["id"], world.builder_id, rounds=3)
    assert escalated["status"] == "ESCALATED", escalated
    assert escalated["attempt_count"] == 3, escalated
    assert_builder_ledger(
        get_builder(api, world.builder_id),
        status="SAMPLING_SUSPENDED",
        sampling_eligible=False,
        open_corrective_action_count=1,
    )
    assert_rating_dimensions(
        get_rating(api, world.rating_id), stage="CONFIRMED", compliance_status="FAILING"
    )


# ============================================================ transitive_cascade
def test_major_qa_failure_revokes_the_package_and_reverses_the_ledger(
    api: ApiClient,
) -> None:
    """A `FAIL_MAJOR` review revokes the issued package with `QA_MAJOR_FAILURE` and
    takes the 100,000 certified cents back off the builder's ledger.

    PRD §3.6: "Hop two: each such revocation lowers the builder's `certified_incentive_cents` by that package's `certified_amount_cents` and raises the builder's `revoked_package_count` by one."

    Design: Difficulty/transitive_cascade/qa_major_failure_cascade_revokes_package_and_suspends_sampling
    """
    world = build_confirmed_world(
        api,
        builder_name="Kestrel Homes",
        subdivision_name="Windrow",
        sampling_enabled=True,
        utility_program_budget_cents=500000,
        lot_number="L-401",
        blower_door=1080,
        duct_leakage=96,
    )
    package = draft_package(api, world.rating_id, world.builder_id, "TAX_CREDIT_45L")
    package = issue_package(api, package["id"])
    assert_builder_ledger(
        get_builder(api, world.builder_id), certified_incentive_cents=100000
    )

    review = assign_qa_review(api, world.rating_id, world.qa_designee_id)
    complete_qa_review(
        api,
        review["id"],
        world.qa_designee_id,
        "FAIL_MAJOR",
        findings_note="Duct leakage worksheet does not match the recorded readings",
    )

    assert_rating_dimensions(get_rating(api, world.rating_id), qa_status="QA_FAILED")
    (revoked,) = list_packages(api, world.rating_id)
    assert_package_state(
        revoked,
        status="REVOKED",
        revocation_reason="QA_MAJOR_FAILURE",
        certified_amount_cents=100000,
    )
    assert_builder_ledger(
        get_builder(api, world.builder_id),
        certified_incentive_cents=0,
        revoked_package_count=1,
    )


def test_major_qa_failure_suspends_sampling_and_voids_the_open_set(
    api: ApiClient,
) -> None:
    """Losing eligibility voids the builder's live sample set, releases its members
    into individual testing and rebalances the subdivision's coverage ledger.

    PRD §3.6: "Hop four: because the builder is no longer sampling-eligible, every sample set belonging to any of that builder's subdivisions whose `status` is `FORMING`, `SELECTED` or `TESTED` transitions to `VOIDED_SAMPLING`."

    Design: Difficulty/transitive_cascade/qa_major_failure_cascade_revokes_package_and_suspends_sampling
    """
    world = build_confirmed_world(
        api,
        builder_name="Kestrel Homes",
        subdivision_name="Windrow",
        sampling_enabled=True,
        utility_program_budget_cents=500000,
        lot_number="L-401",
        blower_door=1080,
        duct_leakage=96,
    )
    package = draft_package(api, world.rating_id, world.builder_id, "TAX_CREDIT_45L")
    issue_package(api, package["id"])

    home_b = create_home(
        api,
        world.subdivision_id,
        world.plan_model_id,
        world.builder_id,
        lot_number="L-402",
        permit_date="2026-08-04",
    )
    home_c = create_home(
        api,
        world.subdivision_id,
        world.plan_model_id,
        world.builder_id,
        lot_number="L-403",
        permit_date="2026-08-05",
    )
    sample_set = create_sample_set(api, world.subdivision_id, world.rater_id)
    add_sample_member(api, sample_set["id"], home_b["id"], world.rater_id)
    add_sample_member(api, sample_set["id"], home_c["id"], world.rater_id)

    review = assign_qa_review(api, world.rating_id, world.qa_designee_id)
    complete_qa_review(
        api,
        review["id"],
        world.qa_designee_id,
        "FAIL_MAJOR",
        findings_note="Duct leakage worksheet does not match the recorded readings",
    )

    assert_builder_ledger(
        get_builder(api, world.builder_id),
        status="SAMPLING_SUSPENDED",
        sampling_eligible=False,
    )
    voided = get_sample_set(api, sample_set["id"])
    assert_sample_set_counters(
        voided,
        status="VOIDED_SAMPLING",
        member_count=0,
        tested_member_count=0,
        represented_member_count=0,
        tested_home_id=None,
        representative_index=None,
    )
    for home in (home_b, home_c):
        assert_home_sampling_state(
            get_home(api, home["id"]),
            sampling_role="UNASSIGNED",
            sample_set_id=None,
            individual_testing_required=True,
        )
    assert_coverage_ledger(
        get_subdivision(api, world.subdivision_id),
        homes_count=3,
        sampled_home_count=0,
        unsampled_home_count=3,
    )
    assert_rater_standing(
        get_rater(api, world.rater_id), certification_status="PROBATION", qa_failure_count=1
    )


def test_failing_closure_expands_the_set_and_regresses_sibling_ratings(
    api: ApiClient,
) -> None:
    """The tested home confirms at 62 and fails, so the set becomes
    `FAILED_EXPANDED`, keeps a null representative index, and both siblings lose
    the confirmed index they would otherwise have inherited.

    PRD §3.5: "Second, each of those homes' existing ratings has its `confirmed_index` cleared to null and its `compliance_status` set to `FAILING`, which for a rating that had been `PASSING` is a genuine regression of the compliance dimension and also resets its `compliance_path` to `NONE`."

    Design: Difficulty/transitive_cascade/sample_set_failure_cascade_creates_corrective_actions_and_suspends_builder
    """
    world = _cedar_run_confirmed(api, blower_door=1620, duct_leakage=150)
    assert_index(get_rating(api, world.ratings[0]["id"])["confirmed_index"], 62)
    closed = close_sample_set(api, world.sample_set_id)
    assert_sample_set_counters(
        closed, status="FAILED_EXPANDED", representative_index=None
    )
    for index in (1, 2):
        assert_home_sampling_state(
            get_home(api, world.homes[index]["id"]),
            sampling_role="REPRESENTED",
            individual_testing_required=True,
        )
        sibling = get_rating(api, world.ratings[index]["id"])
        assert sibling["confirmed_index"] is None, sibling
        assert sibling["compliance_path"] == "NONE", sibling
        assert_rating_dimensions(sibling, compliance_status="FAILING")


def test_failing_closure_opens_sample_failure_actions_and_suspends_the_builder(
    api: ApiClient,
) -> None:
    """Each regressed sibling receives its own `SAMPLE_SET_FAILURE` action, lifting
    the builder's open count to three alongside the tested home's own failure.

    PRD §3.5: "Third, each of those newly failing ratings receives a corrective action with `reason` of `SAMPLE_SET_FAILURE` and `status` of `OPEN`."

    Design: Difficulty/transitive_cascade/sample_set_failure_cascade_creates_corrective_actions_and_suspends_builder
    """
    world = _cedar_run_confirmed(api, blower_door=1620, duct_leakage=150)
    close_sample_set(api, world.sample_set_id)
    for index in (1, 2):
        (action,) = corrective_actions_of(api, world.ratings[index]["id"])
        assert action["reason"] == "SAMPLE_SET_FAILURE", action
        assert action["status"] == "OPEN", action
    assert_builder_ledger(
        get_builder(api, world.builder_id),
        open_corrective_action_count=3,
        status="SAMPLING_SUSPENDED",
        sampling_eligible=False,
    )
