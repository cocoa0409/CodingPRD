"""Fleet replacement planning: weighted scoring snapshot, recommendation
bands, and the single-open-plan guard."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_labor,
    assert_replacement_plan,
    create_in_progress_wo,
    create_replacement_plan_payload,
    get_success_data,
    issue_line,
    line_event,
    make_mechanic_headers,
    new_bus,
    new_mechanic,
    new_part,
    new_qa_mechanic,
    reserve_line,
    validate_error,
    validate_success,
    wo_event,
)
from test_helpers import fixtures as fx


class TestReplacementScore:
    """Four weighted terms with min() caps; the PM-overdue multiplier branch is
    not taken when no active policy exists."""

    def _setup(self):
        bus = new_bus(
            fleet_number="B300", vin="VINB300", model_year=2020,
            in_service_date="2020-08-01", initial_odometer_miles=300_000,
            base_warranty_expiry_miles=100_000,
            base_warranty_expiry_date="2024-01-01",
            overhaul_interval_miles=250_000,
        )
        part = new_part(sku="P-ENG", description="Engine kit",
                        unit_cost_cents=4_496_750, initial_on_hand=5)
        return bus, part

    def _close_cost_wo(self, bus, part):
        """Closed WO costing exactly 9,000,000c: parts 2 x 4,496,750 consumed
        plus 1h AM labor (6500)."""
        lead = new_mechanic(name="Lead", employee_ref="E20")
        qa = new_qa_mechanic()
        wo = create_in_progress_wo(
            bus["id"], lead, planned_start_date="2026-07-10",
            planned_end_date="2026-07-12", estimated_labor_hours=1,
            estimated_cost_cents=9_000_000,
        )
        line = reserve_line(wo["id"], part["id"], qty=2)
        issue_line(line["id"])
        get_success_data(line_event(line["id"], "CONSUME"))
        add_labor(wo["id"], lead, work_date="2026-07-11", hours=1)
        wo_event(wo["id"], "SUBMIT_QA",
                 headers=make_mechanic_headers(lead["id"]))
        return get_success_data(
            wo_event(wo["id"], "QA_CERTIFY",
                     headers=make_mechanic_headers(qa["id"]))
        )

    def _create_plan_and_entry(self, api, fleet_manager_headers):
        plan = validate_success(
            api.create_replacement_plan(
                create_replacement_plan_payload(plan_year=2027),
                fleet_manager_headers,
            ),
            201,
        )
        assert_replacement_plan(plan)
        return plan

    def test_weighted_score_and_recommendation(self, api, fleet_manager_headers):
        """PRD §3.11: "Each bus's score composes four weighted terms. The age
        term is `age_years` — the whole-year floor of the days between
        `in_service_date` and the clock date divided by 365 — normalized by 12
        years and capped at 1, then weighted at 0.30. The mileage term is
        `odometer_miles` normalized by 500,000 miles and capped at 1, weighted
        at 0.30. The cost term is `total_maintenance_cost_cents` divided by
        `replacement_cost_cents`, capped at 1, weighted at 0.25. The overhaul
        term is a binary flag that is 1 when (`odometer_miles` minus
        `last_overhaul_miles`) exceeds `overhaul_interval_miles`, weighted at
        0.15. The weighted sum is then adjusted: if the bus's `pm_due_status`
        is `OVERDUE` (with no active policy counting as `CURRENT`), the score
        is multiplied by 1.25 and capped at 1."
        PRD §3.11: "`REPLACE` when the score is at least 0.70, `OVERHAUL` when
        the score is at least 0.45 but below 0.70, and `KEEP` otherwise."

        age 6y -> 0.30*0.5; miles 300000 -> 0.30*0.6; cost ratio 0.3 ->
        0.25*0.3; overhaul overdue -> 0.15*1; total 0.555. No PM policy exists,
        so pm_due_status counts as CURRENT and the 1.25 branch is skipped.

        Design: Difficulty/combinatorial_formula/replacement_score_weighted_multifactor_conditional_branch
        """
        bus, part = self._setup()
        self._close_cost_wo(bus, part)

        plan = self._create_plan_and_entry(api, fleet_manager_headers)
        assert len(plan["scores"]) == 1
        entry = plan["scores"][0]
        assert entry["bus_id"] == bus["id"]
        assert entry["score"] == pytest.approx(0.555, abs=1e-4), (
            f"0.30*0.5 + 0.30*0.6 + 0.25*0.3 + 0.15*1 = 0.555; got "
            f"{entry['score']} (a 1.25x multiplier would give 0.6938)"
        )
        assert entry["recommendation"] == "OVERHAUL", (
            "0.555 is at least 0.45 but below 0.70"
        )

    def test_snapshot_carries_input_values(self, api, fleet_manager_headers):
        """PRD §3.11: "Each snapshot entry also carries the input values —
        `bus_id`, `age_years`, `odometer_miles`, `cost_ratio`, and
        `overhaul_overdue` — and a `recommendation`"
        PRD §3.11: "A `FleetManager` creates a plan for a `plan_year`; the
        system computes a replacement score for every bus whose
        `service_status` is `ACTIVE` (buses in `OVERHAUL_HOLD` or `RETIRED` are
        excluded) and freezes the results into the plan's `scores` array."

        Design: Difficulty/combinatorial_formula/replacement_score_weighted_multifactor_conditional_branch
        """
        bus, part = self._setup()
        self._close_cost_wo(bus, part)

        plan = self._create_plan_and_entry(api, fleet_manager_headers)
        assert len(plan["scores"]) == 1, (
            "only the single ACTIVE bus is scored"
        )
        entry = plan["scores"][0]
        assert entry["age_years"] == 6, "whole-year floor at clock 2026-08-01"
        assert entry["odometer_miles"] == 300_000
        assert entry["cost_ratio"] == pytest.approx(0.3, abs=1e-9), (
            "9,000,000 / 30,000,000"
        )
        assert entry["overhaul_overdue"] == 1, (
            "300000 - 0 exceeds the 250000 interval"
        )
        assert entry["recommendation"] == "OVERHAUL"


def test_replacement_plan_second_open_rejected(api, fleet_manager_headers):
    """PRD §3.11: "Only one plan may be open at a time — a create while
    another plan is in `DRAFT`, `APPROVED`, or `EXECUTING` is rejected with
    `ERR_PLAN_ALREADY_OPEN`."

    Design: Corner/validations/replacement_plan_second_open_rejected
    """
    new_bus(fleet_number="Y24", vin="VINY24", model_year=2021,
            base_warranty_expiry_miles=5_000,
            base_warranty_expiry_date="2024-01-01")
    first = validate_success(
        api.create_replacement_plan(
            create_replacement_plan_payload(plan_year=2027),
            fleet_manager_headers,
        ),
        201,
    )
    assert first["status"] == "DRAFT"
    assert isinstance(first["scores"], list) and len(first["scores"]) == 1

    res = api.create_replacement_plan(
        create_replacement_plan_payload(plan_year=2028), fleet_manager_headers
    )
    validate_error(res, ApiErrorId.ERR_PLAN_ALREADY_OPEN)
