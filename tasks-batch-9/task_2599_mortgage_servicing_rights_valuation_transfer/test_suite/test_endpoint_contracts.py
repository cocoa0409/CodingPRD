"""
Endpoint-level contracts of the mortgage servicing rights transfer desk.

The endpoints pinned here are the ones whose contract is about the call itself
rather than about one field of one row: the logical-clock control that sits
outside the business prefix and re-evaluates every temporal rule at once, the
computed hedge-effectiveness read, the loan-level tape-line edit that is
reversible before publication and frozen after it, the counterparty suspension
that gates later bids without disturbing earlier ones, the borrower-notice
history reachable through a loan as well as through its transfer, and the
holdback clawback that only becomes available once a release has happened.
"""

from test_helpers import (
    C, F, U,
    ApiClient, JsonDict,
    ERR_AGREEMENT_INVALID_STATE,
    ERR_BID_DEADLINE_PASSED,
    ERR_BIDDER_NOT_ELIGIBLE,
    ERR_CLAWBACK_EXCEEDS_RELEASED,
    ERR_INVALID_REQUEST,
    ERR_PACKAGE_INVALID_STATE,
    ERR_UNAUTHENTICATED,
    assert_holdback_split,
    assert_status,
    build_completed_transfer,
    build_live_bid,
    build_published_package,
    build_settled_trade,
    build_stratified_package,
    build_valued_portfolio,
    data_of,
    is_iso8601_timestamp,
    refresh_agreement,
    refresh_package,
    rows_of,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_JUST_BEFORE_DEADLINE = "2026-08-14T23:59:59Z"
CLOCK_ELIGIBILITY_DAY = "2026-10-01T00:00:00Z"
CLOCK_AFTER_TRANSFER = "2026-09-03T00:00:00Z"


def _tape_line_for(env: JsonDict, loan_id: str) -> JsonDict:
    """The single tape line the package under test cut for one loan."""
    matches = [line for line in env["tape_lines"] if line["loan_id"] == loan_id]
    assert len(matches) == 1, (
        f"expected one tape line for loan {loan_id}, found {len(matches)}"
    )
    return matches[0]


def _released_holdback_env(api: ApiClient) -> JsonDict:
    """A completed transfer whose whole holdback has already been released."""
    env = build_completed_transfer(api)
    F.set_clock(api, CLOCK_ELIGIBILITY_DAY)
    refresh_agreement(api, env)
    env["agreement"] = F.release_holdback(
        api, env["agreement_id"], env["agreement_version"])
    env["agreement_version"] = env["agreement"]["version"]
    return env


def _noticed_loan_env(api: ApiClient) -> JsonDict:
    """A settled trade whose first borrower has a seller and a buyer notice."""
    env = build_settled_trade(api)
    env["seller_notice"] = F.send_notice(
        api, env["transfer_id"], env["loan_ids"][0], env["seller_id"],
        notice_type="TRANSFEROR_15DAY", effective_date=C.TRANSFER_DATE)
    F.set_clock(api, CLOCK_AFTER_TRANSFER)
    env["buyer_notice"] = F.send_notice(
        api, env["transfer_id"], env["loan_ids"][0], env["buyer_id"],
        notice_type="TRANSFEREE_15DAY", effective_date=C.TRANSFER_DATE)
    return env


# ---------------------------------------------------------------------------
# The logical clock, and the temporal rules that read it
# ---------------------------------------------------------------------------
def test_clock_move_writes_no_row_but_closes_the_bid_window(api: ApiClient):
    """
    Moving the clock past a package's deadline mutates nothing yet refuses the
    very next bid on that otherwise untouched package.

    PRD: "It is the one endpoint that does not require authentication headers, though it is authorized for `PlatformAdmin`; it changes no entity state."

    Design: Corner/endpoints/logical_clock_endpoint_moves_every_temporal_rule_at_once
    """
    env = build_published_package(api)
    before = F.read_package(api, env["package_id"])

    moved = validate_success(
        api.set_current_utc({"to_iso8601": C.CLOCK_AUG_20}, U.ADMIN))
    assert is_iso8601_timestamp(moved["current_utc"])
    assert moved["current_utc"].startswith("2026-08-20T00:00:00")

    after = F.read_package(api, env["package_id"])
    assert after["version"] == before["version"]
    assert after["updated_at"] == before["updated_at"]
    assert after["status"] == "PUBLISHED"

    refused = api.create_bid(
        env["package_id"],
        {"bidder_id": env["buyer_id"], "price_bps": 118, "holdback_pct": 6,
         "expected_bid_package_version": after["version"]},
        U.make_buyer_headers(env["buyer_id"]))
    validate_error(refused, ERR_BID_DEADLINE_PASSED, 422)


def test_marketing_window_is_inclusive_at_the_start_and_exclusive_at_the_end(
        api: ApiClient):
    """
    A bid lands on the marketing_start_at instant and one second before the
    deadline, but is refused on the deadline instant itself.

    PRD: "The window's start is inclusive and its end is exclusive: bids are refused at or after the deadline instant, and `bid_deadline_at` must be strictly greater than `marketing_start_at`."

    Design: Corner/endpoints/logical_clock_endpoint_moves_every_temporal_rule_at_once
    """
    env = build_published_package(api)

    # The default clock stands exactly on marketing_start_at.
    opening_bid = F.submit_bid(api, env["package_id"], env["buyer_id"],
                               env["package_version"], price_bps=118)
    assert opening_bid["status"] == "SUBMITTED"
    assert opening_bid["bid_value_cents"] == 472002

    F.set_clock(api, CLOCK_JUST_BEFORE_DEADLINE)
    package = refresh_package(api, env)
    last_bid = F.submit_bid(api, env["package_id"], env["buyer_id"],
                            package["version"], price_bps=118)
    assert last_bid["status"] == "SUBMITTED"

    F.set_clock(api, C.CLOCK_AUG_15)
    package = refresh_package(api, env)
    refused = api.create_bid(
        env["package_id"],
        {"bidder_id": env["buyer_id"], "price_bps": 118, "holdback_pct": 6,
         "expected_bid_package_version": package["version"]},
        U.make_buyer_headers(env["buyer_id"]))
    validate_error(refused, ERR_BID_DEADLINE_PASSED, 422)


def test_clock_control_needs_no_caller_identity_unlike_the_business_prefix(
        api: ApiClient):
    """
    The clock accepts a request carrying no caller identity at all, while a
    business endpoint refuses the same omission.

    PRD: "A request with a missing or empty `X-User-ID` is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/endpoints/logical_clock_endpoint_moves_every_temporal_rule_at_once
    """
    moved = validate_success(
        api.set_current_utc({"to_iso8601": C.CLOCK_AUG_10}, {}))
    assert moved["current_utc"].startswith("2026-08-10T00:00:00")

    anonymous = api.list_counterparties(U.headers_without_user_id())
    validate_error(anonymous, ERR_UNAUTHENTICATED, 401)


# ---------------------------------------------------------------------------
# The hedge-effectiveness computed read
# ---------------------------------------------------------------------------
def test_hedge_effectiveness_read_is_repeatable_and_side_effect_free(
        api: ApiClient):
    """
    Two identical hedge-effectiveness reads answer identically and leave the
    portfolio and the hedge position exactly as they were.

    PRD: "The mark is a pure function of the current curve."

    Design: Corner/endpoints/hedge_effectiveness_read_is_pure_and_repeatable
    """
    env = build_valued_portfolio(api)
    hedge = F.open_hedge(api, env["portfolio_id"],
                         instrument="SWAPTION_RECEIVER",
                         notional_cents=260000, hedge_ratio_pct=60)
    portfolio_before = F.read_portfolio(api, env["portfolio_id"])

    first = data_of(api.get_hedge_effectiveness(
        env["portfolio_id"], U.make_seller_headers(env["seller_id"])))
    second = data_of(
        api.get_hedge_effectiveness(env["portfolio_id"], U.HEDGE))
    assert first == second

    portfolio_after = F.read_portfolio(api, env["portfolio_id"])
    assert portfolio_after["version"] == portfolio_before["version"]
    assert portfolio_after["updated_at"] == portfolio_before["updated_at"]

    hedge_after = F.read_hedge(api, hedge["id"])
    assert hedge_after["version"] == hedge["version"]
    assert hedge_after["mark_to_market_cents"] == 0


def test_hedge_effectiveness_reports_both_legs_at_the_entry_curve(
        api: ApiClient):
    """
    At the curve the hedge was opened against, the read names the effective
    valuation run, its value, a zero aggregate mark and the active base rate.

    PRD: "A hedge-effectiveness read on a portfolio reports the two legs side by side: `effective_valuation_run_id` (the run selected as the portfolio's effective valuation, or null when none is eligible), `msr_value_cents` (that run's `value_cents`, or 0 when there is none), `open_hedge_mtm_cents` (the sum of `mark_to_market_cents` over that portfolio's `OPEN` positions), `net_hedged_position_cents` (the MSR value plus that aggregate mark) and `current_base_rate_bps` (the base rate of the currently active snapshot)."

    Design: Corner/endpoints/hedge_effectiveness_read_is_pure_and_repeatable
    """
    env = build_valued_portfolio(api)
    F.open_hedge(api, env["portfolio_id"], instrument="SWAPTION_RECEIVER",
                 notional_cents=260000, hedge_ratio_pct=60)

    data = data_of(api.get_hedge_effectiveness(env["portfolio_id"], U.HEDGE))
    assert data["effective_valuation_run_id"] == env["valuation_run_id"]
    assert data["msr_value_cents"] == 171576
    assert data["open_hedge_mtm_cents"] == 0
    assert data["net_hedged_position_cents"] == 171576
    assert data["current_base_rate_bps"] == 4000


def test_hedge_effectiveness_aggregates_open_positions_after_a_curve_move(
        api: ApiClient):
    """
    A second open position only widens the aggregate mark, and a curve move
    re-marks both legs without disturbing either position's entry terms.

    PRD: "Take `notional_cents`, multiply by `hedge_ratio_pct` and divide by 100 to get the applied notional; multiply by the instrument's option-adjusted duration factor, which is 4.5 for `TBA_LONG`, 6.0 for `SWAPTION_RECEIVER` and 5.5 for `TREASURY_FUTURE_LONG`; multiply by the difference between `entry_base_rate_bps` and the current active snapshot's base rate, taking entry less current so that a rate rise produces a negative mark; divide by 10,000; and round half up to whole cents on the magnitude, so a computed −0.5 cent becomes −1 cent."

    Design: Corner/endpoints/hedge_effectiveness_read_is_pure_and_repeatable
    """
    env = build_valued_portfolio(api)
    receiver = F.open_hedge(api, env["portfolio_id"],
                            instrument="SWAPTION_RECEIVER",
                            notional_cents=260000, hedge_ratio_pct=60)
    tba = F.open_hedge(api, env["portfolio_id"], instrument="TBA_LONG",
                       notional_cents=260000, hedge_ratio_pct=60)

    at_entry = data_of(
        api.get_hedge_effectiveness(env["portfolio_id"], U.HEDGE))
    assert at_entry["open_hedge_mtm_cents"] == 0
    assert F.read_hedge(api, receiver["id"])["entry_base_rate_bps"] == 4000
    assert F.read_hedge(api, receiver["id"])["notional_cents"] == 260000

    F.create_rate_curve(api, C.CURVE_C2)
    assert F.read_hedge(api, receiver["id"])["mark_to_market_cents"] == -4680
    assert F.read_hedge(api, tba["id"])["mark_to_market_cents"] == -3510

    after = data_of(api.get_hedge_effectiveness(env["portfolio_id"], U.HEDGE))
    assert after["current_base_rate_bps"] == 4050
    assert after["open_hedge_mtm_cents"] == -8190
    assert after["msr_value_cents"] == 171576
    assert after["net_hedged_position_cents"] == 163386


# ---------------------------------------------------------------------------
# Scrubbing the loan-level tape
# ---------------------------------------------------------------------------
def test_pulling_a_tape_line_shrinks_the_package_aggregates(api: ApiClient):
    """
    Excluding one line records its reason and shrinks the package's balance,
    loan count and stratum count together.

    PRD: "Each edit increments the tape line's own `version`, recomputes the package's `tape_upb_cents`, `tape_loan_count` and `stratum_count`, and increments the package's `version` by 1."

    Design: Corner/endpoints/tape_line_patch_re_includes_a_pulled_loan_and_restores_the_tape
    """
    env = build_stratified_package(api)
    assert env["package"]["tape_upb_cents"] == 40000200
    assert env["package"]["tape_loan_count"] == 4
    assert env["package"]["stratum_count"] == 4

    line = _tape_line_for(env, env["loan_ids"][2])
    assert line["stratum_label"] == "FL"

    pulled = F.set_tape_line_inclusion(api, line["id"], False,
                                       exclusion_reason="LITIGATION")
    assert pulled["included"] is False
    assert pulled["exclusion_reason"] == "LITIGATION"
    assert pulled["version"] == line["version"] + 1

    package = F.read_package(api, env["package_id"])
    assert package["tape_upb_cents"] == 30000150
    assert package["tape_loan_count"] == 3
    assert package["stratum_count"] == 3
    assert package["version"] == env["package"]["version"] + 1


def test_re_including_a_pulled_tape_line_restores_the_tape_exactly(
        api: ApiClient):
    """
    Restoring the pulled line clears its exclusion reason, keeps its frozen
    snapshot and stratum, and puts the package's aggregates back where they were.

    PRD: "While the package is `STRATIFIED`, a `ValuationAnalyst` may pull or restore individual lines by setting `included`, supplying `exclusion_reason` — `DOCUMENT_DEFECT`, `LITIGATION` or `INVESTOR_RESTRICTION` — which is required whenever `included` is set to false and must be absent whenever `included` is true."

    Design: Corner/endpoints/tape_line_patch_re_includes_a_pulled_loan_and_restores_the_tape
    """
    env = build_stratified_package(api)
    line = _tape_line_for(env, env["loan_ids"][2])
    F.set_tape_line_inclusion(api, line["id"], False,
                              exclusion_reason="LITIGATION")

    restored = F.set_tape_line_inclusion(api, line["id"], True)
    assert restored["included"] is True
    assert restored["exclusion_reason"] is None
    assert restored["upb_snapshot_cents"] == 10000050
    assert restored["stratum_label"] == "FL"

    package = F.read_package(api, env["package_id"])
    assert package["tape_upb_cents"] == 40000200
    assert package["tape_loan_count"] == 4
    assert package["stratum_count"] == 4


def test_re_included_tape_prices_the_reserve_over_the_whole_pool(
        api: ApiClient):
    """
    Publishing after a pull and a restore stamps the reserve over the full tape
    balance, as if the line had never been pulled.

    PRD: "The reserve is the bound run's `value_cents`, multiplied by the package's `reserve_price_floor_pct` and divided by 100, multiplied by the package's `tape_upb_cents` and divided by the portfolio's `total_upb_cents` as frozen at tape lock, with a single half-up rounding to whole cents applied only at the very end and no intermediate rounding."

    Design: Corner/endpoints/tape_line_patch_re_includes_a_pulled_loan_and_restores_the_tape
    """
    env = build_stratified_package(api)
    line = _tape_line_for(env, env["loan_ids"][2])
    F.set_tape_line_inclusion(api, line["id"], False,
                              exclusion_reason="DOCUMENT_DEFECT")
    F.set_tape_line_inclusion(api, line["id"], True)

    published = F.publish(api, env["package_id"])
    assert published["tape_upb_cents"] == 40000200
    assert published["reserve_price_cents"] == 162997


def test_tape_line_edit_is_refused_once_the_package_is_published(
        api: ApiClient):
    """
    The tape freezes at publication: the same edit that worked a moment earlier
    is refused and leaves the package's aggregates alone.

    PRD: "An edit attempted on a package that is not `STRATIFIED` is refused with `ERR_PACKAGE_INVALID_STATE`."

    Design: Corner/endpoints/tape_line_patch_re_includes_a_pulled_loan_and_restores_the_tape
    """
    env = build_published_package(api)
    line = _tape_line_for(env, env["loan_ids"][0])

    refused = api.patch_tape_line(
        line["id"],
        {"included": False, "exclusion_reason": "DOCUMENT_DEFECT"},
        U.ANALYST)
    validate_error(refused, ERR_PACKAGE_INVALID_STATE, 409)

    unchanged = F.read_package(api, env["package_id"])
    assert unchanged["tape_upb_cents"] == 40000200
    assert unchanged["tape_loan_count"] == 4
    still_included = data_of(api.get_tape_line(line["id"], U.ANALYST))
    assert still_included["included"] is True
    assert still_included["exclusion_reason"] is None


def test_tape_line_edit_pairs_the_exclusion_reason_with_the_flag(
        api: ApiClient):
    """
    An inclusion carrying a reason and an exclusion carrying none are both
    shape violations.

    PRD: "While the package is `STRATIFIED`, a `ValuationAnalyst` may pull or restore individual lines by setting `included`, supplying `exclusion_reason` — `DOCUMENT_DEFECT`, `LITIGATION` or `INVESTOR_RESTRICTION` — which is required whenever `included` is set to false and must be absent whenever `included` is true."

    Design: Corner/endpoints/tape_line_patch_re_includes_a_pulled_loan_and_restores_the_tape
    """
    env = build_stratified_package(api)
    line = _tape_line_for(env, env["loan_ids"][1])

    with_reason = api.patch_tape_line(
        line["id"], {"included": True, "exclusion_reason": "LITIGATION"},
        U.ANALYST)
    validate_error(with_reason, ERR_INVALID_REQUEST, 422)

    without_reason = api.patch_tape_line(
        line["id"], {"included": False}, U.ANALYST)
    validate_error(without_reason, ERR_INVALID_REQUEST, 422)

    untouched = data_of(api.get_tape_line(line["id"], U.ANALYST))
    assert untouched["included"] is True
    assert untouched["version"] == line["version"]


# ---------------------------------------------------------------------------
# Counterparty suspension as a forward-looking gate
# ---------------------------------------------------------------------------
def test_suspension_stamps_the_counterparty_and_blocks_a_later_bid(
        api: ApiClient):
    """
    Suspension is visible as a status plus a timestamp, and the next bid from
    that institution on the very same package is refused.

    PRD: "What suspension does is close two gates — a `SUSPENDED` counterparty may no longer be named as a bidder, and it may no longer be carried through to award."

    Design: Corner/endpoints/counterparty_suspension_gates_every_later_bid
    """
    env = build_live_bid(api)

    suspended = F.suspend_counterparty(api, env["buyer_id"])
    assert suspended["status"] == "SUSPENDED"
    assert is_iso8601_timestamp(suspended["suspended_at"])
    assert suspended["suspended_at"].startswith("2026-08-01T00:00:00")

    package = refresh_package(api, env)
    refused = api.create_bid(
        env["package_id"],
        {"bidder_id": env["buyer_id"], "price_bps": 121, "holdback_pct": 6,
         "expected_bid_package_version": package["version"]},
        U.make_buyer_headers(env["buyer_id"]))
    validate_error(refused, ERR_BIDDER_NOT_ELIGIBLE, 422)
    assert F.read_package(api, env["package_id"])["bid_count"] == 1


def test_suspended_counterparties_are_discoverable_by_status(api: ApiClient):
    """
    The counterparty collection filtered on the suspended status returns only
    the institution that was suspended.

    PRD: "The counterparty collection filters on `role_type` and `status`."

    Design: Corner/endpoints/counterparty_suspension_gates_every_later_bid
    """
    env = build_live_bid(api)
    F.suspend_counterparty(api, env["buyer_id"])

    rows = rows_of(api.list_counterparties(U.ADMIN, {"status": "SUSPENDED"}))
    assert [row["id"] for row in rows] == [env["buyer_id"]]

    active = rows_of(api.list_counterparties(U.ADMIN, {"status": "ACTIVE"}))
    assert [row["id"] for row in active] == [env["seller_id"]]


def test_suspension_leaves_an_existing_bid_exactly_as_it_was(api: ApiClient):
    """
    A bid already on the table keeps its state, its economics and its version
    when its bidder is suspended.

    PRD: "Suspension is forward-looking: bids already on the table are left exactly as they are, so nothing is retroactively voided."

    Design: Corner/endpoints/counterparty_suspension_gates_every_later_bid
    """
    env = build_live_bid(api)
    before = F.read_bid(api, env["bid_id"])
    assert before["status"] == "SUBMITTED"
    assert before["bid_value_cents"] == 472002

    F.suspend_counterparty(api, env["buyer_id"])

    after = F.read_bid(api, env["bid_id"])
    assert after["status"] == "SUBMITTED"
    assert after["bid_value_cents"] == 472002
    assert after["version"] == before["version"]
    assert after["updated_at"] == before["updated_at"]


def test_award_re_checks_the_eligibility_of_a_suspended_bidder(
        api: ApiClient):
    """
    The trade cannot be carried through to award on a bid whose institution was
    suspended after it bid, and the refusal changes nothing.

    PRD: "The package must be `PUBLISHED`; the nominated bid must belong to that package and be `SUBMITTED` or `REVISED`; the nominated bid's institution must still be eligible, so a bidder suspended since it bid is refused here with `ERR_BIDDER_NOT_ELIGIBLE` rather than being retroactively voided; and the acting operator must not be the one who produced the mark, as §2.10 requires."

    Design: Corner/endpoints/counterparty_suspension_gates_every_later_bid
    """
    env = build_live_bid(api)
    F.suspend_counterparty(api, env["buyer_id"])

    refused = api.award_bid_package(
        env["package_id"],
        {"winning_bid_id": env["bid_id"], "rep_warrant_days": 30,
         "indemnification_days": 45},
        U.MANAGER)
    validate_error(refused, ERR_BIDDER_NOT_ELIGIBLE, 422)

    assert F.read_package(api, env["package_id"])["status"] == "PUBLISHED"
    assert F.read_bid(api, env["bid_id"])["status"] == "SUBMITTED"
    assert F.read_portfolio(api, env["portfolio_id"])["status"] == "TAPE_LOCKED"


# ---------------------------------------------------------------------------
# Borrower-notice history, read through the loan and through the transfer
# ---------------------------------------------------------------------------
def test_loan_notice_history_lists_both_sides_in_send_order(api: ApiClient):
    """
    The borrower file carries the seller's pre-transfer notice and the buyer's
    post-transfer notice, oldest first, each stamped with the side that sent it.

    PRD: "An accepted notice is created with `servicing_transfer_id`, `sent_at` set to the current logical clock, and `sent_by_role` recording which side issued it, either `SellerServicer` or `BuyerServicer`."

    Design: Corner/endpoints/loan_notice_history_is_readable_through_the_loan
    """
    env = _noticed_loan_env(api)

    rows, meta = validate_paginated(api.list_loan_notices(
        env["loan_ids"][0], U.make_buyer_headers(env["buyer_id"]),
        {"limit": 10, "offset": 0}))
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [env["seller_notice"]["id"],
                                           env["buyer_notice"]["id"]]
    assert rows[0]["notice_type"] == "TRANSFEROR_15DAY"
    assert rows[0]["sent_by_role"] == "SellerServicer"
    assert rows[1]["notice_type"] == "TRANSFEREE_15DAY"
    assert rows[1]["sent_by_role"] == "BuyerServicer"


def test_transferor_notice_lead_days_count_forward_to_the_effective_date(
        api: ApiClient):
    """
    The seller's notice, sent a month ahead of the transfer date, carries a
    positive lead and reads compliant.

    PRD: "For a `TRANSFEROR_15DAY` or a `COMBINED` notice, `lead_days` is the number of calendar days from the date the notice was sent to the effective date — the effective date less the sent date — and `compliance_status` is `COMPLIANT` when `lead_days` is at least 15, and `LATE` otherwise."

    Design: Corner/endpoints/loan_notice_history_is_readable_through_the_loan
    """
    env = _noticed_loan_env(api)
    notice = env["seller_notice"]
    assert notice["notice_type"] == "TRANSFEROR_15DAY"
    assert notice["lead_days"] == 31
    assert notice["compliance_status"] == "COMPLIANT"


def test_transferee_notice_lead_days_count_back_from_the_effective_date(
        api: ApiClient):
    """
    The buyer's notice, sent two days after the transfer took effect, carries a
    lead of two days and reads compliant.

    PRD: "For a `TRANSFEREE_15DAY` notice the subtraction is reversed: `lead_days` is the sent date less the effective date, and `compliance_status` is `COMPLIANT` when `lead_days` is at least 0 and at most 15, and `LATE` otherwise."

    Design: Corner/endpoints/loan_notice_history_is_readable_through_the_loan
    """
    env = _noticed_loan_env(api)
    notice = env["buyer_notice"]
    assert notice["notice_type"] == "TRANSFEREE_15DAY"
    assert notice["lead_days"] == 2
    assert notice["compliance_status"] == "COMPLIANT"


def test_loan_notice_history_filters_by_type_and_is_scoped_to_the_loan(
        api: ApiClient):
    """
    The loan-side read narrows to one notice type and shows nothing for a
    borrower who was never noticed.

    PRD: "Borrower-notice collections, whether scoped to a transfer or to a loan, filter on `notice_type` and `compliance_status`, and the transfer-scoped listing also filters on `loan_id`."

    Design: Corner/endpoints/loan_notice_history_is_readable_through_the_loan
    """
    env = _noticed_loan_env(api)

    transferee = rows_of(api.list_loan_notices(
        env["loan_ids"][0], U.COMPLIANCE,
        {"notice_type": "TRANSFEREE_15DAY"}))
    assert [row["id"] for row in transferee] == [env["buyer_notice"]["id"]]

    compliant = rows_of(api.list_loan_notices(
        env["loan_ids"][0], U.COMPLIANCE,
        {"compliance_status": "COMPLIANT"}))
    assert len(compliant) == 2

    unnoticed = rows_of(
        api.list_loan_notices(env["loan_ids"][1], U.COMPLIANCE))
    assert unnoticed == []


def test_the_same_notices_are_reachable_through_the_transfer(api: ApiClient):
    """
    The transfer-scoped listing, narrowed to the same borrower, returns exactly
    the rows the loan-scoped listing returned.

    PRD: "Borrower-notice collections, whether scoped to a transfer or to a loan, filter on `notice_type` and `compliance_status`, and the transfer-scoped listing also filters on `loan_id`."

    Design: Corner/endpoints/loan_notice_history_is_readable_through_the_loan
    """
    env = _noticed_loan_env(api)

    through_loan = rows_of(
        api.list_loan_notices(env["loan_ids"][0], U.MANAGER))
    through_transfer = rows_of(api.list_transfer_notices(
        env["transfer_id"], U.MANAGER, {"loan_id": env["loan_ids"][0]}))
    assert [row["id"] for row in through_transfer] == \
        [row["id"] for row in through_loan]
    assert [row["id"] for row in through_transfer] == \
        [env["seller_notice"]["id"], env["buyer_notice"]["id"]]


# ---------------------------------------------------------------------------
# The holdback clawback, conditional on a prior release
# ---------------------------------------------------------------------------
def test_full_release_before_indemnification_expiry_lands_in_holdback_released(
        api: ApiClient):
    """
    Releasing the whole holdback while the indemnification period is still
    running leaves the agreement clawback-able rather than closed.

    PRD: "A release that exhausts the balance *before* the indemnification period has run does **not** close the agreement; it lands in `HOLDBACK_RELEASED`, where it can still be clawed back."

    Design: Corner/endpoints/holdback_clawback_is_conditional_on_a_prior_release
    """
    env = _released_holdback_env(api)
    agreement = env["agreement"]

    assert agreement["holdback_cents"] == 28320
    assert agreement["holdback_released_cents"] == 28320
    assert agreement["holdback_retained_cents"] == 0
    assert_status(agreement, "HOLDBACK_RELEASED")
    assert_holdback_split(agreement, retained=0, released=28320, applied=0)


def test_clawback_is_bounded_above_by_the_released_balance_and_below_by_a_cent(
        api: ApiClient):
    """
    One cent above the released total, exactly nothing, and a negative amount
    are all refused, and none of them moves a bucket.

    PRD: "The amount must be greater than 0 and must not exceed `holdback_released_cents`, else `ERR_CLAWBACK_EXCEEDS_RELEASED` (HTTP 422)."

    Design: Corner/endpoints/holdback_clawback_is_conditional_on_a_prior_release
    """
    env = _released_holdback_env(api)

    for amount in (28321, 0, -1):
        refused = api.create_holdback_clawback(
            env["agreement_id"],
            {"amount_cents": amount,
             "reason": "post-transfer escrow shortfall under review"},
            U.COMPLIANCE_2)
        validate_error(refused, ERR_CLAWBACK_EXCEEDS_RELEASED, 422)

    unchanged = F.read_agreement(api, env["agreement_id"])
    assert unchanged["holdback_released_cents"] == 28320
    assert unchanged["holdback_retained_cents"] == 0
    assert unchanged["version"] == env["agreement_version"]
    assert_status(unchanged, "HOLDBACK_RELEASED")


def test_a_full_clawback_rewinds_the_agreement_to_settled(api: ApiClient):
    """
    Returning the entire released balance moves the money back into the
    retained bucket and puts the release decision back on the table.

    PRD: "A clawback that returns the entire released balance — leaving `holdback_released_cents` at 0 — rewinds the agreement `HOLDBACK_RELEASED → SETTLED` so the release decision can be taken again; a partial clawback leaves the agreement in `HOLDBACK_RELEASED`."

    Design: Corner/endpoints/holdback_clawback_is_conditional_on_a_prior_release
    """
    env = _released_holdback_env(api)

    clawed = F.clawback_holdback(api, env["agreement_id"], 28320)
    assert clawed["holdback_released_cents"] == 0
    assert clawed["holdback_retained_cents"] == 28320
    assert clawed["holdback_cents"] == 28320
    assert_status(clawed, "SETTLED")
    assert_holdback_split(clawed, retained=28320, released=0, applied=0)


def test_a_partial_clawback_stays_in_holdback_released(api: ApiClient):
    """
    A clawback that returns only part of the wire redistributes the buckets and
    leaves the agreement where it was.

    PRD: "The clawback subtracts `amount_cents` from `holdback_released_cents` and adds the same amount to `holdback_retained_cents`, so no value is created or destroyed and the holdback identity is preserved exactly."

    Design: Corner/endpoints/holdback_clawback_is_conditional_on_a_prior_release
    """
    env = _released_holdback_env(api)

    clawed = F.clawback_holdback(api, env["agreement_id"], 10000)
    assert clawed["holdback_released_cents"] == 18320
    assert clawed["holdback_retained_cents"] == 10000
    assert clawed["holdback_cents"] == 28320
    assert_status(clawed, "HOLDBACK_RELEASED")
    assert_holdback_split(clawed, retained=10000, released=18320, applied=0)


def test_clawback_before_any_release_is_refused_on_state_grounds(
        api: ApiClient):
    """
    A settled agreement that has never released anything has nothing to claw
    back, and the attempt is turned away on state grounds.

    PRD: "A `ComplianceOfficer` claws back against a `HOLDBACK_RELEASED` agreement, supplying `amount_cents` and a `reason`."

    Design: Corner/endpoints/holdback_clawback_is_conditional_on_a_prior_release
    """
    env = build_settled_trade(api)
    agreement = F.read_agreement(api, env["agreement_id"])
    assert_status(agreement, "SETTLED")
    assert agreement["holdback_released_cents"] == 0

    refused = api.create_holdback_clawback(
        env["agreement_id"],
        {"amount_cents": 100, "reason": "no release has been taken yet"},
        U.COMPLIANCE_2)
    validate_error(refused, ERR_AGREEMENT_INVALID_STATE, 409)

    after = F.read_agreement(api, env["agreement_id"])
    assert after["version"] == agreement["version"]
    assert_holdback_split(after, retained=28320, released=0, applied=0)
