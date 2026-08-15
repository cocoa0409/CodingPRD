"""Case-post side effects, derived-field reconciliation, immediate consistency
(PRD §2.8, §3.4)."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_implant,
    add_supply_line,
    create_budget_period,
    create_case,
    post_case,
    setup_case_with_lines,
    setup_card_rvu,
    setup_ortho_tdabc,
    setup_posted_card_case,
    validate_success,
)

FC = TEST_USERS["finance_controller_headers"]
CA = TEST_USERS["cost_analyst_headers"]


class TestCasePostSideEffects:
    def test_case_post_side_effects_all_applied(self, api):
        """PRD §3.4: "Posting also stamps the case's `version_at_post` with the
        cost model's current `version` — a staleness marker used later — and
        increments the case's own `version` by one. In the same request, the
        ledger cascades of §2.8 fire: the service line's `total_direct_cost`,
        `total_revenue`, and `contribution_margin` absorb the case's
        contribution, and the budget period covering the case's `period` and the
        model's overhead pool recomputes its actual volume, flexed overhead, and
        variance."
        PRD §3.4: "The case's `total_direct_cost` is its service line's
        `base_direct_cost` plus the sum of each implant's `unit_cost` multiplied
        by its `quantity`, plus the sum of each supply line's `unit_cost`
        multiplied by its `quantity`."

        Design: Corner/endpoints/case_post_side_effects_all_applied
        """
        scenario = setup_card_rvu(period="2026-08", with_budget_period=True,
                                  static_budget_amount=7000.00)
        sl = scenario["service_line"]

        case = create_case(
            service_line_id=sl["id"], physician_id=scenario["physician"]["id"],
            drg_id=scenario["drg"]["id"], cost_model_id=scenario["model"]["id"],
            period="2026-08", expected_reimbursement=30000.00)
        from test_helpers import add_activity_line
        add_activity_line(case["id"], scenario["cc_lab"]["id"], 4)
        add_activity_line(case["id"], scenario["cc_rad"]["id"], 6)
        add_implant(case["id"], item_code="STENT-1", vendor="V1",
                    unit_cost=12000.00, quantity=1)
        add_supply_line(case["id"], supply_code="S1", unit_cost=500.00, quantity=1)
        add_supply_line(case["id"], supply_code="S2", unit_cost=300.00, quantity=1)

        posted = post_case(case["id"], scenario["model_version"])

        # direct = 10000 base + 12000 implant + 500 + 300 supplies = 22800.00
        assert posted["total_direct_cost"] == pytest.approx(22800.00, abs=0.005)
        # indirect = activity 28000.00 (4*2500 + 6*3000) + pool 7000.00
        assert posted["total_indirect_allocated"] == pytest.approx(35000.00, abs=0.005)
        assert posted["total_cost"] == pytest.approx(57800.00, abs=0.005)
        assert posted["margin"] == pytest.approx(-27800.00, abs=0.005)
        assert posted["version_at_post"] == scenario["model_version"]
        assert posted["status"] == "POSTED"

        # Service-line rollup (hop 1): base 10000 + case indirect 35000.00.
        line = validate_success(api.get_service_line(sl["id"], FC))
        assert line["total_direct_cost"] == pytest.approx(45000.00, abs=0.005)
        assert line["total_revenue"] == pytest.approx(30000.00, abs=0.005)
        assert line["contribution_margin"] == pytest.approx(-15000.00, abs=0.005)

        # Budget period (hop 2): actuals 28000.00 -> flex 0.35 * 28000 = 9800.00.
        bp = validate_success(
            api.get_budget_period(scenario["budget_period"]["id"], FC)
        )
        assert bp["actual_indirect_volume"] == pytest.approx(28000.00, abs=0.005)
        assert bp["flexed_overhead"] == pytest.approx(9800.00, abs=0.005)


class TestDerivedFieldReconciliation:
    def test_derived_field_reconciliation_after_implant_add_pre_post(self, api):
        """PRD §3.3: "A new case starts in `DRAFT` with its computed totals —
        `total_direct_cost`, `total_indirect_allocated`, `total_cost`, and
        `margin` — all initialized to zero."
        PRD §3.3: "The line's `allocated_amount` is computed when the case is
        posted and remains zero until then."

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_after_implant_add_pre_post
        """
        scenario = setup_ortho_tdabc(rate_factor=1.00)
        case = setup_case_with_lines(scenario, [100])
        add_implant(case["id"], item_code="HIP-1", vendor="V1",
                    unit_cost=5000.00, quantity=2)

        draft = validate_success(api.get_case(case["id"], CA))
        assert draft["total_direct_cost"] == pytest.approx(0.00, abs=0.005)
        assert draft["total_indirect_allocated"] == pytest.approx(0.00, abs=0.005)
        assert draft["total_cost"] == pytest.approx(0.00, abs=0.005)

        posted = post_case(case["id"], scenario["model_version"])
        # direct = base 9000 + implants 5000*2 = 19000.00
        assert posted["total_direct_cost"] == pytest.approx(19000.00, abs=0.005)


class TestImmediateConsistency:
    def test_immediate_consistency_rollup_visible_same_request_flow(self, api):
        """PRD §2.8: "These fields are not recomputed lazily on read; they are
        synchronized eagerly by the events that change them."
        PRD §2.8: "Events propagate in hops, and every cascade commits inside the
        triggering request — there is no asynchronous settlement."

        Design: Corner/consistency_model/immediate_consistency_rollup_visible_same_request_flow
        """
        scenario = setup_ortho_tdabc(rate_factor=1.20)
        sl_id = scenario["service_line"]["id"]
        case = setup_case_with_lines(scenario, [100, 120, 130, 80])
        post_case(case["id"], scenario["model_version"])

        # The very next GET reflects the updated rollup without delay.
        line = validate_success(api.get_service_line(sl_id, FC))
        # activity = (100+120+130+80) min * 1.50 * 1.20 = 774.00;
        # indirect = 774.00 + pool 7000.00 = 7774.00;
        # rollup total_direct_cost = base 9000 + 7774.00 = 16774.00 (PRD §2.8).
        assert line["total_direct_cost"] == pytest.approx(16774.00, abs=0.005)
        assert line["total_revenue"] == pytest.approx(30000.00, abs=0.005)
        assert line["contribution_margin"] == pytest.approx(30000.00 - 16774.00, abs=0.005)
