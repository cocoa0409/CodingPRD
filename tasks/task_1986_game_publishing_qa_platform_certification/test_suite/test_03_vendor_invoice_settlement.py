"""Vendor invoice computed read: PROVISIONAL vs FINAL variants, per-line
rounding order, and input-set filtering (PRD §3.3)."""
from test_helpers import (
    TEST_USERS,
    add_plan_entry,
    complete_assignment,
    create_assignment,
    create_bug,
    create_build,
    create_plan,
    create_title,
    create_vendor,
    set_clock,
    transition_assignment,
    validate_success,
)

VM_HEADERS = TEST_USERS["vendor_manager_headers"]
WEEK = "2026-08-03"


def _invoice(api, vendor_id, variant, week=WEEK):
    return validate_success(
        api.get_vendor_invoice(
            vendor_id, VM_HEADERS,
            params={"week_start_date": week, "variant": variant},
        )
    )


def _vendor_with_two_done_assignments(rate=10001, actuals=(12, 11),
                                      reserved=10):
    """Vendor with two DONE assignments in week 2026-08-03 and (optionally)
    one post-launch escape bug attributed to it."""
    set_clock("2026-08-04T09:00:00Z")  # Tuesday of the ISO week of 2026-08-03
    title = create_title(title_code="DUAL-V", cert_budget_total_cents=500000)
    vendor = create_vendor(name="VendorPrime", weekly_capacity_hours=40,
                           cost_rate_cents_per_hour=rate)
    plan = create_plan(title["id"], "PS5")
    add_plan_entry(plan["id"], feature_area="COMBAT", required_coverage_hours=1)
    assignments = []
    for actual in actuals:
        a = create_assignment(vendor["id"], plan["id"], feature_area="COMBAT",
                              week_start_date=WEEK, reserved_hours=reserved)
        assignments.append(complete_assignment(a["id"], actual_hours=actual))
    return title, vendor, plan, assignments


def _add_escape_bug(title, vendor):
    build = create_build(title["id"], "PS5", "1.0.0")
    return create_bug(
        title["id"], build["id"], severity="MINOR", category="GAMEPLAY",
        found_by_vendor_id=vendor["id"], found_post_launch=True,
    )


class TestDualVariantDivergence:
    def test_provisional_variant_bills_reserved_hours_without_clawback(self, api):
        """PRD §3.3: "Under `PROVISIONAL` — the as-billed estimate — the
        invoice includes the vendor's assignments for the requested week in
        `SCHEDULED`, `IN_PROGRESS`, or `DONE`. Each line bills the
        `reserved_hours` at the vendor's rate as an exact integer product; the
        subtotal is the sum of lines, the clawback is zero, and the total
        equals the subtotal."

        Design: Difficulty/dual_variant_calc/vendor_invoice_provisional_vs_final_diverge
        """
        title, vendor, _plan, _a = _vendor_with_two_done_assignments()
        _add_escape_bug(title, vendor)
        invoice = _invoice(api, vendor["id"], "PROVISIONAL")
        assert invoice["week_start_date"] == WEEK
        assert invoice["variant"] == "PROVISIONAL"
        assert invoice["subtotal_cents"] == 200020  # 2 x (10h x 10001)
        assert invoice["clawback_cents"] == 0
        assert invoice["total_cents"] == 200020

    def test_final_variant_overtime_per_line_and_escape_clawback(self, api):
        """PRD §3.3: "Under `FINAL` — the settlement reading — only `DONE`
        assignments for the week are included. Each line is computed in two
        parts with per-line rounding, then summed: the regular hours are the
        lesser of `actual_hours` and `reserved_hours`, billed at the rate and
        rounded half-up to whole cents; the overtime hours are the amount by
        which `actual_hours` exceeds `reserved_hours` (zero when it does not),
        billed at one and a half times the rate and itself rounded half-up to
        whole cents."
        PRD §3.3: "The clawback percentage is ten percent per escape, capped
        at fifty percent."
        PRD §3.3: "The two variants price identical underlying data
        differently whenever any completed assignment's actual hours differ
        from its reservation or any escape exists."

        Design: Difficulty/dual_variant_calc/vendor_invoice_provisional_vs_final_diverge
        """
        title, vendor, _plan, _a = _vendor_with_two_done_assignments()
        _add_escape_bug(title, vendor)
        final = _invoice(api, vendor["id"], "FINAL")
        # line1: 100010 + round_half_up(30003.0); line2: 100010 +
        # round_half_up(15001.5) = 15002 -> subtotal 245025
        assert final["subtotal_cents"] == 245025
        # round_half_up(245025 x 10 / 100) = 24503
        assert final["clawback_cents"] == 24503
        assert final["total_cents"] == 220522
        provisional = _invoice(api, vendor["id"], "PROVISIONAL")
        assert provisional["total_cents"] != final["total_cents"]


class TestPerLineRoundingOrder:
    def test_final_invoice_rounds_per_line_then_sums(self, api):
        """PRD §3.3: "Summing first and rounding once is a rejected
        alternative — rounding happens per line, then the per-line values are
        summed into the subtotal."

        Design: Difficulty/combinatorial_formula/vendor_invoice_per_line_rounding_order
        """
        set_clock("2026-08-04T09:00:00Z")
        title = create_title(title_code="COMB-ROUND",
                             cert_budget_total_cents=500000)
        vendor = create_vendor(name="VendorRound", weekly_capacity_hours=40,
                               cost_rate_cents_per_hour=10001)
        plan = create_plan(title["id"], "PS5")
        add_plan_entry(plan["id"], feature_area="COMBAT",
                       required_coverage_hours=1)
        for _ in range(2):
            a = create_assignment(vendor["id"], plan["id"],
                                  feature_area="COMBAT", week_start_date=WEEK,
                                  reserved_hours=8)
            complete_assignment(a["id"], actual_hours=9)
        invoice = _invoice(api, vendor["id"], "FINAL")
        # per line: 8 x 10001 = 80008 regular + round_half_up(15001.5) =
        # 15002 overtime -> 95010; two lines -> 190020
        assert invoice["line_count"] == 2
        assert invoice["subtotal_cents"] == 190020
        assert invoice["total_cents"] == 190020

    def test_final_invoice_rejects_sum_then_round_reading(self, api):
        """PRD §3.3: "Summing first and rounding once is a rejected
        alternative — rounding happens per line, then the per-line values are
        summed into the subtotal."

        Design: Difficulty/combinatorial_formula/vendor_invoice_per_line_rounding_order
        """
        set_clock("2026-08-04T09:00:00Z")
        title = create_title(title_code="COMB-ROUND",
                             cert_budget_total_cents=500000)
        vendor = create_vendor(name="VendorRound", weekly_capacity_hours=40,
                               cost_rate_cents_per_hour=10001)
        plan = create_plan(title["id"], "PS5")
        add_plan_entry(plan["id"], feature_area="COMBAT",
                       required_coverage_hours=1)
        for _ in range(2):
            a = create_assignment(vendor["id"], plan["id"],
                                  feature_area="COMBAT", week_start_date=WEEK,
                                  reserved_hours=8)
            complete_assignment(a["id"], actual_hours=9)
        invoice = _invoice(api, vendor["id"], "FINAL")
        # Sum-then-round would yield 190019; the pinned order yields 190020.
        assert invoice["total_cents"] == 190020
        assert invoice["total_cents"] != 190019
        # No escapes exist for this vendor, so no clawback applies.
        assert invoice["clawback_cents"] == 0


class TestInvoiceInputSetFiltering:
    def test_final_invoice_includes_only_done_assignments_of_the_week(self, api):
        """PRD §3.3: "Under `FINAL` — the settlement reading — only `DONE`
        assignments for the week are included."

        Design: Corner/calculations/invoice_input_set_filtering
        """
        set_clock("2026-08-04T09:00:00Z")
        title = create_title(title_code="CL-FLT", cert_budget_total_cents=1000)
        vendor = create_vendor(name="VendorFlt", weekly_capacity_hours=100,
                               cost_rate_cents_per_hour=5000)
        plan = create_plan(title["id"], "PS5")
        add_plan_entry(plan["id"], feature_area="COMBAT",
                       required_coverage_hours=1)
        # DONE in the requested week — the only qualifying line.
        a1 = create_assignment(vendor["id"], plan["id"], feature_area="COMBAT",
                               week_start_date="2026-08-03", reserved_hours=8)
        complete_assignment(a1["id"], actual_hours=8)
        # DONE but in another week — excluded.
        a2 = create_assignment(vendor["id"], plan["id"], feature_area="COMBAT",
                               week_start_date="2026-08-10", reserved_hours=8)
        complete_assignment(a2["id"], actual_hours=8)
        # Same week but CANCELLED — excluded.
        a3 = create_assignment(vendor["id"], plan["id"], feature_area="COMBAT",
                               week_start_date="2026-08-03", reserved_hours=5)
        transition_assignment(a3["id"], "CANCELLED")
        invoice = _invoice(api, vendor["id"], "FINAL")
        assert invoice["line_count"] == 1
        assert invoice["total_cents"] == 40000  # 8h x 5000, no OT, no escapes
