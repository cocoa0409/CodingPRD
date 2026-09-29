"""Typed HTTP client: one method per documented endpoint.

Every method returns the raw ``requests.Response`` so that tests choose their
own validator (``validate_success`` / ``validate_error`` / ``validate_paginated``).
"""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


def _clean(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Drop keys whose value is ``None`` so optional fields stay absent."""
    if payload is None:
        return None
    return {k: v for k, v in payload.items() if v is not None}


class ApiClient(GenericApiClient):
    """Convention Center Booking & Event Services API."""

    # ------------------------------------------------------------------
    # Clock
    # ------------------------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def run_hold_sweep(self, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/_ops/hold-sweep", {}, headers)

    # ------------------------------------------------------------------
    # Clients
    # ------------------------------------------------------------------

    def create_client(
        self,
        legal_name: Optional[str] = None,
        contact_email: Optional[str] = None,
        organization_type: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        body = payload if payload is not None else _clean(
            {
                "legal_name": legal_name,
                "contact_email": contact_email,
                "organization_type": organization_type,
            }
        )
        return self._request("POST", f"{API_PREFIX}/clients", body, headers)

    def list_clients(
        self,
        headers: Optional[Dict[str, str]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        organization_type: Optional[str] = None,
        booking_standing: Optional[str] = None,
    ) -> requests.Response:
        params = _clean(
            {
                "limit": limit,
                "offset": offset,
                "organization_type": organization_type,
                "booking_standing": booking_standing,
            }
        )
        return self._request("GET", f"{API_PREFIX}/clients", params, headers)

    def get_client(self, client_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/clients/{client_id}", None, headers)

    def record_deposit(
        self,
        client_id: str,
        amount_cents: Optional[int] = None,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        body = payload if payload is not None else _clean({"amount_cents": amount_cents})
        return self._request("POST", f"{API_PREFIX}/clients/{client_id}/deposits", body, headers)

    # ------------------------------------------------------------------
    # Spaces
    # ------------------------------------------------------------------

    def create_space(
        self,
        name: Optional[str] = None,
        space_class: Optional[str] = None,
        rentable_sqft: Optional[int] = None,
        daily_base_rate_cents: Optional[int] = None,
        parent_space_id: Optional[str] = None,
        rigging_capable: Optional[bool] = None,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        body = payload if payload is not None else _clean(
            {
                "name": name,
                "space_class": space_class,
                "rentable_sqft": rentable_sqft,
                "daily_base_rate_cents": daily_base_rate_cents,
                "parent_space_id": parent_space_id,
                "rigging_capable": rigging_capable,
            }
        )
        return self._request("POST", f"{API_PREFIX}/spaces", body, headers)

    def list_spaces(
        self,
        headers: Optional[Dict[str, str]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        parent_space_id: Optional[str] = None,
        space_class: Optional[str] = None,
    ) -> requests.Response:
        params = _clean(
            {
                "limit": limit,
                "offset": offset,
                "parent_space_id": parent_space_id,
                "space_class": space_class,
            }
        )
        return self._request("GET", f"{API_PREFIX}/spaces", params, headers)

    def get_space(self, space_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/spaces/{space_id}", None, headers)

    # ------------------------------------------------------------------
    # Booking policy windows
    # ------------------------------------------------------------------

    def create_policy_window(
        self,
        event_class: Optional[str] = None,
        priority_rank: Optional[int] = None,
        open_months_before: Optional[int] = None,
        close_months_before: Optional[int] = None,
        max_holds_per_booking: Optional[int] = None,
        challenge_response_hours: Optional[int] = None,
        rental_discount_pct: Optional[float] = None,
        max_challenge_rounds: Optional[int] = None,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        body = payload if payload is not None else _clean(
            {
                "event_class": event_class,
                "priority_rank": priority_rank,
                "open_months_before": open_months_before,
                "close_months_before": close_months_before,
                "max_holds_per_booking": max_holds_per_booking,
                "challenge_response_hours": challenge_response_hours,
                "rental_discount_pct": rental_discount_pct,
                "max_challenge_rounds": max_challenge_rounds,
            }
        )
        return self._request("POST", f"{API_PREFIX}/policy-windows", body, headers)

    def list_policy_windows(
        self,
        headers: Optional[Dict[str, str]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        event_class: Optional[str] = None,
    ) -> requests.Response:
        params = _clean({"limit": limit, "offset": offset, "event_class": event_class})
        return self._request("GET", f"{API_PREFIX}/policy-windows", params, headers)

    def get_policy_window(self, window_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/policy-windows/{window_id}", None, headers)

    # ------------------------------------------------------------------
    # Vendors
    # ------------------------------------------------------------------

    def create_vendor(
        self,
        legal_name: Optional[str] = None,
        service_category: Optional[str] = None,
        vendor_tier: Optional[str] = None,
        coi_expiry_date: Optional[str] = None,
        is_in_house_caterer: Optional[bool] = None,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        body = payload if payload is not None else _clean(
            {
                "legal_name": legal_name,
                "service_category": service_category,
                "vendor_tier": vendor_tier,
                "coi_expiry_date": coi_expiry_date,
                "is_in_house_caterer": is_in_house_caterer,
            }
        )
        return self._request("POST", f"{API_PREFIX}/vendors", body, headers)

    def list_vendors(
        self,
        headers: Optional[Dict[str, str]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        service_category: Optional[str] = None,
        vendor_tier: Optional[str] = None,
    ) -> requests.Response:
        params = _clean(
            {
                "limit": limit,
                "offset": offset,
                "service_category": service_category,
                "vendor_tier": vendor_tier,
            }
        )
        return self._request("GET", f"{API_PREFIX}/vendors", params, headers)

    def get_vendor(self, vendor_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/vendors/{vendor_id}", None, headers)

    # ------------------------------------------------------------------
    # Union jurisdictions
    # ------------------------------------------------------------------

    def create_union_jurisdiction(
        self,
        craft_name: Optional[str] = None,
        covered_category: Optional[str] = None,
        straight_time_rate_cents: Optional[int] = None,
        max_crew_hours_per_day: Optional[float] = None,
        overtime_multiplier: Optional[float] = None,
        min_call_hours: Optional[float] = None,
        st_window_start_hour: Optional[int] = None,
        st_window_end_hour: Optional[int] = None,
        lockout_active: Optional[bool] = None,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        body = payload if payload is not None else _clean(
            {
                "craft_name": craft_name,
                "covered_category": covered_category,
                "straight_time_rate_cents": straight_time_rate_cents,
                "max_crew_hours_per_day": max_crew_hours_per_day,
                "overtime_multiplier": overtime_multiplier,
                "min_call_hours": min_call_hours,
                "st_window_start_hour": st_window_start_hour,
                "st_window_end_hour": st_window_end_hour,
                "lockout_active": lockout_active,
            }
        )
        return self._request("POST", f"{API_PREFIX}/union-jurisdictions", body, headers)

    def list_union_jurisdictions(
        self,
        headers: Optional[Dict[str, str]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        covered_category: Optional[str] = None,
    ) -> requests.Response:
        params = _clean({"limit": limit, "offset": offset, "covered_category": covered_category})
        return self._request("GET", f"{API_PREFIX}/union-jurisdictions", params, headers)

    def get_union_jurisdiction(
        self, jurisdiction_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/union-jurisdictions/{jurisdiction_id}", None, headers)

    def update_union_jurisdiction(
        self,
        jurisdiction_id: str,
        lockout_active: Optional[bool] = None,
        max_crew_hours_per_day: Optional[float] = None,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        body = payload if payload is not None else _clean(
            {"lockout_active": lockout_active, "max_crew_hours_per_day": max_crew_hours_per_day}
        )
        return self._request("PATCH", f"{API_PREFIX}/union-jurisdictions/{jurisdiction_id}", body, headers)

    # ------------------------------------------------------------------
    # Event bookings
    # ------------------------------------------------------------------

    def create_booking(
        self,
        client_id: Optional[str] = None,
        space_id: Optional[str] = None,
        event_name: Optional[str] = None,
        event_class: Optional[str] = None,
        move_in_start_date: Optional[str] = None,
        show_start_date: Optional[str] = None,
        show_end_date: Optional[str] = None,
        move_out_end_date: Optional[str] = None,
        projected_room_nights: Optional[int] = None,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        body = payload if payload is not None else _clean(
            {
                "client_id": client_id,
                "space_id": space_id,
                "event_name": event_name,
                "event_class": event_class,
                "move_in_start_date": move_in_start_date,
                "show_start_date": show_start_date,
                "show_end_date": show_end_date,
                "move_out_end_date": move_out_end_date,
                "projected_room_nights": projected_room_nights,
            }
        )
        return self._request("POST", f"{API_PREFIX}/bookings", body, headers)

    def list_bookings(
        self,
        headers: Optional[Dict[str, str]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        client_id: Optional[str] = None,
        space_id: Optional[str] = None,
        policy_window_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> requests.Response:
        params = _clean(
            {
                "limit": limit,
                "offset": offset,
                "client_id": client_id,
                "space_id": space_id,
                "policy_window_id": policy_window_id,
                "status": status,
            }
        )
        return self._request("GET", f"{API_PREFIX}/bookings", params, headers)

    def get_booking(self, booking_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/bookings/{booking_id}", None, headers)

    def confirm_definite_booking(
        self, booking_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/bookings/{booking_id}/confirm-definite", {}, headers)

    def open_show(self, booking_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/bookings/{booking_id}/open-show", {}, headers)

    def close_booking(self, booking_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/bookings/{booking_id}/close", {}, headers)

    def release_booking(self, booking_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/bookings/{booking_id}/release", {}, headers)

    def cancel_booking(self, booking_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/bookings/{booking_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Space holds
    # ------------------------------------------------------------------

    def create_hold(
        self,
        booking_id: str,
        expected_booking_version: Optional[int] = None,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        body = payload if payload is not None else _clean(
            {"expected_booking_version": expected_booking_version}
        )
        return self._request("POST", f"{API_PREFIX}/bookings/{booking_id}/holds", body, headers)

    def list_holds(
        self,
        headers: Optional[Dict[str, str]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        booking_id: Optional[str] = None,
        challenged_by_hold_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> requests.Response:
        params = _clean(
            {
                "limit": limit,
                "offset": offset,
                "booking_id": booking_id,
                "challenged_by_hold_id": challenged_by_hold_id,
                "status": status,
            }
        )
        return self._request("GET", f"{API_PREFIX}/holds", params, headers)

    def get_hold(self, hold_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/holds/{hold_id}", None, headers)

    def challenge_hold(
        self,
        hold_id: str,
        challenger_hold_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        body = payload if payload is not None else _clean({"challenger_hold_id": challenger_hold_id})
        return self._request("POST", f"{API_PREFIX}/holds/{hold_id}/challenge", body, headers)

    def answer_challenge(self, hold_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/holds/{hold_id}/answer-challenge", {}, headers)

    def confirm_first_option(self, hold_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/holds/{hold_id}/confirm-first-option", {}, headers)

    def release_hold(self, hold_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/holds/{hold_id}/release", {}, headers)

    # ------------------------------------------------------------------
    # License agreements
    # ------------------------------------------------------------------

    def create_license(self, booking_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/bookings/{booking_id}/license", {}, headers)

    def list_licenses(
        self,
        headers: Optional[Dict[str, str]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        booking_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> requests.Response:
        params = _clean({"limit": limit, "offset": offset, "booking_id": booking_id, "status": status})
        return self._request("GET", f"{API_PREFIX}/licenses", params, headers)

    def get_license(self, license_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/licenses/{license_id}", None, headers)

    def issue_license(self, license_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/licenses/{license_id}/issue", {}, headers)

    def countersign_license(self, license_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/licenses/{license_id}/countersign", {}, headers)

    def create_amendment(
        self,
        license_id: str,
        expected_license_version: Optional[int] = None,
        amendment_note: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        body = payload if payload is not None else _clean(
            {"expected_license_version": expected_license_version, "amendment_note": amendment_note}
        )
        return self._request("POST", f"{API_PREFIX}/licenses/{license_id}/amendments", body, headers)

    def accept_amendment(self, license_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/licenses/{license_id}/accept-amendment", {}, headers)

    def terminate_license(self, license_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/licenses/{license_id}/terminate", {}, headers)

    # ------------------------------------------------------------------
    # Service orders
    # ------------------------------------------------------------------

    def create_service_order(
        self,
        booking_id: str,
        vendor_id: Optional[str] = None,
        service_category: Optional[str] = None,
        ordered_quantity: Optional[float] = None,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        body = payload if payload is not None else _clean(
            {
                "vendor_id": vendor_id,
                "service_category": service_category,
                "ordered_quantity": ordered_quantity,
            }
        )
        return self._request("POST", f"{API_PREFIX}/bookings/{booking_id}/service-orders", body, headers)

    def list_service_orders(
        self,
        headers: Optional[Dict[str, str]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        booking_id: Optional[str] = None,
        vendor_id: Optional[str] = None,
        approval_status: Optional[str] = None,
        billing_status: Optional[str] = None,
    ) -> requests.Response:
        params = _clean(
            {
                "limit": limit,
                "offset": offset,
                "booking_id": booking_id,
                "vendor_id": vendor_id,
                "approval_status": approval_status,
                "billing_status": billing_status,
            }
        )
        return self._request("GET", f"{API_PREFIX}/service-orders", params, headers)

    def get_service_order(self, order_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/service-orders/{order_id}", None, headers)

    def approve_service_order(self, order_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/service-orders/{order_id}/approve", {}, headers)

    def reject_service_order(self, order_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/service-orders/{order_id}/reject", {}, headers)

    def cancel_service_order(self, order_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/service-orders/{order_id}/cancel", {}, headers)

    def reconcile_service_order(
        self,
        order_id: str,
        actual_quantity: Optional[float] = None,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        body = payload if payload is not None else _clean({"actual_quantity": actual_quantity})
        return self._request("POST", f"{API_PREFIX}/service-orders/{order_id}/reconcile", body, headers)

    # ------------------------------------------------------------------
    # Labor calls
    # ------------------------------------------------------------------

    def create_labor_call(
        self,
        booking_id: str,
        jurisdiction_id: Optional[str] = None,
        work_category: Optional[str] = None,
        work_date: Optional[str] = None,
        scheduled_start_hour: Optional[float] = None,
        scheduled_end_hour: Optional[float] = None,
        crew_size: Optional[int] = None,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        body = payload if payload is not None else _clean(
            {
                "jurisdiction_id": jurisdiction_id,
                "work_category": work_category,
                "work_date": work_date,
                "scheduled_start_hour": scheduled_start_hour,
                "scheduled_end_hour": scheduled_end_hour,
                "crew_size": crew_size,
            }
        )
        return self._request("POST", f"{API_PREFIX}/bookings/{booking_id}/labor-calls", body, headers)

    def list_labor_calls(
        self,
        headers: Optional[Dict[str, str]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        booking_id: Optional[str] = None,
        jurisdiction_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> requests.Response:
        params = _clean(
            {
                "limit": limit,
                "offset": offset,
                "booking_id": booking_id,
                "jurisdiction_id": jurisdiction_id,
                "status": status,
            }
        )
        return self._request("GET", f"{API_PREFIX}/labor-calls", params, headers)

    def get_labor_call(self, call_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/labor-calls/{call_id}", None, headers)

    def dispatch_labor_call(self, call_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/labor-calls/{call_id}/dispatch", {}, headers)

    def actualize_labor_call(
        self,
        call_id: str,
        actual_start_hour: Optional[float] = None,
        actual_end_hour: Optional[float] = None,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        body = payload if payload is not None else _clean(
            {"actual_start_hour": actual_start_hour, "actual_end_hour": actual_end_hour}
        )
        return self._request("POST", f"{API_PREFIX}/labor-calls/{call_id}/actualize", body, headers)

    def cancel_labor_call(self, call_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/labor-calls/{call_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Catering arrangements
    # ------------------------------------------------------------------

    def create_catering_arrangement(
        self,
        booking_id: str,
        vendor_id: Optional[str] = None,
        arrangement_type: Optional[str] = None,
        estimated_fnb_cents: Optional[int] = None,
        exception_reason: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        body = payload if payload is not None else _clean(
            {
                "vendor_id": vendor_id,
                "arrangement_type": arrangement_type,
                "estimated_fnb_cents": estimated_fnb_cents,
                "exception_reason": exception_reason,
            }
        )
        return self._request(
            "POST", f"{API_PREFIX}/bookings/{booking_id}/catering-arrangements", body, headers
        )

    def list_catering_arrangements(
        self,
        headers: Optional[Dict[str, str]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        booking_id: Optional[str] = None,
        vendor_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> requests.Response:
        params = _clean(
            {
                "limit": limit,
                "offset": offset,
                "booking_id": booking_id,
                "vendor_id": vendor_id,
                "status": status,
            }
        )
        return self._request("GET", f"{API_PREFIX}/catering-arrangements", params, headers)

    def get_catering_arrangement(
        self, arrangement_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/catering-arrangements/{arrangement_id}", None, headers)

    def approve_catering_arrangement(
        self, arrangement_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/catering-arrangements/{arrangement_id}/approve", {}, headers
        )

    def deny_catering_arrangement(
        self, arrangement_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/catering-arrangements/{arrangement_id}/deny", {}, headers
        )

    def update_catering_arrangement(
        self,
        arrangement_id: str,
        actual_fnb_cents: Optional[int] = None,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        body = payload if payload is not None else _clean({"actual_fnb_cents": actual_fnb_cents})
        return self._request("PATCH", f"{API_PREFIX}/catering-arrangements/{arrangement_id}", body, headers)

    # ------------------------------------------------------------------
    # Space usage records
    # ------------------------------------------------------------------

    def create_usage_record(
        self,
        booking_id: str,
        usage_date: Optional[str] = None,
        usage_kind: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        body = payload if payload is not None else _clean(
            {"usage_date": usage_date, "usage_kind": usage_kind}
        )
        return self._request("POST", f"{API_PREFIX}/bookings/{booking_id}/usage-records", body, headers)

    def list_usage_records(
        self,
        headers: Optional[Dict[str, str]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        booking_id: Optional[str] = None,
    ) -> requests.Response:
        params = _clean({"limit": limit, "offset": offset, "booking_id": booking_id})
        return self._request("GET", f"{API_PREFIX}/usage-records", params, headers)

    def list_booking_usage_records(
        self,
        booking_id: str,
        headers: Optional[Dict[str, str]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        params = _clean({"limit": limit, "offset": offset})
        return self._request("GET", f"{API_PREFIX}/bookings/{booking_id}/usage-records", params, headers)

    # ------------------------------------------------------------------
    # Event settlements
    # ------------------------------------------------------------------

    def create_settlement(
        self,
        booking_id: str,
        basis: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        body = payload if payload is not None else _clean({"basis": basis})
        return self._request("POST", f"{API_PREFIX}/bookings/{booking_id}/settlement", body, headers)

    def list_settlements(
        self,
        headers: Optional[Dict[str, str]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        booking_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> requests.Response:
        params = _clean({"limit": limit, "offset": offset, "booking_id": booking_id, "status": status})
        return self._request("GET", f"{API_PREFIX}/settlements", params, headers)

    def get_settlement(self, settlement_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/settlements/{settlement_id}", None, headers)

    def create_settlement_line_item(
        self,
        settlement_id: Optional[str] = None,
        line_kind: Optional[str] = None,
        amount_cents: Optional[int] = None,
        source_ref_id: Optional[str] = None,
        memo: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        body = payload if payload is not None else _clean(
            {
                "settlement_id": settlement_id,
                "line_kind": line_kind,
                "amount_cents": amount_cents,
                "source_ref_id": source_ref_id,
                "memo": memo,
            }
        )
        return self._request("POST", f"{API_PREFIX}/settlement-line-items", body, headers)

    def list_settlement_line_items(
        self,
        headers: Optional[Dict[str, str]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        settlement_id: Optional[str] = None,
        line_kind: Optional[str] = None,
    ) -> requests.Response:
        params = _clean(
            {"limit": limit, "offset": offset, "settlement_id": settlement_id, "line_kind": line_kind}
        )
        return self._request("GET", f"{API_PREFIX}/settlement-line-items", params, headers)

    def list_line_items_for_settlement(
        self,
        settlement_id: str,
        headers: Optional[Dict[str, str]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        params = _clean({"limit": limit, "offset": offset})
        return self._request("GET", f"{API_PREFIX}/settlements/{settlement_id}/line-items", params, headers)

    def issue_settlement(self, settlement_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/settlements/{settlement_id}/issue", {}, headers)

    def dispute_settlement(
        self,
        settlement_id: str,
        dispute_reason: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        body = payload if payload is not None else _clean({"dispute_reason": dispute_reason})
        return self._request("POST", f"{API_PREFIX}/settlements/{settlement_id}/dispute", body, headers)

    def escalate_settlement(self, settlement_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/settlements/{settlement_id}/escalate", {}, headers)

    def finalize_settlement(self, settlement_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/settlements/{settlement_id}/finalize", {}, headers)

    def arbitrate_finalize_settlement(
        self, settlement_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/settlements/{settlement_id}/arbitrate-finalize", {}, headers
        )

    # ------------------------------------------------------------------
    # Maintenance blackouts
    # ------------------------------------------------------------------

    def create_maintenance_blackout(
        self,
        space_id: Optional[str] = None,
        window_start_date: Optional[str] = None,
        window_end_date: Optional[str] = None,
        project_kind: Optional[str] = None,
        buffer_days: Optional[int] = None,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        body = payload if payload is not None else _clean(
            {
                "space_id": space_id,
                "window_start_date": window_start_date,
                "window_end_date": window_end_date,
                "project_kind": project_kind,
                "buffer_days": buffer_days,
            }
        )
        return self._request("POST", f"{API_PREFIX}/maintenance-blackouts", body, headers)

    def list_maintenance_blackouts(
        self,
        headers: Optional[Dict[str, str]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        space_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> requests.Response:
        params = _clean({"limit": limit, "offset": offset, "space_id": space_id, "status": status})
        return self._request("GET", f"{API_PREFIX}/maintenance-blackouts", params, headers)

    def get_maintenance_blackout(
        self, blackout_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/maintenance-blackouts/{blackout_id}", None, headers)

    def approve_maintenance_blackout(
        self, blackout_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/maintenance-blackouts/{blackout_id}/approve", {}, headers
        )

    def defer_maintenance_blackout(
        self, blackout_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/maintenance-blackouts/{blackout_id}/defer", {}, headers)


api_client = ApiClient()
