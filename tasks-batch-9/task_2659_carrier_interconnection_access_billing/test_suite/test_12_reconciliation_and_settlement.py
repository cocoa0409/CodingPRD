"""Mutual record exchange reconciliation and the reciprocal compensation settlement read."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_AGREED_MINUTES_OUT_OF_RANGE,
    ERR_CLOCK_MUST_ADVANCE,
    ERR_INVOICE_NOT_ISSUED,
)
from test_helpers.assertions import (
    assert_minutes,
    assert_money,
    assert_pct,
    assert_rate,
    assert_ratio,
    assert_reserve_summary,
)
from test_helpers.constants import (
    BATCH_EXCHANGE_REFERENCE_OUT,
    BILLABLE_MINUTES_TOTAL,
    RATED_TOTAL_PRELIMINARY,
    RECIPROCAL_RATE,
    RESERVE_BUCKET_UNCOLLECTIBLE,
    T_2026_07_01,
    T_2026_07_25,
    T_2026_09_01,
)
from test_helpers.factories import (
    clock_payload,
    local_cdr_payload,
    reconciliation_accept_payload,
    reconciliation_adjust_payload,
    usage_batch_payload,
)
from test_helpers.fixtures import (
    read_carrier,
    read_invoice,
    read_ledger,
    read_reconciliation_case,
    read_reserve_summary,
    read_usage_batch,
    setup_draft_invoice,
    setup_effective_agreement_with_rated_batch,
    setup_issued_invoice,
    setup_outbound_rated_batch,
    setup_reconciliation_case,
)

COUNTERPARTY_MINUTES = 63.0000
COUNTERPARTY_AMOUNT = 28.00
VARIANCE_PCT = 15.87
VARIANCE_AMOUNT = 4.47
OUTBOUND_MINUTES = 60.0000
ISSUE_RESERVE = 1.62


def test_reconciliation_case_creation_snapshots_our_side_of_the_exchange(
    api, controller_headers
):
    """Opening a case freezes our minutes and money and computes nothing yet.

    PRD 3.10: "Creation snapshots our side of the comparison: `our_minutes` from the batch's `total_billable_minutes` and `our_amount_usd` from the batch's `rated_amount_usd`. The case lands in `status` `OPEN` with `minute_variance_pct`, `amount_variance_usd`, `agreed_minutes`, `adjustment_amount_usd` and `adjusted_at` all unset."
    PRD 3.10: "A `RevenueAssuranceController` or an `AccessBillingAnalyst` opens a **reconciliation case** against a batch, naming the `usage_batch_id`, the `counterparty_reported_minutes` (at four decimals, zero or greater) and `counterparty_reported_amount_usd` (at two decimals, zero or greater) the other side computed for the same period and direction, and the `exchange_reference` of the counterparty file being reconciled, which must be non-empty."

    Design: Corner/endpoints/reconciliation_case_creation_snapshots_our_side_of_the_exchange
    """
    state = setup_issued_invoice(api)
    setup_reconciliation_case(api, state, evaluate=False)
    case = state["case"]

    assert case["usage_batch_id"] == state["batch_id"]
    assert_minutes(case["our_minutes"], BILLABLE_MINUTES_TOTAL)
    assert_money(case["our_amount_usd"], RATED_TOTAL_PRELIMINARY)
    assert_minutes(case["counterparty_reported_minutes"], COUNTERPARTY_MINUTES)
    assert_money(case["counterparty_reported_amount_usd"], COUNTERPARTY_AMOUNT)
    assert case["status"] == "OPEN"
    assert case["minute_variance_pct"] is None
    assert case["amount_variance_usd"] is None
    assert case["agreed_minutes"] is None
    assert case["adjustment_amount_usd"] is None
    assert case["adjusted_at"] is None

    _, meta = validate_paginated(
        api.list_batch_reconciliation_cases(state["batch_id"], controller_headers)
    )
    assert meta["total_count"] == 1


def test_record_exchange_variance_exactly_at_tolerance_is_accepted(
    api, controller_headers
):
    """A minute variance of exactly 2.00 percent closes the case without a credit.

    PRD 3.10: "Otherwise `minute_variance_pct` is our minutes less the counterparty's minutes, multiplied by one hundred and divided by the counterparty's minutes, rounded half up to two decimal places. `amount_variance_usd` is `our_amount_usd` less `counterparty_reported_amount_usd`, rounded half up to two decimal places."
    PRD 3.10: "If the absolute value is 2.00 or less, the case moves `OPEN → ACCEPTED`, which is terminal, and no adjustment is posted. A variance of exactly 2.00 therefore resolves to `ACCEPTED`, not `VARIANCE_IDENTIFIED`."

    Design: Corner/calculations/record_exchange_variance_exactly_at_tolerance_is_accepted
    """
    state = setup_issued_invoice(api)
    setup_reconciliation_case(
        api,
        state,
        evaluate=False,
        counterparty_reported_minutes=71.5686,
        counterparty_reported_amount_usd=30.00,
    )

    evaluated = validate_success(
        api.evaluate_reconciliation_case(state["case_id"], {}, controller_headers),
        expected_status=200,
    )

    assert_minutes(evaluated["our_minutes"], BILLABLE_MINUTES_TOTAL)
    assert_money(evaluated["our_amount_usd"], RATED_TOTAL_PRELIMINARY)
    assert_pct(evaluated["minute_variance_pct"], 2.00)
    assert_money(evaluated["amount_variance_usd"], 2.47)
    assert evaluated["status"] == "ACCEPTED"
    assert evaluated["adjustment_amount_usd"] is None
    assert evaluated["adjusted_at"] is None

    invoice = read_invoice(api, state["invoice_id"])
    assert_money(invoice["credited_amount_usd"], 0.00)
    assert_money(invoice["open_balance_usd"], RATED_TOTAL_PRELIMINARY)


def test_reconciliation_adjustment_credits_the_invoice_at_the_blended_rate(
    api, controller_headers
):
    """Conceding three minutes credits them at the invoice's own blended rate.

    PRD 3.10: "The credit is computed at the invoice's blended effective rate: `blended_rate_per_mou_usd` is `our_amount_usd` divided by `our_minutes`, rounded half up to six decimal places, and `adjustment_amount_usd` is `our_minutes` less `agreed_minutes`, multiplied by that blended rate, rounded half up to two decimal places."
    PRD 3.10: "The case moves `VARIANCE_IDENTIFIED → ADJUSTED`, which is terminal, with `adjusted_at` stamped from the logical clock; the invoice's `credited_amount_usd` increases by `adjustment_amount_usd` and its `open_balance_usd` falls by the same amount, with `payment_status` possibly advancing as a result; the reserve recomputation of §2.11 re-runs for the carrier and an `UNCOLLECTIBLE_ADJUSTMENT` reserve ledger entry with `source_event` `RECONCILIATION_ADJUSTED` is appended; and the case's, the invoice's and the carrier's `version` values each increment by 1."
    PRD 2.11: "`uncollectible_reserve_balance_usd` is the greater of `net_receivable_usd` and zero, multiplied by the selected percentage and divided by one hundred, rounded half up to two decimal places."

    Design: Corner/calculations/reconciliation_adjustment_credits_the_invoice_at_the_blended_rate
    """
    state = setup_issued_invoice(api)
    setup_reconciliation_case(api, state)
    evaluated = state["case"]
    assert evaluated["status"] == "VARIANCE_IDENTIFIED"
    assert_pct(evaluated["minute_variance_pct"], VARIANCE_PCT)
    assert_money(evaluated["amount_variance_usd"], VARIANCE_AMOUNT)

    adjusted = validate_success(
        api.adjust_reconciliation_case(
            state["case_id"], reconciliation_adjust_payload(70.0), controller_headers
        ),
        expected_status=200,
    )
    assert adjusted["status"] == "ADJUSTED"
    assert_minutes(adjusted["agreed_minutes"], 70.0000)
    assert adjusted["adjusted_at"] == T_2026_09_01
    assert_money(adjusted["adjustment_amount_usd"], 1.33)

    invoice = read_invoice(api, state["invoice_id"])
    assert_money(invoice["credited_amount_usd"], 1.33)
    assert_money(invoice["open_balance_usd"], 31.14)
    assert_money(invoice["billed_amount_usd"], RATED_TOTAL_PRELIMINARY, "billed_amount_usd")

    assert_reserve_summary(
        read_reserve_summary(api, state["carrier_id"]),
        net_receivable_usd=31.14,
        tier_pct=5.00,
        uncollectible_reserve_balance_usd=1.56,
    )

    entries = read_ledger(
        api, carrier_id=state["carrier_id"], reserve_bucket=RESERVE_BUCKET_UNCOLLECTIBLE
    )
    assert_money(entries[-1]["amount_usd"], -0.06)
    assert_money(entries[-1]["balance_after_usd"], 1.56)


def test_reconciliation_acceptance_documents_the_variance_without_a_credit(
    api, controller_headers
):
    """Accepting a variance records it and moves no money at all.

    PRD 3.10: "**Accepting** a variance instead documents it without posting money. The controller supplies an `acceptance_note`, the case moves `VARIANCE_IDENTIFIED → ACCEPTED`, `adjustment_amount_usd` stays unset, no invoice or carrier row is touched, and the case's `version` increments by 1."
    PRD 3.10: "Both figures are written to the case regardless of the outcome."
    PRD 2.11: "The reserve balances are outputs only. They never feed back into `open_receivable_usd` or `net_receivable_usd`, so a single pass reaches the fixed point and re-running the calculation on unchanged inputs produces no ledger entries at all."

    Design: Corner/endpoints/reconciliation_acceptance_documents_the_variance_without_a_credit
    """
    state = setup_issued_invoice(api)
    setup_reconciliation_case(api, state)

    accepted = validate_success(
        api.accept_reconciliation_case(
            state["case_id"],
            reconciliation_accept_payload(
                acceptance_note="Counterparty sample confirms our record count; the gap is their unbilled tandem leg"
            ),
            controller_headers,
        ),
        expected_status=200,
    )
    assert accepted["status"] == "ACCEPTED"
    assert_pct(accepted["minute_variance_pct"], VARIANCE_PCT)
    assert_money(accepted["amount_variance_usd"], VARIANCE_AMOUNT)
    assert accepted["adjustment_amount_usd"] is None
    assert accepted["agreed_minutes"] is None
    assert accepted["adjusted_at"] is None

    invoice = read_invoice(api, state["invoice_id"])
    assert_money(invoice["credited_amount_usd"], 0.00)
    assert_money(invoice["open_balance_usd"], RATED_TOTAL_PRELIMINARY)
    assert invoice["adjustment_count"] == 0

    _, meta = validate_paginated(
        api.list_reserve_ledger_entries(
            controller_headers,
            {
                "carrier_id": state["carrier_id"],
                "reserve_bucket": RESERVE_BUCKET_UNCOLLECTIBLE,
            },
        )
    )
    assert meta["total_count"] == 1
    carrier = read_carrier(api, state["carrier_id"])
    assert_money(carrier["uncollectible_reserve_balance_usd"], ISSUE_RESERVE)


def test_reconciliation_adjustment_needs_an_issued_invoice_to_carry_the_credit(
    api, controller_headers
):
    """A DRAFT invoice cannot carry the concession, so the adjustment conflicts.

    PRD 3.10: "The batch's access invoice must exist with `lifecycle_status` `ISSUED`, or the adjustment is refused with `ERR_INVOICE_NOT_ISSUED`, and that invoice's `payment_status` must not be `WRITTEN_OFF`."
    PRD 2.11: "Draft invoices carry no exposure and closed invoices have left the receivable set, so neither contributes to either base."

    Design: Corner/errors/reconciliation_adjustment_needs_an_issued_invoice_to_carry_the_credit
    """
    state = setup_draft_invoice(api)
    setup_reconciliation_case(api, state)
    assert state["case"]["status"] == "VARIANCE_IDENTIFIED"

    response = api.adjust_reconciliation_case(
        state["case_id"], reconciliation_adjust_payload(70.0), controller_headers
    )
    validate_error(response, ERR_INVOICE_NOT_ISSUED, expected_status=409)

    invoice = read_invoice(api, state["invoice_id"])
    assert invoice["lifecycle_status"] == "DRAFT"
    assert_money(invoice["credited_amount_usd"], 0.00)
    assert invoice["adjustment_count"] == 0

    case = read_reconciliation_case(api, state["case_id"])
    assert case["status"] == "VARIANCE_IDENTIFIED"
    assert case["adjustment_amount_usd"] is None

    carrier = read_carrier(api, state["carrier_id"])
    assert_money(carrier["uncollectible_reserve_balance_usd"], 0.00)


def test_rewinding_the_logical_clock_and_conceding_minutes_out_of_range_are_refused(
    api, admin_headers, controller_headers
):
    """Agreed minutes above our own figure and a backwards clock are both refused.

    PRD 3.10: "**Adjusting** the case settles on `agreed_minutes`, which must lie inside the closed interval spanned by the smaller and the larger of `our_minutes` and `counterparty_reported_minutes`, both edges included; a value outside that interval is refused with `ERR_AGREED_MINUTES_OUT_OF_RANGE`."
    PRD 2.5: "The clock is monotonic: a `target_utc` earlier than the current logical clock is refused with `ERR_CLOCK_MUST_ADVANCE` (HTTP 422)."

    Design: Corner/errors/rewinding_the_logical_clock_and_conceding_minutes_out_of_range_are_refused
    """
    state = setup_issued_invoice(api)
    setup_reconciliation_case(api, state)

    out_of_range = api.adjust_reconciliation_case(
        state["case_id"], reconciliation_adjust_payload(80.0), controller_headers
    )
    validate_error(out_of_range, ERR_AGREED_MINUTES_OUT_OF_RANGE, expected_status=422)

    rewind = api.set_clock(clock_payload(T_2026_07_01), admin_headers)
    validate_error(rewind, ERR_CLOCK_MUST_ADVANCE, expected_status=422)

    case = read_reconciliation_case(api, state["case_id"])
    assert case["status"] == "VARIANCE_IDENTIFIED"
    assert case["agreed_minutes"] is None

    invoice = read_invoice(api, state["invoice_id"])
    assert_money(invoice["credited_amount_usd"], 0.00)
    assert_money(invoice["open_balance_usd"], RATED_TOTAL_PRELIMINARY)


def test_reciprocal_settlement_outside_the_band_is_metered_and_netted(
    api, manager_headers
):
    """A 1.2167 traffic ratio leaves bill-and-keep and meters the thirteen-minute gap.

    PRD 3.7: "`inbound_minutes` is the sum of `total_billable_minutes` over the qualifying batches whose `direction` is `TERMINATING_TO_US`, and `outbound_minutes` is the same sum over those whose `direction` is `ORIGINATING_FROM_US`."
    PRD 3.7: "Otherwise `traffic_balance_ratio` is `inbound_minutes` divided by `outbound_minutes`, rounded half up to four decimal places. When that ratio falls within the bill-and-keep band — at least 0.9500 and at most 1.0500, both edges inclusive — the traffic is deemed balanced: `settlement_mode` is `BILL_AND_KEEP` and `net_settlement_usd` is 0.00. Outside that band, `settlement_mode` is `METERED` and `net_settlement_usd` is `inbound_minutes` less `outbound_minutes`, multiplied by the agreement's pinned `reciprocal_rate_per_mou_usd`, rounded half up to two decimal places."
    PRD 3.7: "The sign convention is that a positive figure means the counterparty owes us and a negative figure means we owe them. The read also echoes back the `reciprocal_rate_per_mou_usd` it applied."

    Design: Corner/calculations/reciprocal_settlement_outside_the_band_is_metered_and_netted
    """
    state = setup_effective_agreement_with_rated_batch(api)
    outbound = setup_outbound_rated_batch(api, state["carrier_id"])
    assert outbound["status"] == "RATED"
    assert_minutes(outbound["total_billable_minutes"], OUTBOUND_MINUTES)

    settlement = validate_success(
        api.get_reciprocal_settlement(state["agreement_id"], manager_headers),
        expected_status=200,
    )

    assert_minutes(settlement["inbound_minutes"], BILLABLE_MINUTES_TOTAL)
    assert_minutes(settlement["outbound_minutes"], OUTBOUND_MINUTES)
    assert_ratio(settlement["traffic_balance_ratio"], 1.2167)
    assert settlement["settlement_mode"] == "METERED"
    assert_rate(settlement["reciprocal_rate_per_mou_usd"], RECIPROCAL_RATE)
    assert_money(settlement["net_settlement_usd"], 0.80)


def test_settlement_ignores_batches_that_have_not_been_rated(
    api, analyst_headers, manager_headers
):
    """An unrated outbound batch keeps its minutes but contributes none to settlement.

    PRD 3.7: "It aggregates that agreement's carrier's usage batches whose `status` is `RATED` or `INVOICED`; batches still in `SUBMITTED` or `JURISDICTIONALIZED` are excluded because their minutes are not yet settled."
    PRD 3.7: "If `outbound_minutes` is zero, `traffic_balance_ratio` is null, `settlement_mode` is `UNDETERMINED` and `net_settlement_usd` is 0.00."
    PRD 3.7: "On acceptance the record's `billable_minutes` is computed immediately as its `duration_seconds` divided by 60 and rounded **up** to a whole number, its `jurisdiction`, `jurisdiction_source` and `rated_amount_usd` are left null, and the batch's `record_count` and `total_billable_minutes` increase accordingly with the batch's `version` incrementing by 1."

    Design: Corner/calculations/settlement_ignores_batches_that_have_not_been_rated
    """
    state = setup_effective_agreement_with_rated_batch(api)
    outbound = validate_success(
        api.create_usage_batch(
            usage_batch_payload(
                state["carrier_id"],
                period_start=T_2026_07_01,
                period_end=T_2026_07_25,
                direction="ORIGINATING_FROM_US",
                exchange_reference=BATCH_EXCHANGE_REFERENCE_OUT,
            ),
            analyst_headers,
        ),
        expected_status=201,
    )
    validate_success(
        api.append_call_detail_record(
            outbound["id"], local_cdr_payload(duration_seconds=3600), analyst_headers
        ),
        expected_status=201,
    )

    unrated = read_usage_batch(api, outbound["id"])
    assert unrated["status"] == "SUBMITTED"
    assert unrated["record_count"] == 1
    assert_minutes(
        unrated["total_billable_minutes"],
        OUTBOUND_MINUTES,
        "the unrated batch does hold minutes",
    )

    settlement = validate_success(
        api.get_reciprocal_settlement(state["agreement_id"], manager_headers),
        expected_status=200,
    )
    assert_minutes(settlement["inbound_minutes"], BILLABLE_MINUTES_TOTAL)
    assert_minutes(
        settlement["outbound_minutes"],
        0.0000,
        "a SUBMITTED batch contributes nothing to settlement",
    )
    assert settlement["traffic_balance_ratio"] is None
    assert settlement["settlement_mode"] == "UNDETERMINED"
    assert_money(settlement["net_settlement_usd"], 0.00)
