"""API client: one method per endpoint defined in the PRD (§4)."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Productions ---
    def create_production(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/productions", payload, headers)

    def get_production(self, production_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/productions/{production_id}", headers=headers)

    def list_productions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/productions", headers=headers, params=params)

    def lock_baseline(self, production_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/productions/{production_id}/lock-baseline",
                             payload or {}, headers)

    def begin_wrap(self, production_id: str, headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/productions/{production_id}/begin-wrap",
                             payload or {}, headers)

    def close_account(self, production_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/productions/{production_id}/close-account",
                             payload or {}, headers)

    def cancel_production(self, production_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/productions/{production_id}/cancel",
                             payload or {}, headers)

    def get_wrap_preview(self, production_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/productions/{production_id}/wrap-preview",
                             headers=headers)

    # --- Scenes ---
    def create_scene(self, production_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", f"/productions/{production_id}/scenes",
                             payload, headers)

    def list_scenes(self, production_id: str, headers: Dict[str, str],
                    params: Optional[Dict] = None):
        return self._request("GET", f"/productions/{production_id}/scenes",
                             headers=headers, params=params)

    def schedule_scene(self, production_id: str, scene_id: str,
                       payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/productions/{production_id}/scenes/{scene_id}/schedule",
            payload, headers,
        )

    def mark_weather_blocked(self, production_id: str, scene_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/productions/{production_id}/scenes/{scene_id}/mark-weather-blocked",
            payload or {}, headers,
        )

    def reschedule_scene(self, production_id: str, scene_id: str,
                          payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/productions/{production_id}/scenes/{scene_id}/reschedule",
            payload, headers,
        )

    def mark_shot(self, production_id: str, scene_id: str,
                   headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/productions/{production_id}/scenes/{scene_id}/mark-shot",
            payload or {}, headers,
        )

    def omit_scene(self, production_id: str, scene_id: str,
                    headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/productions/{production_id}/scenes/{scene_id}/omit",
            payload or {}, headers,
        )

    # --- Roles & Casting ---
    def create_role(self, production_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", f"/productions/{production_id}/roles",
                             payload, headers)

    def create_audition(self, production_id: str, role_id: str,
                         payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/productions/{production_id}/roles/{role_id}/auditions",
            payload, headers,
        )

    def list_auditions(self, production_id: str, role_id: str,
                        headers: Dict[str, str],
                        params: Optional[Dict] = None):
        return self._request(
            "GET",
            f"/productions/{production_id}/roles/{role_id}/auditions",
            headers=headers, params=params,
        )

    def shortlist_role(self, production_id: str, role_id: str,
                        headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/productions/{production_id}/roles/{role_id}/shortlist",
            payload or {}, headers,
        )

    def reopen_auditions(self, production_id: str, role_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/productions/{production_id}/roles/{role_id}/reopen-auditions",
            payload or {}, headers,
        )

    def offer_role(self, production_id: str, role_id: str,
                    payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/productions/{production_id}/roles/{role_id}/offer",
            payload, headers,
        )

    def sign_role(self, production_id: str, role_id: str,
                   headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/productions/{production_id}/roles/{role_id}/sign",
            payload or {}, headers,
        )

    def recast_role(self, production_id: str, role_id: str,
                     headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/productions/{production_id}/roles/{role_id}/recast",
            payload or {}, headers,
        )

    def substitute_role(self, production_id: str, role_id: str,
                         payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/productions/{production_id}/roles/{role_id}/substitute",
            payload, headers,
        )

    # --- Actors ---
    def create_actor(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/actors", payload, headers)

    def get_actor(self, actor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/actors/{actor_id}", headers=headers)

    # --- Locations & reservations ---
    def create_location(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/locations", payload, headers)

    def create_location_reservation(self, payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request("POST", "/location-reservations", payload, headers)

    def confirm_reservation(self, reservation_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request("POST",
                             f"/location-reservations/{reservation_id}/confirm",
                             payload or {}, headers)

    def release_reservation(self, reservation_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request("POST",
                             f"/location-reservations/{reservation_id}/release",
                             payload or {}, headers)

    def patch_permit_status(self, reservation_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request("PATCH",
                             f"/location-reservations/{reservation_id}/permit-status",
                             payload, headers)

    def patch_weather_status(self, reservation_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("PATCH",
                             f"/location-reservations/{reservation_id}/weather-status",
                             payload, headers)

    # --- Budget ---
    def create_budget_category(self, production_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST",
                             f"/productions/{production_id}/budget-categories",
                             payload, headers)

    def list_budget_categories(self, production_id: str, headers: Dict[str, str],
                                params: Optional[Dict] = None):
        return self._request("GET",
                             f"/productions/{production_id}/budget-categories",
                             headers=headers, params=params)

    def create_change_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/change-orders", payload, headers)

    def approve_change_order(self, change_order_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request("POST",
                             f"/change-orders/{change_order_id}/approve",
                             payload or {}, headers)

    def reject_change_order(self, change_order_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request("POST",
                             f"/change-orders/{change_order_id}/reject",
                             payload or {}, headers)

    def cancel_change_order(self, change_order_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request("POST",
                             f"/change-orders/{change_order_id}/cancel",
                             payload or {}, headers)

    # --- Equipment ---
    def create_equipment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/equipment", payload, headers)

    def list_equipment(self, headers: Dict[str, str],
                        params: Optional[Dict] = None):
        return self._request("GET", "/equipment", headers=headers, params=params)

    def create_equipment_event(self, equipment_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST", f"/equipment/{equipment_id}/events",
                             payload, headers)

    def decommission_equipment(self, equipment_id: str,
                                headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/equipment/{equipment_id}/decommission",
                             payload or {}, headers)

    # --- Crew & Vendor ---
    def create_crew_assignment(self, production_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST",
                             f"/productions/{production_id}/crew-assignments",
                             payload, headers)

    def patch_actual_days(self, production_id: str, crew_assignment_id: str,
                           payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/productions/{production_id}/crew-assignments/{crew_assignment_id}/actual-days",
            payload, headers,
        )

    def create_vendor_invoice(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/vendor-invoices", payload, headers)

    def reconcile_invoice(self, invoice_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/vendor-invoices/{invoice_id}/reconcile",
                             payload or {}, headers)

    def pay_invoice(self, invoice_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/vendor-invoices/{invoice_id}/pay",
                             payload or {}, headers)

    def dispute_invoice(self, invoice_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/vendor-invoices/{invoice_id}/dispute",
                             payload or {}, headers)

    # --- Audit log ---
    def list_audit_logs(self, production_id: str, headers: Dict[str, str],
                         params: Optional[Dict] = None):
        return self._request("GET",
                             f"/productions/{production_id}/audit-logs",
                             headers=headers, params=params)

    # --- Test-driving endpoints ---
    def advance_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def emit_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_events/emit", payload, headers)


api_client = ApiClient()
