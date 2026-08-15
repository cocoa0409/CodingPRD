"""Quote pricing: dual-variant totals, pinned rounding order, and the surge
multiplier's combinatorial clamp."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_instant_equals,
    assert_quote,
    author_and_finalize_report,
    create_part,
    create_quote_for_ro,
    get_quote,
    get_success_data,
    get_window,
    issue_quote,
    quote_part_line,
    setup_closed_shop,
    setup_quote_in_progress_shop,
    setup_warranty_shop,
    setup_window_with_reserved_hours,
    start_teardown,
)

IC = TEST_USERS["intake_coordinator_headers"]

PRICED_LINES_PARTS = [
    {"part_number": "IMPELLER-1", "description": "Impeller", "unit_price_cents": 15000},
    {"part_number": "SEAL-1", "description": "Mech seal", "unit_price_cents": 7500},
]


def _make_priced_lines():
    """Parts IMPELLER-1 (15000) and SEAL-1 (7500) plus priced quote lines
    2x15000 + 1x7500 (commercial subtotal 37500, warranty subtotal 18750)."""
    p1 = create_part(**PRICED_LINES_PARTS[0])
    p2 = create_part(**PRICED_LINES_PARTS[1])
    return [quote_part_line(p1["id"], 2, 15000), quote_part_line(p2["id"], 1, 7500)]


def _create_warranty_ro(shop, failure_mode="SEAL_LEAK", estimated_bay_hours=10):
    return get_success_data(api_client.create_repair_order(
        {"customer_id": shop["customer"]["id"], "asset_id": shop["asset"]["id"],
         "failure_mode": failure_mode, "failure_description": "again",
         "intake_priority": "STANDARD", "planned_start_date": "2026-08-10",
         "planned_end_date": "2026-08-20", "estimated_bay_hours": estimated_bay_hours,
         "warranty_parent_ro_id": shop["ro"]["id"]},
        IC))


class TestDualVariantPricing:
    def test_commercial_and_warranty_quotes_price_identical_work_differently(self, api):
        """PRD §3.5: "The `pricing_variant` is `WARRANTY` when the repair order's `warranty_case` is true, otherwise `COMMERCIAL`."
        PRD §3.5: "Each part line's total is its `quantity` multiplied by its `unit_price_cents`, reduced by a fifty-percent parts discount only when the variant is `WARRANTY`, with each line's result rounded half-up to a whole cent before any summation."
        PRD §3.5: "The `labor_cents` is `labor_hours` multiplied by `labor_rate_cents`, rounded half-up to a whole cent — except on a `WARRANTY` quote, where labor is free and `labor_cents` is zero."
        PRD §3.3: "When eligibility holds, the new order's `warranty_case` is set true — which later forces the `WARRANTY` pricing variant on its quotes — and `repeat_failure_flag` is set true exactly when the parent's `failure_mode` matches the new order's, feeding re-repair analysis."

        Design: Difficulty/dual_variant_calc/quote_total_commercial_vs_warranty_variant
        """
        lines = _make_priced_lines()

        # Parent order: byte-identical lines and labor, ordinary commercial work,
        # driven RECEIVED -> CLOSED.
        shop = setup_closed_shop(
            ro_over={"failure_mode": "SEAL_LEAK", "estimated_bay_hours": 10},
            quote_over={"labor_hours": 4, "labor_rate_cents": 20000,
                        "part_lines": lines})
        parent_quote = get_quote(shop["quote"]["id"])
        assert parent_quote["pricing_variant"] == "COMMERCIAL"
        assert parent_quote["total_cents"] == 117500, "37500 parts + 80000 labor"
        assert shop["ro"]["status"] == "CLOSED"

        # Warranty order against the closed parent, quoted identically.
        warranty_ro = _create_warranty_ro(shop)
        assert warranty_ro["warranty_case"] is True
        assert warranty_ro["repeat_failure_flag"] is True, (
            "same failure_mode as the parent order"
        )
        start_teardown(warranty_ro["id"])
        author_and_finalize_report(
            warranty_ro["id"],
            part_lines=[{"part_id": lines[0]["part_id"], "quantity": 2},
                        {"part_id": lines[1]["part_id"], "quantity": 1}])
        warranty_quote = create_quote_for_ro(
            warranty_ro["id"], shop["window"]["id"],
            labor_hours=4, labor_rate_cents=20000, part_lines=lines)

        assert warranty_quote["pricing_variant"] == "WARRANTY"
        assert warranty_quote["total_cents"] == 18750, (
            "WARRANTY: parts at 50% (15000 + 3750), labor zeroed, surge forced 1.0"
        )

    def test_warranty_quote_computed_field_decomposition(self, api):
        """PRD §3.5: "The `parts_subtotal_cents` is the sum of those already-rounded per-line totals."
        PRD §3.5: "The `total_cents` is the sum of `parts_subtotal_cents` and `labor_cents`, multiplied by `surge_multiplier_applied`, with the final amount rounded half-up to a whole cent."
        PRD §3.6: "On a `WARRANTY` quote the multiplier is forced to exactly 1.0 regardless of posture, priority, or pool membership."

        Design: Difficulty/dual_variant_calc/quote_total_commercial_vs_warranty_variant
        """
        lines = _make_priced_lines()

        # Commercial decomposition on a fresh order.
        shop = setup_quote_in_progress_shop()
        commercial = create_quote_for_ro(
            shop["ro"]["id"], shop["window"]["id"],
            labor_hours=4, labor_rate_cents=20000, part_lines=lines)
        assert_quote(commercial)
        assert commercial["pricing_variant"] == "COMMERCIAL"
        assert commercial["parts_subtotal_cents"] == 37500
        assert commercial["labor_cents"] == 80000
        assert commercial["surge_multiplier_applied"] == pytest.approx(1.0, abs=1e-9)
        assert commercial["total_cents"] == 117500

        # Warranty decomposition against a closed parent on the same asset.
        closed = setup_closed_shop(ro_over={"failure_mode": "SEAL_LEAK",
                                            "estimated_bay_hours": 10})
        warranty_ro = _create_warranty_ro(closed)
        start_teardown(warranty_ro["id"])
        author_and_finalize_report(warranty_ro["id"])
        warranty = create_quote_for_ro(
            warranty_ro["id"], closed["window"]["id"],
            labor_hours=4, labor_rate_cents=20000, part_lines=lines)
        assert warranty["pricing_variant"] == "WARRANTY"
        assert warranty["parts_subtotal_cents"] == 18750, "15000 + 3750 after per-line 50%"
        assert warranty["labor_cents"] == 0, "labor is free on a WARRANTY quote"
        assert warranty["surge_multiplier_applied"] == pytest.approx(1.0, abs=1e-9)
        assert warranty["total_cents"] == 18750


class TestPerLineRoundingOrder:
    def test_warranty_per_line_rounding_before_summation(self, api):
        """PRD §2.8: "Quote part lines are rounded per line, half-up, before any summation; rounding the sum instead of each line produces a different, non-conforming result."
        PRD §3.5: "Each part line's total is its `quantity` multiplied by its `unit_price_cents`, reduced by a fifty-percent parts discount only when the variant is `WARRANTY`, with each line's result rounded half-up to a whole cent before any summation."

        Design: Difficulty/combinatorial_formula/quote_total_per_line_rounding_order
        """
        p1 = create_part(part_number="SHAFT-1", description="Shaft", unit_price_cents=7501)
        p2 = create_part(part_number="SLEEVE-1", description="Sleeve", unit_price_cents=7501)
        lines = [quote_part_line(p1["id"], 3, 7501), quote_part_line(p2["id"], 3, 7501)]

        shop = setup_warranty_shop()
        assert shop["ro"]["warranty_case"] is True
        quote = create_quote_for_ro(
            shop["ro"]["id"], shop["window"]["id"],
            labor_hours=0, labor_rate_cents=20000, part_lines=lines)
        assert_quote(quote)
        assert quote["pricing_variant"] == "WARRANTY"
        # Per line: round_half_up(3 * 7501 * 0.5) = round_half_up(11251.5) = 11252.
        assert quote["parts_subtotal_cents"] == 22504, (
            "11252 + 11252; sum-then-round would wrongly yield 22503"
        )
        assert quote["labor_cents"] == 0
        assert quote["total_cents"] == 22504

    def test_commercial_labor_rounding_half_up(self, api):
        """PRD §3.5: "The `labor_cents` is `labor_hours` multiplied by `labor_rate_cents`, rounded half-up to a whole cent — except on a `WARRANTY` quote, where labor is free and `labor_cents` is zero."
        PRD §3.5: "The `total_cents` is the sum of `parts_subtotal_cents` and `labor_cents`, multiplied by `surge_multiplier_applied`, with the final amount rounded half-up to a whole cent."

        Design: Difficulty/combinatorial_formula/quote_total_per_line_rounding_order
        """
        part = create_part(part_number="SHAFT-1", description="Shaft",
                           unit_price_cents=7501)
        shop = setup_quote_in_progress_shop()
        quote = create_quote_for_ro(
            shop["ro"]["id"], shop["window"]["id"],
            labor_hours=2.5, labor_rate_cents=20001,
            part_lines=[quote_part_line(part["id"], 3, 7501)])
        assert quote["pricing_variant"] == "COMMERCIAL"
        assert quote["parts_subtotal_cents"] == 22503, "3 * 7501, already whole"
        assert quote["labor_cents"] == 50003, (
            "round_half_up(2.5 * 20001) = round_half_up(50002.5)"
        )
        assert quote["total_cents"] == 72506


class TestSurgeMultiplierClamp:
    def test_surge_posture_priority_and_pool_combine_then_clamp(self, api):
        """PRD §3.6: "The multiplier starts at 1.00, or at 1.25 when the referenced window's posture at creation time is `SURGE`."
        PRD §3.6: "A repair order whose `intake_priority` is `SURGE` adds 0.15 to the multiplier, and membership in the customer's pool program subtracts 0.10."
        PRD §3.6: "The result is then clamped: it never falls below 1.00 and never exceeds 1.50, expressed to two decimal places."

        Design: Difficulty/combinatorial_formula/surge_multiplier_nested_minmax_clamp
        """
        # Window pushed to SURGE: capacity 100, 80 hours approved (80 >= 80).
        shop1 = setup_window_with_reserved_hours(reserved_hours=80, capacity=100)
        window1 = get_window(shop1["window"]["id"])
        assert window1["bay_hours_reserved"] == 80
        assert window1["window_posture"] == "SURGE"

        # Pool-program customer quoting SURGE-priority work into the SURGE window:
        # 1.25 + 0.15 - 0.10 = 1.30, inside the clamp.
        shop2 = setup_quote_in_progress_shop(
            customer_over={"pool_program": True},
            ro_over={"intake_priority": "SURGE", "estimated_bay_hours": 5})
        q2 = create_quote_for_ro(shop2["ro"]["id"], shop1["window"]["id"],
                                 labor_hours=5)
        assert q2["surge_multiplier_applied"] == pytest.approx(1.30, abs=1e-9)

        # Pool-program customer quoting STANDARD work into a NORMAL window:
        # 1.00 - 0.10 = 0.90, floor-clamped to 1.00.
        shop3 = setup_quote_in_progress_shop(
            customer_over={"pool_program": True},
            window_capacity=50,
            window_over={"window_start": "2026-08-01T00:00:00Z",
                         "window_end": "2026-09-01T00:00:00Z"},
            ro_over={"intake_priority": "STANDARD", "estimated_bay_hours": 5})
        q3 = create_quote_for_ro(shop3["ro"]["id"], shop3["window"]["id"],
                                 labor_hours=5)
        assert get_window(shop3["window"]["id"])["window_posture"] == "NORMAL"
        assert q3["surge_multiplier_applied"] == pytest.approx(1.00, abs=1e-9)

    def test_posture_priority_combination_without_pool(self, api):
        """PRD §3.6: "The multiplier starts at 1.00, or at 1.25 when the referenced window's posture at creation time is `SURGE`."
        PRD §3.6: "A repair order whose `intake_priority` is `SURGE` adds 0.15 to the multiplier, and membership in the customer's pool program subtracts 0.10."

        Design: Difficulty/combinatorial_formula/surge_multiplier_nested_minmax_clamp
        """
        # SURGE window + SURGE priority, no pool credit: 1.25 + 0.15 = 1.40.
        shop1 = setup_window_with_reserved_hours(reserved_hours=80, capacity=100)
        assert get_window(shop1["window"]["id"])["window_posture"] == "SURGE"
        shop2 = setup_quote_in_progress_shop(
            ro_over={"intake_priority": "SURGE", "estimated_bay_hours": 5})
        q2 = create_quote_for_ro(shop2["ro"]["id"], shop1["window"]["id"],
                                 labor_hours=5)
        assert q2["surge_multiplier_applied"] == pytest.approx(1.40, abs=1e-9)

        # NORMAL window + SURGE priority + pool credit: 1.00 + 0.15 - 0.10 = 1.05.
        shop3 = setup_quote_in_progress_shop(
            customer_over={"pool_program": True},
            window_capacity=50,
            window_over={"window_start": "2026-08-01T00:00:00Z",
                         "window_end": "2026-09-01T00:00:00Z"},
            ro_over={"intake_priority": "SURGE", "estimated_bay_hours": 5})
        q3 = create_quote_for_ro(shop3["ro"]["id"], shop3["window"]["id"],
                                 labor_hours=5)
        assert get_window(shop3["window"]["id"])["window_posture"] == "NORMAL"
        assert q3["surge_multiplier_applied"] == pytest.approx(1.05, abs=1e-9)


class TestIssuanceValidityWindow:
    def test_clock_default_drives_quote_validity_window(self, api):
        """PRD §2.4: "At startup the clock reads exactly `2026-08-01T00:00:00Z`; until it is explicitly set, every read of the current instant returns this default."
        PRD §3.6: "Issuing a quote moves it `DRAFT` → `ISSUED` and stamps `issued_at` with the logical clock and `expires_at` fourteen days later; before issuance both fields are null."

        Design: Corner/endpoints/clock_default_drives_quote_validity_window
        """
        shop = setup_quote_in_progress_shop()
        quote = create_quote_for_ro(shop["ro"]["id"], shop["window"]["id"],
                                    labor_hours=1)
        assert quote["issued_at"] is None and quote["expires_at"] is None

        issued = issue_quote(quote["id"])
        assert issued["status"] == "ISSUED"
        assert_instant_equals(issued["issued_at"], "2026-08-01T00:00:00Z")
        assert_instant_equals(issued["expires_at"], "2026-08-15T00:00:00Z")  # issued_at + 14 days

    def test_aftermarket_substitution_issue_succeeds(self, api):
        """PRD §3.5: "Substitution carries its own rules, enforced when a quote is issued (§3.6): a line's `substitution_for_part_id` must reference a part that is `OBSOLETE`, and that obsolete part must have `aftermarket_allowed` true."
        PRD §3.6: "Issuing a quote moves it `DRAFT` → `ISSUED` and stamps `issued_at` with the logical clock and `expires_at` fourteen days later; before issuance both fields are null."

        Design: Corner/validations/aftermarket_substitution_issue_succeeds
        """
        oem = create_part(part_number="TRIM-O2", description="OEM trim",
                          unit_price_cents=5000, aftermarket_allowed=True)
        sub = create_part(part_number="TRIM-AM2", description="Aftermarket trim",
                          unit_price_cents=4000)
        get_success_data(api_client.mark_part_obsolete(
            oem["id"], {"superseded_by_id": sub["id"]}, TEST_USERS["service_manager_headers"]))

        shop = setup_quote_in_progress_shop()
        quote = create_quote_for_ro(
            shop["ro"]["id"], shop["window"]["id"], labor_hours=1,
            part_lines=[quote_part_line(sub["id"], 1, 4000,
                                        substitution_for_part_id=oem["id"])])
        issued = issue_quote(quote["id"])
        assert issued["status"] == "ISSUED"
        assert_instant_equals(issued["issued_at"], "2026-08-01T00:00:00Z")
        assert_instant_equals(issued["expires_at"], "2026-08-15T00:00:00Z")
