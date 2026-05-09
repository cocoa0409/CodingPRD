"""Indirect-cost allocation tests: rate table, threshold tier, periodic vs scoped runs.

PRD §3.8 (indirect-cost allocation).
"""
import pytest
import uuid

from test_helpers import (
    ApiErrorId,
    api_client,
    create_allocation_run_payload,
    create_and_pay_reimbursement,
    setup_active_project_with_budget,
    setup_two_projects_with_paid_materials,
    TEST_USERS,
    validate_success,
)


class TestRateTable:
    """PRD §3.8 indirect-cost rate by funding source × allocation_base."""

    def test_national_direct_cost_rate(self, api):
        """PRD §3.8: "NATIONAL project: 0.20 with DIRECT_COST, 0.25 with PERSONNEL_COST,
        0.15 with FLOOR_AREA."

        # difficulty: combinatorial_formula/indirect_cost_rate_table_three_input_nonlinear

        Claim: NATIONAL + DIRECT_COST + total_budget=800000 (under threshold)
        produces allocation_rate==0.2000.
        """
        # Project under 1M threshold (so no -0.02 reduction).
        project, items = setup_active_project_with_budget(
            api, pi_id="pi-rate-natl-small", funding_source="NATIONAL",
            categories=[("MATERIALS", 800000.00)],
        )
        create_and_pay_reimbursement(api, project=project, budget_item=items[0],
                                      amount=300.00,
                                      invoice_number=f"INV-NATL-{uuid.uuid4().hex[:6]}")
        finance = TEST_USERS["finance_headers"]
        resp = api.create_allocation_run(
            create_allocation_run_payload(allocation_base="DIRECT_COST",
                                            project_id=project["id"]),
            finance,
        )
        # PRD §4: POST /allocation-runs returns 201 with IndirectCostAllocation[]
        from test_helpers import get_success_data
        body = get_success_data(resp)
        rows = body if isinstance(body, list) else body.get("rows", [body])
        # Find the row for our project.
        our_rows = [r for r in rows if r.get("project_id") == project["id"]]
        assert len(our_rows) >= 1, f"Expected an allocation row for project; got {rows}"
        row = our_rows[0]
        assert row["allocation_rate"] == pytest.approx(0.2000, abs=0.0001), \
            f"NATIONAL+DIRECT_COST under 1M should be 0.2000, got {row['allocation_rate']}"

    def test_national_direct_cost_threshold_tier_reduction(self, api):
        """PRD §3.8: "A threshold tier reduces this rate. If the project's total_budget
        is strictly greater than 1,000,000 CNY, the rate is decreased by 0.02 — but
        never below zero (the rate is the maximum of zero and the table value minus 0.02)."

        # difficulty: combinatorial_formula/indirect_cost_rate_table_three_input_nonlinear

        Claim: NATIONAL + DIRECT_COST + total_budget=1500000 (over threshold) produces
        allocation_rate==0.18 (0.20 - 0.02).
        """
        project, items = setup_active_project_with_budget(
            api, pi_id="pi-rate-natl-big", funding_source="NATIONAL",
            categories=[("MATERIALS", 1500000.00)],
        )
        create_and_pay_reimbursement(api, project=project, budget_item=items[0],
                                      amount=500.00,
                                      invoice_number=f"INV-NATL-BIG-{uuid.uuid4().hex[:6]}")
        finance = TEST_USERS["finance_headers"]
        resp = api.create_allocation_run(
            create_allocation_run_payload(allocation_base="DIRECT_COST",
                                            project_id=project["id"]),
            finance,
        )
        from test_helpers import get_success_data
        body = get_success_data(resp)
        rows = body if isinstance(body, list) else body.get("rows", [body])
        our_rows = [r for r in rows if r.get("project_id") == project["id"]]
        assert len(our_rows) >= 1, f"Expected an allocation row for project; got {rows}"
        row = our_rows[0]
        assert row["allocation_rate"] == pytest.approx(0.1800, abs=0.0001), \
            f"NATIONAL+DIRECT_COST over 1M should be 0.1800 (=0.20 - 0.02), got {row['allocation_rate']}"


class TestPeriodicVsScopedRuns:
    """PRD §3.8 periodic-recalculation variant vs scoped variant."""

    def test_periodic_run_writes_one_row_per_active_project(self, api):
        """PRD §3.8: "When project_id is omitted, the periodic-recalculation variant runs
        across every project whose status is ACTIVE or CLOSING, appending one
        IndirectCostAllocation row per project under a single shared allocation_run_id."

        # difficulty: dual_variant_calc/indirect_cost_periodic_vs_closing_cascade

        Claim: a periodic run (no project_id) produces N rows for N in-scope projects,
        all sharing one allocation_run_id.
        """
        p1, p2 = setup_two_projects_with_paid_materials(api)
        finance = TEST_USERS["finance_headers"]
        resp = api.create_allocation_run(
            create_allocation_run_payload(allocation_base="DIRECT_COST"),
            finance,
        )
        from test_helpers import get_success_data
        body = get_success_data(resp)
        rows = body if isinstance(body, list) else body.get("rows", [body])
        # Both projects should have rows.
        ids = {r.get("project_id") for r in rows}
        assert p1["id"] in ids and p2["id"] in ids, \
            f"Periodic run must produce rows for every ACTIVE/CLOSING project; got {ids}"
        # All rows from this run share one allocation_run_id.
        run_ids = {r.get("allocation_run_id") for r in rows
                    if r.get("project_id") in (p1["id"], p2["id"])}
        assert len(run_ids) == 1, \
            f"Periodic run must use a single shared allocation_run_id; got {run_ids}"

    def test_scoped_run_writes_one_row_with_distinct_run_id(self, api):
        """PRD §3.8: "When project_id is supplied, the run is scoped to a single project
        and uses the previous run's pool remainder as the ceiling — this is the same code
        path the closing-audit close cascade exercises automatically for a single project."

        # difficulty: dual_variant_calc/indirect_cost_periodic_vs_closing_cascade

        Claim: a scoped run (project_id supplied) writes exactly one IndirectCostAllocation
        row whose allocation_run_id differs from the previous periodic run's run_id.
        """
        p1, p2 = setup_two_projects_with_paid_materials(api)
        finance = TEST_USERS["finance_headers"]
        # 1) Periodic run first to seed a previous run id.
        from test_helpers import get_success_data
        resp_periodic = api.create_allocation_run(
            create_allocation_run_payload(allocation_base="DIRECT_COST"),
            finance,
        )
        body_p = get_success_data(resp_periodic)
        rows_p = body_p if isinstance(body_p, list) else body_p.get("rows", [body_p])
        run_ids_periodic = {r.get("allocation_run_id") for r in rows_p
                              if r.get("project_id") in (p1["id"], p2["id"])}
        # 2) Now scoped run for p1 only.
        resp_scoped = api.create_allocation_run(
            create_allocation_run_payload(allocation_base="DIRECT_COST",
                                           project_id=p1["id"]),
            finance,
        )
        body_s = get_success_data(resp_scoped)
        rows_s = body_s if isinstance(body_s, list) else body_s.get("rows", [body_s])
        # Scoped run must produce exactly 1 row for p1.
        scoped_for_p1 = [r for r in rows_s if r.get("project_id") == p1["id"]]
        assert len(scoped_for_p1) == 1, \
            f"Scoped run on a single project should yield exactly 1 row; got {scoped_for_p1}"
        run_id_scoped = scoped_for_p1[0]["allocation_run_id"]
        # The two run_ids must be distinct.
        assert run_id_scoped not in run_ids_periodic, \
            f"Scoped run_id ({run_id_scoped}) must differ from prior periodic run_ids ({run_ids_periodic})"
