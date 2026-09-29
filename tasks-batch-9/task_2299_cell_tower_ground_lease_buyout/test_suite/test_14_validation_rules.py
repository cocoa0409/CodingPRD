"""Validation rules of the lease-buyout pipeline: the guardrails that refuse a request.

Each test drives one rule to the edge that decides it — an advance sitting exactly on the
borrowing base, a second deal on a stream already under offer, a withdrawal one cent past
available capital, a clearance blocked by an open refusal window — and proves both the
error the PRD names and that the refused call left the ledger, the deal and the paperwork
exactly as they were.
"""

from test_helpers import (
    ApiErrorId,
    THRESHOLDS,
    ROFR_REQUIRED_COMPANY,
    advance_payload,
    assert_fields,
    build_chain,
    build_dispute_on_closed_stream,
    build_facility_with_pledge,
    build_mortgaged_deal_awaiting_consent,
    build_two_deals_on_one_portfolio,
    capital_adjustment_payload,
    create_portfolio,
    deal_cleared_to_close,
    deal_in_diligence,
    deal_in_negotiation,
    deal_payload,
    dispute_payload,
    draw_advance,
    make_closing_manager_headers,
    make_landowner_headers,
    offer_payload,
    read_facility,
    stream_with_draft_valuation,
    validate_error,
    validate_paginated,
    validate_success,
)

# Figures the PRD's own arithmetic produces from the canonical seed stream
# (3,600,000 cents of annual rent, FIXED_PCT 300 bps, 180 months remaining, one
# ACTIVE INVESTMENT_GRADE ANCHOR tenancy scoring 40 and therefore discounted at 1000 bps).
CANONICAL_VALUE_CENTS = 44_627_011
CANONICAL_MAX_BID_CENTS = 46_858_362
# 44,627,011 * 6500 / 10000 = 29,007,557.15 -> 29,007,557 rounded half up.
CANONICAL_BORROWING_BASE_CENTS = 29_007_557


def _row_by_id(rows, record_id):
    """Pick one record out of a collection page by its id."""
    matches = [row for row in rows if row["id"] == record_id]
    assert matches, f"record {record_id} is absent from the collection page"
    return matches[0]


# ===========================================================================
# The borrowing base: an advance at equality, and an advance over the total
# ===========================================================================


def test_advance_of_exactly_the_borrowing_base_is_drawn(api, treasury_headers):
    """An advance equal to the whole borrowing base is accepted and leaves the facility compliant.

    PRD 3.9: "The draw is permitted only when `advances_outstanding_cents` plus the requested amount is less than or equal to `borrowing_base_cents`; an over-draw is refused with `ERR_ADVANCE_EXCEEDS_BORROWING_BASE` and HTTP 402."
    PRD 3.9: "`compliance_state` is `BORROWING_BASE_DEFICIT` whenever `advances_outstanding_cents` is strictly greater than `borrowing_base_cents`, and `COMPLIANT` otherwise."

    Design: Corner/validations/satisfaction_to_pass_advance_exactly_equal_to_the_borrowing_base_succeeds
    """
    scenario = build_facility_with_pledge(api)
    facility = read_facility(api, scenario.facility_id)
    assert_fields(
        facility,
        {
            "pledged_eligible_total_cents": CANONICAL_VALUE_CENTS,
            "concentration_excess_cents": 0,
            "borrowing_base_cents": CANONICAL_BORROWING_BASE_CENTS,
            "advances_outstanding_cents": 0,
        },
        "facility before the draw",
    )

    drawn = validate_success(
        api.create_advance(
            scenario.facility_id, advance_payload(CANONICAL_BORROWING_BASE_CENTS), headers=treasury_headers
        )
    )

    assert_fields(
        drawn,
        {
            "advances_outstanding_cents": CANONICAL_BORROWING_BASE_CENTS,
            "borrowing_base_cents": CANONICAL_BORROWING_BASE_CENTS,
            "compliance_state": "COMPLIANT",
            "pledged_eligible_total_cents": CANONICAL_VALUE_CENTS,
        },
        "facility after drawing the whole base",
    )
    pledge = validate_success(api.get_collateral_pledge(scenario["pledge"]["id"], headers=treasury_headers))
    assert_fields(pledge, {"status": "PLEDGED", "eligible_value_cents": CANONICAL_VALUE_CENTS}, "pledge")


def test_second_advance_taking_the_running_total_over_the_base_is_refused(api, treasury_headers):
    """Two draws that are each affordable alone are refused when their sum passes the base, and the first draw survives.

    PRD 2.8: "**Advance within the borrowing base** — `advances_outstanding_cents` plus the requested amount is less than or equal to `borrowing_base_cents`; otherwise `ERR_ADVANCE_EXCEEDS_BORROWING_BASE` (402)."
    PRD 3.9: "A successful draw increases `advances_outstanding_cents` and re-evaluates `compliance_state`, and the response is the updated facility rather than an advance record."

    Design: Corner/validations/aggregate_validation_two_individually_valid_advances_exceed_the_borrowing_base
    """
    scenario = build_facility_with_pledge(api)
    first = draw_advance(api, scenario.facility_id, 20_000_000)
    assert first["advances_outstanding_cents"] == 20_000_000
    assert first["borrowing_base_cents"] == CANONICAL_BORROWING_BASE_CENTS

    # 20,000,000 + 10,000,000 = 30,000,000, which is above the 29,007,557 base.
    refused = api.create_advance(scenario.facility_id, advance_payload(10_000_000), headers=treasury_headers)
    validate_error(refused, ApiErrorId.ERR_ADVANCE_EXCEEDS_BORROWING_BASE.value, 402)

    facility = read_facility(api, scenario.facility_id)
    assert_fields(
        facility,
        {
            "advances_outstanding_cents": 20_000_000,
            "borrowing_base_cents": CANONICAL_BORROWING_BASE_CENTS,
            "compliance_state": "COMPLIANT",
        },
        "facility after the refused draw",
    )


# ===========================================================================
# Uniqueness: one active deal per stream, one outstanding offer per deal
# ===========================================================================


def test_second_deal_on_a_stream_already_under_offer_is_refused(api, analyst_headers, admin_headers):
    """A stream carrying a live deal in negotiation refuses a second deal, and the portfolio still counts one.

    PRD 3.2: "At most one non-terminal deal may exist per stream at a time; a second attempt is refused with `ERR_DUPLICATE_ACTIVE_DEAL`."
    PRD 2.8: "**One active deal per stream** — at most one non-terminal deal exists per lease stream; otherwise `ERR_DUPLICATE_ACTIVE_DEAL` (422)."

    Design: Corner/validations/violation_to_error_second_active_deal_on_the_same_stream_rejected
    """
    scenario = deal_in_negotiation(api)

    refused = api.create_deal(
        deal_payload(
            scenario.portfolio_id,
            scenario.lease_stream_id,
            scenario.valuation_id,
            easement_type="LONG_TERM_EASEMENT",
            easement_term_years=60,
            revenue_share_bps=3000,
        ),
        headers=analyst_headers,
    )
    validate_error(refused, ApiErrorId.ERR_DUPLICATE_ACTIVE_DEAL.value, 422)

    first_deal = validate_success(api.get_deal(scenario.deal_id, headers=analyst_headers))
    assert first_deal["stage"] == "NEGOTIATION"
    portfolio = validate_success(api.get_portfolio(scenario.portfolio_id, headers=admin_headers))
    assert portfolio["active_deal_count"] == 1
    stream = validate_success(api.get_lease_stream(scenario.lease_stream_id, headers=analyst_headers))
    assert stream["acquisition_status"] == "UNDER_OFFER"
    deals, meta = validate_paginated(
        api.list_deals({"lease_stream_id": scenario.lease_stream_id}, headers=analyst_headers)
    )
    assert meta["total_count"] == 1, f"the stream should carry one deal, meta reports {meta['total_count']}"
    assert [row["id"] for row in deals] == [scenario.deal_id]


def test_sending_a_second_offer_while_one_is_outstanding_is_refused(api, analyst_headers):
    """A second offer may be drafted but not sent while the first is still live, and the refused send burns no round.

    PRD 3.5: "**`SEND`** takes the offer `DRAFT → SENT`. It requires the deal's `stage` to be `OUTREACH` or `NEGOTIATION`, requires the landowner not to be at `DO_NOT_CONTACT`, requires the offer's `amount_cents` to be less than or equal to the pinned valuation's `max_bid_cents` — a violation is `ERR_OFFER_EXCEEDS_GUARDRAIL` — and requires that no other offer on the deal is currently sitting in `SENT` or `COUNTERED`, since only one proposal may be live at a time and a second is refused with `ERR_OFFER_ALREADY_OUTSTANDING`."
    PRD 2.8: "**One outstanding offer per deal** — at most one offer per deal sits in `SENT` or `COUNTERED`; otherwise `ERR_OFFER_ALREADY_OUTSTANDING` (422)."

    Design: Corner/validations/violation_to_error_second_outstanding_offer_on_the_same_deal_rejected
    """
    scenario = deal_in_negotiation(api)
    # 38,000,000 sits under the pinned valuation's 46,858,362 ceiling, so the guardrail is not the blocker.
    second_offer = validate_success(
        api.create_offer(scenario.deal_id, offer_payload(amount_cents=38_000_000), headers=analyst_headers), 201
    )
    assert second_offer["amount_cents"] <= CANONICAL_MAX_BID_CENTS

    refused = api.transition_offer(second_offer["id"], {"action": "SEND"}, headers=analyst_headers)
    validate_error(refused, ApiErrorId.ERR_OFFER_ALREADY_OUTSTANDING.value, 422)

    offers, _ = validate_paginated(api.list_offers(scenario.deal_id, headers=analyst_headers))
    still_draft = _row_by_id(offers, second_offer["id"])
    assert_fields(still_draft, {"status": "DRAFT", "round_number": 0}, "the offer whose send was refused")
    assert still_draft.get("sent_at") is None, "a refused send must not stamp sent_at"
    assert _row_by_id(offers, scenario.offer_id)["status"] == "SENT"
    deal = validate_success(api.get_deal(scenario.deal_id, headers=analyst_headers))
    assert_fields(deal, {"negotiation_rounds": 1, "stage": "NEGOTIATION"}, "deal after the refused send")


# ===========================================================================
# One open dispute per stream and type
# ===========================================================================


def test_second_access_dispute_on_the_same_stream_is_refused(api, analyst_headers):
    """A stream already carrying an open ACCESS dispute refuses a second one of the same type.

    PRD 3.8: "At most one non-terminal dispute may exist per stream and `dispute_type` pair; a duplicate is refused with `ERR_DISPUTE_ALREADY_OPEN`."
    PRD 2.8: "**One open dispute per stream and type** — at most one non-terminal dispute exists per lease stream and `dispute_type` pair; otherwise `ERR_DISPUTE_ALREADY_OPEN` (422)."

    Design: Corner/validations/violation_to_error_duplicate_open_dispute_type_rejected_while_a_new_type_is_accepted
    """
    scenario = build_dispute_on_closed_stream(api)
    landowner_headers = make_landowner_headers(scenario.landowner_id)

    refused = api.open_dispute(
        scenario.lease_stream_id,
        dispute_payload("ACCESS", "Second gate complaint on the same access road"),
        headers=landowner_headers,
    )
    validate_error(refused, ApiErrorId.ERR_DISPUTE_ALREADY_OPEN.value, 422)

    original = validate_success(api.get_dispute(scenario["dispute"]["id"], headers=landowner_headers))
    assert_fields(original, {"status": "OPEN", "dispute_type": "ACCESS"}, "the dispute already on file")
    landowner = validate_success(api.get_landowner(scenario.landowner_id, headers=analyst_headers))
    assert landowner["open_dispute_count"] == 1, "the refused duplicate must not raise open_dispute_count"
    _, meta = validate_paginated(api.list_disputes(scenario.lease_stream_id, headers=landowner_headers))
    assert meta["total_count"] == 1
    stream = validate_success(api.get_lease_stream(scenario.lease_stream_id, headers=analyst_headers))
    assert stream["servicing_status"] == "PERFORMING"


def test_interference_dispute_opens_beside_an_open_access_dispute(api, analyst_headers):
    """The duplicate bar is scoped to the type pair: a fresh INTERFERENCE case opens even though ACCESS is refused.

    PRD 3.8: "A `Landowner`, a `ServicingAgent`, or a `PlatformAdmin` may open a **DisputeCase** against a lease stream with a `dispute_type` of `ACCESS`, `INTERFERENCE`, or `PROPERTY_USE` and a free-text `description`."
    PRD 3.8: "At most one non-terminal dispute may exist per stream and `dispute_type` pair; a duplicate is refused with `ERR_DISPUTE_ALREADY_OPEN`."

    Design: Corner/validations/violation_to_error_duplicate_open_dispute_type_rejected_while_a_new_type_is_accepted
    """
    scenario = build_dispute_on_closed_stream(api)
    landowner_headers = make_landowner_headers(scenario.landowner_id)

    refused = api.open_dispute(
        scenario.lease_stream_id,
        dispute_payload("ACCESS", "Second gate complaint on the same access road"),
        headers=landowner_headers,
    )
    validate_error(refused, ApiErrorId.ERR_DISPUTE_ALREADY_OPEN.value, 422)

    accepted = validate_success(
        api.open_dispute(
            scenario.lease_stream_id,
            dispute_payload("INTERFERENCE", "Antenna interferes with irrigation controls"),
            headers=landowner_headers,
        ),
        201,
    )
    assert_fields(
        accepted, {"status": "OPEN", "dispute_type": "INTERFERENCE", "cure_attempts": 0}, "the new dispute type"
    )
    landowner = validate_success(api.get_landowner(scenario.landowner_id, headers=analyst_headers))
    assert landowner["open_dispute_count"] == 2, "two open disputes, not three: the duplicate never landed"
    _, meta = validate_paginated(api.list_disputes(scenario.lease_stream_id, headers=landowner_headers))
    assert meta["total_count"] == 2
    stream = validate_success(api.get_lease_stream(scenario.lease_stream_id, headers=analyst_headers))
    assert stream["servicing_status"] == "PERFORMING"


# ===========================================================================
# The portfolio capital ledger: withdrawals and the frozen posture
# ===========================================================================


def test_capital_withdrawal_one_cent_over_available_is_refused(api, admin_headers, analyst_headers):
    """A withdrawal one cent past available capital is refused, and the pool keeps its committed money.

    PRD 3.1: "A positive delta grows `total_capital_cents`; a negative delta shrinks it, and a withdrawal whose magnitude exceeds `available_capital_cents` is refused with `ERR_CAPITAL_WITHDRAWAL_EXCEEDS_AVAILABLE` — money already committed or deployed cannot be pulled back out."
    PRD 2.8: "**Withdrawal within available capital** — a negative capital adjustment may not exceed `available_capital_cents`; otherwise `ERR_CAPITAL_WITHDRAWAL_EXCEEDS_AVAILABLE` (422)."

    Design: Corner/validations/violation_to_error_capital_withdrawal_one_cent_over_available_rejected_then_exact_withdrawal_allowed
    """
    scenario = deal_in_diligence(api)
    # Gross 36,000,000 at the 150 bps tier: fee 540,000, commitment 36,540,000,
    # so available is 50,000,000 - 36,540,000 = 13,460,000 at 7,308 bps of utilization.
    before = validate_success(api.get_portfolio(scenario.portfolio_id, headers=admin_headers))
    assert_fields(
        before,
        {
            "total_capital_cents": 50_000_000,
            "committed_capital_cents": 36_540_000,
            "available_capital_cents": 13_460_000,
            "utilization_bps": 7308,
            "capital_posture": "OPEN",
        },
        "portfolio before the withdrawal",
    )

    refused = api.adjust_portfolio_capital(
        scenario.portfolio_id,
        capital_adjustment_payload(-13_460_001, "Over-withdrawal attempt"),
        headers=admin_headers,
    )
    validate_error(refused, ApiErrorId.ERR_CAPITAL_WITHDRAWAL_EXCEEDS_AVAILABLE.value, 422)

    after = validate_success(api.get_portfolio(scenario.portfolio_id, headers=admin_headers))
    assert_fields(
        after,
        {
            "total_capital_cents": 50_000_000,
            "committed_capital_cents": 36_540_000,
            "deployed_capital_cents": 0,
            "available_capital_cents": 13_460_000,
            "utilization_bps": 7308,
            "capital_posture": "OPEN",
        },
        "portfolio after the refused withdrawal",
    )
    deal = validate_success(api.get_deal(scenario.deal_id, headers=analyst_headers))
    assert deal["capital_state"] == "RESERVED"


def test_capital_withdrawal_of_exactly_available_capital_freezes_the_pool(api, admin_headers, analyst_headers):
    """Withdrawing exactly the available balance is allowed and leaves the pool fully committed and frozen.

    PRD 3.1: "A positive delta grows `total_capital_cents`; a negative delta shrinks it, and a withdrawal whose magnitude exceeds `available_capital_cents` is refused with `ERR_CAPITAL_WITHDRAWAL_EXCEEDS_AVAILABLE` — money already committed or deployed cannot be pulled back out."
    PRD 3.1: "Both rungs are inclusive, so a portfolio sitting at exactly 9000 basis points is frozen and one sitting at exactly 7500 is constrained."

    Design: Corner/validations/violation_to_error_capital_withdrawal_one_cent_over_available_rejected_then_exact_withdrawal_allowed
    """
    scenario = deal_in_diligence(api)

    refused = api.adjust_portfolio_capital(
        scenario.portfolio_id,
        capital_adjustment_payload(-13_460_001, "Over-withdrawal attempt"),
        headers=admin_headers,
    )
    validate_error(refused, ApiErrorId.ERR_CAPITAL_WITHDRAWAL_EXCEEDS_AVAILABLE.value, 422)

    updated = validate_success(
        api.adjust_portfolio_capital(
            scenario.portfolio_id,
            capital_adjustment_payload(-13_460_000, "Exact residual returned to investors"),
            headers=admin_headers,
        )
    )
    assert_fields(
        updated,
        {
            "total_capital_cents": 36_540_000,
            "committed_capital_cents": 36_540_000,
            "deployed_capital_cents": 0,
            "available_capital_cents": 0,
            "utilization_bps": 10_000,
            "capital_posture": "FROZEN",
        },
        "portfolio after withdrawing exactly the available balance",
    )
    assert updated["utilization_bps"] >= THRESHOLDS["POSTURE_FROZEN_UTILIZATION_BPS"]
    deal = validate_success(api.get_deal(scenario.deal_id, headers=analyst_headers))
    assert_fields(deal, {"capital_state": "RESERVED", "stage": "DILIGENCE"}, "the reserved deal")


def test_acceptance_on_a_frozen_pool_is_refused_though_capital_remains(api, analyst_headers, admin_headers):
    """A frozen posture blocks a second reservation even though the pool still holds more than the commitment.

    PRD 3.5: "Acceptance additionally requires that the funding portfolio's `capital_posture` is not `FROZEN` — refused with `ERR_PORTFOLIO_CAPITAL_FROZEN` — and that the portfolio's `available_capital_cents` is greater than or equal to the deal's computed `total_commitment_cents`, refused with `ERR_INSUFFICIENT_PORTFOLIO_CAPITAL` and HTTP 402 when the pool cannot fund the purchase."
    PRD 2.8: "**Portfolio not frozen** — the portfolio's `capital_posture` is not `FROZEN` when capital is reserved; otherwise `ERR_PORTFOLIO_CAPITAL_FROZEN` (422)."

    Design: Corner/validations/violation_to_error_frozen_posture_blocks_a_reservation_that_still_has_available_capital
    """
    scenario = build_two_deals_on_one_portfolio(
        api,
        total_capital_cents=50_000_000,
        milestones=["offer_sent", "offer_sent"],
        offers=[{"amount_cents": 45_000_000}, {"amount_cents": 4_000_000}],
    )
    big, small = scenario.deal_a, scenario.deal_b

    # 45,000,000 at the 150 bps tier commits 45,675,000, i.e. 9,135 bps of a 50,000,000 pool.
    accepted = validate_success(
        api.transition_offer(big.offer_id, {"action": "ACCEPT"}, headers=big.landowner_headers)
    )
    assert accepted["status"] == "ACCEPTED"
    frozen = validate_success(api.get_portfolio(scenario.portfolio_id, headers=admin_headers))
    assert_fields(
        frozen,
        {"committed_capital_cents": 45_675_000, "available_capital_cents": 4_325_000, "utilization_bps": 9135, "capital_posture": "FROZEN"},
        "portfolio once the larger deal reserved its commitment",
    )

    # 4,000,000 at the 250 bps tier needs 4,100,000, which the remaining 4,325,000 would cover.
    refused = api.transition_offer(small.offer_id, {"action": "ACCEPT"}, headers=small.landowner_headers)
    validate_error(refused, ApiErrorId.ERR_PORTFOLIO_CAPITAL_FROZEN.value, 422)

    small_deal = validate_success(api.get_deal(small.deal_id, headers=analyst_headers))
    assert small_deal["capital_state"] == "UNCOMMITTED"
    assert small_deal.get("agreed_consideration_cents") is None, "a refused acceptance must not strike a price"
    offers, _ = validate_paginated(api.list_offers(small.deal_id, headers=analyst_headers))
    assert _row_by_id(offers, small.offer_id)["status"] == "SENT"
    big_deal = validate_success(api.get_deal(big.deal_id, headers=analyst_headers))
    assert big_deal["total_commitment_cents"] == 45_675_000
    unchanged = validate_success(api.get_portfolio(scenario.portfolio_id, headers=admin_headers))
    assert_fields(
        unchanged,
        {"committed_capital_cents": 45_675_000, "available_capital_cents": 4_325_000, "utilization_bps": 9135, "capital_posture": "FROZEN"},
        "portfolio after the refused acceptance",
    )


# ===========================================================================
# Pinned valuation status gates outreach
# ===========================================================================


def test_outreach_on_a_deal_pinning_a_draft_valuation_is_refused(api, analyst_headers):
    """A deal may be opened against a draft price but may not start outreach until that price is approved.

    PRD 3.4: "A deal pinning a stale valuation cannot advance beyond `ORIGINATION`; the attempt is refused with `ERR_VALUATION_STALE`, and an attempt to start outreach on a valuation still in `DRAFT` is refused with `ERR_VALUATION_NOT_APPROVED`."
    PRD 2.8: "**Pinned valuation approved** — a deal's pinned valuation is `APPROVED` before outreach may start; otherwise `ERR_VALUATION_NOT_APPROVED` (409)."

    Design: Corner/validations/violation_to_error_outreach_on_a_draft_valuation_rejected
    """
    scenario = stream_with_draft_valuation(api)
    assert scenario["valuation"]["status"] == "DRAFT"
    portfolio = create_portfolio(api)
    deal = validate_success(
        api.create_deal(
            deal_payload(portfolio["id"], scenario.lease_stream_id, scenario.valuation_id),
            headers=analyst_headers,
        ),
        201,
    )
    assert deal["stage"] == "ORIGINATION"

    refused = api.start_outreach(deal["id"], headers=analyst_headers)
    validate_error(refused, ApiErrorId.ERR_VALUATION_NOT_APPROVED.value, 409)

    valuations, _ = validate_paginated(api.list_valuations(scenario.lease_stream_id, headers=analyst_headers))
    pinned = _row_by_id(valuations, scenario.valuation_id)
    assert pinned["status"] == "DRAFT"
    assert pinned.get("approved_at") is None, "a refused outreach must not approve the pinned price"
    unmoved = validate_success(api.get_deal(deal["id"], headers=analyst_headers))
    assert unmoved["stage"] == "ORIGINATION"
    stream = validate_success(api.get_lease_stream(scenario.lease_stream_id, headers=analyst_headers))
    assert stream["acquisition_status"] == "PROSPECT"
    landowner = validate_success(api.get_landowner(scenario.landowner_id, headers=analyst_headers))
    assert landowner["outreach_status"] == "NEW"


# ===========================================================================
# The consent track: only a mortgaged property has one
# ===========================================================================


def test_consent_request_on_an_unmortgaged_property_is_refused(api, analyst_headers, title_headers):
    """Findings of no mortgage leave no consent to request, so the request is refused on that ground.

    PRD 3.6: "A `TitleOfficer` then submits **`REQUEST_CONSENT`**, `PENDING_REQUEST → REQUESTED`, permitted only when `mortgage_present` is true; a request against an unmortgaged property is refused with `ERR_MORTGAGE_CONSENT_NOT_REQUIRED`."
    PRD 2.8: "**Consent only when mortgaged** — requesting consent and ruling on consent both require `mortgage_present` true; otherwise `ERR_MORTGAGE_CONSENT_NOT_REQUIRED` (422)."

    Design: Corner/validations/conditional_validation_request_consent_without_a_mortgage_rejected
    """
    scenario = deal_cleared_to_close(api)
    report = validate_success(api.get_title_report(scenario.title_report_id, headers=title_headers))
    assert_fields(
        report,
        {"review_status": "CLEARED", "consent_status": "NOT_REQUIRED", "mortgage_present": False},
        "title report with no mortgage of record",
    )

    refused = api.transition_title_report(
        scenario.title_report_id, {"action": "REQUEST_CONSENT"}, headers=title_headers
    )
    validate_error(refused, ApiErrorId.ERR_MORTGAGE_CONSENT_NOT_REQUIRED.value, 422)

    after = validate_success(api.get_title_report(scenario.title_report_id, headers=title_headers))
    assert_fields(
        after,
        {"review_status": "CLEARED", "consent_status": "NOT_REQUIRED", "open_exception_count": 0},
        "title report after the refused consent request",
    )
    assert after.get("consent_requested_at") is None, "a refused request must not stamp consent_requested_at"
    assert after.get("consent_expires_at") is None, "a refused request must not open a consent window"
    deal = validate_success(api.get_deal(scenario.deal_id, headers=analyst_headers))
    assert deal["stage"] == "CLEAR_TO_CLOSE"


# ===========================================================================
# The clearance join and the order its blockers are reported in
# ===========================================================================


def test_open_refusal_window_is_reported_before_open_title_exceptions(api, analyst_headers, title_headers):
    """With both a pending refusal window and unresolved title exceptions, clearance names the refusal window.

    PRD 2.8: "Checks are evaluated in the following order, and the **first** failing check determines the response; later checks are not evaluated once an earlier one has failed."
    PRD 2.8: "**Refusal window closed** — a deal may not reach `CLEAR_TO_CLOSE` and may not close while its `rofr_state` is `PENDING`; this check runs on the operator-driven clearance evaluation and again at closing; otherwise `ERR_ROFR_WINDOW_OPEN` (422)."
    PRD 3.7: "On failure the explicit evaluation returns the specific blocker: `ERR_ROFR_WINDOW_OPEN` while `rofr_state` is still `PENDING`, `ERR_TITLE_EXCEPTIONS_OPEN` while `open_exception_count` is above zero, or `ERR_MORTGAGE_CONSENT_MISSING` while a mortgage is of record and consent has not been granted."

    Design: Corner/validations/cascading_validation_rofr_window_check_precedes_the_title_exception_check
    """
    scenario = build_chain(
        api,
        "title_cleared",
        tower_company=ROFR_REQUIRED_COMPANY,
        serve_rofr=True,
        findings={"exception_count": 2, "mortgage_present": False},
    )
    deal = validate_success(api.get_deal(scenario.deal_id, headers=analyst_headers))
    assert_fields(deal, {"stage": "DILIGENCE", "rofr_state": "PENDING"}, "deal with both tracks unfinished")
    report = validate_success(api.get_title_report(scenario.title_report_id, headers=title_headers))
    assert_fields(report, {"review_status": "EXCEPTIONS_FOUND", "open_exception_count": 2}, "title report")

    refused = api.clear_to_close(scenario.deal_id, headers=make_closing_manager_headers())
    validate_error(refused, ApiErrorId.ERR_ROFR_WINDOW_OPEN.value, 422)

    after = validate_success(api.get_deal(scenario.deal_id, headers=analyst_headers))
    assert_fields(
        after,
        {"stage": "DILIGENCE", "rofr_state": "PENDING", "easement_status": "NOT_DRAFTED"},
        "deal after the refused clearance",
    )
    notices, _ = validate_paginated(api.list_rofr_notices(scenario.deal_id, headers=analyst_headers))
    assert _row_by_id(notices, scenario["rofr_notice"]["id"])["status"] == "SERVED"
    unchanged = validate_success(api.get_title_report(scenario.title_report_id, headers=title_headers))
    assert unchanged["open_exception_count"] == 2


def test_clearance_with_an_open_title_exception_is_refused(api, analyst_headers, title_headers):
    """One unresolved title exception is enough to refuse clearance, and the deal stays merely reserved.

    PRD 2.8: "**Title exceptions closed** — `open_exception_count` is zero before clearance and before closing; this check runs on the operator-driven clearance evaluation and again at closing; otherwise `ERR_TITLE_EXCEPTIONS_OPEN` (422)."
    PRD 3.7: "On failure the explicit evaluation returns the specific blocker: `ERR_ROFR_WINDOW_OPEN` while `rofr_state` is still `PENDING`, `ERR_TITLE_EXCEPTIONS_OPEN` while `open_exception_count` is above zero, or `ERR_MORTGAGE_CONSENT_MISSING` while a mortgage is of record and consent has not been granted."

    Design: Corner/validations/violation_to_error_clearance_with_open_title_exceptions_rejected
    """
    scenario = build_chain(api, "title_cleared", findings={"exception_count": 1, "mortgage_present": False})
    deal = validate_success(api.get_deal(scenario.deal_id, headers=analyst_headers))
    assert_fields(
        deal,
        {"stage": "DILIGENCE", "rofr_state": "NOT_REQUIRED", "capital_state": "RESERVED"},
        "deal whose only blocker is title",
    )

    refused = api.clear_to_close(scenario.deal_id, headers=make_closing_manager_headers())
    validate_error(refused, ApiErrorId.ERR_TITLE_EXCEPTIONS_OPEN.value, 422)

    report = validate_success(api.get_title_report(scenario.title_report_id, headers=title_headers))
    assert_fields(
        report,
        {"review_status": "EXCEPTIONS_FOUND", "exception_count": 1, "open_exception_count": 1},
        "title report after the refused clearance",
    )
    after = validate_success(api.get_deal(scenario.deal_id, headers=analyst_headers))
    assert_fields(
        after,
        {"stage": "DILIGENCE", "capital_state": "RESERVED", "easement_status": "NOT_DRAFTED"},
        "deal after the refused clearance",
    )


def test_clearance_without_granted_mortgagee_consent_is_refused(api, analyst_headers, title_headers):
    """A cleared title on a mortgaged property still cannot clear the join while consent is only requested.

    PRD 2.8: "**Mortgagee consent present** — when the title report has `mortgage_present` true, `consent_status` is `GRANTED` before clearance and before closing; this check runs on the operator-driven clearance evaluation and again at closing; otherwise `ERR_MORTGAGE_CONSENT_MISSING` (422)."
    PRD 3.7: "A deal leaves `DILIGENCE` for `CLEAR_TO_CLOSE` only when three conditions hold simultaneously: the title report's `review_status` is `CLEARED`, its `consent_status` is either `NOT_REQUIRED` or `GRANTED`, and the deal's `rofr_state` is one of `NOT_REQUIRED`, `WAIVED`, and `WAIVED_BY_LAPSE`."

    Design: Corner/validations/violation_to_error_clearance_without_mortgage_consent_rejected
    """
    scenario = build_mortgaged_deal_awaiting_consent(api)
    report = validate_success(api.get_title_report(scenario.title_report_id, headers=title_headers))
    assert_fields(
        report,
        {"review_status": "CLEARED", "open_exception_count": 0, "mortgage_present": True, "consent_status": "REQUESTED"},
        "mortgaged title report awaiting the lender",
    )
    # The clock starts at 2026-08-01T00:00:00Z and consent runs twenty-one whole days.
    assert report["consent_expires_at"].startswith("2026-08-22T00:00:00")

    refused = api.clear_to_close(scenario.deal_id, headers=make_closing_manager_headers())
    validate_error(refused, ApiErrorId.ERR_MORTGAGE_CONSENT_MISSING.value, 422)

    after_report = validate_success(api.get_title_report(scenario.title_report_id, headers=title_headers))
    assert_fields(
        after_report,
        {"review_status": "CLEARED", "open_exception_count": 0, "consent_status": "REQUESTED"},
        "title report after the refused clearance",
    )
    deal = validate_success(api.get_deal(scenario.deal_id, headers=analyst_headers))
    assert_fields(
        deal,
        {"stage": "DILIGENCE", "capital_state": "RESERVED", "easement_status": "NOT_DRAFTED"},
        "deal after the refused clearance",
    )
