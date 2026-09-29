"""Composite fixtures.

The harness resets the database before every test, so each test builds the world
it needs from scratch.  ``Scenario`` bundles the multi-step chains that recur -
publishing a family, publishing it to a channel, holding a booking, disclosing and
acknowledging its fees, ticketing it - so a test spends its lines on the behaviour
under examination rather than on setup plumbing.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import validate_success

from . import factories
from .api_client import ApiClient
from .test_users import (
    DISTRIBUTION_MANAGER,
    MERCHANDISING_ANALYST,
    OPERATIONS_CONTROLLER,
    PRICING_APPROVER,
    REVENUE_ACCOUNTANT,
    make_channel_partner_headers,
)

CLOCK_9AM = "2026-08-10T09:00:00Z"


class Scenario:
    """Builder for the multi-step setups the workflows require."""

    def __init__(self, api: ApiClient):
        self.api = api

    # -----------------------------------------------------------------
    # Logical clock
    # -----------------------------------------------------------------
    def set_clock(self, to_iso8601: str) -> Dict[str, Any]:
        response = self.api.set_current_utc(
            factories.clock_payload(to_iso8601), OPERATIONS_CONTROLLER
        )
        return validate_success(response)

    # -----------------------------------------------------------------
    # Catalog
    # -----------------------------------------------------------------
    def create_product(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = self.api.create_ancillary_product(payload, MERCHANDISING_ANALYST)
        return validate_success(response, 201)

    def create_products(self, payloads: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [self.create_product(p) for p in payloads]

    def standard_catalog(self) -> Dict[str, Dict[str, Any]]:
        """The five products the merchandising workflows lean on, keyed by sku."""
        products = self.create_products(
            [
                factories.checked_bag_product_payload(),
                factories.standard_seat_product_payload(),
                factories.priority_boarding_product_payload(),
                factories.wifi_product_payload(),
                factories.change_flex_product_payload(),
            ]
        )
        return {p["sku"]: p for p in products}

    # -----------------------------------------------------------------
    # Fare families
    # -----------------------------------------------------------------
    def create_family(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = self.api.create_fare_family(payload, MERCHANDISING_ANALYST)
        return validate_success(response, 201)

    def add_attribute(
        self, family_id: str, ancillary_product_id: str, **overrides
    ) -> Dict[str, Any]:
        response = self.api.add_family_attribute(
            family_id,
            factories.family_attribute_payload(ancillary_product_id, **overrides),
            MERCHANDISING_ANALYST,
        )
        return validate_success(response, 201)

    def submit_family(self, family_id: str) -> Dict[str, Any]:
        response = self.api.submit_fare_family(family_id, {}, MERCHANDISING_ANALYST)
        return validate_success(response)

    def review_family(self, family_id: str, decision: str = "APPROVE") -> Dict[str, Any]:
        response = self.api.review_fare_family(
            family_id, factories.review_decision_payload(decision), PRICING_APPROVER
        )
        return validate_success(response)

    def publish_family(self, family_id: str) -> Dict[str, Any]:
        """Submit then approve, which publishes the family."""
        self.submit_family(family_id)
        return self.review_family(family_id, "APPROVE")

    def build_published_family(
        self,
        family_payload: Dict[str, Any],
        attributes: Sequence[Tuple[str, Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """Create a family with attributes and drive it to PUBLISHED.

        ``attributes`` is a sequence of ``(product_id, attribute_overrides)``.
        Returns the published family resource.
        """
        family = self.create_family(family_payload)
        for product_id, overrides in attributes:
            self.add_attribute(family["id"], product_id, **overrides)
        return self.publish_family(family["id"])

    def get_family(self, family_id: str) -> Dict[str, Any]:
        return validate_success(self.api.get_fare_family(family_id, MERCHANDISING_ANALYST))

    def family_attributes(self, family_id: str) -> List[Dict[str, Any]]:
        body = validate_success(
            self.api.list_family_attributes_of_family(family_id, MERCHANDISING_ANALYST)
        )
        return body if isinstance(body, list) else body

    # -----------------------------------------------------------------
    # Flights, demand and the seat map
    # -----------------------------------------------------------------
    def create_flight(self, **overrides) -> Dict[str, Any]:
        response = self.api.create_flight(
            factories.flight_payload(**overrides), OPERATIONS_CONTROLLER
        )
        return validate_success(response, 201)

    def post_demand(
        self, flight_id: str, booked_load_factor_pct: int, demand_index_bp: int
    ) -> Dict[str, Any]:
        response = self.api.post_demand_snapshot(
            flight_id,
            factories.demand_snapshot_payload(booked_load_factor_pct, demand_index_bp),
            OPERATIONS_CONTROLLER,
        )
        return validate_success(response)

    def advance_phase(self, flight_id: str, target_phase: str) -> Dict[str, Any]:
        return validate_success(
            self.api.advance_flight_phase(
                flight_id, factories.phase_advance_payload(target_phase), OPERATIONS_CONTROLLER
            )
        )

    def advance_to_phase(self, flight_id: str, target_phase: str) -> Dict[str, Any]:
        """Walk the retailing timeline one legal step at a time up to target_phase."""
        ladder = ["PRESALE", "CHECKIN_OPEN", "BOARDING", "DEPARTED"]
        result = None
        for phase in ladder[1 : ladder.index(target_phase) + 1]:
            result = self.advance_phase(flight_id, phase)
        return result

    def settle_change(self, booking_id: str, channel_id: str, resolution: str = "CONFIRM") -> Dict[str, Any]:
        return validate_success(
            self.api.settle_booking_change(
                booking_id,
                factories.change_settle_payload(resolution),
                make_channel_partner_headers(channel_id),
            )
        )

    def open_change(self, booking_id: str, channel_id: str) -> Dict[str, Any]:
        return validate_success(
            self.api.open_booking_change(
                booking_id, {}, make_channel_partner_headers(channel_id)
            )
        )

    def cancel(self, booking_id: str, channel_id: str, cancel_reason: str = "Passenger request") -> Dict[str, Any]:
        return validate_success(
            self.api.cancel_booking(
                booking_id,
                factories.cancel_payload(cancel_reason),
                make_channel_partner_headers(channel_id),
            )
        )

    def release_seat(self, assignment_id: str, channel_id: str, release_reason: str = "PASSENGER_RELEASE") -> Dict[str, Any]:
        return validate_success(
            self.api.release_seat_assignment(
                assignment_id,
                factories.seat_release_payload(release_reason),
                make_channel_partner_headers(channel_id),
            )
        )

    def change_family_status(self, family_id: str, target_status: str, reason: str = "Commercial decision") -> Dict[str, Any]:
        return validate_success(
            self.api.change_fare_family_status(
                family_id, factories.status_change_payload(target_status, reason), PRICING_APPROVER
            )
        )

    def create_segment(
        self, flight_id: str, ancillary_product_id: str, **overrides
    ) -> Dict[str, Any]:
        response = self.api.create_seat_segment(
            factories.seat_segment_payload(flight_id, ancillary_product_id, **overrides),
            OPERATIONS_CONTROLLER,
        )
        return validate_success(response, 201)

    def get_segment(self, segment_id: str) -> Dict[str, Any]:
        return validate_success(
            self.api.get_seat_segment(segment_id, OPERATIONS_CONTROLLER)
        )

    # -----------------------------------------------------------------
    # Distribution
    # -----------------------------------------------------------------
    def create_channel(self, payload: Optional[Dict[str, Any]] = None, **overrides) -> Dict[str, Any]:
        body = payload if payload is not None else factories.distribution_channel_payload(**overrides)
        response = self.api.create_distribution_channel(body, DISTRIBUTION_MANAGER)
        return validate_success(response, 201)

    def get_channel(self, channel_id: str) -> Dict[str, Any]:
        return validate_success(
            self.api.get_distribution_channel(channel_id, DISTRIBUTION_MANAGER)
        )

    def publish_to_channel(
        self, family_id: str, channel_id: str, expected_family_version
    ) -> Dict[str, Any]:
        response = self.api.create_channel_publication(
            factories.channel_publication_payload(
                family_id, channel_id, expected_family_version
            ),
            DISTRIBUTION_MANAGER,
        )
        return validate_success(response, 201)

    def get_publication(self, publication_id: str) -> Dict[str, Any]:
        return validate_success(
            self.api.get_channel_publication(publication_id, DISTRIBUTION_MANAGER)
        )

    # -----------------------------------------------------------------
    # Bookings
    # -----------------------------------------------------------------
    def create_booking(
        self, flight_id: str, family_id: str, channel_id: str, **overrides
    ) -> Dict[str, Any]:
        response = self.api.create_booking(
            factories.booking_payload(flight_id, family_id, channel_id, **overrides),
            make_channel_partner_headers(channel_id),
        )
        return validate_success(response, 201)

    def get_booking(self, booking_id: str, channel_id: str) -> Dict[str, Any]:
        return validate_success(
            self.api.get_booking(booking_id, make_channel_partner_headers(channel_id))
        )

    def disclose(self, booking_id: str, channel_id: str) -> Dict[str, Any]:
        return validate_success(
            self.api.issue_disclosure(
                booking_id, {}, make_channel_partner_headers(channel_id)
            )
        )

    def acknowledge(
        self, booking_id: str, channel_id: str, fingerprint: str
    ) -> Dict[str, Any]:
        return validate_success(
            self.api.acknowledge_disclosure(
                booking_id,
                factories.disclosure_ack_payload(fingerprint),
                make_channel_partner_headers(channel_id),
            )
        )

    def disclose_and_acknowledge(self, booking_id: str, channel_id: str) -> Dict[str, Any]:
        disclosed = self.disclose(booking_id, channel_id)
        return self.acknowledge(
            booking_id, channel_id, disclosed["disclosed_fee_fingerprint"]
        )

    def ticket(self, booking_id: str, channel_id: str) -> Dict[str, Any]:
        return validate_success(
            self.api.ticket_booking(
                booking_id, {}, make_channel_partner_headers(channel_id)
            )
        )

    def hold_disclose_ack_and_ticket(self, booking_id: str, channel_id: str) -> Dict[str, Any]:
        self.disclose_and_acknowledge(booking_id, channel_id)
        return self.ticket(booking_id, channel_id)

    def assign_seat(
        self, booking_id: str, channel_id: str, segment_id: str, row: int, letter: str
    ) -> Dict[str, Any]:
        response = self.api.create_seat_assignment(
            booking_id,
            factories.seat_assignment_payload(segment_id, row, letter),
            make_channel_partner_headers(channel_id),
        )
        return validate_success(response, 201)

    # -----------------------------------------------------------------
    # Merchandising offers
    # -----------------------------------------------------------------
    def open_offer_session(
        self,
        booking_id: str,
        channel_id: str,
        touchpoint: str = "BOOKING",
        requested_product_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        response = self.api.create_offer_session(
            booking_id,
            factories.offer_session_payload(touchpoint, requested_product_ids),
            make_channel_partner_headers(channel_id),
        )
        return validate_success(response, 201)

    def offers_for_booking(self, booking_id: str, channel_id: str, **filters) -> List[Dict[str, Any]]:
        params = {"booking_id": booking_id}
        params.update(filters)
        body = validate_success(
            self.api.list_ancillary_offers(
                make_channel_partner_headers(channel_id), params
            )
        )
        return body

    def accept_offer(
        self, offer_id: str, channel_id: str, expected_booking_version
    ) -> Dict[str, Any]:
        return validate_success(
            self.api.accept_offer(
                offer_id,
                factories.offer_accept_payload(expected_booking_version),
                make_channel_partner_headers(channel_id),
            )
        )

    def decline_offer(self, offer_id: str, channel_id: str) -> Dict[str, Any]:
        return validate_success(
            self.api.decline_offer(offer_id, {}, make_channel_partner_headers(channel_id))
        )

    # -----------------------------------------------------------------
    # Irregular operations
    # -----------------------------------------------------------------
    def declare_waiver(
        self, flight_id: str, event_type: str, delay_minutes: int, waiver_scope: List[str]
    ) -> Dict[str, Any]:
        response = self.api.declare_irops_waiver(
            flight_id,
            factories.irops_waiver_payload(event_type, delay_minutes, waiver_scope),
            OPERATIONS_CONTROLLER,
        )
        return validate_success(response, 201)

    def rescind_waiver(self, waiver_id: str, reason: str = "Operations recovered") -> Dict[str, Any]:
        return validate_success(
            self.api.rescind_irops_waiver(
                waiver_id, factories.waiver_rescind_payload(reason), OPERATIONS_CONTROLLER
            )
        )

    # -----------------------------------------------------------------
    # Revenue ledger
    # -----------------------------------------------------------------
    def booking_ledger(self, booking_id: str) -> List[Dict[str, Any]]:
        body = validate_success(
            self.api.list_booking_revenue_entries(booking_id, REVENUE_ACCOUNTANT)
        )
        return body
