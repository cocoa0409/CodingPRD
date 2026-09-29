"""Negotiation and servicing loops that repeat, and the counters that stop them.

An offer can bounce between the analyst and the landowner, and a landowner dispute can
bounce between the servicing agent and the landowner, but each loop is capped by a
counter rather than by a terminal state. Alongside those cycles, a deal's stage and its
capital state advance on separate tracks, so clearing title and funding escrow each move
one dimension while the other holds still.
"""

from test_helpers import (
    ApiErrorId,
    bps_of,
    deal_cleared_to_close,
    deal_in_diligence,
    deal_with_countered_offer,
    build_dispute_on_closed_stream,
    get_success_data,
    make_servicing_agent_headers,
    record_findings_payload,
    title_report_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# PRD 3.7 keys the broker tier on gross: 36,000,000 cents sits at or above the
# 30,000,000-cent rung, so the fee is 150 bps and the commitment is gross plus that fee.
ACCEPTED_GROSS_CENTS = 36_000_000
EXPECTED_BROKER_FEE_CENTS = bps_of(ACCEPTED_GROSS_CENTS, 150)
EXPECTED_COMMITMENT_CENTS = ACCEPTED_GROSS_CENTS + EXPECTED_BROKER_FEE_CENTS


# ===========================================================================
# The offer counter/revise loop and the three-round negotiation ceiling
# ===========================================================================


def test_revising_a_countered_offer_returns_it_to_sent_and_consumes_a_round(api, analyst_headers, manager_headers):
    """Revising a countered offer sends it back out, raising the round count to two,
    overwriting the amount and clearing the landowner's counter figure.

    PRD 3.5: "**`REVISE`** takes the offer back `COUNTERED → SENT` and is the analyst's answer to a counter."
    PRD 3.5: "A revision increments the deal's `negotiation_rounds`, copies the new count into `round_number`, replaces `amount_cents` with the revised figure, clears `counter_amount_cents`, and re-stamps `sent_at` from the current instant."

    Design: Difficulty/non_linear_state_machine/offer_counter_revise_cycle_bounded_by_negotiation_round_cap
    """
    scenario = deal_with_countered_offer(api)

    revised = validate_success(
        api.transition_offer(
            scenario.offer_id, {"action": "REVISE", "amount_cents": 37_000_000}, headers=analyst_headers
        )
    )
    assert revised["status"] == "SENT", f"a revised offer must go back to SENT, got {revised['status']!r}"
    assert revised["amount_cents"] == 37_000_000, (
        f"amount_cents must be replaced by the revised figure, got {revised['amount_cents']}"
    )
    assert revised["round_number"] == 2, f"round_number must copy the new count 2, got {revised['round_number']}"
    assert revised["counter_amount_cents"] in (None, 0), (
        f"counter_amount_cents must be cleared by a revision, got {revised['counter_amount_cents']!r}"
    )
    assert revised["sent_at"] is not None, "a revision re-stamps sent_at"

    deal = validate_success(api.get_deal(scenario.deal_id, headers=manager_headers))
    assert deal["negotiation_rounds"] == 2, (
        f"negotiation_rounds must be 2 after one send and one revision, got {deal['negotiation_rounds']}"
    )
    assert deal["stage"] == "NEGOTIATION", f"the deal stays in NEGOTIATION while offers cycle, got {deal['stage']!r}"


def test_fourth_revision_is_refused_once_three_negotiation_rounds_are_consumed(api, analyst_headers, manager_headers):
    """After the offer has cycled through three sends, a further revision from COUNTERED
    is refused and the offer stays parked in COUNTERED rather than reaching a terminal state.

    PRD 3.5: "It requires the deal's `negotiation_rounds` to be strictly below three, the maximum number of rounds any single deal may consume; a fourth round is refused with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`."
    PRD 3.5: "A revision increments the deal's `negotiation_rounds`, copies the new count into `round_number`, replaces `amount_cents` with the revised figure, clears `counter_amount_cents`, and re-stamps `sent_at` from the current instant."
    PRD 3.5: "**`COUNTER`** takes the offer `SENT → COUNTERED` and is available only to the deal's own landowner, only while the current instant is strictly before `expires_at` — otherwise `ERR_OFFER_EXPIRED` — and only with a `counter_amount_cents` greater than zero."

    Design: Difficulty/non_linear_state_machine/offer_counter_revise_cycle_bounded_by_negotiation_round_cap
    """
    scenario = deal_with_countered_offer(api)
    landowner_headers = scenario.landowner_headers

    # Round two, then round three: revise, counter, revise, counter.
    get_success_data(
        api.transition_offer(
            scenario.offer_id, {"action": "REVISE", "amount_cents": 37_000_000}, headers=analyst_headers
        )
    )
    get_success_data(
        api.transition_offer(
            scenario.offer_id,
            {"action": "COUNTER", "counter_amount_cents": 43_000_000},
            headers=landowner_headers,
        )
    )
    get_success_data(
        api.transition_offer(
            scenario.offer_id, {"action": "REVISE", "amount_cents": 38_000_000}, headers=analyst_headers
        )
    )
    countered = get_success_data(
        api.transition_offer(
            scenario.offer_id,
            {"action": "COUNTER", "counter_amount_cents": 44_000_000},
            headers=landowner_headers,
        )
    )
    assert countered["round_number"] == 3, (
        f"the third send leaves round_number at 3, got {countered['round_number']}"
    )

    refused = api.transition_offer(
        scenario.offer_id, {"action": "REVISE", "amount_cents": 39_000_000}, headers=analyst_headers
    )
    validate_error(refused, ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED.value)

    rows, _meta = validate_paginated(api.list_offers(scenario.deal_id, headers=analyst_headers))
    offer = next(row for row in rows if row["id"] == scenario.offer_id)
    assert offer["status"] == "COUNTERED", (
        f"the refused revision leaves the offer in COUNTERED, got {offer['status']!r}"
    )
    assert offer["amount_cents"] == 38_000_000, (
        f"the refused revision must not overwrite amount_cents, got {offer['amount_cents']}"
    )
    assert offer["counter_amount_cents"] == 44_000_000, (
        f"the landowner's standing counter survives the refusal, got {offer['counter_amount_cents']!r}"
    )
    assert offer["round_number"] == 3, f"round_number stays at 3, got {offer['round_number']}"

    deal = validate_success(api.get_deal(scenario.deal_id, headers=manager_headers))
    assert deal["negotiation_rounds"] == 3, (
        f"negotiation_rounds is capped at 3, got {deal['negotiation_rounds']}"
    )
    assert deal["stage"] == "NEGOTIATION", (
        f"the deal remains in NEGOTIATION after the refusal, got {deal['stage']!r}"
    )


# ===========================================================================
# Stage and capital state as two independently driven dimensions of one deal
# ===========================================================================


def test_title_clearance_advances_the_stage_while_capital_stays_reserved(
    api, analyst_headers, title_headers, manager_headers
):
    """Recording zero title exceptions clears the report and lifts the deal into
    CLEAR_TO_CLOSE, while the deal's capital dimension is untouched and stays RESERVED.

    PRD 3.6: "From `ORDERED`, findings with an `exception_count` of exactly zero take the report `ORDERED → CLEARED` instead, setting `consent_status` to `NOT_REQUIRED` when no mortgage is present and to `PENDING_REQUEST` when one is, and immediately re-evaluating the deal's clearance join."
    PRD 3.7: "On success the deal moves `DILIGENCE → CLEAR_TO_CLOSE` and its `easement_status` moves `NOT_DRAFTED → DRAFTED`."

    Design: Difficulty/non_linear_state_machine/deal_stage_and_capital_state_dimensions_advance_independently
    """
    scenario = deal_in_diligence(api)
    before = validate_success(api.get_deal(scenario.deal_id, headers=manager_headers))
    assert before["stage"] == "DILIGENCE", f"setup must land in DILIGENCE, got {before['stage']!r}"
    assert before["capital_state"] == "RESERVED", (
        f"acceptance reserves the capital, got {before['capital_state']!r}"
    )

    report = validate_success(
        api.create_title_report(scenario.deal_id, title_report_payload(), headers=analyst_headers), 201
    )
    report = validate_success(
        api.transition_title_report(
            report["id"], record_findings_payload(exception_count=0, mortgage_present=False), headers=title_headers
        )
    )
    assert report["review_status"] == "CLEARED", (
        f"zero exceptions clear the report outright, got {report['review_status']!r}"
    )
    assert report["consent_status"] == "NOT_REQUIRED", (
        f"an unmortgaged property needs no consent, got {report['consent_status']!r}"
    )

    deal = validate_success(api.get_deal(scenario.deal_id, headers=manager_headers))
    assert deal["stage"] == "CLEAR_TO_CLOSE", (
        f"the clearance join lifts the stage to CLEAR_TO_CLOSE, got {deal['stage']!r}"
    )
    assert deal["easement_status"] == "DRAFTED", (
        f"clearance drafts the easement, got {deal['easement_status']!r}"
    )
    assert deal["capital_state"] == "RESERVED", (
        f"the capital dimension does not move with the stage, got {deal['capital_state']!r}"
    )
    assert deal["escrow_funded_cents"] == 0, (
        f"no escrow is funded by title clearance, got {deal['escrow_funded_cents']}"
    )


def test_escrow_funding_advances_capital_while_the_stage_holds_at_clear_to_close(
    api, treasury_headers, manager_headers, admin_headers
):
    """Funding escrow moves only the capital dimension from RESERVED to ESCROWED, leaving
    the stage at CLEAR_TO_CLOSE, and the pool still counts the commitment as committed.

    PRD 3.7: "It takes capital `RESERVED → ESCROWED` and sets `escrow_funded_cents` equal to `total_commitment_cents`."
    PRD 3.1: "`committed_capital_cents` is the sum of `total_commitment_cents` across deals whose `capital_state` is `RESERVED` or `ESCROWED`."
    PRD 3.1: "`deployed_capital_cents` is the sum of `total_commitment_cents` across deals whose `capital_state` is `DISBURSED`."
    PRD 3.7: "`net_landowner_proceeds_cents` is gross less `holdback_cents`, and `total_commitment_cents` — the figure the portfolio actually has to set aside — is gross plus `broker_fee_cents`."

    Design: Difficulty/non_linear_state_machine/deal_stage_and_capital_state_dimensions_advance_independently
    """
    scenario = deal_cleared_to_close(api)
    before = validate_success(api.get_deal(scenario.deal_id, headers=manager_headers))
    assert before["stage"] == "CLEAR_TO_CLOSE", f"setup must be cleared, got {before['stage']!r}"
    assert before["capital_state"] == "RESERVED", (
        f"escrow has not been funded yet, got {before['capital_state']!r}"
    )

    funded = validate_success(api.fund_escrow(scenario.deal_id, headers=treasury_headers))
    assert funded["capital_state"] == "ESCROWED", (
        f"funding escrow moves capital to ESCROWED, got {funded['capital_state']!r}"
    )
    assert funded["stage"] == "CLEAR_TO_CLOSE", (
        f"the stage dimension does not move with the capital, got {funded['stage']!r}"
    )
    assert funded["easement_status"] == "DRAFTED", (
        f"the easement stays DRAFTED until closing records it, got {funded['easement_status']!r}"
    )
    assert funded["escrow_funded_cents"] == EXPECTED_COMMITMENT_CENTS, (
        f"escrow_funded_cents must equal total_commitment_cents {EXPECTED_COMMITMENT_CENTS}, "
        f"got {funded['escrow_funded_cents']}"
    )

    settlement = validate_success(api.get_settlement(scenario.deal_id, headers=manager_headers))
    assert settlement["total_commitment_cents"] == EXPECTED_COMMITMENT_CENTS, (
        f"total_commitment_cents is gross plus the broker fee, got {settlement['total_commitment_cents']}"
    )

    portfolio = validate_success(api.get_portfolio(scenario.portfolio_id, headers=admin_headers))
    assert portfolio["committed_capital_cents"] == EXPECTED_COMMITMENT_CENTS, (
        f"an ESCROWED deal is still committed capital, got {portfolio['committed_capital_cents']}"
    )
    assert portfolio["deployed_capital_cents"] == 0, (
        f"nothing is deployed before closing, got {portfolio['deployed_capital_cents']}"
    )


# ===========================================================================
# The dispute cure/reopen loop and the three-attempt cure ceiling
# ===========================================================================


def test_landowner_reopen_returns_a_pending_cure_for_another_servicing_attempt(api, servicing_headers, analyst_headers):
    """The servicing agent starts a cure and the landowner reopens it, and the pair can
    run the loop again; the stream drops to WATCHLIST on the first cure and stays there.

    PRD 3.8: "**`START_CURE`** takes the case `OPEN → CURE_PENDING` or `REOPENED → CURE_PENDING`."
    PRD 3.8: "Starting a cure increments `cure_attempts` and sets `cure_deadline` to thirty days after the current instant — on the first pass from `OPEN` the deadline is set, and on a repeat pass from `REOPENED` it is reset."
    PRD 3.8: "The first-pass transition out of `OPEN` also degrades the stream's servicing condition, `PERFORMING → WATCHLIST`, which in turn re-haircuts every pledge of that stream and recomputes the borrowing base of the facility holding them; a stream already on `WATCHLIST` stays there."
    PRD 3.8: "**`REOPEN`** takes the case `CURE_PENDING → REOPENED` and leaves the stream on `WATCHLIST`, awaiting another attempt."
    PRD 3.8: "A new case opens at `status` `OPEN` with `cure_attempts` at zero and no `cure_deadline`, increments the landowner's `open_dispute_count`, and — when the stream's deal has not yet closed — triggers a recomputation of that deal's settlement holdback, since an unresolved dispute is exactly what the holdback exists to cover."

    Design: Difficulty/non_linear_state_machine/dispute_cure_reopen_cycle_bounded_by_cure_attempt_cap
    """
    scenario = build_dispute_on_closed_stream(
        api, dispute_type="INTERFERENCE", description="Carrier equipment noise at night"
    )
    dispute_id = scenario["dispute"]["id"]
    assert scenario["dispute"]["status"] == "OPEN", "a new case opens at OPEN"
    assert scenario["dispute"]["cure_attempts"] == 0, "a new case opens with cure_attempts at zero"

    first_cure = validate_success(
        api.transition_dispute(dispute_id, {"action": "START_CURE"}, headers=servicing_headers)
    )
    assert first_cure["status"] == "CURE_PENDING", (
        f"START_CURE takes OPEN to CURE_PENDING, got {first_cure['status']!r}"
    )
    assert first_cure["cure_attempts"] == 1, (
        f"the first cure raises cure_attempts to 1, got {first_cure['cure_attempts']}"
    )
    assert first_cure["cure_deadline"] is not None, "the first pass out of OPEN sets a cure_deadline"

    stream = validate_success(api.get_lease_stream(scenario.lease_stream_id, headers=analyst_headers))
    assert stream["servicing_status"] == "WATCHLIST", (
        f"the first pass out of OPEN degrades the stream to WATCHLIST, got {stream['servicing_status']!r}"
    )

    reopened = validate_success(
        api.transition_dispute(dispute_id, {"action": "REOPEN"}, headers=scenario.landowner_headers)
    )
    assert reopened["status"] == "REOPENED", (
        f"REOPEN takes CURE_PENDING to REOPENED, got {reopened['status']!r}"
    )
    assert reopened["cure_attempts"] == 1, (
        f"reopening consumes no attempt, got {reopened['cure_attempts']}"
    )

    stream = validate_success(api.get_lease_stream(scenario.lease_stream_id, headers=analyst_headers))
    assert stream["servicing_status"] == "WATCHLIST", (
        f"a reopened case leaves the stream on WATCHLIST, got {stream['servicing_status']!r}"
    )

    second_cure = validate_success(
        api.transition_dispute(dispute_id, {"action": "START_CURE"}, headers=servicing_headers)
    )
    assert second_cure["status"] == "CURE_PENDING", (
        f"START_CURE also runs from REOPENED, got {second_cure['status']!r}"
    )
    assert second_cure["cure_attempts"] == 2, (
        f"the repeat pass raises cure_attempts to 2, got {second_cure['cure_attempts']}"
    )
    assert second_cure["cure_deadline"] is not None, "the repeat pass resets the cure_deadline"


def test_fourth_cure_start_is_refused_and_leaves_the_case_parked_in_reopened(
    api, servicing_headers, analyst_headers
):
    """Once three cure attempts have been spent, a fourth START_CURE is refused and the
    case stays in REOPENED with the lease stream still on WATCHLIST.

    PRD 3.8: "Either path requires `cure_attempts` to be strictly below three attempts; a fourth is refused with `ERR_CURE_ATTEMPTS_EXHAUSTED`."
    PRD 3.8: "**`REOPEN`** takes the case `CURE_PENDING → REOPENED` and leaves the stream on `WATCHLIST`, awaiting another attempt."
    PRD 3.8: "A new case opens at `status` `OPEN` with `cure_attempts` at zero and no `cure_deadline`, increments the landowner's `open_dispute_count`, and — when the stream's deal has not yet closed — triggers a recomputation of that deal's settlement holdback, since an unresolved dispute is exactly what the holdback exists to cover."

    Design: Difficulty/non_linear_state_machine/dispute_cure_reopen_cycle_bounded_by_cure_attempt_cap
    """
    scenario = build_dispute_on_closed_stream(
        api, dispute_type="INTERFERENCE", description="Carrier equipment noise at night"
    )
    dispute_id = scenario["dispute"]["id"]
    landowner_headers = scenario.landowner_headers

    for expected_attempts in (1, 2, 3):
        cured = get_success_data(
            api.transition_dispute(dispute_id, {"action": "START_CURE"}, headers=servicing_headers)
        )
        assert cured["cure_attempts"] == expected_attempts, (
            f"cure_attempts must be {expected_attempts} after that pass, got {cured['cure_attempts']}"
        )
        get_success_data(api.transition_dispute(dispute_id, {"action": "REOPEN"}, headers=landowner_headers))

    refused = api.transition_dispute(dispute_id, {"action": "START_CURE"}, headers=make_servicing_agent_headers())
    validate_error(refused, ApiErrorId.ERR_CURE_ATTEMPTS_EXHAUSTED.value)

    dispute = validate_success(api.get_dispute(dispute_id, headers=servicing_headers))
    assert dispute["cure_attempts"] == 3, f"cure_attempts is capped at 3, got {dispute['cure_attempts']}"
    assert dispute["status"] == "REOPENED", (
        f"the refused cure leaves the case in REOPENED, got {dispute['status']!r}"
    )

    stream = validate_success(api.get_lease_stream(scenario.lease_stream_id, headers=analyst_headers))
    assert stream["servicing_status"] == "WATCHLIST", (
        f"the stream stays on WATCHLIST while the dispute is unresolved, got {stream['servicing_status']!r}"
    )

    landowner = validate_success(api.get_landowner(scenario.landowner_id, headers=analyst_headers))
    assert landowner["open_dispute_count"] == 1, (
        f"the one unresolved dispute still counts against the landowner, got {landowner['open_dispute_count']}"
    )
