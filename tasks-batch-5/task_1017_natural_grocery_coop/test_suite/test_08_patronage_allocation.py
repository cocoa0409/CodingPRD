"""Patronage allocation: dividend computation (ESTIMATED vs FINAL), retained-equity
cascade, eligibility filtering, declared-rate requirement, and the OCC stale-version
guard on allocation creation."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_fiscal_year, create_active_member, create_draft_allocation,
    create_allocation_payload,
    setup_estimated_allocation_ready, setup_final_allocation_ready,
    TEST_USERS,
)

FINANCE = TEST_USERS["finance_manager_headers"]
COOP = TEST_USERS["coop_admin_headers"]


class TestEstimatedDividendOnMember:
    """ESTIMATED run uses the fiscal year's patronage_rate (PRD §3.7)."""

    def test_member_dividend_uses_estimated_rate(self, api):
        """PRD §3.7: "For each eligible member, the dividend is the rate multiplied by
        that member's `patronage_cents_ytd`, rounded half up to whole cents, and stored
        as the member's `patronage_dividend_cents`." Rate 0.05 x 20000 = 1000.

        Design: Difficulty/dual_variant_calc/dvc_patronage_dividend_estimated_rate_on_member
        """
        ctx = setup_estimated_allocation_ready(patronage_rate=0.05)
        assert ctx["member"]["patronage_cents_ytd"] == 20000
        validate_success(api.finalize_patronage_allocation(ctx["allocation"]["id"], FINANCE), 200)
        member_after = validate_success(api.get_member(ctx["member"]["id"], COOP), 200)
        assert member_after["patronage_dividend_cents"] == 1000

    def test_allocation_totals_recorded_on_finalize(self, api):
        """PRD §3.7: "Across all eligible members the run records `total_dividend_cents`,
        `total_retained_cents`, and `member_count`." PRD §3.7: "Finalizing an allocation
        is a `FinanceManager` action moving it from `DRAFT` to `FINALIZED`."

        Design: Difficulty/dual_variant_calc/dvc_patronage_dividend_estimated_rate_on_member
        """
        ctx = setup_estimated_allocation_ready(patronage_rate=0.05)
        finalized = validate_success(
            api.finalize_patronage_allocation(ctx["allocation"]["id"], FINANCE), 200)
        assert finalized["status"] == "FINALIZED"
        assert finalized["total_dividend_cents"] == 1000


class TestRetentionCreditsEquityThenYear:
    """The retained portion flows to member equity and the fiscal year (PRD §3.7)."""

    def test_member_equity_credited_with_retained_portion(self, api):
        """PRD §3.7: "A retained portion — the dividend multiplied by the retention
        fraction of twenty percent, rounded half up — is then credited back to member
        equity: the member's `equity_paid_in_cents` is increased by the retained amount".
        1000 dividend -> 200 retained; equity 10000 -> 10200.

        Design: Difficulty/transitive_cascade/tc_allocation_finalize_credits_member_equity_then_year
        """
        ctx = setup_estimated_allocation_ready(patronage_rate=0.05)
        validate_success(api.finalize_patronage_allocation(ctx["allocation"]["id"], FINANCE), 200)
        member_after = validate_success(api.get_member(ctx["member"]["id"], COOP), 200)
        assert member_after["equity_paid_in_cents"] == 10200

    def test_fiscal_year_total_equity_credited_and_total_retained_recorded(self, api):
        """PRD §3.7: "and, in the same movement, the allocation's fiscal year's
        `total_equity_cents` is increased by that retained amount, preserving the equity
        invariant."

        Design: Difficulty/transitive_cascade/tc_allocation_finalize_credits_member_equity_then_year
        """
        ctx = setup_estimated_allocation_ready(patronage_rate=0.05)
        finalized = validate_success(
            api.finalize_patronage_allocation(ctx["allocation"]["id"], FINANCE), 200)
        assert finalized["total_retained_cents"] == 200
        fy_after = validate_success(api.get_fiscal_year(ctx["fiscal_year"]["id"], FINANCE), 200)
        assert fy_after["total_equity_cents"] == 10200


def test_final_variant_dividend_on_closed_year(api):
    """PRD §3.7: "The applicable rate is the fiscal year's `patronage_rate` for an
    `ESTIMATED` run and the allocation's `declared_rate` for a `FINAL` run; because
    these rates differ, the same member's patronage produces a different dividend under
    the two methods." Declared 0.08 x 20000 = 1600.

    Design: Corner/calculations/final_variant_dividend_on_closed_year
    """
    ctx = setup_final_allocation_ready(patronage_rate=0.05, declared_rate=0.08)
    finalized = validate_success(
        api.finalize_patronage_allocation(ctx["allocation"]["id"], FINANCE), 200)
    assert finalized["total_dividend_cents"] == 1600
    member_after = validate_success(api.get_member(ctx["member"]["id"], COOP), 200)
    assert member_after["patronage_dividend_cents"] == 1600


def test_member_below_min_patronage_excluded(api):
    """PRD §3.7: "the run identifies its eligible members — those whose
    `membership_status` is `ACTIVE` and whose `patronage_cents_ytd` is at least the
    minimum participation threshold of 5000 cents." A member at 0 is excluded.

    Design: Corner/calculations/dividend_below_min_patronage_excluded
    """
    fy = create_fiscal_year()
    member = create_active_member(full_name="Zero P", email="zero@x.com")
    allocation = create_draft_allocation(fy["id"], method="ESTIMATED")
    finalized = validate_success(
        api.finalize_patronage_allocation(allocation["id"], FINANCE), 200)
    assert finalized["total_dividend_cents"] == 0
    assert finalized["member_count"] == 0
    member_after = validate_success(api.get_member(member["id"], COOP), 200)
    assert member_after["patronage_dividend_cents"] == 0


def test_final_allocation_without_declared_rate_rejected(api):
    """PRD §3.7: "A `FINAL` run also requires a `declared_rate` to be present (else
    `ERR_DECLARED_RATE_REQUIRED`); the field is ignored for an `ESTIMATED` run."

    Design: Corner/validations/final_allocation_declared_rate_required_rejected
    """
    fy = create_fiscal_year()
    api.close_fiscal_year(fy["id"], FINANCE)
    allocation = create_draft_allocation(fy["id"], method="FINAL", declared_rate=None)
    res = api.finalize_patronage_allocation(allocation["id"], FINANCE)
    validate_error(res, "ERR_DECLARED_RATE_REQUIRED", expected_status=422)


def test_finalize_already_finalized_allocation_rejected(api):
    """PRD §3.7: "It requires the allocation to be in `DRAFT` (else
    `ERR_ALLOCATION_NOT_DRAFT`)".

    Design: Corner/state_machines/allocation_finalize_after_finalized_rejected
    """
    fy = create_fiscal_year()
    allocation = create_draft_allocation(fy["id"], method="ESTIMATED")
    validate_success(api.finalize_patronage_allocation(allocation["id"], FINANCE), 200)
    res = api.finalize_patronage_allocation(allocation["id"], FINANCE)
    validate_error(res, "ERR_ALLOCATION_NOT_DRAFT", expected_status=409)


def test_stale_fiscal_year_version_on_second_create_rejected(api):
    """PRD §2.8: "If that value does not match the fiscal year's current `version` —
    because another allocation run has advanced it since the client last read it — the
    create is rejected with `ERR_STALE_FISCAL_YEAR_VERSION` at HTTP status 412".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_fiscal_year_version_rejected
    """
    fy = create_fiscal_year()
    fy_read = validate_success(api.get_fiscal_year(fy["id"], FINANCE), 200)
    v0 = fy_read["version"]
    # First create advances the fiscal year version to v0 + 1.
    validate_success(api.create_patronage_allocation(
        create_allocation_payload(fy["id"], v0, method="ESTIMATED"), FINANCE), 201)
    # Second create still carrying the stale v0 is refused.
    res = api.create_patronage_allocation(
        create_allocation_payload(fy["id"], v0, method="ESTIMATED"), FINANCE)
    validate_error(res, "ERR_STALE_FISCAL_YEAR_VERSION", expected_status=412)
