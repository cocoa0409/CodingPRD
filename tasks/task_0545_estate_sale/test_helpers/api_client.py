"""API client: one method per endpoint defined in the Estate Sale PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Client ---
    def create_client(self, payload, headers):
        return self._request("POST", "/estate/clients", payload, headers)

    # --- Project ---
    def create_project(self, payload, headers):
        return self._request("POST", "/estate/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/estate/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/estate/projects", headers=headers, params=params)

    def patch_project(self, project_id, payload, headers):
        return self._request("PATCH", f"/estate/projects/{project_id}", payload, headers)

    def cancel_project(self, project_id, headers):
        return self._request("POST", f"/estate/projects/{project_id}/cancel", {}, headers)

    def list_project_settlements(self, project_id, headers):
        return self._request(
            "GET", f"/estate/projects/{project_id}/settlement-statements", headers=headers
        )

    # --- Lot ---
    def create_lot(self, payload, headers):
        return self._request("POST", "/estate/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/estate/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/estate/lots", headers=headers, params=params)

    def patch_lot(self, lot_id, payload, headers):
        return self._request("PATCH", f"/estate/lots/{lot_id}", payload, headers)

    def approve_buyout(self, lot_id, payload, headers):
        return self._request("POST", f"/estate/lots/{lot_id}/approve-buyout", payload, headers)

    def list_lot_bids(self, lot_id, headers):
        return self._request("GET", f"/estate/lots/{lot_id}/bids", headers=headers)

    # --- SaleEvent ---
    def create_sale_event(self, payload, headers):
        return self._request("POST", "/estate/sale-events", payload, headers)

    def get_sale_event(self, sale_event_id, headers):
        return self._request("GET", f"/estate/sale-events/{sale_event_id}", headers=headers)

    def list_sale_events(self, headers, params=None):
        return self._request("GET", "/estate/sale-events", headers=headers, params=params)

    def patch_sale_event(self, sale_event_id, payload, headers):
        return self._request("PATCH", f"/estate/sale-events/{sale_event_id}", payload, headers)

    def close_sale_event(self, sale_event_id, headers):
        return self._request("POST", f"/estate/sale-events/{sale_event_id}/close", {}, headers)

    # --- Crew ---
    def create_crew(self, payload, headers):
        return self._request("POST", "/estate/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/estate/crews/{crew_id}", headers=headers)

    # --- Transaction ---
    def create_transaction(self, payload, headers):
        return self._request("POST", "/estate/transactions", payload, headers)

    def get_transaction(self, transaction_id, headers):
        return self._request("GET", f"/estate/transactions/{transaction_id}", headers=headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", "/estate/transactions", headers=headers, params=params)

    def void_transaction(self, transaction_id, headers):
        return self._request(
            "POST", f"/estate/transactions/{transaction_id}/void", {}, headers
        )

    # --- Bid ---
    def create_bid(self, payload, headers):
        return self._request("POST", "/estate/bids", payload, headers)

    # --- HaulJob ---
    def create_haul_job(self, payload, headers):
        return self._request("POST", "/estate/haul-jobs", payload, headers)

    def get_haul_job(self, haul_job_id, headers):
        return self._request("GET", f"/estate/haul-jobs/{haul_job_id}", headers=headers)

    def list_haul_jobs(self, headers, params=None):
        return self._request("GET", "/estate/haul-jobs", headers=headers, params=params)

    def patch_haul_job(self, haul_job_id, payload, headers):
        return self._request("PATCH", f"/estate/haul-jobs/{haul_job_id}", payload, headers)

    # --- Truck ---
    def create_truck(self, payload, headers):
        return self._request("POST", "/estate/trucks", payload, headers)

    # --- SettlementStatement ---
    def create_settlement(self, payload, headers):
        return self._request("POST", "/estate/settlement-statements", payload, headers)


api_client = ApiClient()
