"""Deal, offer, title, refusal, dispute, pledge and amendment lifecycles.

Each test drives one leg of the buyout pipeline: the states a fresh resource opens in, the
side effects a legitimate verb fires across the deal, the landowner, the stream and the
capital pool, and the refusals a verb earns when it is not declared from the state the
resource is actually sitting in.
"""

from test_helpers import (
    AcquisitionStatus,
    AmendmentStatus,
    ApiErrorId,
    CapitalPosture,
    CapitalState,
    ComplianceState,
    ConsentStatus,
    DealStage,
    DisputeStatus,
    DisputeType,
    EasementStatus,
    OfferStatus,
    OutreachStatus,
    PledgeStatus,
    ROFR_REQUIRED_COMPANY,
    Role,
    RofrNoticeStatus,
    RofrState,
    ServicingStatus,
    TEST_DEFAULTS,
    TEST_USERS,
    TitleReviewStatus,
    assert_deal,
    assert_dispute,
    assert_offer,
    assert_portfolio_ledger_balances,
    assert_title_report,
    build_amendment_on_closed_stream,
    build_dispute_on_closed_stream,
    build_facility_with_pledge,
    closed_deal,
    create_portfolio,
    deal_cleared_to_close,
    deal_in_negotiation,
    deal_with_draft_offer,
    deal_with_ordered_title,
    deal_payload,
    is_iso8601_timestamp,
    make_acquisition_analyst_headers,
    make_lender_headers,
    make_platform_admin_headers,
    make_servicing_agent_headers,
    make_title_officer_headers,
    make_treasury_officer_headers,
    offer_payload,
    read_lease_stream,
    record_findings_payload,
    reverse_amendment_event,
    set_clock,
    stream_with_approved_valuation,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Opening states
# ---------------------------------------------------------------------------


def test_new_deal_opens_in_origination_with_uncommitted_capital(api):
    """Opening a deal against an approved valuation parks it at the front of the pipeline:
    both parallel state fields sit at their opening values and no capital is spoken for yet.

    PRD section 3.5: "A new deal starts at `stage` `ORIGINATION` and `capital_state` `UNCOMMITTED`, increments its portfolio's `active_deal_count`, and takes its initial `rofr_state` from the tower company standing over the stream's site: `PENDING` when that company's `rofr_required` is true, and `NOT_REQUIRED` when it is false."

    PRD section 3.5: "Its `negotiation_rounds` starts at zero, its `easement_status` at `NOT_DRAFTED`, its `agreed_consideration_cents` unset, and every escrow figure at zero."

    Design: Corner/state_machines/initial_state_new_deal_starts_in_origination_and_uncommitted
    """
    priced = stream_with_approved_valuation(api)
    portfolio = create_portfolio(api)

    created = validate_success(
        api.create_deal(
            deal_payload(portfolio["id"], priced.lease_stream_id, priced.valuation_id),
            headers=make_acquisition_analyst_headers(),
        ),
        201,
    )

    assert_deal(created)
    assert created["stage"] == DealStage.ORIGINATION.value
    assert created["capital_state"] == CapitalState.UNCOMMITTED.value
    # The canonical tower company carries rofr_required false, so no refusal is outstanding.
    assert created["rofr_state"] == RofrState.NOT_REQUIRED.value
    assert created["negotiation_rounds"] == 0
    assert created["easement_status"] == EasementStatus.NOT_DRAFTED.value
    assert created.get("agreed_consideration_cents") is None
    assert created["escrow_funded_cents"] == 0
    assert created["escrow_disbursed_cents"] == 0
    assert created["escrow_holdback_cents"] == 0
    assert created["escrow_refunded_cents"] == 0

    pool = validate_success(api.get_portfolio(portfolio["id"], headers=make_platform_admin_headers()))
    assert pool["committed_capital_cents"] == 0
    assert pool["deployed_capital_cents"] == 0
    assert pool["available_capital_cents"] == TEST_DEFAULTS["PORTFOLIO_CAPITAL_CENTS"]
    assert pool["active_deal_count"] == 1
    assert pool["capital_posture"] == CapitalPosture.OPEN.value
    assert_portfolio_ledger_balances(pool)

    stream = read_lease_stream(api, priced.lease_stream_id)
    assert stream["acquisition_status"] == AcquisitionStatus.PROSPECT.value


def test_new_dispute_opens_without_moving_the_stream_off_performing(api):
    """A landowner raising a dispute on an acquired stream gets a case in its opening state,
    and the stream's servicing condition is untouched because no cure has been started.

    PRD section 3.8: "A new case opens at `status` `OPEN` with `cure_attempts` at zero and no `cure_deadline`, increments the landowner's `open_dispute_count`, and — when the stream's deal has not yet closed — triggers a recomputation of that deal's settlement holdback, since an unresolved dispute is exactly what the holdback exists to cover."

    PRD section 3.8: "The system records the declared role of whoever opened it in `raised_by_role`."

    PRD section 3.8: "The first-pass transition out of `OPEN` also degrades the stream's servicing condition, `PERFORMING → WATCHLIST`, which in turn re-haircuts every pledge of that stream and recomputes the borrowing base of the facility holding them; a stream already on `WATCHLIST` stays there."

    Design: Corner/state_machines/initial_state_new_dispute_starts_open_without_touching_servicing_status
    """
    scenario = closed_deal(api)

    dispute = validate_success(
        api.open_dispute(
            scenario.lease_stream_id,
            {"dispute_type": DisputeType.ACCESS.value, "description": "Gate combination changed without notice"},
            headers=scenario.landowner_headers,
        ),
        201,
    )

    assert_dispute(dispute)
    assert dispute["status"] == DisputeStatus.OPEN.value
    assert dispute["cure_attempts"] == 0
    assert dispute.get("cure_deadline") is None
    assert dispute.get("resolved_at") is None
    assert dispute["raised_by_role"] == Role.LANDOWNER.value

    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert stream["servicing_status"] == ServicingStatus.PERFORMING.value

    landowner = validate_success(
        api.get_landowner(scenario.landowner_id, headers=make_acquisition_analyst_headers())
    )
    assert landowner["open_dispute_count"] == 1


# ---------------------------------------------------------------------------
# Legitimate transitions and their side effects
# ---------------------------------------------------------------------------


def test_withdrawn_offer_frees_the_deal_for_a_replacement_offer(api):
    """Withdrawing a live offer retires it without rewinding the deal, so a replacement offer
    may be sent immediately and consumes the next negotiation round.

    PRD section 3.5: "**`WITHDRAW`** is the analyst's mirror image, available from either live state with no preconditions at all — `SENT → WITHDRAWN` and `COUNTERED → WITHDRAWN` — and stamps `decided_at`."

    PRD section 3.5: "It requires the deal's `stage` to be `OUTREACH` or `NEGOTIATION`, requires the landowner not to be at `DO_NOT_CONTACT`, requires the offer's `amount_cents` to be less than or equal to the pinned valuation's `max_bid_cents` — a violation is `ERR_OFFER_EXCEEDS_GUARDRAIL` — and requires that no other offer on the deal is currently sitting in `SENT` or `COUNTERED`, since only one proposal may be live at a time and a second is refused with `ERR_OFFER_ALREADY_OUTSTANDING`."

    PRD section 3.5: "Sending stamps `sent_at` from the current instant, increments the deal's `negotiation_rounds` and then copies the new count into the offer's `round_number`, moves the deal `OUTREACH → NEGOTIATION`, and lifts the landowner's `outreach_status` from `NEW` to `CONTACTED` if it was still `NEW`."

    Design: Corner/state_machines/valid_transition_offer_withdraw_frees_the_deal_for_a_replacement_offer
    """
    scenario = deal_in_negotiation(api)
    first_offer_id = scenario.offer_id

    withdrawn = validate_success(
        api.transition_offer(first_offer_id, {"action": "WITHDRAW"}, headers=make_acquisition_analyst_headers())
    )
    assert_offer(withdrawn)
    assert withdrawn["status"] == OfferStatus.WITHDRAWN.value
    assert withdrawn["round_number"] == 1
    assert withdrawn.get("decided_at") is not None
    assert is_iso8601_timestamp(withdrawn["decided_at"])

    replacement = validate_success(
        api.create_offer(
            scenario.deal_id,
            offer_payload(amount_cents=39_000_000),
            headers=make_acquisition_analyst_headers(),
        ),
        201,
    )
    sent = validate_success(
        api.transition_offer(replacement["id"], {"action": "SEND"}, headers=make_acquisition_analyst_headers())
    )
    assert sent["status"] == OfferStatus.SENT.value
    assert sent["round_number"] == 2
    assert sent["amount_cents"] == 39_000_000

    deal = validate_success(api.get_deal(scenario.deal_id, headers=make_acquisition_analyst_headers()))
    assert deal["negotiation_rounds"] == 2
    assert deal["stage"] == DealStage.NEGOTIATION.value

    landowner = validate_success(
        api.get_landowner(scenario.landowner_id, headers=make_acquisition_analyst_headers())
    )
    assert landowner["outreach_status"] == OutreachStatus.CONTACTED.value


def test_mortgagee_consent_request_then_grant_clears_the_deal(api):
    """Findings that disclose a mortgage open the consent track, the request stamps a
    twenty-one day window off the logical clock, and the lender's grant lifts the deal to
    clearance.

    PRD section 3.6: "From `ORDERED`, findings with an `exception_count` of exactly zero take the report `ORDERED → CLEARED` instead, setting `consent_status` to `NOT_REQUIRED` when no mortgage is present and to `PENDING_REQUEST` when one is, and immediately re-evaluating the deal's clearance join."

    PRD section 3.6: "Requesting stamps `consent_requested_at` from the current instant and sets `consent_expires_at` to twenty-one whole days after that instant, exclusive of the boundary itself."

    PRD section 3.6: "A grant takes the consent `REQUESTED → GRANTED`, stamps `consent_decided_by_user_id`, and re-evaluates the deal's clearance join."

    PRD section 3.7: "On success the deal moves `DILIGENCE → CLEAR_TO_CLOSE` and its `easement_status` moves `NOT_DRAFTED → DRAFTED`."

    Design: Corner/state_machines/valid_transition_mortgage_consent_requested_then_granted_clears_the_deal
    """
    scenario = deal_with_ordered_title(api)

    after_findings = validate_success(
        api.transition_title_report(
            scenario.title_report_id,
            record_findings_payload(
                exception_count=0, mortgage_present=True, lender_name="Hudson Valley Savings"
            ),
            headers=make_title_officer_headers(),
        )
    )
    assert_title_report(after_findings)
    assert after_findings["review_status"] == TitleReviewStatus.CLEARED.value
    assert after_findings["consent_status"] == ConsentStatus.PENDING_REQUEST.value
    assert after_findings["mortgage_present"] is True
    assert after_findings["lender_name"] == "Hudson Valley Savings"

    requested = validate_success(
        api.transition_title_report(
            scenario.title_report_id, {"action": "REQUEST_CONSENT"}, headers=make_title_officer_headers()
        )
    )
    assert requested["consent_status"] == ConsentStatus.REQUESTED.value
    # The clock opens at 2026-08-01T00:00:00Z, so the window runs to 2026-08-22.
    assert requested["consent_requested_at"][:10] == "2026-08-01"
    assert requested["consent_expires_at"][:10] == "2026-08-22"

    granted = validate_success(
        api.decide_consent(scenario.title_report_id, {"decision": "GRANT"}, headers=make_lender_headers())
    )
    assert granted["consent_status"] == ConsentStatus.GRANTED.value
    assert granted["consent_decided_by_user_id"] == TEST_USERS[Role.LENDER.value]

    deal = validate_success(api.get_deal(scenario.deal_id, headers=make_acquisition_analyst_headers()))
    assert deal["stage"] == DealStage.CLEAR_TO_CLOSE.value
    assert deal["easement_status"] == EasementStatus.DRAFTED.value
    assert deal["capital_state"] == CapitalState.RESERVED.value


def test_sending_an_offer_advances_the_deal_and_the_landowner(api):
    """One SEND fires every side effect the transition declares: the offer is stamped and
    numbered, the deal moves into negotiation, and the landowner is marked as contacted.

    PRD section 3.5: "Sending stamps `sent_at` from the current instant, increments the deal's `negotiation_rounds` and then copies the new count into the offer's `round_number`, moves the deal `OUTREACH → NEGOTIATION`, and lifts the landowner's `outreach_status` from `NEW` to `CONTACTED` if it was still `NEW`."

    PRD section 3.5: "The transition pushes the stream from `PROSPECT` to `UNDER_OFFER`."

    Design: Corner/state_machines/side_effect_execution_offer_send_advances_deal_and_landowner_together
    """
    scenario = deal_with_draft_offer(api)
    assert scenario["offer"]["status"] == OfferStatus.DRAFT.value

    sent = validate_success(
        api.transition_offer(scenario.offer_id, {"action": "SEND"}, headers=make_acquisition_analyst_headers())
    )
    assert_offer(sent)
    assert sent["status"] == OfferStatus.SENT.value
    assert sent.get("sent_at") is not None
    assert is_iso8601_timestamp(sent["sent_at"])
    assert sent["round_number"] == 1

    deal = validate_success(api.get_deal(scenario.deal_id, headers=make_acquisition_analyst_headers()))
    assert deal["negotiation_rounds"] == 1
    assert deal["stage"] == DealStage.NEGOTIATION.value
    assert deal["capital_state"] == CapitalState.UNCOMMITTED.value

    landowner = validate_success(
        api.get_landowner(scenario.landowner_id, headers=make_acquisition_analyst_headers())
    )
    assert landowner["outreach_status"] == OutreachStatus.CONTACTED.value

    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert stream["acquisition_status"] == AcquisitionStatus.UNDER_OFFER.value


def test_title_failure_kills_the_deal_and_releases_reserved_capital(api):
    """Failing the title search on a reserved deal is a single request with a four-part
    cascade: the report fails, the deal dies, the stream is lost, and the pool gets its
    money back.

    PRD section 3.6: "A `TitleOfficer` may also give up on the search entirely: **`FAIL`** takes the report `EXCEPTIONS_FOUND → FAILED` with no precondition, and that failure kills the deal — the deal's stage moves `DILIGENCE → DEAD`, its capital moves `RESERVED → RELEASED`, the stream reverts to `LOST`, and the portfolio's capital ledger is recomputed."

    PRD section 2.10: "A portfolio's `active_deal_count` specifically counts the deals on that portfolio whose `stage` is none of `CLOSED`, `DEAD`, `ROFR_LOST`, and `TERMINATED`."

    Design: Corner/state_machines/side_effect_execution_title_failure_kills_the_deal_and_releases_capital
    """
    scenario = deal_with_ordered_title(api)
    with_exceptions = validate_success(
        api.transition_title_report(
            scenario.title_report_id,
            record_findings_payload(exception_count=2, mortgage_present=False),
            headers=make_title_officer_headers(),
        )
    )
    assert with_exceptions["review_status"] == TitleReviewStatus.EXCEPTIONS_FOUND.value
    assert with_exceptions["open_exception_count"] == 2

    failed = validate_success(
        api.transition_title_report(
            scenario.title_report_id, {"action": "FAIL"}, headers=make_title_officer_headers()
        )
    )
    assert failed["review_status"] == TitleReviewStatus.FAILED.value
    assert failed["exception_count"] == 2
    assert failed["open_exception_count"] == 2

    deal = validate_success(api.get_deal(scenario.deal_id, headers=make_acquisition_analyst_headers()))
    assert deal["stage"] == DealStage.DEAD.value
    assert deal["capital_state"] == CapitalState.RELEASED.value
    assert deal["easement_status"] == EasementStatus.NOT_DRAFTED.value

    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert stream["acquisition_status"] == AcquisitionStatus.LOST.value

    pool = validate_success(api.get_portfolio(scenario.portfolio_id, headers=make_platform_admin_headers()))
    assert pool["committed_capital_cents"] == 0
    assert pool["deployed_capital_cents"] == 0
    assert pool["available_capital_cents"] == TEST_DEFAULTS["PORTFOLIO_CAPITAL_CENTS"]
    assert pool["utilization_bps"] == 0
    assert pool["capital_posture"] == CapitalPosture.OPEN.value
    assert pool["active_deal_count"] == 0


# ---------------------------------------------------------------------------
# Verbs that are not declared from the current state
# ---------------------------------------------------------------------------


def test_landowner_cannot_accept_an_offer_that_was_never_sent(api):
    """The deal's own landowner tries to accept a draft offer. Acceptance is declared only
    from SENT, so the refusal is a state conflict and no capital is reserved.

    PRD section 3.5: "A verb sent by the wrong role is refused with `ERR_ACTION_ROLE_MISMATCH`, and a verb that is not declared from the offer's current `status` is refused with `ERR_INVALID_OFFER_STATE`."

    PRD section 3.5: "**`ACCEPT`** takes the offer `SENT → ACCEPTED` and is the pivot of the whole pipeline."

    Design: Corner/state_machines/invalid_transitions_accept_from_draft_offer_rejected
    """
    scenario = deal_with_draft_offer(api)

    refusal = api.transition_offer(
        scenario.offer_id, {"action": "ACCEPT"}, headers=scenario.landowner_headers
    )
    validate_error(refusal, ApiErrorId.ERR_INVALID_OFFER_STATE.value)

    offers, meta = validate_paginated(
        api.list_offers(scenario.deal_id, headers=make_acquisition_analyst_headers())
    )
    assert meta["total_count"] == 1
    offer = offers[0]
    assert offer["status"] == OfferStatus.DRAFT.value
    assert offer.get("decided_at") is None

    deal = validate_success(api.get_deal(scenario.deal_id, headers=make_acquisition_analyst_headers()))
    assert deal["stage"] == DealStage.OUTREACH.value
    assert deal["capital_state"] == CapitalState.UNCOMMITTED.value

    pool = validate_success(api.get_portfolio(scenario.portfolio_id, headers=make_platform_admin_headers()))
    assert pool["committed_capital_cents"] == 0


def test_curing_an_exception_on_a_freshly_ordered_report_is_rejected(api):
    """A title officer tries to cure an exception on a report that has not yet reported any
    findings, so there is nothing to decrement and the verb is refused.

    PRD section 3.6: "A verb that is not declared from the report's current `review_status` or `consent_status` is refused with `ERR_INVALID_TITLE_STATE`."

    PRD section 3.6: "**`CURE_EXCEPTION`** decrements the open count."

    Design: Corner/state_machines/invalid_transitions_cure_exception_from_ordered_title_report_rejected
    """
    scenario = deal_with_ordered_title(api)
    assert scenario["title_report"]["review_status"] == TitleReviewStatus.ORDERED.value

    refusal = api.transition_title_report(
        scenario.title_report_id, {"action": "CURE_EXCEPTION"}, headers=make_title_officer_headers()
    )
    validate_error(refusal, ApiErrorId.ERR_INVALID_TITLE_STATE.value)

    report = validate_success(
        api.get_title_report(scenario.title_report_id, headers=make_title_officer_headers())
    )
    assert report["review_status"] == TitleReviewStatus.ORDERED.value
    assert report["open_exception_count"] == 0
    assert report["consent_status"] == ConsentStatus.NOT_REQUIRED.value

    deal = validate_success(api.get_deal(scenario.deal_id, headers=make_acquisition_analyst_headers()))
    assert deal["stage"] == DealStage.DILIGENCE.value


def test_confirming_a_cure_that_was_never_started_is_rejected(api):
    """The landowner tries to confirm a cure on a dispute the servicing agent never took into
    cure, so the case is not silently resolved.

    PRD section 2.8: "**Dispute state admits the action** — the requested dispute verb is declared from the dispute's current `status`; otherwise `ERR_INVALID_DISPUTE_STATE` (409)."

    PRD section 3.8: "**`CONFIRM_CURE`** takes the case `CURE_PENDING → RESOLVED`, stamps `resolved_at`, recomputes `open_dispute_count`, and — if no other dispute on the stream remains in `OPEN`, `CURE_PENDING`, or `REOPENED` — restores the stream `WATCHLIST → PERFORMING`, which recomputes its pledges at full basis."

    Design: Corner/state_machines/invalid_transitions_confirm_cure_from_open_dispute_rejected
    """
    scenario = build_dispute_on_closed_stream(
        api,
        dispute_type=DisputeType.INTERFERENCE.value,
        description="Night-time equipment noise",
    )
    dispute_id = scenario["dispute"]["id"]
    assert scenario["dispute"]["status"] == DisputeStatus.OPEN.value

    refusal = api.transition_dispute(
        dispute_id, {"action": "CONFIRM_CURE"}, headers=scenario.landowner_headers
    )
    validate_error(refusal, ApiErrorId.ERR_INVALID_DISPUTE_STATE.value)

    dispute = validate_success(api.get_dispute(dispute_id, headers=make_servicing_agent_headers()))
    assert dispute["status"] == DisputeStatus.OPEN.value
    assert dispute["cure_attempts"] == 0
    assert dispute.get("resolved_at") is None

    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert stream["servicing_status"] == ServicingStatus.PERFORMING.value

    landowner = validate_success(
        api.get_landowner(scenario.landowner_id, headers=make_acquisition_analyst_headers())
    )
    assert landowner["open_dispute_count"] == 1


def test_releasing_an_already_released_pledge_is_rejected(api):
    """A second release of the same collateral pledge is refused, so the facility's
    aggregates are not decremented twice.

    PRD section 3.9: "`RELEASED` is terminal, and any further verb against a released pledge is refused with `ERR_INVALID_PLEDGE_STATE`."

    PRD section 3.9: "A release sets `eligible_value_cents` to zero, recomputes the facility's `pledged_eligible_total_cents` and `borrowing_base_cents`, and decrements `pledged_stream_count`."

    Design: Corner/state_machines/invalid_transitions_second_pledge_release_rejected
    """
    scenario = build_facility_with_pledge(api)
    pledge_id = scenario["pledge"]["id"]

    released = validate_success(
        api.release_collateral_pledge(pledge_id, headers=make_treasury_officer_headers())
    )
    assert released["status"] == PledgeStatus.RELEASED.value
    assert released["eligible_value_cents"] == 0

    refusal = api.release_collateral_pledge(pledge_id, headers=make_treasury_officer_headers())
    validate_error(refusal, ApiErrorId.ERR_INVALID_PLEDGE_STATE.value)

    pledge = validate_success(api.get_collateral_pledge(pledge_id, headers=make_treasury_officer_headers()))
    assert pledge["status"] == PledgeStatus.RELEASED.value
    assert pledge["eligible_value_cents"] == 0

    facility = validate_success(
        api.get_financing_facility(scenario.facility_id, headers=make_treasury_officer_headers())
    )
    assert facility["pledged_stream_count"] == 0
    assert facility["pledged_eligible_total_cents"] == 0
    assert facility["borrowing_base_cents"] == 0
    assert facility["compliance_state"] == ComplianceState.COMPLIANT.value


def test_reversing_an_already_reversed_amendment_event_is_rejected(api):
    """Reversing an amendment event twice is refused, so the stream's cumulative revenue
    share is debited once rather than driven negative.

    PRD section 3.8: "`REVERSED` is terminal, and a second reversal attempt is refused with `ERR_INVALID_AMENDMENT_STATE`."

    PRD section 3.8: "A `ServicingAgent` reverses it — `RECORDED → REVERSED` — supplying a `reversal_reason`, which is mandatory; reversal decreases the stream's `cumulative_revenue_share_landowner_cents` by that event's `landowner_share_cents` and its `cumulative_revenue_share_acquirer_cents` by that event's `acquirer_share_cents`."

    Design: Corner/state_machines/invalid_transitions_second_amendment_reversal_rejected
    """
    scenario = build_amendment_on_closed_stream(api, gross_amount_cents=1_000_002)
    event_id = scenario["amendment_event"]["id"]
    # 1000002 cents of colocation upside at the deal's 2500 bps share rounds half up to 250001.
    assert scenario["amendment_event"]["landowner_share_cents"] == 250_001

    reversed_event = reverse_amendment_event(api, event_id, "Colocation cancelled by the carrier")
    assert reversed_event["status"] == AmendmentStatus.REVERSED.value

    refusal = api.reverse_amendment_event(
        event_id, {"reversal_reason": "Duplicate reversal attempt"}, headers=make_servicing_agent_headers()
    )
    validate_error(refusal, ApiErrorId.ERR_INVALID_AMENDMENT_STATE.value)

    events, meta = validate_paginated(
        api.list_amendment_events(scenario.lease_stream_id, headers=make_servicing_agent_headers())
    )
    assert meta["total_count"] == 1
    stored = events[0]
    assert stored["status"] == AmendmentStatus.REVERSED.value
    assert stored["landowner_share_cents"] == 250_001
    assert stored["reversal_reason"] == "Colocation cancelled by the carrier"

    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert stream["cumulative_revenue_share_landowner_cents"] == 0
    assert stream["cumulative_revenue_share_acquirer_cents"] == 0


def test_refusal_response_after_the_window_lapses_is_rejected(api):
    """At exactly the end of a thirty-day refusal window the notice has already lapsed, so the
    tower company's waiver arrives too late — yet the lapse itself satisfies the clearance
    join and the deal is cleared to close.

    PRD section 3.6: "Silence works in our favour: once the current instant reaches `window_end` the notice goes `SERVED → EXPIRED` lazily on the next read or transition attempt, the deal's `rofr_state` becomes `WAIVED_BY_LAPSE`, and the clearance join is re-evaluated."

    PRD section 3.6: "A response outside those bounds, or against a notice that is no longer `SERVED`, is refused with `ERR_INVALID_ROFR_STATE`."

    PRD section 2.11: "A response landing exactly at `window_end` is outside the window."

    Design: Corner/state_machines/invalid_transitions_rofr_response_after_window_lapse_rejected
    """
    scenario = deal_cleared_to_close(api, tower_company=ROFR_REQUIRED_COMPANY, serve_rofr=True)
    notice_id = scenario["rofr_notice"]["id"]
    assert scenario["rofr_notice"]["status"] == RofrNoticeStatus.SERVED.value
    assert scenario["rofr_notice"]["window_days_snapshot"] == TEST_DEFAULTS["ROFR_WINDOW_DAYS"]
    assert scenario["rofr_notice"]["window_end"][:10] == "2026-08-31"

    set_clock(api, "2026-08-31T00:00:00Z")

    refusal = api.respond_to_rofr_notice(
        notice_id, {"decision": "WAIVE"}, headers=scenario.tower_agent_headers
    )
    validate_error(refusal, ApiErrorId.ERR_INVALID_ROFR_STATE.value)

    notices, meta = validate_paginated(
        api.list_rofr_notices(scenario.deal_id, headers=make_acquisition_analyst_headers())
    )
    assert meta["total_count"] == 1
    notice = notices[0]
    assert notice["status"] == RofrNoticeStatus.EXPIRED.value
    assert notice["window_end"][:10] == "2026-08-31"
    assert notice.get("responded_at") is None
    assert notice.get("responded_by_user_id") is None

    deal = validate_success(api.get_deal(scenario.deal_id, headers=make_acquisition_analyst_headers()))
    assert deal["rofr_state"] == RofrState.WAIVED_BY_LAPSE.value
    assert deal["stage"] == DealStage.CLEAR_TO_CLOSE.value
    assert deal["easement_status"] == EasementStatus.DRAFTED.value
