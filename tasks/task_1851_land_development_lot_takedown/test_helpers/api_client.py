"""API client: one method per endpoint defined in PRD §4."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.5) ---
    def set_clock(self, to_iso8601: str, headers: Dict):
        return self._request(
            "POST", "/api/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- parcels ---
    def create_parcel(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/parcels", payload, headers)

    def list_parcels(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/parcels", headers=headers, params=params)

    def get_parcel(self, parcel_id: str, headers: Dict):
        return self._request("GET", f"/api/parcels/{parcel_id}", headers=headers)

    def open_contingency(self, parcel_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/parcels/{parcel_id}/open-contingency", payload, headers)

    def extend_contingency(self, parcel_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/parcels/{parcel_id}/extend-contingency", payload, headers)

    def clear_contingency(self, parcel_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/parcels/{parcel_id}/clear-contingency", {}, headers)

    def terminate_contingency(self, parcel_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/parcels/{parcel_id}/terminate-contingency", {}, headers)

    # --- phases ---
    def create_phase(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/phases", payload, headers)

    def list_phases(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/phases", headers=headers, params=params)

    def get_phase(self, phase_id: str, headers: Dict):
        return self._request("GET", f"/api/phases/{phase_id}", headers=headers)

    def submit_plat(self, phase_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/phases/{phase_id}/submit-plat", payload, headers)

    def review_plat(self, phase_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/phases/{phase_id}/review-plat", payload, headers)

    def record_plat(self, phase_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/phases/{phase_id}/record-plat", {}, headers)

    def activate_phase(self, phase_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/phases/{phase_id}/activate", {}, headers)

    # --- infrastructure bonds ---
    def create_bond(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/infrastructure-bonds", payload, headers)

    def list_bonds(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/api/infrastructure-bonds", headers=headers, params=params)

    def get_bond(self, bond_id: str, headers: Dict):
        return self._request(
            "GET", f"/api/infrastructure-bonds/{bond_id}", headers=headers)

    def award_bid(self, bond_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/infrastructure-bonds/{bond_id}/award-bid", payload, headers)

    def post_bond(self, bond_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/infrastructure-bonds/{bond_id}/post-bond", payload, headers)

    def reduce_bond(self, bond_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/infrastructure-bonds/{bond_id}/reduce", payload, headers)

    def accept_work(self, bond_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/infrastructure-bonds/{bond_id}/accept-work", {}, headers)

    def release_bond(self, bond_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/infrastructure-bonds/{bond_id}/release", {}, headers)

    # --- builders ---
    def create_builder(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/builders", payload, headers)

    def list_builders(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/builders", headers=headers, params=params)

    def get_builder(self, builder_id: str, headers: Dict):
        return self._request("GET", f"/api/builders/{builder_id}", headers=headers)

    # --- takedown agreements ---
    def create_agreement(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/takedown-agreements", payload, headers)

    def list_agreements(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/api/takedown-agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id: str, headers: Dict):
        return self._request(
            "GET", f"/api/takedown-agreements/{agreement_id}", headers=headers)

    def activate_agreement(self, agreement_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/takedown-agreements/{agreement_id}/activate", {}, headers)

    def amend_agreement(self, agreement_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/takedown-agreements/{agreement_id}/amend", payload, headers)

    def declare_default(self, agreement_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/takedown-agreements/{agreement_id}/declare-default",
            payload, headers)

    def cure_agreement(self, agreement_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/takedown-agreements/{agreement_id}/cure", payload, headers)

    def terminate_agreement(self, agreement_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/takedown-agreements/{agreement_id}/terminate", {}, headers)

    # --- lots ---
    def list_lots(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/lots", headers=headers, params=params)

    def get_lot(self, lot_id: str, headers: Dict):
        return self._request("GET", f"/api/lots/{lot_id}", headers=headers)

    def reserve_lot(self, lot_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/api/lots/{lot_id}/reserve", payload, headers)

    # --- lot closings ---
    def create_closing(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/lot-closings", payload, headers)

    def list_closings(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/lot-closings", headers=headers, params=params)

    def get_closing(self, closing_id: str, headers: Dict):
        return self._request("GET", f"/api/lot-closings/{closing_id}", headers=headers)

    def finalize_closing(self, closing_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/lot-closings/{closing_id}/finalize", {}, headers)

    def cancel_closing(self, closing_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/lot-closings/{closing_id}/cancel", {}, headers)

    # --- development loans ---
    def create_loan(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/development-loans", payload, headers)

    def list_loans(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/api/development-loans", headers=headers, params=params)

    def get_loan(self, loan_id: str, headers: Dict):
        return self._request("GET", f"/api/development-loans/{loan_id}", headers=headers)

    def activate_loan(self, loan_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/development-loans/{loan_id}/activate", {}, headers)

    # --- loan draws ---
    def create_draw(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/loan-draws", payload, headers)

    def list_draws(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/loan-draws", headers=headers, params=params)

    def get_draw(self, draw_id: str, headers: Dict):
        return self._request("GET", f"/api/loan-draws/{draw_id}", headers=headers)

    def approve_draw(self, draw_id: str, headers: Dict):
        return self._request("POST", f"/api/loan-draws/{draw_id}/approve", {}, headers)

    def reject_draw(self, draw_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/loan-draws/{draw_id}/reject", payload, headers)

    def fund_draw(self, draw_id: str, headers: Dict):
        return self._request("POST", f"/api/loan-draws/{draw_id}/fund", {}, headers)

    def reverse_draw(self, draw_id: str, headers: Dict):
        return self._request("POST", f"/api/loan-draws/{draw_id}/reverse", {}, headers)

    # --- HOA associations ---
    def create_hoa(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/hoa-associations", payload, headers)

    def list_hoas(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/api/hoa-associations", headers=headers, params=params)

    def get_hoa(self, hoa_id: str, headers: Dict):
        return self._request("GET", f"/api/hoa-associations/{hoa_id}", headers=headers)

    def form_hoa(self, hoa_id: str, headers: Dict):
        return self._request("POST", f"/api/hoa-associations/{hoa_id}/form", {}, headers)

    def evaluate_control(self, hoa_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/hoa-associations/{hoa_id}/evaluate-control", {}, headers)

    def complete_transition(self, hoa_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/hoa-associations/{hoa_id}/complete-transition",
            payload, headers)

    # --- utility providers ---
    def create_provider(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/utility-providers", payload, headers)

    def list_providers(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/api/utility-providers", headers=headers, params=params)

    def get_provider(self, provider_id: str, headers: Dict):
        return self._request(
            "GET", f"/api/utility-providers/{provider_id}", headers=headers)

    # --- utility connections ---
    def create_connection(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/utility-connections", payload, headers)

    def list_connections(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/api/utility-connections", headers=headers, params=params)

    def get_connection(self, connection_id: str, headers: Dict):
        return self._request(
            "GET", f"/api/utility-connections/{connection_id}", headers=headers)

    def schedule_connection(self, connection_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/utility-connections/{connection_id}/schedule", {}, headers)

    def mark_connected(self, connection_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/utility-connections/{connection_id}/mark-connected",
            {}, headers)

    def cancel_connection(self, connection_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/utility-connections/{connection_id}/cancel", {}, headers)


api_client = ApiClient()
