"""Pickup-time negotiation: the OFFERED<->COUNTERED cycle and offer records.

Queue A (Difficulty): non_linear_state_machine / trip negotiation cycle.
Queue B (Corner): trip initial state, offers reverse-reachability.
"""
from test_helpers import validate_success, validate_paginated, TEST_USERS
import test_helpers as th

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ==========================================================================
# Difficulty A — REQUESTED -> OFFERED -> COUNTERED -> OFFERED cycle
# ==========================================================================
def _negotiate_to_third_offer(api):
    """Certified rider, trip offered (09:00), countered (09:30), offered again (09:15)."""
    base = th.scenario_certified_rider_zone(api)
    rider_id = base["rider"]["id"]
    zone_id = base["zone_a"]["id"]
    trip = th.request_trip(api, rider_id, zone_id, zone_id)
    th.offer_trip(api, trip["id"], "2026-06-05T09:00:00Z")
    th.counter_trip(api, trip["id"], rider_id, "2026-06-05T09:30:00Z")
    api.offer_trip(trip["id"], {"proposed_pickup_at": "2026-06-05T09:15:00Z"}, DISPATCHER)
    return trip["id"]


def test_negotiation_cycle_returns_to_offered(api):
    """PRD §3.5: "A dispatcher makes an offer, supplying a `proposed_pickup_at`; this
    advances the trip from `REQUESTED` to `OFFERED` (or from `COUNTERED` back to `OFFERED`
    on a subsequent round), records a `NegotiationOffer` whose `offered_by` is
    `DISPATCHER` and whose `proposed_pickup_at` and `round_number` capture the proposal,
    sets the trip's `current_offer_pickup_at` to the proposed time, and increments the
    trip's `offer_round`."

    Design: Difficulty/non_linear_state_machine/trip_negotiation_offered_countered_cycle_increments_offer_round
    """
    trip_id = _negotiate_to_third_offer(api)
    trip = validate_success(api.get_trip(trip_id, DISPATCHER))
    assert trip["status"] == "OFFERED"
    assert trip["current_offer_pickup_at"] == "2026-06-05T09:15:00Z"


def test_negotiation_cycle_increments_offer_round_each_hop(api):
    """PRD §3.5: "The owning rider may counter an offered time, supplying their own
    `proposed_pickup_at`; this advances the trip from `OFFERED` to `COUNTERED`, records a
    `NegotiationOffer` whose `offered_by` is `RIDER`, updates `current_offer_pickup_at`,
    and increments `offer_round`."

    Design: Difficulty/non_linear_state_machine/trip_negotiation_offered_countered_cycle_increments_offer_round
    """
    trip_id = _negotiate_to_third_offer(api)
    trip = validate_success(api.get_trip(trip_id, DISPATCHER))
    assert trip["offer_round"] == 3


# ==========================================================================
# Corner B
# ==========================================================================
def test_new_trip_starts_in_requested(api):
    """PRD §3.4: "A successful request creates a `TripReservation` in `REQUESTED`."
    PRD §3.5: "Each `NegotiationOffer` carries a one-based `round_number`, and the
    trip's `offer_round` counts the exchanges."

    Design: Corner/state_machines/trip_created_initial_state_is_requested
    """
    base = th.scenario_certified_rider_zone(api, clock=None)
    trip = th.request_trip(api, base["rider"]["id"], base["zone_a"]["id"], base["zone_a"]["id"])
    assert trip["status"] == "REQUESTED"
    assert trip["offer_round"] == 0


def test_list_offers_for_trip(api):
    """PRD §3.5: "A dispatcher makes an offer, supplying a `proposed_pickup_at`; this
    advances the trip from `REQUESTED` to `OFFERED` (or from `COUNTERED` back to `OFFERED`
    on a subsequent round), records a `NegotiationOffer` whose `offered_by` is `DISPATCHER`
    and whose `proposed_pickup_at` and `round_number` capture the proposal, sets the trip's
    `current_offer_pickup_at` to the proposed time, and increments the trip's `offer_round`."
    PRD §3.5: "Each `NegotiationOffer` carries a one-based `round_number`, and the trip's
    `offer_round` counts the exchanges."

    Design: Corner/endpoints/list_offers_for_trip_reverse_reachability
    """
    base = th.scenario_certified_rider_zone(api, clock=None)
    trip = th.create_offered_trip(api, base["rider"]["id"], base["zone_a"]["id"], base["zone_a"]["id"])
    resp = api.list_offers(trip["id"], DISPATCHER)
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert data[0]["offered_by"] == "DISPATCHER"
    assert data[0]["round_number"] == 1
