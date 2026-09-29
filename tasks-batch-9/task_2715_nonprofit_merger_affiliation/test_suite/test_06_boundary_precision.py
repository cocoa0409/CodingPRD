"""Boundary-precision tests for the attorney-general filing thresholds of PRD 3.7.

Every figure exercised here sits exactly on, or one cent either side of, a
threshold whose comparison the PRD pins as inclusive or strictly-less-than. The
deal is walked to REGULATORY_REVIEW through the declared transitions, because
PRD 3.7 admits a filing only while the deal is REGULATORY_REVIEW or INTEGRATION.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_AG_FILING_TYPE_MISMATCH
from test_helpers.assertions import assert_field, assert_money_equals
from test_helpers.constants import (
    AG_PETITION_THRESHOLD_CENTS,
    FEE_TIER_1_CENTS,
    FEE_TIER_2_CENTS,
    FEE_TIER_3_CENTS,
    NOTICE_WAITING_DAYS,
    PETITION_WAITING_DAYS,
)
from test_helpers.test_users import TRUST_COUNSEL


def _deal_in_regulatory_review(api, unrestricted_transfer_value_cents: int):
    """Walk a two-party CA deal to REGULATORY_REVIEW with the given transfer value.

    Both parties are incorporated in CA, one of the five review states, so
    ag_review_required is true and the deal rests in REGULATORY_REVIEW once both
    boards hold a CERTIFIED resolution (PRD 3.2, PRD 3.5).
    """
    ctx = fx.setup_deal_structure_selected(
        api, unrestricted_transfer_value_cents=unrestricted_transfer_value_cents
    )
    ctx = fx.setup_deal_board_approval(api, ctx)
    ctx = fx.setup_deal_regulatory_review(api, ctx)
    assert ctx["deal"]["status"] == "REGULATORY_REVIEW", (
        f"precondition: deal must rest in REGULATORY_REVIEW, got {ctx['deal']['status']}"
    )
    assert ctx["deal"]["ag_review_required"] is True
    return ctx


def test_notice_at_exact_petition_threshold_is_rejected(api):
    """A NOTICE is refused when the recited asset value sits exactly on the petition threshold.

    PRD 3.7 states that "a recited asset value of five million dollars or more"
    independently forces the heavier route, so the required type is
    APPROVAL_PETITION, and "a filing_type that does not equal the required type
    - a notice where a petition is owed - is refused with
    ERR_AG_FILING_TYPE_MISMATCH". The deal's unrestricted_transfer_value_cents is
    exactly 500000000 cents and no restricted fund has moved, so
    transferred_charitable_asset_value_cents lands exactly on the threshold and
    the inclusive "or more" comparison already owes a petition.

    Design: Difficulty/boundary_precision_check/ag_petition_threshold_at_exact_boundary_forces_petition_and_45_days
    """
    ctx = _deal_in_regulatory_review(api, AG_PETITION_THRESHOLD_CENTS)

    response = api.create_ag_filing(
        f.ag_filing_payload(
            ctx["deal"]["id"], filing_type="NOTICE", legal_costs_cents=10000000
        ),
        TRUST_COUNSEL,
    )
    validate_error(response, ERR_AG_FILING_TYPE_MISMATCH, 422)


def test_approval_petition_at_exact_threshold_books_forty_five_statutory_days(api):
    """The petition owed at the exact threshold carries 45 statutory days, not 20.

    PRD 3.7 fixes statutory_waiting_days at "forty-five calendar days for an
    APPROVAL_PETITION and at twenty calendar days for a NOTICE", with no
    surcharge here because the structure is MERGER rather than ASSET_ACQUISITION
    and judicial_basis_present is false. review_deadline_at is "submitted_at
    advanced by statutory_waiting_days calendar days", and submitted_at is
    stamped from the logical clock, which still reads its 2026-08-01T00:00:00Z
    startup default per PRD 2.4, so the deadline is 2026-09-15 and not the
    2026-08-21 a 20-day period would produce.

    Design: Difficulty/boundary_precision_check/ag_petition_threshold_at_exact_boundary_forces_petition_and_45_days
    """
    ctx = _deal_in_regulatory_review(api, AG_PETITION_THRESHOLD_CENTS)

    filing = validate_success(
        api.create_ag_filing(
            f.ag_filing_payload(
                ctx["deal"]["id"],
                filing_type="APPROVAL_PETITION",
                legal_costs_cents=10000000,
            ),
            TRUST_COUNSEL,
        ),
        201,
    )

    assert_field(filing, "filing_type", "APPROVAL_PETITION")
    assert_field(filing, "status", "SUBMITTED")
    assert_money_equals(
        filing["transferred_charitable_asset_value_cents"],
        AG_PETITION_THRESHOLD_CENTS,
        "transferred_charitable_asset_value_cents",
    )
    assert_field(filing, "statutory_waiting_days", PETITION_WAITING_DAYS)
    assert filing["statutory_waiting_days"] != NOTICE_WAITING_DAYS
    assert_field(filing, "review_deadline_at", "2026-09-15T00:00:00.000Z")
    assert_money_equals(
        filing["provisional_consideration_cents"], 510000000, "provisional_consideration_cents"
    )
    assert_money_equals(filing["ag_filing_fee_cents"], FEE_TIER_2_CENTS, "ag_filing_fee_cents")
    assert_money_equals(filing["closing_costs_cents"], 10150000, "closing_costs_cents")
    assert_money_equals(
        filing["total_consideration_cents"], 510150000, "total_consideration_cents"
    )
    assert_field(fx.read_deal(api, ctx["deal"]["id"]), "status", "REGULATORY_REVIEW")


def test_one_cent_below_petition_threshold_requires_a_notice_with_twenty_days(api):
    """One cent below the threshold the required type flips back to NOTICE and to 20 days.

    PRD 3.7 forces an APPROVAL_PETITION only at "five million dollars or more";
    at 499999999 cents the recited value is below that figure and, with no
    contributing PERM_ENDOWMENT fund, "otherwise it is NOTICE". The notice
    therefore stands and takes the twenty-day statutory period, whose deadline is
    submitted_at advanced by twenty calendar days from the logical clock's
    2026-08-01T00:00:00Z default. A petition on the same deal is now the wrong
    type and is refused with ERR_AG_FILING_TYPE_MISMATCH.

    Design: Difficulty/boundary_precision_check/ag_petition_threshold_at_exact_boundary_forces_petition_and_45_days
    """
    ctx = _deal_in_regulatory_review(api, AG_PETITION_THRESHOLD_CENTS - 1)

    filing = validate_success(
        api.create_ag_filing(
            f.ag_filing_payload(
                ctx["deal"]["id"], filing_type="NOTICE", legal_costs_cents=10000000
            ),
            TRUST_COUNSEL,
        ),
        201,
    )
    assert_field(filing, "filing_type", "NOTICE")
    assert_money_equals(
        filing["transferred_charitable_asset_value_cents"],
        AG_PETITION_THRESHOLD_CENTS - 1,
        "transferred_charitable_asset_value_cents",
    )
    assert_field(filing, "statutory_waiting_days", NOTICE_WAITING_DAYS)
    assert_field(filing, "review_deadline_at", "2026-08-21T00:00:00.000Z")

    refused = api.create_ag_filing(
        f.ag_filing_payload(
            ctx["deal"]["id"],
            filing_type="APPROVAL_PETITION",
            legal_costs_cents=10000000,
        ),
        TRUST_COUNSEL,
    )
    validate_error(refused, ERR_AG_FILING_TYPE_MISMATCH, 422)


def test_provisional_total_on_the_one_million_ceiling_takes_the_higher_fee_tier(api):
    """A provisional total exactly on the one-million-dollar ceiling falls into the higher tier.

    PRD 3.7 computes provisional_consideration_cents as the fee-exclusive
    "transferred_charitable_asset_value_cents plus legal_costs_cents", then
    selects the tier "by reading only that provisional total", and states that
    "both tier comparisons are strictly less-than against their ceilings, so a
    provisional total landing exactly on a ceiling falls into the higher tier".
    With a recited value of 99000000 cents and legal costs of 1000000 cents the
    provisional total is exactly 100000000 cents, so the fee is the
    one-thousand-five-hundred-dollar tier, and closing_costs_cents and
    total_consideration_cents fold that fee in per step three.

    Design: Difficulty/boundary_precision_check/ag_fee_tier_ceiling_one_cent_either_side_of_the_boundary
    """
    ctx = _deal_in_regulatory_review(api, 99000000)

    filing = validate_success(
        api.create_ag_filing(
            f.ag_filing_payload(
                ctx["deal"]["id"], filing_type="NOTICE", legal_costs_cents=1000000
            ),
            TRUST_COUNSEL,
        ),
        201,
    )

    assert_money_equals(
        filing["provisional_consideration_cents"], 100000000, "provisional_consideration_cents"
    )
    assert_money_equals(filing["ag_filing_fee_cents"], FEE_TIER_2_CENTS, "ag_filing_fee_cents")
    assert_money_equals(filing["closing_costs_cents"], 1150000, "closing_costs_cents")
    assert_money_equals(
        filing["total_consideration_cents"], 100150000, "total_consideration_cents"
    )
    assert_field(filing, "statutory_waiting_days", NOTICE_WAITING_DAYS)
    assert_field(filing, "review_deadline_at", "2026-08-21T00:00:00.000Z")


def test_provisional_total_one_cent_below_the_ceiling_takes_the_lower_fee_tier(api):
    """One cent below the ceiling the provisional total stays in the two-hundred-fifty-dollar tier.

    PRD 3.7 sets ag_filing_fee_cents at "two hundred fifty dollars" while the
    provisional total is "below one million dollars", and the total is read
    fee-exclusive. Legal costs of 999999 cents against a recited value of
    99000000 cents give a provisional total of 99999999 cents, one cent under the
    ceiling, so the lower fee applies and closing_costs_cents is
    legal_costs_cents plus that fee.

    Design: Difficulty/boundary_precision_check/ag_fee_tier_ceiling_one_cent_either_side_of_the_boundary
    """
    ctx = _deal_in_regulatory_review(api, 99000000)

    filing = validate_success(
        api.create_ag_filing(
            f.ag_filing_payload(
                ctx["deal"]["id"], filing_type="NOTICE", legal_costs_cents=999999
            ),
            TRUST_COUNSEL,
        ),
        201,
    )

    assert_money_equals(
        filing["provisional_consideration_cents"], 99999999, "provisional_consideration_cents"
    )
    assert_money_equals(filing["ag_filing_fee_cents"], FEE_TIER_1_CENTS, "ag_filing_fee_cents")
    assert_money_equals(filing["closing_costs_cents"], 1024999, "closing_costs_cents")
    assert_money_equals(
        filing["total_consideration_cents"], 100024999, "total_consideration_cents"
    )
    assert_field(filing, "statutory_waiting_days", NOTICE_WAITING_DAYS)


def test_provisional_total_on_the_ten_million_ceiling_takes_the_top_fee_tier(api):
    """The second ceiling behaves the same way: exactly ten million dollars pays five thousand.

    PRD 3.7 sets the fee at "one thousand five hundred dollars" at one million or
    above but below ten million, and at "five thousand dollars" at ten million or
    above, both comparisons being "strictly less-than against their ceilings".
    Two filings on the same deal - PRD 3.7 permits several filings to coexist -
    differ by a single cent of legal costs: 901000000 puts the provisional total
    exactly on 1000000000 cents and pays the top fee, while 900999999 leaves it
    one cent below and pays the middle fee.

    Design: Difficulty/boundary_precision_check/ag_fee_tier_ceiling_one_cent_either_side_of_the_boundary
    """
    ctx = _deal_in_regulatory_review(api, 99000000)
    deal_id = ctx["deal"]["id"]

    at_ceiling = validate_success(
        api.create_ag_filing(
            f.ag_filing_payload(deal_id, filing_type="NOTICE", legal_costs_cents=901000000),
            TRUST_COUNSEL,
        ),
        201,
    )
    below_ceiling = validate_success(
        api.create_ag_filing(
            f.ag_filing_payload(deal_id, filing_type="NOTICE", legal_costs_cents=900999999),
            TRUST_COUNSEL,
        ),
        201,
    )

    assert_money_equals(
        at_ceiling["provisional_consideration_cents"],
        1000000000,
        "at_ceiling.provisional_consideration_cents",
    )
    assert_money_equals(
        at_ceiling["ag_filing_fee_cents"], FEE_TIER_3_CENTS, "at_ceiling.ag_filing_fee_cents"
    )
    assert_money_equals(
        at_ceiling["closing_costs_cents"], 901500000, "at_ceiling.closing_costs_cents"
    )
    assert_money_equals(
        at_ceiling["total_consideration_cents"],
        1000500000,
        "at_ceiling.total_consideration_cents",
    )

    assert_money_equals(
        below_ceiling["provisional_consideration_cents"],
        999999999,
        "below_ceiling.provisional_consideration_cents",
    )
    assert_money_equals(
        below_ceiling["ag_filing_fee_cents"],
        FEE_TIER_2_CENTS,
        "below_ceiling.ag_filing_fee_cents",
    )
    assert_money_equals(
        below_ceiling["closing_costs_cents"], 901149999, "below_ceiling.closing_costs_cents"
    )
    assert_money_equals(
        below_ceiling["total_consideration_cents"],
        1000149999,
        "below_ceiling.total_consideration_cents",
    )
