"""Access invoices: creation from a rated batch, issuance, payment and write-off."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_CARRIER_SCOPE_VIOLATION,
    ERR_INVALID_BATCH_STATE,
    ERR_INVALID_FACTOR_FILING_STATE,
    ERR_INVALID_INVOICE_STATE,
    ERR_INVALID_RECONCILIATION_STATE,
    ERR_INVOICE_NOT_YET_DUE,
    ERR_PAYMENT_EXCEEDS_BALANCE,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import (
    assert_invoice_dimensions,
    assert_ledger_entry,
    assert_money,
    assert_reserve_summary,
)
from test_helpers.constants import (
    RATED_TOTAL_PRELIMINARY,
    RESERVE_BUCKET_UNCOLLECTIBLE,
    T_2026_10_01,
)
from test_helpers.factories import (
    dispute_payload,
    factor_review_accept_payload,
    invoice_payload,
    payment_payload,
    reconciliation_adjust_payload,
    resolve_denied_payload,
    write_off_payload,
)
from test_helpers.fixtures import (
    advance_clock,
    bucket_entries,
    read_carrier,
    read_invoice,
    read_ledger,
    read_reconciliation_case,
    read_reserve_summary,
    read_usage_batch,
    setup_draft_invoice,
    setup_issued_invoice,
    setup_reconciliation_case,
    setup_second_carrier,
)
from test_helpers.test_users import (
    USER_ACCESS_BILLING_ANALYST,
    USER_DISPUTE_RESOLUTION_OFFICER,
    revenue_assurance_controller_headers,
)

OPEN_AFTER_PART_PAYMENT = 22.47
PART_PAYMENT = 10.00
ISSUE_RESERVE = 1.62
PART_PAYMENT_RESERVE = 0.45


def test_second_invoice_over_one_batch_is_refused(api, analyst_headers):
    """One rated batch supports exactly one access invoice.

    PRD 3.8: "The batch must be in `RATED` — any other pipeline state is refused with `ERR_INVALID_BATCH_STATE` — and at most one invoice may reference a given batch, with a second attempt refused as `ERR_BATCH_ALREADY_INVOICED`."
    PRD 3.8: "The source batch moves `RATED → INVOICED` and its `version` increments by 1."
    PRD 2.7: "The practical consequence is worth stating plainly. A regulatory cap breach surfaces as its own code rather than being masked by a later capacity or fiscal check, and a state conflict always beats a business-rule breach on the same request — a dispute in the wrong status is reported as an invalid dispute state, not as a credit-amount problem."
    PRD 3.8: "Creation snapshots the batch's figures onto the invoice: `billed_amount_usd` from the batch's `rated_amount_usd`, the three jurisdiction subtotals into the invoice's own `interstate_amount_usd`, `intrastate_amount_usd` and `local_amount_usd`, `rating_variant` mirroring the batch's, and `carrier_id` copied from the batch."

    Design: Corner/errors/second_invoice_over_one_batch_and_issuing_a_zero_amount_invoice_are_refused
    """
    state = setup_issued_invoice(api)
    batch_id = state["batch_id"]
    assert read_usage_batch(api, batch_id)["status"] == "INVOICED"

    # The first invoice moved the batch RATED -> INVOICED, so the state
    # precondition of PRD 2.7 band 9 fires ahead of the uniqueness rule of
    # band 10: the batch is no longer RATED.
    response = api.create_invoice(invoice_payload(batch_id), analyst_headers)
    validate_error(response, ERR_INVALID_BATCH_STATE, expected_status=409)

    _, meta = validate_paginated(
        api.list_invoices(analyst_headers, params={"usage_batch_id": batch_id})
    )
    assert meta["total_count"] == 1, "the refused second invoice must not be persisted"

    invoice = read_invoice(api, state["invoice_id"])
    assert_money(
        invoice["billed_amount_usd"], RATED_TOTAL_PRELIMINARY, "billed_amount_usd"
    )
    assert invoice["carrier_id"] == state["carrier_id"]


def test_write_off_before_the_invoice_due_date_is_refused(api, controller_headers):
    """A balance cannot be abandoned before the printed due date arrives.

    PRD 3.8: "the acting `X-User-ID` must differ from the invoice's `issued_by_user_id`, on pain of `ERR_SEGREGATION_OF_DUTIES`; and the logical clock must have reached the invoice's `due_date`, with a premature attempt refused as `ERR_INVOICE_NOT_YET_DUE`."
    PRD 2.11: "If it is at least twenty-five dollars but below two hundred and fifty dollars the percentage is 5.00."
    PRD 2.11: "`open_receivable_usd` is the sum of `open_balance_usd` over the carrier's access invoices whose `lifecycle_status` is `ISSUED` and whose `payment_status` is either `UNPAID` or `PARTIALLY_PAID`; each such invoice's `open_balance_usd` is its `billed_amount_usd` less its `credited_amount_usd` less its `paid_amount_usd`."

    Design: Corner/endpoints/write_off_before_the_invoice_due_date_is_refused
    """
    state = setup_issued_invoice(api)
    invoice_id = state["invoice_id"]

    response = api.write_off_invoice(invoice_id, write_off_payload(), controller_headers)
    validate_error(response, ERR_INVOICE_NOT_YET_DUE, expected_status=409)

    invoice = read_invoice(api, invoice_id)
    assert_invoice_dimensions(invoice, "ISSUED", "UNPAID", "NONE")
    assert invoice["written_off_at"] is None

    summary = read_reserve_summary(api, state["carrier_id"])
    assert_reserve_summary(
        summary,
        open_receivable_usd=RATED_TOTAL_PRELIMINARY,
        tier_pct=5.00,
        uncollectible_reserve_balance_usd=ISSUE_RESERVE,
    )

    entries = bucket_entries(
        read_ledger(api, carrier_id=state["carrier_id"]), RESERVE_BUCKET_UNCOLLECTIBLE
    )
    assert len(entries) == 1, "the refused write-off appended no ledger movement"


def test_invoice_closes_when_the_final_payment_lands_with_no_open_dispute(api):
    """The closing payment drives payment_status PAID and derives lifecycle CLOSED.

    PRD 3.8: "Where the payment lands determines the resulting dimension move: an amount strictly less than the open balance moves `payment_status` `UNPAID → PARTIALLY_PAID`, while an amount exactly equal to the open balance moves it `UNPAID → PAID` when no earlier payment had been applied and `PARTIALLY_PAID → PAID` when one had."
    PRD 2.10: "Where dimensions do interact, the interaction is a **derivation**, stated once and applied consistently: once an invoice is `ISSUED`, its `lifecycle_status` becomes `CLOSED` as soon as `payment_status` has reached either `PAID` or `WRITTEN_OFF` **and** `dispute_status` is either `NONE` or `RESOLVED`."
    PRD 2.11: "If that net figure is zero or negative the applicable reserve percentage is zero."
    PRD 3.10: "Because entries are never rewritten, the last entry in a bucket's history always carries that bucket's current `balance_after_usd`, and the entries between any two points sum exactly to the difference between their balances."

    Design: Corner/state_machines/invoice_closes_when_the_final_payment_lands_with_no_open_dispute
    """
    state = setup_issued_invoice(api)
    invoice_id = state["invoice_id"]
    rep_headers = state["rep_headers"]

    part_paid = validate_success(
        api.apply_payment(invoice_id, payment_payload(PART_PAYMENT), rep_headers),
        expected_status=200,
    )
    assert_money(part_paid["open_balance_usd"], OPEN_AFTER_PART_PAYMENT)

    response = api.apply_payment(
        invoice_id,
        payment_payload(
            OPEN_AFTER_PART_PAYMENT, remittance_reference="WIRE-2026-09-01-B"
        ),
        rep_headers,
    )
    invoice = validate_success(response, expected_status=200)

    assert invoice["payment_status"] == "PAID"
    assert_money(invoice["paid_amount_usd"], RATED_TOTAL_PRELIMINARY, "paid_amount_usd")
    assert_money(invoice["open_balance_usd"], 0.00, "open_balance_usd")
    assert invoice["lifecycle_status"] == "CLOSED", (
        "the lifecycle move is derived, never posted directly"
    )

    summary = read_reserve_summary(api, state["carrier_id"])
    assert_reserve_summary(
        summary,
        open_receivable_usd=0.00,
        net_receivable_usd=0.00,
        tier_pct=0.00,
        uncollectible_reserve_balance_usd=0.00,
    )

    entries = bucket_entries(
        read_ledger(api, carrier_id=state["carrier_id"]), RESERVE_BUCKET_UNCOLLECTIBLE
    )
    assert_ledger_entry(
        entries[-1],
        amount_usd=-PART_PAYMENT_RESERVE,
        balance_after_usd=0.00,
        reserve_bucket=RESERVE_BUCKET_UNCOLLECTIBLE,
    )
    signed_sum = sum(round(float(entry["amount_usd"]), 2) for entry in entries)
    assert round(signed_sum, 2) == 0.00, (
        "the signed uncollectible movements net to the current balance of zero"
    )


def test_write_off_removes_the_receivable_from_both_reserve_bases(api, controller_headers):
    """A written-off invoice leaves the receivable set and zeroes the reserve.

    PRD 3.8: "On success the caller's `write_off_reason` is recorded, `payment_status` moves `UNPAID → WRITTEN_OFF` or `PARTIALLY_PAID → WRITTEN_OFF`, `written_off_at` is stamped from the logical clock, and the remaining `open_balance_usd` is removed from the receivable set."
    PRD 3.8: "As with payment, `lifecycle_status` auto-moves to `CLOSED` when `dispute_status` is `NONE` or `RESOLVED`, and the invoice's and the carrier's `version` each increment by 1."
    PRD 2.11: "Draft invoices carry no exposure and closed invoices have left the receivable set, so neither contributes to either base."
    PRD 2.11: "For each of the two reserve buckets whose balance actually moved, a reserve ledger entry is appended carrying `amount_usd` equal to the new balance minus the old balance — positive when the reserve grows, negative when it releases — and `balance_after_usd` equal to the new balance."

    Design: Corner/state_machines/write_off_removes_the_receivable_from_both_reserve_bases
    """
    state = setup_issued_invoice(api)
    invoice_id = state["invoice_id"]
    carrier_id = state["carrier_id"]
    advance_clock(api, T_2026_10_01)

    response = api.write_off_invoice(invoice_id, write_off_payload(), controller_headers)
    written_off = validate_success(response, expected_status=200)

    assert written_off["payment_status"] == "WRITTEN_OFF"
    assert written_off["written_off_at"] == T_2026_10_01
    assert written_off["lifecycle_status"] == "CLOSED"
    assert_money(
        written_off["open_balance_usd"],
        RATED_TOTAL_PRELIMINARY,
        "open_balance_usd is retained as the written-off amount",
    )

    summary = read_reserve_summary(api, carrier_id)
    assert_reserve_summary(
        summary,
        open_receivable_usd=0.00,
        disputed_receivable_usd=0.00,
        net_receivable_usd=0.00,
        tier_pct=0.00,
        uncollectible_reserve_balance_usd=0.00,
    )

    entries = bucket_entries(
        read_ledger(api, carrier_id=carrier_id), RESERVE_BUCKET_UNCOLLECTIBLE
    )
    assert_ledger_entry(
        entries[0],
        source_event="INVOICE_CREATED",
        amount_usd=ISSUE_RESERVE,
        balance_after_usd=ISSUE_RESERVE,
        reserve_bucket=RESERVE_BUCKET_UNCOLLECTIBLE,
    )
    assert_ledger_entry(entries[-1], balance_after_usd=0.00)
    carrier = read_carrier(api, carrier_id)
    assert_money(
        carrier["uncollectible_reserve_balance_usd"],
        entries[-1]["balance_after_usd"],
        "uncollectible_reserve_balance_usd",
    )


def test_payment_response_already_shows_the_recomputed_invoice_position(api):
    """The payment response body itself carries the recomputed balance and reserve.

    PRD 3.8: "In the first hop the invoice's `paid_amount_usd` increases by the amount and `open_balance_usd` is recomputed."
    PRD 3.8: "Because the open balance changed, the second hop re-runs the reserve recomputation of §2.11, rewriting the carrier's `open_receivable_usd` and `uncollectible_reserve_balance_usd` — and when the payment drives the balance to 0.00 the invoice leaves the receivable input set entirely, so both reserve balances are rebuilt without it."
    PRD 2.11: "If it is positive but below twenty-five dollars the percentage is 2.00."
    PRD 2.10: "An access invoice carries three such dimensions: `lifecycle_status` for the document, `payment_status` for settlement, and `dispute_status` for the dispute position."

    Design: Corner/consistency_model/payment_response_already_shows_the_recomputed_invoice_position
    """
    state = setup_issued_invoice(api)
    invoice_id = state["invoice_id"]

    response = api.apply_payment(
        invoice_id,
        payment_payload(PART_PAYMENT, remittance_reference="REMIT-2026-09-0001"),
        state["rep_headers"],
    )
    posted = validate_success(response, expected_status=200)

    assert_money(posted["paid_amount_usd"], PART_PAYMENT, "paid_amount_usd")
    assert_money(
        posted["open_balance_usd"], OPEN_AFTER_PART_PAYMENT, "open_balance_usd"
    )
    assert posted["payment_status"] == "PARTIALLY_PAID"
    assert_money(
        posted["billed_amount_usd"], RATED_TOTAL_PRELIMINARY, "billed_amount_usd"
    )
    assert posted["lifecycle_status"] == "ISSUED"

    reread = read_invoice(api, invoice_id)
    for field in (
        "paid_amount_usd",
        "open_balance_usd",
        "payment_status",
        "billed_amount_usd",
        "lifecycle_status",
    ):
        assert reread[field] == posted[field], (
            f"{field} differs between the write response and the subsequent read"
        )

    summary = read_reserve_summary(api, state["carrier_id"])
    assert_reserve_summary(
        summary,
        open_receivable_usd=OPEN_AFTER_PART_PAYMENT,
        tier_pct=2.00,
        uncollectible_reserve_balance_usd=PART_PAYMENT_RESERVE,
    )


def test_billing_pipeline_state_conflicts_each_report_their_own_id(
    api, analyst_headers, controller_headers
):
    """A second review, a re-rate and an unevaluated adjustment each conflict distinctly.

    PRD 3.6: "A decision of `ACCEPT` moves the filing to `ACCEPTED` and its `effective_piu_pct` and `effective_plu_pct` resolve to the reported values; it is permitted from `REPORTED` and from `AUDITED`."
    PRD 3.6: "A review requested from a status where the chosen decision has no transition is refused with `ERR_INVALID_FACTOR_FILING_STATE`."
    PRD 3.7: "Jurisdiction determination is refused unless the batch is `SUBMITTED`, and rating is refused unless it is `JURISDICTIONALIZED`; in both cases the refusal is `ERR_INVALID_BATCH_STATE`."
    PRD 3.10: "Evaluation requires `OPEN`; adjustment and acceptance both require `VARIANCE_IDENTIFIED`."
    PRD 2.7: "A regulatory cap breach surfaces as its own code rather than being masked by a later capacity or fiscal check, and a state conflict always beats a business-rule breach on the same request — a dispute in the wrong status is reported as an invalid dispute state, not as a credit-amount problem."

    Design: Corner/errors/billing_pipeline_state_conflicts_each_report_their_own_id
    """
    state = setup_draft_invoice(api)
    filing_id = state["factor_filing"]["id"]
    accepted = validate_success(
        api.review_factor_filing(
            filing_id, factor_review_accept_payload(), analyst_headers
        ),
        expected_status=200,
    )
    assert accepted["status"] == "ACCEPTED"
    setup_reconciliation_case(api, state, evaluate=False)

    second_review = api.review_factor_filing(
        filing_id, factor_review_accept_payload(), analyst_headers
    )
    validate_error(second_review, ERR_INVALID_FACTOR_FILING_STATE, expected_status=409)

    re_rate = api.rate_batch(state["batch_id"], {}, analyst_headers)
    validate_error(re_rate, ERR_INVALID_BATCH_STATE, expected_status=409)

    premature_adjust = api.adjust_reconciliation_case(
        state["case_id"], reconciliation_adjust_payload(70.0000), controller_headers
    )
    validate_error(
        premature_adjust, ERR_INVALID_RECONCILIATION_STATE, expected_status=409
    )

    batch = read_usage_batch(api, state["batch_id"])
    assert_money(batch["rated_amount_usd"], RATED_TOTAL_PRELIMINARY, "rated_amount_usd")
    invoice = read_invoice(api, state["invoice_id"])
    assert_money(
        invoice["billed_amount_usd"], RATED_TOTAL_PRELIMINARY, "billed_amount_usd"
    )

    case = read_reconciliation_case(api, state["case_id"])
    assert case["status"] == "OPEN"
    assert case["adjustment_amount_usd"] is None


def test_invoice_issuer_cannot_write_off_that_invoice(api, controller_headers):
    """Segregation of duties blocks the issuer even at the due instant.

    PRD 2.9: "The user whose `X-User-ID` was stamped into an invoice's `issued_by_user_id` at issuance may neither resolve a billing dispute filed against that invoice nor write that invoice's balance off, even while holding the `DisputeResolutionOfficer` or `RevenueAssuranceController` role that otherwise authorises the operation."
    PRD 2.9: "In both cases the acting `X-User-ID` must differ from the invoice's `issued_by_user_id`; when it does not, the request is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD 2.7: "7. **Segregation of duties** — see §2.9, else `ERR_SEGREGATION_OF_DUTIES`."
    PRD 3.8: "On success the caller's `write_off_reason` is recorded, `payment_status` moves `UNPAID → WRITTEN_OFF` or `PARTIALLY_PAID → WRITTEN_OFF`, `written_off_at` is stamped from the logical clock, and the remaining `open_balance_usd` is removed from the receivable set."

    Design: Corner/rbac/invoice_issuer_cannot_write_off_that_invoice
    """
    state = setup_issued_invoice(api)
    invoice_id = state["invoice_id"]
    carrier_id = state["carrier_id"]
    assert state["invoice"]["issued_by_user_id"] == USER_ACCESS_BILLING_ANALYST
    advance_clock(api, T_2026_10_01)

    as_issuer = api.write_off_invoice(
        invoice_id,
        write_off_payload(),
        revenue_assurance_controller_headers(USER_ACCESS_BILLING_ANALYST),
    )
    validate_error(as_issuer, ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    response = api.write_off_invoice(invoice_id, write_off_payload(), controller_headers)
    written_off = validate_success(response, expected_status=200)

    assert written_off["payment_status"] == "WRITTEN_OFF"
    assert written_off["lifecycle_status"] == "CLOSED"
    assert written_off["written_off_at"] == T_2026_10_01

    carrier = read_carrier(api, carrier_id)
    assert_money(
        carrier["uncollectible_reserve_balance_usd"],
        0.00,
        "uncollectible_reserve_balance_usd",
    )
    assert_reserve_summary(
        read_reserve_summary(api, carrier_id),
        open_receivable_usd=0.00,
        net_receivable_usd=0.00,
        tier_pct=0.00,
    )


def test_carrier_representative_cannot_read_another_carriers_invoice(
    api, carrier_rep_headers
):
    """The ownership comparison guards reads, and only the acting identity blocks it.

    PRD 2.1: "That comparison reaches through the graph: an agreement's carrier, a trunk group's agreement's carrier, a usage batch's carrier, an invoice's carrier, a dispute's invoice's carrier and a reconciliation case's batch's carrier are all in scope."
    PRD 2.1: "A `CarrierRepresentative` acting on a resource that belongs to a different carrier is refused with `ERR_CARRIER_SCOPE_VIOLATION` (HTTP 403)."
    PRD 2.1: "This check applies to every endpoint that lists `CarrierRepresentative` among its authorised roles, reads as well as writes."
    PRD 2.7: "6. **Carrier scope** — the `CarrierRepresentative` ownership comparison of §2.1, else `ERR_CARRIER_SCOPE_VIOLATION`."

    Design: Corner/rbac/carrier_representative_cannot_read_another_carriers_invoice
    """
    state = setup_issued_invoice(api)
    invoice_id = state["invoice_id"]
    owner_id = state["carrier_id"]
    outsider = setup_second_carrier(api)

    denied = api.get_invoice(invoice_id, carrier_rep_headers(outsider["id"]))
    validate_error(denied, ERR_CARRIER_SCOPE_VIOLATION, expected_status=403)

    allowed = api.get_invoice(invoice_id, carrier_rep_headers(owner_id))
    invoice = validate_success(allowed, expected_status=200)
    assert_money(
        invoice["billed_amount_usd"], RATED_TOTAL_PRELIMINARY, "billed_amount_usd"
    )
    assert_money(
        invoice["open_balance_usd"], RATED_TOTAL_PRELIMINARY, "open_balance_usd"
    )
    assert invoice["carrier_id"] == owner_id
    assert invoice["carrier_id"] != outsider["id"]


def test_payment_on_a_draft_invoice_reports_the_state_conflict_not_the_overpayment(api):
    """A never-issued invoice reports the state conflict ahead of the fiscal breach.

    PRD 3.8: "The invoice's `lifecycle_status` must be `ISSUED` and its `payment_status` must be `UNPAID` or `PARTIALLY_PAID`; an invoice already `PAID` or `WRITTEN_OFF` accepts no further payment and is refused with `ERR_INVALID_INVOICE_STATE`."
    PRD 2.7: "9. **State preconditions** — the target row is in a status from which the requested transition exists, yielding the entity-specific conflict codes catalogued in §3."
    PRD 2.7: "Fiscal amount checks are always last: the empty-invoice refusal, the overpayment refusal, the dispute-amount ceiling and the credit-amount decision match."
    PRD 2.11: "Draft invoices carry no exposure and closed invoices have left the receivable set, so neither contributes to either base."

    Design: Difficulty/priority_pair_validation_conflict/payment_on_draft_invoice_state_beats_fiscal_overpayment
    """
    state = setup_draft_invoice(api)
    invoice_id = state["invoice_id"]
    carrier_id = state["carrier_id"]

    response = api.apply_payment(
        invoice_id,
        payment_payload(999.99, remittance_reference="WIRE-2026-09-01-OVER"),
        state["rep_headers"],
    )
    validate_error(response, ERR_INVALID_INVOICE_STATE, expected_status=409)

    invoice = read_invoice(api, invoice_id)
    assert_invoice_dimensions(invoice, "DRAFT", "UNPAID", "NONE")
    assert_money(invoice["paid_amount_usd"], 0.00, "paid_amount_usd")

    carrier = read_carrier(api, carrier_id)
    assert_money(carrier["open_receivable_usd"], 0.00, "open_receivable_usd")
    assert_money(
        carrier["uncollectible_reserve_balance_usd"],
        0.00,
        "uncollectible_reserve_balance_usd",
    )

    assert read_ledger(api, carrier_id=carrier_id) == [], (
        "a draft invoice books no reserve movement at all"
    )


def test_overpayment_on_an_issued_invoice_reports_the_fiscal_refusal(api):
    """Once the state gate is satisfied the same amount surfaces the overpayment code.

    PRD 3.8: "The amount may not exceed the invoice's current `open_balance_usd`; overpayment is refused rather than credited, with `ERR_PAYMENT_EXCEEDS_BALANCE`."
    PRD 2.7: "Fiscal amount checks are always last: the empty-invoice refusal, the overpayment refusal, the dispute-amount ceiling and the credit-amount decision match."
    PRD 3.8: "In the first hop the invoice's `paid_amount_usd` increases by the amount and `open_balance_usd` is recomputed."

    Design: Difficulty/priority_pair_validation_conflict/payment_on_draft_invoice_state_beats_fiscal_overpayment
    """
    state = setup_issued_invoice(api)
    invoice_id = state["invoice_id"]

    response = api.apply_payment(
        invoice_id,
        payment_payload(999.99, remittance_reference="WIRE-2026-09-01-OVER"),
        state["rep_headers"],
    )
    validate_error(response, ERR_PAYMENT_EXCEEDS_BALANCE, expected_status=422)

    invoice = read_invoice(api, invoice_id)
    assert_invoice_dimensions(invoice, "ISSUED", "UNPAID", "NONE")
    assert_money(invoice["paid_amount_usd"], 0.00, "paid_amount_usd")
    assert_money(
        invoice["open_balance_usd"], RATED_TOTAL_PRELIMINARY, "open_balance_usd"
    )

    assert_reserve_summary(
        read_reserve_summary(api, state["carrier_id"]),
        open_receivable_usd=RATED_TOTAL_PRELIMINARY,
        uncollectible_reserve_balance_usd=ISSUE_RESERVE,
    )


def test_invoice_payment_and_dispute_dimensions_move_independently(api, analyst_headers):
    """A part-paid invoice takes a dispute without disturbing its payment dimension.

    PRD 2.10: "An invoice can be `ISSUED`, `PARTIALLY_PAID` and `DISPUTED` simultaneously."
    PRD 3.9: "The second hop increases the invoice's `disputed_amount_usd` by the new dispute's `disputed_amount_usd` and moves the invoice's `dispute_status` to `DISPUTED` — from `NONE` for a first dispute, or from `RESOLVED` for a re-dispute filed inside the window, which requires the clock to be at or before `dispute_deadline_at` and leaves `payment_status` and any partial payments already applied entirely untouched."
    PRD 3.9: "The new dispute lands in `status` `SUBMITTED` with `escalation_round` at 0, `credited_amount_usd` at 0.00, and `resolution_note`, `resolved_at` and `resolved_by_user_id` all null."
    PRD 3.9: "Its clock is set from the reason code: `sla_days` is **30** calendar days for `RATE_APPLICATION`, **60** for `JURISDICTION_FACTOR` and **45** for `USAGE_DISCREPANCY`."

    Design: Difficulty/non_linear_state_machine/invoice_payment_and_dispute_dimensions_move_independently
    """
    state = setup_issued_invoice(api)
    invoice_id = state["invoice_id"]
    rep_headers = state["rep_headers"]

    part_paid = validate_success(
        api.apply_payment(invoice_id, payment_payload(PART_PAYMENT), rep_headers),
        expected_status=200,
    )
    assert_invoice_dimensions(part_paid, "ISSUED", "PARTIALLY_PAID", "NONE")
    assert_money(
        part_paid["open_balance_usd"], OPEN_AFTER_PART_PAYMENT, "open_balance_usd"
    )

    dispute = validate_success(
        api.create_dispute(
            dispute_payload(
                invoice_id,
                disputed_amount_usd=5.00,
                supporting_detail=(
                    "Interstate rate applied to 2 minutes that signalled intrastate"
                ),
            ),
            rep_headers,
        ),
        expected_status=201,
    )
    assert dispute["status"] == "SUBMITTED"
    assert dispute["sla_days"] == 30
    assert dispute["escalation_round"] == 0

    invoice = read_invoice(api, invoice_id)
    assert_invoice_dimensions(invoice, "ISSUED", "PARTIALLY_PAID", "DISPUTED")
    assert_money(invoice["disputed_amount_usd"], 5.00, "disputed_amount_usd")
    assert_money(invoice["paid_amount_usd"], PART_PAYMENT, "paid_amount_usd")
    assert_money(
        invoice["open_balance_usd"], OPEN_AFTER_PART_PAYMENT, "open_balance_usd"
    )


def test_denied_dispute_resolution_leaves_the_payment_dimension_untouched(
    api, officer_headers
):
    """Closing the dispute dimension moves no money and reopens no payment question.

    PRD 3.9: "A **denied** dispute moves `UNDER_REVIEW → RESOLVED_DENIED`."
    PRD 3.9: "Its `resolved_at` and `resolved_by_user_id` are likewise stamped and no credit is posted; the invoice's `disputed_amount_usd` is reduced by the dispute's `disputed_amount_usd` and its `dispute_status` moves `DISPUTED → RESOLVED`; and a `DISPUTE_RELEASE` reserve ledger entry is appended for the released provision."
    PRD 2.10: "An access invoice carries three such dimensions: `lifecycle_status` for the document, `payment_status` for settlement, and `dispute_status` for the dispute position."
    PRD 2.11: "If it is positive but below twenty-five dollars the percentage is 2.00."

    Design: Difficulty/non_linear_state_machine/invoice_payment_and_dispute_dimensions_move_independently
    """
    state = setup_issued_invoice(api)
    invoice_id = state["invoice_id"]
    rep_headers = state["rep_headers"]
    validate_success(
        api.apply_payment(invoice_id, payment_payload(PART_PAYMENT), rep_headers),
        expected_status=200,
    )
    dispute = validate_success(
        api.create_dispute(
            dispute_payload(invoice_id, disputed_amount_usd=5.00), rep_headers
        ),
        expected_status=201,
    )
    validate_success(
        api.acknowledge_dispute(dispute["id"], {}, officer_headers), expected_status=200
    )

    response = api.resolve_dispute(
        dispute["id"], resolve_denied_payload(), officer_headers
    )
    resolved = validate_success(response, expected_status=200)

    assert resolved["status"] == "RESOLVED_DENIED"
    assert_money(resolved["credited_amount_usd"], 0.00, "credited_amount_usd")
    assert resolved["resolved_by_user_id"] == USER_DISPUTE_RESOLUTION_OFFICER

    invoice = read_invoice(api, invoice_id)
    assert_invoice_dimensions(invoice, "ISSUED", "PARTIALLY_PAID", "RESOLVED")
    assert_money(invoice["disputed_amount_usd"], 0.00, "disputed_amount_usd")
    assert_money(invoice["credited_amount_usd"], 0.00, "credited_amount_usd")
    assert_money(invoice["paid_amount_usd"], PART_PAYMENT, "paid_amount_usd")
    assert_money(
        invoice["open_balance_usd"], OPEN_AFTER_PART_PAYMENT, "open_balance_usd"
    )

    carrier = read_carrier(api, state["carrier_id"])
    assert_money(carrier["net_receivable_usd"], OPEN_AFTER_PART_PAYMENT, "net_receivable_usd")
    assert_money(
        carrier["uncollectible_reserve_balance_usd"],
        PART_PAYMENT_RESERVE,
        "uncollectible_reserve_balance_usd",
    )
