"""Invoices, invoiced-fee tracking, and provisional vs final fee accrual."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_review,
    assert_invoice,
    create_active_engagement,
    create_anomaly,
    create_assembly,
    create_completed_survey,
    create_design_review,
    create_engagement,
    create_invoice,
    create_plan,
    create_warranty_claim,
    get_engagement,
    issue_plan,
    manufacturer_acknowledge,
    manufacturer_decide,
    setup_approved_assembly,
    setup_verified_anomaly,
    start_review,
    validate_error,
    validate_success,
    verify_anomaly,
)

P = TEST_USERS["principal_headers"]
C = TEST_USERS["consultant_headers"]
MR = TEST_USERS["manufacturer_rep_headers"]


class TestInvoiceCalculation:

    def test_invoice_volume_tier_boundary_at_exactly_2m(self):
        """PRD §3.9: "the discount tier is then selected from the pre-discount
        subtotal — when `subtotal_cents` is at least 2000000 cents, the
        effective discount is the larger of the supplied `discount_pct` and 10
        percent, and otherwise it is simply the supplied `discount_pct`; the
        `total_cents` is the subtotal reduced by the effective discount
        percentage, rounded half-up to whole cents."
        PRD §3.9: "the labor line is `labor_hours` multiplied by the
        engagement's `labor_rate_cents_per_hour`, rounded half-up to whole
        cents, and the `subtotal_cents` is that figure plus `expense_cents`..."

        Design: Corner/calculations/invoice_volume_tier_boundary_at_exactly_2m
        """
        eng = create_active_engagement(name="EI", fee_cap_cents=50_000_000,
                                       labor_rate_cents_per_hour=14_000)
        eng2 = create_active_engagement(name="EI2", fee_cap_cents=50_000_000,
                                        labor_rate_cents_per_hour=15_000)
        # Subtotal exactly 2000000 -> tier floor engages: effective 10%.
        resp = api_client.create_invoice(
            eng["id"],
            {"labor_hours": 100, "expense_cents": 600000, "discount_pct": 0},
            C,
        )
        inv1 = validate_success(resp, 201)
        assert_invoice(inv1)
        assert inv1["subtotal_cents"] == 2000000
        assert inv1["total_cents"] == 1800000

        # Subtotal below the tier keeps the declared discount.
        resp = api_client.create_invoice(
            eng2["id"],
            {"labor_hours": 10, "expense_cents": 500000, "discount_pct": 5},
            C,
        )
        inv2 = validate_success(resp, 201)
        assert inv2["subtotal_cents"] == 650000
        assert inv2["total_cents"] == 617500

    def test_invoice_labor_rounding_half_up(self):
        """PRD §3.9: "the labor line is `labor_hours` multiplied by the
        engagement's `labor_rate_cents_per_hour`, rounded half-up to whole
        cents, and the `subtotal_cents` is that figure plus `expense_cents`..."
        PRD §2.8: "Where a calculation produces a fractional cent at a pinned
        rounding step, the value is rounded half-up to whole cents at that step
        — never earlier, never later."

        Design: Corner/calculations/invoice_labor_rounding_half_up
        """
        eng = create_active_engagement(name="ER2", fee_cap_cents=50_000_000,
                                       labor_rate_cents_per_hour=13_333)
        resp = api_client.create_invoice(
            eng["id"],
            {"labor_hours": 7.5, "expense_cents": 0, "discount_pct": 0},
            C,
        )
        inv = validate_success(resp, 201)
        # 7.5 * 13333 = 99997.5 -> round_half_up -> 99998.
        assert inv["subtotal_cents"] == 99998
        assert inv["total_cents"] == 99998


class TestInvoicedCentsTracking:

    def test_invoice_issue_then_mark_paid_updates_invoiced_cents(self):
        """PRD §2.7: "`invoiced_cents` is the sum of `total_cents` over the
        engagement's invoices whose status is `ISSUED` or `PAID`, recomputed
        whenever an invoice enters or leaves that set."
        PRD §3.9: "On issuance the engagement's `invoiced_cents` is recomputed
        as the sum of `total_cents` over invoices in `ISSUED` or `PAID`."

        Design: Corner/endpoints/invoice_issue_then_mark_paid_updates_invoiced_cents
        """
        eng = create_active_engagement(name="EIV", fee_cap_cents=50_000_000,
                                       labor_rate_cents_per_hour=10_000)
        inv1 = create_invoice(eng["id"], labor_hours=2, expense_cents=1000,
                              discount_pct=0)
        inv2 = create_invoice(eng["id"], labor_hours=1, expense_cents=0,
                              discount_pct=0)
        # A VOID draft never enters the ISSUED/PAID set.
        resp = api_client.void_invoice(eng["id"], inv2["id"], C)
        validate_success(resp, 200)

        resp = api_client.issue_invoice(eng["id"], inv1["id"], C)
        validate_success(resp, 200)
        assert get_engagement(eng["id"])["invoiced_cents"] == 21000

        resp = api_client.mark_invoice_paid(eng["id"], inv1["id"], P)
        data = validate_success(resp, 200)
        assert data["invoice_status"] == "PAID"
        assert get_engagement(eng["id"])["invoiced_cents"] == 21000

    def test_invoice_state_errors_distinct(self):
        """PRD §3.9: "Issuance requires the invoice to be `DRAFT` (otherwise
        `ERR_INVOICE_NOT_DRAFT`, HTTP 409)..."
        PRD §3.9: "A `Principal` marks an issued invoice paid, moving it from
        `ISSUED` to `PAID` (`ERR_INVOICE_NOT_ISSUED` when it is not `ISSUED`)
        and recomputing `invoiced_cents` again."

        Design: Corner/errors/invoice_state_errors_distinct
        """
        eng = create_active_engagement(name="EE", fee_cap_cents=50_000_000,
                                       labor_rate_cents_per_hour=10_000)
        inv1 = create_invoice(eng["id"], labor_hours=1)
        inv2 = create_invoice(eng["id"], labor_hours=1)
        resp = api_client.issue_invoice(eng["id"], inv2["id"], C)
        validate_success(resp, 200)

        resp = api_client.mark_invoice_paid(eng["id"], inv1["id"], P)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_ISSUED)
        resp = api_client.issue_invoice(eng["id"], inv2["id"], C)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_DRAFT)


class TestChildEntityReads:

    def test_get_single_child_entities(self):
        """PRD §3.1: "its `review_status` begins at `NONE`, reflecting that no
        design review round has yet been started against it."
        PRD §3.2: "The new review round starts in `SUBMITTED` with
        `revision_round` at 0 and `reviewer_id` unset..."
        PRD §3.3: "A slot is created in `RESERVED`."
        PRD §3.9: "the labor line is `labor_hours` multiplied by the
        engagement's `labor_rate_cents_per_hour`, rounded half-up to whole
        cents, and the `subtotal_cents` is that figure plus `expense_cents`..."
        PRD §3.9: "The invoice is created with its `invoice_status` at
        `DRAFT`..."

        Design: Corner/endpoints/get_single_child_entities
        """
        eng = create_active_engagement(name="EG", fee_cap_cents=50_000_000,
                                       labor_rate_cents_per_hour=10_000)
        asm = create_assembly(eng["id"], tag="AG", assembly_type="MASONRY",
                              design_u_factor=1.0,
                              required_airtightness_lps_m2=2.0)
        rev = create_design_review(eng["id"], asm["id"],
                                   barrier_scope=["AIR", "WATER"],
                                   drawing_count=5)
        slot_resp = api_client.create_chamber_slot(
            eng["id"],
            {"chamber_code": "CHAMBER-G", "start_date": "2026-09-01",
             "end_date": "2026-09-03", "daily_rate_cents": 50000},
            C,
        )
        slot = validate_success(slot_resp, 201)
        inv = create_invoice(eng["id"], labor_hours=2, expense_cents=1000,
                             discount_pct=0)

        asm_read = validate_success(
            api_client.get_assembly(eng["id"], asm["id"], C), 200)
        assert asm_read["review_status"] == "NONE"
        rev_read = validate_success(
            api_client.get_design_review(eng["id"], rev["id"], C), 200)
        assert rev_read["revision_round"] == 0
        assert rev_read["status"] == "SUBMITTED"
        slot_read = validate_success(
            api_client.get_chamber_slot(eng["id"], slot["id"], C), 200)
        assert slot_read["status"] == "RESERVED"
        inv_read = validate_success(
            api_client.get_invoice(eng["id"], inv["id"], C), 200)
        assert inv_read["subtotal_cents"] == 21000
        assert inv_read["total_cents"] == 21000
        assert inv_read["invoice_status"] == "DRAFT"


class TestProvisionalVsFinalFeeAccrual:

    def _setup_engagement_with_recovery(self, review_drawings=8,
                                        review_barriers=None,
                                        claim_amount=8_000_000):
        """One approved design review (fee 380000), a plan ISSUED then
        COMPLETED (estimate 6600000, actual 6000000, delta -600000), and a
        warranty claim RESOLVED with recovery 6000000. The claim is filed,
        acknowledged, and accepted before plan completion because the anomaly
        leaves VERIFIED when the plan completes (PRD §3.7 cascade); resolution
        happens after completion so the waterfall sees the completed plan.

        Returns (engagement, plan, claim).
        """
        eng = create_active_engagement(name="E2", fee_cap_cents=50_000_000,
                                       labor_rate_cents_per_hour=15_000)
        asm = create_assembly(eng["id"], tag="W2", assembly_type="WINDOW_WALL",
                              design_u_factor=2.0,
                              required_airtightness_lps_m2=1.5)
        rev = create_design_review(eng["id"], asm["id"],
                                   barrier_scope=review_barriers or ["AIR", "WATER"],
                                   drawing_count=review_drawings)
        start_review(eng["id"], rev["id"], "rev-user-1")
        approve_review(eng["id"], rev["id"], "rev-user-1")

        srv = create_completed_survey(eng["id"], asm["id"],
                                      survey_date="2026-09-05")
        an1 = create_anomaly(eng["id"], anomaly_type="WATER_INGRESS",
                             severity="HIGH", description="leak",
                             survey_id=srv["id"])
        an2 = create_anomaly(eng["id"], anomaly_type="MOISTURE_TRAP",
                             severity="MEDIUM", description="wet",
                             survey_id=srv["id"])
        verify_anomaly(eng["id"], an1["id"])
        verify_anomaly(eng["id"], an2["id"])

        plan = create_plan(eng["id"], [an1["id"], an2["id"]],
                           ["07 01 00", "07 02 00", "08 01 00", "08 02 00"])
        plan = issue_plan(eng["id"], plan["id"])
        assert plan["estimated_cost_cents"] == 6600000

        claim = create_warranty_claim(eng["id"], an1["id"],
                                      manufacturer_name="ACME Glazing",
                                      claimed_amount_cents=claim_amount)
        manufacturer_acknowledge(eng["id"], claim["id"])
        manufacturer_decide(eng["id"], claim["id"], "ACCEPTED")

        resp = api_client.complete_remediation_plan(eng["id"], plan["id"], P)
        completed = validate_success(resp, 200)
        assert completed["actual_cost_cents"] == 6000000

        resp = api_client.resolve_claim(eng["id"], claim["id"], C)
        resolved = validate_success(resp, 200)
        # outlay = 6000000; already = 0; recovered = min(claim, 6000000).
        assert resolved["recovered_amount_cents"] == min(claim_amount, 6000000)
        assert resolved["claim_status"] == "RESOLVED"
        return get_engagement(eng["id"]), completed, resolved

    def test_provisional_nets_recovery_final_excludes_it(self):
        """PRD §2.7: "The **provisional** variant is a running accumulator:
        each fee event — a design review round reaching `APPROVED` or
        `REJECTED`, a mock-up test reaching `PASSED` or `FAILED`, a remediation
        plan being issued, completed, or superseded, or a warranty claim being
        resolved — applies its signed delta to `recognized_fees_cents` at
        transition time, and the accumulator is floored at 0 after each step so
        the provisional total can never go negative. The **final** variant runs
        once, at the moment the engagement moves from `IN_PROGRESS` to
        `CLOSE_OUT`: the server recomputes recognized fees from scratch by
        replaying every fee-bearing event of the engagement in chronological
        order (ordered by event timestamp ascending, ties broken by event
        creation timestamp ascending), summing only the positive fee events.
        Warranty-recovery offsets are excluded from the final replay
        entirely..."

        Design: Difficulty/dual_variant_calc/engagement_provisional_vs_final_fee_accrual
        """
        eng, plan, claim = self._setup_engagement_with_recovery()
        # Provisional: 380000 + 6600000 - 600000 - 6000000 = 380000.
        assert eng["recognized_fees_cents"] == 380000

        resp = api_client.begin_close_out(eng["id"], P)
        data = validate_success(resp, 200)
        assert data["status"] == "CLOSE_OUT"
        # Final: positive events only = 380000 + 6600000 = 6980000.
        assert data["recognized_fees_cents"] == 6980000
        assert get_engagement(eng["id"])["recognized_fees_cents"] == 6980000

    def test_provisional_nets_recovery_on_independent_stream(self):
        """PRD §2.7: "The **provisional** variant is a running accumulator:
        each fee event — a design review round reaching `APPROVED` or
        `REJECTED`, a mock-up test reaching `PASSED` or `FAILED`, a remediation
        plan being issued, completed, or superseded, or a warranty claim being
        resolved — applies its signed delta to `recognized_fees_cents` at
        transition time, and the accumulator is floored at 0 after each step so
        the provisional total can never go negative."
        PRD §2.7: "The **final** variant runs once, at the moment the
        engagement moves from `IN_PROGRESS` to `CLOSE_OUT`: ... summing only
        the positive fee events. Warranty-recovery offsets are excluded from
        the final replay entirely — the final accrual treats recoveries as
        contra-revenue reported separately rather than netted against fees —
        and no intermediate floor is applied."

        Design: Difficulty/dual_variant_calc/engagement_provisional_vs_final_fee_accrual
        """
        # Stream: review approve +250000; plan issue +1800000; plan complete
        # -175000; claim resolve -1625000 (waterfall: outlay = actual 1625000,
        # nothing recovered before).
        eng2 = create_active_engagement(name="E2B", fee_cap_cents=50_000_000,
                                        labor_rate_cents_per_hour=15_000)
        asm2 = create_assembly(eng2["id"], tag="W2B",
                               assembly_type="WINDOW_WALL", design_u_factor=2.0,
                               required_airtightness_lps_m2=1.5)
        rev2 = create_design_review(eng2["id"], asm2["id"],
                                    barrier_scope=["AIR"], drawing_count=2)
        start_review(eng2["id"], rev2["id"], "rev-user-1")
        approve_review(eng2["id"], rev2["id"], "rev-user-1")  # +250000
        srv2 = create_completed_survey(eng2["id"], asm2["id"])
        an2 = create_anomaly(eng2["id"], anomaly_type="MOISTURE_TRAP",
                             severity="MEDIUM", description="wet",
                             survey_id=srv2["id"])
        verify_anomaly(eng2["id"], an2["id"])
        plan2 = create_plan(eng2["id"], [an2["id"]], ["07 01 00"])
        plan2 = issue_plan(eng2["id"], plan2["id"])  # +1800000
        claim2 = create_warranty_claim(eng2["id"], an2["id"],
                                       claimed_amount_cents=5_000_000)
        manufacturer_acknowledge(eng2["id"], claim2["id"])
        manufacturer_decide(eng2["id"], claim2["id"], "ACCEPTED")
        resp = api_client.complete_remediation_plan(eng2["id"], plan2["id"], P)
        completed2 = validate_success(resp, 200)
        assert completed2["actual_cost_cents"] == 1625000
        # Provisional now: 250000 + 1800000 - 175000 = 1875000.
        assert get_engagement(eng2["id"])["recognized_fees_cents"] == 1875000
        resp = api_client.resolve_claim(eng2["id"], claim2["id"], C)
        resolved2 = validate_success(resp, 200)
        assert resolved2["recovered_amount_cents"] == 1625000
        # Provisional nets the recovery: 1875000 - 1625000 = 250000.
        assert get_engagement(eng2["id"])["recognized_fees_cents"] == 250000
        # The final replay sums positive events only: 250000 + 1800000.
        resp = api_client.begin_close_out(eng2["id"], P)
        data2 = validate_success(resp, 200)
        assert data2["recognized_fees_cents"] == 2050000
