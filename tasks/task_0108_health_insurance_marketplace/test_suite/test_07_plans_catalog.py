"""Insurer / Plan / PlanVariant catalog. Includes benchmark conflict,
ownership, optimistic concurrency, catalog version bump.

PRD §3.5, §2.6, §2.8.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    assert_insurer,
    assert_plan,
    assert_plan_variant,
    create_insurer,
    create_insurer_payload,
    create_plan,
    create_plan_payload,
    create_plan_variant,
    create_plan_variant_payload,
    make_insurer_headers,
    patch_plan_payload,
    setup_benchmark_silver_catalog,
    validate_error,
    validate_success,
)


# ===========================================================================
# Insurer CRUD
# ===========================================================================
class TestInsurer:
    """PRD §3.5: "An Insurer row is created with a name, a list of
    two-letter state codes in filing_states where the issuer offers
    products, and a contact_phone."""

    def test_create_insurer_returns_append_only_shape(self, api):
        """PRD §2.4: "Append-only resources — IncomeRecord, Insurer,
        PlanVariant, PremiumInvoice — carry only id and created_at."
        """
        ins = create_insurer(filing_states=["CA", "NY"])
        assert_insurer(ins)
        assert ins["filing_states"] == ["CA", "NY"]
        assert "updated_at" not in ins or ins.get("updated_at") is None
        assert "version" not in ins or ins.get("version") is None


# ===========================================================================
# Plan creation and benchmark uniqueness
# ===========================================================================
class TestPlanCreate:
    """PRD §3.5: Plan creation with insurer_id, coverage_year,
    filing_state, tier, base_monthly_premium_cents,
    optional is_benchmark_silver."""

    def test_create_plan_returns_active_catalog_v1(self, api):
        """PRD §3.5: "A plan's lifecycle status is ACTIVE by default ...
        Each plan also carries a catalog_version integer that increments
        every time base_monthly_premium_cents or status changes".

        Claim: a new Plan returns status=ACTIVE and catalog_version=1.
        """
        ins = create_insurer(filing_states=["CA"])
        plan = create_plan(
            insurer=ins, filing_state="CA", coverage_year=2026,
            tier="SILVER", base_monthly_premium_cents=40_000,
        )
        assert_plan(plan)
        assert plan["status"] == "ACTIVE"
        assert plan["catalog_version"] == 1
        assert plan["is_benchmark_silver"] is False


class TestBenchmarkSilverConflict:
    """PRD §3.5: "The flag may be set true on at most one plan per
    (filing_state, coverage_year) combination; an attempt to set it
    true while another active plan already holds it is rejected with
    ERR_BENCHMARK_CONFLICT."""

    def test_second_benchmark_in_same_state_year_rejected(self, api):
        """PRD §3.5: ERR_BENCHMARK_CONFLICT on conflicting flag."""
        ins = create_insurer(filing_states=["CA"])
        # First benchmark Silver — accepted.
        create_plan(
            insurer=ins, filing_state="CA", coverage_year=2026,
            tier="SILVER", base_monthly_premium_cents=40_000,
            is_benchmark_silver=True,
        )
        # Second benchmark Silver in same (CA, 2026) — rejected.
        res = api.create_plan(
            create_plan_payload(
                insurer_id=ins["id"], filing_state="CA",
                coverage_year=2026, tier="SILVER",
                base_monthly_premium_cents=50_000,
                is_benchmark_silver=True,
            ),
            make_insurer_headers(ins["id"]),
        )
        validate_error(res, "ERR_BENCHMARK_CONFLICT")

    def test_benchmark_silver_allowed_in_different_year(self, api):
        """PRD §3.5: benchmark uniqueness is scoped to
        (filing_state, coverage_year). Different coverage_year is OK.
        """
        ins = create_insurer(filing_states=["CA"])
        create_plan(
            insurer=ins, filing_state="CA", coverage_year=2025,
            tier="SILVER", base_monthly_premium_cents=40_000,
            is_benchmark_silver=True,
        )
        # 2026 benchmark should succeed despite 2025 benchmark existing.
        res = api.create_plan(
            create_plan_payload(
                insurer_id=ins["id"], filing_state="CA",
                coverage_year=2026, tier="SILVER",
                base_monthly_premium_cents=42_000,
                is_benchmark_silver=True,
            ),
            make_insurer_headers(ins["id"]),
        )
        validate_success(res, 201)


# ===========================================================================
# PATCH /plans/{id} + version bump
# ===========================================================================
class TestPatchPlanCatalogVersion:
    """PRD §3.5: "catalog_version integer that increments every time
    base_monthly_premium_cents or status changes"."""

    def test_patch_premium_increments_catalog_version(self, api):
        """PRD §3.5: "catalog_version increments every time
        base_monthly_premium_cents or status changes".

        Claim: PATCH that mutates base_monthly_premium_cents bumps
        catalog_version by 1.
        """
        ins = create_insurer(filing_states=["CA"])
        plan = create_plan(
            insurer=ins, filing_state="CA", coverage_year=2026,
            tier="SILVER", base_monthly_premium_cents=40_000,
        )
        old_cv = plan["catalog_version"]
        res = api.patch_plan(
            plan["id"],
            patch_plan_payload(base_monthly_premium_cents=42_000),
            make_insurer_headers(ins["id"]),
        )
        updated = validate_success(res, 200)
        assert updated["catalog_version"] == old_cv + 1
        assert updated["base_monthly_premium_cents"] == 42_000

    def test_patch_with_stale_version_rejected(self, api):
        """PRD §2.6: "When the caller supplies version, the server
        compares it to the stored version of the resource; if they
        differ, the request is rejected with ERR_STALE_VERSION and no
        mutation is applied."
        """
        ins = create_insurer(filing_states=["CA"])
        plan = create_plan(
            insurer=ins, filing_state="CA", coverage_year=2026,
            tier="SILVER", base_monthly_premium_cents=40_000,
        )
        # First update bumps version to 2.
        api.patch_plan(
            plan["id"],
            patch_plan_payload(base_monthly_premium_cents=42_000,
                               version=plan["version"]),
            make_insurer_headers(ins["id"]),
        )
        # Second update with the now-stale version=1 must be rejected.
        res = api.patch_plan(
            plan["id"],
            patch_plan_payload(base_monthly_premium_cents=45_000,
                               version=plan["version"]),
            make_insurer_headers(ins["id"]),
        )
        validate_error(res, "ERR_STALE_VERSION")


# ===========================================================================
# PlanVariant
# ===========================================================================
class TestPlanVariant:
    """PRD §3.5: "A PlanVariant is the CSR overlay attached to a Silver-
    tier plan via plan_id; only Silver plans may carry variants."""

    def test_create_csr_variant_returns_append_only_shape(self, api):
        """PRD §2.4: PlanVariant is append-only — id + created_at only.
        """
        ins, plan, _v = setup_benchmark_silver_catalog(
            filing_state="CA", include_standard_variant=False,
        )
        variant = create_plan_variant(
            plan=plan, csr_level="CSR_94", actuarial_value=94.0,
            out_of_pocket_max_cents=500_000, insurer=ins,
        )
        assert_plan_variant(variant)
        assert variant["csr_level"] == "CSR_94"
        # PRD §2.4: append-only — no version/updated_at.
        assert variant.get("version") is None
        assert variant.get("updated_at") is None
