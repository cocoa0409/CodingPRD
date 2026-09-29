"""Guards on the transitions a lease-buyout deal is allowed to make.

A closed purchase cannot be unwound, an accepted offer cannot be pulled back, outreach
cannot be started twice, a price cannot be blessed on a tower with no carriers on it, the
walk into clearance waits for both the title search and the tower company's refusal right,
and title exceptions come off one cure at a time until the last one clears.
"""

from decimal import Decimal

from test_helpers import (
    ApiErrorId,
    THRESHOLDS,
    TEST_DEFAULTS,
    ROFR_REQUIRED_COMPANY,
    PM_APPROVER_USER_ID,
    PM_CLOSER_USER_ID,
    assert_deal,
    assert_title_report,
    assert_utilization_and_posture,
    assert_valuation,
    bps_of,
    build_chain,
    closed_deal,
    deal_escrowed,
    deal_in_diligence,
    deal_in_negotiation,
    deal_in_origination,
    deal_in_outreach,
    make_acquisition_analyst_headers,
    make_platform_admin_headers,
    make_portfolio_manager_headers,
    make_title_officer_headers,
    make_treasury_officer_headers,
    read_lease_stream,
    round_half_up,
    stream_with_draft_valuation,
    terminate_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

GROSS_CENTS = TEST_DEFAULTS["OFFER_AMOUNT_CENTS"]
BROKER_FEE_CENTS = bps_of(GROSS_CENTS, THRESHOLDS["BROKER_FEE_BPS_HIGH"])
TOTAL_COMMITMENT_CENTS = GROSS_CENTS + BROKER_FEE_CENTS
POOL_CENTS = TEST_DEFAULTS["PORTFOLIO_CAPITAL_CENTS"]
# Every stamped instant derives from the logical clock, which starts at 2026-08-01T00:00:00Z.
CLOCK_START_PREFIX = THRESHOLDS["CLOCK_DEFAULT_UTC"].rstrip("Z")


def _read_deal(api, deal_id):
    return validate_success(api.get_deal(deal_id, headers=make_portfolio_manager_headers()))


def _read_portfolio(api, portfolio_id):
    return validate_success(api.get_portfolio(portfolio_id, headers=make_platform_admin_headers()))


def _read_valuation(api, lease_stream_id, valuation_id):
    rows, _meta = validate_paginated(
        api.list_valuations(lease_stream_id, headers=make_acquisition_analyst_headers())
    )
    matches = [row for row in rows if row["id"] == valuation_id]
    assert matches, f"valuation {valuation_id} is absent from the stream's valuation list"
    return matches[0]


# ===========================================================================
# A closed purchase is final: termination is not available from CLOSED
# ===========================================================================


def test_terminating_a_closed_deal_is_refused_as_an_invalid_stage(api):
    """A deal that has already closed and disbursed cannot be terminated afterwards.

    PRD section 3.7: **Termination** is the `PortfolioManager`'s escape hatch, taking a `reason`, and it is available from either `DILIGENCE → TERMINATED` or `CLEAR_TO_CLOSE → TERMINATED` with no further precondition.
    PRD section 2.8: **Deal stage admits the action** — the deal's `stage` permits the operation; otherwise `ERR_INVALID_DEAL_STAGE` (409).

    Design: Corner/state_machines/terminal_state_lockdown_closed_deal_cannot_be_terminated
    """
    scenario = closed_deal(api)
    assert scenario["deal"]["stage"] == "CLOSED"

    response = api.terminate_deal(
        scenario.deal_id,
        terminate_payload(reason="Post-closing seller remorse"),
        headers=make_portfolio_manager_headers(PM_CLOSER_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_DEAL_STAGE.value)


def test_closed_deal_keeps_its_disbursement_after_a_refused_termination(api):
    """The refused termination claws nothing back: the money stays deployed and the ground stays ours.

    PRD section 3.7: The deal moves `CLEAR_TO_CLOSE → CLOSED` and records `closed_by_user_id`.
    PRD section 3.1: `deployed_capital_cents` is the sum of `total_commitment_cents` across deals whose `capital_state` is `DISBURSED`.
    PRD section 3.2: When a deal on the stream closes, `UNDER_OFFER → ACQUIRED`, and that same closing sets `rent_redirection_status` to `SENT` and `servicing_status` to `PERFORMING`.

    Design: Corner/state_machines/terminal_state_lockdown_closed_deal_cannot_be_terminated
    """
    scenario = closed_deal(api)

    response = api.terminate_deal(
        scenario.deal_id,
        terminate_payload(reason="Post-closing seller remorse"),
        headers=make_portfolio_manager_headers(PM_CLOSER_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_DEAL_STAGE.value)

    deal = _read_deal(api, scenario.deal_id)
    assert_deal(deal)
    assert deal["stage"] == "CLOSED"
    assert deal["capital_state"] == "DISBURSED"
    assert deal["escrow_refunded_cents"] == 0
    assert deal["recording_ref"] == TEST_DEFAULTS["RECORDING_REF"]
    assert deal["total_commitment_cents"] == TOTAL_COMMITMENT_CENTS

    portfolio = _read_portfolio(api, scenario.portfolio_id)
    assert portfolio["deployed_capital_cents"] == TOTAL_COMMITMENT_CENTS
    assert portfolio["committed_capital_cents"] == 0
    assert portfolio["available_capital_cents"] == POOL_CENTS - TOTAL_COMMITMENT_CENTS
    assert_utilization_and_posture(portfolio)

    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert stream["acquisition_status"] == "ACQUIRED"
    assert stream["servicing_status"] == "PERFORMING"


def test_terminating_a_cleared_deal_refunds_the_funded_escrow(api):
    """One stage earlier the same verb works: a cleared, escrowed deal terminates and the escrow comes back.

    PRD section 3.7: **Termination** is the `PortfolioManager`'s escape hatch, taking a `reason`, and it is available from either `DILIGENCE → TERMINATED` or `CLEAR_TO_CLOSE → TERMINATED` with no further precondition.
    PRD section 3.7: Terminating from `DILIGENCE` releases a merely reserved commitment; terminating from `CLEAR_TO_CLOSE`, where escrow may already be funded, additionally sets `escrow_refunded_cents` equal to `escrow_funded_cents` so the money is visibly returned.
    PRD section 3.2: When a deal on the stream is terminated outright, or dies because negotiation rounds ran out, the stream is released back to the funnel: `UNDER_OFFER → PROSPECT`.

    Design: Corner/state_machines/terminal_state_lockdown_closed_deal_cannot_be_terminated
    """
    scenario = deal_escrowed(api)
    assert scenario["deal"]["stage"] == "CLEAR_TO_CLOSE"
    assert scenario["deal"]["capital_state"] == "ESCROWED"
    assert scenario["deal"]["escrow_funded_cents"] == TOTAL_COMMITMENT_CENTS

    deal = validate_success(
        api.terminate_deal(
            scenario.deal_id,
            terminate_payload(reason="Landowner withdrew from talks"),
            headers=make_portfolio_manager_headers(PM_CLOSER_USER_ID),
        )
    )
    assert deal["stage"] == "TERMINATED"
    assert deal["capital_state"] == "RELEASED"
    assert deal["escrow_refunded_cents"] == deal["escrow_funded_cents"] == TOTAL_COMMITMENT_CENTS

    portfolio = _read_portfolio(api, scenario.portfolio_id)
    assert portfolio["committed_capital_cents"] == 0
    assert portfolio["deployed_capital_cents"] == 0
    assert portfolio["available_capital_cents"] == POOL_CENTS

    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert stream["acquisition_status"] == "PROSPECT"


# ===========================================================================
# An accepted offer is final: WITHDRAW cannot unwind the acceptance
# ===========================================================================


def test_withdrawing_an_accepted_offer_is_refused_as_an_invalid_offer_state(api):
    """Once the landowner has accepted, the analyst can no longer withdraw the offer.

    PRD section 3.5: **`WITHDRAW`** is the analyst's mirror image, available from either live state with no preconditions at all — `SENT → WITHDRAWN` and `COUNTERED → WITHDRAWN` — and stamps `decided_at`.
    PRD section 2.8: **Offer state admits the action** — the requested offer verb is declared from the offer's current `status`; otherwise `ERR_INVALID_OFFER_STATE` (409).

    Design: Corner/state_machines/terminal_state_lockdown_accepted_offer_cannot_be_withdrawn
    """
    scenario = deal_in_diligence(api)
    assert scenario["offer"]["status"] == "ACCEPTED"

    response = api.transition_offer(
        scenario.offer_id, {"action": "WITHDRAW"}, headers=make_acquisition_analyst_headers()
    )
    validate_error(response, ApiErrorId.ERR_INVALID_OFFER_STATE.value)


def test_accepted_offer_and_its_capital_reservation_survive_a_refused_withdrawal(api):
    """The refused withdrawal changes nothing: the offer stays accepted and the commitment stays reserved.

    PRD section 3.5: A verb sent by the wrong role is refused with `ERR_ACTION_ROLE_MISMATCH`, and a verb that is not declared from the offer's current `status` is refused with `ERR_INVALID_OFFER_STATE`.
    PRD section 3.5: On success the offer stamps `decided_at` and `decided_by_user_id`, the deal's `agreed_consideration_cents` is set to the accepted `amount_cents`, the settlement statement described in §3.7 is computed, the deal's capital state moves `UNCOMMITTED → RESERVED`, the deal's stage moves `NEGOTIATION → DILIGENCE`, the landowner's `outreach_status` moves to `UNDER_CONTRACT`, the deal's `rofr_state` is confirmed as `PENDING` when the tower company's `rofr_required` is true and `NOT_REQUIRED` otherwise, and the portfolio's `committed_capital_cents`, `available_capital_cents`, `utilization_bps`, and `capital_posture` are all recomputed.
    PRD section 3.1: `committed_capital_cents` is the sum of `total_commitment_cents` across deals whose `capital_state` is `RESERVED` or `ESCROWED`.
    PRD section 2.6: The clock's value, referred to throughout this document as the current instant, starts at `2026-08-01T00:00:00Z` and is repositioned only by a `PlatformAdmin` supplying a `current_utc` instant to the administrative clock capability, which echoes back the resulting `current_utc`.

    Design: Corner/state_machines/terminal_state_lockdown_accepted_offer_cannot_be_withdrawn
    """
    scenario = deal_in_diligence(api)

    response = api.transition_offer(
        scenario.offer_id, {"action": "WITHDRAW"}, headers=make_acquisition_analyst_headers()
    )
    validate_error(response, ApiErrorId.ERR_INVALID_OFFER_STATE.value)

    offers, meta = validate_paginated(
        api.list_offers(scenario.deal_id, headers=make_acquisition_analyst_headers())
    )
    assert meta["total_count"] == 1
    assert offers[0]["status"] == "ACCEPTED"
    assert offers[0]["decided_at"].startswith(CLOCK_START_PREFIX)
    assert offers[0]["amount_cents"] == GROSS_CENTS

    deal = _read_deal(api, scenario.deal_id)
    assert deal["stage"] == "DILIGENCE"
    assert deal["capital_state"] == "RESERVED"
    assert deal["agreed_consideration_cents"] == GROSS_CENTS

    portfolio = _read_portfolio(api, scenario.portfolio_id)
    assert portfolio["committed_capital_cents"] == TOTAL_COMMITMENT_CENTS
    assert portfolio["deployed_capital_cents"] == 0
    expected_utilization = round_half_up(
        Decimal(TOTAL_COMMITMENT_CENTS) * Decimal(10000) / Decimal(POOL_CENTS)
    )
    assert portfolio["utilization_bps"] == expected_utilization
    assert_utilization_and_posture(portfolio)


def test_withdrawing_a_live_sent_offer_succeeds(api):
    """While the offer is still live rather than accepted, the analyst may pull it without any precondition.

    PRD section 3.5: **`WITHDRAW`** is the analyst's mirror image, available from either live state with no preconditions at all — `SENT → WITHDRAWN` and `COUNTERED → WITHDRAWN` — and stamps `decided_at`.
    PRD section 3.5: Sending stamps `sent_at` from the current instant, increments the deal's `negotiation_rounds` and then copies the new count into the offer's `round_number`, moves the deal `OUTREACH → NEGOTIATION`, and lifts the landowner's `outreach_status` from `NEW` to `CONTACTED` if it was still `NEW`.
    PRD section 3.7: It starts `UNCOMMITTED`.

    Design: Corner/state_machines/terminal_state_lockdown_accepted_offer_cannot_be_withdrawn
    """
    scenario = deal_in_negotiation(api)
    assert scenario["offer"]["status"] == "SENT"

    offer = validate_success(
        api.transition_offer(
            scenario.offer_id, {"action": "WITHDRAW"}, headers=make_acquisition_analyst_headers()
        )
    )
    assert offer["status"] == "WITHDRAWN"
    assert offer["decided_at"].startswith(CLOCK_START_PREFIX)

    deal = _read_deal(api, scenario.deal_id)
    assert deal["stage"] == "NEGOTIATION"
    assert deal["capital_state"] == "UNCOMMITTED"


# ===========================================================================
# Outreach is a one-shot transition out of ORIGINATION
# ===========================================================================


def test_replaying_the_outreach_request_is_refused_as_an_invalid_stage(api):
    """Asking for outreach a second time on a deal already out on outreach is refused, not repeated.

    PRD section 3.5: Starting outreach moves the deal `ORIGINATION → OUTREACH`, and is permitted only when the pinned valuation's `status` is `APPROVED` and the landowner is not at `DO_NOT_CONTACT`.
    PRD section 2.8: **Deal stage admits the action** — the deal's `stage` permits the operation; otherwise `ERR_INVALID_DEAL_STAGE` (409).

    Design: Corner/state_machines/idempotency_second_outreach_request_on_the_same_deal_rejected
    """
    scenario = deal_in_outreach(api)
    assert scenario["deal"]["stage"] == "OUTREACH"

    response = api.start_outreach(scenario.deal_id, headers=make_acquisition_analyst_headers())
    validate_error(response, ApiErrorId.ERR_INVALID_DEAL_STAGE.value)


def test_refused_outreach_replay_leaves_the_stream_and_landowner_untouched(api):
    """The rejected replay does not re-notify anybody: no offer exists and the landowner is still uncontacted.

    PRD section 3.5: Sending stamps `sent_at` from the current instant, increments the deal's `negotiation_rounds` and then copies the new count into the offer's `round_number`, moves the deal `OUTREACH → NEGOTIATION`, and lifts the landowner's `outreach_status` from `NEW` to `CONTACTED` if it was still `NEW`.
    PRD section 3.2: Its `outreach_status` is initialized to `NEW` and thereafter tracks the progression of offers and deals through `CONTACTED`, `NEGOTIATING`, `UNDER_CONTRACT`, and `CLOSED`.
    PRD section 3.5: The transition pushes the stream from `PROSPECT` to `UNDER_OFFER`.
    PRD section 3.5: A new deal starts at `stage` `ORIGINATION` and `capital_state` `UNCOMMITTED`, increments its portfolio's `active_deal_count`, and takes its initial `rofr_state` from the tower company standing over the stream's site: `PENDING` when that company's `rofr_required` is true, and `NOT_REQUIRED` when it is false.

    Design: Corner/state_machines/idempotency_second_outreach_request_on_the_same_deal_rejected
    """
    scenario = deal_in_outreach(api)

    response = api.start_outreach(scenario.deal_id, headers=make_acquisition_analyst_headers())
    validate_error(response, ApiErrorId.ERR_INVALID_DEAL_STAGE.value)

    deal = _read_deal(api, scenario.deal_id)
    assert deal["stage"] == "OUTREACH"
    assert deal["negotiation_rounds"] == 0
    assert deal["capital_state"] == "UNCOMMITTED"

    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert stream["acquisition_status"] == "UNDER_OFFER"

    landowner = validate_success(
        api.get_landowner(scenario.landowner_id, headers=make_acquisition_analyst_headers())
    )
    assert landowner["outreach_status"] == "NEW"

    offers, meta = validate_paginated(
        api.list_offers(scenario.deal_id, headers=make_acquisition_analyst_headers())
    )
    assert meta["total_count"] == 0
    assert offers == []


def test_first_outreach_request_moves_the_deal_out_of_origination(api):
    """The first outreach call is the one that works, and it flips the stream to UNDER_OFFER.

    PRD section 3.5: Starting outreach moves the deal `ORIGINATION → OUTREACH`, and is permitted only when the pinned valuation's `status` is `APPROVED` and the landowner is not at `DO_NOT_CONTACT`.
    PRD section 3.5: The transition pushes the stream from `PROSPECT` to `UNDER_OFFER`.
    PRD section 3.5: Its `negotiation_rounds` starts at zero, its `easement_status` at `NOT_DRAFTED`, its `agreed_consideration_cents` unset, and every escrow figure at zero.

    Design: Corner/state_machines/idempotency_second_outreach_request_on_the_same_deal_rejected
    """
    scenario = deal_in_origination(api)
    assert scenario["deal"]["stage"] == "ORIGINATION"
    assert read_lease_stream(api, scenario.lease_stream_id)["acquisition_status"] == "PROSPECT"

    deal = validate_success(
        api.start_outreach(scenario.deal_id, headers=make_acquisition_analyst_headers())
    )
    assert deal["stage"] == "OUTREACH"
    assert deal["negotiation_rounds"] == 0

    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert stream["acquisition_status"] == "UNDER_OFFER"


# ===========================================================================
# A price may not be blessed on a tower with no carriers on it
# ===========================================================================


def test_approving_a_valuation_on_a_tenancy_free_stream_is_refused(api):
    """A stream whose carrier roster is empty cannot have its price approved.

    PRD section 3.4: A `PortfolioManager` approves a `DRAFT`: `DRAFT → APPROVED`, permitted only when the stream's `active_tenancy_count` is at least one — otherwise `ERR_NO_ACTIVE_TENANCY` — and only when `tenancy_quality_score_snapshot` still equals the stream's current `tenancy_quality_score`.
    PRD section 2.8: **Stream has an active tenancy** — a valuation may not be approved for a stream with no tenancy in `ACTIVE` or `HOLDOVER`; otherwise `ERR_NO_ACTIVE_TENANCY` (422).

    Design: Corner/state_machines/precondition_enforcement_valuation_approval_without_active_tenancy_rejected
    """
    scenario = stream_with_draft_valuation(api, tenancies=[])
    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert stream["active_tenancy_count"] == 0

    response = api.approve_valuation(
        scenario.valuation_id, headers=make_portfolio_manager_headers(PM_APPROVER_USER_ID)
    )
    validate_error(response, ApiErrorId.ERR_NO_ACTIVE_TENANCY.value)


def test_refused_approval_leaves_the_valuation_in_draft_unstamped(api):
    """The refusal leaves the price exactly where it was born: DRAFT, with no approver recorded.

    PRD section 3.4: A valuation is born in `DRAFT`.
    PRD section 3.4: Approval stamps `approved_by_user_id` from the acting `X-User-ID` and `approved_at` from the current instant, and demotes any previously approved valuation on the same stream: `APPROVED → SUPERSEDED`.

    Design: Corner/state_machines/precondition_enforcement_valuation_approval_without_active_tenancy_rejected
    """
    scenario = stream_with_draft_valuation(api, tenancies=[])

    response = api.approve_valuation(
        scenario.valuation_id, headers=make_portfolio_manager_headers(PM_APPROVER_USER_ID)
    )
    validate_error(response, ApiErrorId.ERR_NO_ACTIVE_TENANCY.value)

    valuation = _read_valuation(api, scenario.lease_stream_id, scenario.valuation_id)
    assert valuation["status"] == "DRAFT"
    assert valuation.get("approved_by_user_id") is None
    assert valuation.get("approved_at") is None


def test_a_tenancy_free_stream_still_prices_at_the_below_forty_discount_tier(api):
    """The arithmetic runs regardless: an empty roster scores zero and prices off the bottom rung.

    PRD section 3.3: A stream with no `ACTIVE` or `HOLDOVER` tenancy scores zero.
    PRD section 3.4: That snapshot picks the base discount tier from a four-rung ladder evaluated from the top down: a score of 80 or more prices at 700 basis points; failing that, a score of 60 or more prices at 850; failing that, a score of 40 or more prices at 1000; and anything below 40 prices at 1250.

    Design: Corner/state_machines/precondition_enforcement_valuation_approval_without_active_tenancy_rejected
    """
    scenario = stream_with_draft_valuation(api, tenancies=[])

    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert stream["tenancy_quality_score"] == 0
    assert stream["active_tenancy_count"] == 0

    valuation = scenario["valuation"]
    assert_valuation(valuation)
    assert valuation["tenancy_quality_score_snapshot"] == 0
    assert valuation["discount_rate_bps"] == THRESHOLDS["DISCOUNT_BPS_SCORE_BELOW_40"]
    assert valuation["horizon_years"] == THRESHOLDS["LUMP_SUM_HORIZON_YEARS"]
    assert valuation["status"] == "DRAFT"


def test_approval_succeeds_once_the_stream_carries_an_active_tenancy(api):
    """With one active anchor carrier on the roster the same approval goes through and is stamped.

    PRD section 3.4: A `PortfolioManager` approves a `DRAFT`: `DRAFT → APPROVED`, permitted only when the stream's `active_tenancy_count` is at least one — otherwise `ERR_NO_ACTIVE_TENANCY` — and only when `tenancy_quality_score_snapshot` still equals the stream's current `tenancy_quality_score`.
    PRD section 3.4: Approval stamps `approved_by_user_id` from the acting `X-User-ID` and `approved_at` from the current instant, and demotes any previously approved valuation on the same stream: `APPROVED → SUPERSEDED`.
    PRD section 2.6: The clock's value, referred to throughout this document as the current instant, starts at `2026-08-01T00:00:00Z` and is repositioned only by a `PlatformAdmin` supplying a `current_utc` instant to the administrative clock capability, which echoes back the resulting `current_utc`.

    Design: Corner/state_machines/precondition_enforcement_valuation_approval_without_active_tenancy_rejected
    """
    scenario = stream_with_draft_valuation(api)
    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert stream["active_tenancy_count"] == 1

    valuation = validate_success(
        api.approve_valuation(
            scenario.valuation_id, headers=make_portfolio_manager_headers(PM_APPROVER_USER_ID)
        )
    )
    assert valuation["status"] == "APPROVED"
    assert valuation["approved_by_user_id"] == PM_APPROVER_USER_ID
    assert valuation["approved_at"].startswith(CLOCK_START_PREFIX)


# ===========================================================================
# Clearance is a join: the title track and the refusal track must both finish
# ===========================================================================


def test_cleared_title_alone_leaves_the_deal_waiting_in_diligence(api):
    """A clean title search is only one of the two branches, so the deal stays in diligence.

    PRD section 3.7: A deal leaves `DILIGENCE` for `CLEAR_TO_CLOSE` only when three conditions hold simultaneously: the title report's `review_status` is `CLEARED`, its `consent_status` is either `NOT_REQUIRED` or `GRANTED`, and the deal's `rofr_state` is one of `NOT_REQUIRED`, `WAIVED`, and `WAIVED_BY_LAPSE`.
    PRD section 3.6: Serving snapshots the tower company's `rofr_window_days` into `window_days_snapshot` — later edits to the tower company do not move an already-served window — sets `served_at` and `window_start` to the current instant, sets `window_end` to `window_days_snapshot` days after `window_start`, opens the notice at `status` `SERVED`, and moves the deal's `rofr_state` to `PENDING`.

    Design: Corner/state_machines/branching_diligence_join_waits_for_both_title_and_rofr_branches
    """
    scenario = build_chain(
        api, "title_cleared", tower_company=ROFR_REQUIRED_COMPANY, serve_rofr=True
    )

    report = validate_success(
        api.get_title_report(scenario.title_report_id, headers=make_title_officer_headers())
    )
    assert_title_report(report)
    assert report["review_status"] == "CLEARED"
    assert report["consent_status"] == "NOT_REQUIRED"
    assert report["open_exception_count"] == 0

    deal = _read_deal(api, scenario.deal_id)
    assert deal["stage"] == "DILIGENCE"
    assert deal["easement_status"] == "NOT_DRAFTED"
    assert deal["rofr_state"] == "PENDING"
    assert deal["capital_state"] == "RESERVED"

    notices, meta = validate_paginated(
        api.list_rofr_notices(scenario.deal_id, headers=make_acquisition_analyst_headers())
    )
    assert meta["total_count"] == 1
    assert notices[0]["status"] == "SERVED"


def test_explicit_clearance_evaluation_reports_the_open_refusal_window(api):
    """Demanding clearance while the tower company has not answered names the refusal window as the blocker.

    PRD section 3.7: On failure the explicit evaluation returns the specific blocker: `ERR_ROFR_WINDOW_OPEN` while `rofr_state` is still `PENDING`, `ERR_TITLE_EXCEPTIONS_OPEN` while `open_exception_count` is above zero, or `ERR_MORTGAGE_CONSENT_MISSING` while a mortgage is of record and consent has not been granted.
    PRD section 2.8: **Refusal window closed** — a deal may not reach `CLEAR_TO_CLOSE` and may not close while its `rofr_state` is `PENDING`; this check runs on the operator-driven clearance evaluation and again at closing; otherwise `ERR_ROFR_WINDOW_OPEN` (422).
    PRD section 3.7: **Escrow funding** is the `TreasuryOfficer`'s step, and it is permitted only from `capital_state` `RESERVED` while the deal's `stage` is `CLEAR_TO_CLOSE`.
    PRD section 2.8: **Deal stage admits the action** — the deal's `stage` permits the operation; otherwise `ERR_INVALID_DEAL_STAGE` (409).

    Design: Corner/state_machines/branching_diligence_join_waits_for_both_title_and_rofr_branches
    """
    scenario = build_chain(
        api, "title_cleared", tower_company=ROFR_REQUIRED_COMPANY, serve_rofr=True
    )

    response = api.clear_to_close(scenario.deal_id, headers=make_portfolio_manager_headers())
    validate_error(response, ApiErrorId.ERR_ROFR_WINDOW_OPEN.value)

    deal = _read_deal(api, scenario.deal_id)
    assert deal["stage"] == "DILIGENCE"
    assert deal["easement_status"] == "NOT_DRAFTED"
    assert deal["rofr_state"] == "PENDING"

    escrow_response = api.fund_escrow(scenario.deal_id, headers=make_treasury_officer_headers())
    validate_error(escrow_response, ApiErrorId.ERR_INVALID_DEAL_STAGE.value)


def test_tower_company_waiver_completes_the_clearance_join(api):
    """The second branch closing — the tower company waiving its refusal right — is what drafts the easement.

    PRD section 3.6: A waiver takes the notice `SERVED → WAIVED`, stamps `responded_at` and `responded_by_user_id`, moves the deal's `rofr_state` to `WAIVED`, and re-evaluates the clearance join.
    PRD section 3.7: On success the deal moves `DILIGENCE → CLEAR_TO_CLOSE` and its `easement_status` moves `NOT_DRAFTED → DRAFTED`.
    PRD section 2.6: The clock's value, referred to throughout this document as the current instant, starts at `2026-08-01T00:00:00Z` and is repositioned only by a `PlatformAdmin` supplying a `current_utc` instant to the administrative clock capability, which echoes back the resulting `current_utc`.

    Design: Corner/state_machines/branching_diligence_join_waits_for_both_title_and_rofr_branches
    """
    scenario = build_chain(
        api, "title_cleared", tower_company=ROFR_REQUIRED_COMPANY, serve_rofr=True
    )
    assert _read_deal(api, scenario.deal_id)["stage"] == "DILIGENCE"

    notice = validate_success(
        api.respond_to_rofr_notice(
            scenario["rofr_notice"]["id"], {"decision": "WAIVE"}, headers=scenario.tower_agent_headers
        )
    )
    assert notice["status"] == "WAIVED"
    assert notice["responded_at"].startswith(CLOCK_START_PREFIX)
    assert notice["responded_by_user_id"] == scenario.tower_company_id

    deal = _read_deal(api, scenario.deal_id)
    assert deal["rofr_state"] == "WAIVED"
    assert deal["stage"] == "CLEAR_TO_CLOSE"
    assert deal["easement_status"] == "DRAFTED"
    assert deal["capital_state"] == "RESERVED"


# ===========================================================================
# Title exceptions come off one cure at a time
# ===========================================================================


def test_first_cure_of_three_exceptions_keeps_the_report_in_exceptions_found(api):
    """Curing one of three exceptions only decrements the open count; the report does not clear.

    PRD section 3.6: From `ORDERED`, findings with an `exception_count` greater than zero take the report `ORDERED → EXCEPTIONS_FOUND`, setting both `exception_count` and `open_exception_count` to the reported figure, recording `mortgage_present` and `lender_name`, and — when `mortgage_present` is true — flipping `consent_status` to `PENDING_REQUEST`.
    PRD section 3.6: While more than one exception remains open the report stays put — `EXCEPTIONS_FOUND → EXCEPTIONS_FOUND` with `open_exception_count` reduced by one.
    PRD section 3.7: A deal leaves `DILIGENCE` for `CLEAR_TO_CLOSE` only when three conditions hold simultaneously: the title report's `review_status` is `CLEARED`, its `consent_status` is either `NOT_REQUIRED` or `GRANTED`, and the deal's `rofr_state` is one of `NOT_REQUIRED`, `WAIVED`, and `WAIVED_BY_LAPSE`.
    PRD section 3.7: On success the deal moves `DILIGENCE → CLEAR_TO_CLOSE` and its `easement_status` moves `NOT_DRAFTED → DRAFTED`.

    Design: Corner/state_machines/cyclic_title_exception_self_loop_decrements_until_the_last_one_clears
    """
    scenario = build_chain(
        api, "title_cleared", findings={"exception_count": 3, "mortgage_present": False}
    )
    assert scenario["title_report"]["review_status"] == "EXCEPTIONS_FOUND"
    assert scenario["title_report"]["exception_count"] == 3
    assert scenario["title_report"]["open_exception_count"] == 3

    report = validate_success(
        api.transition_title_report(
            scenario.title_report_id, {"action": "CURE_EXCEPTION"}, headers=make_title_officer_headers()
        )
    )
    assert report["review_status"] == "EXCEPTIONS_FOUND"
    assert report["open_exception_count"] == 2
    assert report["exception_count"] == 3

    deal = _read_deal(api, scenario.deal_id)
    assert deal["stage"] == "DILIGENCE"
    assert deal["easement_status"] == "NOT_DRAFTED"


def test_last_cure_clears_the_report_and_fires_the_clearance_join(api):
    """The third cure is the one that closes the search out and carries the deal into clearance.

    PRD section 3.6: When exactly one exception remains open, the same verb finishes the job: `EXCEPTIONS_FOUND → CLEARED`, driving `open_exception_count` to zero and re-evaluating the deal's clearance join.
    PRD section 3.7: On success the deal moves `DILIGENCE → CLEAR_TO_CLOSE` and its `easement_status` moves `NOT_DRAFTED → DRAFTED`.

    Design: Corner/state_machines/cyclic_title_exception_self_loop_decrements_until_the_last_one_clears
    """
    scenario = build_chain(
        api, "title_cleared", findings={"exception_count": 3, "mortgage_present": False}
    )

    open_counts = []
    statuses = []
    for _ in range(3):
        report = validate_success(
            api.transition_title_report(
                scenario.title_report_id,
                {"action": "CURE_EXCEPTION"},
                headers=make_title_officer_headers(),
            )
        )
        statuses.append(report["review_status"])
        open_counts.append(report["open_exception_count"])

    assert open_counts == [2, 1, 0]
    assert statuses == ["EXCEPTIONS_FOUND", "EXCEPTIONS_FOUND", "CLEARED"]

    final = validate_success(
        api.get_title_report(scenario.title_report_id, headers=make_title_officer_headers())
    )
    assert final["review_status"] == "CLEARED"
    assert final["exception_count"] == 3
    assert final["open_exception_count"] == 0
    assert final["consent_status"] == "NOT_REQUIRED"

    deal = _read_deal(api, scenario.deal_id)
    assert deal["stage"] == "CLEAR_TO_CLOSE"
    assert deal["easement_status"] == "DRAFTED"


def test_curing_again_after_the_report_cleared_is_refused(api):
    """A fourth cure has nothing left to decrement: the verb is not declared from CLEARED and is refused.

    PRD section 3.6: A verb that is not declared from the report's current `review_status` or `consent_status` is refused with `ERR_INVALID_TITLE_STATE`.
    PRD section 2.8: **Title state admits the action** — the requested title or consent verb is declared from the current `review_status` or `consent_status`; otherwise `ERR_INVALID_TITLE_STATE` (409).
    PRD section 3.7: On success the deal moves `DILIGENCE → CLEAR_TO_CLOSE` and its `easement_status` moves `NOT_DRAFTED → DRAFTED`.

    Design: Corner/state_machines/cyclic_title_exception_self_loop_decrements_until_the_last_one_clears
    """
    scenario = build_chain(
        api, "title_cleared", findings={"exception_count": 3, "mortgage_present": False}
    )
    for _ in range(3):
        validate_success(
            api.transition_title_report(
                scenario.title_report_id,
                {"action": "CURE_EXCEPTION"},
                headers=make_title_officer_headers(),
            )
        )

    response = api.transition_title_report(
        scenario.title_report_id, {"action": "CURE_EXCEPTION"}, headers=make_title_officer_headers()
    )
    validate_error(response, ApiErrorId.ERR_INVALID_TITLE_STATE.value)

    report = validate_success(
        api.get_title_report(scenario.title_report_id, headers=make_title_officer_headers())
    )
    assert report["review_status"] == "CLEARED"
    assert report["open_exception_count"] == 0
    assert report["exception_count"] == 3

    deal = _read_deal(api, scenario.deal_id)
    assert deal["stage"] == "CLEAR_TO_CLOSE"
    assert deal["easement_status"] == "DRAFTED"
