"""Which refusal a buyout operator sees when one request breaks two rules at once.

A lapsed offer accepted against an underfunded pool, a closing signed by the manager who
priced the deal while a landowner dispute is open, a closing demanded before escrow was
funded, and a prepaid-rent proposal written against a perpetual valuation for more than the
bid ceiling allows: in every one of these the request is doubly disqualified, and the PRD's
validation order decides which single error the caller is told about and what the pipeline
looks like afterwards.
"""

from test_helpers import (
    ApiErrorId,
    CANONICAL,
    DisputeType,
    OfferType,
    PM_APPROVER_USER_ID,
    PM_CLOSER_USER_ID,
    build_chain,
    close_payload,
    deal_cleared_to_close,
    deal_escrowed,
    deal_in_outreach,
    make_acquisition_analyst_headers,
    make_platform_admin_headers,
    make_portfolio_manager_headers,
    make_servicing_agent_headers,
    offer_payload,
    open_dispute,
    read_lease_stream,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

# The canonical seed stream prices at 44,627,011 cents under LUMP_SUM_PERPETUAL, so the
# negotiating ceiling is 44,627,011 * 10500 / 10000 rounded half up = 46,858,362 cents
# (PRD 3.4). A 36,000,000 cent purchase carries a 150 bps broker fee of 540,000 cents, so
# the commitment the pool must set aside is 36,540,000 cents (PRD 3.7).
MAX_BID_CENTS = 46_858_362
GROSS_CENTS = 36_000_000
BROKER_FEE_CENTS = 540_000
TOTAL_COMMITMENT_CENTS = GROSS_CENTS + BROKER_FEE_CENTS
ONE_DISPUTE_HOLDBACK_CENTS = 900_000

STARVED_POOL_CENTS = 30_000_000
OFFER_EXPIRES_AT = "2026-09-30T00:00:00Z"
ONE_DAY_PAST_EXPIRY = "2026-10-01T00:00:00Z"
ABOVE_CEILING_CENTS = 50_000_000


def _read_deal(api, deal_id):
    return validate_success(api.get_deal(deal_id, headers=make_acquisition_analyst_headers()))


def _read_offer(api, deal_id, offer_id):
    offers, _meta = validate_paginated(api.list_offers(deal_id, headers=make_acquisition_analyst_headers()))
    matching = [offer for offer in offers if offer["id"] == offer_id]
    assert matching, f"offer {offer_id} is no longer listed under deal {deal_id}"
    return matching[0]


def _read_portfolio(api, portfolio_id):
    return validate_success(api.get_portfolio(portfolio_id, headers=make_platform_admin_headers()))


def _read_settlement(api, deal_id):
    return validate_success(api.get_settlement(deal_id, headers=make_acquisition_analyst_headers()))


def _read_landowner(api, landowner_id):
    return validate_success(api.get_landowner(landowner_id, headers=make_acquisition_analyst_headers()))


def _lapsed_offer_on_starved_pool(api):
    """A sent offer the landowner can no longer act on, funded by a pool that is too small."""
    scenario = build_chain(
        api,
        "offer_sent",
        portfolio={"total_capital_cents": STARVED_POOL_CENTS},
        offer={"expires_at": OFFER_EXPIRES_AT},
    )
    assert scenario["offer"]["amount_cents"] == GROSS_CENTS
    set_clock(api, ONE_DAY_PAST_EXPIRY)
    return scenario


# ===========================================================================
# Expiry of the offer outranks the shortfall in the capital pool
# ===========================================================================


def test_acceptance_past_expiry_reports_expiry_rather_than_pool_shortfall(api):
    """A landowner accepting a day after the offer lapsed is told the offer expired, even though
    the 30,000,000 cent pool could never have funded the 36,540,000 cent commitment.

    PRD 2.8: "Checks are evaluated in the following order, and the **first** failing check determines the response; later checks are not evaluated once an earlier one has failed."
    PRD 2.8: "13. **Offer not expired** — the current instant is strictly before `expires_at`, checked for the counter, accept, and reject verbs; otherwise `ERR_OFFER_EXPIRED` (409)."
    PRD 2.8: "41. **Portfolio capital sufficient** — the portfolio's `available_capital_cents` is greater than or equal to the deal's `total_commitment_cents` at acceptance; otherwise `ERR_INSUFFICIENT_PORTFOLIO_CAPITAL` (402)."

    Design: Difficulty/priority_pair_validation_conflict/offer_expired_precedes_insufficient_portfolio_capital
    """
    scenario = _lapsed_offer_on_starved_pool(api)

    pool_before = _read_portfolio(api, scenario.portfolio_id)
    assert pool_before["available_capital_cents"] == STARVED_POOL_CENTS
    assert pool_before["available_capital_cents"] < TOTAL_COMMITMENT_CENTS

    response = api.transition_offer(
        scenario.offer_id, {"action": "ACCEPT"}, headers=scenario.landowner_headers
    )
    validate_error(response, ApiErrorId.ERR_OFFER_EXPIRED.value, 409)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_INSUFFICIENT_PORTFOLIO_CAPITAL.value


def test_lapsed_offer_acceptance_leaves_capital_uncommitted_and_deal_in_negotiation(api):
    """The refused acceptance reserves nothing: the offer reads back LAPSED, the deal stays in
    NEGOTIATION with no agreed consideration, and the capital pool is untouched.

    PRD 2.8: "Checks are evaluated in the following order, and the **first** failing check determines the response; later checks are not evaluated once an earlier one has failed."
    PRD 2.8: "13. **Offer not expired** — the current instant is strictly before `expires_at`, checked for the counter, accept, and reject verbs; otherwise `ERR_OFFER_EXPIRED` (409)."
    PRD 2.8: "41. **Portfolio capital sufficient** — the portfolio's `available_capital_cents` is greater than or equal to the deal's `total_commitment_cents` at acceptance; otherwise `ERR_INSUFFICIENT_PORTFOLIO_CAPITAL` (402)."

    Design: Difficulty/priority_pair_validation_conflict/offer_expired_precedes_insufficient_portfolio_capital
    """
    scenario = _lapsed_offer_on_starved_pool(api)

    response = api.transition_offer(
        scenario.offer_id, {"action": "ACCEPT"}, headers=scenario.landowner_headers
    )
    validate_error(response, ApiErrorId.ERR_OFFER_EXPIRED.value, 409)

    offer = _read_offer(api, scenario.deal_id, scenario.offer_id)
    assert offer["status"] == "LAPSED"
    assert offer.get("decided_at") is None

    deal = _read_deal(api, scenario.deal_id)
    assert deal["stage"] == "NEGOTIATION"
    assert deal["capital_state"] == "UNCOMMITTED"
    assert deal.get("agreed_consideration_cents") is None

    pool = _read_portfolio(api, scenario.portfolio_id)
    assert pool["committed_capital_cents"] == 0
    assert pool["deployed_capital_cents"] == 0
    assert pool["available_capital_cents"] == STARVED_POOL_CENTS


# ===========================================================================
# The duty split outranks the unresolved dispute at closing
# ===========================================================================


def _escrowed_deal_with_open_dispute(api):
    """Escrow funded on a cleared deal, then the landowner opens an access dispute."""
    scenario = deal_escrowed(api, approver_user_id=PM_APPROVER_USER_ID)
    scenario["deal"] = _read_deal(api, scenario.deal_id)
    assert scenario["deal"]["stage"] == "CLEAR_TO_CLOSE"
    assert scenario["deal"]["capital_state"] == "ESCROWED"
    scenario["dispute"] = open_dispute(
        api,
        scenario.lease_stream_id,
        landowner_id=scenario.landowner_id,
        dispute_type=DisputeType.ACCESS.value,
        description="Access road blocked by new fencing",
    )
    return scenario


def test_close_by_the_pricing_manager_reports_duty_split_rather_than_open_dispute(api):
    """The manager who approved the valuation tries to sign the closing while an access dispute is
    open on the stream, and is turned away on identity grounds rather than on the dispute.

    PRD 2.8: "Checks are evaluated in the following order, and the **first** failing check determines the response; later checks are not evaluated once an earlier one has failed."
    PRD 2.8: "9. **Segregation of duties** — the `PortfolioManager` closing a deal is not the user recorded as `approved_by_user_id` on the deal's pinned valuation; otherwise `ERR_SEGREGATION_OF_DUTIES` (403)."
    PRD 2.8: "25. **No unresolved dispute at close** — no dispute on the lease stream is `OPEN`, `CURE_PENDING`, or `REOPENED` at closing; otherwise `ERR_OPEN_DISPUTE_BLOCKS_CLOSE` (422)."
    PRD 2.8: "And because segregation of duties sits at position 9, a closing attempt by the approving manager is refused on identity grounds even when the deal is also blocked by an open title exception."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_precedes_open_dispute_close_block
    """
    scenario = _escrowed_deal_with_open_dispute(api)
    assert scenario["dispute"]["status"] == "OPEN"

    # The holdback proves the losing rule is genuinely violated: one unresolved dispute
    # holds back 250 bps of the 36,000,000 cent gross, i.e. 900,000 cents (PRD 3.7).
    settlement = _read_settlement(api, scenario.deal_id)
    assert settlement["holdback_cents"] == ONE_DISPUTE_HOLDBACK_CENTS

    response = api.close_deal(
        scenario.deal_id,
        close_payload("BK1420-PG318"),
        headers=make_portfolio_manager_headers(PM_APPROVER_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_OPEN_DISPUTE_BLOCKS_CLOSE.value


def test_refused_close_by_pricing_manager_leaves_escrow_undisbursed_and_stream_unacquired(api):
    """Nothing the closing cascade would have done happened: the deal is still cleared and
    escrowed, the easement is only drafted, and the stream is still merely under offer.

    PRD 2.8: "Checks are evaluated in the following order, and the **first** failing check determines the response; later checks are not evaluated once an earlier one has failed."
    PRD 2.8: "9. **Segregation of duties** — the `PortfolioManager` closing a deal is not the user recorded as `approved_by_user_id` on the deal's pinned valuation; otherwise `ERR_SEGREGATION_OF_DUTIES` (403)."
    PRD 2.8: "25. **No unresolved dispute at close** — no dispute on the lease stream is `OPEN`, `CURE_PENDING`, or `REOPENED` at closing; otherwise `ERR_OPEN_DISPUTE_BLOCKS_CLOSE` (422)."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_precedes_open_dispute_close_block
    """
    scenario = _escrowed_deal_with_open_dispute(api)

    response = api.close_deal(
        scenario.deal_id,
        close_payload("BK1420-PG318"),
        headers=make_portfolio_manager_headers(PM_APPROVER_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    deal = _read_deal(api, scenario.deal_id)
    assert deal["stage"] == "CLEAR_TO_CLOSE"
    assert deal["capital_state"] == "ESCROWED"
    assert deal["easement_status"] == "DRAFTED"
    assert deal["escrow_funded_cents"] == TOTAL_COMMITMENT_CENTS
    assert deal["escrow_disbursed_cents"] == 0
    assert deal.get("recording_ref") is None
    assert deal.get("closed_by_user_id") is None

    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert stream["acquisition_status"] == "UNDER_OFFER"
    assert stream["rent_redirection_status"] == "NOT_APPLICABLE"

    landowner = _read_landowner(api, scenario.landowner_id)
    assert landowner["outreach_status"] == "UNDER_CONTRACT"

    dispute = validate_success(
        api.get_dispute(scenario["dispute"]["id"], headers=make_servicing_agent_headers())
    )
    assert dispute["status"] == "OPEN"


# ===========================================================================
# The capital state outranks the unresolved dispute at closing
# ===========================================================================


def _cleared_deal_without_escrow_and_with_open_dispute(api):
    """A cleared deal whose escrow was never funded, carrying an open interference dispute."""
    scenario = deal_cleared_to_close(api, approver_user_id=PM_APPROVER_USER_ID)
    scenario["deal"] = _read_deal(api, scenario.deal_id)
    assert scenario["deal"]["stage"] == "CLEAR_TO_CLOSE"
    assert scenario["deal"]["capital_state"] == "RESERVED"
    scenario["dispute"] = open_dispute(
        api,
        scenario.lease_stream_id,
        landowner_id=scenario.landowner_id,
        dispute_type=DisputeType.INTERFERENCE.value,
        description="Rooftop antenna interferes with irrigation controls",
    )
    return scenario


def test_close_before_escrow_funding_reports_capital_state_rather_than_open_dispute(api):
    """A manager who is not the valuation approver demands closing on a deal whose capital is only
    reserved; the capital-state conflict answers, not the open interference dispute.

    PRD 2.8: "Checks are evaluated in the following order, and the **first** failing check determines the response; later checks are not evaluated once an earlier one has failed."
    PRD 2.8: "15. **Capital state admits the action** — the deal's `capital_state` permits the capital operation; otherwise `ERR_INVALID_CAPITAL_STATE` (409)."
    PRD 2.8: "25. **No unresolved dispute at close** — no dispute on the lease stream is `OPEN`, `CURE_PENDING`, or `REOPENED` at closing; otherwise `ERR_OPEN_DISPUTE_BLOCKS_CLOSE` (422)."

    Design: Difficulty/priority_pair_validation_conflict/invalid_capital_state_precedes_open_dispute_close_block
    """
    scenario = _cleared_deal_without_escrow_and_with_open_dispute(api)
    assert scenario["dispute"]["status"] == "OPEN"
    assert scenario["deal"]["capital_state"] == "RESERVED"

    # One unresolved dispute holds back 250 bps of the 36,000,000 cent gross (PRD 3.7),
    # which shows the dispute rule is genuinely disqualifying on this same call.
    settlement = _read_settlement(api, scenario.deal_id)
    assert settlement["holdback_cents"] == ONE_DISPUTE_HOLDBACK_CENTS

    response = api.close_deal(
        scenario.deal_id,
        close_payload("BK1420-PG319"),
        headers=make_portfolio_manager_headers(PM_CLOSER_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_CAPITAL_STATE.value, 409)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_OPEN_DISPUTE_BLOCKS_CLOSE.value


def test_unfunded_close_attempt_leaves_capital_reserved_and_nothing_deployed(api):
    """The refused closing disburses nothing: capital stays RESERVED with an empty escrow, and the
    portfolio has deployed no money at all.

    PRD 2.8: "Checks are evaluated in the following order, and the **first** failing check determines the response; later checks are not evaluated once an earlier one has failed."
    PRD 2.8: "15. **Capital state admits the action** — the deal's `capital_state` permits the capital operation; otherwise `ERR_INVALID_CAPITAL_STATE` (409)."
    PRD 2.8: "25. **No unresolved dispute at close** — no dispute on the lease stream is `OPEN`, `CURE_PENDING`, or `REOPENED` at closing; otherwise `ERR_OPEN_DISPUTE_BLOCKS_CLOSE` (422)."

    Design: Difficulty/priority_pair_validation_conflict/invalid_capital_state_precedes_open_dispute_close_block
    """
    scenario = _cleared_deal_without_escrow_and_with_open_dispute(api)

    response = api.close_deal(
        scenario.deal_id,
        close_payload("BK1420-PG319"),
        headers=make_portfolio_manager_headers(PM_CLOSER_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_CAPITAL_STATE.value, 409)

    deal = _read_deal(api, scenario.deal_id)
    assert deal["stage"] == "CLEAR_TO_CLOSE"
    assert deal["capital_state"] == "RESERVED"
    assert deal["escrow_funded_cents"] == 0
    assert deal["escrow_disbursed_cents"] == 0
    assert deal["escrow_holdback_cents"] == 0
    assert deal.get("recorded_at") is None

    pool = _read_portfolio(api, scenario.portfolio_id)
    assert pool["deployed_capital_cents"] == 0
    assert pool["committed_capital_cents"] == TOTAL_COMMITMENT_CENTS

    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert stream["acquisition_status"] == "UNDER_OFFER"


# ===========================================================================
# The offer-to-valuation method match outranks the bid guardrail
# ===========================================================================


def _prepaid_proposal_above_ceiling(api):
    """A perpetual-valuation deal in outreach, plus a prepaid proposal over the bid ceiling."""
    scenario = deal_in_outreach(api)
    assert scenario["valuation"]["method"] == "LUMP_SUM_PERPETUAL"
    assert scenario["valuation"]["max_bid_cents"] == MAX_BID_CENTS == CANONICAL["MAX_BID_CENTS"]
    assert ABOVE_CEILING_CENTS > scenario["valuation"]["max_bid_cents"]
    payload = offer_payload(
        offer_type=OfferType.PREPAID_RENT.value,
        amount_cents=ABOVE_CEILING_CENTS,
        prepaid_term_months=120,
        expires_at="2026-12-31T00:00:00Z",
    )
    return scenario, payload


def test_prepaid_proposal_on_perpetual_valuation_reports_method_mismatch_rather_than_guardrail(api):
    """A PREPAID_RENT proposal of 50,000,000 cents is written against a LUMP_SUM_PERPETUAL
    valuation whose ceiling is 46,858,362 cents, and the method mismatch is what answers.

    PRD 2.8: "Checks are evaluated in the following order, and the **first** failing check determines the response; later checks are not evaluated once an earlier one has failed."
    PRD 2.8: "29. **Offer type matches valuation method** — a `LUMP_SUM` offer requires a pinned valuation whose `method` is `LUMP_SUM_PERPETUAL`, and a `PREPAID_RENT` offer requires a pinned valuation whose `method` is `PREPAID_RENT_TERM`; otherwise `ERR_VALUATION_METHOD_MISMATCH` (422)."
    PRD 2.8: "39. **Offer within the bid guardrail** — the offer's `amount_cents` is less than or equal to the pinned valuation's `max_bid_cents`; otherwise `ERR_OFFER_EXCEEDS_GUARDRAIL` (422)."

    Design: Difficulty/priority_pair_validation_conflict/valuation_method_mismatch_precedes_offer_guardrail_breach
    """
    scenario, payload = _prepaid_proposal_above_ceiling(api)

    response = api.create_offer(scenario.deal_id, payload, headers=make_acquisition_analyst_headers())
    validate_error(response, ApiErrorId.ERR_VALUATION_METHOD_MISMATCH.value, 422)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_OFFER_EXCEEDS_GUARDRAIL.value


def test_mismatched_prepaid_proposal_leaves_deal_in_outreach_with_no_proposal_on_file(api):
    """The rejected proposal never becomes a negotiating instrument: the deal is still in outreach
    at round zero, no offer is on file, and the landowner has not been contacted.

    PRD 2.8: "Checks are evaluated in the following order, and the **first** failing check determines the response; later checks are not evaluated once an earlier one has failed."
    PRD 2.8: "29. **Offer type matches valuation method** — a `LUMP_SUM` offer requires a pinned valuation whose `method` is `LUMP_SUM_PERPETUAL`, and a `PREPAID_RENT` offer requires a pinned valuation whose `method` is `PREPAID_RENT_TERM`; otherwise `ERR_VALUATION_METHOD_MISMATCH` (422)."
    PRD 2.8: "39. **Offer within the bid guardrail** — the offer's `amount_cents` is less than or equal to the pinned valuation's `max_bid_cents`; otherwise `ERR_OFFER_EXCEEDS_GUARDRAIL` (422)."

    Design: Difficulty/priority_pair_validation_conflict/valuation_method_mismatch_precedes_offer_guardrail_breach
    """
    scenario, payload = _prepaid_proposal_above_ceiling(api)

    response = api.create_offer(scenario.deal_id, payload, headers=make_acquisition_analyst_headers())
    validate_error(response, ApiErrorId.ERR_VALUATION_METHOD_MISMATCH.value, 422)

    offers, meta = validate_paginated(
        api.list_offers(scenario.deal_id, headers=make_acquisition_analyst_headers())
    )
    assert meta["total_count"] == 0
    assert offers == []

    deal = _read_deal(api, scenario.deal_id)
    assert deal["stage"] == "OUTREACH"
    assert deal["negotiation_rounds"] == 0

    landowner = _read_landowner(api, scenario.landowner_id)
    assert landowner["outreach_status"] == "NEW"

    valuations, _valuation_meta = validate_paginated(
        api.list_valuations(scenario.lease_stream_id, headers=make_acquisition_analyst_headers())
    )
    pinned = [row for row in valuations if row["id"] == scenario.valuation_id][0]
    assert pinned["max_bid_cents"] == MAX_BID_CENTS
    assert pinned["status"] == "APPROVED"
