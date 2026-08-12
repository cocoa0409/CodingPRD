"""Donation intake, administrative fees, tax receipts, and refunds
(PRD §2.4, §2.5, §2.6, §3.3)."""
from test_helpers import (
    ApiErrorId,
    assert_ledger_entry,
    create_active_bundle,
    create_donation_payload,
    create_received_donation,
    create_receipted_donation,
    decide_refund,
    get_fund,
    issue_receipt,
    make_donor_headers,
    make_finance_officer_headers,
    make_sponsor_admin_headers,
    pledge_donation,
    receive_donation,
    request_refund,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDonationIntake:
    def test_donation_anonymous_default_false(self, api):
        """PRD §3.3: "an `anonymous` flag (default false) that suppresses the donor's
        name on public listings"

        Design: Corner/entities/e_donation_anonymous_default_false
        """
        bundle = create_active_bundle("user_c_app3", project_name="An", contact_email="an@x.org")
        donation = pledge_donation(bundle["project_id"], 5000)
        assert donation["anonymous"] is False, "omitted anonymous flag defaults to false"

    def test_donation_minimum_boundary(self, api):
        """PRD §3.3: "by supplying `amount_cents` (at least 100 cents, one dollar, else
        `ERR_AMOUNT_BELOW_MINIMUM`)"

        Design: Corner/validations/v_donation_minimum_boundary
        """
        bundle = create_active_bundle("user_c_v17", project_name="MN", contact_email="mn@x.org")
        pid = bundle["project_id"]
        resp = api.create_donation(pid, create_donation_payload(amount_cents=99),
                                   make_donor_headers())
        validate_error(resp, ApiErrorId.ERR_AMOUNT_BELOW_MINIMUM)
        ok = api.create_donation(pid, create_donation_payload(amount_cents=100),
                                 make_donor_headers())
        data = validate_success(ok, expected_status=201)
        assert data["status"] == "PLEDGED", "exactly 100 cents meets the inclusive minimum"


class TestAdminFeeArithmetic:
    def test_fee_single_tier_eight_percent(self, api):
        """PRD §3.3: "the portion falling within the fund's first 10,000,000 cents (one
        hundred thousand dollars) of cumulative receipts is charged eight percent"
        100,000 cents with zero prior receipts -> fee 8,000.

        Design: Corner/calculations/c_fee_single_tier_eight_percent
        """
        bundle = create_active_bundle("user_c_f1", project_name="F1", contact_email="f1@x.org")
        donation = create_received_donation(bundle["project_id"], 100000)
        assert donation["fee_cents"] == 8000

    def test_fee_grant_half_cent_rounds_half_up(self, api):
        """PRD §3.3: "Under `PRE_APPROVED_GRANT`, the fee is a flat three percent of the
        gift amount, rounded half up to whole cents, with no minimum and no reference to
        cumulative receipts"
        PRD §2.4: "the rounding method is round half up, applied at the granularity the
        calculation specifies; no calculation ever uses banker's rounding or truncation."
        3% of 150 = 4.5 -> 5.

        Design: Corner/calculations/c_fee_grant_half_cent_rounds_half_up
        """
        bundle = create_active_bundle("user_c_f2", model="PRE_APPROVED_GRANT",
                                      project_name="F2", contact_email="f2@x.org")
        donation = create_received_donation(bundle["project_id"], 150)
        assert donation["fee_cents"] == 5, "round half up of 4.5 cents must yield 5"

    def test_fee_tier_cap_boundary_exact(self, api):
        """PRD §3.3: "the portion falling within the fund's first 10,000,000 cents (one
        hundred thousand dollars) of cumulative receipts is charged eight percent; the
        portion falling between the 10,000,000-cent and 50,000,000-cent (five hundred
        thousand dollar) cumulative lines is charged six percent"

        Design: Corner/calculations/c_fee_tier_cap_boundary_exact
        """
        bundle = create_active_bundle("user_c_f3", project_name="F3",
                                      budget_estimate_cents=900000000, contact_email="f3@x.org")
        pid = bundle["project_id"]
        first = create_received_donation(pid, 10000000)
        assert first["fee_cents"] == 800000, (
            "donation landing cumulative receipts exactly on the tier-1 cap is entirely at 8%")
        second = create_received_donation(pid, 1000)
        assert second["fee_cents"] == 60, "the next 1,000 cents fall fully in the 6% tier"

    def test_fee_comprehensive_variant_tier_straddle(self, api):
        """PRD §3.3: "Under `COMPREHENSIVE`, the fee walks the donation amount through
        marginal tiers of the fund's cumulative lifetime receipts, measured by
        `total_received_cents` immediately before this receipt"
        Cumulative 9,900,000 then a 200,000 gift: 100,000 at 8% (8,000) + 100,000 at
        6% (6,000) = 14,000.

        Design: Difficulty/dual_variant_calc/admin_fee_model_variants_diverge
        """
        bundle = create_active_bundle("user_app_a", project_name="Alpha",
                                      budget_estimate_cents=50000000, contact_email="a@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 9900000)
        donation = create_received_donation(pid, 200000)
        assert donation["fee_cents"] == 14000, (
            f"tier straddle must yield 8000 + 6000 = 14000, got {donation['fee_cents']}")

    def test_fee_grant_variant_flat_diverges(self, api):
        """PRD §3.3: "Under `PRE_APPROVED_GRANT`, the fee is a flat three percent of the
        gift amount, rounded half up to whole cents, with no minimum and no reference to
        cumulative receipts"
        The same 200,000-cent gift under the grant model yields 6,000 — identical
        inputs price differently purely by the granted model.

        Design: Difficulty/dual_variant_calc/admin_fee_model_variants_diverge
        """
        bundle = create_active_bundle("user_app_b", model="PRE_APPROVED_GRANT",
                                      project_name="Beta", budget_estimate_cents=5000000,
                                      contact_email="b@x.org")
        donation = create_received_donation(bundle["project_id"], 200000)
        assert donation["fee_cents"] == 6000, (
            f"flat 3% with no cumulative input must yield 6000, got {donation['fee_cents']}")

    def test_fee_straddle_per_segment_rounding(self, api):
        """PRD §3.3: "Each segment's charge is rounded half up to whole cents before the
        segments are summed, and if the sum is below 50 cents it is raised to that
        per-donation minimum."
        Cumulative 9,900,000 then 200,000 straddles tiers: 8,000 + 6,000 = 14,000.

        Design: Difficulty/combinatorial_formula/fee_tier_straddle_and_min_branches
        """
        bundle = create_active_bundle("user_app_d", project_name="Delta",
                                      budget_estimate_cents=900000000, contact_email="d@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 9900000)
        donation = create_received_donation(pid, 200000)
        assert donation["fee_cents"] == 14000

    def test_fee_minimum_branch_binds(self, api):
        """PRD §3.3: "Each segment's charge is rounded half up to whole cents before the
        segments are summed, and if the sum is below 50 cents it is raised to that
        per-donation minimum."
        A 100-cent gift at 8% computes to 8 cents; the minimum branch raises it to 50.

        Design: Difficulty/combinatorial_formula/fee_tier_straddle_and_min_branches
        """
        bundle = create_active_bundle("user_app_e", project_name="Epsilon",
                                      budget_estimate_cents=100000, contact_email="e@x.org")
        donation = create_received_donation(bundle["project_id"], 100)
        assert donation["fee_cents"] == 50, "max(50-cent minimum, raw 8) must bind"


class TestReceiveSideEffects:
    def test_fund_available_computed_after_receive(self, api):
        """PRD §3.3: "the fund's `total_received_cents` grows by the gift amount while
        `total_fees_charged_cents` grows by the fee"
        PRD §2.6: "From these totals the account derives `available_cents`: total
        received, minus total refunded, minus total fees charged, plus total fees
        reversed, minus total disbursed, minus total transferred out, plus total
        adjustments, minus committed, minus reserved."

        Design: Corner/entities/e_fund_available_computed_after_receive
        """
        bundle = create_active_bundle("user_c_app4", project_name="Cf", contact_email="cf@x.org")
        donation = create_received_donation(bundle["project_id"], 100000)
        assert donation["fee_cents"] == 8000
        fund = get_fund(bundle["fund_account_id"])
        assert fund["total_received_cents"] == 100000
        assert fund["total_fees_charged_cents"] == 8000
        assert fund["available_cents"] == 92000

    def test_ledger_entry_immutable_shape(self, api):
        """PRD §3.3: "Receipt then posts two ledger entries linked by `donation_id` — a
        `DONATION_CREDIT` for the gross amount and a `FEE_DEBIT` for the fee"
        PRD §2.6: "a signed `amount_cents` (credits positive, debits negative)"
        PRD §2.5: "a `FundLedgerEntry` carries only `id` and `created_at`. Both
        `updated_at` and `version` are absent from ledger entries, because entries are
        immutable once posted."

        Design: Corner/entities/e_ledger_entry_immutable_shape
        """
        bundle = create_active_bundle("user_c_app6", project_name="Li", contact_email="li@x.org")
        donation = create_received_donation(bundle["project_id"], 10000)
        entries, meta = validate_paginated(api.list_fund_ledger_entries(
            bundle["fund_account_id"], make_finance_officer_headers()))
        assert len(entries) == 2, "receive posts exactly two ledger entries"
        for entry in entries:
            assert_ledger_entry(entry)
            assert entry["donation_id"] == donation["id"]
        by_type = {entry["entry_type"]: entry["amount_cents"] for entry in entries}
        assert by_type["DONATION_CREDIT"] == 10000, "credit posts the gross amount (positive)"
        assert by_type["FEE_DEBIT"] == -800, "debit posts the fee (negative)"
        created = [entry["created_at"] for entry in entries]
        assert created == sorted(created), "PRD §2.3: lists sort by created_at ascending"


class TestRefundGuards:
    def test_decide_refund_without_request_rejected(self, api):
        """PRD §2.11: "Seventh, state-machine guards: the target resource must be in a
        from-state of the requested transition, else the per-machine state error"
        PRD §4: POST /fsa/donations/{id}/decide-refund — "Approve or reject the open
        refund request".

        Design: Corner/state_machines/sm_decide_refund_without_request_rejected
        """
        bundle = create_active_bundle("user_c_rf", project_name="RF", contact_email="rf@x.org")
        donation = create_received_donation(bundle["project_id"], 10000)
        resp = api.decide_refund(donation["id"], {"decision": "APPROVE"},
                                 make_sponsor_admin_headers())
        validate_error(resp, ApiErrorId.ERR_DONATION_STATE_INVALID)
        after = validate_success(api.get_donation(donation["id"], make_finance_officer_headers()))
        assert after["status"] == "RECEIVED"
        fund = get_fund(bundle["fund_account_id"])
        assert fund["total_refunded_cents"] == 0

    def test_refund_exceeds_remaining(self, api):
        """PRD §3.3: "A `Donor` or `FinanceOfficer` requests a refund with an
        `amount_cents` of at least one cent and at most the gift's remaining unrefunded
        balance — the original `amount_cents` minus the already-accumulated
        `refunded_cents` — otherwise `ERR_REFUND_EXCEEDS_REMAINING`"

        Design: Corner/validations/v_refund_exceeds_remaining
        """
        bundle = create_active_bundle("user_c_v4", project_name="RX", contact_email="rx@x.org")
        donation = create_received_donation(bundle["project_id"], 100000)
        resp = api.request_refund(donation["id"],
                                  {"amount_cents": 100001, "reason": "too much"},
                                  make_donor_headers())
        validate_error(resp, ApiErrorId.ERR_REFUND_EXCEEDS_REMAINING)
        after = validate_success(api.get_donation(donation["id"], make_finance_officer_headers()))
        assert after["status"] == "RECEIVED"
        assert after["pending_refund_amount_cents"] is None

    def test_donor_cannot_decide_refund(self, api):
        """PRD §2.1: "A request whose role is not on the target endpoint's authorized
        list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST /fsa/donations/{id}/decide-refund is authorized for SponsorAdmin
        only; PRD §3.3: "The decision belongs to a `SponsorAdmin`".

        Design: Corner/rbac/rbac_donor_cannot_decide_refund
        """
        bundle = create_active_bundle("user_c_b1", project_name="RB1", contact_email="rb1@x.org")
        donation = create_received_donation(bundle["project_id"], 10000)
        request_refund(donation["id"], 10000, requester="donor")
        resp = api.decide_refund(donation["id"], {"decision": "APPROVE"}, make_donor_headers())
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        after = validate_success(api.get_donation(donation["id"], make_finance_officer_headers()))
        assert after["status"] == "REFUND_REQUESTED"


class TestRefundCascades:
    def test_full_refund_completes_donation_and_debits_fund(self, api):
        """PRD §3.3: "A full approval — the pending amount covering the entire remaining
        balance — moves the gift to `REFUNDED`, sets `refunded_cents` to the full
        `amount_cents`, adds the pending amount to the fund's `total_refunded_cents`,
        posts the same `DONATION_REFUND_DEBIT` entry"
        PRD §3.3: "Critically, fees are never reversed at refund time: the per-receipt
        fee stays charged against the fund until period close"
        Fund: 100,000 received - 100,000 refunded - 8,000 fee retained = -8,000 available.

        Design: Difficulty/transitive_cascade/refund_approval_voids_receipt_and_debits_fund
        """
        bundle = create_active_bundle("user_app_k", project_name="Lambda", contact_email="l@x.org")
        donation = create_receipted_donation(bundle["project_id"], 100000)
        request_refund(donation["id"], 100000, requester="donor", reason="donor remorse")
        decided = decide_refund(donation["id"], "APPROVE")
        assert decided["status"] == "REFUNDED"
        assert decided["refunded_cents"] == 100000
        fund = get_fund(bundle["fund_account_id"])
        assert fund["total_refunded_cents"] == 100000
        assert fund["total_fees_charged_cents"] == 8000, "fee retained until period close"
        assert fund["available_cents"] == -8000

    def test_full_refund_voids_issued_receipt(self, api):
        """PRD §3.3: "and transitions any `ISSUED` receipt to `VOIDED` with
        `void_reason` `FULL_REFUND` (no replacement is issued)."

        Design: Difficulty/transitive_cascade/refund_approval_voids_receipt_and_debits_fund
        """
        bundle = create_active_bundle("user_app_k2", project_name="Lambda2",
                                      contact_email="l2@x.org")
        donation = create_receipted_donation(bundle["project_id"], 100000)
        receipts_before, _ = validate_paginated(api.list_donation_receipts(
            donation["id"], make_finance_officer_headers()))
        assert len(receipts_before) == 1
        original = receipts_before[0]

        request_refund(donation["id"], 100000, requester="donor")
        decide_refund(donation["id"], "APPROVE")

        receipt = validate_success(api.get_receipt(original["id"], make_finance_officer_headers()))
        assert receipt["status"] == "VOIDED"
        assert receipt["void_reason"] == "FULL_REFUND"
        receipts_after, _ = validate_paginated(api.list_donation_receipts(
            donation["id"], make_finance_officer_headers()))
        assert len(receipts_after) == 1, "full refund issues no replacement receipt"

    def test_partial_refund_restores_receipted_and_voids_original(self, api):
        """PRD §3.3: "A partial approval — the pending amount below the full remaining
        balance — restores the prior state (`RECEIVED` or `RECEIPTED`), adds the pending
        amount to the gift's `refunded_cents` and the fund's `total_refunded_cents`,
        posts a `DONATION_REFUND_DEBIT` ledger entry, clears `pending_refund_amount_cents`,
        and stamps `refunded_at` from the logical clock"
        PRD §3.3: "when the gift had been receipted, the existing `ISSUED` receipt
        additionally transitions to `VOIDED` with `void_reason` `PARTIAL_REFUND` and a
        replacement receipt is issued whose `amount_cents` equals the gift amount minus
        total refunds, bearing a new `receipt_number`."

        Design: Difficulty/compensating_invariant/receipt_conservation_across_partial_refund
        """
        bundle = create_active_bundle("user_app_w", project_name="Psi", contact_email="ps@x.org")
        donation = create_receipted_donation(bundle["project_id"], 100000)
        receipts_before, _ = validate_paginated(api.list_donation_receipts(
            donation["id"], make_finance_officer_headers()))
        original = receipts_before[0]

        request_refund(donation["id"], 40000, requester="donor", reason="partial remorse")
        decided = decide_refund(donation["id"], "APPROVE")
        assert decided["status"] == "RECEIPTED"
        assert decided["refunded_cents"] == 40000

        r1 = validate_success(api.get_receipt(original["id"], make_finance_officer_headers()))
        assert r1["status"] == "VOIDED"
        assert r1["void_reason"] == "PARTIAL_REFUND"
        assert r1["amount_cents"] == 100000, "voided receipt keeps its original amount"

    def test_partial_refund_reissues_net_receipt_conserving_outstanding(self, api):
        """PRD §3.3: "a replacement receipt is issued whose `amount_cents` equals the
        gift amount minus total refunds, bearing a new `receipt_number`."
        PRD §3.3: "Receipt numbers are never reused"
        Conservation: outstanding ISSUED receipted cents == amount - refunded
        (100,000 - 40,000 = 60,000).

        Design: Difficulty/compensating_invariant/receipt_conservation_across_partial_refund
        """
        bundle = create_active_bundle("user_app_w2", project_name="Psi2",
                                      contact_email="ps2@x.org")
        donation = create_receipted_donation(bundle["project_id"], 100000)
        receipts_before, _ = validate_paginated(api.list_donation_receipts(
            donation["id"], make_finance_officer_headers()))
        original = receipts_before[0]

        request_refund(donation["id"], 40000, requester="donor")
        decide_refund(donation["id"], "APPROVE")

        receipts_after, _ = validate_paginated(api.list_donation_receipts(
            donation["id"], make_finance_officer_headers()))
        assert len(receipts_after) == 2
        replacement = [r for r in receipts_after if r["id"] != original["id"]]
        assert len(replacement) == 1, "exactly one replacement receipt is issued"
        r2 = replacement[0]
        assert r2["status"] == "ISSUED"
        assert r2["amount_cents"] == 60000, "replacement equals amount minus total refunds"
        assert r2["receipt_number"] != original["receipt_number"], "numbers are never reused"
        issued_total = sum(r["amount_cents"] for r in receipts_after if r["status"] == "ISSUED")
        assert issued_total == 60000, (
            "sum of ISSUED receipt amounts conserves amount_cents - refunded_cents")

    def test_available_reconciles_immediately_after_partial_refund(self, api):
        """PRD §2.6: "From these totals the account derives `available_cents`: total
        received, minus total refunded, minus total fees charged, plus total fees
        reversed, minus total disbursed, minus total transferred out, plus total
        adjustments, minus committed, minus reserved."
        PRD §3.3: "Critically, fees are never reversed at refund time: the per-receipt
        fee stays charged against the fund until period close"
        100,000 received (fee 8,000) then 40,000 refunded -> available 52,000.

        Design: Corner/cross_cutting_complexity_layers/layer_derived_available_after_partial_refund
        """
        bundle = create_active_bundle("user_c_o3", project_name="DR", contact_email="drc@x.org")
        donation = create_received_donation(bundle["project_id"], 100000)
        request_refund(donation["id"], 40000, requester="donor", reason="partial")
        decide_refund(donation["id"], "APPROVE")
        fund = get_fund(bundle["fund_account_id"])
        assert fund["available_cents"] == 52000
        assert fund["total_refunded_cents"] == 40000
        assert fund["total_fees_charged_cents"] == 8000, "reversal deferred to close-period"
