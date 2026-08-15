"""Account analysis: earnings-credit variants, statement composition, SLA
threshold arithmetic, net-due flooring under error credits, and settle OCC."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_item,
    add_live_customer_to_bank,
    assert_net_amount_non_negative,
    balance_batch_ok,
    begin_capture,
    capture_and_accept_items,
    capture_item,
    close_batch,
    confirm_incident,
    create_bank,
    create_batch,
    decide_exception_ok,
    file_error_credit,
    fulfill_image_request,
    list_cycles,
    list_line_items,
    raise_exception,
    report_incident,
    run_close_analysis_cycle_at_month_end,
    run_close_business_day,
    settle_batch,
    settle_cycle,
    setup_active_agreement,
    setup_live_lockbox,
    validate_error,
    validate_paginated,
    validate_success,
    create_image_request_payload,
    make_customer_operator_headers,
)

BILLING_SPEC = TEST_USERS["billing_specialist_headers"]
BILLING_APPR = TEST_USERS["billing_approver_headers"]


def _finalized_cycle(ws):
    """Return the first (oldest) cycle after a cycle close — the FINALIZED
    one; a fresh OPEN cycle sorts after it by created_at."""
    return list_cycles(ws)[0]


def _post_settled_batch(ws, total_cents, reference):
    """One SAME_DAY item carried all the way to ACKED so the business-day
    close settles the batch and credits the collected-balance accumulator."""
    batch = create_batch(ws, batch_reference=reference,
                         declared_item_count=1, declared_total_cents=total_cents)
    begin_capture(ws, batch["id"])
    item = capture_item(ws, batch["id"], check_number="9001",
                        amount_cents=total_cents)
    accept_item(ws, batch["id"], item["id"])
    balance_batch_ok(ws, batch["id"])
    close_batch(ws, batch["id"], operator_id="lock-op-2")
    settle_batch(ws, batch["id"])
    return batch


def _setup_two_customer_ecr_scenario(api):
    """One bank (default ECR 100bp); C1 without an override, C2 with an
    honored 300bp override; both settle a $36,000 SAME_DAY item on day one and
    close their cycles on the same close."""
    bank = create_bank(default_earnings_credit_rate_bp=100,
                       sla_credit_breach_threshold_bp=200)
    ws1 = add_live_customer_to_bank(
        bank,
        customer_overrides={"legal_name": "Acme One", "tax_id": "12-1111111",
                            "deposit_account_number": "DDA-2001"},
        agreement_overrides={"agreement_number": "AGR-C1",
                             "ecr_override_allowed": False,
                             "monthly_maintenance_fee_cents": 100000},
        site_code="S-C1")
    ws2 = add_live_customer_to_bank(
        bank,
        customer_overrides={"legal_name": "Acme Two", "tax_id": "12-2222222",
                            "deposit_account_number": "DDA-2002"},
        agreement_overrides={"agreement_number": "AGR-C2",
                             "ecr_override_allowed": True,
                             "earnings_credit_rate_bp": 300,
                             "monthly_maintenance_fee_cents": 100000},
        site_code="S-C2")
    _post_settled_batch(ws1, 3600000, "B-C1")
    _post_settled_batch(ws2, 3600000, "B-C2")
    # The day closes: both batches settle and each accumulator gains
    # 3,600,000 cents. The cycle close is gated on cycle_end_date ==
    # current_business_date (PRD §3.7), so the fixture advances the business
    # date to the cycle end (2026-08-31) before closing; the accumulator is
    # unchanged by the extra closes since nothing else settles.
    run_close_business_day({"bank": bank})
    run_close_analysis_cycle_at_month_end({"bank": bank})
    return bank, ws1, ws2


def _first_cycle(api, bank, ws):
    data, _meta = validate_paginated(
        api.list_analysis_cycles(bank["id"], ws["customer"]["id"],
                                 BILLING_SPEC))
    return data[0]


class TestEarningsCreditVariants:
    def test_bank_default_rate_applies_when_override_not_allowed(self, api):
        """PRD §3.7: "`earnings_credit_cents` — the rate is the agreement's
        `earnings_credit_rate_bp` when `ecr_override_allowed` is true and the
        override is set, and the bank's `default_earnings_credit_rate_bp`
        otherwise. The raw credit is the average collected balance multiplied
        by the rate and by the days elapsed, divided by 360 and by the 10,000
        basis-point denominator, then rounded half-up to whole cents, floored
        at zero, and capped at `gross_service_charges_cents` — the bank never
        pays the customer for excess credit."

        Design: Difficulty/dual_variant_calc/earnings_credit_override_vs_bank_default_on_customer_billing
        """
        bank, ws1, _ws2 = _setup_two_customer_ecr_scenario(api)
        cycle1 = _first_cycle(api, bank, ws1)
        # accumulator 3,600,000 over 21 elapsed days at the bank-wide 100bp:
        # avg = round_half_up(3,600,000/21) = 171,429; credit =
        # round_half_up(171,429 * 100 * 21 / (360 * 10,000)) = 100 cents.
        assert cycle1["earnings_credit_cents"] == 100
        assert cycle1["gross_service_charges_cents"] == 100000

    def test_agreement_override_rate_shadows_bank_default(self, api):
        """PRD §3.7: "the rate is the agreement's `earnings_credit_rate_bp`
        when `ecr_override_allowed` is true and the override is set, and the
        bank's `default_earnings_credit_rate_bp` otherwise."
        PRD §3.2: "The override is honored at calculation time only when
        `ecr_override_allowed` is true; that flag defaults to false, and a
        disallowed override is silently ignored when the earnings credit is
        computed."

        Design: Difficulty/dual_variant_calc/earnings_credit_override_vs_bank_default_on_customer_billing
        """
        bank, ws1, ws2 = _setup_two_customer_ecr_scenario(api)
        cycle1 = _first_cycle(api, bank, ws1)
        cycle2 = _first_cycle(api, bank, ws2)
        # Same balance and days, but the honored 300bp override triples the
        # credit: round_half_up(171,429 * 300 * 21 / (360 * 10,000)) = 300.
        assert cycle2["earnings_credit_cents"] == 300
        assert cycle2["earnings_credit_cents"] != cycle1["earnings_credit_cents"]


class TestGrossServiceCharges:
    def _setup_cycle_with_mixed_activity(self, api):
        ws = setup_live_lockbox(agreement_overrides={
            "monthly_maintenance_fee_cents": 33333,
            "per_item_capture_fee_cents": 7,
            "per_exception_decision_fee_cents": 13,
            "per_image_retrieval_fee_cents": 17,
        })
        batch = create_batch(ws, batch_reference="B1", declared_item_count=5,
                             declared_total_cents=50000)
        begin_capture(ws, batch["id"])
        items = [capture_item(ws, batch["id"], check_number=str(i + 1),
                              amount_cents=10000) for i in range(5)]
        # Three straight accepts.
        for item in items[:3]:
            accept_item(ws, batch["id"], item["id"])
        # Two exceptions, both decisioned PAY.
        for item in items[3:]:
            exception = raise_exception(ws, batch["id"], item["id"],
                                        default_decision="PAY")
            decide_exception_ok(ws, exception["id"], "PAY")
        # One fulfilled image retrieval.
        resp = api.create_image_request(
            ws["bank"]["id"], ws["customer"]["id"],
            create_image_request_payload(items[0]["id"]),
            make_customer_operator_headers(ws["customer"]["id"]))
        image_request = validate_success(resp, 201)
        fulfill_image_request(ws, image_request["id"])
        run_close_business_day(ws)
        run_close_analysis_cycle_at_month_end(
            ws, customer_id=ws["customer"]["id"])
        return ws

    def test_gross_sums_per_line_amounts(self, api):
        """PRD §3.7: "`gross_service_charges_cents` — the sum of four charges:
        the flat `monthly_maintenance_fee_cents`; `accepted_item_count`
        multiplied by `per_item_capture_fee_cents`; `exception_decision_count`
        multiplied by `per_exception_decision_fee_cents`; and
        `image_retrieval_fulfilled_count` multiplied by
        `per_image_retrieval_fee_cents`."
        PRD §3.7: "The counters themselves accrue through the cycle:
        `accepted_item_count` counts items that moved into `ACCEPTED` or
        `DECISIONED_PAY`, `exception_decision_count` counts exceptions that
        reached `DECIDED` or `AUTO_DECISIONED`, and
        `image_retrieval_fulfilled_count` counts requests fulfilled."

        Design: Difficulty/combinatorial_formula/gross_service_charges_per_line_rounding_then_sum
        """
        ws = self._setup_cycle_with_mixed_activity(api)
        cycle = _finalized_cycle(ws)
        # 3 accepts + 2 decisioned PAY = 5 captures; 2 decisions; 1 image.
        assert cycle["accepted_item_count"] == 5
        assert cycle["exception_decision_count"] == 2
        assert cycle["image_retrieval_fulfilled_count"] == 1
        # 33333 + 5*7 + 2*13 + 1*17 = 33333 + 35 + 26 + 17.
        assert cycle["gross_service_charges_cents"] == 33411

    def test_statement_line_items_compose_the_gross_total(self, api):
        """PRD §3.7: "The close also emits the statement's AnalysisLineItems —
        `MAINTENANCE` with `quantity` one; `PER_ITEM_CAPTURE`,
        `PER_EXCEPTION_DECISION`, and `PER_IMAGE_RETRIEVAL` with quantities
        taken from the cycle counters; each line's `unit_price_cents` copied
        from the agreement at close and its `extended_amount_cents` equal to
        `quantity` multiplied by `unit_price_cents`".
        PRD §3.7: "Each line is rounded half-up to whole cents first, and only
        then are the lines summed — never the reverse."

        Design: Difficulty/combinatorial_formula/gross_service_charges_per_line_rounding_then_sum
        """
        ws = self._setup_cycle_with_mixed_activity(api)
        cycle = _finalized_cycle(ws)
        lines = list_line_items(ws, cycle["id"])
        by_kind = {line["line_kind"]: line for line in lines}
        assert by_kind["MAINTENANCE"]["quantity"] == 1
        assert by_kind["MAINTENANCE"]["unit_price_cents"] == 33333
        assert by_kind["MAINTENANCE"]["extended_amount_cents"] == 33333
        assert by_kind["PER_ITEM_CAPTURE"]["quantity"] == 5
        assert by_kind["PER_ITEM_CAPTURE"]["unit_price_cents"] == 7
        assert by_kind["PER_ITEM_CAPTURE"]["extended_amount_cents"] == 35
        assert by_kind["PER_EXCEPTION_DECISION"]["quantity"] == 2
        assert by_kind["PER_EXCEPTION_DECISION"]["unit_price_cents"] == 13
        assert by_kind["PER_EXCEPTION_DECISION"]["extended_amount_cents"] == 26
        assert by_kind["PER_IMAGE_RETRIEVAL"]["quantity"] == 1
        assert by_kind["PER_IMAGE_RETRIEVAL"]["unit_price_cents"] == 17
        assert by_kind["PER_IMAGE_RETRIEVAL"]["extended_amount_cents"] == 17
        total = sum(line["extended_amount_cents"] for line in lines)
        assert total == cycle["gross_service_charges_cents"] == 33411


class TestSlaErrorRateThreshold:
    def _setup_cycle_with_one_confirmed_incident(self, api, item_count):
        ws = setup_live_lockbox(
            bank_overrides={"sla_credit_breach_threshold_bp": 200},
            agreement_overrides={"monthly_maintenance_fee_cents": 100000,
                                 "per_item_capture_fee_cents": 10})
        batch = create_batch(ws, batch_reference="B-N",
                             declared_item_count=item_count,
                             declared_total_cents=item_count * 1000)
        begin_capture(ws, batch["id"])
        capture_and_accept_items(ws, batch["id"], item_count, 1000)
        balance_batch_ok(ws, batch["id"])
        close_batch(ws, batch["id"], operator_id="lock-op-2")
        settle_batch(ws, batch["id"])
        run_close_business_day(ws)
        incident = report_incident(
            ws, incident_kind="LATE_TRANSMISSION",
            occurred_on_business_date="2026-08-01",
            reference_batch_id=batch["id"])
        confirm_incident(ws, incident["id"])
        run_close_analysis_cycle_at_month_end(
            ws, customer_id=ws["customer"]["id"])
        return ws

    def test_sla_error_rate_at_threshold_is_breach(self, api):
        """PRD §3.8: "`sla_breach` holds when the rate reaches the bank's
        `sla_credit_breach_threshold_bp` — a rate exactly at the threshold is
        a breach, one basis point below it is not. On breach,
        `sla_credit_cents` is ten percent of `gross_service_charges_cents`,
        rounded half-up to whole cents; otherwise it is zero."
        PRD §3.8: "The error-rate denominator is one, or the sum of
        `accepted_item_count` and `exception_decision_count`, whichever is
        larger, so an idle cycle never divides by zero. `sla_error_rate_bp` is
        `sla_error_count` multiplied by 10,000 and divided by that denominator,
        rounded half-up to whole basis points."

        Design: Difficulty/boundary_precision_check/sla_error_rate_at_threshold_is_breach
        """
        ws = self._setup_cycle_with_one_confirmed_incident(api, 50)
        cycle = _finalized_cycle(ws)
        # rate = round_half_up(1 * 10,000 / 50) = 200bp == threshold → breach.
        assert cycle["sla_error_rate_bp"] == 200
        assert cycle["sla_breach"] is True
        # gross = 100000 + 50 * 10 = 100500; credit = 10% = 10050.
        assert cycle["gross_service_charges_cents"] == 100500
        assert cycle["sla_credit_cents"] == 10050

    def test_sla_error_rate_below_threshold_is_not_breach(self, api):
        """PRD §3.8: "`sla_breach` holds when the rate reaches the bank's
        `sla_credit_breach_threshold_bp` — a rate exactly at the threshold is
        a breach, one basis point below it is not. On breach,
        `sla_credit_cents` is ten percent of `gross_service_charges_cents`,
        rounded half-up to whole cents; otherwise it is zero."

        Design: Difficulty/boundary_precision_check/sla_error_rate_at_threshold_is_breach
        """
        ws = self._setup_cycle_with_one_confirmed_incident(api, 51)
        cycle = _finalized_cycle(ws)
        # rate = round_half_up(1 * 10,000 / 51) = 196bp < 200bp → no breach.
        assert cycle["sla_error_rate_bp"] == 196
        assert cycle["sla_breach"] is False
        assert cycle["sla_credit_cents"] == 0


class TestNetAmountDueFloor:
    def _setup_finalized_cycle_with_disputed_credit(self, api):
        ws = setup_active_agreement(
            agreement_overrides={"monthly_maintenance_fee_cents": 10000})
        run_close_business_day(ws)
        run_close_analysis_cycle_at_month_end(
            ws, customer_id=ws["customer"]["id"])
        cycle = _finalized_cycle(ws)
        assert cycle["status"] == "FINALIZED"
        assert cycle["gross_service_charges_cents"] == 10000
        assert cycle["net_amount_due_cents"] == 10000
        credit = file_error_credit(ws, cycle["id"],
                                   requested_credit_cents=15000)
        return ws, cycle, credit

    def test_net_amount_due_never_negative_conserved_under_error_credit(self, api):
        """PRD §3.7: "From `DISPUTED`, settlement additionally requires every
        ErrorCreditRequest against the cycle resolved to `APPROVED`,
        `PARTIALLY_APPROVED`, or `DENIED`, and the approved credits apply in a
        fixed order — earnings credit first, then the SLA credit, then approved
        error credits — so the debit is gross charges minus the earnings credit
        minus the SLA credit minus the sum of approved credits, floored at
        zero."
        PRD §3.8: "Full approval sets `approved_credit_cents` equal to
        `requested_credit_cents` and records `reviewed_by_user_id`."

        Design: Difficulty/compensating_invariant/net_amount_due_never_negative_conserved_under_error_credit
        """
        ws, cycle, credit = \
            self._setup_finalized_cycle_with_disputed_credit(api)
        approved = validate_success(
            api.approve_error_credit(ws["bank"]["id"], ws["customer"]["id"],
                                     credit["id"], BILLING_APPR))
        assert approved["status"] == "APPROVED"
        assert approved["approved_credit_cents"] == 15000
        settled = settle_cycle(ws, cycle["id"])
        # 10000 - 0 (ECR) - 0 (SLA) - 15000 (approved) floors at zero.
        assert settled["status"] == "SETTLED"
        assert settled["net_amount_due_cents"] == 0
        assert_net_amount_non_negative(settled)

    def test_partial_approval_reduces_net_due_exactly(self, api):
        """PRD §3.7: "the approved credits apply in a fixed order — earnings
        credit first, then the SLA credit, then approved error credits — so
        the debit is gross charges minus the earnings credit minus the SLA
        credit minus the sum of approved credits, floored at zero."
        PRD §3.8: "Partial approval takes a payload `approved_credit_cents`
        that must be strictly less than the requested amount — anything at or
        above it is `ERR_CREDIT_EXCEEDS_REQUESTED` — and lands the request in
        `PARTIALLY_APPROVED`."

        Design: Difficulty/compensating_invariant/net_amount_due_never_negative_conserved_under_error_credit
        """
        ws, cycle, credit = \
            self._setup_finalized_cycle_with_disputed_credit(api)
        approved = validate_success(
            api.approve_partial_error_credit(ws["bank"]["id"],
                                             ws["customer"]["id"],
                                             credit["id"], 4000, BILLING_APPR))
        assert approved["status"] == "PARTIALLY_APPROVED"
        assert approved["approved_credit_cents"] == 4000
        settled = settle_cycle(ws, cycle["id"])
        assert settled["status"] == "SETTLED"
        # 10000 - 0 - 0 - 4000 = 6000.
        assert settled["net_amount_due_cents"] == 6000
        assert_net_amount_non_negative(settled)


class TestEarningsCreditFloor:
    def test_earnings_credit_floored_at_zero(self, api):
        """PRD §3.7: "The raw credit is the average collected balance
        multiplied by the rate and by the days elapsed, divided by 360 and by
        the 10,000 basis-point denominator, then rounded half-up to whole
        cents, floored at zero, and capped at `gross_service_charges_cents` —
        the bank never pays the customer for excess credit."

        Design: Corner/calculations/earnings_credit_floored_at_zero
        """
        ws = setup_active_agreement(
            bank_overrides={"default_earnings_credit_rate_bp": 500})
        # No billable activity at all: gross is zero, so the cap binds the
        # earnings credit to zero and the net due floors at zero.
        run_close_business_day(ws)
        run_close_analysis_cycle_at_month_end(
            ws, customer_id=ws["customer"]["id"])
        cycle = _finalized_cycle(ws)
        assert cycle["gross_service_charges_cents"] == 0
        assert cycle["earnings_credit_cents"] == 0
        assert cycle["net_amount_due_cents"] == 0


class TestAnalysisCycleSettleOcc:
    def test_occ_analysis_cycle_settle(self, api):
        """PRD §3.7: "From `FINALIZED`, settlement requires that no `SUBMITTED`
        ErrorCreditRequest remains against the cycle
        (`ERR_CYCLE_HAS_OPEN_DISPUTES`) and that `expected_cycle_version` match
        the cycle's current `version` (`ERR_STALE_VERSION`, HTTP 412)".
        PRD §2.4: "If the parent's version has advanced since the client last
        read it — another writer has legitimately moved the resource forward,
        for example by activating the agreement or by a confirmation cascade
        bumping a cycle — the write is rejected with `ERR_STALE_VERSION`
        (HTTP 412), so the client never overwrites state it has not observed."

        Design: Corner/cross_cutting_layers/occ_analysis_cycle_settle
        """
        ws = setup_live_lockbox(
            agreement_overrides={"monthly_maintenance_fee_cents": 1000})
        batch = create_batch(ws, batch_reference="B-REF", declared_item_count=0,
                             declared_total_cents=0)
        # Reported BEFORE the close so §3.7 attaches the incident to the cycle
        # at finalization ("their `cycle_id` is set here"); confirming it after
        # finalization then recomputes the FINALIZED cycle (§3.8: "if the
        # attached cycle is already `FINALIZED`, its `sla_error_count` is
        # recomputed"), which advances the cycle's version (§2.4).
        incident = report_incident(
            ws, incident_kind="LATE_TRANSMISSION",
            occurred_on_business_date="2026-08-01",
            reference_batch_id=batch["id"])
        run_close_business_day(ws)
        run_close_analysis_cycle_at_month_end(
            ws, customer_id=ws["customer"]["id"])
        cycle = _finalized_cycle(ws)
        assert cycle["status"] == "FINALIZED"
        stale_version = cycle["version"]
        confirm_incident(ws, incident["id"])
        resp = api.settle_analysis_cycle(ws["bank"]["id"], ws["customer"]["id"],
                                         cycle["id"], stale_version,
                                         BILLING_SPEC)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
