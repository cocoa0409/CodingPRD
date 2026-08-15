"""Budget line OCC, fiscal-year close variant flip, and retention rollup
zero-denominator handling (PRD §2.7, §2.9, §3.6, §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_claim,
    create_budget_line,
    create_claim,
    create_certification,
    create_nurse,
    get_budget_line,
    run_ops_cycle,
    set_clock,
    update_budget_line_payload,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
ANALYST = TEST_USERS["retention_analyst_headers"]


class TestBudgetLineOcc:
    def test_occ_stale_budget_line_on_update(self, api):
        """PRD §2.7: "Updating a budget line's allocation requires
        `expected_budget_line_version`, matching the budget line's current
        `version`. If a reimbursement approval cascade has just recomputed
        `committed_cents` on the same line since the client last read it, the
        allocation edit is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/endpoints/occ_stale_budget_line_on_update
        """
        set_clock("2026-08-01T00:00:00Z")
        line = create_budget_line("ICU-4W", 2027, 9000000)
        stale_version = line["version"]
        nurse = create_nurse(employee_code="RN-OCC3", full_name="Occ Three",
                             hire_date="2021-01-01T00:00:00Z", home_unit="ICU-4W")
        cert = create_certification(nurse["id"], track="BASIC")
        claim = create_claim(cert["id"], nurse["id"], 30000)
        approve_claim(claim["id"])  # cascade recomputes committed_cents
        resp = api.update_budget_line(
            line["id"],
            update_budget_line_payload(
                allocated_cents=8000000,
                expected_budget_line_version=stale_version,
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


class TestFiscalYearClose:
    def test_ops_cycle_closes_fiscal_year_flips_variant(self, api):
        """PRD §2.9: "One sweep lapses every certification whose expiry has
        passed, expires every review assignment whose scoring window has
        closed, lapses every anniversary review left open past its review
        year's end, closes budget lines whose fiscal year has ended by flipping
        their forecast variant to `FINAL`, and captures retention snapshot
        rows."
        PRD §3.6: "When the ops-run sweep closes the fiscal year, the variant
        flips to `FINAL`..."

        Design: Corner/cross_cutting_layers/ops_cycle_closes_fiscal_year_flips_variant
        """
        set_clock("2025-08-01T00:00:00Z")
        line = create_budget_line("MED-2E", 2026, 5000000)
        assert line["forecast_variant"] == "PROVISIONAL", (
            "an open fiscal year must start PROVISIONAL"
        )
        set_clock("2026-07-15T00:00:00Z")  # past FY2026's end of 2026-06-30
        run_ops_cycle()
        after = get_budget_line(line["id"])
        assert after["forecast_variant"] == "FINAL", (
            f"closed fiscal year must flip the variant to FINAL, got {after['forecast_variant']}"
        )


class TestRetentionRollup:
    def test_retention_rollup_zero_denominator(self, api):
        """PRD §3.7: "During the ops-run sweep the system captures one
        `RetentionSnapshot` per unit plus one hospital-wide row whose `unit`
        reads "ALL"..."
        PRD §3.7: "An empty unit is not an error: its demotion rate is 0.0000."

        Design: Corner/calculations/retention_rollup_zero_denominator
        """
        set_clock("2026-08-01T00:00:00Z")
        run_ops_cycle()
        rows = validate_success(
            api.list_retention_snapshots(ANALYST, params={"unit": "ALL"})
        )
        assert len(rows) == 1, (
            f"the hospital-wide ALL row must be captured even with no nurses, got {len(rows)}"
        )
        row = rows[0]
        assert row["unit"] == "ALL"
        assert row["demotion_rate"] == 0, (
            f"empty population demotion rate must be 0.0000, got {row['demotion_rate']}"
        )
        headcount = row["headcount_by_level"]
        assert all(headcount.get(level, 0) == 0
                   for level in ("CN_I", "CN_II", "CN_III", "CN_IV"))
