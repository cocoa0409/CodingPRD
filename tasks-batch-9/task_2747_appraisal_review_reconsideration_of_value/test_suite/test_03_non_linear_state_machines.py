"""
Non-linear state machines: a bounded cycle and two dimensions on one row.

A reconsideration request re-enters a state it has already left, and the loop is
bounded by a round counter rather than by any terminal state. An appraisal carries a
review lifecycle and a compliance lifecycle on the same row, and each advances
without disturbing the other.
"""

from test_helpers import (
    ApiErrorId,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
)
from test_helpers import DESK_REVIEWER_HEADERS

VINE_GRID = [
    {
        "street_address": "51 Vine Street",
        "sale_price_cents": 39000000,
        "gross_adjustment_cents": 390000,
        "net_adjustment_cents": 390000,
        "distance_miles": 1.0,
        "sale_date": "2026-05-01T00:00:00Z",
    },
    {
        "street_address": "52 Vine Street",
        "sale_price_cents": 40000000,
        "gross_adjustment_cents": 400000,
        "net_adjustment_cents": 0,
        "distance_miles": 1.5,
        "sale_date": "2026-06-01T00:00:00Z",
    },
    {
        "street_address": "53 Vine Street",
        "sale_price_cents": 41000000,
        "gross_adjustment_cents": 410000,
        "net_adjustment_cents": -410000,
        "distance_miles": 2.0,
        "sale_date": "2026-06-15T00:00:00Z",
    },
]

BIASED_NARRATIVE = (
    "Subject sits in a desirable neighborhood with strong pride of ownership "
    "and a family-oriented character."
)


def _rov_at_second_round_responded(api):
    """A reconsideration request cycled once and answered twice, resting at RESPONDED
    with its round counter at the two-round ceiling."""
    env = fx.accepted_report(
        api,
        amc={"name": "Beacon Appraisal Management"},
        appraiser={
            "full_name": "Alice Author",
            "license_number": "CA-AL-3001",
            "license_state": "CA",
        },
        loan={"loan_number": "LN-2747-3A", "borrower_display_name": "Dana Borrower"},
        comparables=VINE_GRID,
    )
    rov = fx.open_rov(
        api, env["loan"]["id"], env["appraisal"]["id"],
        requested_value_cents=41000000,
        borrower_statement="Round one evidence attached.",
    )
    fx.file_evidence(
        api, rov["id"], "CLOSED_SALE", street_address="404 Walnut Court",
        sale_price_cents=41000000, sale_date="2026-06-20T00:00:00Z",
        distance_miles=1.1,
    )
    fx.file_evidence(
        api, rov["id"], "CLOSED_SALE", street_address="505 Spruce Way",
        sale_price_cents=40500000, sale_date="2026-06-25T00:00:00Z",
        distance_miles=0.9,
    )
    fx.route_rov(api, rov["id"], intake_note="Round 1 intake complete.")
    fx.rov_respond(
        api, rov["id"], env["appraiser"]["id"], "VALUE_AFFIRMED",
        response_note="Original opinion stands.",
    )
    fx.rov_next_round(
        api, rov["id"],
        next_round_reason="Borrower supplied two further closings.",
    )
    fx.file_evidence(
        api, rov["id"], "CLOSED_SALE", street_address="606 Alder Place",
        sale_price_cents=41500000, sale_date="2026-07-01T00:00:00Z",
        distance_miles=1.3,
    )
    fx.file_evidence(
        api, rov["id"], "CLOSED_SALE", street_address="707 Poplar Street",
        sale_price_cents=41200000, sale_date="2026-07-05T00:00:00Z",
        distance_miles=1.4,
    )
    fx.route_rov(api, rov["id"], intake_note="Round 2 intake complete.")
    env["rov"] = fx.rov_respond(
        api, rov["id"], env["appraiser"]["id"], "VALUE_AFFIRMED",
        response_note="Opinion still stands.",
    )
    return env


def test_a_third_reconsideration_round_is_refused_at_the_ceiling(api):
    """Opening a third round is rejected and the request stays where it was.

    The request has already cycled once, so its round counter sits at two. The loop is
    bounded by that counter rather than by a terminal state, so the request is still in
    RESPONDED and still looks openable, yet the third attempt is refused and nothing
    about the request moves.

    PRD: "At most two rounds exist: a further round may be opened only while
    `round_number` is strictly less than 2, and an attempt to open a third round when
    `round_number` already equals 2 is refused with `ERR_ROV_ROUND_LIMIT` (HTTP 422)."

    Design: Difficulty/non_linear_state_machine/rov_request_cycles_back_to_intake_until_round_limit
    """
    env = _rov_at_second_round_responded(api)

    response = api.rov_next_round(
        env["rov"]["id"],
        f.rov_next_round_payload(next_round_reason="Borrower wants a third pass."),
        DESK_REVIEWER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_ROV_ROUND_LIMIT, 422)

    rov = fx.read_rov_request(api, env["rov"]["id"])
    assert rov["round_number"] == 2
    assert rov["status"] == "RESPONDED"


def test_the_cycle_rebases_the_evidence_tally_on_each_new_round(api):
    """Round two counts only round two's evidence, and the surrounding state is intact.

    Four admissible items were filed in total, two per round, but the tally is
    recomputed over the current round alone, so it reads two rather than four. The
    affirmation resolved the contest, so the report is back at VALUE_ACCEPTED and the
    loan's collateral position follows it, while the loan still records exactly one
    reconsideration ever filed.

    PRD: "Opening a round clears the whole per-round response record —
    `response_deadline_at`, `appraiser_responded_at`, `responded_late`, `outcome`, and
    `revised_value_cents` are all reset — and `admissible_evidence_count` is recomputed
    over the *new* round only, which means it is 0 the moment the new round opens and the
    borrower must file at least two fresh admissible items before routing is possible
    again."

    Design: Difficulty/non_linear_state_machine/rov_request_cycles_back_to_intake_until_round_limit
    """
    env = _rov_at_second_round_responded(api)

    rov = fx.read_rov_request(api, env["rov"]["id"])
    assert rov["round_number"] == 2
    assert rov["admissible_evidence_count"] == 2

    appraisal = fx.read_appraisal(api, env["appraisal"]["id"])
    assert appraisal["review_status"] == "VALUE_ACCEPTED"

    loan = fx.read_loan_file(api, env["loan"]["id"])
    assert loan["collateral_status"] == "VALUE_ACCEPTED"
    assert loan["rov_request_count"] == 1


def _graded_biased_report(api):
    """A report whose receipt checks have cleared but whose narrative carries three
    prohibited terms, so the compliance dimension has not yet moved."""
    return fx.graded_report(
        api,
        amc={"name": "Trellis Appraisal Management"},
        appraiser={
            "full_name": "Alice Author",
            "license_number": "CA-AL-3002",
            "license_state": "CA",
        },
        loan={"loan_number": "LN-2747-3B", "borrower_display_name": "Dana Borrower"},
        appraisal={"narrative_text": BIASED_NARRATIVE},
        comparables=VINE_GRID,
    )


def test_the_bias_screen_moves_only_the_compliance_dimension(api):
    """Screening flips the compliance status and leaves the review status alone.

    The report has already cleared its receipt checks, so its review status is
    RULES_CLEARED. The screen matches three prohibited terms for an index of 36, which
    is at or above the indication threshold, and the response still reports
    RULES_CLEARED on the review dimension.

    PRD: "Screening an appraisal is guarded by `expected_appraisal_version` matching the
    appraisal's current `version`, increments that `version` by 1, and — this is the
    point of a parallel dimension — leaves `review_status` completely untouched."

    Design: Difficulty/non_linear_state_machine/appraisal_review_and_bias_dimensions_advance_independently
    """
    env = _graded_biased_report(api)
    assert env["appraisal"]["review_status"] == "RULES_CLEARED"
    assert env["appraisal"]["bias_screen_status"] == "NOT_SCREENED"

    screened = fx.run_bias_screen(api, env["appraisal"]["id"])
    assert screened["review_status"] == "RULES_CLEARED"
    assert screened["bias_screen_status"] == "INDICATED"
    assert screened["bias_risk_index"] == 36
    assert screened["completeness_score_bps"] == 10000
    assert screened["rule_check_fail_count"] == 0
    assert screened["rule_check_warn_count"] == 0

    flags_body = api.list_bias_flags(
        env["appraisal"]["id"], fx.COMPLIANCE_HEADERS, {"limit": 100}
    )
    flags, meta = validate_paginated(flags_body)
    assert meta["total_count"] == 3
    assert [flag["indicator_code"] for flag in flags] == ["TERM_1", "TERM_2", "TERM_8"]
    assert all(flag["severity_weight"] == 12 for flag in flags)
    assert all(flag["status"] == "OPEN" for flag in flags)


def test_opening_the_desk_review_moves_only_the_review_dimension(api):
    """The desk review advances the review status and leaves the indication standing.

    With the screen already reporting INDICATED, opening a desk review moves the review
    dimension to IN_DESK_REVIEW and pulls the loan's collateral position into review,
    while the compliance status and index stay exactly where the screen left them. The
    preliminary score is a perfect 10000 because no receipt row failed or warned.

    PRD: "Running the bias screen never touches `review_status`; desk-review transitions
    never touch `bias_screen_status`."

    Design: Difficulty/non_linear_state_machine/appraisal_review_and_bias_dimensions_advance_independently
    """
    env = _graded_biased_report(api)
    fx.run_bias_screen(api, env["appraisal"]["id"])
    review = fx.open_desk_review(api, env["appraisal"]["id"])

    appraisal = fx.read_appraisal(api, env["appraisal"]["id"])
    assert appraisal["review_status"] == "IN_DESK_REVIEW"
    assert appraisal["bias_screen_status"] == "INDICATED"
    assert appraisal["bias_risk_index"] == 36

    assert review["preliminary_quality_score_bps"] == 10000

    loan = fx.read_loan_file(api, env["loan"]["id"])
    assert loan["collateral_status"] == "UNDER_REVIEW"
