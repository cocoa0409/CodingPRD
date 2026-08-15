"""Invoicing, the final money variant, and the depreciation-recovery waterfall.

Covers provisional-vs-final variant divergence, the pinned recovery evaluation
order (deductible snapshot -> cleared advance -> gap -> capped recovery), the
invoice-issue cascade (recovery payment + posture flip), and estimate locking at
invoice creation.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_approved_claim, setup_in_progress_claim, setup_complete_claim,
    setup_invoiced_claim, read_estimate, read_claim, list_claim_payments,
    find_payment, make_and_sign_wa, TEST_USERS,
)

ADMIN = TEST_USERS["contractor_admin_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]

# Carrier-standard water-restoration estimate: three trades so O&P compounds.
_ACME_CARRIER = {"name": "Acme Mutual", "tax_rate": 0.07, "overhead_rate": 0.10,
                 "profit_rate": 0.10, "o_and_p_min_trades": 3}
_ACME_ENTRIES = (
    {"category_code": "WTR-DEMO", "trade": "DEMOLITION", "kind": "LABOR",
     "unit": "SF", "unit_price_cents": 200, "tax_applicable": False,
     "o_and_p_eligible": True, "default_depreciation_pct": 0.10},
    {"category_code": "DRY-SHEET", "trade": "DRYWALL", "kind": "MATERIAL",
     "unit": "SF", "unit_price_cents": 150, "tax_applicable": True,
     "o_and_p_eligible": True, "default_depreciation_pct": 0.20},
    {"category_code": "PNT-WALL", "trade": "PAINT", "kind": "MATERIAL",
     "unit": "SF", "unit_price_cents": 120, "tax_applicable": True,
     "o_and_p_eligible": True, "default_depreciation_pct": 0.25},
)
_ACME_POLICY = {"coverage_a_limit_cents": 100000000, "flat_deductible_cents": 100000,
                "ordinance_coverage_pct": 0.10, "ordinance_flat_cap_cents": 250000}

_ROOF_ENTRY = ({"category_code": "RFR-1", "trade": "ROOFING", "kind": "LABOR",
                "unit": "SF", "unit_price_cents": 200,
                "default_depreciation_pct": 0.20},)


class TestProvisionalVsFinalVariant:
    def test_provisional_rcv_acv_vs_final_invoice(self, api):
        """PRD §3.9: "The invoice's `total_cents` is the **final-variant** grand
        total: every approved estimate is recomputed with `qty_actual` overriding
        the planned quantity wherever recorded (a recorded zero excludes the
        line), removed lines excluded, per-line rounding, tax, the trade gate
        re-evaluated on the final line set, overhead-and-profit compounding, and
        the depreciation split all reapplied exactly as §3.4 specifies — so the
        two variants diverge whenever actuals differ from plan."
        PRD §3.9: "the recovery is the lesser of the claim's
        `recoverable_depreciation_cents` and that gap — never exceeding the
        depreciation withheld, and never exceeding what the customer actually spent
        beyond advance plus deductible, so a smaller final invoice reduces the
        recovery cent-for-cent."

        Design: Difficulty/dual_variant_calc/provisional_rcv_acv_vs_final_invoice
        """
        ctx = setup_in_progress_claim(
            cause_of_loss="WATER", carrier_overrides=_ACME_CARRIER,
            policy_overrides=_ACME_POLICY, entry_specs=_ACME_ENTRIES,
            line_specs=[(0, 10000), (1, 10000), (2, 10000)],
            direct_pay=True, clear_advance=True)
        claim_id = ctx["claim"]["id"]
        # L2 completes at 9,000 of the planned 10,000 (others unrecorded => plan)
        validate_success(api.record_actuals(
            ctx["estimate"]["id"],
            {"entries": [{"estimate_line_id": ctx["lines"][1]["id"],
                          "qty_actual": 9000}]}, ESTIMATOR), 200)
        validate_success(api.complete_work(claim_id, ADMIN), 200)
        invoice = validate_success(api.create_invoice(claim_id, ADMIN), 201)
        # final variant: RCV 4,550,000 + OH 455,000 + profit 500,500 + tax 178,500
        assert invoice["total_cents"] == 5684000
        est = read_estimate(ctx["estimate"]["id"])
        # provisional variant: 4,700,000 RCV + 470,000 OH + 517,000 profit + 189,000 tax
        assert est["grand_total_cents"] == 5876000
        assert est["status"] == "LOCKED", "invoice creation locks approved estimates"
        assert invoice["total_cents"] != est["grand_total_cents"], \
            "the two variants diverge for identical approved scope"
        validate_success(api.issue_invoice(invoice["id"], ADMIN), 200)
        recovery = find_payment(claim_id, "DEPRECIATION_RECOVERY")
        # min(800,000 recoverable, 5,684,000 - 4,976,000 advance - 100,000 deductible)
        assert recovery["amount_cents"] == 608000, \
            "capped below the 800,000 projected at approval"
        assert recovery["status"] == "REQUESTED"
        assert recovery["auto_created"] is True
        assert recovery["invoice_id"] == invoice["id"]

    def test_provisional_basis_preserved_through_actuals_recording(self, api):
        """PRD §3.8: "Recording actuals increments the estimate's `version` but
        deliberately does **not** recompute the estimate's provisional totals —
        the provisional basis agreed at approval is preserved; actuals take effect
        only in the final-variant invoice of §3.9, where a `qty_actual` of zero
        excludes the line entirely."
        PRD §3.4: "At the claim level, `rcv_total_cents`, `acv_total_cents`, and
        `recoverable_depreciation_cents` are recomputed whenever the approved
        estimate set changes: each is the sum of the same-named estimate figure
        over the claim's estimates in `APPROVED` or `LOCKED` status."

        Design: Difficulty/dual_variant_calc/provisional_rcv_acv_vs_final_invoice
        """
        ctx = setup_approved_claim(
            cause_of_loss="WATER", carrier_overrides=_ACME_CARRIER,
            policy_overrides=_ACME_POLICY, entry_specs=_ACME_ENTRIES,
            line_specs=[(0, 10000), (1, 10000), (2, 10000)])
        claim = read_claim(ctx["claim"]["id"])
        assert claim["rcv_total_cents"] == 5876000
        assert claim["acv_total_cents"] == 5076000, "grand minus 800,000 depreciation"
        assert claim["recoverable_depreciation_cents"] == 800000
        make_and_sign_wa(ctx, direct_pay=True)
        advance = find_payment(ctx["claim"]["id"], "ACV_ADVANCE")
        # deductible netted out of the first carrier payment: 5,076,000 - 100,000
        assert advance["amount_cents"] == 4976000
        assert advance["auto_created"] is True
        assert advance["type"] == "ACV_ADVANCE"
        assert advance["direction"] == "CARRIER_TO_CONTRACTOR"
        validate_success(api.start_work(ctx["claim"]["id"], ADMIN), 200)
        before = read_estimate(ctx["estimate"]["id"])
        validate_success(api.record_actuals(
            ctx["estimate"]["id"],
            {"entries": [{"estimate_line_id": ctx["lines"][1]["id"],
                          "qty_actual": 9000}]}, ESTIMATOR), 200)
        after = read_estimate(ctx["estimate"]["id"])
        assert after["grand_total_cents"] == 5876000, \
            "provisional totals preserved after record-actuals"
        assert after["version"] == before["version"] + 1


class TestDeductibleRecoveryEvaluationOrder:
    _PCT_POLICY = {"coverage_a_limit_cents": 2500000,
                   "deductible_type": "PERCENT_OF_COVERAGE_A",
                   "deductible_pct": 0.02, "recoverable_depreciation": True}

    def test_deductible_recovery_evaluation_order(self, api):
        """PRD §3.2: "for a `PERCENT_OF_COVERAGE_A` policy it is the deductible
        percentage multiplied by `coverage_a_limit_cents`, rounded half up."
        PRD §3.9: "It also runs the depreciation-recovery waterfall in a pinned
        order: start from the claim's `deductible_cents` (the policy snapshot,
        never derived from payments); take `acv_advance_paid` as the sum of
        `CLEARED` `ACV_ADVANCE` payments; compute the actual spend gap as the
        invoice's `total_cents` minus `acv_advance_paid` minus `deductible_cents`,
        floored at zero; the recovery is the lesser of the claim's
        `recoverable_depreciation_cents` and that gap"

        Design: Difficulty/combinatorial_formula/deductible_recovery_evaluation_order
        """
        ctx = setup_invoiced_claim(
            cause_of_loss="WIND", carrier_overrides={"name": "ZeroTax Mutual",
                                                     "tax_rate": 0},
            policy_overrides=self._PCT_POLICY, entry_specs=_ROOF_ENTRY,
            line_specs=[(0, 1000)], direct_pay=True, clear_advance=True,
            issue=False)
        # percentage deductible: round_half_up(0.02 * 2,500,000) = 50,000,
        # snapshotted at creation before any payment exists
        claim = read_claim(ctx["claim"]["id"])
        assert claim["deductible_cents"] == 50000
        # advance = acv 160,000 - deductible 50,000
        assert ctx["advance"]["amount_cents"] == 110000
        assert ctx["invoice"]["total_cents"] == 200000
        validate_success(api.issue_invoice(ctx["invoice"]["id"], ADMIN), 200)
        recovery = find_payment(ctx["claim"]["id"], "DEPRECIATION_RECOVERY")
        # min(recoverable 40,000, 200,000 - 110,000 - 50,000): deductible first,
        # advance second, recovery last
        assert recovery["amount_cents"] == 40000

    def test_zero_gap_produces_no_recovery_payment(self, api):
        """PRD §3.9: "compute the actual spend gap as the invoice's `total_cents`
        minus `acv_advance_paid` minus `deductible_cents`, floored at zero; the
        recovery is the lesser of the claim's `recoverable_depreciation_cents` and
        that gap"
        PRD §3.9: "When the recovery is positive, the system auto-creates a
        `Payment` of `type` `DEPRECIATION_RECOVERY`, direction
        `CARRIER_TO_CONTRACTOR`, status `REQUESTED`, `auto_created` true, with
        `invoice_id` set to this invoice."

        Design: Difficulty/combinatorial_formula/deductible_recovery_evaluation_order
        """
        # halved actual spend: invoice 100,000 < advance 110,000 + deductible 50,000
        # -> gap floored at 0 -> no recovery payment auto-created.
        ctx = setup_in_progress_claim(
            cause_of_loss="WIND", carrier_overrides={"name": "ZeroTax Mutual",
                                                     "tax_rate": 0},
            policy_overrides=self._PCT_POLICY, entry_specs=_ROOF_ENTRY,
            line_specs=[(0, 1000)], direct_pay=True, clear_advance=True)
        validate_success(api.record_actuals(
            ctx["estimate"]["id"],
            {"entries": [{"estimate_line_id": ctx["lines"][0]["id"],
                          "qty_actual": 500}]}, ESTIMATOR), 200)
        validate_success(api.complete_work(ctx["claim"]["id"], ADMIN), 200)
        invoice = validate_success(api.create_invoice(ctx["claim"]["id"], ADMIN), 201)
        assert invoice["total_cents"] == 100000
        validate_success(api.issue_invoice(invoice["id"], ADMIN), 200)
        payments = list_claim_payments(ctx["claim"]["id"])
        assert len(payments) == 1, "no DEPRECIATION_RECOVERY auto-created at gap 0"
        assert payments[0]["type"] == "ACV_ADVANCE"


class TestInvoiceIssueCascade:
    def test_invoice_issue_spawns_recovery_payment_and_posture(self, api):
        """PRD §3.9: "Issuing the invoice moves it `DRAFT → ISSUED`, but only while
        the claim is `COMPLETE`; any other combination is
        `ERR_INVOICE_NOT_ISSUABLE` (HTTP 409)."
        PRD §3.9: "When the recovery is positive, the system auto-creates a
        `Payment` of `type` `DEPRECIATION_RECOVERY`, direction
        `CARRIER_TO_CONTRACTOR`, status `REQUESTED`, `auto_created` true, with
        `invoice_id` set to this invoice."
        PRD §3.9: "An issued-but-unsettled invoice sets the claim's
        `payment_posture` to `DEPRECIATION_PENDING`."

        Design: Difficulty/transitive_cascade/invoice_issue_spawns_recovery_payment_and_posture
        """
        ctx = setup_invoiced_claim(
            cause_of_loss="WIND", carrier_overrides={"name": "ZeroTax Mutual",
                                                     "tax_rate": 0},
            policy_overrides={"coverage_a_limit_cents": 5000000,
                              "deductible_type": "FLAT", "flat_deductible_cents": 10000,
                              "recoverable_depreciation": True},
            entry_specs=_ROOF_ENTRY, line_specs=[(0, 1000)],
            direct_pay=True, clear_advance=True, issue=False)
        # advance = acv 160,000 - deductible 10,000
        assert ctx["advance"]["amount_cents"] == 150000
        issued = validate_success(api.issue_invoice(ctx["invoice"]["id"], ADMIN), 200)
        assert issued["status"] == "ISSUED", "hop 1"
        recovery = find_payment(ctx["claim"]["id"], "DEPRECIATION_RECOVERY")
        assert recovery["status"] == "REQUESTED", "hop 2: auto-created by the issue"
        # min(40,000 recoverable, 200,000 - 150,000 - 10,000)
        assert recovery["amount_cents"] == 40000
        assert recovery["invoice_id"] == ctx["invoice"]["id"]
        claim = read_claim(ctx["claim"]["id"])
        assert claim["status"] == "INVOICED", "hop 3"
        assert claim["payment_posture"] == "DEPRECIATION_PENDING"

    def test_issue_on_acv_only_policy_creates_no_recovery(self, api):
        """PRD §3.4: "The estimate's `depreciation_total_cents` sums these, while
        `recoverable_depreciation_cents` sums only the portions from lines whose
        `depreciation_recoverable` is true, and only when the claim's policy has
        `recoverable_depreciation` true — an ACV-only policy recovers nothing."
        PRD §3.9: "An issued-but-unsettled invoice sets the claim's
        `payment_posture` to `DEPRECIATION_PENDING`."

        Design: Difficulty/transitive_cascade/invoice_issue_spawns_recovery_payment_and_posture
        """
        ctx = setup_invoiced_claim(
            cause_of_loss="WIND", carrier_overrides={"name": "ZeroTax Mutual",
                                                     "tax_rate": 0},
            policy_overrides={"coverage_a_limit_cents": 5000000,
                              "deductible_type": "FLAT", "flat_deductible_cents": 10000,
                              "recoverable_depreciation": False},
            entry_specs=_ROOF_ENTRY, line_specs=[(0, 1000)],
            direct_pay=True, clear_advance=True, issue=False)
        validate_success(api.issue_invoice(ctx["invoice"]["id"], ADMIN), 200)
        payments = list_claim_payments(ctx["claim"]["id"])
        assert len(payments) == 1, "ACV-only policy recovers nothing"
        assert payments[0]["type"] == "ACV_ADVANCE"
        claim = read_claim(ctx["claim"]["id"])
        assert claim["status"] == "INVOICED"
        assert claim["payment_posture"] == "DEPRECIATION_PENDING"


class TestInvoiceCreationLocking:
    def test_invoice_creation_locks_approved_estimates(self, api):
        """PRD §3.9: "Creation also locks the estimate set: every `APPROVED`
        estimate of the claim moves to `LOCKED`, freezing it against further
        record-actuals."
        PRD §3.9: "Creation requires the claim `COMPLETE` (priority 6) and at most
        one non-`VOIDED` invoice per claim — a second active invoice is
        `ERR_DUPLICATE_ACTIVE_INVOICE` (HTTP 409, priority 8)."

        Design: Difficulty/cross_entity_state_dependency/invoice_creation_locks_approved_estimates
        """
        ctx = setup_complete_claim(
            cause_of_loss="FIRE",
            entry_specs=({"category_code": "GEN-1", "trade": "GENERAL",
                          "kind": "LABOR", "unit": "EA", "unit_price_cents": 200,
                          "default_depreciation_pct": 0},),
            line_specs=[(0, 2500)], direct_pay=False)
        invoice = validate_success(
            api.create_invoice(ctx["claim"]["id"], ADMIN), 201)
        # final variant with no actuals recorded == provisional
        assert invoice["total_cents"] == 500000
        est = read_estimate(ctx["estimate"]["id"])
        assert est["status"] == "LOCKED", "invoice creation froze the estimate"
        res = api.create_invoice(ctx["claim"]["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_ACTIVE_INVOICE)

    def test_locked_estimate_refuses_record_actuals(self, api):
        """PRD §3.8: "Once an estimate is `LOCKED`, record-actuals is refused with
        `ERR_ESTIMATE_NOT_EDITABLE`."

        Design: Difficulty/cross_entity_state_dependency/invoice_creation_locks_approved_estimates
        """
        ctx = setup_invoiced_claim(
            cause_of_loss="FIRE",
            entry_specs=({"category_code": "GEN-1", "trade": "GENERAL",
                          "kind": "LABOR", "unit": "EA", "unit_price_cents": 200,
                          "default_depreciation_pct": 0},),
            line_specs=[(0, 2500)], direct_pay=False, issue=False)
        res = api.record_actuals(
            ctx["estimate"]["id"],
            {"entries": [{"estimate_line_id": ctx["lines"][0]["id"],
                          "qty_actual": 2000}]}, ESTIMATOR)
        validate_error(res, ApiErrorId.ERR_ESTIMATE_NOT_EDITABLE)

    def test_invoice_issue_twice_returns_not_issuable(self, api):
        """PRD §3.9: "Issuing the invoice moves it `DRAFT → ISSUED`, but only while
        the claim is `COMPLETE`; any other combination is
        `ERR_INVOICE_NOT_ISSUABLE` (HTTP 409)."

        Design: Corner/validations/invoice_issue_twice_returns_not_issuable
        """
        ctx = setup_invoiced_claim(
            cause_of_loss="FIRE",
            entry_specs=({"category_code": "GEN-1", "trade": "GENERAL",
                          "kind": "LABOR", "unit": "EA", "unit_price_cents": 200,
                          "default_depreciation_pct": 0},),
            line_specs=[(0, 2500)], direct_pay=False)
        assert ctx["invoice"]["status"] == "ISSUED"
        res = api.issue_invoice(ctx["invoice"]["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_INVOICE_NOT_ISSUABLE)
