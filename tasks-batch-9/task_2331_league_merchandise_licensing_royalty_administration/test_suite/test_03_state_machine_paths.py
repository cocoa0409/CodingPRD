"""State-machine paths that are cyclic, two-dimensional or forked.

These walk the graph rather than a single happy transition.
"""

from test_helpers import *  # noqa: F401,F403


# ---------------------------------------------------------------------------
# The two independent dimensions of a license agreement
# ---------------------------------------------------------------------------


def _suspended_agreement_on_a_probation_licensee():
    context = setup_active_agreement(
        minimum_guarantee_cents=1000000,
        required_advance_cents=250000,
        term_start_date="2026-01-01",
        term_end_date="2027-12-31",
    )
    suspend_agreement(context["agreement"]["id"], reason="Mark misuse under review")
    # Three seizures dated in the clock's quarter carry 15 points each.
    create_seizure_factors(context["licensee"]["id"], 3)
    assert get_licensee(context["licensee"]["id"])["compliance_risk_index"] == 45
    return context


def test_posture_recompute_leaves_the_contract_dimension_where_it_was(api):
    """PRD §2.9: "A transition on one dimension never implies a transition on the other:
    suspending an agreement leaves its posture exactly where it was, and a posture
    recompute never changes `contract_status`."

    Design: Difficulty/non_linear_state_machine/agreement_parallel_dimensions_move_independently
    """
    context = _suspended_agreement_on_a_probation_licensee()

    counters = quarter_close("2026Q3")
    assert counters["agreements_expired"] == 0
    assert counters["shortfalls_assessed"] == 1
    assert counters["risk_indexes_recomputed"] == 1
    assert counters["postures_changed"] == 1
    assert counters["submissions_held"] == 0
    assert counters["submissions_released"] == 0

    agreement = get_agreement(context["agreement"]["id"])
    # The posture jumped a band; the contract dimension did not move at all.
    assert agreement["compliance_posture"] == "PROBATION"
    assert agreement["posture_as_of_quarter"] == "2026Q3"
    assert agreement["contract_status"] == "SUSPENDED"
    assert agreement["suspension_reason"] == "Mark misuse under review"
    assert agreement["mg_accrued_shortfall_cents"] == 375000


def test_contract_reinstatement_leaves_the_posture_dimension_where_it_was(api):
    """PRD §3.3: "Each of these transitions increments the agreement's `version` by 1,
    and none of them ever touches `compliance_posture`."

    Design: Difficulty/non_linear_state_machine/agreement_parallel_dimensions_move_independently
    """
    context = _suspended_agreement_on_a_probation_licensee()
    quarter_close("2026Q3")

    reinstated = reinstate_agreement(context["agreement"]["id"])
    assert reinstated["contract_status"] == "ACTIVE"
    assert reinstated["suspension_reason"] is None
    assert reinstated["compliance_posture"] == "PROBATION"
    assert reinstated["posture_as_of_quarter"] == "2026Q3"


# ---------------------------------------------------------------------------
# The unbounded submission revision cycle
# ---------------------------------------------------------------------------


def _submission_after_two_revision_rounds():
    mark = create_league_mark()
    context = setup_submission_in_review(mark_ids=[mark["id"]])
    context["league_mark"] = mark
    submission_id = context["submission"]["id"]
    licensee_id = context["licensee"]["id"]

    first = submission_decision(
        submission_id, "REQUEST_REVISION", defect_codes=["MARK_PLACEMENT"]
    )
    context["after_round_one"] = first

    resubmitted = submit_submission(submission_id, licensee_id)
    context["after_resubmit"] = resubmitted
    submission_decision(submission_id, "BEGIN_REVIEW")
    second = submission_decision(submission_id, "REQUEST_REVISION", defect_codes=["TRIM_COLOR"])
    context["after_round_two"] = second
    return context


def test_each_revision_round_increments_the_counter_and_replaces_the_defect_codes(api):
    """PRD §3.5: "Requesting a revision with `REQUEST_REVISION` is permitted from
    `IN_REVIEW` and from `SAMPLE_REQUESTED`, requires at least one entry in the supplied
    `defect_codes`, increments `revision_round` by 1, and stores the supplied codes as the
    submission's `defect_codes`."

    Design: Difficulty/non_linear_state_machine/submission_revision_cycle_increments_round_counter
    """
    context = _submission_after_two_revision_rounds()

    first = context["after_round_one"]
    assert first["status"] == "REVISION_REQUESTED"
    assert first["revision_round"] == 1
    assert first["defect_codes"] == ["MARK_PLACEMENT"]

    # Re-submission clears the codes, because the licensee is presenting a corrected design.
    assert context["after_resubmit"]["status"] == "SUBMITTED"
    assert context["after_resubmit"]["defect_codes"] == []

    second = context["after_round_two"]
    assert second["status"] == "REVISION_REQUESTED"
    assert second["revision_round"] == 2
    assert second["defect_codes"] == ["TRIM_COLOR"]


def test_approval_after_two_rounds_keeps_the_round_counter_and_pins_the_snapshot(api):
    """PRD §3.5: "`approved_mark_snapshot` is pinned as one entry per mark in `mark_ids`,
    each entry recording that mark's `mark_id`, its current `mark_version` and its
    `usage_class`; `approved_by_user_id` is set to the approving manager's `X-User-ID`"

    Design: Difficulty/non_linear_state_machine/submission_revision_cycle_increments_round_counter
    """
    context = _submission_after_two_revision_rounds()
    submission_id = context["submission"]["id"]

    submit_submission(submission_id, context["licensee"]["id"])
    submission_decision(submission_id, "BEGIN_REVIEW")
    approved = submission_decision(submission_id, "APPROVE")

    assert approved["status"] == "APPROVED"
    assert approved["revision_round"] == 2
    assert approved["approved_by_user_id"] == "u_ops_1"
    assert approved["mark_snapshot_stale"] is False
    assert len(approved["approved_mark_snapshot"]) == 1
    entry = approved["approved_mark_snapshot"][0]
    assert entry["mark_id"] == context["league_mark"]["id"]
    assert entry["usage_class"] == "PRIMARY"
    assert entry["mark_version"] == context["league_mark"]["version"]

    assert get_agreement(context["agreement"]["id"])["approved_sku_count"] == 1


# ---------------------------------------------------------------------------
# An approved submission does not re-enter the review pipeline
# ---------------------------------------------------------------------------


def test_resubmitting_an_approved_design_is_refused(api):
    """PRD §2.8: "Terminal states admit no transition at all, and repeating a transition
    that has already been applied yields this error on the second attempt."

    Design: Difficulty/non_linear_state_machine/submission_cannot_resubmit_after_approval_rejected
    """
    context = setup_approved_submission()
    submission_id = context["submission"]["id"]
    licensee_id = context["licensee"]["id"]
    version_before = context["submission"]["version"]

    response = api.submit_product_submission(
        submission_id, None, make_licensee_headers(licensee_id)
    )
    validate_error(response, ApiErrorId.INVALID_STATE.value, 409)

    unchanged = get_submission(submission_id)
    assert unchanged["status"] == "APPROVED"
    assert unchanged["version"] == version_before


def test_revising_an_approved_design_is_refused(api):
    """PRD §3.5: "While a submission sits in `DRAFT` or `REVISION_REQUESTED`, its licensee
    may revise `product_name`, `retail_price_cents`, `mark_ids` and `sample_required`."

    Design: Difficulty/non_linear_state_machine/submission_cannot_resubmit_after_approval_rejected
    """
    context = setup_approved_submission()
    submission_id = context["submission"]["id"]
    licensee_id = context["licensee"]["id"]

    response = api.patch_product_submission(
        submission_id, {"product_name": "Away Replica Jersey"}, make_licensee_headers(licensee_id)
    )
    validate_error(response, ApiErrorId.INVALID_STATE.value, 409)

    unchanged = get_submission(submission_id)
    assert unchanged["status"] == "APPROVED"
    assert unchanged["product_name"] == "Home Replica Jersey"


# ---------------------------------------------------------------------------
# The sample verdict fork
# ---------------------------------------------------------------------------


def test_conditional_pass_moves_the_design_forward_without_a_risk_factor(api):
    """PRD §3.5: "A `PASS` or a `CONDITIONAL_PASS` moves the submission from
    `SAMPLE_REQUESTED` to `SAMPLE_PASSED`; a `PASS` clears `defect_codes` back to an empty
    array, while a `CONDITIONAL_PASS` stores the supplied defect codes as the submission's
    `defect_codes`. Neither adds a risk factor and neither advances the revision counter."

    Design: Difficulty/non_linear_state_machine/sample_review_fork_divergent_side_effects
    """
    context = setup_submission_awaiting_sample()
    submission_id = context["submission"]["id"]

    review = record_sample_review(
        submission_id, "CONDITIONAL_PASS", note="Tighten the trim stitching"
    )
    assert_sample_review(review)
    assert review["submission_id"] == submission_id
    assert review["verdict"] == "CONDITIONAL_PASS"
    # The submission's revision_round is still 0, so the round stamped is 1.
    assert review["sample_round"] == 1
    assert review["occurrence_quarter"] == "2026Q3"
    assert review["reviewer_user_id"] == "u_mco_1"
    assert review["conditions"] == "Tighten the trim stitching"

    submission = get_submission(submission_id)
    assert submission["status"] == "SAMPLE_PASSED"
    assert submission["revision_round"] == 0
    assert submission["defect_codes"] == []

    projection = get_risk_index(context["licensee"]["id"])
    assert projection["factor_count"] == 0
    assert projection["index"] == 0


def test_failed_sample_sends_the_design_back_and_adds_a_risk_factor(api):
    """PRD §3.5: "A `FAIL` moves the submission from `SAMPLE_REQUESTED` back to
    `REVISION_REQUESTED`, increments `revision_round` by 1, stores the supplied defect
    codes as the submission's `defect_codes`, and recomputes the licensee's rolling risk
    index as of the clock's quarter, because a failed-sample factor has just appeared."

    Design: Difficulty/non_linear_state_machine/sample_review_fork_divergent_side_effects
    """
    context = setup_submission_awaiting_sample()
    submission_id = context["submission"]["id"]

    review = record_sample_review(
        submission_id, "FAIL", defect_codes=["MARK_PLACEMENT", "TRIM_COLOR"]
    )
    assert_sample_review(review)
    assert review["sample_round"] == 1
    assert review["occurrence_quarter"] == "2026Q3"

    submission = get_submission(submission_id)
    assert submission["status"] == "REVISION_REQUESTED"
    assert submission["revision_round"] == 1
    assert submission["defect_codes"] == ["MARK_PLACEMENT", "TRIM_COLOR"]

    projection = get_risk_index(context["licensee"]["id"])
    assert projection["factor_count"] == 1
    assert projection["index"] == 8
    assert projection["posture_band"] == "CLEAR"
    assert get_licensee(context["licensee"]["id"])["compliance_risk_index"] == 8
    assert get_agreement(context["agreement"]["id"])["approved_sku_count"] == 0
