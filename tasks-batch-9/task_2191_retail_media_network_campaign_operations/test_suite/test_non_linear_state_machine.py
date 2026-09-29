"""A state machine with a genuine cycle, whose derived fields never cycle with it.

A dispute under review may be sent back for more evidence and then returned to review, and
the loop may be taken twice. Both loops land the dispute in exactly the state it held
before them, so the status alone cannot say how many were taken. What distinguishes them
are the counters and the service-level deadline, which ratchet forward monotonically and at
different rates, and a first-response stamp that is written once and never again.
"""

from test_helpers import (
    ERR_DISPUTE_INVALID_STATE,
    ERR_MAX_INFO_REQUESTS_EXCEEDED,
    INFO_REQUEST_EXTENSION_HOURS,
    MAX_INFO_REQUESTS,
    SECOND_MEASUREMENT_ANALYST,
    SLA_BASE_HOURS,
    SLA_MANAGED_REDUCTION_HOURS,
    advertiser_headers,
    api_client,
    build_billable_world,
    build_dispute_awaiting_info,
    build_issued_invoice,
    parse_utc,
    provide_dispute_info,
    reread_campaign,
    reread_dispute,
    reread_invoice,
    request_dispute_info,
    round_half_up_int,
    set_clock,
    shift_hours,
    validate_error,
)

MANAGED_SERVICE_FEE_PCT = 0.05
PLAN_COMMITTED_CENTS = 40000000
CAMPAIGN_FLIGHT = ("2026-08-01T00:00:00Z", "2026-08-11T00:00:00Z")
AUCTION_AT = "2026-08-05T10:00:00Z"
SLOT_FLOOR_CENTS = 1250

ISSUED_AT = "2026-09-01T00:00:00Z"
FILED_AT = "2026-09-05T00:00:00Z"
DISPUTE_CATEGORY = "IMPRESSION_DISCREPANCY"
CLAIMED_AMOUNT_CENTS = 1000

# The base hours for this category, less the managed advertiser's reduction, is what the
# dispute starts with; each information request adds one extension on top.
BASE_SLA_HOURS = SLA_BASE_HOURS[DISPUTE_CATEGORY] - SLA_MANAGED_REDUCTION_HOURS
SLA_HOURS_AFTER_ONE_REQUEST = BASE_SLA_HOURS + INFO_REQUEST_EXTENSION_HOURS
SLA_HOURS_AFTER_TWO_REQUESTS = BASE_SLA_HOURS + 2 * INFO_REQUEST_EXTENSION_HOURS

ONSITE_SPEND_CENTS = SLOT_FLOOR_CENTS
MANAGED_FEE_CENTS = round_half_up_int(ONSITE_SPEND_CENTS * MANAGED_SERVICE_FEE_PCT)
NET_CASH_DUE_CENTS = ONSITE_SPEND_CENTS + MANAGED_FEE_CENTS


def _due_at(hours):
    """The deadline a service level of the given length puts on this dispute."""
    return parse_utc(shift_hours(FILED_AT, hours))


def _submitted_dispute_world():
    """A managed advertiser's issued invoice with one freshly filed dispute.

    One cost-per-click line item wins one auction and takes one click, so the invoice's
    on-site spend is exactly the slot floor. The trade fund pool is open with nothing
    accrued and the plan commits no trade-fund share, so the deduction ceiling is 0 and
    the whole charge falls to cash — which keeps the disputed figure a single simple
    number. The clock is left at the filing instant and is not moved again, and the daily
    checkpoint is never run, so no clock-driven escalation can fire during the cycle.
    """
    world = build_billable_world(
        managed=True,
        accrual_cents=0,
        advertiser={"managed_service_fee_pct": MANAGED_SERVICE_FEE_PCT},
        plan={
            "committed_total_cents": PLAN_COMMITTED_CENTS,
            "trade_fund_share_cents": 0,
            "window_start_at": "2026-08-01T00:00:00Z",
            "window_end_at": "2026-10-01T00:00:00Z",
        },
        slot={
            "max_concurrent_line_items": 2,
            "floor_cpc_cents": SLOT_FLOOR_CENTS,
            "relevance_weight": 1.0,
        },
        product={"category_code": "GROCERY", "margin_pct": 0.4},
        campaign={
            "channel_mix": "ONSITE_ONLY",
            "flight_start_at": CAMPAIGN_FLIGHT[0],
            "flight_end_at": CAMPAIGN_FLIGHT[1],
            "allocated_budget_cents": 5000000,
            "daily_cap_cents": 400000,
        },
        line_item={
            "bid_cents": 3000,
            "bid_type": "CPC",
            "daily_budget_cents": 200000,
            "flight_start_at": CAMPAIGN_FLIGHT[0],
            "flight_end_at": CAMPAIGN_FLIGHT[1],
            "category_code": "GROCERY",
            "keyword_match_terms": ["coffee"],
        },
        activate_at=AUCTION_AT,
        impressions=1,
        clicks=1,
    )
    set_clock(world, ISSUED_AT)
    build_issued_invoice(world, billing_period_code="2026-08")
    set_clock(world, FILED_AT)
    return world


def _dispute_after_one_loop():
    """File a dispute, review it, request evidence once and receive it."""
    world = _submitted_dispute_world()
    build_dispute_awaiting_info(
        world,
        claimed_amount_cents=CLAIMED_AMOUNT_CENTS,
        dispute_category=DISPUTE_CATEGORY,
    )
    provide_dispute_info(world)
    return world


def _dispute_after_two_loops():
    """Take the request-and-answer loop a second time around."""
    world = _dispute_after_one_loop()
    request_dispute_info(world, note="also send the partner reconciliation extract")
    provide_dispute_info(world)
    return world


def test_two_information_request_loops_return_the_dispute_to_where_they_started():
    """The status is unchanged by the cycle while every derived field has moved on.

    PRD 3.9: "An information request moves an `UNDER_REVIEW` dispute to `INFO_REQUESTED`,
    is available to `NetworkAdmin` and `MeasurementAnalyst`, and requires an
    `information_request_note`. It requires `info_request_count` to be strictly below 2,
    raises that count by 1, and extends `sla_due_at` by 48 hours with
    `sla_response_hours` recomputed accordingly. Providing the requested evidence moves
    the dispute back to `UNDER_REVIEW` ... raises `review_rounds` by 1 and recomputes
    `sla_breached`."

    PRD 3.9: "It stamps `first_response_at` with the current logical time when that field
    is still null, sets `assigned_analyst_user_id` to the acting `X-User-ID`, raises
    `review_rounds` by 1, and recomputes `sla_breached` under the strict-after rule."

    Design: Difficulty/non_linear_state_machine/nlsm_dispute_info_request_review_cycle
    """
    world = _dispute_after_two_loops()
    dispute = reread_dispute(world)

    # Two full loops end where the first review began.
    assert dispute["dispute_status"] == "UNDER_REVIEW"

    # The two counters ratchet at different rates: one per request against one per entry
    # into review, and the first review counts.
    assert dispute["info_request_count"] == MAX_INFO_REQUESTS == 2
    assert dispute["review_rounds"] == 3
    assert dispute["info_request_count"] != dispute["review_rounds"]

    assert dispute["sla_response_hours"] == SLA_HOURS_AFTER_TWO_REQUESTS == 144
    assert parse_utc(dispute["sla_due_at"]) == _due_at(SLA_HOURS_AFTER_TWO_REQUESTS)

    # Re-applying the extension only once, or not at all, would have left the deadline
    # shorter than it is.
    assert dispute["sla_response_hours"] != BASE_SLA_HOURS == 48
    assert dispute["sla_response_hours"] != SLA_HOURS_AFTER_ONE_REQUEST == 96

    # The first response is written once and never rewritten, so the second entry into
    # review leaves it exactly where the first put it.
    assert parse_utc(dispute["first_response_at"]) == parse_utc(FILED_AT)
    assert dispute["sla_breached"] is False
    assert dispute["escalation_level"] == 0
    assert dispute["approved_credit_cents"] == 0
    assert dispute["assigned_analyst_user_id"] == (
        SECOND_MEASUREMENT_ANALYST["X-User-ID"]
    )

    # One version per accepted transition: filing, review, request, answer, request,
    # answer.
    assert dispute["version"] == 6


def test_the_service_level_deadline_slides_outward_once_per_information_request():
    """Each request adds one extension; answering one adds none.

    PRD 3.9: "`sla_response_hours` is the base hours less the managed reduction plus 48
    hours for each information request already made, with the whole result floored at 24
    hours — so no dispute ever carries a service level tighter than a single day.
    `sla_due_at` is `filed_at` plus `sla_response_hours`, and it therefore moves outward as
    the information-request count grows."

    PRD 3.9: "The base hours come from `dispute_category`: 72 for
    `IMPRESSION_DISCREPANCY`, 120 for `ATTRIBUTION_WINDOW`, 96 for
    `OFFSITE_SPEND_VARIANCE` and 240 for `INCREMENTALITY_RESTATEMENT`. A managed
    advertiser earns a reduction of 24 hours; a self-serve advertiser earns none."

    Design: Difficulty/non_linear_state_machine/nlsm_dispute_info_request_review_cycle
    """
    world = _submitted_dispute_world()
    build_dispute_awaiting_info(
        world,
        claimed_amount_cents=CLAIMED_AMOUNT_CENTS,
        dispute_category=DISPUTE_CATEGORY,
    )

    # One request has been made, so one extension is on the clock.
    awaiting = reread_dispute(world)
    assert awaiting["dispute_status"] == "INFO_REQUESTED"
    assert awaiting["info_request_count"] == 1
    assert awaiting["review_rounds"] == 1
    assert awaiting["sla_response_hours"] == SLA_HOURS_AFTER_ONE_REQUEST == 96
    assert parse_utc(awaiting["sla_due_at"]) == _due_at(SLA_HOURS_AFTER_ONE_REQUEST)

    # Answering the request moves the state back but not the deadline.
    provide_dispute_info(world)
    answered = reread_dispute(world)
    assert answered["dispute_status"] == "UNDER_REVIEW"
    assert answered["info_request_count"] == 1
    assert answered["review_rounds"] == 2
    assert answered["sla_response_hours"] == awaiting["sla_response_hours"]
    assert parse_utc(answered["sla_due_at"]) == parse_utc(awaiting["sla_due_at"])

    # The second request adds the second extension.
    request_dispute_info(world, note="also send the partner reconciliation extract")
    requested_again = reread_dispute(world)
    assert requested_again["dispute_status"] == "INFO_REQUESTED"
    assert requested_again["info_request_count"] == 2
    assert requested_again["sla_response_hours"] == SLA_HOURS_AFTER_TWO_REQUESTS
    assert parse_utc(requested_again["sla_due_at"]) == _due_at(
        SLA_HOURS_AFTER_TWO_REQUESTS
    )
    assert parse_utc(requested_again["sla_due_at"]) > parse_utc(answered["sla_due_at"])


def test_a_third_information_request_is_refused_once_the_cycle_is_exhausted():
    """The loop is bounded at two requests even though the state permits another.

    PRD 3.9: "The review-request-review cycle is bounded at two information requests: a
    third request against a dispute whose `info_request_count` has already reached 2 is
    refused as a conflict, and the review must be concluded or escalated instead."

    PRD 2.12: "65. On a dispute information request: `info_request_count` is strictly less
    than the maximum of 2 — otherwise `ERR_MAX_INFO_REQUESTS_EXCEEDED`, 409."

    Design: Difficulty/non_linear_state_machine/nlsm_dispute_info_request_review_cycle
    """
    world = _dispute_after_two_loops()
    before = reread_dispute(world)

    # The dispute is back under review, which is the only state a request is declared
    # from, so nothing but the exhausted count can refuse this one.
    assert before["dispute_status"] == "UNDER_REVIEW"
    assert before["info_request_count"] == MAX_INFO_REQUESTS

    validate_error(
        api_client.request_measurement_dispute_info(
            before["id"],
            {"information_request_note": "one more log extract please"},
            SECOND_MEASUREMENT_ANALYST,
        ),
        ERR_MAX_INFO_REQUESTS_EXCEEDED,
    )

    after = reread_dispute(world)
    assert after["dispute_status"] == "UNDER_REVIEW"
    assert after["info_request_count"] == before["info_request_count"]
    assert after["review_rounds"] == before["review_rounds"]
    assert after["sla_response_hours"] == before["sla_response_hours"]
    assert after["version"] == before["version"]

    # Answering is refused too, because no request is outstanding to answer.
    validate_error(
        api_client.provide_measurement_dispute_info(
            before["id"], {"evidence_note": "unsolicited"}, advertiser_headers(world)
        ),
        ERR_DISPUTE_INVALID_STATE,
    )


def test_the_cycle_leaves_the_charge_and_the_delivery_dimension_untouched():
    """Only the billing dimension carries the dispute; the money is exactly as issued.

    PRD 3.8: "Step four computes `managed_service_fee_cents` as `gross_spend_cents`
    multiplied by the advertiser's `managed_service_fee_pct`, rounded half-up to whole
    cents; for a self-serve advertiser this is necessarily 0."

    PRD 3.8: "Step nine sets `trade_fund_deduction_cents` to that ceiling floored at 0,
    and to exactly 0 when the invoice names no pool. Step ten sets `net_cash_due_cents`
    to the billable-before-funds figure less `trade_fund_deduction_cents`, floored at 0."

    PRD 3.9: "Filing increments the invoice's `version` by 1."

    Design: Difficulty/non_linear_state_machine/nlsm_dispute_info_request_review_cycle
    """
    world = _dispute_after_two_loops()

    invoice = reread_invoice(world)
    assert invoice["onsite_spend_cents"] == ONSITE_SPEND_CENTS == 1250
    assert invoice["offsite_spend_cents"] == 0
    assert invoice["gross_spend_cents"] == ONSITE_SPEND_CENTS
    assert invoice["managed_service_fee_cents"] == MANAGED_FEE_CENTS == 63
    assert invoice["dispute_credit_cents"] == 0

    # The pool holds nothing and the plan commits no share, so the ceiling of step eight
    # is 0 and the whole charge stays in cash.
    assert invoice["trade_fund_deduction_cents"] == 0
    assert invoice["net_cash_due_cents"] == NET_CASH_DUE_CENTS == 1313
    assert invoice["invoice_status"] == "DISPUTED"
    assert CLAIMED_AMOUNT_CENTS <= (
        invoice["net_cash_due_cents"] + invoice["trade_fund_deduction_cents"]
    )

    # The campaign's two dimensions moved independently: delivery finished long before
    # the dispute was filed, and only the billing side reacted to it.
    campaign = reread_campaign(world)
    assert campaign["delivery_status"] == "COMPLETED"
    assert campaign["billing_status"] == "DISPUTED"
