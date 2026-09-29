"""Quantities that must come back to where they started after a round trip.

Hydraulic flow handed out to a second pump is handed back when the pump goes
away, and the money moved off an order's ledger by a dispute comes back onto it
when the claim is settled again.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import test_users as users
from test_helpers.assertions import (
    assert_claim_split,
    assert_order_commitments,
    assert_order_ledger,
)
from test_helpers.constants import EQ_PTO_PUMP_AUX, vin_f550
from test_helpers.fixtures import (
    adjudicate_claim,
    allocate,
    catalog_service,
    delivered_service_order,
    dispute_claim,
    inspect_claim,
    new_configuration,
    new_customer,
    new_equipment_spec,
    new_order,
    open_claim,
    plan_equipment,
    read_claim,
    read_installation,
    read_order,
    received_and_inspected_chassis,
    remove_equipment,
)

PUMP_REMOVAL_REASON = "auxiliary pump deleted from the build sheet"
DISPUTE_REASON = "fleet disputes the upfitter share of the harness failure"


def _crane_only_order(api):
    """A bound truck with a single planned crane drawing eight of eighteen gallons."""
    ns = catalog_service(api)
    ns.pump = new_equipment_spec(api, EQ_PTO_PUMP_AUX)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.chassis = received_and_inspected_chassis(
        api, ns.cm["id"], vin=vin_f550(18), measured=(4820, 2680)
    )
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-2801",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
        required_payload_lb=5000,
        requested_in_service_date="2026-09-20",
    )
    allocate(api, ns.order["id"], ns.chassis["id"])
    ns.crane_install = plan_equipment(
        api, ns.order["id"], ns.crane["id"], 208, "PRIMARY", headers=users.TECHNICIAN
    )
    ns.order = read_order(api, ns.order["id"])
    return ns


def _adjudicated_electrical_claim(api):
    """A delivered gateway truck carrying a settled 73333-cent harness claim."""
    ns = delivered_service_order(
        api,
        interfaces=[("CAN_GATEWAY", 8, "J1939_BUS")],
        order_type="CUSTOMER_SPECIFIC",
        warranty_liability_cap_cents=5000000,
    )
    ns.claim = open_claim(
        api, ns.order["id"], "CHASSIS_ELECTRICAL", 73333, claim_number="WC-3901"
    )
    ns.claim = inspect_claim(api, ns.claim["id"], True)
    ns.claim = adjudicate_claim(api, ns.claim["id"])
    ns.order = read_order(api, ns.order["id"])
    return ns


class TestHydraulicFlowConservation:
    """Adding and then stripping a second pump leaves the pool exactly as it was."""

    def test_planning_the_second_pump_raises_the_committed_flow_and_load(self, api):
        """Six more gallons and four more amps are committed by the pump.

        The order starts committed to the crane's eight gallons and to twenty-two
        amps of body and crane, and planning the pump moves those to fourteen
        gallons and twenty-six amps.

        Design: Difficulty/compensating_invariant/pto_flow_conservation_across_install_and_remove
        """
        ns = _crane_only_order(api)
        assert_order_commitments(ns.order, flow_gpm=8, aux_amps=22)

        plan_equipment(
            api, ns.order["id"], ns.pump["id"], 150, "SECONDARY", headers=users.TECHNICIAN
        )

        assert_order_commitments(read_order(api, ns.order["id"]), flow_gpm=14, aux_amps=26)

    def test_removing_the_pump_hands_every_gallon_and_amp_back(self, api):
        """The round trip is exact, not approximate.

        With the pump stripped the order is committed to eight gallons and
        twenty-two amps again — the values it held before the pump existed — and
        the pump's own row keeps neither flow nor a hydraulic verdict.

        Design: Difficulty/compensating_invariant/pto_flow_conservation_across_install_and_remove
        """
        ns = _crane_only_order(api)
        pump_install = plan_equipment(
            api, ns.order["id"], ns.pump["id"], 150, "SECONDARY", headers=users.TECHNICIAN
        )

        remove_equipment(api, pump_install["id"], PUMP_REMOVAL_REASON)

        assert_order_commitments(read_order(api, ns.order["id"]), flow_gpm=8, aux_amps=22)
        removed = read_installation(api, pump_install["id"])
        assert removed["status"] == "REMOVED"
        assert removed["allocated_flow_gpm"] == 0
        assert removed["hydraulic_status"] == "NOT_APPLICABLE"

    def test_the_crane_grant_is_untouched_at_every_step(self, api):
        """The higher-ranked crane is never disturbed by the pump coming and going.

        The crane is served first in the waterfall, so its eight-gallon grant and
        its satisfied verdict hold before the pump is planned, while the pump
        holds its own six gallons, and after the pump is gone.

        Design: Difficulty/compensating_invariant/pto_flow_conservation_across_install_and_remove
        """
        ns = _crane_only_order(api)
        assert ns.crane_install["allocated_flow_gpm"] == 8
        assert ns.crane_install["hydraulic_status"] == "OK"
        assert ns.crane["duty_priority"] < ns.pump["duty_priority"]

        pump_install = plan_equipment(
            api, ns.order["id"], ns.pump["id"], 150, "SECONDARY", headers=users.TECHNICIAN
        )
        assert pump_install["allocated_flow_gpm"] == 6
        assert pump_install["hydraulic_status"] == "OK"
        crane = read_installation(api, ns.crane_install["id"])
        assert crane["allocated_flow_gpm"] == 8
        assert crane["hydraulic_status"] == "OK"

        remove_equipment(api, pump_install["id"], PUMP_REMOVAL_REASON)

        crane = read_installation(api, ns.crane_install["id"])
        assert crane["allocated_flow_gpm"] == 8
        assert crane["hydraulic_status"] == "OK"


class TestWarrantyCentsConservation:
    """Disputing a settled claim takes it off the order's books; settling puts it back."""

    def test_the_dispute_empties_the_order_ledger_without_touching_the_claim(self, api):
        """Only the rollup moves: the settlement being argued about stays on record.

        The order carried the settled split before the dispute and carries nothing
        after it, while the claim itself keeps the same three amounts, lands at
        DISPUTED and counts its first dispute round.

        Design: Difficulty/compensating_invariant/warranty_cents_conservation_across_dispute_and_readjudication
        """
        ns = _adjudicated_electrical_claim(api)
        assert_order_ledger(ns.order, 11000, 58666, 3667)

        disputed = dispute_claim(api, ns.claim["id"], DISPUTE_REASON)

        assert_order_ledger(read_order(api, ns.order["id"]), 0, 0, 0)
        assert_claim_split(disputed, 15, 80, 5, 11000, 58666, 3667, split_basis="FINAL")
        assert disputed["status"] == "DISPUTED"
        assert disputed["dispute_round"] == 1

    def test_re_adjudication_puts_the_same_cents_back_on_the_order(self, api):
        """The money returns to the ledger unchanged, down to the last cent.

        Re-inspecting and re-adjudicating settle the claim on the final basis
        again, and the order's three ledger fields read exactly what they read
        before the dispute.

        Design: Difficulty/compensating_invariant/warranty_cents_conservation_across_dispute_and_readjudication
        """
        ns = _adjudicated_electrical_claim(api)
        dispute_claim(api, ns.claim["id"], DISPUTE_REASON)

        inspect_claim(api, ns.claim["id"], True)
        settled = adjudicate_claim(api, ns.claim["id"])

        assert settled["status"] == "ADJUDICATED"
        assert settled["split_basis"] == "FINAL"
        assert_order_ledger(read_order(api, ns.order["id"]), 11000, 58666, 3667)

    def test_the_dispute_counter_moves_only_on_the_dispute_edge(self, api):
        """Re-inspection and re-adjudication are not further rounds of dispute.

        The counter reaches one on the dispute and stays at one through the
        re-inspection back to INSPECTED and through the re-adjudication.

        Design: Difficulty/compensating_invariant/warranty_cents_conservation_across_dispute_and_readjudication
        """
        ns = _adjudicated_electrical_claim(api)
        assert ns.claim["dispute_round"] == 0

        dispute_claim(api, ns.claim["id"], DISPUTE_REASON)
        reinspected = inspect_claim(api, ns.claim["id"], True)
        assert reinspected["status"] == "INSPECTED"
        assert reinspected["dispute_round"] == 1

        resettled = adjudicate_claim(api, ns.claim["id"])
        assert resettled["dispute_round"] == 1

    def test_the_three_shares_always_sum_to_the_repair_cost(self, api):
        """Nothing is ever created or lost in the split, whatever the claim's state.

        At settlement, while disputed and after re-settlement the chassis,
        upfitter and goodwill amounts on the claim add up to the 73333-cent repair
        cost exactly.

        Design: Difficulty/compensating_invariant/warranty_cents_conservation_across_dispute_and_readjudication
        """
        ns = _adjudicated_electrical_claim(api)

        observations = [ns.claim, dispute_claim(api, ns.claim["id"], DISPUTE_REASON)]
        inspect_claim(api, ns.claim["id"], True)
        observations.append(adjudicate_claim(api, ns.claim["id"]))
        observations.append(read_claim(api, ns.claim["id"]))

        for claim in observations:
            assert (
                claim["chassis_liability_cents"]
                + claim["upfitter_liability_cents"]
                + claim["customer_goodwill_cents"]
                == 73333
            )
            assert claim["claim_cost_cents"] == 73333

    def test_the_settled_order_ledger_never_exceeds_the_liability_cap(self, api):
        """The cap is well clear of this claim in every phase of the round trip.

        The upfitter share of 58666 cents sits far below the order's five-million
        cent cap, so neither the settlement nor the re-settlement is capped and
        the conservation being checked is not an artefact of a cap being hit.

        Design: Difficulty/compensating_invariant/warranty_cents_conservation_across_dispute_and_readjudication
        """
        ns = _adjudicated_electrical_claim(api)
        assert ns.order["warranty_liability_cap_cents"] == 5000000

        first = validate_success(api.get_upfit_order(ns.order["id"], users.WARRANTY_ADMIN))
        assert first["upfitter_liability_cents"] < first["warranty_liability_cap_cents"]

        dispute_claim(api, ns.claim["id"], DISPUTE_REASON)
        inspect_claim(api, ns.claim["id"], True)
        adjudicate_claim(api, ns.claim["id"])

        second = read_order(api, ns.order["id"])
        assert second["upfitter_liability_cents"] == 58666
        assert second["upfitter_liability_cents"] < second["warranty_liability_cap_cents"]
