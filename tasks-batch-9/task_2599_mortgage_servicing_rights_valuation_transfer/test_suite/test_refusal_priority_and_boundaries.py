"""
Refusal precedence and threshold boundaries on the transfer desk.

Two themes live in this module. The first is which single error a doubly
defective request is told about: a bid that is both filed on a package that is
no longer open and priced below the reserve, and a bid filed by a suspended
institution after the marketing window has closed. In each pair the test shows
the outranking refusal winning, and a companion test cures the outranking
defect so the lower-ranked refusal can surface with the same payload.

The second theme is the exact edge of a threshold: a complaint concentration
ratio sitting precisely on the inclusive upper bound of the first release tier
and one complaint past it, and a bid package whose tape holds exactly zero
included lines and then exactly one.
"""

from decimal import Decimal

from test_helpers import (
    C, F, U,
    ApiClient, JsonDict,
    ERR_BIDDER_NOT_ELIGIBLE,
    ERR_BID_BELOW_RESERVE,
    ERR_BID_DEADLINE_PASSED,
    ERR_HOLDBACK_EXHAUSTED,
    ERR_HOLDBACK_NOT_ELIGIBLE,
    ERR_PACKAGE_NOT_ACCEPTING_BIDS,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_TAPE_EMPTY,
    assert_holdback_split,
    assert_status,
    price_at_bps,
    refresh_agreement,
    refresh_package,
    refresh_transfer,
    round_half_up,
    validate_error,
)

# The four-loan pool T carries 40000200 cents of unpaid balance and values at
# 171576 cents under the desk-base assumptions at the opening curve, so a
# ninety-five percent floor stamps a reserve of 162997 cents on the whole tape.
TAPE_UPB_CENTS = 40000200
ONE_LOAN_UPB_CENTS = 10000050
FULL_TAPE_RESERVE_CENTS = 162997
ONE_LINE_RESERVE_CENTS = 40749

BELOW_RESERVE_BPS = 40
BELOW_RESERVE_VALUE_CENTS = 160001
CLEARING_BPS = 118
CLEARING_VALUE_CENTS = 472002

SIZED_HOLDBACK_CENTS = 28320
ELIGIBLE_DATE = "2026-10-01"
CLOCK_ELIGIBLE = "2026-10-01T00:00:00Z"
CLOCK_DAY_BEFORE_ELIGIBLE = "2026-09-30T00:00:00Z"
CLOCK_COMPLAINT_DAY = "2026-09-05T00:00:00Z"


def _bid_body(bidder_id: str, price_bps: int, package_version: int) -> JsonDict:
    """A bid payload carrying a current package concurrency token."""
    return {
        "bidder_id": bidder_id,
        "price_bps": price_bps,
        "holdback_pct": 6,
        "expected_bid_package_version": package_version,
    }


def _file_bid(api: ApiClient, env: JsonDict, bidder_id: str, price_bps: int,
              package_version: int):
    """File a bid as the named acquiring servicer and return the raw response."""
    return api.create_bid(
        env["package_id"], _bid_body(bidder_id, price_bps, package_version),
        U.make_buyer_headers(bidder_id))


def _resolved_case(api: ApiClient, env: JsonDict, loan_id: str,
                   remediation_cents: int) -> JsonDict:
    """Log one borrower notice of error, acknowledge it and resolve it."""
    case = F.open_error_case(api, env["transfer_id"], loan_id)
    F.acknowledge_case(api, case["id"], env["buyer_id"])
    return F.resolve_case(api, case["id"], env["buyer_id"],
                          remediation_cents=remediation_cents)


def _release(api: ApiClient, agreement_id: str, expected_version: int,
             headers=None):
    """Attempt a holdback release and return the raw response."""
    return api.create_holdback_release(
        agreement_id, {"expected_purchase_agreement_version": expected_version},
        headers or U.COMPLIANCE_2)


# ---------------------------------------------------------------------------
# A bid that is both untimely by state and short of the reserve
# ---------------------------------------------------------------------------
def test_bid_on_a_suspended_package_reports_the_state_not_the_reserve(
        api, published_package):
    """
    A below-reserve bid on a package suspended by a curve move is told only that
    the package is closed, even though the reserve is still violated.

    PRD: "First, **state always beats economics**: a bid filed on a package that is not `PUBLISHED` reports `ERR_PACKAGE_NOT_ACCEPTING_BIDS` even when the bid also sits below the reserve, so a refusal never leaks pricing information about a package that is not open."

    Design: Difficulty/priority_pair_validation_conflict/package_state_check_outranks_reserve_price_check
    """
    env = published_package
    assert env["package"]["tape_upb_cents"] == TAPE_UPB_CENTS
    assert env["package"]["reserve_price_cents"] == FULL_TAPE_RESERVE_CENTS

    # A later curve stales the bound run and suspends the auction it anchors.
    F.create_rate_curve(api, C.CURVE_C2)
    package = refresh_package(api, env)
    assert_status(package, "BIDDING_SUSPENDED")
    assert package["suspended_reason"] == "VALUATION_STALE"
    # The reserve survives the suspension, so both defects are live at once.
    assert package["reserve_price_cents"] == FULL_TAPE_RESERVE_CENTS
    assert price_at_bps(TAPE_UPB_CENTS, BELOW_RESERVE_BPS) == (
        BELOW_RESERVE_VALUE_CENTS
    )
    assert BELOW_RESERVE_VALUE_CENTS < FULL_TAPE_RESERVE_CENTS

    response = _file_bid(api, env, env["buyer_id"], BELOW_RESERVE_BPS,
                         package["version"])
    validate_error(response, ERR_PACKAGE_NOT_ACCEPTING_BIDS, 409)

    after = refresh_package(api, env)
    assert after["bid_count"] == 0
    assert after["version"] == package["version"]


def test_bid_below_reserve_on_an_open_package_reports_the_reserve(
        api, published_package):
    """
    The identical below-reserve payload is refused on price once the package is
    still open, which is the only condition under which the reserve is quoted.

    PRD: "And `bid_value_cents` must be at least the package's `reserve_price_cents`, else `ERR_BID_BELOW_RESERVE` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/package_state_check_outranks_reserve_price_check
    """
    env = published_package
    package = env["package"]
    assert_status(package, "PUBLISHED")
    assert package["reserve_price_cents"] == FULL_TAPE_RESERVE_CENTS
    assert price_at_bps(package["tape_upb_cents"], BELOW_RESERVE_BPS) == (
        BELOW_RESERVE_VALUE_CENTS
    )

    response = _file_bid(api, env, env["buyer_id"], BELOW_RESERVE_BPS,
                         package["version"])
    validate_error(response, ERR_BID_BELOW_RESERVE, 422)

    after = refresh_package(api, env)
    assert_status(after, "PUBLISHED")
    assert after["bid_count"] == 0
    assert after["version"] == package["version"]


# ---------------------------------------------------------------------------
# A bid that is both from a suspended institution and past the deadline
# ---------------------------------------------------------------------------
def test_suspended_bidder_past_the_deadline_reports_eligibility(
        api, published_package):
    """
    A suspended institution bidding after the window has closed is told about its
    eligibility, never about the calendar.

    PRD: "Eligibility deliberately outranks the deadline, so an ineligible bidder is told about its eligibility even when the window has also closed; and the reserve test, being the last of the five, is only ever reported when everything else passes."

    Design: Difficulty/priority_pair_validation_conflict/bidder_eligibility_outranks_bid_deadline
    """
    env = published_package
    assert env["package"]["bid_deadline_at"].startswith("2026-08-15")

    # 2026-08-20 is past the 2026-08-15 deadline for both calls of this pair.
    F.set_clock(api, C.CLOCK_AUG_20)
    bravo = F.suspend_counterparty(api, env["buyer_id"])
    assert_status(bravo, "SUSPENDED")
    assert bravo["suspended_at"].startswith("2026-08-20")

    # The price clears the reserve, so the fiscal floor cannot confound the pair.
    assert price_at_bps(TAPE_UPB_CENTS, CLEARING_BPS) == CLEARING_VALUE_CENTS
    assert CLEARING_VALUE_CENTS > env["package"]["reserve_price_cents"]

    response = _file_bid(api, env, env["buyer_id"], CLEARING_BPS,
                         env["package_version"])
    validate_error(response, ERR_BIDDER_NOT_ELIGIBLE, 422)

    after = refresh_package(api, env)
    assert_status(after, "PUBLISHED")
    assert after["bid_count"] == 0


def test_eligible_bidder_past_the_deadline_reports_the_deadline(
        api, published_package):
    """
    Curing the eligibility defect — an active, agency-approved bidder filing the
    same price at the same instant — lets the closed window surface instead.

    PRD: "The logical clock must fall inside the marketing window, at or after `marketing_start_at` and strictly before `bid_deadline_at`, else `ERR_BID_DEADLINE_PASSED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/bidder_eligibility_outranks_bid_deadline
    """
    env = published_package
    charlie = F.create_counterparty(api, C.BUYER_CHARLIE)
    assert_status(charlie, "ACTIVE")
    assert charlie["agency_approvals"] == ["FNMA"]

    F.set_clock(api, C.CLOCK_AUG_20)
    response = _file_bid(api, env, charlie["id"], CLEARING_BPS,
                         env["package_version"])
    validate_error(response, ERR_BID_DEADLINE_PASSED, 422)

    after = refresh_package(api, env)
    assert_status(after, "PUBLISHED")
    assert after["bid_count"] == 0


def test_suspended_bidder_inside_the_window_still_reports_eligibility(
        api, published_package):
    """
    Restoring the calendar does not rehabilitate the bidder: the suspension alone
    is disqualifying while the window is still open.

    PRD: "What suspension does is close two gates — a `SUSPENDED` counterparty may no longer be named as a bidder, and it may no longer be carried through to award."

    Design: Difficulty/priority_pair_validation_conflict/bidder_eligibility_outranks_bid_deadline
    """
    env = published_package
    F.suspend_counterparty(api, env["buyer_id"])
    F.set_clock(api, C.CLOCK_AUG_10)

    response = _file_bid(api, env, env["buyer_id"], CLEARING_BPS,
                         env["package_version"])
    validate_error(response, ERR_BIDDER_NOT_ELIGIBLE, 422)

    after = refresh_package(api, env)
    assert after["bid_count"] == 0


# ---------------------------------------------------------------------------
# The inclusive upper bound of the first complaint concentration tier
# ---------------------------------------------------------------------------
def test_complaint_ratio_exactly_at_the_tier_one_bound_releases_in_full(
        api, completed_transfer):
    """
    One complaint over four transferred loans is a ratio of exactly 25.00, which
    the inclusive bound reads as the first tier and releases the whole balance.

    PRD: "A ratio of 25.00 percent or less releases 100 percent."

    Design: Difficulty/boundary_precision_check/complaint_ratio_exactly_at_tier_one_upper_bound_releases_in_full
    """
    env = completed_transfer
    transfer = refresh_transfer(api, env)
    assert transfer["transferred_loan_count"] == 4

    agreement = refresh_agreement(api, env)
    assert agreement["holdback_cents"] == SIZED_HOLDBACK_CENTS
    assert agreement["holdback_retained_cents"] == SIZED_HOLDBACK_CENTS
    assert agreement["holdback_release_eligible_at"] == ELIGIBLE_DATE

    F.set_clock(api, CLOCK_COMPLAINT_DAY)
    case = _resolved_case(api, env, env["loan_ids"][0], 5000)
    assert_status(case, "RESOLVED")
    assert case["remediation_cents"] == 5000

    # One case over four loans is 1 * 100 / 4 == 25.00 exactly, so the release
    # percentage is 100: gross 28320, cap floor(28320 * 0.40) == 11328, and the
    # 5000 remediation total sits below that cap.
    assert round_half_up(Decimal(1) * 100 / Decimal(4), 2) == 25.00

    F.set_clock(api, CLOCK_ELIGIBLE)
    agreement = refresh_agreement(api, env)
    released = F.release_holdback(api, env["agreement_id"],
                                 agreement["version"])
    assert_holdback_split(released, retained=0, released=23320, applied=5000)
    assert_status(released, "HOLDBACK_RELEASED")

    # The balance is gone, so an immediate repeat has nothing left to release.
    repeat = _release(api, env["agreement_id"], released["version"])
    validate_error(repeat, ERR_HOLDBACK_EXHAUSTED, 409)


def test_complaint_ratio_one_case_past_the_tier_one_bound_releases_half(
        api, completed_transfer):
    """
    A second complaint carries the ratio to 50.00, one cardinality step past the
    first tier, and only half the retained balance is released.

    PRD: "A ratio above 25.00 and up to and including 50.00 releases 50 percent."

    Design: Difficulty/boundary_precision_check/complaint_ratio_exactly_at_tier_one_upper_bound_releases_in_full
    """
    env = completed_transfer
    F.set_clock(api, CLOCK_COMPLAINT_DAY)
    _resolved_case(api, env, env["loan_ids"][0], 5000)
    # A second case, left OPEN, still counts in the concentration numerator.
    second = F.open_error_case(api, env["transfer_id"], env["loan_ids"][1])
    assert_status(second, "OPEN")

    # Two cases over four loans is 50.00 exactly: release percentage 50, gross
    # 14160, cap floor(14160 * 0.40) == 5664, charge 5000, net wire 9160.
    assert round_half_up(Decimal(2) * 100 / Decimal(4), 2) == 50.00

    F.set_clock(api, CLOCK_ELIGIBLE)
    agreement = refresh_agreement(api, env)
    released = F.release_holdback(api, env["agreement_id"],
                                 agreement["version"])
    assert_holdback_split(released, retained=14160, released=9160, applied=5000)
    assert_status(released, "HOLDBACK_RELEASED")


def test_holdback_release_the_day_before_eligibility_is_refused(
        api, completed_transfer):
    """
    The eligibility date is inclusive: the day before it the same release is
    refused and no holdback bucket moves.

    PRD: "The money must be eligible: the bound servicing transfer must be `COMPLETED` and the current logical clock date must have reached `holdback_release_eligible_at`, else `ERR_HOLDBACK_NOT_ELIGIBLE` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/complaint_ratio_exactly_at_tier_one_upper_bound_releases_in_full
    """
    env = completed_transfer
    F.set_clock(api, CLOCK_DAY_BEFORE_ELIGIBLE)
    agreement = refresh_agreement(api, env)
    assert agreement["holdback_release_eligible_at"] == ELIGIBLE_DATE

    response = _release(api, env["agreement_id"], agreement["version"])
    validate_error(response, ERR_HOLDBACK_NOT_ELIGIBLE, 409)

    after = refresh_agreement(api, env)
    assert_status(after, "SETTLED")
    assert after["version"] == agreement["version"]
    assert_holdback_split(after, retained=SIZED_HOLDBACK_CENTS, released=0,
                          applied=0)


def test_holdback_release_by_the_attesting_officer_is_refused(
        api, completed_transfer):
    """
    The officer who certified the borrower notices cannot sign the same holdback
    back to the seller.

    PRD: "When a `ComplianceOfficer` releases holdback, the acting `X-User-ID` must differ from the `notice_attested_by_user_id` recorded on the bound servicing transfer."

    Design: Difficulty/boundary_precision_check/complaint_ratio_exactly_at_tier_one_upper_bound_releases_in_full
    """
    env = completed_transfer
    transfer = refresh_transfer(api, env)
    assert transfer["notice_attested_by_user_id"] == C.COMPLIANCE_ID

    F.set_clock(api, CLOCK_ELIGIBLE)
    agreement = refresh_agreement(api, env)
    response = _release(api, env["agreement_id"], agreement["version"],
                        headers=U.COMPLIANCE)
    validate_error(response, ERR_SEGREGATION_OF_DUTIES, 403)

    after = refresh_agreement(api, env)
    assert after["version"] == agreement["version"]
    assert_holdback_split(after, retained=SIZED_HOLDBACK_CENTS, released=0,
                          applied=0)


# ---------------------------------------------------------------------------
# The zero-included-line boundary on publication
# ---------------------------------------------------------------------------
def _exclude_whole_tape(api: ApiClient, env: JsonDict) -> None:
    """Pull every line of the cut tape, leaving no included line behind."""
    reasons = ["DOCUMENT_DEFECT", "DOCUMENT_DEFECT", "LITIGATION",
               "INVESTOR_RESTRICTION"]
    for line, reason in zip(env["tape_lines"], reasons):
        F.set_tape_line_inclusion(api, line["id"], False,
                                  exclusion_reason=reason)


def test_publication_is_refused_when_the_tape_holds_zero_included_lines(
        api, stratified_package):
    """
    A package whose every line has been pulled cannot be published and is not
    priced: it stays stratified with no reserve and no publication stamp.

    PRD: "Third, the tape must not be empty: a package whose `tape_loan_count` is exactly 0 because every line was excluded cannot be published, and is refused with `ERR_TAPE_EMPTY` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/empty_tape_boundary_blocks_publication_at_zero_included_lines
    """
    env = stratified_package
    assert env["package"]["stratum_count"] == 4
    assert env["package"]["tape_loan_count"] == 4
    assert env["package"]["tape_upb_cents"] == TAPE_UPB_CENTS

    _exclude_whole_tape(api, env)
    emptied = refresh_package(api, env)
    assert emptied["tape_loan_count"] == 0
    assert emptied["tape_upb_cents"] == 0
    assert emptied["stratum_count"] == 0
    assert_status(emptied, "STRATIFIED")

    response = api.publish_bid_package(env["package_id"], U.MANAGER)
    validate_error(response, ERR_TAPE_EMPTY, 422)

    after = refresh_package(api, env)
    assert_status(after, "STRATIFIED")
    assert after["published_at"] is None
    assert after["reserve_price_cents"] is None
    assert after["version"] == emptied["version"]


def test_publication_succeeds_at_one_included_line_with_a_pro_rata_reserve(
        api, stratified_package):
    """
    Restoring a single line carries the tape one step past the empty boundary, and
    the reserve scales down by that line's share of the frozen pool balance.

    PRD: "The reserve is the bound run's `value_cents`, multiplied by the package's `reserve_price_floor_pct` and divided by 100, multiplied by the package's `tape_upb_cents` and divided by the portfolio's `total_upb_cents` as frozen at tape lock, with a single half-up rounding to whole cents applied only at the very end and no intermediate rounding."

    Design: Difficulty/boundary_precision_check/empty_tape_boundary_blocks_publication_at_zero_included_lines
    """
    env = stratified_package
    _exclude_whole_tape(api, env)
    assert refresh_package(api, env)["tape_loan_count"] == 0

    F.set_tape_line_inclusion(api, env["tape_lines"][0]["id"], True)
    restored = refresh_package(api, env)
    assert restored["tape_loan_count"] == 1
    assert restored["tape_upb_cents"] == ONE_LOAN_UPB_CENTS
    assert restored["stratum_count"] == 1

    # 171576 * 95 / 100 * 10000050 / 40000200 with one half-up rounding at the
    # very end is 40749 cents.
    derived = round_half_up(
        Decimal(C.POOL_T_STATIC_VALUE_CENTS)
        * Decimal(C.RESERVE_PRICE_FLOOR_PCT) / Decimal(100)
        * Decimal(ONE_LOAN_UPB_CENTS) / Decimal(C.POOL_T_TOTAL_UPB_CENTS))
    assert derived == ONE_LINE_RESERVE_CENTS

    published = F.publish(api, env["package_id"])
    assert_status(published, "PUBLISHED")
    assert published["reserve_price_cents"] == ONE_LINE_RESERVE_CENTS
    assert published["published_at"] is not None

    # Excluding lines never rewrites the frozen pool total or the valuation.
    portfolio = F.read_portfolio(api, env["portfolio_id"])
    assert portfolio["total_upb_cents"] == C.POOL_T_TOTAL_UPB_CENTS
    run = F.read_valuation_run(api, env["valuation_run_id"])
    assert run["value_cents"] == C.POOL_T_STATIC_VALUE_CENTS
