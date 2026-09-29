"""Lifecycles that are not a single straight line.

A market report advances three dimensions at once, a filing runs a bounded
correction cycle back to where it started, and an audit case forks into two
branches with disjoint side effects before both join at closure.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as u
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_discrepancy_rates,
    assert_report_dimensions,
    assert_submission_totals,
    assert_window_ledger,
)
from test_helpers.types import (
    AggregationState,
    AuditCaseStatus,
    AuditFinding,
    DisclosureState,
    PublicationState,
    ReportingWindowStatus,
    SubmissionStatus,
    WeightingVariant,
)


def _computed_report_on_a_locked_window(api):
    """A computed report whose window is locked and whose release instant is now."""
    scene = fx.three_reporter_cattle_window(api)
    report = fx.computed_report(
        api,
        scene["window"]["id"],
        weighting_variant=WeightingVariant.HEAD_WEIGHTED.value,
    )
    fx.lock_window(api, scene["window"]["id"])
    fx.set_clock(api, k.WINDOW_PUBLICATION_RELEASE)
    return scene, report


def test_01_publication_is_gated_on_a_dimension_other_than_its_own(api):
    """Current arithmetic is not enough: the disclosure axis must move too.

    The aggregation dimension is already computed and the clock is exactly at
    the release instant, yet release is refused because the confidentiality
    review has not happened -- and the refusal moves no dimension at all.

    PRD §3.6: "the disclosure review must have happened, so a `disclosure_state`
    still at `UNREVIEWED` yields `ERR_DISCLOSURE_NOT_REVIEWED`".

    Design: Difficulty/non_linear_state_machine/market_report_three_parallel_dimensions
    """
    _scene, report = _computed_report_on_a_locked_window(api)

    refused = api.publish_market_report(report["id"], u.MARKET_ANALYST)
    validate_error(refused, ApiErrorId.ERR_DISCLOSURE_NOT_REVIEWED.value, 409)

    unmoved = fx.read_report(api, report["id"])
    assert_report_dimensions(
        unmoved,
        AggregationState.COMPUTED.value,
        DisclosureState.UNREVIEWED.value,
        PublicationState.UNPUBLISHED.value,
    )


def test_02_each_endpoint_advances_exactly_one_of_the_three_dimensions(api):
    """Review moves disclosure only; release then moves publication only.

    The confidentiality review clears the report while aggregation and
    publication stand still, and the release that follows moves publication
    alone -- carrying the window from locked to published as its side effect.

    PRD §3.6: "Releasing a report moves `publication_state` from `UNPUBLISHED`
    to `PUBLISHED`, stamps `published_at` with the logical clock, and carries the
    report's window from `LOCKED` to `PUBLISHED`."

    Design: Difficulty/non_linear_state_machine/market_report_three_parallel_dimensions
    """
    scene, report = _computed_report_on_a_locked_window(api)

    reviewed = validate_success(
        api.disclosure_review_market_report(report["id"], u.MARKET_ANALYST)
    )
    assert_report_dimensions(
        reviewed,
        AggregationState.COMPUTED.value,
        DisclosureState.CLEARED.value,
        PublicationState.UNPUBLISHED.value,
    )
    assert reviewed["suppression_reason"] is None, reviewed

    published = validate_success(
        api.publish_market_report(report["id"], u.MARKET_ANALYST)
    )
    assert_report_dimensions(
        published,
        AggregationState.COMPUTED.value,
        DisclosureState.CLEARED.value,
        PublicationState.PUBLISHED.value,
    )
    assert published["weighted_average_price_per_cwt"] == 285.61, published

    window = fx.read_window(api, scene["window"]["id"])
    assert window["status"] == ReportingWindowStatus.PUBLISHED.value, window


def test_03_one_correction_cycle_returns_the_filing_to_accepted(api):
    """The head leaves the ledger on reopening and comes back on re-acceptance.

    Reopening drops the filing's 200 head out of the window ledger, the added
    50 head are booked on the refiling, and the re-acceptance brings the whole
    250 back in with the loop counter standing at one.

    PRD §3.5: "acceptance closes the cycle `ACCEPTED → UNDER_CORRECTION →
    RESUBMITTED → ACCEPTED` and brings the head back into the window ledger".

    Design: Difficulty/non_linear_state_machine/submission_correction_cycle_returns_to_accepted
    """
    firm = fx.alpha_firm(api)
    window = fx.create_window(api)
    filing = fx.accepted_filing(
        api,
        firm["entity"]["id"],
        firm["plant"]["id"],
        window["id"],
        lines=[
            f.transaction_payload(
                head_count=200,
                avg_net_price_per_cwt=279.75,
                avg_carcass_weight_cwt=8.60,
            )
        ],
    )
    assert_submission_totals(
        fx.read_submission(api, filing["id"]),
        reported_head=200,
        reported_value_dollars=481170.00,
    )

    reopened = fx.reopen_filing(api, filing["id"], "omitted 50 head")
    assert reopened["status"] == SubmissionStatus.UNDER_CORRECTION.value
    assert reopened["resubmission_count"] == 0, reopened
    assert_window_ledger(
        fx.read_window(api, window["id"]),
        total_head_reported=0,
        accepted_submission_count=0,
    )

    fx.add_transaction(
        api,
        firm["entity"]["id"],
        filing["id"],
        f.transaction_payload(
            head_count=50, avg_net_price_per_cwt=280.00, avg_carcass_weight_cwt=8.00
        ),
    )
    refiled = fx.resubmit_filing(api, firm["entity"]["id"], filing["id"])
    assert refiled["status"] == SubmissionStatus.RESUBMITTED.value
    assert refiled["resubmission_count"] == 1, refiled
    assert_submission_totals(
        refiled, reported_head=250, reported_value_dollars=593170.00
    )

    accepted = fx.accept_filing(api, filing["id"])
    assert accepted["status"] == SubmissionStatus.ACCEPTED.value
    assert_window_ledger(
        fx.read_window(api, window["id"]),
        total_head_reported=250,
        accepted_submission_count=1,
    )


def test_04_the_loop_counter_and_not_a_terminal_state_ends_the_cycle(api):
    """Two cycles are allowed; the third reopening is refused on the counter.

    After a second full cycle the filing is accepted again with 300 head and
    2520.00 hundredweight booked, and the next reopening is refused because the
    resubmission count has reached the ceiling -- the filing itself is fine.

    PRD §3.5: "the filing's `resubmission_count` must be below 2, or the request
    is refused with `ERR_RESUBMISSION_LIMIT_REACHED`".

    Design: Difficulty/non_linear_state_machine/submission_correction_cycle_returns_to_accepted
    """
    firm = fx.alpha_firm(api)
    window = fx.create_window(api)
    filing = fx.accepted_filing(
        api,
        firm["entity"]["id"],
        firm["plant"]["id"],
        window["id"],
        lines=[
            f.transaction_payload(
                head_count=200,
                avg_net_price_per_cwt=279.75,
                avg_carcass_weight_cwt=8.60,
            )
        ],
    )

    for reason in ("omitted 50 head", "omitted another 50 head"):
        fx.reopen_filing(api, filing["id"], reason)
        fx.add_transaction(
            api,
            firm["entity"]["id"],
            filing["id"],
            f.transaction_payload(
                head_count=50,
                avg_net_price_per_cwt=280.00,
                avg_carcass_weight_cwt=8.00,
            ),
        )
        fx.resubmit_filing(api, firm["entity"]["id"], filing["id"])
        fx.accept_filing(api, filing["id"])

    twice_corrected = fx.read_submission(api, filing["id"])
    assert twice_corrected["status"] == SubmissionStatus.ACCEPTED.value
    assert twice_corrected["resubmission_count"] == 2, twice_corrected
    assert_submission_totals(
        twice_corrected,
        reported_head=300,
        reported_cwt=2520.00,
        reported_value_dollars=705170.00,
    )
    assert_window_ledger(
        fx.read_window(api, window["id"]),
        total_head_reported=300,
        accepted_submission_count=1,
    )

    refused = api.open_correction(
        filing["id"], f.correction_payload("third attempt"), u.COMPLIANCE_AUDITOR
    )
    validate_error(refused, ApiErrorId.ERR_RESUBMISSION_LIMIT_REACHED.value, 409)

    unmoved = fx.read_submission(api, filing["id"])
    assert unmoved["status"] == SubmissionStatus.ACCEPTED.value
    assert unmoved["resubmission_count"] == 2, unmoved


def _two_audited_filings(api):
    """Two accepted filings in one window, each with a case in fieldwork."""
    alpha = fx.alpha_firm(api)
    bravo = fx.bravo_firm(api)
    window = fx.create_window(api)

    filing_a = fx.accepted_filing(
        api,
        alpha["entity"]["id"],
        alpha["plant"]["id"],
        window["id"],
        lines=[
            f.transaction_payload(
                head_count=255,
                avg_net_price_per_cwt=280.00,
                avg_carcass_weight_cwt=8.00,
            )
        ],
    )
    filing_b = fx.accepted_filing(
        api,
        bravo["entity"]["id"],
        bravo["plant"]["id"],
        window["id"],
        lines=[
            f.transaction_payload(
                head_count=400,
                avg_net_price_per_cwt=284.00,
                avg_carcass_weight_cwt=8.50,
            )
        ],
    )
    assert_window_ledger(
        fx.read_window(api, window["id"]),
        total_head_reported=655,
        accepted_submission_count=2,
    )

    return {
        "window": window,
        "filing_a": filing_a,
        "filing_b": filing_b,
        "case_a": fx.fieldwork_case(api, filing_a["id"]),
        "case_b": fx.fieldwork_case(api, filing_b["id"]),
    }


def test_05_the_fork_out_of_fieldwork_has_disjoint_side_effect_sets(api):
    """An immaterial finding changes nothing else; a material one reopens.

    Five head out of 250 verified is exactly the materiality threshold and so
    reconciles with the filing left accepted, while twenty out of 380 is
    material and drives its filing out of the ledger.

    PRD §3.7: "Nothing else moves: the audited filing is left in `ACCEPTED`, the
    window ledger is untouched, and no market report is invalidated."

    Design: Difficulty/non_linear_state_machine/audit_case_fork_join_divergent_branch_effects
    """
    scene = _two_audited_filings(api)

    reconciled = fx.finalize_case(api, scene["case_a"]["id"], 250, 571200.00)
    assert reconciled["status"] == AuditCaseStatus.RECONCILED.value, reconciled
    assert_discrepancy_rates(reconciled, 2.00, 0.00, AuditFinding.IMMATERIAL.value)
    assert (
        fx.read_submission(api, scene["filing_a"]["id"])["status"]
        == SubmissionStatus.ACCEPTED.value
    )

    discrepant = fx.finalize_case(api, scene["case_b"]["id"], 380, 965600.00)
    assert discrepant["status"] == AuditCaseStatus.DISCREPANCY.value, discrepant
    assert_discrepancy_rates(discrepant, 5.26, 0.00, AuditFinding.MATERIAL_HEAD.value)
    assert (
        fx.read_submission(api, scene["filing_b"]["id"])["status"]
        == SubmissionStatus.UNDER_CORRECTION.value
    )

    assert_window_ledger(
        fx.read_window(api, scene["window"]["id"]),
        total_head_reported=255,
        accepted_submission_count=1,
    )


def test_06_both_branches_join_at_the_single_terminal_closure(api):
    """Reconciled and discrepant cases close through the same door.

    Whichever branch a case took, closure carries it to the one terminal state
    and stamps the closing instant on it.

    PRD §3.7: "Both branches join at closure: a case in `RECONCILED` or
    `DISCREPANCY` is closed by a `ComplianceAuditor`, moving it to `CLOSED` and
    stamping `closed_at` with the logical clock."

    Design: Difficulty/non_linear_state_machine/audit_case_fork_join_divergent_branch_effects
    """
    scene = _two_audited_filings(api)
    fx.finalize_case(api, scene["case_a"]["id"], 250, 571200.00)
    fx.finalize_case(api, scene["case_b"]["id"], 380, 965600.00)

    for key in ("case_a", "case_b"):
        closed = get_success_data(
            api.close_audit_case(scene[key]["id"], u.COMPLIANCE_AUDITOR_2)
        )
        assert closed["status"] == AuditCaseStatus.CLOSED.value, closed
        assert closed["closed_at"] is not None, closed
