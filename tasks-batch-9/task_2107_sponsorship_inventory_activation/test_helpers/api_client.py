"""API client: one method per endpoint defined in the PRD."""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin endpoint wrapper. Every method returns the raw HTTP response."""

    # ---- Properties -------------------------------------------------------
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def transition_property(self, property_id, payload, headers):
        return self._request(
            "POST", f"/properties/{property_id}/transition", payload, headers
        )

    # ---- Rate cards -------------------------------------------------------
    def create_rate_card(self, property_id, payload, headers):
        return self._request(
            "POST", f"/properties/{property_id}/rate-cards", payload, headers
        )

    def get_rate_card(self, rate_card_id, headers):
        return self._request("GET", f"/rate-cards/{rate_card_id}", headers=headers)

    def list_rate_cards(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/rate-cards", payload=params, headers=headers)

    def create_rate_card_line(self, rate_card_id, payload, headers):
        return self._request(
            "POST", f"/rate-cards/{rate_card_id}/lines", payload, headers
        )

    def list_rate_card_lines(self, rate_card_id, headers):
        return self._request(
            "GET", f"/rate-cards/{rate_card_id}/lines", headers=headers
        )

    def publish_rate_card(self, rate_card_id, headers):
        return self._request(
            "POST", f"/rate-cards/{rate_card_id}/publish", {}, headers
        )

    # ---- Inventory assets -------------------------------------------------
    def create_inventory_asset(self, property_id, payload, headers):
        return self._request(
            "POST", f"/properties/{property_id}/inventory-assets", payload, headers
        )

    def get_inventory_asset(self, inventory_asset_id, headers):
        return self._request(
            "GET", f"/inventory-assets/{inventory_asset_id}", headers=headers
        )

    def list_inventory_assets(self, headers, params: Optional[dict] = None):
        return self._request(
            "GET", "/inventory-assets", payload=params, headers=headers
        )

    # ---- Sponsors ---------------------------------------------------------
    def create_sponsor(self, payload, headers):
        return self._request("POST", "/sponsors", payload, headers)

    def get_sponsor(self, sponsor_id, headers):
        return self._request("GET", f"/sponsors/{sponsor_id}", headers=headers)

    # ---- Contracts --------------------------------------------------------
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/contracts", payload=params, headers=headers)

    def create_entitlement(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/entitlements", payload, headers
        )

    def get_entitlement(self, entitlement_id, headers):
        return self._request(
            "GET", f"/entitlements/{entitlement_id}", headers=headers
        )

    def list_entitlements(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/entitlements", payload=params, headers=headers)

    def submit_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/submit", {}, headers)

    def return_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/return", payload, headers
        )

    def countersign_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/countersign", payload, headers
        )

    def activate_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/activate", {}, headers
        )

    def terminate_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/terminate", payload, headers
        )

    def close_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/close", {}, headers)

    def get_roi_report(self, contract_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"/contracts/{contract_id}/roi-report", payload=params,
            headers=headers,
        )

    # ---- Asset bookings ---------------------------------------------------
    def create_asset_booking(self, payload, headers):
        return self._request("POST", "/asset-bookings", payload, headers)

    def get_asset_booking(self, booking_id, headers):
        return self._request("GET", f"/asset-bookings/{booking_id}", headers=headers)

    def list_asset_bookings(self, headers, params: Optional[dict] = None):
        return self._request(
            "GET", "/asset-bookings", payload=params, headers=headers
        )

    def cancel_asset_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/asset-bookings/{booking_id}/cancel", payload, headers
        )

    def deliver_asset_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/asset-bookings/{booking_id}/deliver", {}, headers
        )

    # ---- Proof of performance --------------------------------------------
    def create_proof(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/asset-bookings/{booking_id}/proofs", payload, headers
        )

    def list_proofs(self, booking_id, headers):
        return self._request(
            "GET", f"/asset-bookings/{booking_id}/proofs", headers=headers
        )

    def adjudicate_proof(self, proof_id, payload, headers):
        return self._request(
            "POST", f"/proofs/{proof_id}/adjudicate", payload, headers
        )

    # ---- Staffing ---------------------------------------------------------
    def create_staff_member(self, payload, headers):
        return self._request("POST", "/staff-members", payload, headers)

    def create_staff_assignment(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/asset-bookings/{booking_id}/assignments", payload, headers
        )

    def get_staff_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/staff-assignments/{assignment_id}", headers=headers
        )

    def list_staff_assignments(self, headers, params: Optional[dict] = None):
        return self._request(
            "GET", "/staff-assignments", payload=params, headers=headers
        )

    def check_in_staff_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/staff-assignments/{assignment_id}/check-in", {}, headers
        )

    # ---- Sponsor surveys --------------------------------------------------
    def create_survey(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/surveys", payload, headers
        )

    def list_surveys(self, contract_id, headers):
        return self._request(
            "GET", f"/contracts/{contract_id}/surveys", headers=headers
        )

    # ---- Logical clock ----------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
