"""Closing a funded buyout is the widest fan-out in the pipeline, and every consequence of
it — the closed stage, the disbursed escrow, the recorded easement, the portfolio ledger,
the acquired stream and its rent redirection — is already final in the body the close call
itself returns, with the later reads merely repeating what was written.
"""

from typing import Any, Dict

from test_helpers import (
    PM_CLOSER_USER_ID,
    TEST_DEFAULTS,
    THRESHOLDS,
    ApiClient,
    assert_escrow_accounts_for_funding,
    assert_fields,
    assert_fields_match,
    assert_portfolio_ledger_balances,
    assert_settlement_arithmetic,
    assert_utilization_and_posture,
    bps_of,
    close_payload,
    deal_escrowed,
    is_iso8601_timestamp,
    make_acquisition_analyst_headers,
    make_platform_admin_headers,
    make_portfolio_manager_headers,
    make_servicing_agent_headers,
    validate_paginated,
    validate_success,
)

# The canonical seed drives the whole arithmetic: the accepted offer is the gross.
GROSS_CENTS = TEST_DEFAULTS["OFFER_AMOUNT_CENTS"]
TOTAL_CAPITAL_CENTS = 200_000_000
RECORDING_REF = TEST_DEFAULTS["RECORDING_REF"]

# The exact projection field list PRD 3.7 pins.
SETTLEMENT_FIELDS = (
    "deal_id",
    "agreed_consideration_cents",
    "broker_fee_bps",
    "broker_fee_cents",
    "holdback_cents",
    "net_landowner_proceeds_cents",
    "total_commitment_cents",
    "escrow_funded_cents",
    "escrow_disbursed_cents",
    "escrow_holdback_cents",
    "escrow_refunded_cents",
)


def _settlement_from_prd(gross: int, open_dispute_count: int = 0) -> Dict[str, int]:
    """Recompute PRD 3.7's statement in the pinned order: tier on gross, fee, holdback, net."""
    if gross >= THRESHOLDS["BROKER_TIER_HIGH_GROSS_CENTS"]:
        broker_fee_bps = THRESHOLDS["BROKER_FEE_BPS_HIGH"]
    elif gross >= THRESHOLDS["BROKER_TIER_MID_GROSS_CENTS"]:
        broker_fee_bps = THRESHOLDS["BROKER_FEE_BPS_MID"]
    else:
        broker_fee_bps = THRESHOLDS["BROKER_FEE_BPS_LOW"]
    broker_fee_cents = bps_of(gross, broker_fee_bps)
    holdback_bps = min(
        open_dispute_count * THRESHOLDS["HOLDBACK_BPS_PER_DISPUTE"], THRESHOLDS["HOLDBACK_BPS_CAP"]
    )
    holdback_cents = bps_of(gross, holdback_bps)
    net_landowner_proceeds_cents = gross - holdback_cents
    return {
        "broker_fee_bps": broker_fee_bps,
        "broker_fee_cents": broker_fee_cents,
        "holdback_cents": holdback_cents,
        "net_landowner_proceeds_cents": net_landowner_proceeds_cents,
        "total_commitment_cents": gross + broker_fee_cents,
        "escrow_disbursed_cents": net_landowner_proceeds_cents + broker_fee_cents,
    }


def _close_a_funded_deal(api: ApiClient) -> tuple:
    """Fund escrow on a cleared deal, then close it and hand back the write response body."""
    scenario = deal_escrowed(api, portfolio={"total_capital_cents": TOTAL_CAPITAL_CENTS})
    response = api.close_deal(
        scenario.deal_id,
        close_payload(RECORDING_REF),
        headers=make_portfolio_manager_headers(PM_CLOSER_USER_ID),
    )
    written = validate_success(response)
    return scenario, written


# ---------------------------------------------------------------------------
# The write response body itself
# ---------------------------------------------------------------------------


def test_close_response_body_alone_reports_the_closed_disbursed_and_recorded_deal(api: ApiClient) -> None:
    """The body the close call returns already carries the closed stage, the disbursed capital
    state, the recorded easement with its county reference, and the escrow split — nothing is
    read back to make those values appear.

    PRD 3.7: "The deal moves `CLEAR_TO_CLOSE → CLOSED` and records `closed_by_user_id`."
    PRD 3.7: "Capital moves `ESCROWED → DISBURSED`, with `escrow_disbursed_cents` set to the sum of `net_landowner_proceeds_cents` and `broker_fee_cents` and `escrow_holdback_cents` set to `holdback_cents`, so that the disbursement and the retained holdback together account for everything that was funded."
    PRD 3.7: "`easement_status` moves `DRAFTED → RECORDED`, with `recording_ref` stored and `recorded_at` stamped from the current instant."

    Design: Corner/consistency_model/immediate_the_close_response_itself_reports_the_disbursed_ledger_before_any_re_read
    """
    expected = _settlement_from_prd(GROSS_CENTS)
    _, written = _close_a_funded_deal(api)

    assert_fields(
        written,
        {
            "stage": "CLOSED",
            "capital_state": "DISBURSED",
            "easement_status": "RECORDED",
            "recording_ref": RECORDING_REF,
            "closed_by_user_id": PM_CLOSER_USER_ID,
            "agreed_consideration_cents": GROSS_CENTS,
            "escrow_funded_cents": expected["total_commitment_cents"],
            "escrow_disbursed_cents": expected["escrow_disbursed_cents"],
            "escrow_holdback_cents": expected["holdback_cents"],
        },
        label="close write response",
    )
    assert is_iso8601_timestamp(written["recorded_at"]), (
        f"recorded_at must be stamped in the close response, got {written.get('recorded_at')!r}"
    )
    assert_escrow_accounts_for_funding(written)


# ---------------------------------------------------------------------------
# Write body versus the subsequent read
# ---------------------------------------------------------------------------


def test_deal_read_after_closing_repeats_the_close_response_field_for_field(api: ApiClient) -> None:
    """Every field captured from the close write response comes back identical on the next read
    of the deal, so no reconciliation happens between the two requests.

    PRD 2.10: "They are recomputed immediately — within the same request that caused the change — rather than on a schedule."
    PRD 2.10: "Consistency is immediate everywhere; there is no eventual-consistency window and no deferred reconciliation job."

    Design: Corner/consistency_model/immediate_the_close_response_itself_reports_the_disbursed_ledger_before_any_re_read
    """
    scenario, written = _close_a_funded_deal(api)

    read_back = validate_success(
        api.get_deal(scenario.deal_id, headers=make_portfolio_manager_headers(PM_CLOSER_USER_ID))
    )

    assert_fields_match(
        written,
        read_back,
        (
            "id",
            "portfolio_id",
            "lease_stream_id",
            "valuation_id",
            "stage",
            "capital_state",
            "rofr_state",
            "easement_status",
            "recording_ref",
            "recorded_at",
            "closed_by_user_id",
            "agreed_consideration_cents",
            "broker_fee_bps",
            "broker_fee_cents",
            "holdback_cents",
            "net_landowner_proceeds_cents",
            "total_commitment_cents",
            "escrow_funded_cents",
            "escrow_disbursed_cents",
            "escrow_holdback_cents",
            "escrow_refunded_cents",
            "version",
            "updated_at",
        ),
        label="closed Deal",
    )


# ---------------------------------------------------------------------------
# The capital ledger in the same instant
# ---------------------------------------------------------------------------


def test_portfolio_ledger_moves_committed_into_deployed_in_the_same_instant_as_the_close(
    api: ApiClient,
) -> None:
    """The pool's ledger has already shifted the whole commitment out of committed capital and
    into deployed capital by the time the close response is in hand, by exactly the amount that
    response itself reports as funded into escrow.

    PRD 3.7: "Finally the portfolio's `deployed_capital_cents` rises by the commitment, its `committed_capital_cents` falls by the same amount, and `available_capital_cents`, `utilization_bps`, and `capital_posture` are all recomputed."
    PRD 3.7: "It takes capital `RESERVED → ESCROWED` and sets `escrow_funded_cents` equal to `total_commitment_cents`."
    PRD 2.10: "A portfolio's `active_deal_count` specifically counts the deals on that portfolio whose `stage` is none of `CLOSED`, `DEAD`, `ROFR_LOST`, and `TERMINATED`."

    Design: Corner/consistency_model/immediate_the_close_response_itself_reports_the_disbursed_ledger_before_any_re_read
    """
    expected = _settlement_from_prd(GROSS_CENTS)
    scenario, written = _close_a_funded_deal(api)

    commitment_reported_by_the_close = written["escrow_funded_cents"]
    assert commitment_reported_by_the_close == expected["total_commitment_cents"], (
        f"the close response reports escrow_funded_cents {commitment_reported_by_the_close}, "
        f"expected the commitment {expected['total_commitment_cents']}"
    )

    portfolio = validate_success(api.get_portfolio(scenario.portfolio_id, headers=make_platform_admin_headers()))

    assert_fields(
        portfolio,
        {
            "total_capital_cents": TOTAL_CAPITAL_CENTS,
            "committed_capital_cents": 0,
            "deployed_capital_cents": commitment_reported_by_the_close,
            "available_capital_cents": TOTAL_CAPITAL_CENTS - commitment_reported_by_the_close,
            "active_deal_count": 0,
        },
        label="portfolio ledger after the close",
    )
    assert_portfolio_ledger_balances(portfolio)
    assert_utilization_and_posture(portfolio)


# ---------------------------------------------------------------------------
# The asset side in the same instant
# ---------------------------------------------------------------------------


def test_stream_is_already_acquired_with_rent_redirection_sent_on_the_first_read_after_close(
    api: ApiClient,
) -> None:
    """The first read of the lease stream after the close already shows it acquired, performing,
    and with rent redirection served to its sitting carrier.

    PRD 3.7: "The stream moves to `acquisition_status` `ACQUIRED` and `servicing_status` `PERFORMING`."
    PRD 3.7: "Every carrier tenancy on the stream in `ACTIVE` or `HOLDOVER` has its `redirection_notice_status` set to `SENT`, and the stream's own `rent_redirection_status` becomes `SENT`."
    PRD 3.3: "A new tenancy begins life with `status` `ACTIVE`."
    PRD 3.3: "`active_tenancy_count` counts the tenancies in `ACTIVE` or `HOLDOVER`."

    Design: Corner/consistency_model/immediate_the_close_response_itself_reports_the_disbursed_ledger_before_any_re_read
    """
    scenario, _ = _close_a_funded_deal(api)

    stream = validate_success(
        api.get_lease_stream(scenario.lease_stream_id, headers=make_acquisition_analyst_headers())
    )
    assert_fields(
        stream,
        {
            "acquisition_status": "ACQUIRED",
            "servicing_status": "PERFORMING",
            "rent_redirection_status": "SENT",
            "active_tenancy_count": 1,
        },
        label="acquired LeaseStream",
    )

    tenancies, meta = validate_paginated(
        api.list_tenancies(scenario.lease_stream_id, headers=make_servicing_agent_headers())
    )
    assert meta["total_count"] == 1, f"expected one tenancy on the stream, meta reports {meta['total_count']}"
    for tenancy in tenancies:
        assert_fields(
            tenancy,
            {"status": "ACTIVE", "redirection_notice_status": "SENT"},
            label="carrier tenancy after the close",
        )


def test_landowner_outreach_is_already_closed_on_the_first_read_after_close(api: ApiClient) -> None:
    """The counterparty's outreach record is already final on the first read after the close; the
    landowner does not linger at UNDER_CONTRACT waiting for a sweep.

    PRD 3.7: "The landowner's `outreach_status` becomes `CLOSED`."

    Design: Corner/consistency_model/immediate_the_close_response_itself_reports_the_disbursed_ledger_before_any_re_read
    """
    scenario, _ = _close_a_funded_deal(api)

    landowner = validate_success(
        api.get_landowner(scenario.landowner_id, headers=make_acquisition_analyst_headers())
    )
    assert_fields(
        landowner,
        {"outreach_status": "CLOSED"},
        label="landowner after the close",
    )


# ---------------------------------------------------------------------------
# The settlement projection in the same instant
# ---------------------------------------------------------------------------


def test_settlement_projection_read_after_close_agrees_with_the_close_response(api: ApiClient) -> None:
    """Read immediately after the close, the settlement projection returns exactly the fields the
    PRD pins and reports the same disbursement and retained holdback the close response carried.

    PRD 3.7: "A read-only settlement projection is available for any deal, returning `deal_id`, `agreed_consideration_cents`, `broker_fee_bps`, `broker_fee_cents`, `holdback_cents`, `net_landowner_proceeds_cents`, `total_commitment_cents`, `escrow_funded_cents`, `escrow_disbursed_cents`, `escrow_holdback_cents`, and `escrow_refunded_cents`."
    PRD 3.7: "`net_landowner_proceeds_cents` is gross less `holdback_cents`, and `total_commitment_cents` — the figure the portfolio actually has to set aside — is gross plus `broker_fee_cents`."

    Design: Corner/consistency_model/immediate_the_close_response_itself_reports_the_disbursed_ledger_before_any_re_read
    """
    expected = _settlement_from_prd(GROSS_CENTS)
    scenario, written = _close_a_funded_deal(api)

    projection: Dict[str, Any] = validate_success(
        api.get_settlement(scenario.deal_id, headers=make_portfolio_manager_headers(PM_CLOSER_USER_ID))
    )

    assert set(projection.keys()) == set(SETTLEMENT_FIELDS), (
        f"settlement projection returns {sorted(projection.keys())}, expected exactly {sorted(SETTLEMENT_FIELDS)}"
    )
    assert_fields(
        projection,
        {
            "deal_id": scenario.deal_id,
            "agreed_consideration_cents": GROSS_CENTS,
            "broker_fee_bps": expected["broker_fee_bps"],
            "broker_fee_cents": expected["broker_fee_cents"],
            "holdback_cents": expected["holdback_cents"],
            "net_landowner_proceeds_cents": expected["net_landowner_proceeds_cents"],
            "total_commitment_cents": expected["total_commitment_cents"],
            "escrow_funded_cents": expected["total_commitment_cents"],
            "escrow_disbursed_cents": expected["escrow_disbursed_cents"],
            "escrow_holdback_cents": expected["holdback_cents"],
            "escrow_refunded_cents": 0,
        },
        label="settlement projection after the close",
    )
    assert_settlement_arithmetic(projection)
    assert_escrow_accounts_for_funding(projection)
    assert_fields_match(
        written,
        projection,
        ("agreed_consideration_cents", "escrow_funded_cents", "escrow_disbursed_cents", "escrow_holdback_cents"),
        label="close response versus settlement projection",
    )
