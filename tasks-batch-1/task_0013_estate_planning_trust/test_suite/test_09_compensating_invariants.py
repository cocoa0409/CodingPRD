"""Compensating-action invariants across different conserved quantities.

Revoking a primary designation auto-activates contingent children
(share_basis_points conservation); liquidating an asset decreases gross
by the asset's exact appraised_value_cents (gross conservation).
"""
import pytest

from test_helpers import (
    validate_success,
    bootstrap_estate_with_contingent_designation_chain,
    bootstrap_estate_in_alive_with_two_assets,
    make_planner_headers,
    make_executor_headers,
)


class TestRevokePrimaryActivatesContingent:
    """PRD §3.1: revoking ACTIVE primary auto-promotes DRAFT contingent
    children to ACTIVE; this preserves the cumulative ACTIVE share total."""

    def test_revoke_primary_cascades_contingent_to_active(self, api):
        """PRD §3.1: "On a successful revocation, every designation on the
        same estate whose contingent_of_designation_id points at the
        just-revoked row and whose current status is DRAFT is automatically
        promoted to ACTIVE, so the contingent backup takes effect immediately"

        Design: Difficulty/compensating_invariant/revoke_primary_activates_contingent_share_total_preserved
        """
        ctx = bootstrap_estate_with_contingent_designation_chain(
            spouse_bp=4000, primary_bp=6000, contingent_bp=6000,
        )
        est = ctx["estate"]
        primary = ctx["primary"]
        contingent = ctx["contingent"]
        # Revoke primary; OCC token = current version.
        resp = api.revoke_beneficiary_designation(
            primary["id"], expected_estate_version=est["version"],
            headers=make_planner_headers(),
        )
        d_revoked = validate_success(resp, expected_status=200)
        assert d_revoked["status"] == "REVOKED"
        # Contingent child should now be ACTIVE.
        get_resp = api.get_beneficiary_designation(
            contingent["id"], make_planner_headers(),
        )
        d_cont = validate_success(get_resp, expected_status=200)
        assert d_cont["status"] == "ACTIVE", (
            f"Contingent child should auto-promote DRAFT->ACTIVE, "
            f"got {d_cont['status']!r}"
        )

    def test_active_share_total_preserved_after_cascade(self, api):
        """PRD §3.1: "On a successful revocation, every designation on the
        same estate whose contingent_of_designation_id points at the
        just-revoked row and whose current status is DRAFT is automatically
        promoted to ACTIVE, so the contingent backup takes effect immediately"

        Design: Difficulty/compensating_invariant/revoke_primary_activates_contingent_share_total_preserved
        """
        ctx = bootstrap_estate_with_contingent_designation_chain(
            spouse_bp=4000, primary_bp=6000, contingent_bp=6000,
        )
        est = ctx["estate"]
        # Pre-action: ACTIVE total = spouse(4000) + primary(6000) = 10000.
        api.revoke_beneficiary_designation(
            ctx["primary"]["id"],
            expected_estate_version=est["version"],
            headers=make_planner_headers(),
        )
        # Verify ACTIVE total: spouse(4000) + contingent(6000) = 10000.
        spouse = validate_success(
            api.get_beneficiary_designation(
                ctx["spouse"]["id"], make_planner_headers(),
            ),
            expected_status=200,
        )
        contingent = validate_success(
            api.get_beneficiary_designation(
                ctx["contingent"]["id"], make_planner_headers(),
            ),
            expected_status=200,
        )
        assert spouse["status"] == "ACTIVE"
        assert contingent["status"] == "ACTIVE"
        assert spouse["share_basis_points"] + contingent["share_basis_points"] == 10000, (
            f"Active share total after revoke+cascade should be 10000, got "
            f"{spouse['share_basis_points'] + contingent['share_basis_points']}"
        )


class TestLiquidateAssetDecreasesGrossExact:
    """PRD §3.6 / §3.1: liquidating an INCLUDED asset moves it to LIQUIDATED
    and recomputes gross excluding that asset."""

    def test_liquidate_drops_gross_by_exact_asset_value(self, api):
        """PRD §2.7: "All monetary amounts in this domain are integer cents
        — there is no floating-point currency, no internal rounding, and no
        fractional dollars."
        PRD §4 (endpoint row): "POST /assets/{id}/liquidate ... Sell an
        asset (INCLUDED to LIQUIDATED); recomputes gross."

        Design: Difficulty/compensating_invariant/liquidate_asset_decreases_gross_by_exact_appraised_value
        """
        ctx = bootstrap_estate_in_alive_with_two_assets(
            real_estate_value_cents=500000,
            bank_value_cents=300000,
        )
        # Pre: gross = 500_000 + 300_000 = 800_000.
        est_id = ctx["estate"]["id"]
        exec_id = ctx["executor"]["id"]
        est_pre = validate_success(
            api.get_estate(est_id, make_planner_headers()),
            expected_status=200,
        )
        assert est_pre["gross_estate_value_cents"] == 800000

        # Liquidate the 300_000 bank asset.
        api.liquidate_asset(
            ctx["bank_asset"]["id"], make_executor_headers(exec_id),
        )

        est_post = validate_success(
            api.get_estate(est_id, make_planner_headers()),
            expected_status=200,
        )
        assert est_post["gross_estate_value_cents"] == 500000, (
            f"Gross should decrease by exact appraised value (300_000), "
            f"got post={est_post['gross_estate_value_cents']}"
        )

    def test_liquidate_asset_transitions_to_liquidated(self, api):
        """PRD §4 (endpoint row): "POST /assets/{id}/liquidate ... Sell an
        asset (INCLUDED to LIQUIDATED); recomputes gross."

        Design: Difficulty/compensating_invariant/liquidate_asset_decreases_gross_by_exact_appraised_value
        """
        ctx = bootstrap_estate_in_alive_with_two_assets()
        resp = api.liquidate_asset(
            ctx["bank_asset"]["id"],
            make_executor_headers(ctx["executor"]["id"]),
        )
        d = validate_success(resp, expected_status=200)
        assert d["status"] == "LIQUIDATED", (
            f"Asset should transition INCLUDED->LIQUIDATED on liquidate, "
            f"got {d['status']!r}"
        )
