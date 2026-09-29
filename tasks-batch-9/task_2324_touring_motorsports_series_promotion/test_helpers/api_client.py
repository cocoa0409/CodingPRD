"""HTTP client with one method per documented endpoint.

Every method takes the request payload or query filters explicitly and threads
the caller's headers through untouched, so that role and identity are always
decided by the test rather than by this module.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed access to the touring series promotion API."""

    # -----------------------------------------------------------------
    # Logical clock
    # -----------------------------------------------------------------

    def set_clock(
        self, to_iso8601: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Set the server's logical clock to ``to_iso8601``."""
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers=headers,
        )

    # -----------------------------------------------------------------
    # Seasons
    # -----------------------------------------------------------------

    def create_season(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Create a season with its calendar window, cooldown and budget."""
        return self._request("POST", "/seasons", payload, headers=headers)

    def get_season(
        self, season_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Read one season including its marketing ledger and counters."""
        return self._request("GET", f"/seasons/{season_id}", headers=headers)

    def get_season_market_report(
        self, season_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Profitability by market across the season's approved settlements."""
        return self._request(
            "GET", f"/seasons/{season_id}/market-report", headers=headers
        )

    # -----------------------------------------------------------------
    # Venues
    # -----------------------------------------------------------------

    def create_venue(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Register a building with its capacity, floor, bays and turnaround."""
        return self._request("POST", "/venues", payload, headers=headers)

    def get_venue(
        self, venue_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Read one venue."""
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    # -----------------------------------------------------------------
    # Venue bookings
    # -----------------------------------------------------------------

    def create_venue_booking(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Propose rental terms for a date at a venue."""
        return self._request("POST", "/venue-bookings", payload, headers=headers)

    def list_venue_bookings(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """List bookings, filterable by season, venue and state."""
        return self._request("GET", "/venue-bookings", params, headers=headers)

    def get_venue_booking(
        self, booking_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Read one booking with the terms currently on the row."""
        return self._request("GET", f"/venue-bookings/{booking_id}", headers=headers)

    def counter_venue_booking(
        self,
        booking_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Venue counters the terms on the booking."""
        return self._request(
            "POST", f"/venue-bookings/{booking_id}/counter", payload, headers=headers
        )

    def revise_venue_booking(
        self,
        booking_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Promoter re-proposes terms after a counter."""
        return self._request(
            "POST", f"/venue-bookings/{booking_id}/revise", payload, headers=headers
        )

    def accept_venue_booking(
        self,
        booking_id: str,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """Accept the terms on the row and synthesize the tour stop."""
        return self._request(
            "POST", f"/venue-bookings/{booking_id}/accept", payload or {}, headers=headers
        )

    def withdraw_venue_booking(
        self,
        booking_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Withdraw the booking, tearing down anything it produced."""
        return self._request(
            "POST", f"/venue-bookings/{booking_id}/withdraw", payload, headers=headers
        )

    # -----------------------------------------------------------------
    # Tour stops
    # -----------------------------------------------------------------

    def list_tour_stops(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """List stops, filterable by season, booking, predecessor, market, state."""
        return self._request("GET", "/tour-stops", params, headers=headers)

    def get_tour_stop(
        self, stop_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Read one stop with both state dimensions, posture and roll-ups."""
        return self._request("GET", f"/tour-stops/{stop_id}", headers=headers)

    def update_tour_stop_logistics(
        self,
        stop_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Set show timing, pit party terms and the transport chain link."""
        return self._request(
            "PATCH", f"/tour-stops/{stop_id}/logistics", payload, headers=headers
        )

    def open_tour_stop_sales(
        self,
        stop_id: str,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """Open ticket sales on the stop."""
        return self._request(
            "POST", f"/tour-stops/{stop_id}/on-sale", payload or {}, headers=headers
        )

    def close_tour_stop_sales(
        self,
        stop_id: str,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """Close ticket sales ahead of settlement."""
        return self._request(
            "POST", f"/tour-stops/{stop_id}/close-sales", payload or {}, headers=headers
        )

    def resume_tour_stop_sales(
        self,
        stop_id: str,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """Return a halted stop to sale."""
        return self._request(
            "POST", f"/tour-stops/{stop_id}/resume-sales", payload or {}, headers=headers
        )

    def safety_suspend_tour_stop(
        self,
        stop_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Suspend the stop on safety grounds."""
        return self._request(
            "POST", f"/tour-stops/{stop_id}/safety-suspend", payload, headers=headers
        )

    def safety_reinstate_tour_stop(
        self,
        stop_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Lift a safety suspension on the stop."""
        return self._request(
            "POST",
            f"/tour-stops/{stop_id}/safety-reinstate",
            payload or {},
            headers=headers,
        )

    # -----------------------------------------------------------------
    # Competitors
    # -----------------------------------------------------------------

    def create_competitor(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Register a competing team."""
        return self._request("POST", "/competitors", payload, headers=headers)

    def get_competitor(
        self, competitor_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Read one competitor."""
        return self._request("GET", f"/competitors/{competitor_id}", headers=headers)

    # -----------------------------------------------------------------
    # Vehicle entries
    # -----------------------------------------------------------------

    def create_vehicle_entry(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Enter a vehicle in a stop and assign its staging bay."""
        return self._request("POST", "/vehicle-entries", payload, headers=headers)

    def list_vehicle_entries(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """List entries, filterable by stop, competitor and logistics state."""
        return self._request("GET", "/vehicle-entries", params, headers=headers)

    def get_vehicle_entry(
        self, entry_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Read one entry with its bay, tech status and readiness score."""
        return self._request("GET", f"/vehicle-entries/{entry_id}", headers=headers)

    def check_in_vehicle_entry(
        self,
        entry_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Record the transporter's arrival at the staging bay."""
        return self._request(
            "POST", f"/vehicle-entries/{entry_id}/check-in", payload or {}, headers=headers
        )

    def create_tech_inspection(
        self,
        entry_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """File one technical inspection attempt against the entry."""
        return self._request(
            "POST",
            f"/vehicle-entries/{entry_id}/tech-inspections",
            payload,
            headers=headers,
        )

    def list_tech_inspections(
        self,
        entry_id: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Full inspection history of an entry."""
        return self._request(
            "GET", f"/vehicle-entries/{entry_id}/tech-inspections", params, headers=headers
        )

    def get_tech_inspection(
        self, inspection_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Read one filed inspection attempt."""
        return self._request(
            "GET", f"/tech-inspections/{inspection_id}", headers=headers
        )

    def list_featured_segments(
        self,
        entry_id: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Run-order segments that headline this entry."""
        return self._request(
            "GET", f"/vehicle-entries/{entry_id}/featured-segments", params, headers=headers
        )

    # -----------------------------------------------------------------
    # Show segments
    # -----------------------------------------------------------------

    def create_show_segment(
        self,
        stop_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Insert a competition or intermission segment into the run order."""
        return self._request(
            "POST", f"/tour-stops/{stop_id}/show-segments", payload, headers=headers
        )

    def list_show_segments(
        self,
        stop_id: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Run order of the stop."""
        return self._request(
            "GET", f"/tour-stops/{stop_id}/show-segments", params, headers=headers
        )

    def get_show_segment(
        self, segment_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Read one segment with its computed timeline offsets."""
        return self._request("GET", f"/show-segments/{segment_id}", headers=headers)

    # -----------------------------------------------------------------
    # Ticket tiers
    # -----------------------------------------------------------------

    def create_ticket_tier(
        self,
        stop_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Add a pricing tier to the stop."""
        return self._request(
            "POST", f"/tour-stops/{stop_id}/ticket-tiers", payload, headers=headers
        )

    def list_ticket_tiers(
        self,
        stop_id: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Tiers of the stop."""
        return self._request(
            "GET", f"/tour-stops/{stop_id}/ticket-tiers", params, headers=headers
        )

    def get_ticket_tier(
        self, tier_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Read one tier with its conserved seat pool."""
        return self._request("GET", f"/ticket-tiers/{tier_id}", headers=headers)

    # -----------------------------------------------------------------
    # Ticket orders
    # -----------------------------------------------------------------

    def create_ticket_order(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Place an order against a tier, carrying the expected tier version."""
        return self._request("POST", "/ticket-orders", payload, headers=headers)

    def list_ticket_orders(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """List orders, filterable by stop, tier and status."""
        return self._request("GET", "/ticket-orders", params, headers=headers)

    def get_ticket_order(
        self, order_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Read one order with its frozen money breakdown."""
        return self._request("GET", f"/ticket-orders/{order_id}", headers=headers)

    def pay_ticket_order(
        self,
        order_id: str,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """Settle a pending order."""
        return self._request(
            "POST", f"/ticket-orders/{order_id}/pay", payload or {}, headers=headers
        )

    def refund_ticket_order(
        self,
        order_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Refund a paid order."""
        return self._request(
            "POST", f"/ticket-orders/{order_id}/refund", payload, headers=headers
        )

    # -----------------------------------------------------------------
    # Sponsors
    # -----------------------------------------------------------------

    def create_sponsor(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Register a sponsor and its category exclusivity claim."""
        return self._request("POST", "/sponsors", payload, headers=headers)

    def get_sponsor(
        self, sponsor_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Read one sponsor."""
        return self._request("GET", f"/sponsors/{sponsor_id}", headers=headers)

    # -----------------------------------------------------------------
    # Sponsorship activations
    # -----------------------------------------------------------------

    def create_sponsorship_activation(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Propose an activation package."""
        return self._request(
            "POST", "/sponsorship-activations", payload, headers=headers
        )

    def list_sponsorship_activations(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """List activations, filterable by sponsor, stop, tier, entry and state."""
        return self._request("GET", "/sponsorship-activations", params, headers=headers)

    def get_sponsorship_activation(
        self, activation_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Read one activation."""
        return self._request(
            "GET", f"/sponsorship-activations/{activation_id}", headers=headers
        )

    def activate_sponsorship_activation(
        self,
        activation_id: str,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """Activate the package."""
        return self._request(
            "POST",
            f"/sponsorship-activations/{activation_id}/activate",
            payload or {},
            headers=headers,
        )

    def fulfill_sponsorship_activation(
        self,
        activation_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Sign off that the activation's obligations were delivered."""
        return self._request(
            "POST",
            f"/sponsorship-activations/{activation_id}/fulfill",
            payload or {},
            headers=headers,
        )

    # -----------------------------------------------------------------
    # Safety plans
    # -----------------------------------------------------------------

    def create_safety_plan(
        self,
        stop_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Create the stop's single safety plan."""
        return self._request(
            "POST", f"/tour-stops/{stop_id}/safety-plan", payload, headers=headers
        )

    def get_tour_stop_safety_plan(
        self, stop_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """The stop's safety plan as an array of length 0 or 1."""
        return self._request("GET", f"/tour-stops/{stop_id}/safety-plan", headers=headers)

    def get_safety_plan(
        self, plan_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Read one plan with provisioned and required figures side by side."""
        return self._request("GET", f"/safety-plans/{plan_id}", headers=headers)

    def update_safety_plan(
        self,
        plan_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Revise a plan's provisioning."""
        return self._request(
            "PATCH", f"/safety-plans/{plan_id}", payload, headers=headers
        )

    def submit_safety_plan(
        self,
        plan_id: str,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """Submit the plan for certification."""
        return self._request(
            "POST", f"/safety-plans/{plan_id}/submit", payload or {}, headers=headers
        )

    def certify_safety_plan(
        self,
        plan_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Certify a submitted plan; the caller may not be its author."""
        return self._request(
            "POST", f"/safety-plans/{plan_id}/certify", payload or {}, headers=headers
        )

    def return_safety_plan(
        self,
        plan_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Return a submitted plan for rework."""
        return self._request(
            "POST", f"/safety-plans/{plan_id}/return", payload, headers=headers
        )

    # -----------------------------------------------------------------
    # Marketing allocations
    # -----------------------------------------------------------------

    def create_marketing_allocation(
        self,
        stop_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Commit local marketing spend on one channel for the stop."""
        return self._request(
            "POST",
            f"/tour-stops/{stop_id}/marketing-allocations",
            payload,
            headers=headers,
        )

    def list_marketing_allocations(
        self,
        stop_id: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Allocations of the stop."""
        return self._request(
            "GET", f"/tour-stops/{stop_id}/marketing-allocations", params, headers=headers
        )

    def get_marketing_allocation(
        self, allocation_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Read one allocation."""
        return self._request(
            "GET", f"/marketing-allocations/{allocation_id}", headers=headers
        )

    def release_marketing_allocation(
        self, allocation_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Release a committed allocation back to the season pool."""
        return self._request(
            "DELETE", f"/marketing-allocations/{allocation_id}", headers=headers
        )

    # -----------------------------------------------------------------
    # Settlements
    # -----------------------------------------------------------------

    def create_settlement(
        self,
        stop_id: str,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """Prepare the stop's settlement under the provisional variant."""
        return self._request(
            "POST", f"/tour-stops/{stop_id}/settlement", payload or {}, headers=headers
        )

    def get_tour_stop_settlement(
        self, stop_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """The stop's settlement as an array of length 0 or 1."""
        return self._request("GET", f"/tour-stops/{stop_id}/settlement", headers=headers)

    def get_settlement(
        self, settlement_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Read one settlement with its variant, waterfall buckets and margin."""
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def approve_settlement(
        self,
        settlement_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Approve the settlement under the final variant."""
        return self._request(
            "POST", f"/settlements/{settlement_id}/approve", payload or {}, headers=headers
        )

    def dispute_settlement(
        self,
        settlement_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Dispute a prepared settlement."""
        return self._request(
            "POST", f"/settlements/{settlement_id}/dispute", payload, headers=headers
        )


#: Shared client instance used by the pytest fixtures.
api_client = ApiClient()
