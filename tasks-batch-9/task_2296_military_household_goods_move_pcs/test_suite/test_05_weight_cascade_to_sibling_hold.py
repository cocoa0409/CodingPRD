"""One certified scale reading running four links to a sibling shipment's hold."""

import pytest

from test_helpers import (
    find_notification,
    read_entitlement,
    read_shipment,
    record_actual_weight,
    setup_second_shipment,
    setup_surveyed_shipment,
)

E5_WITHOUT_DEPENDENTS = {
    "rank_code": "E5",
    "branch": "AIR_FORCE",
    "dependents_count": 0,
    "spouse_present": False,
}


def _heavy_scale_reading_on_the_first_shipment():
    """A 7,000 pound cap charged 10,000 pounds, with a second shipment still awarded."""
    scenario = setup_surveyed_shipment(member_overrides=E5_WITHOUT_DEPENDENTS)
    scenario["shipment_2"] = setup_second_shipment(
        scenario,
        shipment_code="SHP-C02",
        shipment_method="UB",
        requested_pack_date="2026-09-01T00:00:00Z",
        requested_pickup_date="2026-09-08T00:00:00Z",
        requested_delivery_date="2026-09-20T00:00:00Z",
    )
    assert scenario["entitlement"]["total_billable_cap_lbs"] == 7000
    assert scenario["shipment_2"]["movement_status"] == "AWARDED"
    assert scenario["shipment_2"]["weight_recon_status"] == "PENDING"

    scenario["weighed"] = record_actual_weight(
        scenario, 11800, 1800, weigh_date="2026-08-03T00:00:00Z"
    )
    return scenario


class TestActualWeightCascade:
    """The scale figure moves the shipment, the ledger, the entitlement and its siblings."""

    def test_the_scale_figures_become_the_weight_of_record(self):
        """11,800 gross less 1,800 tare charges 10,000 pounds and demands a reweigh.

        "**First**, `billable_weight_lbs` is recomputed under the final actual variant and
        `billable_basis` becomes `ACTUAL`."

        Design: Difficulty/transitive_cascade/actual_weight_cascades_four_links_to_sibling_shipment_hold
        """
        scenario = _heavy_scale_reading_on_the_first_shipment()
        weighed = scenario["weighed"]

        assert weighed["net_actual_lbs"] == 10000
        assert weighed["billable_weight_lbs"] == 10000
        assert weighed["billable_basis"] == "ACTUAL"
        assert weighed["reweigh_required"] is True

    def test_the_entitlement_ledger_prices_the_overage(self):
        """3,000 pounds over a 7,000 pound cap costs 2,835.00 plus a 170.10 fee.

        "**Second**, because the shipment's charge changed, the owning entitlement's
        `charged_billable_weight_lbs`, `excess_weight_lbs`, `gross_excess_cost_usd` and
        `excess_cost_due_usd` are recomputed."

        Design: Difficulty/transitive_cascade/actual_weight_cascades_four_links_to_sibling_shipment_hold
        """
        scenario = _heavy_scale_reading_on_the_first_shipment()

        entitlement = read_entitlement(scenario["entitlement"]["id"])
        assert entitlement["charged_billable_weight_lbs"] == 10000
        assert entitlement["excess_weight_lbs"] == 3000
        assert entitlement["gross_excess_cost_usd"] == pytest.approx(3005.10, abs=0.01)
        assert entitlement["excess_cost_due_usd"] == pytest.approx(3005.10, abs=0.01)

    def test_money_outstanding_above_the_threshold_suspends_the_entitlement(self):
        """3,005.10 due is more than the 2,500.00 the program tolerates.

        "**Third**, if the recomputed `excess_cost_due_usd` now strictly exceeds 2,500.00
        US dollars while the entitlement is `AUTHORIZED`, the entitlement moves
        `AUTHORIZED → SUSPENDED` with `suspension_reason` `EXCESS_COST_UNPAID`."

        Design: Difficulty/transitive_cascade/actual_weight_cascades_four_links_to_sibling_shipment_hold
        """
        scenario = _heavy_scale_reading_on_the_first_shipment()

        entitlement = read_entitlement(scenario["entitlement"]["id"])
        assert entitlement["status"] == "SUSPENDED"
        assert entitlement["suspension_reason"] == "EXCESS_COST_UNPAID"

    def test_the_untouched_sibling_shipment_goes_on_hold(self):
        """The awarded baggage shipment freezes while the weighed shipment carries on.

        "**Fourth**, every sibling shipment sharing that `entitlement_id` whose
        `movement_status` is `AWARDED` moves `AWARDED → ON_HOLD` with `hold_reason`
        `ENTITLEMENT_SUSPENDED` — a heavy scale reading on one shipment can therefore
        freeze a member's other, untouched shipments."

        Design: Difficulty/transitive_cascade/actual_weight_cascades_four_links_to_sibling_shipment_hold
        """
        scenario = _heavy_scale_reading_on_the_first_shipment()

        sibling = read_shipment(scenario["shipment_2"]["id"])
        assert sibling["movement_status"] == "ON_HOLD"
        assert sibling["hold_reason"] == "ENTITLEMENT_SUSPENDED"
        assert read_shipment(scenario["shipment"]["id"])["movement_status"] == "SURVEYED"

    def test_recording_the_weight_owes_the_member_a_weekly_notification(self):
        """The obligation is due a week after the scale reading and starts unsent.

        "Recording the weight also creates one `PENDING` notification obligation of type
        `WEIGHT_RECON_COMPLETE`."

        Design: Difficulty/transitive_cascade/actual_weight_cascades_four_links_to_sibling_shipment_hold
        """
        scenario = _heavy_scale_reading_on_the_first_shipment()

        obligation = find_notification(
            scenario["shipment"]["id"], "WEIGHT_RECON_COMPLETE"
        )
        assert obligation["status"] == "PENDING"
        assert obligation["sla_hours"] == 168
        assert obligation["due_by"] == "2026-08-10T00:00:00Z"
