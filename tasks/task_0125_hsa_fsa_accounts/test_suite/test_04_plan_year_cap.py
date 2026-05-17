"""PlanYear creation and cap pinning — PRD §3.2.

Coverage targets:
- ContributionCap pinning rules by (account_type, coverage_tier,
  filing_status, age-at-Dec-31).
- (account_id, calendar_year) uniqueness -> ERR_DUPLICATE_PLAN_YEAR.
- Newly opened plan year is ACTIVE with zero counters and null
  grace_period_end_date.
- HSA catch-up boundary: age 55 at YYYY-12-31T23:59:59Z gates
  catch_up_cap_cents = 100_000 vs 0.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    assert_plan_year,
    create_account_holder,
    iso_datetime_utc,
    open_account,
    open_plan_year,
    setup_active_plan_year,
    setup_holder_and_account,
    validate_error,
    validate_success,
)


# ===========================================================================
# Cap pinning — PRD §3.2
# ===========================================================================
class TestPlanYearCapPinning:

    def test_hsa_self_only_cap_412500(self, api, plan_admin_headers):
        """PRD §3.2: "For an HSA with self-only coverage,
        contribution_cap_cents is set to 412,500 cents ($4,125.00)."

        Claim: HSA SELF_ONLY plan year's contribution_cap_cents == 412500.
        """
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        holder = create_account_holder(birth_date="1980-01-01")
        acct = open_account(
            holder, account_type="HSA", coverage_tier="SELF_ONLY",
            year_end_policy="NONE",
            account_holder_birth_date="1980-01-01",
        )
        resp = api.create_plan_year(
            acct["id"], {"calendar_year": 2025}, plan_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_plan_year(data)
        assert data["contribution_cap_cents"] == 412_500
        assert data["catch_up_cap_cents"] == 0
        assert data["status"] == "ACTIVE"

    def test_hsa_family_cap_830000(self, api, plan_admin_headers):
        """PRD §3.2: "For an HSA with family coverage, it is 830,000
        cents ($8,300.00)."

        Claim: HSA FAMILY plan year's contribution_cap_cents == 830_000.
        """
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        holder = create_account_holder(birth_date="1980-01-01")
        acct = open_account(
            holder, account_type="HSA", coverage_tier="FAMILY",
            year_end_policy="NONE",
            account_holder_birth_date="1980-01-01",
        )
        resp = api.create_plan_year(
            acct["id"], {"calendar_year": 2025}, plan_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["contribution_cap_cents"] == 830_000
        assert data["catch_up_cap_cents"] == 0

    def test_hsa_catch_up_when_age_at_least_55(
        self, api, plan_admin_headers,
    ):
        """PRD §3.2: "The HSA catch-up cap catch_up_cap_cents is
        100,000 cents ($1,000.00) if, on December 31 of the plan
        year's calendar_year (specifically, on the ISO instant
        YYYY-12-31T23:59:59Z where YYYY is the plan year), the
        account holder's age — counted in whole calendar years
        between account_holder_birth_date and that instant by
        month-and-day comparison, not by dividing days by 365.25 — is
        at least 55; otherwise it is 0."

        Claim: birth_date 1969-06-01 with calendar_year 2025 -> age 56
        at 2025-12-31T23:59:59Z -> catch_up_cap_cents == 100_000.
        """
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        holder = create_account_holder(birth_date="1969-06-01")
        acct = open_account(
            holder, account_type="HSA", coverage_tier="FAMILY",
            year_end_policy="NONE",
            account_holder_birth_date="1969-06-01",
        )
        resp = api.create_plan_year(
            acct["id"], {"calendar_year": 2025}, plan_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["contribution_cap_cents"] == 830_000
        assert data["catch_up_cap_cents"] == 100_000

    def test_hsa_catch_up_age_55_exact_on_dec31(
        self, api, plan_admin_headers,
    ):
        """PRD §3.2: "the account holder's age ... is at least 55".

        Claim (boundary): birth 1970-12-31 -> on 2025-12-31T23:59:59Z
        the age comparison by month/day yields exactly 55 ->
        catch_up_cap_cents == 100_000.
        """
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        holder = create_account_holder(birth_date="1970-12-31")
        acct = open_account(
            holder, account_type="HSA", coverage_tier="SELF_ONLY",
            year_end_policy="NONE",
            account_holder_birth_date="1970-12-31",
        )
        resp = api.create_plan_year(
            acct["id"], {"calendar_year": 2025}, plan_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["catch_up_cap_cents"] == 100_000

    def test_hsa_catch_up_age_54_no_catchup(
        self, api, plan_admin_headers,
    ):
        """PRD §3.2: "the account holder's age ... is at least 55;
        otherwise it is 0."

        Claim (boundary): birth 1971-01-01 -> on 2025-12-31 age is 54
        (will not turn 55 until 2026-01-01) -> catch_up_cap_cents == 0.
        """
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        holder = create_account_holder(birth_date="1971-01-01")
        acct = open_account(
            holder, account_type="HSA", coverage_tier="SELF_ONLY",
            year_end_policy="NONE",
            account_holder_birth_date="1971-01-01",
        )
        resp = api.create_plan_year(
            acct["id"], {"calendar_year": 2025}, plan_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["catch_up_cap_cents"] == 0

    def test_health_fsa_cap_320000(self, api, plan_admin_headers):
        """PRD §3.2: "For a Health FSA, contribution_cap_cents is set
        to 320,000 cents ($3,200.00), and catch_up_cap_cents is 0."

        Claim: HEALTH_FSA cap == 320_000, catch_up == 0.
        """
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        holder = create_account_holder(birth_date="1980-01-01")
        acct = open_account(
            holder, account_type="HEALTH_FSA", coverage_tier=None,
            year_end_policy="NONE",
            account_holder_birth_date="1980-01-01",
        )
        resp = api.create_plan_year(
            acct["id"], {"calendar_year": 2025}, plan_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["contribution_cap_cents"] == 320_000
        assert data["catch_up_cap_cents"] == 0

    def test_dcfsa_married_separate_cap_250000(
        self, api, plan_admin_headers,
    ):
        """PRD §3.2: "For a Dependent Care FSA,
        contribution_cap_cents is set to 250,000 cents ($2,500.00)
        when the linked account holder's tax_filing_status is
        MARRIED_SEPARATE, and 500,000 cents ($5,000.00) for every
        other filing status."

        Claim: DCFSA + MARRIED_SEPARATE -> cap 250_000.
        """
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        holder = create_account_holder(
            birth_date="1980-01-01",
            tax_filing_status="MARRIED_SEPARATE",
        )
        acct = open_account(
            holder, account_type="DEPENDENT_CARE_FSA", coverage_tier=None,
            year_end_policy="NONE",
            account_holder_birth_date="1980-01-01",
        )
        resp = api.create_plan_year(
            acct["id"], {"calendar_year": 2025}, plan_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["contribution_cap_cents"] == 250_000
        assert data["catch_up_cap_cents"] == 0

    @pytest.mark.parametrize(
        "filing_status",
        ["SINGLE", "MARRIED_JOINT", "HEAD_OF_HOUSEHOLD"],
    )
    def test_dcfsa_non_married_separate_cap_500000(
        self, api, plan_admin_headers, filing_status,
    ):
        """PRD §3.2: "For a Dependent Care FSA,
        contribution_cap_cents is set to ... 500,000 cents ($5,000.00)
        for every other filing status."

        Claim: DCFSA + non-MARRIED_SEPARATE -> cap 500_000.
        """
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        holder = create_account_holder(
            birth_date="1980-01-01",
            tax_filing_status=filing_status,
        )
        acct = open_account(
            holder, account_type="DEPENDENT_CARE_FSA", coverage_tier=None,
            year_end_policy="NONE",
            account_holder_birth_date="1980-01-01",
        )
        resp = api.create_plan_year(
            acct["id"], {"calendar_year": 2025}, plan_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["contribution_cap_cents"] == 500_000


# ===========================================================================
# Uniqueness — PRD §3.2
# ===========================================================================
class TestPlanYearUniqueness:

    def test_duplicate_calendar_year_rejected(
        self, api, plan_admin_headers,
    ):
        """PRD §3.2: "The pair (account_id, calendar_year) is unique
        per account; an attempt to open a duplicate plan year returns
        ERR_DUPLICATE_PLAN_YEAR."

        Claim: opening the same calendar_year twice ->
        ERR_DUPLICATE_PLAN_YEAR.
        """
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        _, acct = setup_holder_and_account()
        open_plan_year(acct["id"], calendar_year=2025)
        resp = api.create_plan_year(
            acct["id"], {"calendar_year": 2025}, plan_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PLAN_YEAR.value)

    def test_adjacent_calendar_years_allowed(
        self, api, plan_admin_headers,
    ):
        """PRD §3.2: "The pair (account_id, calendar_year) is unique
        per account".

        Claim: distinct adjacent calendar_year values 2025 + 2026 on
        the same account both succeed.
        """
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        _, acct = setup_holder_and_account()
        py1 = open_plan_year(acct["id"], calendar_year=2025)
        py2 = open_plan_year(acct["id"], calendar_year=2026)
        assert py1["calendar_year"] == 2025
        assert py2["calendar_year"] == 2026
        assert py1["id"] != py2["id"]


# ===========================================================================
# Initial PlanYear shape — PRD §3.2
# ===========================================================================
class TestPlanYearInitialShape:

    def test_active_with_zero_counters(self, api, plan_admin_headers):
        """PRD §3.2: "The plan year's denormalized counters —
        contributions_ytd_cents, claims_paid_ytd_cents,
        provisional_balance_cents, carryover_consumed_cents,
        forfeited_cents, and grace_period_end_date — all start at 0
        or null".

        Claim: a freshly created PlanYear has all counters at 0 and
        grace_period_end_date null.
        """
        _, _, py = setup_active_plan_year(calendar_year=2025)
        assert py["status"] == "ACTIVE"
        assert py["contributions_ytd_cents"] == 0
        assert py["claims_paid_ytd_cents"] == 0
        assert py["carryover_in_cents"] == 0
        assert py["carryover_consumed_cents"] == 0
        assert py["forfeited_cents"] == 0
        assert py.get("grace_period_end_date") is None
