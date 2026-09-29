"""
One method per endpoint of §4's table.

Every path is rooted at the server origin: "Every path is rooted at the server
origin with no version or namespace prefix."  Methods return the raw
requests.Response so a test can assert the status code itself.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed surface over the 50 endpoints of the Trade Show Exhibitor Sales API."""

    # ── Logical clock (§2.4) ─────────────────────────────────────────────────
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Venue contracts (§3.1) ──────────────────────────────────────────────
    def create_venue_contract(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/venue-contracts", payload, headers)

    def execute_venue_contract(self, vc_id: str, headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/venue-contracts/{vc_id}/execute", payload or {}, headers
        )

    def terminate_venue_contract(self, vc_id: str, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/venue-contracts/{vc_id}/terminate", payload, headers
        )

    def get_venue_contract(self, vc_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/venue-contracts/{vc_id}", None, headers)

    def list_venue_contract_shows(self, vc_id: str, headers: Dict[str, str],
                                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/venue-contracts/{vc_id}/shows", params, headers
        )

    # ── Shows (§3.1, §3.2, §3.4, §3.9) ──────────────────────────────────────
    def create_show(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/shows", payload, headers)

    def get_show(self, show_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/shows/{show_id}", None, headers)

    def publish_floor_plan(self, show_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/shows/{show_id}/publish-floor-plan", payload or {}, headers
        )

    def transition_show(self, show_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", f"/shows/{show_id}/transition", payload, headers)

    def advance_selection_round(self, show_id: str, headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/shows/{show_id}/advance-selection-round", payload or {}, headers
        )

    def get_post_show_report(self, show_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/shows/{show_id}/post-show-report", None, headers)

    # ── Booths (§3.2) ───────────────────────────────────────────────────────
    def create_booth(self, show_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", f"/shows/{show_id}/booths", payload, headers)

    def get_booth(self, booth_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/booths/{booth_id}", None, headers)

    def list_booths(self, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/booths", params, headers)

    def combine_booths(self, booth_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", f"/booths/{booth_id}/combine", payload, headers)

    # ── Exhibitors (§3.3) ───────────────────────────────────────────────────
    def create_exhibitor(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/exhibitors", payload, headers)

    def get_exhibitor(self, exhibitor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/exhibitors/{exhibitor_id}", None, headers)

    def adjust_priority_points(self, exhibitor_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/exhibitors/{exhibitor_id}/priority-point-adjustments",
            payload, headers,
        )

    def reinstate_exhibitor(self, exhibitor_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/exhibitors/{exhibitor_id}/reinstate", payload, headers
        )

    # ── Selection appointments (§3.4) ───────────────────────────────────────
    def create_selection_appointment(self, show_id: str, payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/shows/{show_id}/selection-appointments", payload, headers
        )

    def get_selection_appointment(self, appointment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/selection-appointments/{appointment_id}", None, headers
        )

    def list_selection_appointments(self, headers: Dict[str, str],
                                    params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/selection-appointments", params, headers)

    def exercise_appointment(self, appointment_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/selection-appointments/{appointment_id}/exercise",
            payload, headers,
        )

    # ── Space contracts (§3.5, §3.6, §3.9) ──────────────────────────────────
    def create_space_contract(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/space-contracts", payload, headers)

    def get_space_contract(self, sc_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/space-contracts/{sc_id}", None, headers)

    def list_space_contracts(self, headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/space-contracts", params, headers)

    def negotiate(self, sc_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/space-contracts/{sc_id}/negotiate", payload, headers
        )

    def sign_space_contract(self, sc_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", f"/space-contracts/{sc_id}/sign", payload, headers)

    def post_deposit(self, sc_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/space-contracts/{sc_id}/deposits", payload, headers
        )

    def cancel_space_contract(self, sc_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/space-contracts/{sc_id}/cancel", payload, headers
        )

    def rebook(self, sc_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/space-contracts/{sc_id}/rebook", payload, headers
        )

    # ── Service orders (§3.9) ───────────────────────────────────────────────
    def create_service_order(self, sc_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/space-contracts/{sc_id}/service-orders", payload, headers
        )

    def list_service_orders(self, sc_id: str, headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/space-contracts/{sc_id}/service-orders", params, headers
        )

    # ── Rule violations (§3.9) ──────────────────────────────────────────────
    def create_rule_violation(self, sc_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/space-contracts/{sc_id}/rule-violations", payload, headers
        )

    def list_rule_violations(self, sc_id: str, headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/space-contracts/{sc_id}/rule-violations", params, headers
        )

    def adjudicate(self, rv_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/rule-violations/{rv_id}/adjudicate", payload, headers
        )

    # ── Lead scans (§3.8) ───────────────────────────────────────────────────
    def create_lead_scan(self, sc_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/space-contracts/{sc_id}/lead-scans", payload, headers
        )

    def list_contract_lead_scans(self, sc_id: str, headers: Dict[str, str],
                                 params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/space-contracts/{sc_id}/lead-scans", params, headers
        )

    def list_registration_lead_scans(self, registration_id: str,
                                     headers: Dict[str, str],
                                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/registrations/{registration_id}/lead-scans", params, headers
        )

    # ── Sponsorship (§3.7) ──────────────────────────────────────────────────
    def create_sponsorship_package(self, show_id: str, payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/shows/{show_id}/sponsorship-packages", payload, headers
        )

    def list_sponsorship_packages(self, show_id: str, headers: Dict[str, str],
                                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/shows/{show_id}/sponsorship-packages", params, headers
        )

    def create_sponsorship_deal(self, package_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/sponsorship-packages/{package_id}/deals", payload, headers
        )

    def get_sponsorship_deal(self, deal_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/sponsorship-deals/{deal_id}", None, headers)

    def list_sponsorship_deals(self, headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/sponsorship-deals", params, headers)

    def sign_sponsorship_deal(self, deal_id: str, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/sponsorship-deals/{deal_id}/sign", payload or {}, headers
        )

    def cancel_sponsorship_deal(self, deal_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/sponsorship-deals/{deal_id}/cancel", payload, headers
        )

    def list_obligations(self, deal_id: str, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/sponsorship-deals/{deal_id}/obligations", params, headers
        )

    def resolve_obligation(self, deal_id: str, obligation_id: str,
                           payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/sponsorship-deals/{deal_id}/obligations/{obligation_id}/resolve",
            payload, headers,
        )

    # ── Registrations (§3.8) ────────────────────────────────────────────────
    def create_registration(self, show_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/shows/{show_id}/registrations", payload, headers
        )

    def get_registration(self, registration_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/registrations/{registration_id}", None, headers)

    def list_registrations(self, show_id: str, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/shows/{show_id}/registrations", params, headers
        )

    def screen_registration(self, registration_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/registrations/{registration_id}/screen", payload, headers
        )
