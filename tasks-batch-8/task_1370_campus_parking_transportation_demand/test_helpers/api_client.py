"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Patrons ---
    def create_patron(self, payload, headers):
        return self._request("POST", "/parking/patrons", payload, headers)

    def list_patrons(self, headers, params=None):
        return self._request("GET", "/parking/patrons", headers=headers, params=params)

    def get_patron(self, patron_id, headers):
        return self._request("GET", f"/parking/patrons/{patron_id}", headers=headers)

    # --- Parking lots ---
    def create_lot(self, payload, headers):
        return self._request("POST", "/parking/lots", payload, headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/parking/lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/parking/lots/{lot_id}", headers=headers)

    # --- Lot allocations ---
    def create_allocation(self, payload, headers):
        return self._request("POST", "/parking/allocations", payload, headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/parking/allocations", headers=headers, params=params)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/parking/allocations/{allocation_id}", headers=headers)

    def patch_allocation(self, allocation_id, payload, headers):
        return self._request("PATCH", f"/parking/allocations/{allocation_id}", payload, headers)

    def extend_offers(self, allocation_id, headers, payload=None):
        return self._request(
            "POST", f"/parking/allocations/{allocation_id}/extend-offers", payload or {}, headers
        )

    # --- Waitlist entries ---
    def create_waitlist_entry(self, payload, headers):
        return self._request("POST", "/parking/waitlist-entries", payload, headers)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/parking/waitlist-entries", headers=headers, params=params)

    def get_waitlist_entry(self, entry_id, headers):
        return self._request("GET", f"/parking/waitlist-entries/{entry_id}", headers=headers)

    def claim_waitlist_entry(self, entry_id, payload, headers):
        return self._request(
            "POST", f"/parking/waitlist-entries/{entry_id}/claim", payload, headers
        )

    def withdraw_waitlist_entry(self, entry_id, headers):
        return self._request(
            "POST", f"/parking/waitlist-entries/{entry_id}/withdraw", {}, headers
        )

    # --- Permits ---
    def create_permit(self, payload, headers):
        return self._request("POST", "/parking/permits", payload, headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/parking/permits", headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/parking/permits/{permit_id}", headers=headers)

    def cancel_permit(self, permit_id, headers):
        return self._request("POST", f"/parking/permits/{permit_id}/cancel", {}, headers)

    # --- Citations ---
    def create_citation(self, payload, headers):
        return self._request("POST", "/parking/citations", payload, headers)

    def list_citations(self, headers, params=None):
        return self._request("GET", "/parking/citations", headers=headers, params=params)

    def get_citation(self, citation_id, headers):
        return self._request("GET", f"/parking/citations/{citation_id}", headers=headers)

    def pay_citation(self, citation_id, headers):
        return self._request("POST", f"/parking/citations/{citation_id}/pay", {}, headers)

    def appeal_citation(self, citation_id, payload, headers):
        return self._request("POST", f"/parking/citations/{citation_id}/appeal", payload, headers)

    def decide_appeal(self, citation_id, payload, headers):
        return self._request(
            "POST", f"/parking/citations/{citation_id}/decide-appeal", payload, headers
        )

    # --- Lot closures ---
    def create_closure(self, payload, headers):
        return self._request("POST", "/parking/closures", payload, headers)

    def list_closures(self, headers, params=None):
        return self._request("GET", "/parking/closures", headers=headers, params=params)

    def get_closure(self, closure_id, headers):
        return self._request("GET", f"/parking/closures/{closure_id}", headers=headers)

    def activate_closure(self, closure_id, headers):
        return self._request("POST", f"/parking/closures/{closure_id}/activate", {}, headers)

    def lift_closure(self, closure_id, headers):
        return self._request("POST", f"/parking/closures/{closure_id}/lift", {}, headers)

    def cancel_closure(self, closure_id, headers):
        return self._request("POST", f"/parking/closures/{closure_id}/cancel", {}, headers)

    # --- Shuttle routes ---
    def create_shuttle_route(self, payload, headers):
        return self._request("POST", "/parking/shuttle-routes", payload, headers)

    def list_shuttle_routes(self, headers, params=None):
        return self._request("GET", "/parking/shuttle-routes", headers=headers, params=params)

    def get_shuttle_route(self, route_id, headers):
        return self._request("GET", f"/parking/shuttle-routes/{route_id}", headers=headers)

    def activate_shuttle_route(self, route_id, headers):
        return self._request("POST", f"/parking/shuttle-routes/{route_id}/activate", {}, headers)

    def suspend_shuttle_route(self, route_id, headers):
        return self._request("POST", f"/parking/shuttle-routes/{route_id}/suspend", {}, headers)

    def create_ridership_log(self, route_id, payload, headers):
        return self._request(
            "POST", f"/parking/shuttle-routes/{route_id}/ridership-logs", payload, headers
        )

    # --- Incentive accounts ---
    def create_incentive_account(self, payload, headers):
        return self._request("POST", "/parking/incentive-accounts", payload, headers)

    def list_incentive_accounts(self, headers, params=None):
        return self._request(
            "GET", "/parking/incentive-accounts", headers=headers, params=params
        )

    def get_incentive_account(self, account_id, headers):
        return self._request("GET", f"/parking/incentive-accounts/{account_id}", headers=headers)

    def create_accrual(self, account_id, payload, headers):
        return self._request(
            "POST", f"/parking/incentive-accounts/{account_id}/accruals", payload, headers
        )

    def redeem_incentive(self, account_id, payload, headers):
        return self._request(
            "POST", f"/parking/incentive-accounts/{account_id}/redeem", payload, headers
        )

    # --- Transportation funds ---
    def create_transportation_fund(self, payload, headers):
        return self._request("POST", "/parking/transportation-funds", payload, headers)

    def list_transportation_funds(self, headers, params=None):
        return self._request(
            "GET", "/parking/transportation-funds", headers=headers, params=params
        )

    def get_transportation_fund(self, fund_id, headers):
        return self._request("GET", f"/parking/transportation-funds/{fund_id}", headers=headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/parking/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
