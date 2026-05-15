"""Repair-ticket lifecycle and capacity alerts (PRD §3.7, §3.8)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    accept_repair,
    api_client,
    assert_cabinet_capacity_alert_invariant,
    create_active_rental,
    create_rental_payload,
    dispatch_repair_payload,
    dispatch_repair_ticket,
    make_renter_headers,
    make_technician_headers,
    open_repair_ticket,
    rent_k_compartments,
    repair_as_technician,
    repair_ticket_payload,
    setup_basic_rental,
    setup_cabinet_with_compartment,
    setup_cabinet_with_n_small_compartments,
    validate_error,
    validate_success,
    walk_repair_to_accepted,
)


# ===========================================================================
# Repair-ticket lifecycle happy path (PRD §3.8)
# ===========================================================================
class TestRepairLifecycle:

    def test_opening_ticket_cascades_compartment_to_fault(self, api,
                                                         operator_headers):
        """PRD §3.8: "When a fault is observed — by the renter, by an
        Operator walking the site, or by an automated detector — a
        RepairTicket is opened against a specific compartment_id with a
        fault_category drawn from DOOR_NOT_CLOSED, SENSOR_FAULT,
        COMMUNICATION_LOSS, and USER_REPORTED. The compartment's
        operational_status cascades from OK to FAULT and its
        fault_category is set."

        Claim: opening a ticket flips Compartment.operational_status to
        FAULT and sets fault_category.
        """
        cabinet, comps, _ = setup_cabinet_with_compartment()
        ticket = open_repair_ticket(comps[0]["id"],
                                    fault_category="SENSOR_FAULT")
        assert ticket["status"] == "OPEN"
        comp = validate_success(api.get_compartment(
            cabinet["id"], comps[0]["id"], operator_headers,
        ))
        assert comp["operational_status"] == "FAULT"
        assert comp["fault_category"] == "SENSOR_FAULT"

    def test_dispatch_advances_status(self, api):
        """PRD §3.8: "An Operator dispatches the ticket by supplying
        assigned_technician_id and optional version; the ticket's status
        advances to DISPATCHED."

        Claim: dispatch on OPEN ticket → DISPATCHED with technician_id.
        """
        cabinet, comps, _ = setup_cabinet_with_compartment()
        ticket = open_repair_ticket(comps[0]["id"])
        dispatched = dispatch_repair_ticket(
            ticket["id"], technician_id="tech-a",
            version=ticket["version"],
        )
        assert dispatched["status"] == "DISPATCHED"
        assert dispatched["assigned_technician_id"] == "tech-a"

    def test_repair_advances_status_when_caller_is_assigned(self, api):
        """PRD §3.8: "The assigned RepairTechnician — and only that
        technician, identified by X-User-ID equality with
        assigned_technician_id — then marks the work as repaired by
        supplying repair_notes."

        Claim: repair as the assigned technician → status=REPAIRED.
        """
        cabinet, comps, _ = setup_cabinet_with_compartment()
        ticket = open_repair_ticket(comps[0]["id"])
        ticket = dispatch_repair_ticket(
            ticket["id"], technician_id="tech-b", version=ticket["version"],
        )
        repaired = repair_as_technician(
            ticket["id"], technician_id="tech-b",
            repair_notes="aligned", version=ticket["version"],
        )
        assert repaired["status"] == "REPAIRED"
        assert repaired["repair_notes"] == "aligned"

    def test_repair_by_unassigned_technician_rejected(self, api):
        """PRD §3.8: "The assigned RepairTechnician — and only that
        technician, identified by X-User-ID equality with
        assigned_technician_id — then marks the work as repaired."

        Claim: repair by a different technician → ERR_FORBIDDEN.
        """
        cabinet, comps, _ = setup_cabinet_with_compartment()
        ticket = open_repair_ticket(comps[0]["id"])
        ticket = dispatch_repair_ticket(
            ticket["id"], technician_id="tech-assigned",
            version=ticket["version"],
        )
        resp = api.repair_ticket(
            ticket["id"], repair_ticket_payload(repair_notes="x",
                                                version=ticket["version"]),
            make_technician_headers("tech-impostor"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_accept_repair_restores_compartment_ok(self, api,
                                                  operator_headers):
        """PRD §3.8: "An Operator accepts the repair, advancing status to
        ACCEPTED, stamping accepted_at, cascading the compartment's
        operational_status back to OK, and clearing fault_category."

        Claim: accept on REPAIRED → status=ACCEPTED, accepted_at set,
        Compartment.operational_status=OK, fault_category=null.

        # difficulty: transitive_cascade/repair_acceptance_two_hop_cascade
        """
        cabinet, comps, _ = setup_cabinet_with_compartment()
        ticket = walk_repair_to_accepted(comps[0]["id"])
        assert ticket["status"] == "ACCEPTED"
        assert ticket["accepted_at"] is not None
        comp = validate_success(api.get_compartment(
            cabinet["id"], comps[0]["id"], operator_headers,
        ))
        assert comp["operational_status"] == "OK"
        assert comp.get("fault_category") in (None,)

    def test_rental_creation_succeeds_after_accept(self, api):
        """PRD §3.8: "An Operator accepts the repair, advancing status to
        ACCEPTED, stamping accepted_at, cascading the compartment's
        operational_status back to OK, and clearing fault_category;
        this makes the compartment rentable again once occupancy_status
        is IDLE."

        Claim: after accept, a new rental on this compartment succeeds
        (was previously blocked by ERR_COMPARTMENT_FAULT).

        # difficulty: transitive_cascade/repair_acceptance_two_hop_cascade
        """
        from test_helpers import create_pricing_profile
        cabinet, comps, _ = setup_cabinet_with_compartment(
            create_pricing=True, rental_mode="HOURLY",
        )
        walk_repair_to_accepted(comps[0]["id"])
        # Rental should now succeed.
        resp = api.create_rental(
            cabinet["id"], comps[0]["id"], create_rental_payload(),
            make_renter_headers("renter-after-repair"),
        )
        validate_success(resp, expected_status=201)


# ===========================================================================
# Capacity alert tiering (PRD §3.7)
# ===========================================================================
class TestCapacityAlerts:

    def test_capacity_alert_none_below_warning(self, api, operator_headers):
        """PRD §3.7: "A percentage at or above 95.00 is CRITICAL, a
        percentage at or above 80.00 (but below 95.00) is WARNING, and
        anything below 80.00 is NONE."

        Claim: 3 rented of 5 SMALL = 60.00% → capacity_alert_level=NONE.

        # difficulty: boundary_precision_check/capacity_alert_threshold_exactly_80_pct
        """
        cabinet, comps, _ = setup_cabinet_with_n_small_compartments(
            5, rental_mode="DAILY",
        )
        rent_k_compartments(cabinet["id"], comps, 3, rental_mode="DAILY")
        fresh = validate_success(api.get_cabinet(
            cabinet["id"], operator_headers,
        ))
        assert fresh["small_occupancy_pct"] == 60.00
        assert fresh["capacity_alert_level"] == "NONE"

    def test_capacity_alert_warning_at_exactly_80_pct(self, api,
                                                     operator_headers):
        """PRD §3.7: "The threshold comparisons are >=, not >, so a
        percentage of exactly 80.00 trips WARNING and exactly 95.00
        trips CRITICAL."

        Claim: 4 rented of 5 SMALL = 80.00% → capacity_alert_level=WARNING.

        # difficulty: boundary_precision_check/capacity_alert_threshold_exactly_80_pct
        """
        cabinet, comps, _ = setup_cabinet_with_n_small_compartments(
            5, rental_mode="DAILY",
        )
        rent_k_compartments(cabinet["id"], comps, 4, rental_mode="DAILY")
        fresh = validate_success(api.get_cabinet(
            cabinet["id"], operator_headers,
        ))
        assert fresh["small_occupancy_pct"] == 80.00
        assert fresh["capacity_alert_level"] == "WARNING"

    def test_capacity_alert_critical_at_95_pct(self, api, operator_headers):
        """PRD §3.7: "A percentage at or above 95.00 is CRITICAL ...
        exactly 95.00 trips CRITICAL."

        Claim: 19 rented of 20 SMALL = 95.00% → capacity_alert_level=CRITICAL.
        """
        cabinet, comps, _ = setup_cabinet_with_n_small_compartments(
            20, rental_mode="DAILY",
        )
        rent_k_compartments(cabinet["id"], comps, 19, rental_mode="DAILY")
        fresh = validate_success(api.get_cabinet(
            cabinet["id"], operator_headers,
        ))
        assert fresh["small_occupancy_pct"] == 95.00
        assert fresh["capacity_alert_level"] == "CRITICAL"

    def test_alert_level_invariant_holds(self, api, operator_headers):
        """PRD §3.7: "the overall capacity_alert_level is the most severe
        of the three size-class verdicts (with CRITICAL outranking
        WARNING outranking NONE)."

        Claim: capacity_alert_level == max severity of the three
        size-class tiers (computed locally and compared).
        """
        cabinet, comps, _ = setup_cabinet_with_n_small_compartments(
            5, rental_mode="DAILY",
        )
        rent_k_compartments(cabinet["id"], comps, 4, rental_mode="DAILY")
        fresh = validate_success(api.get_cabinet(
            cabinet["id"], operator_headers,
        ))
        assert_cabinet_capacity_alert_invariant(fresh)


# ===========================================================================
# Compartment-occupancy conservation invariant
# ===========================================================================
class TestOccupancyConservation:

    def test_capacity_total_unchanged_across_rent_return_cycle(self, api,
                                                              operator_headers):
        """PRD §3.7: "For each size class, the count of compartments in
        that class becomes small_capacity_total, medium_capacity_total,
        or large_capacity_total."

        Claim: small_capacity_total is invariant across rent + return,
        and small_occupancy_pct returns to its pre-rental value.

        # difficulty: compensating_invariant/compartment_occupancy_count_conservation_on_return
        """
        cabinet, comps, _ = setup_cabinet_with_n_small_compartments(
            4, rental_mode="DAILY",
        )
        s0 = validate_success(api.get_cabinet(cabinet["id"],
                                              operator_headers))
        assert s0["small_capacity_total"] == 4
        assert s0["small_occupancy_pct"] == 0.00
        assert s0["capacity_alert_level"] == "NONE"

        # rent one
        rental, renter_id = create_active_rental(
            cabinet["id"], comps[0]["id"],
            renter_id="renter-cap-cycle",
            rental_mode="DAILY", billing_units=1, unlock_channel="QR",
        )
        s1 = validate_success(api.get_cabinet(cabinet["id"],
                                              operator_headers))
        assert s1["small_capacity_total"] == 4, (
            "small_capacity_total must remain 4 across the cycle"
        )
        assert s1["small_occupancy_pct"] == 25.00

        # return
        from test_helpers import return_rental_as_owner
        return_rental_as_owner(rental, renter_id)
        s2 = validate_success(api.get_cabinet(cabinet["id"],
                                              operator_headers))
        assert s2["small_capacity_total"] == 4
        assert s2["small_occupancy_pct"] == 0.00, (
            f"after return occupancy_pct must return to 0.00, "
            f"got {s2['small_occupancy_pct']}"
        )
        assert s2["capacity_alert_level"] == "NONE"
