"""Dual-variant calculations across different entity domains.

Tests covering net_taxable_estate's provisional/final variant switch and
the creditor-payment waterfall's priority/pro-rata variant switch.
"""
import pytest

from test_helpers import (
    validate_success,
    bootstrap_probate_open_with_assets,
    bootstrap_administration_with_assets_and_claim,
    bootstrap_administration_with_n_claims,
    create_probate_order,
    enter_probate_order,
    make_executor_headers,
)


class TestNetTaxableEstateVariants:
    """PRD §3.9: same Estate, same Assets, same CreditorClaims → two
    different net_taxable_estate_cents values depending on Estate.status."""

    def test_provisional_variant_uses_live_gross(self, api):
        """PRD §3.9: "While the estate is in DECEASED, PROBATE_PENDING, or
        PROBATE_OPEN, the provisional variant is in effect: the calculation
        uses the live gross_estate_value_cents, so any subsequent update to
        an INCLUDED asset's appraised_value_cents flows immediately into the
        provisional net taxable estate."

        PRD §3.6 forbids creditor-claim allowance while the estate is in
        PROBATE_OPEN (allowance is only permitted during ADMINISTRATION), so
        the provisional snapshot is observed without any allowed claim — the
        test demonstrates the LIVE-gross behavior by PATCHing the asset and
        re-reading the summary.

        Design: Difficulty/dual_variant_calc/net_taxable_estate_provisional_vs_final
        """
        ctx = bootstrap_probate_open_with_assets(
            clock="2026-03-01T00:00:00Z",
            date_of_death="2026-02-15T00:00:00Z",
            asset_value_cents=5000000,
            asset_category="REAL_ESTATE",
            domicile_state_code="CA",
        )
        exec_id = ctx["executor"]["id"]
        resp = api.get_net_taxable_summary(
            ctx["estate"]["id"], make_executor_headers(exec_id),
        )
        data = validate_success(resp, expected_status=200)
        assert data["variant"] == "provisional", (
            f"Expected provisional while in PROBATE_OPEN, got {data['variant']!r}"
        )
        # gross_used = live gross = 5_000_000; exempt = 0 (no IRA);
        # allowed claims = 0 (PRD §3.6 forbids allowance in PROBATE_OPEN)
        # → net = 5_000_000.
        assert data["net_taxable_estate_cents"] == 5000000, (
            f"Provisional net should be 5_000_000, got {data['net_taxable_estate_cents']}"
        )
        # PATCH the asset appraisal upward; the live gross must immediately
        # flow into the provisional calculation.
        home_id = ctx["asset"]["id"]
        api.patch_asset(
            home_id, {"appraised_value_cents": 8000000},
            make_executor_headers(exec_id),
        )
        resp2 = api.get_net_taxable_summary(
            ctx["estate"]["id"], make_executor_headers(exec_id),
        )
        data2 = validate_success(resp2, expected_status=200)
        assert data2["variant"] == "provisional", (
            f"Still provisional after PATCH while in PROBATE_OPEN, "
            f"got {data2['variant']!r}"
        )
        assert data2["net_taxable_estate_cents"] == 8000000, (
            f"Provisional net should track live gross (8_000_000), "
            f"got {data2['net_taxable_estate_cents']}"
        )

    def test_final_variant_freezes_inventory_snapshot(self, api):
        """PRD §3.9: "Once the inventory-approval order from the court enters
        and the estate advances into ADMINISTRATION (and from then on into
        CLOSED), the final variant takes over: the calculation now uses the
        frozen inventory_snapshot_gross_cents instead of the live gross, so
        any subsequent asset re-appraisal does not re-enter the net-taxable
        computation."

        Design: Difficulty/dual_variant_calc/net_taxable_estate_provisional_vs_final
        """
        # Fixture now advances to ADMINISTRATION (so claim allowance is
        # permitted per PRD §3.6) and the inventory snapshot is frozen.
        ctx = bootstrap_administration_with_assets_and_claim(
            clock="2026-03-01T00:00:00Z",
            date_of_death="2026-02-15T00:00:00Z",
            asset_value_cents=5000000,
            asset_category="REAL_ESTATE",
            claim_amount_cents=100000,
            claim_filed_at="2026-04-01T00:00:00Z",
            claim_clock_advance="2026-04-01T00:00:00Z",
            domicile_state_code="CA",
        )
        # Now bump the asset appraisal upwards — should NOT re-enter final.
        exec_id = ctx["executor"]["id"]
        home_id = ctx["asset"]["id"]
        api.patch_asset(
            home_id, {"appraised_value_cents": 8000000},
            make_executor_headers(exec_id),
        )
        resp = api.get_net_taxable_summary(
            ctx["estate"]["id"], make_executor_headers(exec_id),
        )
        data = validate_success(resp, expected_status=200)
        assert data["variant"] == "final", (
            f"Expected final under ADMINISTRATION, got {data['variant']!r}"
        )
        # gross_used = frozen snapshot = 5_000_000; the PATCH to 8_000_000
        # does NOT re-enter the final variant.
        # exempt = 0; allowed claims = 100_000 → net = 4_900_000.
        # A non-frozen reading would have produced 8_000_000 - 100_000 =
        # 7_900_000, so the assertion below alone is a strict witness that
        # the final variant uses the frozen inventory snapshot rather than
        # the live gross.
        assert data["net_taxable_estate_cents"] == 4900000, (
            f"Final net should be 4_900_000 (using frozen snapshot), "
            f"got {data['net_taxable_estate_cents']}"
        )


class TestCreditorWaterfallPriorityVariant:
    """PRD §3.6: priority-full-pay variant under the default ADMINISTRATION
    state (no DRAFT CLOSE_ESTATE order). Earliest-created in each class is
    paid in full; the marginal claim takes the residual; later siblings get
    zero."""

    def test_priority_full_pay_marginal_residual(self, api):
        """PRD §3.6: "while the estate is in ADMINISTRATION and no
        CLOSE_ESTATE order has yet been drafted, claims are paid in the order
        described — the marginal claim within an under-funded class gets
        whatever residual remains and later siblings within the same class
        get zero."

        Design: Difficulty/dual_variant_calc/creditor_waterfall_pro_rata_vs_priority
        """
        ctx = bootstrap_administration_with_n_claims(
            claim_specs=[
                {"creditor_name": "ClaimA", "amount_cents": 700000,
                 "claim_class": "SECURED", "filed_at": "2026-02-01T00:00:00Z"},
                {"creditor_name": "ClaimB", "amount_cents": 700000,
                 "claim_class": "SECURED", "filed_at": "2026-02-02T00:00:00Z"},
            ],
            gross_asset_value_cents=1000000,
            domicile_state_code="NY",
        )
        exec_id = ctx["executor"]["id"]
        claim_a, claim_b = ctx["claims"]
        # Pay claim A first → should be paid 700000 in full.
        resp_a = api.pay_creditor_claim(claim_a["id"], make_executor_headers(exec_id))
        data_a = validate_success(resp_a, expected_status=200)
        assert data_a["status"] == "PAID"
        assert data_a["paid_amount_cents"] == 700000, (
            f"Earliest-created SECURED claim should get full 700000, "
            f"got {data_a['paid_amount_cents']}"
        )
        # Pay claim B next → only 300000 residual remains.
        resp_b = api.pay_creditor_claim(claim_b["id"], make_executor_headers(exec_id))
        data_b = validate_success(resp_b, expected_status=200)
        assert data_b["status"] == "PAID"
        assert data_b["paid_amount_cents"] == 300000, (
            f"Marginal SECURED claim should get residual 300000, "
            f"got {data_b['paid_amount_cents']}"
        )

    def test_pro_rata_variant_when_close_estate_in_draft(self, api):
        """PRD §3.6: "while the estate is in ADMINISTRATION and at least one
        CLOSE_ESTATE order is in DRAFT, an under-funded class is paid pro-rata
        across all of its allowed members. In that case each member of the
        short-funded class receives the integer floor of its own amount_cents
        multiplied by the remaining pool divided by the sum of amount_cents
        across all allowed members of that class, and any residual cents left
        over after these floor divisions (i.e., the difference between the
        remaining pool and the sum of the floored shares) are allocated one
        cent at a time in created_at ascending order"

        Design: Difficulty/dual_variant_calc/creditor_waterfall_pro_rata_vs_priority
        """
        ctx = bootstrap_administration_with_n_claims(
            claim_specs=[
                {"creditor_name": "ClaimA", "amount_cents": 700000,
                 "claim_class": "SECURED", "filed_at": "2026-02-01T00:00:00Z"},
                {"creditor_name": "ClaimB", "amount_cents": 700000,
                 "claim_class": "SECURED", "filed_at": "2026-02-02T00:00:00Z"},
            ],
            gross_asset_value_cents=1000000,
            domicile_state_code="NY",
        )
        exec_id = ctx["executor"]["id"]
        # Draft a CLOSE_ESTATE order (do NOT enter it) — triggers pro_rata.
        close_order = create_probate_order(ctx["estate"]["id"], "CLOSE_ESTATE")
        # Don't enter; verify it stays DRAFT.
        assert close_order["status"] == "DRAFT"

        claim_a, claim_b = ctx["claims"]
        # Pay claim A: class-total 1_400_000, pool 1_000_000.
        # floor(700_000 * 1_000_000 / 1_400_000) = 500_000 each.
        # Residual = 1_000_000 - 1_000_000 = 0.
        resp_a = api.pay_creditor_claim(claim_a["id"], make_executor_headers(exec_id))
        data_a = validate_success(resp_a, expected_status=200)
        assert data_a["status"] == "PAID"
        assert data_a["paid_amount_cents"] == 500000, (
            f"Pro-rata: each SECURED claim should get 500_000, "
            f"got {data_a['paid_amount_cents']}"
        )
        resp_b = api.pay_creditor_claim(claim_b["id"], make_executor_headers(exec_id))
        data_b = validate_success(resp_b, expected_status=200)
        assert data_b["status"] == "PAID"
        assert data_b["paid_amount_cents"] == 500000, (
            f"Pro-rata: each SECURED claim should get 500_000, "
            f"got {data_b['paid_amount_cents']}"
        )
