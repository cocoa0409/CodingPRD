"""Round-trip ledger checks on the buyout pipeline: capital that an offer acceptance moves
out of a portfolio's available balance and a termination moves straight back, revenue share
that amendment events accumulate onto an acquired stream and their reversals take away again,
and escrow funding that closing or termination accounts for down to the last cent.
"""

from decimal import Decimal

from test_helpers import (
    PM_CLOSER_USER_ID,
    TEST_DEFAULTS,
    THRESHOLDS,
    Scenario,
    assert_amendment_split_exhausts_net,
    assert_escrow_accounts_for_funding,
    assert_fields,
    assert_portfolio_ledger_balances,
    assert_settlement_arithmetic,
    assert_utilization_and_posture,
    bps_of,
    build_chain,
    closed_deal,
    deal_escrowed,
    deal_in_diligence,
    make_portfolio_manager_headers,
    open_dispute,
    read_lease_stream,
    record_amendment_event,
    record_findings_payload,
    reverse_amendment_event,
    round_half_up,
    terminate_payload,
    title_report_payload,
    validate_paginated,
    validate_success,
)

# --- Figures the PRD's own arithmetic produces from the canonical seed ------------------
POOL_CENTS = TEST_DEFAULTS["PORTFOLIO_CAPITAL_CENTS"]  # 50_000_000
GROSS_CENTS = TEST_DEFAULTS["OFFER_AMOUNT_CENTS"]  # 36_000_000 accepted consideration
BROKER_FEE_CENTS = bps_of(GROSS_CENTS, THRESHOLDS["BROKER_FEE_BPS_HIGH"])  # 540_000 at 150 bps
COMMITMENT_CENTS = GROSS_CENTS + BROKER_FEE_CENTS  # 36_540_000
AVAILABLE_WHILE_COMMITTED_CENTS = POOL_CENTS - COMMITMENT_CENTS  # 13_460_000
UTILIZATION_WHILE_COMMITTED_BPS = round_half_up(
    Decimal(COMMITMENT_CENTS) * Decimal(10000) / Decimal(POOL_CENTS)
)  # 7308
ONE_DISPUTE_HOLDBACK_CENTS = bps_of(GROSS_CENTS, THRESHOLDS["HOLDBACK_BPS_PER_DISPUTE"])  # 900_000
NET_PROCEEDS_WITH_ONE_DISPUTE_CENTS = GROSS_CENTS - ONE_DISPUTE_HOLDBACK_CENTS  # 35_100_000

REVENUE_SHARE_BPS = TEST_DEFAULTS["REVENUE_SHARE_BPS"]  # 2500
COLOCATION_GROSS_CENTS = 1_000_002
COLOCATION_LANDOWNER_CENTS = bps_of(COLOCATION_GROSS_CENTS, REVENUE_SHARE_BPS)  # 250_001
COLOCATION_ACQUIRER_CENTS = COLOCATION_GROSS_CENTS - COLOCATION_LANDOWNER_CENTS  # 750_001
SECOND_COLOCATION_GROSS_CENTS = 2_000_005
SECOND_COLOCATION_LANDOWNER_CENTS = bps_of(SECOND_COLOCATION_GROSS_CENTS, REVENUE_SHARE_BPS)  # 500_001
SECOND_COLOCATION_ACQUIRER_CENTS = SECOND_COLOCATION_GROSS_CENTS - SECOND_COLOCATION_LANDOWNER_CENTS


def _closing_manager_headers():
    """The PortfolioManager who did not approve the price, per PRD section 2.12."""
    return make_portfolio_manager_headers(PM_CLOSER_USER_ID)


# ======================================================================================
# Capital reserved by an acceptance and released again by a termination
# ======================================================================================


def test_reserved_capital_returns_to_the_pool_when_the_deal_is_terminated(api, manager_headers):
    """A reservation moves 36540000 cents from available into committed, and terminating the
    deal moves exactly that much back, leaving the pool untouched at 50000000 cents.

    PRD 3.1: At every moment the three balances must add back to the whole: `available_capital_cents` plus `committed_capital_cents` plus `deployed_capital_cents` equals `total_capital_cents`.
    PRD 3.7: In both cases the deal's capital moves to `RELEASED`, the stream returns to `PROSPECT`, and the portfolio's ledger is recomputed.

    Design: Difficulty/compensating_invariant/portfolio_capital_conservation_across_reserve_then_terminate
    """
    scenario = deal_in_diligence(api)

    settlement = validate_success(api.get_settlement(scenario.deal_id, headers=manager_headers))
    assert_settlement_arithmetic(settlement, expected_open_dispute_count=0)
    assert settlement["total_commitment_cents"] == COMMITMENT_CENTS

    reserved_pool = validate_success(api.get_portfolio(scenario.portfolio_id, headers=manager_headers))
    assert_fields(
        reserved_pool,
        {
            "total_capital_cents": POOL_CENTS,
            "committed_capital_cents": COMMITMENT_CENTS,
            "deployed_capital_cents": 0,
            "available_capital_cents": AVAILABLE_WHILE_COMMITTED_CENTS,
            "utilization_bps": UTILIZATION_WHILE_COMMITTED_BPS,
            "capital_posture": "OPEN",
            "active_deal_count": 1,
        },
        "portfolio while the commitment is reserved",
    )
    assert_portfolio_ledger_balances(reserved_pool)
    assert_utilization_and_posture(reserved_pool)

    terminated = validate_success(
        api.terminate_deal(
            scenario.deal_id,
            terminate_payload("Landowner withdrew from the transaction"),
            headers=_closing_manager_headers(),
        )
    )
    assert_fields(
        terminated,
        {"stage": "TERMINATED", "capital_state": "RELEASED"},
        "terminated deal",
    )

    restored_pool = validate_success(api.get_portfolio(scenario.portfolio_id, headers=manager_headers))
    assert_fields(
        restored_pool,
        {
            "total_capital_cents": POOL_CENTS,
            "committed_capital_cents": 0,
            "deployed_capital_cents": 0,
            "available_capital_cents": POOL_CENTS,
            "utilization_bps": 0,
            "capital_posture": "OPEN",
            "active_deal_count": 0,
        },
        "portfolio after the release",
    )
    assert_portfolio_ledger_balances(restored_pool)
    assert_utilization_and_posture(restored_pool)

    assert read_lease_stream(api, scenario.lease_stream_id)["acquisition_status"] == "PROSPECT"


def test_released_capital_funds_a_second_commitment_of_the_same_size(api, manager_headers):
    """Capital returned by a termination is genuinely spendable again: a second deal on the
    same pool reserves the identical 36540000 cents and lands back on 7308 basis points.

    PRD 3.1: `committed_capital_cents` is the sum of `total_commitment_cents` across deals whose `capital_state` is `RESERVED` or `ESCROWED`.
    PRD 3.1: Utilization is measured against the whole pool: let *used* be the sum of `committed_capital_cents` and `deployed_capital_cents`; then `utilization_bps` is zero when `total_capital_cents` is zero, and otherwise is *used* multiplied by ten thousand, divided by `total_capital_cents`, and rounded half up to a whole number of basis points.
    PRD 2.10: A portfolio's `active_deal_count` specifically counts the deals on that portfolio whose `stage` is none of `CLOSED`, `DEAD`, `ROFR_LOST`, and `TERMINATED`.

    Design: Difficulty/compensating_invariant/portfolio_capital_conservation_across_reserve_then_terminate
    """
    first = deal_in_diligence(api)
    validate_success(
        api.terminate_deal(
            first.deal_id,
            terminate_payload("Site access could not be documented"),
            headers=_closing_manager_headers(),
        )
    )

    emptied_pool = validate_success(api.get_portfolio(first.portfolio_id, headers=manager_headers))
    assert_fields(
        emptied_pool,
        {
            "committed_capital_cents": 0,
            "available_capital_cents": POOL_CENTS,
            "utilization_bps": 0,
            "active_deal_count": 0,
        },
        "portfolio between the two deals",
    )
    assert_portfolio_ledger_balances(emptied_pool)

    build_chain(
        api,
        "offer_accepted",
        existing=Scenario(portfolio=first["portfolio"]),
        tower_site={"site_code": "NE-1043"},
        landowner={"legal_name": "Sagamore Ridge Trust", "contact_email": "owner@sagamore.example"},
    )

    reserved_again = validate_success(api.get_portfolio(first.portfolio_id, headers=manager_headers))
    assert_fields(
        reserved_again,
        {
            "total_capital_cents": POOL_CENTS,
            "committed_capital_cents": COMMITMENT_CENTS,
            "deployed_capital_cents": 0,
            "available_capital_cents": AVAILABLE_WHILE_COMMITTED_CENTS,
            "utilization_bps": UTILIZATION_WHILE_COMMITTED_BPS,
            "active_deal_count": 1,
        },
        "portfolio funding the replacement deal",
    )
    assert_portfolio_ledger_balances(reserved_again)
    assert_utilization_and_posture(reserved_again)


# ======================================================================================
# Cumulative revenue share accumulated by amendment events and undone by reversals
# ======================================================================================


def test_reversing_one_colocation_leaves_the_other_events_share_on_the_stream(api, servicing_headers):
    """Two 1000002-cent colocations accumulate 500002 and 1500002 cents through per-event
    rounding, and reversing one subtracts exactly that event's 250001 and 750001.

    PRD 3.8: `landowner_share_cents` is `net_amount_cents` multiplied by `share_bps_applied`, divided by ten thousand, rounded half up to a whole number of cents.
    PRD 3.8: The stream's `cumulative_revenue_share_landowner_cents` and `cumulative_revenue_share_acquirer_cents` then accumulate these **per-event rounded** figures.
    PRD 3.8: The invariant to hold is that the two cumulative fields together equal the sum of `net_amount_cents` across all `RECORDED` amendment events on the stream.

    Design: Difficulty/compensating_invariant/revenue_share_cumulative_reconciles_after_amendment_reversal
    """
    scenario = closed_deal(api)
    first = record_amendment_event(api, scenario.lease_stream_id, COLOCATION_GROSS_CENTS, effective_date="2026-09-01")
    second = record_amendment_event(api, scenario.lease_stream_id, COLOCATION_GROSS_CENTS, effective_date="2026-09-15")

    for event in (first, second):
        assert_fields(
            event,
            {
                "status": "RECORDED",
                "effective_pass_through_cents": 0,
                "share_bps_applied": REVENUE_SHARE_BPS,
                "net_amount_cents": COLOCATION_GROSS_CENTS,
                "landowner_share_cents": COLOCATION_LANDOWNER_CENTS,
                "acquirer_share_cents": COLOCATION_ACQUIRER_CENTS,
            },
            "colocation amendment event",
        )
        assert_amendment_split_exhausts_net(event)

    accumulated = read_lease_stream(api, scenario.lease_stream_id)
    assert_fields(
        accumulated,
        {
            "cumulative_revenue_share_landowner_cents": 2 * COLOCATION_LANDOWNER_CENTS,
            "cumulative_revenue_share_acquirer_cents": 2 * COLOCATION_ACQUIRER_CENTS,
        },
        "stream after both colocations",
    )
    assert accumulated["cumulative_revenue_share_landowner_cents"] != bps_of(
        2 * COLOCATION_GROSS_CENTS, REVENUE_SHARE_BPS
    ), "per-event rounding must not collapse into a single rounding over the summed gross"
    assert (
        accumulated["cumulative_revenue_share_landowner_cents"]
        + accumulated["cumulative_revenue_share_acquirer_cents"]
        == 2 * COLOCATION_GROSS_CENTS
    )

    reversed_event = reverse_amendment_event(
        api, second["id"], "Colocation cancelled by the carrier before installation"
    )
    assert_fields(
        reversed_event,
        {
            "status": "REVERSED",
            "landowner_share_cents": COLOCATION_LANDOWNER_CENTS,
            "acquirer_share_cents": COLOCATION_ACQUIRER_CENTS,
        },
        "reversed amendment event",
    )

    reconciled = read_lease_stream(api, scenario.lease_stream_id)
    assert_fields(
        reconciled,
        {
            "cumulative_revenue_share_landowner_cents": COLOCATION_LANDOWNER_CENTS,
            "cumulative_revenue_share_acquirer_cents": COLOCATION_ACQUIRER_CENTS,
        },
        "stream after the reversal",
    )

    recorded_page, recorded_meta = validate_paginated(
        api.list_amendment_events(scenario.lease_stream_id, params={"status": "RECORDED"}, headers=servicing_headers)
    )
    assert recorded_meta["total_count"] == 1
    assert [row["id"] for row in recorded_page] == [first["id"]]
    assert (
        reconciled["cumulative_revenue_share_landowner_cents"]
        + reconciled["cumulative_revenue_share_acquirer_cents"]
        == sum(row["net_amount_cents"] for row in recorded_page)
    )


def test_reversing_every_amendment_event_empties_the_cumulative_revenue_share(api, servicing_headers):
    """Two differently sized upside events are recorded and then both reversed, so the
    stream's two cumulative share fields come back to zero with no residue.

    PRD 3.8: For a `COLOCATION_ADDED` event, `effective_pass_through_cents` is zero and `share_bps_applied` is the closed deal's `revenue_share_bps` in full.
    PRD 3.8: A `ServicingAgent` reverses it — `RECORDED → REVERSED` — supplying a `reversal_reason`, which is mandatory; reversal decreases the stream's `cumulative_revenue_share_landowner_cents` by that event's `landowner_share_cents` and its `cumulative_revenue_share_acquirer_cents` by that event's `acquirer_share_cents`.

    Design: Difficulty/compensating_invariant/revenue_share_cumulative_reconciles_after_amendment_reversal
    """
    scenario = closed_deal(api)
    small = record_amendment_event(api, scenario.lease_stream_id, COLOCATION_GROSS_CENTS, effective_date="2026-09-01")
    large = record_amendment_event(
        api, scenario.lease_stream_id, SECOND_COLOCATION_GROSS_CENTS, effective_date="2026-09-20"
    )
    assert_fields(
        large,
        {
            "effective_pass_through_cents": 0,
            "share_bps_applied": REVENUE_SHARE_BPS,
            "net_amount_cents": SECOND_COLOCATION_GROSS_CENTS,
            "landowner_share_cents": SECOND_COLOCATION_LANDOWNER_CENTS,
            "acquirer_share_cents": SECOND_COLOCATION_ACQUIRER_CENTS,
        },
        "larger colocation amendment event",
    )

    both_recorded = read_lease_stream(api, scenario.lease_stream_id)
    assert_fields(
        both_recorded,
        {
            "cumulative_revenue_share_landowner_cents": COLOCATION_LANDOWNER_CENTS + SECOND_COLOCATION_LANDOWNER_CENTS,
            "cumulative_revenue_share_acquirer_cents": COLOCATION_ACQUIRER_CENTS + SECOND_COLOCATION_ACQUIRER_CENTS,
        },
        "stream carrying both events",
    )
    assert (
        both_recorded["cumulative_revenue_share_landowner_cents"]
        + both_recorded["cumulative_revenue_share_acquirer_cents"]
        == COLOCATION_GROSS_CENTS + SECOND_COLOCATION_GROSS_CENTS
    )

    reverse_amendment_event(api, large["id"], "Amendment superseded by a corrected schedule")
    after_first_reversal = read_lease_stream(api, scenario.lease_stream_id)
    assert_fields(
        after_first_reversal,
        {
            "cumulative_revenue_share_landowner_cents": COLOCATION_LANDOWNER_CENTS,
            "cumulative_revenue_share_acquirer_cents": COLOCATION_ACQUIRER_CENTS,
        },
        "stream after the larger event is reversed",
    )

    reverse_amendment_event(api, small["id"], "Colocation never installed")
    emptied = read_lease_stream(api, scenario.lease_stream_id)
    assert_fields(
        emptied,
        {
            "cumulative_revenue_share_landowner_cents": 0,
            "cumulative_revenue_share_acquirer_cents": 0,
        },
        "stream after every event is reversed",
    )

    recorded_page, recorded_meta = validate_paginated(
        api.list_amendment_events(scenario.lease_stream_id, params={"status": "RECORDED"}, headers=servicing_headers)
    )
    assert recorded_meta["total_count"] == 0
    assert (
        emptied["cumulative_revenue_share_landowner_cents"] + emptied["cumulative_revenue_share_acquirer_cents"]
        == sum(row["net_amount_cents"] for row in recorded_page)
    )


# ======================================================================================
# Escrow funding accounted for by disbursement, holdback and refund
# ======================================================================================


def test_escrow_funding_matches_the_commitment_while_a_dispute_holdback_stands(api, manager_headers, analyst_headers, title_headers, treasury_headers):
    """A dispute open at acceptance withholds 900000 cents of the 36000000-cent price, yet
    escrow is funded with the full 36540000-cent commitment before anything is paid out.

    PRD 3.7: `holdback_cents` is gross multiplied by that capped rate, divided by ten thousand, rounded half up to a whole number of cents.
    PRD 3.7: `net_landowner_proceeds_cents` is gross less `holdback_cents`, and `total_commitment_cents` — the figure the portfolio actually has to set aside — is gross plus `broker_fee_cents`.
    PRD 3.7: It takes capital `RESERVED → ESCROWED` and sets `escrow_funded_cents` equal to `total_commitment_cents`.

    Design: Difficulty/compensating_invariant/escrow_components_reconcile_at_close_with_dispute_holdback
    """
    scenario = build_chain(api, "offer_sent")
    open_dispute(
        api,
        scenario.lease_stream_id,
        landowner_id=scenario.landowner_id,
        description="Locked gate during maintenance window",
    )
    validate_success(
        api.transition_offer(scenario.offer_id, {"action": "ACCEPT"}, headers=scenario.landowner_headers)
    )

    at_acceptance = validate_success(api.get_settlement(scenario.deal_id, headers=manager_headers))
    assert_settlement_arithmetic(at_acceptance, expected_open_dispute_count=1)
    assert_fields(
        at_acceptance,
        {
            "agreed_consideration_cents": GROSS_CENTS,
            "broker_fee_bps": THRESHOLDS["BROKER_FEE_BPS_HIGH"],
            "broker_fee_cents": BROKER_FEE_CENTS,
            "holdback_cents": ONE_DISPUTE_HOLDBACK_CENTS,
            "net_landowner_proceeds_cents": NET_PROCEEDS_WITH_ONE_DISPUTE_CENTS,
            "total_commitment_cents": COMMITMENT_CENTS,
            "escrow_funded_cents": 0,
            "escrow_disbursed_cents": 0,
            "escrow_holdback_cents": 0,
            "escrow_refunded_cents": 0,
        },
        "settlement projection at acceptance",
    )

    report = validate_success(
        api.create_title_report(scenario.deal_id, title_report_payload(), headers=analyst_headers), 201
    )
    validate_success(
        api.transition_title_report(
            report["id"], record_findings_payload(exception_count=0, mortgage_present=False), headers=title_headers
        )
    )

    funded = validate_success(api.fund_escrow(scenario.deal_id, headers=treasury_headers))
    assert_fields(
        funded,
        {
            "stage": "CLEAR_TO_CLOSE",
            "capital_state": "ESCROWED",
            "escrow_funded_cents": COMMITMENT_CENTS,
            "escrow_disbursed_cents": 0,
            "escrow_holdback_cents": 0,
            "escrow_refunded_cents": 0,
        },
        "deal with escrow funded",
    )

    after_funding = validate_success(api.get_settlement(scenario.deal_id, headers=manager_headers))
    assert_fields(
        after_funding,
        {
            "holdback_cents": ONE_DISPUTE_HOLDBACK_CENTS,
            "net_landowner_proceeds_cents": NET_PROCEEDS_WITH_ONE_DISPUTE_CENTS,
            "escrow_funded_cents": COMMITMENT_CENTS,
            "escrow_disbursed_cents": 0,
            "escrow_holdback_cents": 0,
            "escrow_refunded_cents": 0,
        },
        "settlement projection after escrow funding",
    )

    committed_pool = validate_success(api.get_portfolio(scenario.portfolio_id, headers=manager_headers))
    assert_fields(
        committed_pool,
        {
            "committed_capital_cents": COMMITMENT_CENTS,
            "deployed_capital_cents": 0,
            "available_capital_cents": AVAILABLE_WHILE_COMMITTED_CENTS,
        },
        "portfolio while escrow is funded",
    )
    assert_portfolio_ledger_balances(committed_pool)


def test_closing_accounts_for_the_funded_escrow_in_disbursement_and_holdback(api, manager_headers, analyst_headers):
    """Closing an undisputed deal splits the 36540000 cents of funded escrow into a
    36540000-cent disbursement, a zero holdback and no refund.

    PRD 3.7: Capital moves `ESCROWED → DISBURSED`, with `escrow_disbursed_cents` set to the sum of `net_landowner_proceeds_cents` and `broker_fee_cents` and `escrow_holdback_cents` set to `holdback_cents`, so that the disbursement and the retained holdback together account for everything that was funded.
    PRD 3.7: Every carrier tenancy on the stream in `ACTIVE` or `HOLDOVER` has its `redirection_notice_status` set to `SENT`, and the stream's own `rent_redirection_status` becomes `SENT`.

    Design: Difficulty/compensating_invariant/escrow_components_reconcile_at_close_with_dispute_holdback
    """
    scenario = closed_deal(api)

    closed = validate_success(api.get_deal(scenario.deal_id, headers=manager_headers))
    assert_fields(
        closed,
        {
            "stage": "CLOSED",
            "capital_state": "DISBURSED",
            "easement_status": "RECORDED",
            "recording_ref": TEST_DEFAULTS["RECORDING_REF"],
            "escrow_funded_cents": COMMITMENT_CENTS,
            "escrow_disbursed_cents": GROSS_CENTS + BROKER_FEE_CENTS,
            "escrow_holdback_cents": 0,
            "escrow_refunded_cents": 0,
        },
        "closed deal",
    )
    assert_escrow_accounts_for_funding(closed)
    assert (
        closed["escrow_funded_cents"]
        == closed["escrow_disbursed_cents"] + closed["escrow_holdback_cents"] + closed["escrow_refunded_cents"]
    )

    settlement = validate_success(api.get_settlement(scenario.deal_id, headers=manager_headers))
    assert_settlement_arithmetic(settlement, expected_open_dispute_count=0)
    assert_fields(
        settlement,
        {
            "holdback_cents": 0,
            "net_landowner_proceeds_cents": GROSS_CENTS,
            "total_commitment_cents": COMMITMENT_CENTS,
            "escrow_funded_cents": COMMITMENT_CENTS,
            "escrow_disbursed_cents": GROSS_CENTS + BROKER_FEE_CENTS,
            "escrow_holdback_cents": 0,
            "escrow_refunded_cents": 0,
        },
        "settlement projection at close",
    )
    assert_escrow_accounts_for_funding(settlement)

    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert_fields(
        stream,
        {"acquisition_status": "ACQUIRED", "servicing_status": "PERFORMING", "rent_redirection_status": "SENT"},
        "acquired lease stream",
    )
    tenancies, _ = validate_paginated(api.list_tenancies(scenario.lease_stream_id, headers=analyst_headers))
    assert [row["redirection_notice_status"] for row in tenancies] == ["SENT"]

    pool = validate_success(api.get_portfolio(scenario.portfolio_id, headers=manager_headers))
    assert_fields(
        pool,
        {
            "committed_capital_cents": 0,
            "deployed_capital_cents": COMMITMENT_CENTS,
            "available_capital_cents": AVAILABLE_WHILE_COMMITTED_CENTS,
            "utilization_bps": UTILIZATION_WHILE_COMMITTED_BPS,
        },
        "portfolio after disbursement",
    )
    assert_portfolio_ledger_balances(pool)
    assert_utilization_and_posture(pool)


def test_terminating_a_cleared_deal_refunds_every_cent_of_funded_escrow(api, manager_headers):
    """Escrow funded on a cleared deal that is then terminated comes back as a refund, so the
    36540000 cents funded are accounted for with nothing disbursed and nothing held back.

    PRD 3.7: Terminating from `DILIGENCE` releases a merely reserved commitment; terminating from `CLEAR_TO_CLOSE`, where escrow may already be funded, additionally sets `escrow_refunded_cents` equal to `escrow_funded_cents` so the money is visibly returned.

    Design: Difficulty/compensating_invariant/escrow_components_reconcile_at_close_with_dispute_holdback
    """
    scenario = deal_escrowed(api)
    assert_fields(
        scenario["deal"],
        {
            "stage": "CLEAR_TO_CLOSE",
            "capital_state": "ESCROWED",
            "escrow_funded_cents": COMMITMENT_CENTS,
            "escrow_disbursed_cents": 0,
            "escrow_holdback_cents": 0,
            "escrow_refunded_cents": 0,
        },
        "deal awaiting close with escrow funded",
    )

    terminated = validate_success(
        api.terminate_deal(
            scenario.deal_id,
            terminate_payload("Landowner refused to execute the easement"),
            headers=_closing_manager_headers(),
        )
    )
    assert_fields(
        terminated,
        {
            "stage": "TERMINATED",
            "capital_state": "RELEASED",
            "escrow_funded_cents": COMMITMENT_CENTS,
            "escrow_disbursed_cents": 0,
            "escrow_holdback_cents": 0,
            "escrow_refunded_cents": COMMITMENT_CENTS,
        },
        "terminated deal after the escrow refund",
    )
    assert (
        terminated["escrow_funded_cents"]
        == terminated["escrow_disbursed_cents"]
        + terminated["escrow_holdback_cents"]
        + terminated["escrow_refunded_cents"]
    )

    settlement = validate_success(api.get_settlement(scenario.deal_id, headers=manager_headers))
    assert_fields(
        settlement,
        {
            "total_commitment_cents": COMMITMENT_CENTS,
            "escrow_funded_cents": COMMITMENT_CENTS,
            "escrow_disbursed_cents": 0,
            "escrow_holdback_cents": 0,
            "escrow_refunded_cents": COMMITMENT_CENTS,
        },
        "settlement projection after termination",
    )

    restored_pool = validate_success(api.get_portfolio(scenario.portfolio_id, headers=manager_headers))
    assert_fields(
        restored_pool,
        {
            "committed_capital_cents": 0,
            "deployed_capital_cents": 0,
            "available_capital_cents": POOL_CENTS,
            "utilization_bps": 0,
        },
        "portfolio after the escrowed commitment is released",
    )
    assert_portfolio_ledger_balances(restored_pool)
