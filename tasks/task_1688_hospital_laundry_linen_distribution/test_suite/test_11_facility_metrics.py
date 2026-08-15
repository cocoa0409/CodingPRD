"""Cost per adjusted patient day: posted (SETTLED only) vs accrual (all
invoices) bases (PRD 3.9)."""
import pytest
from test_helpers import (
    LM,
    api_client,
    collect_soiled,
    create_invoice,
    finalize_invoice,
    make_manifest,
    reconcile_manifest,
    return_manifest,
    setup_unit_with_collection,
    validate_success,
)


def _setup_two_invoice_facility():
    """Cycle 1 settles at 560 cents over 50 patient days; cycle 2 finalizes
    at 800 over 100 patient days and stays open."""
    ctx = setup_unit_with_collection(soiled_pieces=8)
    manifest1 = make_manifest(ctx, [ctx["collect_run"]["id"]], 16.00)
    manifest1 = return_manifest(
        manifest1["id"],
        [{"stock_id": ctx["stock"]["id"], "pieces": 7, "condemned_pieces": 0}],
    )
    reconcile_manifest(manifest1["id"])
    invoice1 = create_invoice(
        ctx["facility"]["id"], [manifest1["id"]],
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-07T00:00:00Z",
        period_adjusted_patient_days=50,
    )
    finalize_invoice(invoice1["id"])
    validate_success(api_client.settle_invoice(invoice1["id"], LM), 200)

    collect2 = collect_soiled(
        ctx,
        [{"stock_id": ctx["stock"]["id"], "pieces": 10}],
        start="2026-08-03T08:00:00Z",
        end="2026-08-03T09:00:00Z",
    )
    manifest2 = make_manifest(ctx, [collect2["id"]], 20.00)
    manifest2 = return_manifest(
        manifest2["id"],
        [{"stock_id": ctx["stock"]["id"], "pieces": 10, "condemned_pieces": 0}],
    )
    reconcile_manifest(manifest2["id"])
    invoice2 = create_invoice(
        ctx["facility"]["id"], [manifest2["id"]],
        period_start="2026-08-08T00:00:00Z",
        period_end="2026-08-14T00:00:00Z",
        period_adjusted_patient_days=100,
    )
    finalize_invoice(invoice2["id"])
    ctx.update({"invoice1": invoice1, "invoice2": invoice2})
    return ctx


class TestPostedVsAccrual:
    def test_posted_basis_counts_settled_only(self, api, linen_manager_headers):
        """PRD 3.9: "The posted basis is cash-basis: the sum of
        `billed_total_cents` over the facility's `SETTLED` invoices divided by
        the sum of `period_adjusted_patient_days` over those same invoices,
        rounded half up to two decimal places, returned as
        `cost_per_apd_posted_cents`."
        PRD 3.9: "The response also carries `posted_invoice_count`, the number
        of `SETTLED` invoices feeding the posted figure, and
        `accrual_invoice_count`, the number of invoices of all statuses
        feeding the accrual figure."

        Design: Difficulty/dual_variant_calc/facility_cost_per_apd_posted_vs_accrual
        """
        ctx = _setup_two_invoice_facility()
        metrics = validate_success(
            api.get_facility_metrics(ctx["facility"]["id"], linen_manager_headers),
            200,
        )
        # SETTLED only: 560 / 50 = 11.20.
        assert metrics["cost_per_apd_posted_cents"] == pytest.approx(11.20, abs=0.001)
        assert metrics["posted_invoice_count"] == 1

    def test_accrual_basis_includes_open_invoices(self, api, linen_manager_headers):
        """PRD 3.9: "The accrual basis includes open invoices: the sum of
        `billed_total_cents` over `FINALIZED`, `DISPUTED`, and `SETTLED`
        invoices plus the sum of `provisional_total_cents` over `PROVISIONAL`
        invoices, divided by the sum of `period_adjusted_patient_days` over
        all of the facility's invoices, rounded half up to two decimal places,
        returned as `cost_per_apd_accrual_cents`."
        PRD 3.9: "The two bases diverge for identical data whenever open
        invoices exist, and the accrual figure is the one that moves as
        provisional bills are created."

        Design: Difficulty/dual_variant_calc/facility_cost_per_apd_posted_vs_accrual
        """
        ctx = _setup_two_invoice_facility()
        metrics = validate_success(
            api.get_facility_metrics(ctx["facility"]["id"], linen_manager_headers),
            200,
        )
        # (560 + 800) / (50 + 100) = 1360/150 = 9.0666... -> 9.07.
        assert metrics["cost_per_apd_accrual_cents"] == pytest.approx(9.07, abs=0.001)
        assert metrics["accrual_invoice_count"] == 2
        assert metrics["cost_per_apd_accrual_cents"] != pytest.approx(
            metrics["cost_per_apd_posted_cents"]
        )
