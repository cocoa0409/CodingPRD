"""Difficulty: combinatorial formula — the GA composite's pinned rounding order
(PRD §3.6)."""
import pytest

from test_helpers import (
    lab_sample_payload,
    setup_batch_in_state,
    validate_success,
)

# Sample readings whose pinned rounding order decides the outcome (PRD §3.6).
SAMPLES = [
    ("FIRST", 38.236),
    ("MIDDLE", 22.379),
    ("COMPOSITE", 22.345),
]


def _build_batch_with_samples(api, quality_analyst_headers):
    ctx = setup_batch_in_state("COMPLETED", planned_kg=1000.0, line_id="LINE-A")
    batch_id = ctx["batch"]["id"]
    for position, protein in SAMPLES:
        validate_success(
            api.create_lab_sample(
                batch_id,
                lab_sample_payload(
                    sample_type=position,
                    measured_protein_pct=protein,
                    measured_fat_pct=12.0,
                    measured_fiber_pct=2.0,
                    measured_moisture_pct=9.0,
                ),
                quality_analyst_headers,
            ),
            expected_status=201,
        )
    return ctx, batch_id


class TestGaCompositeRoundingOrderPinned:
    def test_composite_protein_uses_pinned_rounding_order(self, api, quality_analyst_headers):
        """PRD §3.6: "The rounding order is pinned and load-bearing: first, each
        sample's weighted contribution — its measured value multiplied by its
        weight — is rounded half up to 3 decimal places; then the rounded
        contributions are summed; then the sum is divided by the unrounded sum of
        the weights; finally the quotient is rounded half up to 2 decimal places.
        Reordering those steps changes answers — samples reading 38.236, 22.379,
        and a composite at 22.345 produce 27.24 under the pinned order but 27.25
        when unrounded contributions are summed first."
        PRD §3.6: "Spot samples (`FIRST`, `MIDDLE`, `LAST`) each carry weight 1;
        a `COMPOSITE` sample carries weight 1.25."

        Design: Difficulty/combinatorial_formula/ga_composite_rounding_order_pinned
        """
        _ctx, batch_id = _build_batch_with_samples(api, quality_analyst_headers)
        report = validate_success(api.create_ga_report(batch_id, quality_analyst_headers), 201)
        assert report["composite_protein_pct"] == pytest.approx(27.24, abs=0.001), (
            "Pinned order must yield 27.24 (27.25 would mean unrounded "
            "contributions were summed first)"
        )

    def test_other_composites_and_label_compliance(self, api, quality_analyst_headers):
        """PRD §3.6: "Spot samples (`FIRST`, `MIDDLE`, `LAST`) each carry weight
        1; a `COMPOSITE` sample carries weight 1.25."
        PRD §3.6: "The report's `label_compliance` — default `PENDING` — resolves
        to `MISBRANDED` when the deviation index is greater than zero, and to
        `COMPLIANT` when it is exactly zero."

        Design: Difficulty/combinatorial_formula/ga_composite_rounding_order_pinned
        """
        # Label guarantees of the fixture's profile: protein >= 26.0, fat >= 9.0,
        # fiber <= 3.0, moisture <= 10.0; composites 27.24 / 12.0 / 2.0 / 9.0 all
        # satisfy them, so the deviation index is 0 and the report is COMPLIANT.
        _ctx, batch_id = _build_batch_with_samples(api, quality_analyst_headers)
        report = validate_success(api.create_ga_report(batch_id, quality_analyst_headers), 201)
        assert report["composite_fat_pct"] == pytest.approx(12.0, abs=0.005)
        assert report["composite_fiber_pct"] == pytest.approx(2.0, abs=0.005)
        assert report["composite_moisture_pct"] == pytest.approx(9.0, abs=0.005)
        assert report["deviation_index"] == pytest.approx(0.0, abs=0.005)
        assert report["label_compliance"] == "COMPLIANT"
