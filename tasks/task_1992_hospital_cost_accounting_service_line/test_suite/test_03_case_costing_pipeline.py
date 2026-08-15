"""Case costing pipeline: allocation bases, pinned rounding order (PRD §3.4)."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_active_cost_model,
    create_case,
    create_drg,
    create_minutes_center,
    create_overhead_center,
    create_physician,
    create_rvu_center,
    create_service_line,
    add_activity_line,
    post_case,
)

FC = TEST_USERS["finance_controller_headers"]
CA = TEST_USERS["cost_analyst_headers"]


class TestDualVariantDivergence:
    def test_tdabc_vs_rvu_identical_minutes_diverge(self, api):
        """PRD §2.6: "The two bases are not cosmetic variants: identical financial
        data costs differently under them, which is precisely why the choice of
        basis is a governed attribute of the model rather than a report-time
        switch."
        PRD §3.4: "The case's `total_indirect_allocated` is the total activity
        amount plus the full overhead pool."

        Design: Difficulty/dual_variant_calc/tdabc_vs_rvu_identical_minutes_diverge
        """
        sl = create_service_line(name="Orthopedic Surgery", code="ORTHO",
                                 base_direct_cost=9000.00, budgeted_volume=120)
        cc_mins = create_minutes_center(name="OR Minutes", code="ORMINS",
                                        allocated_cost=12000.00,
                                        practical_capacity_minutes=8000)
        cc_rvu = create_rvu_center(name="OR RVU", code="ORRVU",
                                   allocated_cost=12000.00, total_rvu=4000.0)
        cc_periop = create_overhead_center(name="Periop Services", code="PERIOP",
                                           allocated_cost=7000.00)
        phys = create_physician(npi="1000000001", full_name="Dr. One",
                                specialty="Orthopedics")
        drg = create_drg(drg_code="470", description="Major joint replacement",
                         target_cost=750.00, base_rate=30000.00)
        m_tdabc, m_tdabc_v = create_active_cost_model(
            name="ORTHO-TDABC", service_line_id=sl["id"], allocation_basis="TDABC",
            rate_factor=1.20, overhead_cost_center_id=cc_periop["id"],
            effective_period="2026-01")
        m_rvu, m_rvu_v = create_active_cost_model(
            name="ORTHO-RVU", service_line_id=sl["id"], allocation_basis="RVU",
            rate_factor=1.00, overhead_cost_center_id=cc_periop["id"],
            effective_period="2026-01")

        case_a = create_case(service_line_id=sl["id"], physician_id=phys["id"],
                             drg_id=drg["id"], cost_model_id=m_tdabc["id"],
                             period="2026-08", expected_reimbursement=30000.00)
        add_activity_line(case_a["id"], cc_mins["id"], 100)
        case_b = create_case(service_line_id=sl["id"], physician_id=phys["id"],
                             drg_id=drg["id"], cost_model_id=m_rvu["id"],
                             period="2026-08", expected_reimbursement=30000.00)
        add_activity_line(case_b["id"], cc_rvu["id"], 100)

        posted_a = post_case(case_a["id"], m_tdabc_v)
        posted_b = post_case(case_b["id"], m_rvu_v)

        # TDABC: activity round_half_up(100 * (12000/8000) * 1.20) = 180.00; + pool 7000.00
        assert posted_a["total_indirect_allocated"] == pytest.approx(7180.00, abs=0.005)
        # RVU: activity round_half_up(100 * (12000/4000) * 1.00) = 300.00; + pool 7000.00
        assert posted_b["total_indirect_allocated"] == pytest.approx(7300.00, abs=0.005)
        assert posted_a["total_indirect_allocated"] != posted_b["total_indirect_allocated"]

    def test_tdabc_case_margin_reflects_pipeline(self, api):
        """PRD §3.4: "The case's `total_direct_cost` is its service line's
        `base_direct_cost` plus the sum of each implant's `unit_cost` multiplied
        by its `quantity`, plus the sum of each supply line's `unit_cost`
        multiplied by its `quantity`."
        PRD §3.4: "The case's `margin` is its `expected_reimbursement` minus
        `total_cost`."

        Design: Difficulty/dual_variant_calc/tdabc_vs_rvu_identical_minutes_diverge
        """
        sl = create_service_line(name="Orthopedic Surgery", code="ORTHO",
                                 base_direct_cost=9000.00, budgeted_volume=120)
        cc_mins = create_minutes_center(name="OR Minutes", code="ORMINS",
                                        allocated_cost=12000.00,
                                        practical_capacity_minutes=8000)
        cc_periop = create_overhead_center(name="Periop Services", code="PERIOP",
                                           allocated_cost=7000.00)
        phys = create_physician(npi="1000000001", full_name="Dr. One",
                                specialty="Orthopedics")
        drg = create_drg(drg_code="470", description="Major joint replacement",
                         target_cost=750.00, base_rate=30000.00)
        model, model_v = create_active_cost_model(
            name="ORTHO-TDABC", service_line_id=sl["id"], allocation_basis="TDABC",
            rate_factor=1.20, overhead_cost_center_id=cc_periop["id"],
            effective_period="2026-01")
        case = create_case(service_line_id=sl["id"], physician_id=phys["id"],
                           drg_id=drg["id"], cost_model_id=model["id"],
                           period="2026-08", expected_reimbursement=30000.00)
        add_activity_line(case["id"], cc_mins["id"], 100)

        posted = post_case(case["id"], model_v)
        assert posted["total_direct_cost"] == pytest.approx(9000.00, abs=0.005)
        assert posted["total_indirect_allocated"] == pytest.approx(7180.00, abs=0.005)
        assert posted["total_cost"] == pytest.approx(16180.00, abs=0.005)
        assert posted["margin"] == pytest.approx(30000.00 - 16180.00, abs=0.005)


class TestPinnedRoundingOrder:
    def test_per_line_round_then_sum_order_pinned(self, api):
        """PRD §2.5: "Where a pipeline produces several intermediate amounts
        (notably the case-costing pipeline of §3.4), each line-level amount is
        rounded half-up to two decimal places individually, before any summation
        takes place; summing unrounded raw values and rounding once at the end
        is forbidden."
        PRD §3.4: "The line's `allocated_amount` is that raw amount rounded
        half-up to two decimal places — each line rounded before any summation,
        per §2.5."

        Design: Difficulty/combinatorial_formula/per_line_round_then_sum_order_pinned
        """
        sl = create_service_line(name="Neurosurgery", code="NEURO",
                                 base_direct_cost=5000.00, budgeted_volume=40)
        cc_mins = create_minutes_center(name="OR Minutes N", code="ORMINS2",
                                        allocated_cost=12360.00,
                                        practical_capacity_minutes=8000)
        cc_periop = create_overhead_center(name="Periop N", code="PERIOP2",
                                           allocated_cost=100.00)
        phys = create_physician(npi="1000000001", full_name="Dr. One",
                                specialty="Neurosurgery")
        drg = create_drg(drg_code="470", description="Major joint replacement",
                         target_cost=750.00, base_rate=30000.00)
        model, model_v = create_active_cost_model(
            name="NEURO-TDABC", service_line_id=sl["id"], allocation_basis="TDABC",
            rate_factor=1.00, overhead_cost_center_id=cc_periop["id"],
            effective_period="2026-01")
        case = create_case(service_line_id=sl["id"], physician_id=phys["id"],
                           drg_id=drg["id"], cost_model_id=model["id"],
                           period="2026-08", expected_reimbursement=20000.00)
        for _ in range(3):
            add_activity_line(case["id"], cc_mins["id"], 7)

        posted = post_case(case["id"], model_v)

        from test_helpers import validate_paginated
        lines, _m = validate_paginated(api.list_activity_lines(case["id"], CA))
        assert len(lines) == 3
        # Capacity rate = 12360 / 8000 = 1.545/min; round_half_up(7 * 1.545) = 10.82 each
        for line in lines:
            assert line["allocated_amount"] == pytest.approx(10.82, abs=0.005)
        # total_indirect = 3 * 10.82 (32.46) + pool 100.00 = 132.46;
        # the forbidden sum-then-round order would give 32.45 + 100.00 = 132.45.
        assert posted["total_indirect_allocated"] == pytest.approx(132.46, abs=0.005)

    def test_per_line_rounding_visible_on_single_line(self, api):
        """PRD §3.4: "The line's raw amount is its `quantity` multiplied by that
        capacity rate, multiplied by the model's `rate_factor`. The line's
        `allocated_amount` is that raw amount rounded half-up to two decimal
        places — each line rounded before any summation, per §2.5."

        Design: Difficulty/combinatorial_formula/per_line_round_then_sum_order_pinned
        """
        sl = create_service_line(name="Neurosurgery", code="NEURO",
                                 base_direct_cost=5000.00, budgeted_volume=40)
        cc_mins = create_minutes_center(name="OR Minutes N", code="ORMINS2",
                                        allocated_cost=12360.00,
                                        practical_capacity_minutes=8000)
        cc_periop = create_overhead_center(name="Periop N", code="PERIOP2",
                                           allocated_cost=100.00)
        phys = create_physician(npi="1000000001", full_name="Dr. One",
                                specialty="Neurosurgery")
        drg = create_drg(drg_code="470", description="Major joint replacement",
                         target_cost=750.00, base_rate=30000.00)
        model, model_v = create_active_cost_model(
            name="NEURO-TDABC", service_line_id=sl["id"], allocation_basis="TDABC",
            rate_factor=1.00, overhead_cost_center_id=cc_periop["id"],
            effective_period="2026-01")
        case = create_case(service_line_id=sl["id"], physician_id=phys["id"],
                           drg_id=drg["id"], cost_model_id=model["id"],
                           period="2026-08", expected_reimbursement=20000.00)
        add_activity_line(case["id"], cc_mins["id"], 7)
        post_case(case["id"], model_v)

        from test_helpers import validate_paginated
        lines, _m = validate_paginated(api.list_activity_lines(case["id"], CA))
        assert len(lines) == 1
        # 7 * 1.545 = 10.815 -> round-half-up 10.82 (round-half-even would give 10.81)
        assert lines[0]["allocated_amount"] == pytest.approx(10.82, abs=0.005)
