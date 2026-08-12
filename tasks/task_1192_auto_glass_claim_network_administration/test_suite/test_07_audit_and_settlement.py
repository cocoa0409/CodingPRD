"""Invoice audit, settlement cascades, money conservation, shop audit scores."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, validate_paginated,
    ApiErrorId, assert_invoice_conservation, part_line, audit_decision_payload, make_shop_operator_headers,
    make_adjuster_headers, make_auditor_headers,
    make_part, make_claim, add_disclosure, verify_claim, route_claim,
    accept_work_order, schedule_work_order, complete_work_order,
    create_invoice, submit_invoice, approve_invoice, dispute_invoice,
    get_claim, get_invoice, get_shop, set_clock,
    setup_network, setup_claim_verified, setup_work_order_completed,
    setup_invoice_submitted, setup_invoice_approved, setup_invoice_paid,
)

ADMIN = TEST_USERS["admin_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def _full_approve_adjustment(api, invoice_id, amounts=None, origin="AFTERMARKET"):
    lines, _meta = validate_paginated(api.list_invoice_line_items(invoice_id, ADMIN))
    if amounts is None:
        amounts = [ln["line_total_cents"] for ln in lines]
    return [
        {"line_index": i, "approved_amount_cents": amt, "approved_origin": origin}
        for i, amt in enumerate(amounts)
    ]


class TestSegregationOfDuties:
    def test_segregation_of_duties_violation(self, api):
        """PRD §3.5: "Segregation of duties is enforced here: the auditor's
        `X-User-ID` must differ from the claim's `coverage_verified_by_user_id`,
        so the adjuster who verified the claim's coverage may not audit that
        claim's invoices; a violation is rejected with
        `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403)."

        Design: Corner/validations/segregation_of_duties_violation
        """
        net = setup_network()
        claim = make_claim(net["policyholder"], net["policy"],
                           estimated_repair_cost_cents=95000)
        add_disclosure(claim["id"], net["policyholder"]["id"])
        # Coverage verified by the opaque operator id 'adj-shared-1'.
        verify_claim(claim["id"], adjuster_headers=make_adjuster_headers("adj-shared-1"))
        wo = route_claim(claim["id"], adjuster_headers=make_adjuster_headers("adj-other-2"))
        shop_id = wo["shop_id"]
        accept_work_order(wo["id"], shop_id)
        schedule_work_order(wo["id"], shop_id,
                            start="2026-05-02T10:00:00Z", end="2026-05-02T11:30:00Z")
        set_clock("2026-05-02T12:30:00Z")
        complete_work_order(wo["id"], shop_id)
        invoice = create_invoice(wo["id"], shop_id,
                                 [part_line(net["part"]["id"], 95000)])
        invoice = submit_invoice(invoice["id"], shop_id)

        same_user = api.create_audit_decision(
            invoice["id"],
            audit_decision_payload(
                "APPROVE", _full_approve_adjustment(api, invoice["id"])),
            make_auditor_headers("adj-shared-1"))
        validate_error(same_user, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)
        assert get_invoice(invoice["id"])["status"] == "SUBMITTED"

        other = api.create_audit_decision(
            invoice["id"],
            audit_decision_payload(
                "APPROVE", _full_approve_adjustment(api, invoice["id"])),
            make_auditor_headers("auditor-9"))
        assert validate_success(other, 200)["status"] == "APPROVED"
        assert get_claim(claim["id"])["coverage_verified_by_user_id"] == "adj-shared-1"
        assert get_invoice(invoice["id"])["audited_by_user_id"] == "auditor-9"


class TestAuditCompleteness:
    def test_audit_incomplete_coverage_rejected(self, api):
        """PRD §3.5: "For `APPROVE` and `DISPUTE`, the `adjustment_lines` must
        cover every line item exactly once, and each line's
        `approved_amount_cents` must not exceed its `line_total_cents`;
        incomplete coverage or an over-line approval is rejected with
        `ERR_AUDIT_INCOMPLETE` (HTTP 422)."

        Design: Corner/validations/audit_incomplete_coverage_rejected
        """
        ctx = _setup_two_line_invoice(api)
        invoice = ctx["invoice"]
        missing = api.create_audit_decision(
            invoice["id"],
            audit_decision_payload("APPROVE", [
                {"line_index": 0, "approved_amount_cents": 95000,
                 "approved_origin": "AFTERMARKET"}]),
            AUDITOR)
        validate_error(missing, ApiErrorId.ERR_AUDIT_INCOMPLETE)
        over = api.create_audit_decision(
            invoice["id"],
            audit_decision_payload("APPROVE", [
                {"line_index": 0, "approved_amount_cents": 95000,
                 "approved_origin": "AFTERMARKET"},
                {"line_index": 1, "approved_amount_cents": 96000,
                 "approved_origin": "AFTERMARKET"}]),
            AUDITOR)
        validate_error(over, ApiErrorId.ERR_AUDIT_INCOMPLETE)
        assert get_invoice(invoice["id"])["status"] == "SUBMITTED"


def _setup_two_line_invoice(api):
    ctx = setup_work_order_completed(
        claim_overrides={"estimated_repair_cost_cents": 200000})
    invoice = create_invoice(
        ctx["work_order"]["id"], ctx["work_order"]["shop_id"],
        [part_line(ctx["part"]["id"], 95000),
         part_line(ctx["part"]["id"], 95000)])
    invoice = submit_invoice(invoice["id"], ctx["work_order"]["shop_id"])
    ctx["invoice"] = invoice
    return ctx


class TestInvoiceStateGates:
    def test_invoice_terminal_paid_lockdown(self, api):
        """PRD §3.5: "Submission requires the invoice to be in `DRAFT` or
        `DISPUTED` (else `ERR_INVOICE_NOT_SUBMITTABLE`)..."
        PRD §3.5: "a `NetworkAuditor`, who decides a `SUBMITTED` invoice (else
        `ERR_INVOICE_NOT_SUBMITTED`)..."

        Design: Corner/state_machines/invoice_terminal_paid_lockdown
        """
        ctx = setup_invoice_paid()
        invoice = ctx["invoice"]
        sub = api.submit_invoice(invoice["id"], {},
                                 make_shop_operator_headers(ctx["shop"]["id"]))
        validate_error(sub, ApiErrorId.ERR_INVOICE_NOT_SUBMITTABLE)
        aud = api.create_audit_decision(
            invoice["id"],
            audit_decision_payload(
                "APPROVE", _full_approve_adjustment(api, invoice["id"])),
            AUDITOR)
        validate_error(aud, ApiErrorId.ERR_INVOICE_NOT_SUBMITTED)
        assert get_invoice(invoice["id"])["status"] == "PAID"

    def test_invoice_pay_before_approve_rejected(self, api):
        """PRD §3.5: "Paying an invoice requires it to be `APPROVED` (else
        `ERR_INVOICE_NOT_APPROVED`)..."

        Design: Corner/state_machines/invoice_pay_before_approve_rejected
        """
        ctx = setup_invoice_submitted()
        resp = api.pay_invoice(ctx["invoice"]["id"], AUDITOR)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_APPROVED)
        assert get_invoice(ctx["invoice"]["id"])["status"] == "SUBMITTED"

    def test_invoice_reject_denies_claim(self, api):
        """PRD §3.5: "On `REJECT`, the invoice becomes `REJECTED` and the claim
        cascades `INVOICED` → `DENIED`."

        Design: Corner/state_machines/invoice_reject_denies_claim
        """
        ctx = setup_invoice_submitted()
        resp = api.create_audit_decision(
            ctx["invoice"]["id"], audit_decision_payload("REJECT"), AUDITOR)
        assert validate_success(resp, 200)["status"] == "REJECTED"
        assert get_claim(ctx["claim"]["id"])["status"] == "DENIED"


class TestRbacAudit:
    def test_rbac_shop_operator_cannot_audit(self, api):
        """PRD §2.1: "Access to specific operations is restricted by role; an
        attempt to perform an action outside the caller's designated role is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §3.5: "Audit is the exclusive province of a `NetworkAuditor`..."

        Design: Corner/rbac/rbac_shop_operator_cannot_audit
        """
        ctx = setup_invoice_submitted()
        resp = api.create_audit_decision(
            ctx["invoice"]["id"],
            audit_decision_payload(
                "APPROVE", _full_approve_adjustment(api, ctx["invoice"]["id"])),
            make_shop_operator_headers(ctx["shop"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert get_invoice(ctx["invoice"]["id"])["status"] == "SUBMITTED"


class TestOemEndorsement:
    def test_oem_endorsement_waives_upcharge(self, api):
        """PRD §3.5: "the endorsement waives the upcharge entirely."
        PRD §3.5: "The `customer_responsibility_cents` is the smaller of the
        invoice's `approved_total_cents` and the sum of the claim's
        `deductible_applied_cents` plus its `oem_upcharge_cents`..."

        Design: Corner/calculations/oem_endorsement_waives_upcharge
        """
        ctx = setup_invoice_approved(
            oem_endorsement=True,
            part_overrides={"part_number": "OEM-WS-1", "part_origin": "OEM",
                            "nags_list_price_cents": 120000},
            part_price_cents=120000,
            claim_overrides={"estimated_repair_cost_cents": 200000},
            shop_overrides={"oem_certified": True},
        )
        claim = get_claim(ctx["claim"]["id"])
        assert claim["oem_upcharge_cents"] == 0
        assert claim["customer_responsibility_cents"] == 50000
        assert claim["insurer_payment_cents"] == 70000


# ---------------------------------------------------------------------------
# Difficulty: provisional vs final deductible variants on Claim
# ---------------------------------------------------------------------------

class TestDeductibleProvisionalVsFinal:
    def _setup(self):
        """FL (no zero-ded, tax 0), deductible 50000, no OEM endorsement,
        PLATINUM shop, OEM 120000 + AM 100000 parts, claim est 200000."""
        net = setup_network(
            state_code="FL", zero_deductible_windshield=False, tax_bp=0,
            deductible_cents=50000, oem_endorsement=False,
            shop_overrides={"agreement_tier": "PLATINUM", "oem_certified": True,
                            "bay_count": 2},
            part_overrides={"part_number": "AM-WS-1",
                            "nags_list_price_cents": 100000},
        )
        net["part_oem"] = make_part(part_number="OEM-WS-1", part_origin="OEM",
                                    nags_list_price_cents=120000)
        net["claim"] = make_claim(net["policyholder"], net["policy"],
                                  estimated_repair_cost_cents=200000,
                                  description="cracked windshield")
        add_disclosure(net["claim"]["id"], net["policyholder"]["id"],
                       disclosure_channel="PORTAL")
        return net

    def test_provisional_and_final_deductible_basis(self, api):
        """PRD §3.2: "The provisional customer responsibility, stored as
        `provisional_customer_responsibility_cents`, is zero when the
        zero-deductible rule applies and otherwise the smaller of the effective
        deductible and the intake `estimated_repair_cost_cents`..."
        PRD §3.2: "On success the claim moves `SUBMITTED` → `COVERAGE_VERIFIED`;
        the final deductible basis is stored in `deductible_applied_cents`..."

        Design: Difficulty/dual_variant_calc/deductible_provisional_vs_final_on_claim
        """
        net = self._setup()
        claim = get_claim(net["claim"]["id"])
        # min(50000 effective deductible, 200000 estimate) at intake.
        assert claim["provisional_customer_responsibility_cents"] == 50000
        verified = verify_claim(claim["id"])
        assert verified["deductible_applied_cents"] == 50000

    def test_final_settlement_after_full_approve(self, api):
        """PRD §3.5: "The claim's `oem_upcharge_cents` is the sum, over approved
        `PART` lines whose final origin — the `approved_origin` when set,
        otherwise the `origin_claimed` — is `OEM` and whose policy does not
        carry the `oem_endorsement`, of one quarter of each such line's approved
        amount, each quarter rounded half-up to whole cents per line and then
        summed... The `customer_responsibility_cents` is the smaller of the
        invoice's `approved_total_cents` and the sum of the claim's
        `deductible_applied_cents` plus its `oem_upcharge_cents`... The
        `insurer_payment_cents` is the approved total minus the customer
        responsibility, floored at zero."

        Design: Difficulty/dual_variant_calc/deductible_provisional_vs_final_on_claim
        """
        net = self._setup()
        claim = verify_claim(net["claim"]["id"])
        wo = route_claim(claim["id"])
        shop_id = net["shop"]["id"]
        accept_work_order(wo["id"], shop_id)
        schedule_work_order(wo["id"], shop_id,
                            start="2026-05-02T10:00:00Z",
                            end="2026-05-02T12:00:00Z")
        set_clock("2026-05-02T13:00:00Z")
        complete_work_order(wo["id"], shop_id)
        invoice = create_invoice(wo["id"], shop_id, [
            part_line(net["part_oem"]["id"], 120000, origin_claimed="OEM"),
            part_line(net["part"]["id"], 75000),
        ])
        invoice = submit_invoice(invoice["id"], shop_id)
        approve_invoice(invoice["id"], [
            {"line_index": 0, "approved_amount_cents": 120000,
             "approved_origin": "OEM"},
            {"line_index": 1, "approved_amount_cents": 75000,
             "approved_origin": "AFTERMARKET"},
        ])
        invoice = get_invoice(invoice["id"])
        assert invoice["approved_total_cents"] == 195000
        assert invoice["adjustment_total_cents"] == 0
        claim = get_claim(net["claim"]["id"])
        # round_half_up(120000 x 0.25) on the single approved OEM line.
        assert claim["oem_upcharge_cents"] == 30000
        # min(195000, 50000 + 30000)
        assert claim["customer_responsibility_cents"] == 80000
        assert claim["insurer_payment_cents"] == 115000


class TestZeroDeductibleVariants:
    def _setup(self):
        """FL zero-deductible state; STANDARD OEM-certified shop; OEM 120000."""
        return setup_network(
            state_code="FL", zero_deductible_windshield=True, tax_bp=0,
            deductible_cents=50000, oem_endorsement=False,
            shop_overrides={"oem_certified": True},
            part_overrides={"part_number": "OEM-WS-1", "part_origin": "OEM",
                            "nags_list_price_cents": 120000},
        )

    def test_zero_deductible_provisional_and_basis(self, api):
        """PRD §3.2: "The zero-deductible rule applies when all three conditions
        hold: the regulation's `zero_deductible_windshield` is true, the claim's
        `part_category` is `WINDSHIELD`, and the policy's `coverage_type` is
        `COMPREHENSIVE`. The provisional customer responsibility ... is zero
        when the zero-deductible rule applies..."
        PRD §3.2: "the final deductible basis is stored in
        `deductible_applied_cents` as zero under the zero-deductible rule..."

        Design: Difficulty/dual_variant_calc/deductible_zero_state_provisional_vs_final_zero_deductible
        """
        net = self._setup()
        claim = make_claim(net["policyholder"], net["policy"],
                           estimated_repair_cost_cents=90000,
                           description="zero-ded claim")
        assert claim["provisional_customer_responsibility_cents"] == 0
        verified = verify_claim(claim["id"])
        assert verified["deductible_applied_cents"] == 0

    def test_zero_deductible_final_still_adds_oem_upcharge(self, api):
        """PRD §3.5: "The `customer_responsibility_cents` is the smaller of the
        invoice's `approved_total_cents` and the sum of the claim's
        `deductible_applied_cents` plus its `oem_upcharge_cents` — it is capped
        at the approved total."

        Design: Difficulty/dual_variant_calc/deductible_zero_state_provisional_vs_final_zero_deductible
        """
        net = self._setup()
        claim = make_claim(net["policyholder"], net["policy"],
                           estimated_repair_cost_cents=90000,
                           description="zero-ded claim")
        add_disclosure(claim["id"], net["policyholder"]["id"],
                       disclosure_channel="PORTAL")
        claim = verify_claim(claim["id"])
        wo = route_claim(claim["id"])
        shop_id = net["shop"]["id"]
        accept_work_order(wo["id"], shop_id)
        schedule_work_order(wo["id"], shop_id,
                            start="2026-05-02T10:00:00Z",
                            end="2026-05-02T11:00:00Z")
        set_clock("2026-05-02T12:00:00Z")
        complete_work_order(wo["id"], shop_id)
        invoice = create_invoice(wo["id"], shop_id, [
            part_line(net["part"]["id"], 120000, origin_claimed="OEM")])
        invoice = submit_invoice(invoice["id"], shop_id)
        approve_invoice(invoice["id"], [
            {"line_index": 0, "approved_amount_cents": 120000,
             "approved_origin": "OEM"}])
        claim = get_claim(claim["id"])
        assert claim["oem_upcharge_cents"] == 30000
        # Final variant: min(120000, 0 + 30000) despite the zero deductible.
        assert claim["customer_responsibility_cents"] == 30000
        assert claim["insurer_payment_cents"] == 90000


class TestCustomerResponsibilityCap:
    def _setup_submitted(self):
        return setup_invoice_submitted(
            claim_overrides={"estimated_repair_cost_cents": 200000})

    def test_partial_approval_below_deductible_caps_responsibility(self, api):
        """PRD §3.5: "The `customer_responsibility_cents` is the smaller of the
        invoice's `approved_total_cents` and the sum of the claim's
        `deductible_applied_cents` plus its `oem_upcharge_cents` — it is capped
        at the approved total. The `insurer_payment_cents` is the approved total
        minus the customer responsibility, floored at zero."

        Design: Difficulty/combinatorial_formula/customer_responsibility_cap_circular_mode_c
        """
        ctx = self._setup_submitted()
        approve_invoice(ctx["invoice"]["id"], [
            {"line_index": 0, "approved_amount_cents": 30000,
             "approved_origin": "AFTERMARKET"}])
        invoice = get_invoice(ctx["invoice"]["id"])
        assert invoice["approved_total_cents"] == 30000  # 30000 + 0 tax
        assert invoice["adjustment_total_cents"] == 65000
        assert_invoice_conservation(invoice)
        claim = get_claim(ctx["claim"]["id"])
        # min(30000 approved, 50000 deductible + 0 upcharge) collapses to 30000.
        assert claim["customer_responsibility_cents"] == 30000
        assert claim["insurer_payment_cents"] == 0

    def test_deductible_basis_unchanged_by_cap(self, api):
        """PRD §3.2: "the final deductible basis is stored in
        `deductible_applied_cents` as zero under the zero-deductible rule and as
        the effective deductible otherwise" — the stored basis is independent of
        the later approval cap.

        Design: Difficulty/combinatorial_formula/customer_responsibility_cap_circular_mode_c
        """
        ctx = self._setup_submitted()
        approve_invoice(ctx["invoice"]["id"], [
            {"line_index": 0, "approved_amount_cents": 30000,
             "approved_origin": "AFTERMARKET"}])
        claim = get_claim(ctx["claim"]["id"])
        assert claim["deductible_applied_cents"] == 50000


class TestInvoicePaySettlesClaim:
    def test_pay_moves_invoice_to_paid_and_stamps_logical_clock(self, api):
        """PRD §3.5: "Paying an invoice requires it to be `APPROVED` (else
        `ERR_INVOICE_NOT_APPROVED`), stamps `paid_at` from the logical clock,
        moves the invoice to `PAID`, and cascades the claim `INVOICED` →
        `SETTLED`."

        Design: Difficulty/transitive_cascade/invoice_pay_settles_claim_cascade_depth2
        """
        ctx = setup_invoice_approved(
            claim_overrides={"estimated_repair_cost_cents": 95000})
        resp = api.pay_invoice(ctx["invoice"]["id"], AUDITOR)
        invoice = validate_success(resp, 200)
        assert invoice["status"] == "PAID"
        # complete_at of the fixture was 2026-05-02T12:00:00Z; pay reads it too.
        assert invoice["paid_at"].startswith("2026-05-02T12:00:00")

    def test_pay_cascades_claim_to_settled_with_final_split(self, api):
        """PRD §2.9: "when the invoice is paid, the claim settles."
        PRD §3.5: "The `customer_responsibility_cents` is the smaller of the
        invoice's `approved_total_cents` and the sum of the claim's
        `deductible_applied_cents` plus its `oem_upcharge_cents`... The
        `insurer_payment_cents` is the approved total minus the customer
        responsibility, floored at zero."

        Design: Difficulty/transitive_cascade/invoice_pay_settles_claim_cascade_depth2
        """
        ctx = setup_invoice_approved(
            claim_overrides={"estimated_repair_cost_cents": 95000})
        api.pay_invoice(ctx["invoice"]["id"], AUDITOR)
        claim = get_claim(ctx["claim"]["id"])
        assert claim["status"] == "SETTLED"
        assert claim["customer_responsibility_cents"] == 50000
        assert claim["insurer_payment_cents"] == 45000


class TestInvoiceMoneyConservation:
    def _setup_submitted(self):
        """CA tax 560bp; one AM PART line billed 95000 -> submitted 100320."""
        return setup_invoice_submitted(
            state_code="CA", tax_bp=560,
            claim_overrides={"incident_state_code": "CA",
                             "service_zip_code": "90001",
                             "estimated_repair_cost_cents": 110000},
            shop_overrides={"state_code": "CA", "service_zip_prefixes": ["900"]},
        )

    def test_conservation_holds_through_dispute(self, api):
        """PRD §2.9: "Money is conserved on every invoice: from the moment of
        creation, the submitted total always equals the approved total plus the
        adjustment total, regardless of how many dispute-and-resubmit cycles the
        invoice passes through."
        PRD §3.5: "On `DISPUTE`, the invoice becomes `DISPUTED`: the proposed
        approved amounts are recorded on the lines and the adjustment total is
        computed, but the approved total stays at zero, so the whole submitted
        amount remains disputed..."

        Design: Difficulty/compensating_invariant/invoice_money_conservation_through_dispute_cycle
        """
        ctx = self._setup_submitted()
        invoice = get_invoice(ctx["invoice"]["id"])
        assert invoice["submitted_total_cents"] == 100320  # 95000 + tax 5320
        assert invoice["approved_total_cents"] == 0
        assert invoice["adjustment_total_cents"] == 100320
        assert_invoice_conservation(invoice)
        dispute_invoice(invoice["id"], [
            {"line_index": 0, "approved_amount_cents": 90000,
             "approved_origin": "AFTERMARKET"}])
        invoice = get_invoice(invoice["id"])
        assert invoice["status"] == "DISPUTED"
        assert invoice["approved_total_cents"] == 0
        assert invoice["adjustment_total_cents"] == 100320
        assert_invoice_conservation(invoice)

    def test_conservation_holds_through_resubmit_and_approve(self, api):
        """PRD §3.5: "resubmission from `DISPUTED` — supplying
        `revised_line_items` — replaces the line items wholesale, recomputes the
        agreement prices, the tax, and the submitted total, and resets the
        approved and adjustment totals to zero and the full submitted amount
        respectively."
        PRD §3.5: "On `APPROVE`, the invoice becomes `APPROVED`: the
        `approved_total_cents` is set to the sum of the lines' approved amounts
        plus the `tax_amount_cents`; the `adjustment_total_cents` becomes the
        submitted total minus the approved total..."

        Design: Difficulty/compensating_invariant/invoice_money_conservation_through_dispute_cycle
        """
        ctx = self._setup_submitted()
        shop_id = ctx["work_order"]["shop_id"]
        invoice_id = ctx["invoice"]["id"]
        dispute_invoice(invoice_id, [
            {"line_index": 0, "approved_amount_cents": 90000,
             "approved_origin": "AFTERMARKET"}])
        resubmitted = submit_invoice(invoice_id, shop_id, revised_line_items=[
            part_line(ctx["part"]["id"], 92000)])
        # tax = round_half_up(92000 x 560 / 10000) = 5152
        assert resubmitted["submitted_total_cents"] == 97152
        assert resubmitted["approved_total_cents"] == 0
        assert resubmitted["adjustment_total_cents"] == 97152
        assert_invoice_conservation(resubmitted)
        approved = approve_invoice(invoice_id, [
            {"line_index": 0, "approved_amount_cents": 90000,
             "approved_origin": "AFTERMARKET"}])
        # approved = 90000 + 5152 tax; adjustment = 97152 - 95152 = 2000
        assert approved["approved_total_cents"] == 95152
        assert approved["adjustment_total_cents"] == 2000
        assert_invoice_conservation(approved)


class TestInvoiceDisputeResubmitCycle:
    def _setup_disputed(self):
        ctx = setup_invoice_submitted(
            claim_overrides={"estimated_repair_cost_cents": 95000})
        disputed = dispute_invoice(ctx["invoice"]["id"], [
            {"line_index": 0, "approved_amount_cents": 80000,
             "approved_origin": "AFTERMARKET"}])
        ctx["invoice"] = disputed
        return ctx

    def test_dispute_records_proposed_amounts_keeps_totals(self, api):
        """PRD §3.5: "On `DISPUTE`, the invoice becomes `DISPUTED`: the proposed
        approved amounts are recorded on the lines and the adjustment total is
        computed, but the approved total stays at zero, so the whole submitted
        amount remains disputed; the auditor's identifier is likewise recorded."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_resubmit_cycle
        """
        ctx = self._setup_disputed()
        invoice = ctx["invoice"]
        assert invoice["status"] == "DISPUTED"
        assert invoice["approved_total_cents"] == 0
        assert invoice["adjustment_total_cents"] == 95000
        lines, _meta = validate_paginated(
            api.list_invoice_line_items(invoice["id"], ADMIN))
        assert lines[0]["approved_amount_cents"] == 80000

    def test_resubmit_replaces_lines_and_resets_totals(self, api):
        """PRD §3.5: "resubmission from `DISPUTED` — supplying
        `revised_line_items` — replaces the line items wholesale, recomputes the
        agreement prices, the tax, and the submitted total, and resets the
        approved and adjustment totals to zero and the full submitted amount
        respectively."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_resubmit_cycle
        """
        ctx = self._setup_disputed()
        resubmitted = submit_invoice(
            ctx["invoice"]["id"], ctx["work_order"]["shop_id"],
            revised_line_items=[part_line(ctx["part"]["id"], 85000)])
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["submitted_total_cents"] == 85000
        assert resubmitted["approved_total_cents"] == 0
        assert resubmitted["adjustment_total_cents"] == 85000
        lines, _meta = validate_paginated(
            api.list_invoice_line_items(ctx["invoice"]["id"], ADMIN))
        assert lines[0]["agreement_unit_price_cents"] == 95000
        assert lines[0]["line_total_cents"] == 85000


class TestShopAuditScores:
    def _setup_two_audits(self):
        """STANDARD shop; invoice A approved in full (event 100), invoice B
        submitted 95000 approved 76000 (event 80)."""
        net = setup_network()
        shop = net["shop"]
        # --- claim/invoice A: full approval ---
        ctx_a = setup_claim_verified(net)
        wo_a = route_claim(ctx_a["claim"]["id"], requested_shop_id=shop["id"])
        accept_work_order(wo_a["id"], shop["id"])
        schedule_work_order(wo_a["id"], shop["id"],
                            start="2026-05-02T09:00:00Z",
                            end="2026-05-02T10:00:00Z")
        set_clock("2026-05-02T11:00:00Z")
        complete_work_order(wo_a["id"], shop["id"])
        inv_a = create_invoice(wo_a["id"], shop["id"],
                               [part_line(net["part"]["id"], 95000)])
        inv_a = submit_invoice(inv_a["id"], shop["id"])
        approve_invoice(inv_a["id"], [
            {"line_index": 0, "approved_amount_cents": 95000,
             "approved_origin": "AFTERMARKET"}])
        # --- claim/invoice B: partial approval ---
        claim_b = make_claim(net["policyholder"], net["policy"],
                             loss_date="2026-04-20", description="claim B",
                             estimated_repair_cost_cents=95000)
        add_disclosure(claim_b["id"], net["policyholder"]["id"])
        claim_b = verify_claim(claim_b["id"])
        wo_b = route_claim(claim_b["id"], requested_shop_id=shop["id"])
        accept_work_order(wo_b["id"], shop["id"])
        schedule_work_order(wo_b["id"], shop["id"],
                            start="2026-05-03T09:00:00Z",
                            end="2026-05-03T10:00:00Z")
        set_clock("2026-05-03T11:00:00Z")
        complete_work_order(wo_b["id"], shop["id"])
        inv_b = create_invoice(wo_b["id"], shop["id"],
                               [part_line(net["part"]["id"], 95000)])
        inv_b = submit_invoice(inv_b["id"], shop["id"])
        approve_invoice(inv_b["id"], [
            {"line_index": 0, "approved_amount_cents": 76000,
             "approved_origin": "AFTERMARKET"}])
        return net, inv_b

    def test_rolling_ema_and_period_close_mean_diverge(self, api):
        """PRD §3.7: "The `rolling_audit_score` is an exponentially weighted
        moving average maintained incrementally on every approval ...: it is
        seven tenths of the previous rolling score plus three tenths of the
        event score, rounded half-up to two decimal places, starting from an
        initial previous value of 100. The `period_close_audit_score` is the
        flat arithmetic mean of all of the shop's per-audit event scores,
        rounded half-up to two decimal places, computed on read whenever the
        shop is retrieved..."

        Design: Difficulty/dual_variant_calc/shop_score_rolling_ema_vs_period_close_mean
        """
        net, _inv_b = self._setup_two_audits()
        shop = get_shop(net["shop"]["id"])
        # events 100 then 80: rolling = 0.7*100 + 0.3*80 = 94.0; mean = 90.0.
        assert shop["rolling_audit_score"] == 94.0
        assert shop["period_close_audit_score"] == 90.0
        assert shop["rolling_audit_score"] != shop["period_close_audit_score"]

    def test_partial_approval_totals_feed_event_score(self, api):
        """PRD §3.7: "Each approval of one of the shop's invoices produces a
        per-audit event score: the variance ratio is the invoice's
        `adjustment_total_cents` divided by its `submitted_total_cents` — taken
        as zero when the submitted total is zero — and the event score is one
        hundred times one minus that ratio."

        Design: Difficulty/dual_variant_calc/shop_score_rolling_ema_vs_period_close_mean
        """
        _net, inv_b = self._setup_two_audits()
        invoice = get_invoice(inv_b["id"])
        assert invoice["submitted_total_cents"] == 95000
        assert invoice["approved_total_cents"] == 76000
        assert invoice["adjustment_total_cents"] == 19000
