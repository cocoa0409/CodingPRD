"""
Version tokens on the pricing-sensitive writes, and immediate visibility.

Two properties of the transfer desk are pinned here. First, the three writes
whose economics are only meaningful against an observed parent state — a
valuation run against a portfolio, a bid against a bid package and a holdback
release against a purchase agreement — each spend exactly one version token:
the token the caller just used successfully is refused on the next call, the
refusal leaves nothing behind, and the operation succeeds again once the parent
has been re-read. Second, every derived figure the desk computes is already in
the response of the write that caused it, and every cross-entity consequence of
that write is visible on the very first read afterwards, with no settling step.
"""

from test_helpers import (
    C,
    F,
    U,
    ApiClient,
    ERR_HOLDBACK_EXHAUSTED,
    ERR_HOLDBACK_NOT_ELIGIBLE,
    ERR_INVALID_REQUEST,
    ERR_STALE_AGREEMENT_VERSION,
    ERR_STALE_BID_PACKAGE_VERSION,
    ERR_STALE_PORTFOLIO_VERSION,
    JsonDict,
    assert_holdback_split,
    assert_readiness,
    assert_status,
    assert_stratum_breakdown,
    bps_of_upb,
    data_of,
    ids_of,
    refresh_agreement,
    refresh_package,
    refresh_portfolio,
    rows_of,
    validate_error,
    validate_success,
)

# Pool T priced at 118 basis points of tape unpaid balance: a single rounding
# over the whole tape for the bid, and one rounding per state stratum for the
# contractual purchase price.
BID_VALUE_AT_118_BPS = 472002
BID_VALUE_AT_121_BPS = 484002
PURCHASE_PRICE_CENTS = 472004
HOLDBACK_AT_6_PCT_CENTS = 28320
SETTLEMENT_WIRE_CENTS = PURCHASE_PRICE_CENTS - HOLDBACK_AT_6_PCT_CENTS
RESERVE_AT_95_PCT_CENTS = 162997
POOL_T_STRATA_BY_STATE = ["CA", "FL", "NY", "TX"]


def _valuation_payload(env: JsonDict, token, method="DETERMINISTIC_STATIC"):
    """A valuation-run body echoing a portfolio version token."""
    return {
        "assumption_set_id": env["assumption_set_id"],
        "method": method,
        "expected_portfolio_version": token,
    }


def _bid_payload(bidder_id: str, token, price_bps: int, holdback_pct=6):
    """A bid body echoing a bid-package version token."""
    return {
        "bidder_id": bidder_id,
        "price_bps": price_bps,
        "holdback_pct": holdback_pct,
        "expected_bid_package_version": token,
    }


# ---------------------------------------------------------------------------
# The portfolio version token on a valuation run
# ---------------------------------------------------------------------------
def test_second_valuation_run_reusing_the_spent_portfolio_token_is_refused(
        api: ApiClient, locked_portfolio: JsonDict) -> None:
    """
    The token a successful valuation run consumed cannot price a second run.

    PRD: "If it does not equal the portfolio's current `version`, the request fails with `ERR_STALE_PORTFOLIO_VERSION` (HTTP 412) and no valuation run row is created."

    Design: Corner/cross_cutting_complexity_layers/portfolio_version_token_guards_the_second_valuation_run
    """
    env = locked_portfolio
    token = env["portfolio_version"]

    first = api.create_valuation_run(
        env["portfolio_id"], _valuation_payload(env, token), U.ANALYST)
    run = validate_success(first, 201)
    assert run["value_cents"] == C.POOL_T_STATIC_VALUE_CENTS
    assert run["sequence_no"] == 1
    assert_status(run, "COMPLETED")

    replay = api.create_valuation_run(
        env["portfolio_id"],
        _valuation_payload(env, token, "OAS_SHOCK_WEIGHTED"), U.ANALYST)
    validate_error(replay, ERR_STALE_PORTFOLIO_VERSION)


def test_refused_valuation_run_creates_no_run_row_and_moves_no_version(
        api: ApiClient, locked_portfolio: JsonDict) -> None:
    """
    The stale-token refusal leaves the run collection and the portfolio alone.

    PRD: "If a validation refuses an operation, no field changes, no child row is created, no `version` increments and no `updated_at` moves — including for the entities the operation would have cascaded into."

    Design: Corner/cross_cutting_complexity_layers/portfolio_version_token_guards_the_second_valuation_run
    """
    env = locked_portfolio
    portfolio_id = env["portfolio_id"]
    token = env["portfolio_version"]

    run = validate_success(
        api.create_valuation_run(
            portfolio_id, _valuation_payload(env, token), U.ANALYST),
        201)
    before = data_of(api.get_portfolio(portfolio_id, U.MANAGER))
    assert before["version"] == token + 1
    assert before["valuation_freshness"] == "CURRENT"

    validate_error(
        api.create_valuation_run(
            portfolio_id,
            _valuation_payload(env, token, "OAS_SHOCK_WEIGHTED"), U.ANALYST),
        ERR_STALE_PORTFOLIO_VERSION)

    runs = rows_of(
        api.list_valuation_runs(U.ANALYST, {"portfolio_id": portfolio_id}))
    assert ids_of(runs) == [run["id"]]

    after = data_of(api.get_portfolio(portfolio_id, U.MANAGER))
    assert after["version"] == before["version"]
    assert after["updated_at"] == before["updated_at"]
    assert after["valuation_freshness"] == before["valuation_freshness"]


def test_refreshed_portfolio_token_admits_exactly_one_further_valuation_run(
        api: ApiClient, locked_portfolio: JsonDict) -> None:
    """
    Re-reading the portfolio buys one more run, and one more only.

    PRD: "A successful run increments the portfolio's `version` by 1, which invalidates the token the caller just spent — a second run must first re-read the portfolio."

    Design: Corner/cross_cutting_complexity_layers/portfolio_version_token_guards_the_second_valuation_run
    """
    env = locked_portfolio
    portfolio_id = env["portfolio_id"]
    first_token = env["portfolio_version"]

    first = validate_success(
        api.create_valuation_run(
            portfolio_id, _valuation_payload(env, first_token), U.ANALYST),
        201)

    refreshed = refresh_portfolio(api, env)
    second_token = refreshed["version"]
    assert second_token == first_token + 1

    second = validate_success(
        api.create_valuation_run(
            portfolio_id,
            _valuation_payload(env, second_token, "OAS_SHOCK_WEIGHTED"),
            U.ANALYST),
        201)
    assert second["value_cents"] == C.POOL_T_OAS_VALUE_CENTS
    assert second["sequence_no"] == 2

    retired = data_of(api.get_valuation_run(first["id"], U.ANALYST))
    assert_status(retired, "SUPERSEDED")

    validate_error(
        api.create_valuation_run(
            portfolio_id,
            _valuation_payload(env, second_token, "DETERMINISTIC_STATIC"),
            U.ANALYST),
        ERR_STALE_PORTFOLIO_VERSION)


def test_valuation_run_without_the_portfolio_token_is_a_shape_violation(
        api: ApiClient, locked_portfolio: JsonDict) -> None:
    """
    Omitting the token is a different failure from supplying a stale one.

    PRD: "Request shape: body parses, required fields present, every value satisfying its declared type, enum, range and decimal-place constraints, and no attempt to write a system-maintained or computed field — `ERR_INVALID_REQUEST`."

    Design: Corner/cross_cutting_complexity_layers/portfolio_version_token_guards_the_second_valuation_run
    """
    env = locked_portfolio

    untokened = api.create_valuation_run(
        env["portfolio_id"],
        {"assumption_set_id": env["assumption_set_id"],
         "method": "DETERMINISTIC_STATIC"},
        U.ANALYST)
    validate_error(untokened, ERR_INVALID_REQUEST)

    runs = rows_of(
        api.list_valuation_runs(
            U.ANALYST, {"portfolio_id": env["portfolio_id"]}))
    assert runs == []


# ---------------------------------------------------------------------------
# The bid package version token on a bid
# ---------------------------------------------------------------------------
def test_second_bidder_reusing_the_spent_package_token_is_refused(
        api: ApiClient, published_package: JsonDict) -> None:
    """
    One bidder's accepted submission invalidates the token every bidder holds.

    PRD: "A mismatch fails with `ERR_STALE_BID_PACKAGE_VERSION` (HTTP 412) and no bid row is created."

    Design: Corner/cross_cutting_complexity_layers/bid_package_version_token_guards_the_second_bid
    """
    env = published_package
    token = env["package_version"]
    charlie = F.create_counterparty(api, C.BUYER_CHARLIE)

    first = validate_success(
        api.create_bid(env["package_id"],
                       _bid_payload(env["buyer_id"], token, 118),
                       U.make_buyer_headers(env["buyer_id"])),
        201)
    assert first["bid_value_cents"] == BID_VALUE_AT_118_BPS
    assert first["round_number"] == 1
    assert_status(first, "SUBMITTED")

    contender = api.create_bid(
        env["package_id"], _bid_payload(charlie["id"], token, 121, 5),
        U.make_buyer_headers(charlie["id"]))
    validate_error(contender, ERR_STALE_BID_PACKAGE_VERSION)


def test_refused_bid_creates_no_bid_row_and_leaves_bid_count_at_one(
        api: ApiClient, published_package: JsonDict) -> None:
    """
    The refused submission is invisible: no bid row and no aggregate movement.

    PRD: "If a validation refuses an operation, no field changes, no child row is created, no `version` increments and no `updated_at` moves — including for the entities the operation would have cascaded into."

    Design: Corner/cross_cutting_complexity_layers/bid_package_version_token_guards_the_second_bid
    """
    env = published_package
    package_id = env["package_id"]
    token = env["package_version"]
    charlie = F.create_counterparty(api, C.BUYER_CHARLIE)

    accepted = validate_success(
        api.create_bid(package_id, _bid_payload(env["buyer_id"], token, 118),
                       U.make_buyer_headers(env["buyer_id"])),
        201)
    before = data_of(api.get_bid_package(package_id, U.MANAGER))
    assert before["version"] == token + 1
    assert before["bid_count"] == 1

    validate_error(
        api.create_bid(package_id, _bid_payload(charlie["id"], token, 121, 5),
                       U.make_buyer_headers(charlie["id"])),
        ERR_STALE_BID_PACKAGE_VERSION)

    after = data_of(api.get_bid_package(package_id, U.MANAGER))
    assert after["version"] == before["version"]
    assert after["bid_count"] == before["bid_count"]
    assert after["updated_at"] == before["updated_at"]

    bids = rows_of(api.list_bids(U.MANAGER, {"bid_package_id": package_id}))
    assert ids_of(bids) == [accepted["id"]]
    assert rows_of(
        api.list_bids(U.MANAGER, {"bidder_id": charlie["id"]})) == []


def test_second_bidder_succeeds_once_the_package_token_is_refreshed(
        api: ApiClient, published_package: JsonDict) -> None:
    """
    Re-reading the package lets the contender price its own offer.

    PRD: "A successful submission increments the package's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/bid_package_version_token_guards_the_second_bid
    """
    env = published_package
    package_id = env["package_id"]
    first_token = env["package_version"]
    charlie = F.create_counterparty(api, C.BUYER_CHARLIE)

    incumbent = validate_success(
        api.create_bid(package_id,
                       _bid_payload(env["buyer_id"], first_token, 118),
                       U.make_buyer_headers(env["buyer_id"])),
        201)

    refreshed = refresh_package(api, env)
    second_token = refreshed["version"]
    assert second_token == first_token + 1

    contender = validate_success(
        api.create_bid(package_id, _bid_payload(charlie["id"], second_token,
                                                121, 5),
                       U.make_buyer_headers(charlie["id"])),
        201)
    assert contender["bid_value_cents"] == BID_VALUE_AT_121_BPS
    assert contender["round_number"] == 1
    assert_status(contender, "SUBMITTED")

    final = data_of(api.get_bid_package(package_id, U.MANAGER))
    assert final["version"] == second_token + 1
    assert final["bid_count"] == 2

    bids = rows_of(api.list_bids(U.MANAGER, {"bid_package_id": package_id}))
    assert sorted(ids_of(bids)) == sorted([incumbent["id"], contender["id"]])


def test_stale_package_token_outranks_the_bidder_eligibility_check(
        api: ApiClient, published_package: JsonDict) -> None:
    """
    A suspended contender replaying a spent token still hears about the token.

    PRD: "Second, **the version guard sits between state and business**: a stale version supplied on an action that would have been refused for state reasons anyway yields the state error, not the 412."

    Design: Corner/cross_cutting_complexity_layers/bid_package_version_token_guards_the_second_bid
    """
    env = published_package
    package_id = env["package_id"]
    stale_token = env["package_version"]
    charlie = F.create_counterparty(api, C.BUYER_CHARLIE)

    validate_success(
        api.create_bid(package_id,
                       _bid_payload(env["buyer_id"], stale_token, 118),
                       U.make_buyer_headers(env["buyer_id"])),
        201)

    suspended = F.suspend_counterparty(api, charlie["id"])
    assert_status(suspended, "SUSPENDED")

    refused = api.create_bid(
        package_id, _bid_payload(charlie["id"], stale_token, 121, 5),
        U.make_buyer_headers(charlie["id"]))
    validate_error(refused, ERR_STALE_BID_PACKAGE_VERSION)


# ---------------------------------------------------------------------------
# The agreement version token on a holdback release
# ---------------------------------------------------------------------------
def _release(api: ApiClient, agreement_id: str, token):
    """Ask for a holdback release, echoing an agreement version token."""
    return api.create_holdback_release(
        agreement_id, {"expected_purchase_agreement_version": token},
        U.COMPLIANCE_2)


def test_holdback_release_replayed_with_the_spent_agreement_token_is_refused(
        api: ApiClient, completed_transfer: JsonDict) -> None:
    """
    The token that paid the seller once cannot be presented a second time.

    PRD: "A mismatch fails with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412) and no holdback field changes."

    Design: Corner/cross_cutting_complexity_layers/agreement_version_token_outranks_the_exhausted_holdback
    """
    env = completed_transfer
    F.set_clock(api, "2026-10-01T00:00:00Z")
    agreement = refresh_agreement(api, env)
    token = agreement["version"]
    assert agreement["holdback_cents"] == HOLDBACK_AT_6_PCT_CENTS
    assert_holdback_split(agreement, retained=HOLDBACK_AT_6_PCT_CENTS,
                          released=0, applied=0)

    released = validate_success(_release(api, env["agreement_id"], token))
    assert_holdback_split(released, retained=0,
                          released=HOLDBACK_AT_6_PCT_CENTS, applied=0)
    assert_status(released, "HOLDBACK_RELEASED")
    assert released["version"] == token + 1

    validate_error(_release(api, env["agreement_id"], token),
                   ERR_STALE_AGREEMENT_VERSION)


def test_refused_holdback_release_leaves_the_three_buckets_untouched(
        api: ApiClient, completed_transfer: JsonDict) -> None:
    """
    Neither refusal double-pays: the holdback split is exactly as it was.

    PRD: "If a validation refuses an operation, no field changes, no child row is created, no `version` increments and no `updated_at` moves — including for the entities the operation would have cascaded into."

    Design: Corner/cross_cutting_complexity_layers/agreement_version_token_outranks_the_exhausted_holdback
    """
    env = completed_transfer
    F.set_clock(api, "2026-10-01T00:00:00Z")
    spent_token = refresh_agreement(api, env)["version"]

    after_release = validate_success(_release(api, env["agreement_id"],
                                             spent_token))
    current_token = after_release["version"]

    validate_error(_release(api, env["agreement_id"], spent_token),
                   ERR_STALE_AGREEMENT_VERSION)

    unchanged = data_of(
        api.get_purchase_agreement(env["agreement_id"], U.COMPLIANCE_2))
    assert unchanged["version"] == current_token
    assert unchanged["updated_at"] == after_release["updated_at"]
    assert_holdback_split(unchanged, retained=0,
                          released=HOLDBACK_AT_6_PCT_CENTS, applied=0)
    assert_status(unchanged, "HOLDBACK_RELEASED")


def test_current_agreement_token_surfaces_the_exhausted_holdback(
        api: ApiClient, completed_transfer: JsonDict) -> None:
    """
    The balance objection is only reported once the token itself is right.

    PRD: "And there must be something left to release: `holdback_retained_cents` must be greater than 0, else `ERR_HOLDBACK_EXHAUSTED` (HTTP 409)."

    Design: Corner/cross_cutting_complexity_layers/agreement_version_token_outranks_the_exhausted_holdback
    """
    env = completed_transfer
    F.set_clock(api, "2026-10-01T00:00:00Z")
    spent_token = refresh_agreement(api, env)["version"]

    released = validate_success(_release(api, env["agreement_id"],
                                        spent_token))
    assert released["holdback_retained_cents"] == 0

    validate_error(_release(api, env["agreement_id"], spent_token),
                   ERR_STALE_AGREEMENT_VERSION)
    validate_error(_release(api, env["agreement_id"], released["version"]),
                   ERR_HOLDBACK_EXHAUSTED)

    final = data_of(
        api.get_purchase_agreement(env["agreement_id"], U.COMPLIANCE_2))
    assert_holdback_split(final, retained=0,
                          released=HOLDBACK_AT_6_PCT_CENTS, applied=0)


def test_stale_agreement_token_outranks_the_holdback_eligibility_check(
        api: ApiClient, completed_transfer: JsonDict) -> None:
    """
    Before the representations expire a wrong token still wins over the date.

    PRD: "The money must be eligible: the bound servicing transfer must be `COMPLETED` and the current logical clock date must have reached `holdback_release_eligible_at`, else `ERR_HOLDBACK_NOT_ELIGIBLE` (HTTP 409)."

    Design: Corner/cross_cutting_complexity_layers/agreement_version_token_outranks_the_exhausted_holdback
    """
    env = completed_transfer
    F.set_clock(api, "2026-09-30T00:00:00Z")
    agreement = refresh_agreement(api, env)
    current_token = agreement["version"]

    validate_error(_release(api, env["agreement_id"], current_token - 1),
                   ERR_STALE_AGREEMENT_VERSION)
    validate_error(_release(api, env["agreement_id"], current_token),
                   ERR_HOLDBACK_NOT_ELIGIBLE)

    untouched = data_of(
        api.get_purchase_agreement(env["agreement_id"], U.COMPLIANCE_2))
    assert untouched["version"] == current_token
    assert_holdback_split(untouched, retained=HOLDBACK_AT_6_PCT_CENTS,
                          released=0, applied=0)

    F.set_clock(api, "2026-10-01T00:00:00Z")
    paid = validate_success(_release(api, env["agreement_id"], current_token))
    assert_holdback_split(paid, retained=0,
                          released=HOLDBACK_AT_6_PCT_CENTS, applied=0)


# ---------------------------------------------------------------------------
# Every derived value is already in the response that caused it
# ---------------------------------------------------------------------------
def test_portfolio_aggregates_are_current_on_the_first_read_after_a_loan(
        api: ApiClient, desk: JsonDict) -> None:
    """
    Adding a loan returns the loan, and the pool aggregates have already moved.

    PRD: "Adding a loan recomputes four portfolio aggregates and increments the portfolio's `version` by 1."

    Design: Corner/consistency_model/every_derived_value_is_visible_in_the_response_that_caused_it
    """
    env = desk
    portfolio = F.create_portfolio(api, env["seller_id"])
    assert portfolio["loan_count"] == 0
    assert portfolio["total_upb_cents"] == 0
    assert portfolio["custodial_funds_total_cents"] == 0
    opening_version = portfolio["version"]

    seller_headers = U.make_seller_headers(env["seller_id"])
    first_loan = validate_success(
        api.create_loan(portfolio["id"], C.LOANS_T[0], seller_headers), 201)
    assert first_loan["upb_cents"] == 10000050

    after_first = data_of(api.get_portfolio(portfolio["id"], U.MANAGER))
    assert after_first["loan_count"] == 1
    assert after_first["total_upb_cents"] == 10000050
    assert after_first["custodial_funds_total_cents"] == 125000
    assert float(after_first["weighted_avg_note_rate_pct"]) == 6.5
    assert after_first["version"] == opening_version + 1

    validate_success(
        api.create_loan(portfolio["id"], C.LOANS_T[1], seller_headers), 201)
    after_second = data_of(api.get_portfolio(portfolio["id"], U.MANAGER))
    assert after_second["loan_count"] == 2
    assert after_second["total_upb_cents"] == 20000100
    assert after_second["custodial_funds_total_cents"] == 250000
    assert float(after_second["weighted_avg_note_rate_pct"]) == 6.5
    assert after_second["version"] == opening_version + 2


def test_valuation_run_response_carries_its_own_economics_and_the_freshness(
        api: ApiClient, locked_portfolio: JsonDict) -> None:
    """
    The run response already prices the pool and the pool already reads CURRENT.

    PRD: "A successful run increments the portfolio's `version` by 1 in addition to recomputing its `valuation_freshness`."

    Design: Corner/consistency_model/every_derived_value_is_visible_in_the_response_that_caused_it
    """
    env = locked_portfolio
    token = env["portfolio_version"]

    run = validate_success(
        api.create_valuation_run(
            env["portfolio_id"], _valuation_payload(env, token), U.ANALYST),
        201)
    assert run["value_cents"] == C.POOL_T_STATIC_VALUE_CENTS
    assert float(run["value_bps_of_upb"]) == bps_of_upb(
        C.POOL_T_STATIC_VALUE_CENTS, C.POOL_T_TOTAL_UPB_CENTS)
    assert float(run["effective_discount_rate_pct"]) == 10.0
    assert run["included_loan_count"] == 4
    assert run["scenario_values"] is None
    assert_status(run, "COMPLETED")

    read_back = data_of(api.get_valuation_run(run["id"], U.ANALYST))
    assert read_back["value_cents"] == run["value_cents"]
    assert read_back["value_bps_of_upb"] == run["value_bps_of_upb"]
    assert read_back["status"] == run["status"]

    portfolio = data_of(api.get_portfolio(env["portfolio_id"], U.MANAGER))
    assert portfolio["valuation_freshness"] == "CURRENT"
    assert portfolio["version"] == token + 1


def test_tape_aggregates_are_visible_in_the_response_that_cut_the_tape(
        api: ApiClient, valued_portfolio: JsonDict) -> None:
    """
    Cutting the tape returns the package with its three aggregates already set.

    PRD: "The package's `tape_loan_count` is then the number of included lines, `tape_upb_cents` the sum of `upb_snapshot_cents` over included lines, and `stratum_count` the number of distinct `stratum_label` values among included lines; the package moves `DRAFT → STRATIFIED` and its `version` increments by 1."

    Design: Corner/consistency_model/every_derived_value_is_visible_in_the_response_that_caused_it
    """
    env = valued_portfolio
    package = F.create_bid_package(
        api, env["portfolio_id"], env["valuation_run_id"])
    assert package["tape_loan_count"] == 0
    assert package["tape_upb_cents"] == 0
    assert package["stratum_count"] == 0
    draft_version = package["version"]

    cut = data_of(api.stratify_bid_package(package["id"], U.ANALYST))
    assert cut["tape_loan_count"] == 4
    assert cut["tape_upb_cents"] == C.POOL_T_TOTAL_UPB_CENTS
    assert cut["stratum_count"] == 4
    assert cut["version"] == draft_version + 1
    assert_status(cut, "STRATIFIED")

    read_back = data_of(api.get_bid_package(package["id"], U.MANAGER))
    assert read_back["tape_loan_count"] == cut["tape_loan_count"]
    assert read_back["tape_upb_cents"] == cut["tape_upb_cents"]
    assert read_back["stratum_count"] == cut["stratum_count"]
    assert read_back["version"] == cut["version"]

    lines = rows_of(api.list_package_tape_lines(package["id"], U.ANALYST))
    assert len(lines) == 4
    assert sorted(line["stratum_label"] for line in lines) == (
        POOL_T_STRATA_BY_STATE)


def test_reserve_price_is_visible_in_the_response_that_published_the_package(
        api: ApiClient, stratified_package: JsonDict) -> None:
    """
    Publication stamps the reserve into the very response that publishes.

    PRD: "The reserve is the bound run's `value_cents`, multiplied by the package's `reserve_price_floor_pct` and divided by 100, multiplied by the package's `tape_upb_cents` and divided by the portfolio's `total_upb_cents` as frozen at tape lock, with a single half-up rounding to whole cents applied only at the very end and no intermediate rounding."

    Design: Corner/consistency_model/every_derived_value_is_visible_in_the_response_that_caused_it
    """
    env = stratified_package
    stratified_version = env["package_version"]

    published = data_of(api.publish_bid_package(env["package_id"], U.MANAGER))
    assert published["reserve_price_cents"] == RESERVE_AT_95_PCT_CENTS
    assert published["published_at"] is not None
    assert published["version"] == stratified_version + 1
    assert_status(published, "PUBLISHED")

    read_back = data_of(api.get_bid_package(env["package_id"], U.MANAGER))
    assert read_back["reserve_price_cents"] == published["reserve_price_cents"]
    assert read_back["published_at"] == published["published_at"]
    assert read_back["status"] == published["status"]


def test_award_response_carries_the_agreement_economics_it_computed(
        api: ApiClient, live_bid: JsonDict) -> None:
    """
    The award answers with the priced agreement, and later reads never differ.

    PRD: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

    Design: Corner/consistency_model/every_derived_value_is_visible_in_the_response_that_caused_it
    """
    env = live_bid

    agreement = validate_success(
        api.award_bid_package(
            env["package_id"],
            {"winning_bid_id": env["bid_id"], "rep_warrant_days": 30,
             "indemnification_days": 45},
            U.MANAGER),
        201)
    assert agreement["purchase_price_cents"] == PURCHASE_PRICE_CENTS
    assert agreement["holdback_cents"] == HOLDBACK_AT_6_PCT_CENTS
    assert agreement["settlement_wire_cents"] == SETTLEMENT_WIRE_CENTS
    assert_holdback_split(agreement, retained=HOLDBACK_AT_6_PCT_CENTS,
                          released=0, applied=0)
    assert_stratum_breakdown(agreement, POOL_T_STRATA_BY_STATE)
    assert_status(agreement, "DRAFTED")

    first_read = data_of(
        api.get_purchase_agreement(agreement["id"], U.MANAGER))
    second_read = data_of(
        api.get_purchase_agreement(agreement["id"], U.MANAGER))
    assert first_read == second_read
    assert first_read["purchase_price_cents"] == PURCHASE_PRICE_CENTS
    assert first_read["stratum_price_breakdown"] == (
        agreement["stratum_price_breakdown"])
    assert first_read["status"] == agreement["status"]
    assert first_read["version"] == agreement["version"]


def test_award_side_effects_are_visible_on_the_first_read_of_each_entity(
        api: ApiClient, live_bid: JsonDict) -> None:
    """
    The auction, the winning offer and the pool have all moved before any read.

    PRD: "Awarding also settles the auction around it: the nominated bid becomes `ACCEPTED`, every other live bid on the package becomes `REJECTED`, the package moves `PUBLISHED → AWARDED` with its `version` incremented, and the owning portfolio moves `TAPE_LOCKED → UNDER_CONTRACT` with its `version` incremented."

    Design: Corner/consistency_model/every_derived_value_is_visible_in_the_response_that_caused_it
    """
    env = live_bid
    package_version_before = env["package_version"]
    portfolio_version_before = data_of(
        api.get_portfolio(env["portfolio_id"], U.MANAGER))["version"]

    agreement = validate_success(
        api.award_bid_package(
            env["package_id"],
            {"winning_bid_id": env["bid_id"], "rep_warrant_days": 30,
             "indemnification_days": 45},
            U.MANAGER),
        201)
    assert agreement["winning_bid_id"] == env["bid_id"]
    assert agreement["buyer_id"] == env["buyer_id"]

    package = data_of(api.get_bid_package(env["package_id"], U.MANAGER))
    assert_status(package, "AWARDED")
    assert package["version"] == package_version_before + 1

    bid = data_of(api.get_bid(env["bid_id"], U.MANAGER))
    assert_status(bid, "ACCEPTED")

    portfolio = data_of(api.get_portfolio(env["portfolio_id"], U.MANAGER))
    assert_status(portfolio, "UNDER_CONTRACT")
    assert portfolio["version"] == portfolio_version_before + 1


def test_transfer_readiness_is_re_derived_in_the_response_of_each_step(
        api: ApiClient, settled_trade: JsonDict) -> None:
    """
    Each work-stream step answers with the dimension and the readiness it implies.

    PRD: "A derived `readiness` reads `READY` if and only if `notice_status` is `NOTICES_ATTESTED` **and** `data_status` is `RECONCILED` **and** `pipeline_status` is `PIPELINE_TRANSFERRED`; in every other combination it reads `NOT_READY`."

    Design: Corner/consistency_model/every_derived_value_is_visible_in_the_response_that_caused_it
    """
    env = settled_trade
    transfer_id = env["transfer_id"]
    opened = data_of(api.get_servicing_transfer(transfer_id, U.MANAGER))
    assert opened["notice_status"] == "NOT_STARTED"
    assert opened["data_status"] == "NOT_STARTED"
    assert opened["pipeline_status"] == "NOT_STARTED"
    assert_readiness(opened, "NOT_READY")

    mapped = F.map_data(api, transfer_id, env["buyer_id"])
    assert mapped["data_status"] == "MAPPED"
    assert_readiness(mapped, "NOT_READY")

    swept = F.map_escrow(api, transfer_id, env["buyer_id"])
    assert swept["data_status"] == "ESCROW_MAPPED"
    assert swept["escrow_transferred_cents"] == 400000
    assert swept["suspense_transferred_cents"] == 100000
    assert_readiness(swept, "NOT_READY")
    assert data_of(
        api.get_servicing_transfer(transfer_id, U.MANAGER)) == swept

    reconciled = F.reconcile(api, transfer_id, env["buyer_id"])
    assert reconciled["data_status"] == "RECONCILED"
    assert_readiness(reconciled, "NOT_READY")

    F.send_notices(api, transfer_id, env["included_loan_ids"],
                   env["seller_id"])
    attested = F.attest_notices(api, transfer_id)
    assert attested["notice_status"] == "NOTICES_ATTESTED"
    assert attested["notice_count"] == 4
    assert attested["late_notice_count"] == 0
    assert_readiness(attested, "NOT_READY")

    handed_over = F.transfer_pipeline(api, transfer_id, env["buyer_id"])
    assert handed_over["pipeline_status"] == "PIPELINE_TRANSFERRED"
    assert handed_over["loss_mit_pipeline_count"] == 0
    assert_readiness(handed_over, "READY")
    assert data_of(
        api.get_servicing_transfer(transfer_id, U.MANAGER)) == handed_over
