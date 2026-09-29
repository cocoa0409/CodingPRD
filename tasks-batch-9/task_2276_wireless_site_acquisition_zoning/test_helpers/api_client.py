"""HTTP client covering every endpoint declared by the PRD.

All endpoints live at the service root. Creates answer `201`; every other
successful call answers `200`. Reads take their filters as query parameters and
writes take their payload as a JSON body, which is what the underlying
transport already does per HTTP method.
"""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .test_users import (
    make_program_director_headers,
)

Headers = Optional[Dict[str, str]]
Payload = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """Thin, explicit wrapper: one method per PRD endpoint."""

    # -- raw escape hatch --------------------------------------------------
    def request(
        self,
        method: str,
        path: str,
        payload: Payload = None,
        headers: Headers = None,
    ) -> requests.Response:
        return self._request(method, path, payload=payload, headers=headers)

    def patch(
        self, path: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("PATCH", path, payload=payload, headers=headers)

    # The framework's convenience helpers name the body ``json`` and the query
    # string ``params``; every method below speaks ``payload`` for both, so the
    # two verbs are re-declared here rather than at each of the call sites.
    def post(
        self, path: str, payload: Payload = None, headers: Headers = None, **_: Any
    ) -> requests.Response:
        return self._request("POST", path, payload=payload, headers=headers)

    def get(
        self,
        path: str,
        payload: Payload = None,
        headers: Headers = None,
        params: Payload = None,
        **_: Any,
    ) -> requests.Response:
        return self._request(
            "GET", path, payload=payload if payload is not None else params, headers=headers
        )

    # =====================================================================
    # Logical clock
    # =====================================================================
    def set_clock(self, to_iso8601: str, headers: Headers = None) -> requests.Response:
        return self.post(
            "/_clock/set_current_utc",
            payload={"to_iso8601": to_iso8601},
            headers=headers if headers is not None else make_program_director_headers(),
        )

    # =====================================================================
    # Search rings
    # =====================================================================
    def create_search_ring(self, payload: Payload, headers: Headers = None):
        return self.post("/search-rings", payload=payload, headers=headers)

    def list_search_rings(self, params: Payload = None, headers: Headers = None):
        return self.get("/search-rings", payload=params, headers=headers)

    def get_search_ring(self, ring_id: str, headers: Headers = None):
        return self.get(f"/search-rings/{ring_id}", headers=headers)

    def open_search_ring(self, ring_id: str, headers: Headers = None):
        return self.post(f"/search-rings/{ring_id}/open", payload={}, headers=headers)

    def select_site(self, ring_id: str, payload: Payload, headers: Headers = None):
        return self.post(
            f"/search-rings/{ring_id}/select-site", payload=payload, headers=headers
        )

    def reopen_search_ring(self, ring_id: str, payload: Payload, headers: Headers = None):
        return self.post(
            f"/search-rings/{ring_id}/reopen", payload=payload, headers=headers
        )

    # =====================================================================
    # Landlords
    # =====================================================================
    def create_landlord(self, payload: Payload, headers: Headers = None):
        return self.post("/landlords", payload=payload, headers=headers)

    def list_landlords(self, params: Payload = None, headers: Headers = None):
        return self.get("/landlords", payload=params, headers=headers)

    def get_landlord(self, landlord_id: str, headers: Headers = None):
        return self.get(f"/landlords/{landlord_id}", headers=headers)

    def set_landlord_standing(
        self, landlord_id: str, payload: Payload, headers: Headers = None
    ):
        return self.post(
            f"/landlords/{landlord_id}/standing", payload=payload, headers=headers
        )

    # =====================================================================
    # Jurisdictions
    # =====================================================================
    def create_jurisdiction(self, payload: Payload, headers: Headers = None):
        return self.post("/jurisdictions", payload=payload, headers=headers)

    def list_jurisdictions(self, params: Payload = None, headers: Headers = None):
        return self.get("/jurisdictions", payload=params, headers=headers)

    def get_jurisdiction(self, jurisdiction_id: str, headers: Headers = None):
        return self.get(f"/jurisdictions/{jurisdiction_id}", headers=headers)

    # =====================================================================
    # Candidates
    # =====================================================================
    def create_candidate(self, payload: Payload, headers: Headers = None):
        return self.post("/candidates", payload=payload, headers=headers)

    def list_candidates(self, params: Payload = None, headers: Headers = None):
        return self.get("/candidates", payload=params, headers=headers)

    def get_candidate(self, candidate_id: str, headers: Headers = None):
        return self.get(f"/candidates/{candidate_id}", headers=headers)

    def patch_candidate(
        self, candidate_id: str, payload: Payload, headers: Headers = None
    ):
        return self.patch(f"/candidates/{candidate_id}", payload=payload, headers=headers)

    def add_outreach_event(
        self, candidate_id: str, payload: Payload, headers: Headers = None
    ):
        return self.post(
            f"/candidates/{candidate_id}/outreach-events",
            payload=payload,
            headers=headers,
        )

    def rf_qualify(self, candidate_id: str, headers: Headers = None):
        return self.post(
            f"/candidates/{candidate_id}/rf-qualify", payload={}, headers=headers
        )

    def mark_build_ready(self, candidate_id: str, headers: Headers = None):
        return self.post(
            f"/candidates/{candidate_id}/mark-build-ready", payload={}, headers=headers
        )

    # =====================================================================
    # Lease agreements
    # =====================================================================
    def create_lease(self, payload: Payload, headers: Headers = None):
        return self.post("/leases", payload=payload, headers=headers)

    def list_leases(self, params: Payload = None, headers: Headers = None):
        return self.get("/leases", payload=params, headers=headers)

    def get_lease(self, lease_id: str, headers: Headers = None):
        return self.get(f"/leases/{lease_id}", headers=headers)

    def add_lease_round(self, lease_id: str, payload: Payload, headers: Headers = None):
        return self.post(f"/leases/{lease_id}/rounds", payload=payload, headers=headers)

    def execute_lease(self, lease_id: str, payload: Payload, headers: Headers = None):
        return self.post(f"/leases/{lease_id}/execute", payload=payload, headers=headers)

    def terminate_lease(self, lease_id: str, payload: Payload, headers: Headers = None):
        return self.post(
            f"/leases/{lease_id}/terminate", payload=payload, headers=headers
        )

    def get_rent_schedule(self, lease_id: str, headers: Headers = None):
        return self.get(f"/leases/{lease_id}/rent-schedule", headers=headers)

    # =====================================================================
    # Zoning applications
    # =====================================================================
    def create_zoning_application(self, payload: Payload, headers: Headers = None):
        return self.post("/zoning-applications", payload=payload, headers=headers)

    def list_zoning_applications(self, params: Payload = None, headers: Headers = None):
        return self.get("/zoning-applications", payload=params, headers=headers)

    def get_zoning_application(self, za_id: str, headers: Headers = None):
        return self.get(f"/zoning-applications/{za_id}", headers=headers)

    def add_visual_simulation(self, za_id: str, payload: Payload, headers: Headers = None):
        return self.post(
            f"/zoning-applications/{za_id}/visual-simulations",
            payload=payload,
            headers=headers,
        )

    def submit_zoning_application(self, za_id: str, headers: Headers = None):
        return self.post(
            f"/zoning-applications/{za_id}/submit", payload={}, headers=headers
        )

    def set_completeness(self, za_id: str, payload: Payload, headers: Headers = None):
        return self.post(
            f"/zoning-applications/{za_id}/completeness", payload=payload, headers=headers
        )

    def hearing_action(self, za_id: str, payload: Payload, headers: Headers = None):
        return self.post(
            f"/zoning-applications/{za_id}/hearings", payload=payload, headers=headers
        )

    def decide_zoning_application(
        self, za_id: str, payload: Payload, headers: Headers = None
    ):
        return self.post(
            f"/zoning-applications/{za_id}/decide", payload=payload, headers=headers
        )

    def deem_granted(self, za_id: str, headers: Headers = None):
        return self.post(
            f"/zoning-applications/{za_id}/deem-granted", payload={}, headers=headers
        )

    def get_shot_clock(self, za_id: str, headers: Headers = None):
        return self.get(f"/zoning-applications/{za_id}/shot-clock", headers=headers)

    # =====================================================================
    # Structural analyses
    # =====================================================================
    def create_structural_analysis(self, payload: Payload, headers: Headers = None):
        return self.post("/structural-analyses", payload=payload, headers=headers)

    def list_structural_analyses(self, params: Payload = None, headers: Headers = None):
        return self.get("/structural-analyses", payload=params, headers=headers)

    def get_structural_analysis(self, sa_id: str, headers: Headers = None):
        return self.get(f"/structural-analyses/{sa_id}", headers=headers)

    def complete_structural_analysis(self, sa_id: str, headers: Headers = None):
        return self.post(
            f"/structural-analyses/{sa_id}/complete", payload={}, headers=headers
        )

    # =====================================================================
    # Modification designs
    # =====================================================================
    def create_modification_design(self, payload: Payload, headers: Headers = None):
        return self.post("/modification-designs", payload=payload, headers=headers)

    def list_modification_designs(self, params: Payload = None, headers: Headers = None):
        return self.get("/modification-designs", payload=params, headers=headers)

    def get_modification_design(self, md_id: str, headers: Headers = None):
        return self.get(f"/modification-designs/{md_id}", headers=headers)

    def peer_review(self, md_id: str, payload: Payload, headers: Headers = None):
        return self.post(
            f"/modification-designs/{md_id}/peer-review", payload=payload, headers=headers
        )

    # =====================================================================
    # Environmental reviews
    # =====================================================================
    def create_environmental_review(self, payload: Payload, headers: Headers = None):
        return self.post("/environmental-reviews", payload=payload, headers=headers)

    def list_environmental_reviews(self, params: Payload = None, headers: Headers = None):
        return self.get("/environmental-reviews", payload=params, headers=headers)

    def get_environmental_review(self, er_id: str, headers: Headers = None):
        return self.get(f"/environmental-reviews/{er_id}", headers=headers)

    def screen_environmental_review(self, er_id: str, headers: Headers = None):
        return self.post(
            f"/environmental-reviews/{er_id}/screen", payload={}, headers=headers
        )

    def complete_branch(self, er_id: str, payload: Payload, headers: Headers = None):
        return self.post(
            f"/environmental-reviews/{er_id}/branch-complete",
            payload=payload,
            headers=headers,
        )

    # =====================================================================
    # Construction permits
    # =====================================================================
    def create_permit(self, payload: Payload, headers: Headers = None):
        return self.post("/construction-permits", payload=payload, headers=headers)

    def list_permits(self, params: Payload = None, headers: Headers = None):
        return self.get("/construction-permits", payload=params, headers=headers)

    def get_permit(self, permit_id: str, headers: Headers = None):
        return self.get(f"/construction-permits/{permit_id}", headers=headers)

    def issue_permit(self, permit_id: str, payload: Payload, headers: Headers = None):
        return self.post(
            f"/construction-permits/{permit_id}/issue", payload=payload, headers=headers
        )

    def revoke_permit(self, permit_id: str, payload: Payload, headers: Headers = None):
        return self.post(
            f"/construction-permits/{permit_id}/revoke", payload=payload, headers=headers
        )

    # =====================================================================
    # Utility providers
    # =====================================================================
    def create_utility_provider(self, payload: Payload, headers: Headers = None):
        return self.post("/utility-providers", payload=payload, headers=headers)

    def list_utility_providers(self, params: Payload = None, headers: Headers = None):
        return self.get("/utility-providers", payload=params, headers=headers)

    def get_utility_provider(self, provider_id: str, headers: Headers = None):
        return self.get(f"/utility-providers/{provider_id}", headers=headers)

    # =====================================================================
    # Backhaul orders
    # =====================================================================
    def create_backhaul_order(self, payload: Payload, headers: Headers = None):
        return self.post("/backhaul-orders", payload=payload, headers=headers)

    def list_backhaul_orders(self, params: Payload = None, headers: Headers = None):
        return self.get("/backhaul-orders", payload=params, headers=headers)

    def get_backhaul_order(self, order_id: str, headers: Headers = None):
        return self.get(f"/backhaul-orders/{order_id}", headers=headers)

    def order_status_action(self, order_id: str, payload: Payload, headers: Headers = None):
        return self.post(
            f"/backhaul-orders/{order_id}/status-actions",
            payload=payload,
            headers=headers,
        )

    # =====================================================================
    # On-air plans
    # =====================================================================
    def create_on_air_plan(self, payload: Payload, headers: Headers = None):
        return self.post("/on-air-plans", payload=payload, headers=headers)

    def list_on_air_plans(self, params: Payload = None, headers: Headers = None):
        return self.get("/on-air-plans", payload=params, headers=headers)

    def get_on_air_plan(self, plan_id: str, headers: Headers = None):
        return self.get(f"/on-air-plans/{plan_id}", headers=headers)

    def reforecast_plan(self, plan_id: str, payload: Payload = None, headers: Headers = None):
        return self.post(
            f"/on-air-plans/{plan_id}/reforecast", payload=payload or {}, headers=headers
        )

    def reset_plan(self, plan_id: str, payload: Payload, headers: Headers = None):
        return self.post(
            f"/on-air-plans/{plan_id}/reset", payload=payload, headers=headers
        )

    def activate_plan(self, plan_id: str, payload: Payload = None, headers: Headers = None):
        return self.post(
            f"/on-air-plans/{plan_id}/activate", payload=payload or {}, headers=headers
        )

    def get_forecast(self, plan_id: str, headers: Headers = None):
        return self.get(f"/on-air-plans/{plan_id}/forecast", headers=headers)


__all__ = ["ApiClient"]
