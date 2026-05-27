"""Corner-design coverage for calculations section: input set filtering,
precision (floor at zero).
"""
import pytest

from test_helpers import (
    validate_success,
    set_clock,
    create_decedent,
    create_estate,
    create_asset,
    bootstrap_estate_in_administration,
    create_creditor_claim,
    allow_creditor_claim,
    make_planner_headers,
    make_executor_headers,
)


class TestGrossInputSetFiltering:
    def test_gross_excludes_draft_assets_before_finalize(self, api):
        """PRD §3.1: "the gross-estate value is recomputed as the sum of
        appraised_value_cents across every asset whose status is INCLUDED,
        iterated by created_at ascending for stability"

        Design: Corner/calculations/gross_excludes_draft_assets_before_finalize
        """
        set_clock("2026-01-01T00:00:00Z")
        dec = create_decedent(
            full_legal_name="Eli E",
            domicile_state_code="CA", ssn_last4="0008",
        )
        estate = create_estate(dec["id"])
        # Assets created in DRAFT (no finalize yet).
        create_asset(estate["id"], "BANK_ACCOUNT", "A1", 200000)
        create_asset(estate["id"], "BANK_ACCOUNT", "A2", 300000)
        resp = api.get_estate(estate["id"], make_planner_headers())
        data = validate_success(resp, expected_status=200)
        assert data["gross_estate_value_cents"] == 0, (
            f"DRAFT assets should not contribute to gross; expected 0, got "
            f"{data['gross_estate_value_cents']}"
        )


class TestNetTaxableFloorsAtZero:
    def test_net_taxable_floors_at_zero_when_claims_exceed_gross(self, api):
        """PRD §2.7: "The net taxable estate calculation is floored at zero
        by taking the maximum of zero and the would-be negative result, so
        an estate whose allowed claims exceed its gross can never present a
        negative net_taxable_estate_cents."

        Design: Corner/calculations/net_taxable_floors_at_zero
        """
        ctx = bootstrap_estate_in_administration(
            clock="2026-01-01T00:00:00Z",
            date_of_death="2026-01-15T00:00:00Z",
            asset_value_cents=100000,
            domicile_state_code="NY",
        )
        # File and allow a claim larger than gross.
        claim = create_creditor_claim(
            ctx["estate"]["id"],
            creditor_name="BigDebt",
            amount_cents=500000,
            claim_class="UNSECURED",
            filed_at="2026-02-01T00:00:00Z",
        )
        allow_creditor_claim(claim["id"], ctx["executor"]["id"])
        resp = api.get_net_taxable_summary(
            ctx["estate"]["id"], make_executor_headers(ctx["executor"]["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["net_taxable_estate_cents"] == 0, (
            f"net_taxable must floor at zero; got "
            f"{data['net_taxable_estate_cents']}"
        )
