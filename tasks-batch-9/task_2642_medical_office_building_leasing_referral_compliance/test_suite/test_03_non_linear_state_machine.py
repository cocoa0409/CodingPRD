"""The bounded review cycle on a lease and the fork-join on a tenant-improvement project."""
from test_helpers import ApiErrorId, validate_error
from test_helpers import fixtures as fx
from test_helpers import factories as f
from test_helpers.test_users import COMPLIANCE_OFFICER, FACILITIES_ENGINEER


def _lease_in_review(api):
    """A DIRECT lease at the rate card, submitted once and sitting in review."""
    ctx = fx.drafted_lease(api)
    ctx["lease"] = fx.submit_for_review(api, ctx["lease"]["id"], "First pass")
    return ctx


def test_each_return_for_revision_sends_the_lease_back_and_counts_a_round(api):
    """Two full returns are traversable, each incrementing the round counter by one.

    PRD: "The `RETURN_FOR_REVISION` action sends a lease in review back to the agent,
    `PENDING_FMV_REVIEW → DRAFT`, incrementing `revision_round` by 1, resetting
    `fmv_certification_status` to `NOT_STARTED`, clearing `fmv_submitted_by_user_id` to null
    and advancing `version`."

    Design: Difficulty/non_linear_state_machine/lease_revision_cycle_bounded_at_two_rounds
    """
    ctx = _lease_in_review(api)
    lease_id = ctx["lease"]["id"]
    assert ctx["lease"]["status"] == "PENDING_FMV_REVIEW"
    assert ctx["lease"]["revision_round"] == 0

    first_return = fx.return_for_revision(api, lease_id,
                                          "Attach the CAM reconciliation exhibit")
    assert first_return["status"] == "DRAFT"
    assert first_return["revision_round"] == 1
    assert first_return["fmv_certification_status"] == "NOT_STARTED"
    assert first_return["fmv_submitted_by_user_id"] is None

    resubmitted = fx.submit_for_review(api, lease_id, "Exhibit attached")
    assert resubmitted["status"] == "PENDING_FMV_REVIEW"
    assert resubmitted["revision_round"] == 1

    second_return = fx.return_for_revision(api, lease_id,
                                           "Exhibit references the wrong suite")
    assert second_return["status"] == "DRAFT"
    assert second_return["revision_round"] == 2

    third_submission = fx.submit_for_review(api, lease_id, "Suite reference corrected")
    assert third_submission["status"] == "PENDING_FMV_REVIEW"
    assert third_submission["revision_round"] == 2


def test_a_third_return_for_revision_is_refused_and_leaves_the_lease_in_review(api):
    """The cycle bound is observable only by walking it to exhaustion.

    PRD: "It is admissible only while `revision_round` is at most 1, so at most three review
    submissions can ever occur on one lease; a fourth attempt is refused with
    `ERR_REVISION_LIMIT_EXCEEDED`."

    Design: Difficulty/non_linear_state_machine/lease_revision_cycle_bounded_at_two_rounds
    """
    ctx = _lease_in_review(api)
    lease_id = ctx["lease"]["id"]

    fx.return_for_revision(api, lease_id, "Attach the CAM reconciliation exhibit")
    fx.submit_for_review(api, lease_id, "Exhibit attached")
    fx.return_for_revision(api, lease_id, "Exhibit references the wrong suite")
    fx.submit_for_review(api, lease_id, "Suite reference corrected")

    refused = api.lease_compliance_decision(
        lease_id, f.lease_compliance_decision_payload("RETURN_FOR_REVISION",
                                                      "Third bite at the apple"),
        COMPLIANCE_OFFICER)
    validate_error(refused, ApiErrorId.ERR_REVISION_LIMIT_EXCEEDED)

    lease = fx.read_lease(api, lease_id)
    assert lease["status"] == "PENDING_FMV_REVIEW"
    assert lease["revision_round"] == 2


def _imaging_project_in_review(api):
    """An imaging build-out submitted for both reviews on a 200-amp uncertified suite."""
    ctx = fx.drafted_lease(api)
    project = fx.open_ti_project(api, ctx["lease"]["id"], ctx["suite"]["id"],
                                target_suite_class="IMAGING", lead_thickness_mm=2.5,
                                power_amps_requested=150, medical_gas_requested=False,
                                authorized_allowance_total=500000.00,
                                landlord_share_pct=0.6000)
    fx.add_line_item(api, project["id"], project["version"],
                     description="Lead shielding, walls and ceiling",
                     category="SHIELDING", cost_amount=88000.00)
    ctx["project"] = fx.ti_transition(api, project["id"], "SUBMIT_REVIEWS",
                                      "Shielding and utility packages issued")
    return ctx


def test_submit_reviews_sets_both_dimensions_pending_in_the_same_transition(api):
    """The fork point puts both review dimensions in play at once.

    PRD: "It then sets **both** `shielding_review_status` and `utility_review_status` to
    `PENDING` in the same transition and advances `version`."

    Design: Difficulty/non_linear_state_machine/ti_project_fork_join_permits_only_after_both_reviews_approved
    """
    ctx = _imaging_project_in_review(api)
    project = ctx["project"]

    assert project["status"] == "IN_REVIEW"
    assert project["shielding_review_status"] == "PENDING"
    assert project["utility_review_status"] == "PENDING"


def test_the_two_review_branches_have_strictly_disjoint_effects_and_join_on_the_second(api):
    """Shielding stamps the suite flag, utility alone deducts the amps, and the join permits.

    PRD: "The two effect sets are strictly disjoint: the shielding branch touches
    `shielding_certified` and `lead_thickness_mm` and never electrical capacity, and the
    utility branch touches `power_amps_available` and never shielding."

    Design: Difficulty/non_linear_state_machine/ti_project_fork_join_permits_only_after_both_reviews_approved
    """
    ctx = _imaging_project_in_review(api)
    project_id = ctx["project"]["id"]
    suite_id = ctx["suite"]["id"]

    after_shielding = fx.ti_review(api, project_id, "SHIELDING", "APPROVE",
                                   lead_thickness_verified_mm=2.5,
                                   review_note="Physicist sign-off on file")
    assert after_shielding["status"] == "IN_REVIEW"
    assert after_shielding["shielding_review_status"] == "APPROVED"
    assert after_shielding["utility_review_status"] == "PENDING"

    suite = fx.read_suite(api, suite_id, FACILITIES_ENGINEER)
    assert suite["shielding_certified"] is True
    assert suite["lead_thickness_mm"] == 2.5
    assert suite["power_amps_available"] == 200, "the shielding branch never moves the amps"

    after_utility = fx.ti_review(api, project_id, "UTILITY", "APPROVE",
                                 review_note="Feeder capacity confirmed")
    assert after_utility["status"] == "PERMITTED"
    assert after_utility["utility_review_status"] == "APPROVED"
    assert after_utility["power_amps_drawn"] == 150

    suite = fx.read_suite(api, suite_id, FACILITIES_ENGINEER)
    assert suite["power_amps_available"] == 50
    assert suite["suite_class"] == "STANDARD_EXAM", "reclassification waits for close-out"
