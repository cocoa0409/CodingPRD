"""Optimistic concurrency tokens, and the promise that no write ever lags.

The three guarded writes — an aggregated allocation, a credit-support post and a
metered hour — are each blocked by a token that some earlier legitimate write
advanced, never by a state precondition, and each succeeds unchanged once the
caller re-reads its parent.  The consistency pair then shows the mirror image of
the same property: every computed figure is already in the response body of the
write that produced it, and a neighbour read taken immediately afterwards is
already current.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (  # noqa: E402
    get_success_data,
    validate_error,
)

from test_helpers import assertions as asserts  # noqa: E402
from test_helpers import factories as f  # noqa: E402
from test_helpers import fixtures as fx  # noqa: E402
from test_helpers.api_errors import ApiErrorId  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    CREDIT_OFFICER,
    ORIGINATOR,
    SETTLEMENT_ANALYST,
)

# ---------------------------------------------------------------------------
# An allocation that fits perfectly is still refused on a stale token.
# ---------------------------------------------------------------------------

CONTRACTED_MW = 25.000
ANCHOR_SLICE_MW = 15.000
SECOND_SLICE_MW = 10.000
SECOND_BUYER = {
    "legal_name": "Cascadia Data Centers LLC",
    "registry_account_id": "WREGIS-ACC-00555",
}


def test_01_a_stale_deal_token_blocks_a_slice_that_would_otherwise_fit(api):
    """The second slice takes exactly the 10.000 MW of headroom the first one left, for
    a QUALIFIED buyer, on a deal in an accepting state — and is refused at 412 solely
    because the first slice and its confirmation moved the deal's version. Resending
    the identical body under the re-read token succeeds.

    "Proposing an aggregated-buyer allocation against a deal requires
    `expected_deal_version` in the payload, carrying the client's last observed
    `version` of that `Deal`."

    "If any writer has advanced the deal's `version` since the client read it, the
    proposal is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    "Aggregated arrangements let many allocations coexist on one deal, so nothing
    about the deal's state blocks a second proposal — what blocks it is that the
    proposer's view of `unallocated_mw` is stale, and honouring the proposal could
    oversubscribe the contracted capacity."

    "Optimistic concurrency: the supplied expected parent version equals the parent's
    current `version` — `ERR_STALE_VERSION`."

    "Its `allocation_share_pct` is one hundred multiplied by `allocated_mw` divided
    by the deal's `contracted_mw`, rounded half up to four decimal places."

    "The deal's `unallocated_mw` is then recomputed as `contracted_mw` less the sum of
    `allocated_mw` over the slices whose `status` is `PROPOSED` or `CONFIRMED`, both
    the slice's `version` and the deal's `version` increment by one."

    Design: Corner/complexity_layers/stale_deal_version_blocks_a_second_allocation_that_would_oversubscribe
    """
    node = fx.create_node(api)
    anchor = fx.create_qualified_offtaker(api)
    second = fx.create_qualified_offtaker(api, **SECOND_BUYER)
    project = fx.create_project(api, node["id"])
    deal = fx.create_deal(api, project["id"], anchor["id"], node["id"],
                          product_type="AGGREGATED")
    fx.table_round(api, deal["id"], response_deadline="2026-09-01T00:00:00Z")

    stale_token = fx.deal_version(api, deal["id"])
    first = fx.propose_allocation(api, deal["id"], anchor["id"],
                                  ANCHOR_SLICE_MW)
    asserts.assert_share_pct(first["allocation_share_pct"], 60.0000,
                             "allocation_share_pct")
    fx.confirm_allocation(api, first["id"], anchor["id"])

    after_first = fx.read_deal(api, deal["id"])
    asserts.assert_mw(after_first["unallocated_mw"], SECOND_SLICE_MW,
                      "unallocated_mw")
    asserts.assert_mw(after_first["confirmed_allocated_mw"], ANCHOR_SLICE_MW,
                      "confirmed_allocated_mw")

    # The body is legal in every respect; only the token is behind.
    body = f.allocation_payload(second["id"], SECOND_SLICE_MW, stale_token,
                               joint_and_several=True)
    refused = api.create_allocation(deal["id"], body, ORIGINATOR)
    validate_error(refused, ApiErrorId.ERR_STALE_VERSION.value, 412)

    slices, meta = fx.list_all(api.list_allocations(deal["id"], ORIGINATOR))
    assert meta["total_count"] == 1, meta
    assert asserts.ids_of(slices) == [first["id"]], slices
    assert fx.read_deal(api, deal["id"])["unallocated_mw"] == \
        after_first["unallocated_mw"], after_first

    fresh_token = fx.deal_version(api, deal["id"])
    assert fresh_token > stale_token, (fresh_token, stale_token)

    accepted = get_success_data(api.create_allocation(
        deal["id"], f.allocation_payload(second["id"], SECOND_SLICE_MW,
                                         fresh_token, joint_and_several=True),
        ORIGINATOR), 201)
    assert accepted["status"] == "PROPOSED", accepted
    asserts.assert_mw(accepted["allocated_mw"], SECOND_SLICE_MW, "allocated_mw")
    asserts.assert_share_pct(accepted["allocation_share_pct"], 40.0000,
                             "allocation_share_pct")

    settled = fx.read_deal(api, deal["id"])
    asserts.assert_mw(settled["unallocated_mw"], 0.000, "unallocated_mw")
    asserts.assert_mw(settled["confirmed_allocated_mw"], ANCHOR_SLICE_MW,
                      "confirmed_allocated_mw")
    asserts.assert_version_advanced_by(fresh_token, settled["version"], 1,
                                       "deal version")


# ---------------------------------------------------------------------------
# Instruments stack, so only the token can stop the second post.
# ---------------------------------------------------------------------------

FIRST_CASH_USD = 300000.00
SECOND_CASH_USD = 250000.00
STACKED_TOTAL_USD = 550000.00


def test_02_a_stale_deal_token_blocks_the_second_of_two_stacked_posts(api):
    """Registering the two cash instruments moves no version at all, so the token read
    after submission is good for the first post and one step behind for the second.
    The refusal leaves the second instrument entirely unvalued.

    "A registered instrument arrives with `status` `PROPOSED` and with `haircut_pct`,
    `eligible_credit_usd`, `posted_at` and `closed_at` all null; registration
    deliberately does **not** move `posted_credit_support_usd` and does **not**
    increment the deal's `version`."

    "Posting a registered credit-support instrument likewise requires
    `expected_deal_version` matching the parent deal's current `version`."

    "Instruments legitimately stack, so a later post is not blocked by any state
    precondition; it is blocked because the poster's view of
    `posted_credit_support_usd` and `credit_support_required_usd` is stale, and the
    coverage arithmetic that decides whether the deal's credit standing cures from
    `SUPPORT_SHORTFALL` back to `APPROVED` would otherwise be evaluated against a
    superseded requirement."

    "`CASH_COLLATERAL` consults neither issuer nor guarantor fields."

    "A successful post moves the instrument `PROPOSED → POSTED`, stamps `posted_at`
    with the logical clock, and recomputes the deal's `posted_credit_support_usd` as
    the sum of `eligible_credit_usd` over that deal's `POSTED` instruments."

    "Submission is legal from `NOT_SUBMITTED`, from `DECLINED` — the re-underwriting
    loop after a refused package — and from `SUPPORT_SHORTFALL`, and in every case
    the deal moves to `SUBMITTED`."

    Design: Corner/complexity_layers/stale_deal_version_blocks_the_second_of_two_stacked_credit_support_posts
    """
    node = fx.create_node(api)
    anchor = fx.create_qualified_offtaker(api)
    project = fx.create_project(api, node["id"])
    deal = fx.create_deal(api, project["id"], anchor["id"], node["id"])

    before_registration = fx.deal_version(api, deal["id"])
    first = fx.register_cash(api, deal["id"], FIRST_CASH_USD)
    secondary = fx.register_cash(api, deal["id"], SECOND_CASH_USD)
    for registered in (first, secondary):
        assert registered["status"] == "PROPOSED", registered
        asserts.assert_all_null(registered, ["haircut_pct",
                                             "eligible_credit_usd",
                                             "posted_at", "closed_at"])
    after_registration = fx.read_deal(api, deal["id"])
    assert after_registration["version"] == before_registration, \
        after_registration
    asserts.assert_money(after_registration["posted_credit_support_usd"], 0.00,
                         "posted_credit_support_usd")

    submitted = fx.submit_credit(api, deal["id"])
    assert submitted["credit_status"] == "SUBMITTED", submitted
    stale_token = submitted["version"]

    posted = get_success_data(api.post_credit_support(
        first["id"], f.post_credit_support_payload(stale_token),
        CREDIT_OFFICER), 200)
    assert posted["status"] == "POSTED", posted
    asserts.assert_money(posted["haircut_pct"], 0.00, "haircut_pct")
    asserts.assert_money(posted["eligible_credit_usd"], FIRST_CASH_USD,
                         "eligible_credit_usd")
    asserts.assert_instant_equals(posted["posted_at"], fx.INITIAL_CLOCK,
                                  "posted_at")
    asserts.assert_money(fx.read_deal(api, deal["id"])
                         ["posted_credit_support_usd"], FIRST_CASH_USD,
                         "posted_credit_support_usd")

    # The same token, reused one write too late.
    refused = api.post_credit_support(
        secondary["id"], f.post_credit_support_payload(stale_token),
        CREDIT_OFFICER)
    validate_error(refused, ApiErrorId.ERR_STALE_VERSION.value, 412)

    stack, _ = fx.list_all(api.list_credit_support(deal["id"], CREDIT_OFFICER))
    untouched = asserts.row_by_id(stack, secondary["id"])
    assert untouched["status"] == "PROPOSED", untouched
    asserts.assert_all_null(untouched, ["haircut_pct", "eligible_credit_usd",
                                        "posted_at", "closed_at"])

    fresh_token = fx.deal_version(api, deal["id"])
    asserts.assert_version_advanced_by(stale_token, fresh_token, 1,
                                       "deal version")
    stacked = get_success_data(api.post_credit_support(
        secondary["id"], f.post_credit_support_payload(fresh_token),
        CREDIT_OFFICER), 200)
    assert stacked["status"] == "POSTED", stacked
    asserts.assert_money(stacked["eligible_credit_usd"], SECOND_CASH_USD,
                         "eligible_credit_usd")

    covered = fx.read_deal(api, deal["id"])
    asserts.assert_money(covered["posted_credit_support_usd"],
                         STACKED_TOTAL_USD, "posted_credit_support_usd")
    asserts.assert_money(covered["released_credit_support_usd"], 0.00,
                         "released_credit_support_usd")
    asserts.assert_money(covered["drawn_credit_support_usd"], 0.00,
                         "drawn_credit_support_usd")
    assert covered["credit_status"] == "SUBMITTED", covered
    assert covered["status"] == "DRAFT", covered


# ---------------------------------------------------------------------------
# Hours accumulate by design, so the token is the only obstacle.
# ---------------------------------------------------------------------------

PERIOD_START = "2026-08-01T00:00:00Z"
PERIOD_END = "2026-09-01T00:00:00Z"
SECOND_HOUR = "2026-08-01T01:00:00Z"
FIRST_HOUR_MWH = 30.0000
SECOND_HOUR_MWH = 28.0000


def test_03_a_stale_period_token_blocks_the_second_hour_of_the_window(api):
    """Hour 01 is a brand-new slot inside the window with no duplicate and no boundary
    problem, so nothing but the token stands against it: the token minted at period
    creation went stale the moment hour 00 landed.

    "Posting a metered hour into a settlement period requires
    `expected_settlement_period_version` matching that `SettlementPeriod`'s current
    `version`, and a mismatch is refused with `ERR_STALE_VERSION` (HTTP 412)."

    "Hourly intervals accumulate by design, so no state precondition stands in the
    way; the danger is that a poster whose view of `interval_count` and the period's
    computed totals is stale is precisely the poster who would re-load an hour
    another writer already posted."

    "The period arrives with `status` `OPEN`, `interval_count` 0, `total_metered_mwh`,
    `total_deemed_mwh` and `total_delivered_mwh` at 0, and
    `weighted_avg_index_usd_per_mwh`, `energy_settlement_usd`,
    `basis_adjustment_usd`, `net_settlement_usd`, `seller_pays_usd`,
    `buyer_pays_usd`, `mintable_attributes_mwh`, `calculated_at`, `invoiced_at` and
    `dispute_reason` all null."

    "Only after that in-window test does the duplicate test run: an hour already
    loaded into this period is refused with `ERR_DUPLICATE_METER_HOUR`, so a
    duplicate hour that is also out of range returns the out-of-range error instead."

    "A new interval carries `settlement_period_id` set to the period it was loaded
    into, `posted_by_user_id` stamped from the acting analyst, `expected_mwh` and
    `delivered_mwh` null and `deemed_mwh` 0 until the period is calculated; the
    period's `interval_count` increments by one and its `version` increments by one."

    Design: Corner/complexity_layers/stale_period_version_blocks_the_second_hour_posted_to_a_settlement_period
    """
    chain = fx.chain_c(api)
    period = fx.open_period(api, chain["deal"]["id"], PERIOD_START, PERIOD_END)
    assert period["status"] == "OPEN", period
    assert period["interval_count"] == 0, period
    assert period["calculated_at"] is None, period
    stale_token = period["version"]

    first = get_success_data(api.create_meter_interval(
        period["id"],
        f.meter_interval_payload(PERIOD_START, FIRST_HOUR_MWH, 25.00, 26.00,
                                 stale_token), SETTLEMENT_ANALYST), 201)
    assert first["settlement_period_id"] == period["id"], first
    assert fx.read_period(api, period["id"])["interval_count"] == 1, first

    # A different hour, a legal window, a legal state — and a stale token.
    refused = api.create_meter_interval(
        period["id"],
        f.meter_interval_payload(SECOND_HOUR, SECOND_HOUR_MWH, 24.00, 26.00,
                                 stale_token), SETTLEMENT_ANALYST)
    validate_error(refused, ApiErrorId.ERR_STALE_VERSION.value, 412)

    after_refusal = fx.read_period(api, period["id"])
    assert after_refusal["interval_count"] == 1, after_refusal
    hours, meta = fx.list_all(api.list_meter_intervals(period["id"],
                                                       SETTLEMENT_ANALYST))
    assert meta["total_count"] == 1, meta
    assert asserts.ids_of(hours) == [first["id"]], hours

    fresh_token = after_refusal["version"]
    asserts.assert_version_advanced_by(stale_token, fresh_token, 1,
                                       "settlement period version")
    second = get_success_data(api.create_meter_interval(
        period["id"],
        f.meter_interval_payload(SECOND_HOUR, SECOND_HOUR_MWH, 24.00, 26.00,
                                 fresh_token), SETTLEMENT_ANALYST), 201)
    assert second["settlement_period_id"] == period["id"], second

    loaded = fx.read_period(api, period["id"])
    assert loaded["interval_count"] == 2, loaded
    assert loaded["status"] == "OPEN", loaded
    assert loaded["calculated_at"] is None, loaded
    asserts.assert_version_advanced_by(fresh_token, loaded["version"], 1,
                                       "settlement period version")


# ---------------------------------------------------------------------------
# Every computed figure is already in the body of the write that made it.
# ---------------------------------------------------------------------------

CREDIT_SCORE = 83.70
SUSTAINABILITY_SCORE = 100.00
UNSECURED_LIMIT_USD = 3000000.00
CONTRACT_PRICE = 22.75
EXPECTED_ANNUAL_MWH = 61320.00
EXPOSURE_USD = 1395030.00
COMPUTED_AT_CREATION = ["credit_score", "credit_score_variant", "credit_tier",
                        "sustainability_score", "unsecured_credit_limit_usd"]


def test_04_each_write_response_already_carries_what_that_write_computed(api):
    """No figure below is read twice: the scoring chain's five outputs arrive in the
    submission's own response body, the decision's outcome in its own, and the whole
    priced and sized credit package in the deal-creation response.

    "A caller who reads the affected resources immediately after such a request
    observes every hop already applied."

    "On creation `qualification_status` is `DRAFT`, `conditions` is the empty array,
    `claimed_attributes_mwh` is 0, `watchlist_since` is null, `decision_by_user_id`
    is null, and `credit_score`, `credit_score_variant`, `credit_tier`,
    `sustainability_score` and `unsecured_credit_limit_usd` are all null — no scoring
    runs at creation."

    "Both paths recompute `credit_score`, `credit_score_variant`, `credit_tier`,
    `sustainability_score` and `unsecured_credit_limit_usd`, and both increment the
    buyer's `version` by one."

    "The three effective component values are then combined by weight — the rating
    component at 0.55, the leverage component at 0.30 and the disclosure component at
    0.15 — and the weighted sum is rounded half up to two decimal places to give
    `credit_score`."

    "A `credit_score` of at least 80.00 is `PRIME`; failing that, at least 62.00 is
    `STANDARD`; failing that, at least 45.00 is `SUBPRIME`; anything below 45.00 is
    `DECLINED`."

    "`QUALIFY` moves the buyer `UNDER_REVIEW → QUALIFIED` and requires both that
    `credit_tier` is `PRIME` or `STANDARD` and that `sustainability_score` is at least
    70.00; it sets `conditions` to the empty array and stamps `decision_by_user_id`
    with the acting operator."

    "Step two selects `price_tier` **from the escalated base alone**: an escalated
    base below 40.00 is `LOW`, an escalated base of at least 40.00 but below 60.00 is
    `MID`, and an escalated base of 60.00 or more is `HIGH`."

    "`expected_annual_mwh` is `contracted_mw` multiplied by the technology capacity
    factor of the parent project — 0.28 for `SOLAR`, 0.42 for `WIND`, 0.35 for
    `STORAGE_HYBRID` — multiplied by the 8,760 hours in a year, rounded half up to two
    decimal places."

    "Creation also prices the deal, projects its volume, snapshots the buyer's
    unsecured limit into `unsecured_credit_limit_usd` and `collateral_threshold_usd`,
    and sizes `exposure_usd` and `credit_support_required_usd`."

    "If `exposure_usd` is at or below `collateral_threshold_usd`, then
    `credit_support_required_usd` is 0.00."

    Design: Corner/consistency_model/immediate_consistency_every_write_response_and_neighbour_read_is_already_current
    """
    node = fx.create_node(api)
    project = fx.create_project(api, node["id"])
    buyer = fx.create_anchor_offtaker(api)
    assert buyer["qualification_status"] == "DRAFT", buyer
    asserts.assert_all_null(buyer, COMPUTED_AT_CREATION)

    # The submission's own body carries the entire scoring chain.
    scored = fx.submit_offtaker(api, buyer["id"])
    assert scored["qualification_status"] == "UNDER_REVIEW", scored
    asserts.assert_score(scored["credit_score"], CREDIT_SCORE, "credit_score")
    assert scored["credit_score_variant"] == "STANDALONE", scored
    assert scored["credit_tier"] == "PRIME", scored
    asserts.assert_score(scored["sustainability_score"], SUSTAINABILITY_SCORE,
                         "sustainability_score")
    asserts.assert_money(scored["unsecured_credit_limit_usd"],
                         UNSECURED_LIMIT_USD, "unsecured_credit_limit_usd")

    qualified = fx.decide_offtaker(api, buyer["id"], "QUALIFY")
    assert qualified["qualification_status"] == "QUALIFIED", qualified
    assert qualified["conditions"] == [], qualified
    assert qualified["decision_by_user_id"] == "u_credit_1", qualified

    # The creation response is already the priced and sized package.
    deal = fx.create_deal(api, project["id"], buyer["id"], node["id"])
    asserts.assert_money(deal["contract_price_usd_per_mwh"], CONTRACT_PRICE,
                         "contract_price_usd_per_mwh")
    assert deal["price_tier"] == "LOW", deal
    asserts.assert_mwh(deal["expected_annual_mwh"], EXPECTED_ANNUAL_MWH,
                       "expected_annual_mwh", places=2)
    asserts.assert_money(deal["exposure_usd"], EXPOSURE_USD, "exposure_usd")
    asserts.assert_money(deal["collateral_threshold_usd"], UNSECURED_LIMIT_USD,
                         "collateral_threshold_usd")
    asserts.assert_money(deal["credit_support_required_usd"], 0.00,
                         "credit_support_required_usd")
    asserts.assert_mw(deal["unallocated_mw"], CONTRACTED_MW, "unallocated_mw")
    asserts.assert_mw(deal["confirmed_allocated_mw"], 0.000,
                      "confirmed_allocated_mw")
    assert deal["credit_status"] == "NOT_SUBMITTED", deal
    assert deal["cp_total_count"] == 0, deal
    assert deal["created_by_user_id"] == "u_orig_1", deal


# ---------------------------------------------------------------------------
# The neighbour read never lags the write that changed it.
# ---------------------------------------------------------------------------

AVAILABLE_AFTER_EXECUTION_MW = 75.000
PROJECT_CAPACITY_MW = 100.000


def test_05_a_neighbour_read_taken_immediately_is_already_current(api):
    """Reads of entities the caller never named are current the instant the write
    returns: the project's version already reflects the deal creation that recomputed
    its ledger, the deal's roll-ups already reflect a slice proposed and then
    confirmed, and the project's capacity ledger already counts the executed deal
    with no second write and no reconciliation pass.

    "A project milestone advance, a deal execution, a rating change, a termination and
    a risk-event acceptance each propagate through two, three, four or five hops of
    dependent state, and every hop is part of the same request: there is no deferred
    queue and no eventual consistency."

    "Whenever a hop mutates a row, that row's `updated_at` is refreshed and its
    `version` increases by one — including rows the caller never named, such as the
    sibling deals of a downgraded buyer or the guarantor-supported children of a
    downgraded parent."

    "Finally it recomputes the parent project's `contracted_mw` and `available_mw` and
    increments that project's `version` by one."

    "Thereafter `contracted_mw` is always the sum of `contracted_mw` over the
    project's deals whose `status` is `EXECUTED` or `EFFECTIVE`, and `available_mw` is
    `capacity_mw` less `contracted_mw`."

    "The deal's `unallocated_mw` is then recomputed as `contracted_mw` less the sum of
    `allocated_mw` over the slices whose `status` is `PROPOSED` or `CONFIRMED`, both
    the slice's `version` and the deal's `version` increment by one."

    "A `CONFIRM` moves the slice `PROPOSED → CONFIRMED`, requires that the deal's
    `status` is `TERM_SHEET_ISSUED`, `UNDER_NEGOTIATION` or `TERMS_AGREED` and that
    the referenced buyer's `qualification_status` is `QUALIFIED` or `CONDITIONAL`, and
    stamps `confirmed_at` with the logical clock."

    "Equality is allowed, and confirming exactly to the contracted total drives
    `unallocated_mw` to 0.000."

    "`confirmed_allocated_mw` must equal `contracted_mw` exactly, or the answer is
    `ERR_ALLOCATION_INCOMPLETE`; a single-buyer deal satisfies this with one confirmed
    slice equal to the contracted total."

    Design: Corner/consistency_model/immediate_consistency_every_write_response_and_neighbour_read_is_already_current
    """
    node = fx.create_node(api)
    buyer = fx.create_qualified_offtaker(api)
    project = fx.create_project(api, node["id"])
    asserts.assert_mw(project["contracted_mw"], 0.000, "contracted_mw")
    asserts.assert_mw(project["available_mw"], PROJECT_CAPACITY_MW,
                      "available_mw")

    deal = fx.create_deal(api, project["id"], buyer["id"], node["id"])
    deal_v1 = deal["version"]

    # A read of a different entity, with no intervening write.
    parent = fx.read_project(api, project["id"])
    asserts.assert_version_advanced_by(project["version"], parent["version"], 1,
                                       "project version")
    asserts.assert_mw(parent["contracted_mw"], 0.000, "contracted_mw")
    asserts.assert_mw(parent["available_mw"], PROJECT_CAPACITY_MW,
                      "available_mw")

    fx.table_round(api, deal["id"], response_deadline="2026-09-01T00:00:00Z")
    slice_row = fx.propose_allocation(api, deal["id"], buyer["id"],
                                      CONTRACTED_MW)
    proposed_view = fx.read_deal(api, deal["id"])
    asserts.assert_mw(proposed_view["unallocated_mw"], 0.000, "unallocated_mw")
    asserts.assert_mw(proposed_view["confirmed_allocated_mw"], 0.000,
                      "confirmed_allocated_mw")

    fx.confirm_allocation(api, slice_row["id"], buyer["id"])
    confirmed_view = fx.read_deal(api, deal["id"])
    asserts.assert_mw(confirmed_view["confirmed_allocated_mw"], CONTRACTED_MW,
                      "confirmed_allocated_mw")
    asserts.assert_mw(confirmed_view["unallocated_mw"], 0.000, "unallocated_mw")
    assert confirmed_view["version"] > proposed_view["version"] > deal_v1, \
        (deal_v1, proposed_view["version"], confirmed_view["version"])

    # Signing is a cascade, and the parent's ledger does not lag it either.
    fx.respond_accept(api, fx.list_all(
        api.list_rounds(deal["id"], ORIGINATOR))[0][0]["id"], buyer["id"])
    fx.approve_credit(api, deal["id"])
    executed = fx.execute_deal(api, deal["id"])
    assert executed["status"] == "EXECUTED", executed

    booked = fx.read_project(api, project["id"])
    asserts.assert_mw(booked["contracted_mw"], CONTRACTED_MW, "contracted_mw")
    asserts.assert_mw(booked["available_mw"], AVAILABLE_AFTER_EXECUTION_MW,
                      "available_mw")
