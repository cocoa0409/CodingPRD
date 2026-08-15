"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Docks ────────────────────────────────────────
    def create_dock(self, payload, headers):
        return self._request("POST", "/v1/docks", payload, headers)

    def get_dock(self, dock_id, headers):
        return self._request("GET", f"/v1/docks/{dock_id}", headers=headers)

    # ─── Vessels ──────────────────────────────────────
    def create_vessel(self, payload, headers):
        return self._request("POST", "/v1/vessels", payload, headers)

    def get_vessel(self, vessel_id, headers):
        return self._request("GET", f"/v1/vessels/{vessel_id}", headers=headers)

    # ─── Subcontractors ───────────────────────────────
    def create_subcontractor(self, payload, headers):
        return self._request("POST", "/v1/subcontractors", payload, headers)

    def get_subcontractor(self, subcontractor_id, headers):
        return self._request(
            "GET", f"/v1/subcontractors/{subcontractor_id}", headers=headers
        )

    # ─── Repair projects ──────────────────────────────
    def create_repair_project(self, payload, headers):
        return self._request("POST", "/v1/repair-projects", payload, headers)

    def get_repair_project(self, project_id, headers):
        return self._request(
            "GET", f"/v1/repair-projects/{project_id}", headers=headers
        )

    def list_repair_projects(self, headers, params=None):
        return self._request("GET", "/v1/repair-projects", headers=headers, params=params)

    def submit_bid(self, project_id, headers):
        return self._request(
            "POST", f"/v1/repair-projects/{project_id}/submit-bid", headers=headers
        )

    def award_project(self, project_id, headers):
        return self._request(
            "POST", f"/v1/repair-projects/{project_id}/award", headers=headers
        )

    def deliver_project(self, project_id, headers):
        return self._request(
            "POST", f"/v1/repair-projects/{project_id}/deliver", headers=headers
        )

    # ─── Dock reservations ────────────────────────────
    def create_dock_reservation(self, payload, headers):
        return self._request("POST", "/v1/dock-reservations", payload, headers)

    def get_dock_reservation(self, reservation_id, headers):
        return self._request(
            "GET", f"/v1/dock-reservations/{reservation_id}", headers=headers
        )

    def list_dock_reservations(self, headers, params=None):
        return self._request(
            "GET", "/v1/dock-reservations", headers=headers, params=params
        )

    def activate_dock_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/v1/dock-reservations/{reservation_id}/activate", headers=headers
        )

    def cancel_dock_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/v1/dock-reservations/{reservation_id}/cancel", headers=headers
        )

    # ─── Work items ───────────────────────────────────
    def create_work_item(self, payload, headers):
        return self._request("POST", "/v1/work-items", payload, headers)

    def get_work_item(self, work_item_id, headers):
        return self._request("GET", f"/v1/work-items/{work_item_id}", headers=headers)

    def list_work_items(self, headers, params=None):
        return self._request("GET", "/v1/work-items", headers=headers, params=params)

    def list_work_item_dependents(self, work_item_id, headers, params=None):
        return self._request(
            "GET", f"/v1/work-items/{work_item_id}/dependents",
            headers=headers, params=params,
        )

    def patch_work_item(self, work_item_id, payload, headers):
        return self._request(
            "PATCH", f"/v1/work-items/{work_item_id}", payload, headers
        )

    def start_work_item(self, work_item_id, headers):
        return self._request(
            "POST", f"/v1/work-items/{work_item_id}/start", headers=headers
        )

    def complete_work_item(self, work_item_id, headers):
        return self._request(
            "POST", f"/v1/work-items/{work_item_id}/complete", headers=headers
        )

    def cancel_work_item(self, work_item_id, headers):
        return self._request(
            "POST", f"/v1/work-items/{work_item_id}/cancel", headers=headers
        )

    # ─── Change orders ────────────────────────────────
    def create_change_order(self, payload, headers):
        return self._request("POST", "/v1/change-orders", payload, headers)

    def get_change_order(self, change_order_id, headers):
        return self._request(
            "GET", f"/v1/change-orders/{change_order_id}", headers=headers
        )

    def list_change_orders(self, headers, params=None):
        return self._request("GET", "/v1/change-orders", headers=headers, params=params)

    def approve_change_order(self, change_order_id, headers):
        return self._request(
            "POST", f"/v1/change-orders/{change_order_id}/approve", headers=headers
        )

    def owner_approve_change_order(self, change_order_id, headers):
        return self._request(
            "POST", f"/v1/change-orders/{change_order_id}/owner-approve",
            headers=headers,
        )

    def reject_change_order(self, change_order_id, payload, headers):
        return self._request(
            "POST", f"/v1/change-orders/{change_order_id}/reject", payload, headers
        )

    def revise_change_order(self, change_order_id, payload, headers):
        return self._request(
            "POST", f"/v1/change-orders/{change_order_id}/revise", payload, headers
        )

    def withdraw_change_order(self, change_order_id, headers):
        return self._request(
            "POST", f"/v1/change-orders/{change_order_id}/withdraw", headers=headers
        )

    # ─── Surveys ──────────────────────────────────────
    def create_survey(self, payload, headers):
        return self._request("POST", "/v1/surveys", payload, headers)

    def get_survey(self, survey_id, headers):
        return self._request("GET", f"/v1/surveys/{survey_id}", headers=headers)

    def list_surveys(self, headers, params=None):
        return self._request("GET", "/v1/surveys", headers=headers, params=params)

    def record_survey_result(self, survey_id, payload, headers):
        return self._request(
            "POST", f"/v1/surveys/{survey_id}/record-result", payload, headers
        )

    # ─── Permits ──────────────────────────────────────
    def create_permit(self, payload, headers):
        return self._request("POST", "/v1/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/v1/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/v1/permits", headers=headers, params=params)

    def grant_permit(self, permit_id, headers):
        return self._request("POST", f"/v1/permits/{permit_id}/grant", headers=headers)

    def suspend_permit(self, permit_id, headers):
        return self._request(
            "POST", f"/v1/permits/{permit_id}/suspend", headers=headers
        )

    def close_permit(self, permit_id, headers):
        return self._request("POST", f"/v1/permits/{permit_id}/close", headers=headers)

    # ─── Warranty claims ──────────────────────────────
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/v1/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/v1/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request(
            "GET", "/v1/warranty-claims", headers=headers, params=params
        )

    def accept_warranty_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/v1/warranty-claims/{claim_id}/accept", payload, headers
        )

    def deny_warranty_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/v1/warranty-claims/{claim_id}/deny", payload, headers
        )

    # ─── Logical clock (test-driving) ─────────────────
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/v1/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
