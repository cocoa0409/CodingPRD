"""Non-linear lifecycle paths.

Covers the re-entrant engagement-quality-review concern negotiation with its
cross-entity revert onto the engagement, and the peer review's report-issuance
fork whose branches carry different side-effect sets.
"""
from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_errors import ERR_CORRECTIVE_ACTION_OUTSTANDING
from test_helpers.assertions import assert_fields, read_entity
from test_helpers.test_users import (
    make_committee_headers,
    make_eq_reviewer_headers,
    make_peer_reviewer_headers,
)

_ROUND_ONE_SUMMARY = "Round one: impairment model inputs are not corroborated."
_ROUND_TWO_SUMMARY = (
    "Round two: revised disclosure still omits the sensitivity analysis."
)


# ---------------------------------------------------------------------------
# non_linear_state_machine / eqr_concern_cycle_reverts_engagement_and_counts_rounds
# ---------------------------------------------------------------------------
def _eqr_step(api, eqr_id, to_state, headers, **extra):
    return read_entity(
        api.create_quality_review_transition(
            eqr_id, f.quality_review_transition_payload(to_state, **extra),
            headers=headers,
        ),
        expected_status=200,
    )


def _two_concern_rounds_then_concurrence(api):
    """Drive a public-interest engagement through two full concern rounds, concurrence
    and the clearing leg, recording the state after the first revert."""
    ctx = fixtures.firm_context(api, legal_name="Ilkwood Bay LLP")
    reviewer = fixtures.add_eq_reviewer(api, ctx, full_name="Sable Ord")
    ep_headers = ctx["ep_headers"]

    engagement = fixtures.new_engagement(
        api, ctx, partner=ctx["ep"], client_name="Cinder Utilities",
        engagement_type="AUDIT", period_end="2026-06-30", is_public_interest=True,
    )
    in_fieldwork = fixtures.workflow_step(api, engagement, "FIELDWORK", ep_headers)
    eqr = read_entity(
        api.assign_quality_review(
            engagement["id"],
            f.quality_review_assignment_payload(
                reviewer["id"], in_fieldwork["version"]
            ),
            headers=ctx["qc_headers"],
        ),
        expected_status=201,
    )
    fixtures.workflow_step(api, engagement, "EQR_PENDING", ep_headers)

    reviewer_headers = make_eq_reviewer_headers(reviewer["id"])
    _eqr_step(api, eqr["id"], "IN_PROGRESS", reviewer_headers)
    _eqr_step(
        api, eqr["id"], "CONCERNS_RAISED", reviewer_headers,
        concern_summary=_ROUND_ONE_SUMMARY,
    )
    after_first_revert = fixtures.read_engagement(
        api, engagement["id"], ep_headers
    )
    fixtures.workflow_step(api, engagement, "EQR_PENDING", ep_headers)
    _eqr_step(api, eqr["id"], "IN_PROGRESS", reviewer_headers)
    _eqr_step(
        api, eqr["id"], "CONCERNS_RAISED", reviewer_headers,
        concern_summary=_ROUND_TWO_SUMMARY,
    )
    fixtures.workflow_step(api, engagement, "EQR_PENDING", ep_headers)
    _eqr_step(api, eqr["id"], "IN_PROGRESS", reviewer_headers)
    concurred = _eqr_step(api, eqr["id"], "CONCURRED", reviewer_headers)
    cleared = fixtures.workflow_step(api, engagement, "EQR_CLEARED", ep_headers)

    return {
        "ctx": ctx,
        "reviewer": reviewer,
        "engagement": engagement,
        "after_first_revert": after_first_revert,
        "concurred": concurred,
        "cleared": cleared,
    }


def test_eqr_concern_rounds_are_counted_and_the_review_still_reaches_concurrence(api):
    """Two IN_PROGRESS -> CONCERNS_RAISED -> IN_PROGRESS rounds leave concern_round_count
    at exactly 2, the latest summary retained, and the review terminally CONCURRED.

    "Rounds repeat as often as the negotiation requires, and `concern_round_count`
    records how many there were."

    Design: Difficulty/non_linear_state_machine/eqr_concern_cycle_reverts_engagement_and_counts_rounds
    """
    result = _two_concern_rounds_then_concurrence(api)
    concurred = result["concurred"]

    assert_fields(
        concurred,
        state="CONCURRED",
        concern_round_count=2,
        last_concern_summary=_ROUND_TWO_SUMMARY,
    )
    assert concurred["concluded_at"] is not None, (
        "concurrence must stamp concluded_at from the logical clock"
    )
    # Each round drags the engagement backwards and nulls its concurrence stamp.
    assert_fields(
        result["after_first_revert"], workflow_state="FIELDWORK", eqr_concurred_at=None
    )


def test_eqr_negotiation_leaves_the_engagement_cleared_and_the_reviewer_free(api):
    """Clearing quality review after the negotiation stamps eqr_concurred_at on an
    engagement that still requires a review, and recomputes open_eqr_count to 0.

    "Concurrence stamps `concluded_at` with the logical-clock instant - closing the
    reviewer's capacity interval - and recomputes the reviewer's `open_eqr_count`,
    which decreases by one."

    Design: Difficulty/non_linear_state_machine/eqr_concern_cycle_reverts_engagement_and_counts_rounds
    """
    result = _two_concern_rounds_then_concurrence(api)
    ctx = result["ctx"]
    cleared = result["cleared"]

    assert_fields(
        cleared, workflow_state="EQR_CLEARED", eqr_required=True, reopened_count=0
    )
    assert cleared["eqr_concurred_at"] is not None, (
        "the clearing leg must copy the concurring review's concluded_at instant"
    )
    assert_fields(
        read_entity(
            api.get_partner(result["reviewer"]["id"], headers=ctx["qc_headers"])
        ),
        open_eqr_count=0,
    )


# ---------------------------------------------------------------------------
# non_linear_state_machine / peer_review_report_issued_fork_fail_branch_side_effect_set
# ---------------------------------------------------------------------------
def _failing_peer_review_at_rating_drafted(api):
    """A peer review rated FAIL and sitting in RATING_DRAFTED, over a firm whose latest
    internal inspection cycle has already CONCLUDED."""
    ctx = fixtures.firm_context(api, legal_name="Jarrow Lint LLP")
    engagement = fixtures.released_engagement(
        api, ctx, partner=ctx["ep"], client_name="Alder Foods",
        engagement_type="AUDIT", period_end="2024-06-30",
    )
    inspection = fixtures.new_inspection(
        api, ctx, inspection_year=2024, target_engagement_count=1
    )
    fixtures.run_selector(api, ctx, inspection["id"])
    fixtures.inspection_step(api, ctx, inspection["id"], "IN_PROGRESS")
    fixtures.inspection_step(
        api, ctx, inspection["id"], "FINDINGS_CLASSIFIED",
        severity_index_basis="ENGAGEMENT_WEIGHTED",
    )
    fixtures.inspection_step(api, ctx, inspection["id"], "CONCLUDED")

    reviewer = fixtures.new_peer_reviewer(
        api, reviewer_firm_name="Kestrel Peer Review PC", license_state="CA",
        qualified_categories=[], max_concurrent_reviews=2, experience_hours=5000,
    )
    review = fixtures.new_peer_review(
        api, ctx["firm_id"], review_type="SYSTEM_REVIEW", year_end="2026-12-31",
        scheduled_window_start="2026-09-01", scheduled_window_end="2026-09-15",
    )
    fixtures.assign_reviewer(api, review["id"], reviewer["id"])
    fixtures.set_scope(api, review["id"], reviewer["id"])
    selection = fixtures.select_engagement(
        api, review["id"], reviewer["id"], engagement["id"],
        hours_committed=10, is_scope_limitation=False,
    )
    reviewer_headers = make_peer_reviewer_headers(reviewer["id"])
    fixtures.peer_review_step(api, review["id"], "FIELDWORK", reviewer_headers)
    fixtures.record_disposition(
        api, selection["id"], reviewer["id"], "SIGNIFICANT_DEFICIENCY",
        non_conforming=True,
    )
    drafted = fixtures.peer_review_step(
        api, review["id"], "RATING_DRAFTED", reviewer_headers
    )
    return ctx, reviewer, review, drafted, reviewer_headers


def test_report_issuance_on_a_fail_rating_forks_and_synthesizes_one_preissuance_plan(api):
    """A FAIL rating forks the review to CORRECTIVE_ACTION_REQUIRED inside the issuance
    request and synthesizes exactly one PREISSUANCE_REVIEW plan due 45 days later.

    "`PREISSUANCE_REVIEW` with a `due_date` 45 days after the report issue date when
    the rating is `FAIL`."

    Design: Difficulty/non_linear_state_machine/peer_review_report_issued_fork_fail_branch_side_effect_set
    """
    ctx, reviewer, review, drafted, reviewer_headers = _failing_peer_review_at_rating_drafted(api)

    assert_fields(drafted, rating="FAIL", total_scope_hours=16)

    issued = fixtures.peer_review_step(
        api, review["id"], "REPORT_ISSUED", reviewer_headers
    )

    assert_fields(issued, rating="FAIL", state="CORRECTIVE_ACTION_REQUIRED")
    assert issued["report_issued_at"] is not None, (
        "issuance must stamp report_issued_at from the logical clock"
    )

    plans = fixtures.corrective_action_plans_of(api, review["id"])
    assert len(plans) == 1, f"the FAIL branch synthesizes exactly one plan, got {len(plans)}"
    assert_fields(
        plans[0],
        action_code="PREISSUANCE_REVIEW",
        due_date="2026-09-15",
        status="REQUIRED",
        rejection_count=0,
    )


def test_direct_acceptance_is_barred_while_the_corrective_action_is_outstanding(api):
    """The direct REPORT_ISSUED -> ACCEPTED leg is refused on a non-PASS rating, leaving
    the review, the firm's last_peer_review_rating and the reviewer's load untouched.

    "attempting that direct acceptance on a review whose `rating` is not `PASS` is
    refused with `ERR_CORRECTIVE_ACTION_OUTSTANDING`."

    Design: Difficulty/non_linear_state_machine/peer_review_report_issued_fork_fail_branch_side_effect_set
    """
    ctx, reviewer, review, drafted, reviewer_headers = _failing_peer_review_at_rating_drafted(api)
    committee_headers = make_committee_headers()

    fixtures.peer_review_step(api, review["id"], "REPORT_ISSUED", reviewer_headers)
    refused = api.create_peer_review_transition(
        review["id"], f.peer_review_transition_payload("ACCEPTED"),
        headers=committee_headers,
    )

    validate_error(refused, ERR_CORRECTIVE_ACTION_OUTSTANDING, expected_status=409)
    assert_fields(
        read_entity(api.get_peer_review(review["id"], headers=committee_headers)),
        state="CORRECTIVE_ACTION_REQUIRED",
        rating="FAIL",
        total_scope_hours=16,
    )
    assert_fields(
        read_entity(api.get_firm(ctx["firm_id"], headers=committee_headers)),
        last_peer_review_rating="NONE",
    )
    assert_fields(
        read_entity(api.get_peer_reviewer(reviewer["id"], headers=committee_headers)),
        active_review_count=1,
    )
