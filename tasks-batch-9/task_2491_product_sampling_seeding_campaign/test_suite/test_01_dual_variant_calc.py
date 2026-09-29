"""Paired computations whose two variants must diverge on identical inputs."""

import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers import (
    assert_instant,
    campaign_manager_headers,
    fulfillment_ops_headers,
    moderator_a_headers,
)


class TestCostPerSampleVariants:
    """The provisional and final per-sample costs on one shipment set."""

    @staticmethod
    def _two_shipments_shipped(api):
        """One delivered-ready shipment with no surcharge, one with 250 cents.

        The canonical three-line kit assembles at 454 cents and the center
        charges 300 cents of freight, so each shipment commits 754 cents.
        """
        world = fx.allocated_sample_world(
            api,
            panelist_count=2,
            surcharges=[0, 250],
            center_overrides={"freight_cents_per_kit": 300},
            wave_overrides={"planned_capacity_units": 50},
        )
        fx.lock_wave(api, world.wave_id)
        fx.release_wave(api, world.wave_id)
        return world

    def test_provisional_cost_ignores_the_surcharge_and_counts_the_lost_shipment(self, api):
        """PRD §3.6: "The numerator sums, once per shipment in that population,
        the campaign's `kit_assembly_unit_cost_cents` plus that shipment's
        freight, and it ignores `surcharge_cents` and `write_off_cost_cents`
        altogether. The result is that sum divided by the count of shipments in
        the population, rounded half-up to a whole cent in a **single** division
        at the end."

        Design: Difficulty/dual_variant_calc/cost_per_sample_provisional_vs_final_on_campaign
        """
        world = self._two_shipments_shipped(api)
        ops = fulfillment_ops_headers()

        delivered = validate_success(
            api.deliver_sample_shipment(ops, world.shipment_id(0))
        )
        lost = validate_success(
            api.report_sample_shipment_lost(ops, world.shipment_id(1))
        )

        assert delivered["status"] == "DELIVERED"
        assert lost["status"] == "LOST"
        assert delivered["committed_cost_cents"] == 754
        assert lost["committed_cost_cents"] == 754

        campaign = validate_success(
            api.get_campaign(campaign_manager_headers(), world.campaign_id)
        )
        assert campaign["kit_assembly_unit_cost_cents"] == 454
        assert campaign["delivered_sample_count"] == 1
        assert campaign["cost_per_sample_provisional_cents"] == 754

    def test_final_cost_keeps_the_lost_shipment_in_the_numerator_only(self, api):
        """PRD §3.6: "A `LOST` shipment therefore stays in the numerator and
        leaves the denominator: its cost was really incurred but it delivered
        nothing."

        Design: Difficulty/dual_variant_calc/cost_per_sample_provisional_vs_final_on_campaign
        """
        world = self._two_shipments_shipped(api)
        ops = fulfillment_ops_headers()

        validate_success(api.deliver_sample_shipment(ops, world.shipment_id(0)))
        validate_success(api.report_sample_shipment_lost(ops, world.shipment_id(1)))

        campaign = validate_success(
            api.get_campaign(campaign_manager_headers(), world.campaign_id)
        )
        assert campaign["delivered_sample_count"] == 1
        assert campaign["cost_per_sample_final_cents"] == 1758

    def test_cost_summary_reports_both_variants_side_by_side(self, api):
        """PRD §3.6: "A dedicated cost read exposes both figures side by side
        together with the budget triple, returning `campaign_id`,
        `kit_assembly_unit_cost_cents`, `cost_per_sample_provisional_cents`,
        `cost_per_sample_final_cents`, `budget_total_cents`,
        `budget_committed_cents`, `budget_available_cents`,
        `allocated_sample_count`, `delivered_sample_count` and
        `write_off_cost_cents`, so that the budget conservation identity of §2.7
        can be checked directly against the cost figures derived from it."

        Design: Difficulty/dual_variant_calc/cost_per_sample_provisional_vs_final_on_campaign
        """
        world = self._two_shipments_shipped(api)
        ops = fulfillment_ops_headers()

        validate_success(api.deliver_sample_shipment(ops, world.shipment_id(0)))
        validate_success(api.report_sample_shipment_lost(ops, world.shipment_id(1)))

        summary = validate_success(
            api.get_campaign_cost_summary(campaign_manager_headers(), world.campaign_id)
        )
        assert summary["campaign_id"] == world.campaign_id
        assert summary["kit_assembly_unit_cost_cents"] == 454
        assert summary["cost_per_sample_provisional_cents"] == 754
        assert summary["cost_per_sample_final_cents"] == 1758
        assert summary["delivered_sample_count"] == 1


class TestFraudRiskScoreVariants:
    """The screening and audit fraud scores on one unchanged panelist row."""

    @staticmethod
    def _shared_address_pair(api):
        """A sibling and a target panelist that share one address hash.

        The target's account was opened on 2026-07-20, twelve whole days before
        the clock's instant, so the account-age term applies to it.
        """
        sibling = fx.create_panelist(
            api,
            email="sib@example.com",
            display_name="Sibling",
            address_hash="H-SHARED",
            account_opened_at="2026-01-01T00:00:00Z",
        )
        target = fx.create_panelist(
            api,
            email="tgt@example.com",
            display_name="Target",
            address_hash="H-SHARED",
            account_opened_at="2026-07-20T00:00:00Z",
        )
        return sibling, target

    def test_screening_variant_takes_the_address_term_at_face_weight(self, api):
        """PRD §3.3: "The **screening variant** is the sum of exactly those four
        terms, taken with the address term at its face weight. The result is
        capped at 100.0, rounded half-up to one decimal place, and written to
        `fraud_risk_score_screening`."

        Design: Difficulty/dual_variant_calc/panelist_fraud_screening_vs_audit_on_shared_address
        """
        sibling, target = self._shared_address_pair(api)
        moderator = moderator_a_headers()

        scored = validate_success(
            api.rescore_panelist_risk(moderator, target["id"], "SCREENING")
        )

        assert scored["fraud_risk_score_screening"] == pytest.approx(28.0, abs=0.01)
        assert_instant(scored["last_risk_scored_at"], "2026-08-01T00:00:00Z", "last_risk_scored_at")

        untouched = validate_success(api.get_panelist(moderator, sibling["id"]))
        assert untouched["fraud_risk_score_screening"] == pytest.approx(0.0, abs=0.01)

    def test_audit_variant_multiplies_the_same_address_term_by_one_and_a_half(self, api):
        """PRD §3.3: "The **audit variant** re-weights and extends. The address
        term is multiplied by 1.5 before summation, and two additional terms
        join."

        Design: Difficulty/dual_variant_calc/panelist_fraud_screening_vs_audit_on_shared_address
        """
        _, target = self._shared_address_pair(api)
        moderator = moderator_a_headers()

        validate_success(api.rescore_panelist_risk(moderator, target["id"], "SCREENING"))
        audited = validate_success(
            api.rescore_panelist_risk(moderator, target["id"], "AUDIT")
        )

        assert audited["fraud_risk_score_screening"] == pytest.approx(28.0, abs=0.01)
        assert audited["fraud_risk_score_audit"] == pytest.approx(31.0, abs=0.01)
        assert_instant(audited["last_risk_scored_at"], "2026-08-01T00:00:00Z", "last_risk_scored_at")

    def test_an_audit_score_below_the_threshold_leaves_the_standing_clear(self, api):
        """PRD §3.3: "when the resulting `fraud_risk_score_audit` is at least
        55.0 and the panelist is currently `CLEAR`, their `integrity_status`
        becomes `FLAGGED`."

        Design: Difficulty/dual_variant_calc/panelist_fraud_screening_vs_audit_on_shared_address
        """
        _, target = self._shared_address_pair(api)
        moderator = moderator_a_headers()

        validate_success(api.rescore_panelist_risk(moderator, target["id"], "SCREENING"))
        audited = validate_success(
            api.rescore_panelist_risk(moderator, target["id"], "AUDIT")
        )

        assert audited["fraud_risk_score_audit"] == pytest.approx(31.0, abs=0.01)
        assert audited["integrity_status"] == "CLEAR"
