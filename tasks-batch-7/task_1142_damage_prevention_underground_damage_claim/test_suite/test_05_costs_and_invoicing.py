"""Repair cost compilation, invoice dual basis, nested rounding, and finalize caps
(PRD §3.4, §3.5)."""
from test_helpers import (
    ApiErrorId,
    add_cost_line,
    add_evidence,
    assert_case_invoice_conservation,
    begin_investigation,
    create_allocation,
    create_case,
    create_excavator,
    create_locator,
    finalize_allocation,
    get_allocation,
    get_case,
    get_success_data,
    list_case_invoices,
    make_adjuster_headers,
    make_investigator_headers,
    make_manager_headers,
    propose_allocation,
    setup_proposed_allocation,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCostLineMarkupCapEmergency:
    def test_labor_line_major_case_full_markup_no_cap(self, api):
        """PRD §3.5: "A category-specific markup is applied to the submitted unit cost:
        15% for `LABOR`, 10% for `MATERIAL`, 12% for `EQUIPMENT`, 8% for `RESTORATION`."
        and "If the case's `severity` is `CRITICAL`, an emergency multiplier of 1.25 also
        applies; otherwise the multiplier is 1.00." LABOR 30x12000 on a MAJOR case:
        30 * 12000 * 1.15 * 1.00 = 414000, below the cap.

        Design: Difficulty/combinatorial_formula/cost_line_markup_cap_emergency_interaction
        """
        excavator = create_excavator()
        case = create_case(excavator["id"], "3 Elm St", "GAS", "MAJOR", "2026-05-04T09:00:00Z")
        resp = api.create_cost_line_item(
            {
                "damage_case_id": case["id"], "category": "LABOR", "description": "crew",
                "quantity": 30, "unit_cost_cents": 12000,
            },
            make_adjuster_headers(),
        )
        line = validate_success(resp, expected_status=201)
        assert line["line_total_cents"] == 414000, (
            f"expected 414000 (30*12000*1.15), got {line['line_total_cents']}"
        )

    def test_labor_line_critical_case_emergency_multiplier_clamped_by_cap(self, api):
        """PRD §3.5: "the line total is capped at 500000 cents (five thousand dollars)
        per line — if the rounded value exceeds the cap, the line total is the cap."
        LABOR 30x12000 on a CRITICAL case: 30 * 12000 * 1.15 * 1.25 = 517500 -> 500000.

        Design: Difficulty/combinatorial_formula/cost_line_markup_cap_emergency_interaction
        """
        excavator = create_excavator()
        case = create_case(excavator["id"], "3 Elm St", "GAS", "CRITICAL", "2026-05-04T11:00:00Z")
        resp = api.create_cost_line_item(
            {
                "damage_case_id": case["id"], "category": "LABOR", "description": "crew",
                "quantity": 30, "unit_cost_cents": 12000,
            },
            make_adjuster_headers(),
        )
        line = validate_success(resp, expected_status=201)
        assert line["line_total_cents"] == 500000, (
            f"expected cap 500000 (517500 uncapped), got {line['line_total_cents']}"
        )


class TestNestedRounding:
    def _setup_three_way_case(self):
        excavator = create_excavator()
        locator = create_locator()
        case = create_case(excavator["id"], "7 Birch Rd", "TELECOM", "MINOR",
                           "2026-05-05T09:00:00Z")
        add_evidence(case["id"], captured_at="2026-05-05T10:00:00Z")
        case = begin_investigation(case["id"], "inv-1")
        shares = [
            {"party_type": "EXCAVATOR", "party_id": excavator["id"], "share_bp": 3334},
            {"party_type": "LOCATOR", "party_id": locator["id"], "share_bp": 3333},
            {"party_type": "FACILITY_OWNER", "party_id": None, "share_bp": 3333},
        ]
        allocation = create_allocation(case["id"], case["version"],
                                       root_cause_code="MISMARK", shares=shares)
        return excavator, locator, case, allocation

    def test_per_line_rounding_before_case_sum(self, api):
        """PRD §3.5: "the result is rounded half-up to a whole cent exactly once, at this
        final multiply" and "The per-line rounding happens before any case-level sum, so
        `subtotal_cents` is always the sum of already-rounded line totals." LABOR 1x1001
        rounds to 1151 and LABOR 1x1003 rounds to 1153; the case sums 2304 (a
        sum-then-round order would yield 2305).

        Design: Difficulty/combinatorial_formula/nested_rounding_per_line_then_allocate
        """
        _excavator, _locator, case, _allocation = self._setup_three_way_case()
        line1 = add_cost_line(case["id"], "LABOR", 1, 1001, description="l1")
        line2 = add_cost_line(case["id"], "LABOR", 1, 1003, description="l2")
        assert line1["line_total_cents"] == 1151, (
            f"round_half_up(1001*1.15)=1151 expected, got {line1['line_total_cents']}"
        )
        assert line2["line_total_cents"] == 1153, (
            f"round_half_up(1003*1.15)=1153 expected, got {line2['line_total_cents']}"
        )
        case_after = get_case(case["id"])
        assert case_after["subtotal_cents"] == 2304, (
            f"per-line-then-sum must give 1151+1153=2304, got {case_after['subtotal_cents']}"
        )

    def test_allocation_rounds_after_multiply_with_remainder_absorption(self, api):
        """PRD §3.5: "The largest share (highest `share_bp`; ties broken by lowest index
        in the allocation's `shares` array) is designated the residual recipient. For
        every non-largest share, the invoiced amount is the case's `subtotal_cents`
        multiplied by that share's `share_bp`, divided by 10000, rounded half-up to a
        whole cent." Subtotal 2304 at 3334/3333/3333 -> 768 + 768 + 768 = 2304 exactly.

        Design: Difficulty/combinatorial_formula/nested_rounding_per_line_then_allocate
        """
        excavator, locator, case, allocation = self._setup_three_way_case()
        add_cost_line(case["id"], "LABOR", 1, 1001, description="l1")
        add_cost_line(case["id"], "LABOR", 1, 1003, description="l2")
        propose_allocation(allocation["id"], "inv-1")
        finalize_allocation(allocation["id"], "mgr-1")
        invoices = list_case_invoices(case["id"])
        assert len(invoices) == 3
        for inv in invoices:
            assert inv["invoiced_cents"] == 768, (
                f"every share of 2304 at 3334/3333/3333 must invoice 768, "
                f"got {inv['invoiced_cents']} for debtor {inv['debtor_id']}"
            )
        case_after = get_case(case["id"])
        assert_case_invoice_conservation(case_after, invoices)


class TestInvoiceDualBasis:
    def _setup_finalized_standard_case(self):
        # Case with evidence, NO_TICKET rule-default allocation, the canonical cost
        # pair (LABOR 10x9000 + MATERIAL 5x3000), PROPOSED — ready to finalize.
        ctx = setup_proposed_allocation(
            root_cause_code="NO_TICKET", with_standard_costs=True,
            severity="MAJOR", dig_site_address="9 Pine St",
            occurred_at="2026-05-03T09:00:00Z", investigator_id="inv-2",
        )
        return ctx, ctx["case"], ctx["allocation"]

    def test_invoice_actual_cost_basis_is_billed(self, api):
        """PRD §3.5: "The actual basis uses the submitted `unit_cost_cents` and is the
        amount actually billed" — LABOR 10x9000 (103500) + MATERIAL 5x3000 (16500) gives
        a single excavator invoice of 120000.

        Design: Difficulty/dual_variant_calc/invoice_actual_vs_standard_basis_diverge
        """
        ctx, case, allocation = self._setup_finalized_standard_case()
        finalize_allocation(allocation["id"], "mgr-1")
        invoices = list_case_invoices(case["id"])
        assert len(invoices) == 1
        assert invoices[0]["invoiced_cents"] == 120000, (
            f"actual-basis billed amount must be 120000, got {invoices[0]['invoiced_cents']}"
        )

    def test_invoice_standard_basis_diverges_from_actual(self, api):
        """PRD §3.5: "the standard basis substitutes the standard rates and is surfaced
        only for comparison — identical inputs produce a different total whenever any
        submitted unit cost differs from the standard rate." Standard rates price the
        same lines at 10*9500*1.15 + 5*4000*1.10 = 109250 + 22000 = 131250.

        Design: Difficulty/dual_variant_calc/invoice_actual_vs_standard_basis_diverge
        """
        ctx, case, allocation = self._setup_finalized_standard_case()
        finalize_allocation(allocation["id"], "mgr-1")
        invoices = list_case_invoices(case["id"])
        assert len(invoices) == 1
        invoice = invoices[0]
        assert invoice["standard_basis_cents"] == 131250, (
            f"standard basis must be 131250, got {invoice['standard_basis_cents']}"
        )
        assert invoice["standard_basis_cents"] != invoice["invoiced_cents"]


class TestCostLineDelete:
    def test_delete_cost_line_recomputes_subtotal(self, api):
        """PRD §3.5: "A line may be removed only while the case's `recovery_status` is
        `COSTING` (otherwise `ERR_INVALID_STATE`); deletion recomputes `subtotal_cents`
        and bumps the case's `version`." Removing the 103500 LABOR line from a 120000
        subtotal leaves exactly 16500.

        Design: Corner/cross_cutting_layers/delete_cost_line_recomputes_subtotal
        """
        excavator = create_excavator()
        case = create_case(excavator["id"], "47 Heth St", "GAS", "MAJOR", "2026-05-02T09:00:00Z")
        line_labor = add_cost_line(case["id"], "LABOR", 10, 9000, description="crew")
        add_cost_line(case["id"], "MATERIAL", 5, 3000, description="pipe")
        case_mid = get_case(case["id"])
        assert case_mid["subtotal_cents"] == 120000
        resp = api.delete_cost_line_item(line_labor["id"], make_adjuster_headers())
        assert resp.status_code == 204, f"expected 204 on delete, got {resp.status_code}"
        case_after = get_case(case["id"])
        assert case_after["subtotal_cents"] == 16500
        lines_resp = api.list_cost_line_items(
            make_manager_headers(), params={"damage_case_id": case["id"]},
        )
        lines, _meta = validate_paginated(lines_resp)
        lines = [l for l in lines if l.get("damage_case_id") in (None, case["id"])]
        assert len(lines) == 1


class TestFinalizePreconditions:
    def test_finalize_without_evidence_returns_aggregate_error(self, api):
        """PRD §3.4: "the case's `evidence_count` must be at least 1 (otherwise
        `ERR_NO_SCENE_EVIDENCE`, HTTP 409)"

        Design: Corner/validations/finalize_without_evidence_returns_aggregate_error
        """
        excavator = create_excavator()
        case = create_case(excavator["id"], "25 Kappa St", "GAS", "MINOR", "2026-05-02T09:00:00Z")
        case = begin_investigation(case["id"], "inv-1")
        shares = [{"party_type": "EXCAVATOR", "party_id": excavator["id"], "share_bp": 10000}]
        allocation = create_allocation(case["id"], case["version"],
                                       root_cause_code="NO_TICKET", shares=shares)
        propose_allocation(allocation["id"], "inv-1")
        resp = api.finalize_fault_allocation(allocation["id"], {}, make_manager_headers("mgr-1"))
        validate_error(resp, ApiErrorId.ERR_NO_SCENE_EVIDENCE, expected_status=409)
        assert get_allocation(allocation["id"])["status"] == "PROPOSED"

    def test_finalize_over_cap_without_override_rejected(self, api):
        """PRD §3.4: "the case's `subtotal_cents` must not exceed 5000000 cents (fifty
        thousand dollars) unless `override_authority_cap` is passed as true (otherwise
        `ERR_INVOICE_AUTHORITY_CAP_EXCEEDED`, HTTP 409)." Eleven LABOR lines of 40x12000
        each clamp to the 500000 per-line cap, for a subtotal of 5500000.

        Design: Corner/errors/finalize_over_cap_without_override_rejected
        """
        excavator = create_excavator()
        case = create_case(excavator["id"], "43 Daleth St", "GAS", "MAJOR", "2026-05-02T09:00:00Z")
        add_evidence(case["id"])
        case = begin_investigation(case["id"], "inv-1")
        shares = [{"party_type": "EXCAVATOR", "party_id": excavator["id"], "share_bp": 10000}]
        allocation = create_allocation(case["id"], case["version"],
                                       root_cause_code="NO_TICKET", shares=shares)
        for i in range(11):
            add_cost_line(case["id"], "LABOR", 40, 12000, description=f"c{i + 1}")
        case_mid = get_case(case["id"])
        assert case_mid["subtotal_cents"] == 5500000
        propose_allocation(allocation["id"], "inv-1")
        resp = api.finalize_fault_allocation(allocation["id"], {}, make_manager_headers("mgr-1"))
        validate_error(resp, ApiErrorId.ERR_INVOICE_AUTHORITY_CAP_EXCEEDED, expected_status=409)
        assert get_allocation(allocation["id"])["status"] == "PROPOSED"
