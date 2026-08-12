"""Rent roll: cash vs straight-line basis divergence on an escalated term."""
from test_helpers import (
    add_schedule_line,
    create_lease,
    create_property,
    set_clock,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["portfolio_manager_headers"]
ACCT = TEST_USERS["lease_accountant_headers"]


def _two_year_escalated_lease(api):
    """Two-year term (2026-01-01 to 2027-12-31): year-one line at 1200000
    without escalation, year-two line at 1200000 with a 10% FIXED_PCT step
    (effective 1320000). Term rent 2520000 over 730 days; FY2026 holds 365
    in-term days."""
    set_clock("2026-06-01T00:00:00Z")
    prop = create_property()
    lease = create_lease(
        prop["id"],
        tenant_legal_name="T1", suite="100", leased_sf=4000,
        commencement_date="2026-01-01", expiration_date="2027-12-31",
        base_rent_annual_cents=1200000, escalation_type="FIXED_PCT",
        recovery_structure="NNN", pro_rata_share_bps=4000,
        security_deposit_cents=0,
    )
    step = validate_success(
        api.create_escalation_step(
            lease["id"],
            {"step_index": 1, "kind": "FIXED_PCT", "pct_bps": 1000,
             "effective_on": "2027-01-01"},
            PM,
        ),
        201,
    )
    add_schedule_line(lease["id"], period_start="2026-01-01",
                      period_end="2027-01-01", base_rent_cents=1200000)
    line2 = add_schedule_line(
        lease["id"], period_start="2027-01-01", period_end="2028-01-01",
        base_rent_cents=1200000, escalation_step_id=step["id"],
    )
    assert line2["effective_rent_cents"] == 1320000
    return lease


class TestRentRollCashVsStraightLine:
    def test_cash_basis_sums_scheduled_lines_in_fiscal_year(
        self, api, lease_accountant_headers
    ):
        """PRD §3.9: "The default `cash` basis reports the lease's
        `cached_annual_rent_cents` — the sum of scheduled, per-line-rounded
        `effective_rent_cents` overlapping the fiscal year as defined in §3.3."
        (Only the 2026 line overlaps FY2026, so the cash basis reports
        1200000.)

        Design: Difficulty/dual_variant_calc/rent_roll_cash_vs_straight_line
        """
        lease = _two_year_escalated_lease(api)
        data = validate_success(
            api.get_rent_roll(
                lease["id"], lease_accountant_headers,
                params={"fiscal_year": 2026, "basis": "cash"},
            )
        )
        assert data["total_rent_cents"] == 1200000, (
            f"cash basis must report the scheduled FY2026 rent, got "
            f"{data['total_rent_cents']}"
        )
        assert data["basis"] == "cash"
        assert data["fiscal_year"] == 2026

    def test_straight_line_basis_smooths_escalation_across_term(
        self, api, lease_accountant_headers
    ):
        """PRD §3.9: "The `straight_line` basis instead smooths rent evenly
        across the entire lease term per GAAP: the total term rent is the sum
        of `effective_rent_cents` over all schedule lines, the term length is
        the total number of days across all lines, and the fiscal-year
        allocation is the total term rent multiplied by the number of in-term
        days falling inside the fiscal-year window and divided by the total
        term days, with the intermediate division kept as an exact rational and
        only the final figure rounded half-up to whole cents. The two bases
        diverge whenever escalations are non-flat, because straight-lining
        spreads each escalation across the whole term."
        (2520000 total over 730 days; FY2026 holds 365 in-term days, so the
        straight-line figure is round_half_up(2520000 * 365 / 730) = 1260000.)

        Design: Difficulty/dual_variant_calc/rent_roll_cash_vs_straight_line
        """
        lease = _two_year_escalated_lease(api)
        cash = validate_success(
            api.get_rent_roll(
                lease["id"], lease_accountant_headers,
                params={"fiscal_year": 2026, "basis": "cash"},
            )
        )
        sl = validate_success(
            api.get_rent_roll(
                lease["id"], lease_accountant_headers,
                params={"fiscal_year": 2026, "basis": "straight_line"},
            )
        )
        assert sl["total_rent_cents"] == 1260000, (
            f"straight-line must smooth the 10% step across the term, got "
            f"{sl['total_rent_cents']}"
        )
        assert sl["total_rent_cents"] - cash["total_rent_cents"] == 60000, (
            "the two bases must diverge by exactly the smoothed half of the "
            "escalation (60000)"
        )
