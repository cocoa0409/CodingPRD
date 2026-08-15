"""Fee and audit calculations: dual pricing variants, rounding order, thresholds,
day-count conventions, reminder input-set filtering, and the compliance audit."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId, TEST_USERS,
    assert_invoice_invariants,
    make_coordinator, make_agent, make_coordinator_with_seller,
    make_coordinator_with_buyer_seller, make_template, make_subscription,
    make_file, activate_file, make_active_listing_file, make_active_purchase_file,
    get_deadline_by_kind, get_milestone_by_name, get_file_invoice,
    list_reminders_for_deadline, accept_document, run_audit,
    make_fully_signed_amendment, get_file_closing_verification, clear_to_close,
    request_close,
)


def _line_amounts(invoice):
    return {line["label"]: line["amount_cents"] for line in invoice["line_items"]}


class TestFeeEstimates:
    def test_per_file_fee_base_rush_conditional_formula(self):
        """PRD §3.4: "Under `PER_FILE`, the base is 39500 cents for a `PURCHASE_SALE`
        contract or 29500 cents for a `LISTING_ONLY` contract, and a rush surcharge of
        7500 cents is added when the gap between `closing_date` and the activation
        date is strictly less than 10 days — a gap of exactly 10 days does not trigger
        the surcharge."
        PRD §3.8: "The `subtotal_cents` is the sum of the per-line amounts, each line
        already rounded to integer cents before summing — the raw sum is never
        rounded."

        Design: Difficulty/combinatorial_formula/per_file_fee_base_rush_conditional_formula
        """
        # Closing 2026-08-08 is 7 days after the 2026-08-01 activation date -> rush.
        scen = make_active_purchase_file(closing_date="2026-08-08",
                                         required_doc_types=["EXECUTED_CONTRACT"])
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        fetched = validate_success(api_client.get_file(file_id, coord_h))
        assert fetched["fee_estimate_cents"] == 47000, (
            f"PURCHASE_SALE base 39500 + rush 7500 = 47000; "
            f"got {fetched['fee_estimate_cents']}"
        )
        invoice = get_file_invoice(coord_h, file_id)
        assert_invoice_invariants(invoice)
        assert invoice["subtotal_cents"] == 47000
        assert invoice["discount_cents"] == 0, "PER_FILE invoices carry no discount"
        assert invoice["total_cents"] == 47000
        amounts = _line_amounts(invoice)
        assert amounts["BASE_FEE"] == 39500
        assert amounts["RUSH_SURCHARGE"] == 7500

    def test_subscription_overage_invoice_discount_rounding_order(self):
        """PRD §3.4: "Under `SUBSCRIPTION`, the frozen within-quota verdict decides:
        if the file committed within quota the estimate is 0 (an included slot);
        otherwise it is the subscription's `overage_fee_cents` plus the same 7500-cent
        rush surcharge under the same strictly-less-than-10-days rule."
        PRD §2.7: "Where a computation needs rounding — the per-line charge components
        of an invoice and the subscription discount — the rule is round-half-up. Two
        rounding points are pinned: each charge component is rounded to integer cents
        first, one line per component, and the subscription discount is then computed
        once on the summed subtotal."

        Design: Difficulty/combinatorial_formula/subscription_overage_invoice_discount_rounding_order
        """
        coord, coord_h, buyer, buyer_h, seller, seller_h = make_coordinator_with_buyer_seller()
        make_template(
            state_code="TX", contract_type="PURCHASE_SALE",
            milestone_defs=[{"name": "Earnest Money", "offset_days": 3, "mandatory": True}],
            required_doc_types=["EXECUTED_CONTRACT"],
        )
        # Quota 0: every file commits as overage (0 < 0 is false).
        sub = make_subscription(coord_h, included_files_quota=0, overage_fee_cents=33335)
        f = make_file(
            coord_h, seller["id"], buyer_agent_id=buyer["id"],
            billing_model="SUBSCRIPTION", contract_type="PURCHASE_SALE",
            closing_date="2026-08-08", financing_offset_days=21, subscription=sub,
        )
        activate_file(coord_h, f["id"])
        fetched = validate_success(api_client.get_file(f["id"], coord_h))
        assert fetched["fee_estimate_cents"] == 40835
        invoice = get_file_invoice(coord_h, f["id"])
        assert_invoice_invariants(invoice)
        assert invoice["subtotal_cents"] == 40835, \
            "SUBSCRIPTION_OVERAGE 33335 + RUSH_SURCHARGE 7500"
        assert invoice["discount_cents"] == 2042, (
            f"round_half_up(40835 * 0.05) = round_half_up(2041.75) = 2042; "
            f"got {invoice['discount_cents']}"
        )
        assert invoice["total_cents"] == 38793
        amounts = _line_amounts(invoice)
        assert amounts["SUBSCRIPTION_OVERAGE"] == 33335
        assert amounts["RUSH_SURCHARGE"] == 7500

    def test_subscription_vs_per_file_pricing_divergence(self):
        """PRD §3.4: "Under `PER_FILE`, the base is 39500 cents for a `PURCHASE_SALE`
        contract or 29500 cents for a `LISTING_ONLY` contract, and a rush surcharge of
        7500 cents is added when the gap between `closing_date` and the activation
        date is strictly less than 10 days — a gap of exactly 10 days does not trigger
        the surcharge. Under `SUBSCRIPTION`, the frozen within-quota verdict decides:
        if the file committed within quota the estimate is 0 (an included slot);
        otherwise it is the subscription's `overage_fee_cents` plus the same 7500-cent
        rush surcharge under the same strictly-less-than-10-days rule. Identical file
        data therefore prices differently under the two variants."
        PRD §3.8: "When the billing model is `SUBSCRIPTION`, a `discount_cents` of the
        subtotal multiplied by 5 percent, rounded half-up, is computed once on that
        summed subtotal; under `PER_FILE` the discount is 0."

        Design: Difficulty/dual_variant_calc/subscription_vs_per_file_pricing_divergence
        """
        coord, coord_h, buyer, buyer_h, seller, seller_h = make_coordinator_with_buyer_seller()
        make_template(state_code="TX", contract_type="PURCHASE_SALE")
        sub = make_subscription(coord_h, included_files_quota=1, overage_fee_cents=34900)
        file_a = make_file(
            coord_h, seller["id"], buyer_agent_id=buyer["id"],
            billing_model="PER_FILE", contract_type="PURCHASE_SALE",
            closing_date="2026-08-31", financing_offset_days=21,
        )
        file_b = make_file(
            coord_h, seller["id"], buyer_agent_id=buyer["id"],
            billing_model="SUBSCRIPTION", contract_type="PURCHASE_SALE",
            closing_date="2026-09-02", financing_offset_days=21,
            property_address="2 Oak Ave", subscription=sub,
        )
        # Both activated at the 2026-08-01 default clock: 30 and 32 days out, no rush.
        activate_file(coord_h, file_a["id"])
        invoices_after_a = get_success_data(api_client.list_invoices(coord_h, params={"limit": 10}))
        assert len(invoices_after_a) == 1
        inv_a = invoices_after_a[0]
        activate_file(coord_h, file_b["id"])
        invoices_after_b = get_success_data(api_client.list_invoices(coord_h, params={"limit": 10}))
        assert len(invoices_after_b) == 2
        inv_b_rows = [i for i in invoices_after_b if i["id"] != inv_a["id"]]
        assert len(inv_b_rows) == 1
        inv_b = inv_b_rows[0]

        assert inv_a["subtotal_cents"] == 39500
        assert inv_a["discount_cents"] == 0
        assert inv_a["total_cents"] == 39500
        assert inv_b["subtotal_cents"] == 0
        assert inv_b["total_cents"] == 0
        assert _line_amounts(inv_b).get("SUBSCRIPTION_INCLUDED") == 0

        fa = validate_success(api_client.get_file(file_a["id"], coord_h))
        fb = validate_success(api_client.get_file(file_b["id"], coord_h))
        assert fa["fee_estimate_cents"] == 39500
        assert fb["fee_estimate_cents"] == 0
        assert fa["fee_estimate_cents"] != fb["fee_estimate_cents"], \
            "identical contract data must price differently under the two variants"

    def test_rush_threshold_exactly_10_days_escapes_surcharge(self):
        """PRD §3.4: "Under `PER_FILE`, the base is 39500 cents for a `PURCHASE_SALE`
        contract or 29500 cents for a `LISTING_ONLY` contract, and a rush surcharge of
        7500 cents is added when the gap between `closing_date` and the activation
        date is strictly less than 10 days — a gap of exactly 10 days does not trigger
        the surcharge."

        Design: Corner/calculations/rush_threshold_exactly_10_days_escapes_surcharge
        """
        # Both activations run at the default clock date 2026-08-01.
        # Distinct state_code per scenario: PRD §3.1 allows at most one ACTIVE
        # template per (state_code, contract_type) pair, so the two scenarios'
        # templates must occupy different pairs. Fee math is state-independent.
        scen9 = make_active_listing_file(closing_date="2026-08-10", coordinator_name="Casey Coord")
        scen10 = make_active_listing_file(closing_date="2026-08-11", state_code="CO",
                                          coordinator_name="Dana Coord")
        fee9 = validate_success(api_client.get_file(scen9["file"]["id"], scen9["coord_h"]))["fee_estimate_cents"]
        fee10 = validate_success(api_client.get_file(scen10["file"]["id"], scen10["coord_h"]))["fee_estimate_cents"]
        assert fee9 == 37000, f"9-day gap: 29500 + 7500 rush = 37000; got {fee9}"
        assert fee10 == 29500, f"exactly 10-day gap escapes the surcharge: 29500; got {fee10}"


class TestDeadlineConventions:
    def test_deadline_calendar_vs_business_day_convention(self):
        """PRD §2.9: "Two deadline day-count conventions exist. A file's `state_code`
        pins which one applies: for `NY`, deadlines count business days; for every
        other state code, deadlines count calendar days. Under the calendar
        convention, a deadline's `due_date` is the file's `effective_date` plus
        `offset_days` calendar days. Under the business convention, `due_date` is the
        `effective_date` plus `offset_days` business days, counting Monday through
        Friday only, with the count starting on the day after the `effective_date`
        (day zero is the `effective_date` itself); holidays are not observed, only
        weekends. The two conventions produce different due dates for identical
        inputs, and the business convention always yields a date no earlier than the
        calendar one for a positive offset."

        Design: Difficulty/dual_variant_calc/deadline_calendar_vs_business_day_convention
        """
        coord, coord_h, buyer, buyer_h, seller, seller_h = make_coordinator_with_buyer_seller()
        make_template(state_code="TX", contract_type="PURCHASE_SALE")
        make_template(state_code="NY", contract_type="PURCHASE_SALE")
        file_tx = make_file(
            coord_h, seller["id"], buyer_agent_id=buyer["id"],
            contract_type="PURCHASE_SALE", state_code="TX",
            closing_date="2026-08-31", financing_offset_days=21,
        )
        activate_file(coord_h, file_tx["id"])
        tx_deadlines = get_success_data(api_client.list_deadlines(coord_h, params={"limit": 100}))
        tx_insp = [d for d in tx_deadlines if d["kind"] == "INSPECTION"]
        assert len(tx_insp) == 1
        tx_insp = tx_insp[0]
        tx_ids = {d["id"] for d in tx_deadlines}

        file_ny = make_file(
            coord_h, seller["id"], buyer_agent_id=buyer["id"],
            contract_type="PURCHASE_SALE", state_code="NY",
            closing_date="2026-09-02", financing_offset_days=21,
            property_address="9 Pine Rd", list_price_cents=38000000,
        )
        activate_file(coord_h, file_ny["id"])
        all_deadlines = get_success_data(api_client.list_deadlines(coord_h, params={"limit": 100}))
        ny_insp = [d for d in all_deadlines if d["id"] not in tx_ids and d["kind"] == "INSPECTION"]
        assert len(ny_insp) == 1
        ny_insp = ny_insp[0]

        # Identical inputs: effective 2026-08-03, inspection_offset_days 7.
        assert tx_insp["due_date"] == "2026-08-10", "TX calendar: 2026-08-03 + 7 days"
        assert tx_insp["day_convention"] == "CALENDAR"
        assert ny_insp["due_date"] == "2026-08-12", (
            "NY business: Aug 4,5,6,7,10,11,12 = 7 business days (weekends skipped); "
            f"got {ny_insp['due_date']}"
        )
        assert ny_insp["day_convention"] == "BUSINESS"
        assert tx_insp["due_date"] != ny_insp["due_date"], \
            "identical inputs must diverge by convention"


class TestReminderScheduleFiltering:
    def test_reminders_skip_past_candidates_at_late_activation(self):
        """PRD §3.4: "Each deadline then generates its reminder schedule: candidate
        reminders sit at 5 days before, 2 days before, and on the due date itself,
        each at 09:00:00 UTC; only candidates whose `scheduled_at` is strictly after
        the current clock time are actually created, and created reminders are
        numbered `sequence_no` 1, 2, 3 in ascending `scheduled_at` order."

        Design: Corner/calculations/reminders_skip_past_candidates_at_late_activation
        """
        coord, coord_h, seller, seller_h = make_coordinator_with_seller()
        make_template(
            state_code="TX", contract_type="LISTING_ONLY",
            milestone_defs=[{"name": "Listing Paperwork", "offset_days": 30, "mandatory": False}],
            required_doc_types=[],
        )
        # Advance the clock BEFORE activation so the T-5 candidate (2026-08-05T09:00Z)
        # is no longer strictly after the current clock time.
        validate_success(api_client.set_clock({"to_iso8601": "2026-08-06T00:00:00Z"},
                                              TEST_USERS["admin_headers"]))
        f = make_file(coord_h, seller["id"], inspection_offset_days=7, appraisal_offset_days=25)
        activate_file(coord_h, f["id"])
        insp = get_deadline_by_kind(coord_h, f["id"], "INSPECTION")
        assert insp["due_date"] == "2026-08-10"
        reminders = list_reminders_for_deadline(coord_h, insp["id"])
        assert len(reminders) == 2, (
            f"the past T-5 candidate must be skipped, leaving T-2 and T-0; "
            f"got {len(reminders)} reminders"
        )
        by_seq = {r["sequence_no"]: r for r in reminders}
        assert by_seq[1]["scheduled_at"].startswith("2026-08-08T09:00:00")
        assert by_seq[2]["scheduled_at"].startswith("2026-08-10T09:00:00")
        assert all(r["status"] == "QUEUED" for r in reminders)
        assert not any(r["scheduled_at"].startswith("2026-08-05") for r in reminders), \
            "the 2026-08-05T09:00Z candidate predates the 2026-08-06 activation clock"


class TestComplianceAudit:
    def test_audit_fail_lists_missing_types_in_order(self):
        """PRD §3.7: "The required set is built by concatenating the pinned template's
        `required_doc_types` (in template declaration order) with the state-mandated
        disclosures for the file's `state_code` (in constant declaration order) — `TX`
        requires `T47_DISCLOSURE`; `NY` requires `NHD_REPORT`; `CA` requires
        `TDS_DISCLOSURE` then `NHD_REPORT`; `CO` requires nothing extra — and removing
        duplicates while keeping each first occurrence."
        PRD §3.7: "The unsatisfied types, in required-set order, are returned as
        `missing_doc_types`, and the `result` is `PASS` exactly when that list is
        empty — so an empty required set passes with zero documents. The audit writes
        the file's `last_audit_status` to the result."

        Design: Corner/calculations/audit_fail_lists_missing_types_in_order
        """
        scen = make_active_purchase_file(
            required_doc_types=["EXECUTED_CONTRACT", "TITLE_COMMITMENT"],
        )
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        accept_document(coord_h, scen["buyer_h"], file_id, "EXECUTED_CONTRACT")
        result = run_audit(coord_h, file_id)
        assert result["result"] == "FAIL"
        assert result["missing_doc_types"] == ["TITLE_COMMITMENT", "T47_DISCLOSURE"], (
            f"template order first, then state disclosures; "
            f"got {result['missing_doc_types']}"
        )
        fetched = validate_success(api_client.get_file(file_id, coord_h))
        assert fetched["last_audit_status"] == "FAIL"

    def test_audit_empty_required_set_passes_with_zero_documents(self):
        """PRD §3.7: "The unsatisfied types, in required-set order, are returned as
        `missing_doc_types`, and the `result` is `PASS` exactly when that list is
        empty — so an empty required set passes with zero documents. The audit writes
        the file's `last_audit_status` to the result."
        PRD §3.7: "The required set is built by concatenating the pinned template's
        `required_doc_types` (in template declaration order) with the state-mandated
        disclosures for the file's `state_code` (in constant declaration order) — `TX`
        requires `T47_DISCLOSURE`; `NY` requires `NHD_REPORT`; `CA` requires
        `TDS_DISCLOSURE` then `NHD_REPORT`; `CO` requires nothing extra — and removing
        duplicates while keeping each first occurrence."

        Design: Difficulty/boundary_precision_check/audit_empty_required_set_passes_with_zero_documents
        """
        scen = make_active_listing_file(state_code="CO")
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        result = run_audit(coord_h, file_id)
        assert result["result"] == "PASS"
        assert result["missing_doc_types"] == []
        fetched = validate_success(api_client.get_file(file_id, coord_h))
        assert fetched["last_audit_status"] == "PASS", \
            "an empty required set must PASS with zero documents on the file"


class TestFinalFee:
    def test_first_effective_amendment_is_free_at_close(self):
        """PRD §3.8: "The amendment component counts only the file's amendments in
        `EFFECTIVE` status — drafts, routed, partially or fully signed, rejected, and
        voided amendments are excluded — subtracts the one free amendment with a floor
        of zero, and multiplies the remainder by 5000 cents each."
        PRD §3.8: "The evaluation order is fixed: count effective amendments, subtract
        the free allowance floored at zero, multiply by the per-amendment fee, then
        add to the activation components. The result is stored as `fee_final_cents`."

        Design: Corner/calculations/first_effective_amendment_is_free_at_close
        """
        scen = make_active_purchase_file(
            milestone_defs=[{"name": "Earnest Money", "offset_days": 3, "mandatory": True}],
            required_doc_types=["EXECUTED_CONTRACT"],
        )
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        am = make_fully_signed_amendment(
            coord_h, file_id,
            buyer_h=scen["buyer_h"], seller_h=scen["seller_h"],
            buyer_id=scen["buyer"]["id"], seller_id=scen["seller"]["id"],
            new_list_price_cents=44500000,
        )
        applied = validate_success(api_client.apply_amendment(am["id"], coord_h))
        assert applied["status"] == "EFFECTIVE"
        accept_document(coord_h, scen["buyer_h"], file_id, "EXECUTED_CONTRACT")
        accept_document(coord_h, scen["seller_h"], file_id, "T47_DISCLOSURE")
        run_audit(coord_h, file_id)
        ms = get_milestone_by_name(coord_h, file_id, "Earnest Money")
        api_client.start_milestone(ms["id"], coord_h)
        api_client.complete_milestone(ms["id"], coord_h)
        request_close(coord_h, file_id)
        cv = get_file_closing_verification(coord_h, file_id)
        clear_to_close(coord_h, cv["id"], lender_needed=True)
        closed = validate_success(api_client.close_file(file_id, coord_h))
        assert closed["status"] == "CLOSED"
        assert closed["fee_final_cents"] == 39500, (
            f"max(0, 1 EFFECTIVE - 1 free) * 5000 = 0 amendment fee; "
            f"got {closed['fee_final_cents']}"
        )
        invoice = get_file_invoice(coord_h, file_id)
        assert_invoice_invariants(invoice)
        assert invoice["status"] == "ISSUED"
        assert invoice["subtotal_cents"] == 39500
        assert invoice["total_cents"] == 39500
        assert "AMENDMENT_FEE" not in _line_amounts(invoice), \
            "the first EFFECTIVE amendment is free; no AMENDMENT_FEE line may appear"


class TestSubscriptionQuotaBoundary:
    def test_subscription_quota_equality_triggers_overage(self):
        """PRD §3.3: "Before this file's commitment is applied, the service evaluates
        whether the subscription's `included_files_used` is strictly less than its
        `included_files_quota`; the boundary is strict, so when the counter equals the
        quota exactly the new file is an overage commitment. That within-quota verdict
        is frozen onto the file at creation and reused verbatim by the fee
        calculations later, independent of how the counter moves afterward."
        PRD §3.4: "Under `SUBSCRIPTION`, the frozen within-quota verdict decides: if
        the file committed within quota the estimate is 0 (an included slot);
        otherwise it is the subscription's `overage_fee_cents` plus the same 7500-cent
        rush surcharge under the same strictly-less-than-10-days rule."

        Design: Difficulty/boundary_precision_check/subscription_quota_equality_triggers_overage
        """
        coord, coord_h, buyer, buyer_h, seller, seller_h = make_coordinator_with_buyer_seller()
        make_template(state_code="TX", contract_type="PURCHASE_SALE")
        sub = make_subscription(coord_h, included_files_quota=1, overage_fee_cents=34900)
        file_a = make_file(
            coord_h, seller["id"], buyer_agent_id=buyer["id"],
            billing_model="SUBSCRIPTION", contract_type="PURCHASE_SALE",
            closing_date="2026-08-31", financing_offset_days=21, subscription=sub,
        )
        file_b = make_file(
            coord_h, seller["id"], buyer_agent_id=buyer["id"],
            billing_model="SUBSCRIPTION", contract_type="PURCHASE_SALE",
            closing_date="2026-09-02", financing_offset_days=21,
            property_address="2 Oak Ave", subscription=sub,
        )
        activate_file(coord_h, file_a["id"])
        inv_a = get_success_data(api_client.list_invoices(coord_h, params={"limit": 10}))
        assert len(inv_a) == 1
        inv_a = inv_a[0]
        activate_file(coord_h, file_b["id"])
        inv_b_rows = [i for i in get_success_data(api_client.list_invoices(coord_h, params={"limit": 10}))
                      if i["id"] != inv_a["id"]]
        assert len(inv_b_rows) == 1
        inv_b = inv_b_rows[0]
        # File A committed at used 0 < quota 1: included slot, zeroed invoice.
        assert inv_a["subtotal_cents"] == 0
        assert inv_a["total_cents"] == 0
        # File B committed at used 1 == quota 1 (equality): overage.
        assert inv_b["subtotal_cents"] == 34900
        assert inv_b["discount_cents"] == 1745, "round_half_up(34900 * 0.05) = 1745"
        assert inv_b["total_cents"] == 33155
        sub_after = validate_success(api_client.get_subscription(sub["id"], coord_h))
        assert sub_after["included_files_used"] == 2

    def test_subscription_quota_third_file_is_overage(self):
        """PRD §3.3: "Before this file's commitment is applied, the service evaluates
        whether the subscription's `included_files_used` is strictly less than its
        `included_files_quota`; the boundary is strict, so when the counter equals the
        quota exactly the new file is an overage commitment."
        PRD §3.2: "The `included_files_used` counter is the subscription's
        committed-slot ledger: it increases by 1 the moment a file is created under
        the subscription and decreases by 1 only on an eligible termination release
        described in §3.6."

        Design: Difficulty/boundary_precision_check/subscription_quota_equality_triggers_overage
        """
        coord, coord_h, buyer, buyer_h, seller, seller_h = make_coordinator_with_buyer_seller()
        make_template(state_code="TX", contract_type="PURCHASE_SALE")
        sub = make_subscription(coord_h, included_files_quota=2, overage_fee_cents=34900)
        invoice_ids = []
        for i, closing in enumerate(["2026-08-31", "2026-09-02", "2026-09-04"]):
            f = make_file(
                coord_h, seller["id"], buyer_agent_id=buyer["id"],
                billing_model="SUBSCRIPTION", contract_type="PURCHASE_SALE",
                closing_date=closing, financing_offset_days=21,
                property_address=f"{i + 1} Main St", subscription=sub,
            )
            activate_file(coord_h, f["id"])
            rows = [r for r in get_success_data(api_client.list_invoices(coord_h, params={"limit": 10}))
                    if r["id"] not in invoice_ids]
            assert len(rows) == 1
            invoice_ids.append(rows[0]["id"])
            if i < 2:
                assert rows[0]["total_cents"] == 0, f"file {i + 1} committed within quota"
            else:
                # Third commit evaluates used 2 == quota 2: strictly-less fails.
                assert rows[0]["subtotal_cents"] == 34900
                assert rows[0]["discount_cents"] == 1745
                assert rows[0]["total_cents"] == 33155
        sub_after = validate_success(api_client.get_subscription(sub["id"], coord_h))
        assert sub_after["included_files_used"] == 3


class TestFeeEstimatesSecondForms:
    def test_per_file_listing_rush_formula(self):
        """PRD §3.4: "Under `PER_FILE`, the base is 39500 cents for a `PURCHASE_SALE`
        contract or 29500 cents for a `LISTING_ONLY` contract, and a rush surcharge of
        7500 cents is added when the gap between `closing_date` and the activation
        date is strictly less than 10 days — a gap of exactly 10 days does not trigger
        the surcharge."

        Design: Difficulty/combinatorial_formula/per_file_fee_base_rush_conditional_formula
        """
        # LISTING_ONLY tier, closing 2026-08-05 -> 4-day gap -> rush applies.
        scen = make_active_listing_file(closing_date="2026-08-05")
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        fetched = validate_success(api_client.get_file(file_id, coord_h))
        assert fetched["fee_estimate_cents"] == 37000
        invoice = get_file_invoice(coord_h, file_id)
        assert_invoice_invariants(invoice)
        assert invoice["subtotal_cents"] == 37000
        assert invoice["discount_cents"] == 0
        assert invoice["total_cents"] == 37000
        amounts = _line_amounts(invoice)
        assert amounts["BASE_FEE"] == 29500
        assert amounts["RUSH_SURCHARGE"] == 7500

    def test_subscription_overage_discount_without_rush(self):
        """PRD §3.4: "Under `SUBSCRIPTION`, the frozen within-quota verdict decides:
        if the file committed within quota the estimate is 0 (an included slot);
        otherwise it is the subscription's `overage_fee_cents` plus the same 7500-cent
        rush surcharge under the same strictly-less-than-10-days rule."
        PRD §2.7: "Where a computation needs rounding — the per-line charge components
        of an invoice and the subscription discount — the rule is round-half-up. Two
        rounding points are pinned: each charge component is rounded to integer cents
        first, one line per component, and the subscription discount is then computed
        once on the summed subtotal."

        Design: Difficulty/combinatorial_formula/subscription_overage_invoice_discount_rounding_order
        """
        coord, coord_h, buyer, buyer_h, seller, seller_h = make_coordinator_with_buyer_seller()
        make_template(state_code="TX", contract_type="PURCHASE_SALE")
        sub = make_subscription(coord_h, included_files_quota=0, overage_fee_cents=33335)
        f = make_file(
            coord_h, seller["id"], buyer_agent_id=buyer["id"],
            billing_model="SUBSCRIPTION", contract_type="PURCHASE_SALE",
            closing_date="2026-08-31", financing_offset_days=21, subscription=sub,
        )
        activate_file(coord_h, f["id"])
        fetched = validate_success(api_client.get_file(f["id"], coord_h))
        assert fetched["fee_estimate_cents"] == 33335, "30 days out: overage only, no rush"
        invoice = get_file_invoice(coord_h, f["id"])
        assert_invoice_invariants(invoice)
        assert invoice["subtotal_cents"] == 33335
        assert invoice["discount_cents"] == 1667, \
            "round_half_up(33335 * 0.05) = round_half_up(1666.75) = 1667"
        assert invoice["total_cents"] == 31668

    def test_listing_files_diverge_under_per_file_and_subscription(self):
        """PRD §3.4: "Under `PER_FILE`, the base is 39500 cents for a `PURCHASE_SALE`
        contract or 29500 cents for a `LISTING_ONLY` contract, and a rush surcharge of
        7500 cents is added when the gap between `closing_date` and the activation
        date is strictly less than 10 days — a gap of exactly 10 days does not trigger
        the surcharge. Under `SUBSCRIPTION`, the frozen within-quota verdict decides:
        if the file committed within quota the estimate is 0 (an included slot);
        otherwise it is the subscription's `overage_fee_cents` plus the same 7500-cent
        rush surcharge under the same strictly-less-than-10-days rule. Identical file
        data therefore prices differently under the two variants."

        Design: Difficulty/dual_variant_calc/subscription_vs_per_file_pricing_divergence
        """
        coord, coord_h, seller, seller_h = make_coordinator_with_seller()
        make_template(state_code="TX", contract_type="LISTING_ONLY")
        sub = make_subscription(coord_h, included_files_quota=1, overage_fee_cents=34900)
        file_a = make_file(coord_h, seller["id"], closing_date="2026-08-31")
        file_b = make_file(
            coord_h, seller["id"], billing_model="SUBSCRIPTION",
            closing_date="2026-09-02", property_address="2 Oak Ave", subscription=sub,
        )
        activate_file(coord_h, file_a["id"])
        inv_a = get_success_data(api_client.list_invoices(coord_h, params={"limit": 10}))[0]
        activate_file(coord_h, file_b["id"])
        inv_b = [i for i in get_success_data(api_client.list_invoices(coord_h, params={"limit": 10}))
                 if i["id"] != inv_a["id"]][0]
        assert inv_a["total_cents"] == 29500, "LISTING_ONLY base under PER_FILE"
        assert inv_a["discount_cents"] == 0
        assert inv_b["total_cents"] == 0, "within-quota SUBSCRIPTION file is an included slot"
        fa = validate_success(api_client.get_file(file_a["id"], coord_h))
        fb = validate_success(api_client.get_file(file_b["id"], coord_h))
        assert fa["fee_estimate_cents"] == 29500
        assert fb["fee_estimate_cents"] == 0


class TestDeadlineConventionsSecondForm:
    def test_appraisal_deadline_diverges_by_convention(self):
        """PRD §2.9: "Two deadline day-count conventions exist. A file's `state_code`
        pins which one applies: for `NY`, deadlines count business days; for every
        other state code, deadlines count calendar days. Under the calendar
        convention, a deadline's `due_date` is the file's `effective_date` plus
        `offset_days` calendar days. Under the business convention, `due_date` is the
        `effective_date` plus `offset_days` business days, counting Monday through
        Friday only, with the count starting on the day after the `effective_date`
        (day zero is the `effective_date` itself); holidays are not observed, only
        weekends. The two conventions produce different due dates for identical
        inputs, and the business convention always yields a date no earlier than the
        calendar one for a positive offset."

        Design: Difficulty/dual_variant_calc/deadline_calendar_vs_business_day_convention
        """
        coord, coord_h, buyer, buyer_h, seller, seller_h = make_coordinator_with_buyer_seller()
        make_template(state_code="TX", contract_type="PURCHASE_SALE")
        make_template(state_code="NY", contract_type="PURCHASE_SALE")
        file_tx = make_file(
            coord_h, seller["id"], buyer_agent_id=buyer["id"],
            contract_type="PURCHASE_SALE", state_code="TX",
            closing_date="2026-08-31", financing_offset_days=21,
        )
        activate_file(coord_h, file_tx["id"])
        tx_rows = get_success_data(api_client.list_deadlines(coord_h, params={"limit": 100}))
        tx_appr = [d for d in tx_rows if d["kind"] == "APPRAISAL"][0]
        tx_ids = {d["id"] for d in tx_rows}
        file_ny = make_file(
            coord_h, seller["id"], buyer_agent_id=buyer["id"],
            contract_type="PURCHASE_SALE", state_code="NY",
            closing_date="2026-09-02", financing_offset_days=21,
            property_address="9 Pine Rd",
        )
        activate_file(coord_h, file_ny["id"])
        ny_appr = [d for d in get_success_data(api_client.list_deadlines(coord_h, params={"limit": 100}))
                   if d["id"] not in tx_ids and d["kind"] == "APPRAISAL"][0]
        # Identical inputs: effective 2026-08-03 (Monday), appraisal_offset_days 14.
        assert tx_appr["due_date"] == "2026-08-17", "TX calendar: 2026-08-03 + 14 days"
        assert ny_appr["due_date"] == "2026-08-21", (
            "NY business: Aug 4-7, 10-14, 17-21 excluding the Aug 8-9 and 15-16 "
            f"weekends = 14 business days; got {ny_appr['due_date']}"
        )
        assert tx_appr["day_convention"] == "CALENDAR"
        assert ny_appr["day_convention"] == "BUSINESS"


class TestComplianceAuditSecondForm:
    def test_audit_empty_template_set_still_requires_state_disclosures(self):
        """PRD §3.7: "The required set is built by concatenating the pinned template's
        `required_doc_types` (in template declaration order) with the state-mandated
        disclosures for the file's `state_code` (in constant declaration order) — `TX`
        requires `T47_DISCLOSURE`; `NY` requires `NHD_REPORT`; `CA` requires
        `TDS_DISCLOSURE` then `NHD_REPORT`; `CO` requires nothing extra — and removing
        duplicates while keeping each first occurrence."
        PRD §3.7: "The unsatisfied types, in required-set order, are returned as
        `missing_doc_types`, and the `result` is `PASS` exactly when that list is
        empty — so an empty required set passes with zero documents. The audit writes
        the file's `last_audit_status` to the result."

        Design: Difficulty/boundary_precision_check/audit_empty_required_set_passes_with_zero_documents
        """
        # CA LISTING_ONLY: the template requires nothing, but the state mandates
        # TDS_DISCLOSURE then NHD_REPORT, so zero documents cannot pass here.
        scen = make_active_listing_file(state_code="CA")
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        result = run_audit(coord_h, file_id)
        assert result["result"] == "FAIL"
        assert result["missing_doc_types"] == ["TDS_DISCLOSURE", "NHD_REPORT"]
        fetched = validate_success(api_client.get_file(file_id, coord_h))
        assert fetched["last_audit_status"] == "FAIL"
