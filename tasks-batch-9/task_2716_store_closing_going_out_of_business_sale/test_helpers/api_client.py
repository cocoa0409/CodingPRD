"""API client: one method per endpoint declared by the PRD.

Every endpoint is served at the root of the service with no shared prefix and no
version segment.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (requires neither X-User-ID nor X-User-Role)
    # ------------------------------------------------------------------
    def set_clock(self, current_utc, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers=headers,
        )

    def set_clock_raw(self, payload, headers=None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)

    # ------------------------------------------------------------------
    # Jurisdictions
    # ------------------------------------------------------------------
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/jurisdictions", payload, headers=headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/jurisdictions/{jurisdiction_id}", headers=headers)

    # ------------------------------------------------------------------
    # Engagements
    # ------------------------------------------------------------------
    def create_engagement(self, payload, headers):
        return self._request("POST", "/engagements", payload, headers=headers)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/engagements/{engagement_id}", headers=headers)

    def submit_engagement_for_approval(self, engagement_id, headers, payload=None):
        return self._request(
            "POST", f"/engagements/{engagement_id}/submit-for-approval",
            payload, headers=headers,
        )

    def decide_engagement_approval(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/approval-decision",
            payload, headers=headers,
        )

    def wind_down_engagement(self, engagement_id, headers, payload=None):
        return self._request(
            "POST", f"/engagements/{engagement_id}/wind-down", payload, headers=headers,
        )

    def run_compliance_sweep(self, engagement_id, headers, payload=None):
        return self._request(
            "POST", f"/engagements/{engagement_id}/compliance-sweep",
            payload, headers=headers,
        )

    def get_recovery_summary(self, engagement_id, headers):
        return self._request(
            "GET", f"/engagements/{engagement_id}/recovery-summary", headers=headers,
        )

    # ------------------------------------------------------------------
    # Expense items
    # ------------------------------------------------------------------
    def create_expense_item(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/expense-items", payload, headers=headers,
        )

    def list_engagement_expense_items(self, engagement_id, headers, params=None):
        return self._request(
            "GET", f"/engagements/{engagement_id}/expense-items",
            headers=headers, params=params,
        )

    def list_store_expense_items(self, store_id, headers, params=None):
        return self._request(
            "GET", f"/stores/{store_id}/expense-items", headers=headers, params=params,
        )

    def get_expense_item(self, expense_item_id, headers):
        return self._request("GET", f"/expense-items/{expense_item_id}", headers=headers)

    def decide_expense_item(self, expense_item_id, payload, headers):
        return self._request(
            "POST", f"/expense-items/{expense_item_id}/decision", payload, headers=headers,
        )

    # ------------------------------------------------------------------
    # Settlements
    # ------------------------------------------------------------------
    def create_settlement(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/settlements", payload, headers=headers,
        )

    def list_settlements(self, engagement_id, headers, params=None):
        return self._request(
            "GET", f"/engagements/{engagement_id}/settlements",
            headers=headers, params=params,
        )

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def propose_settlement(self, settlement_id, headers, payload=None):
        return self._request(
            "POST", f"/settlements/{settlement_id}/propose", payload, headers=headers,
        )

    def respond_to_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"/settlements/{settlement_id}/response", payload, headers=headers,
        )

    def finalize_settlement(self, settlement_id, headers, payload=None):
        return self._request(
            "POST", f"/settlements/{settlement_id}/finalize", payload, headers=headers,
        )

    # ------------------------------------------------------------------
    # Stores
    # ------------------------------------------------------------------
    def create_store(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/stores", payload, headers=headers,
        )

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", "/stores", headers=headers, params=params)

    def close_selling(self, store_id, headers, payload=None):
        return self._request(
            "POST", f"/stores/{store_id}/close-selling", payload, headers=headers,
        )

    def suspend_store(self, store_id, headers, payload=None):
        return self._request(
            "POST", f"/stores/{store_id}/suspend", payload, headers=headers,
        )

    def resume_store(self, store_id, headers, payload=None):
        return self._request(
            "POST", f"/stores/{store_id}/resume", payload, headers=headers,
        )

    # ------------------------------------------------------------------
    # Inventory lots
    # ------------------------------------------------------------------
    def create_inventory_lot(self, store_id, payload, headers):
        return self._request(
            "POST", f"/stores/{store_id}/inventory-lots", payload, headers=headers,
        )

    def list_inventory_lots(self, store_id, headers, params=None):
        return self._request(
            "GET", f"/stores/{store_id}/inventory-lots", headers=headers, params=params,
        )

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/inventory-lots/{lot_id}", headers=headers)

    def list_consignment_inventory_lots(self, consignment_id, headers, params=None):
        return self._request(
            "GET", f"/augmentation-consignments/{consignment_id}/inventory-lots",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Going-out-of-business licences
    # ------------------------------------------------------------------
    def create_gob_license(self, store_id, payload, headers):
        return self._request(
            "POST", f"/stores/{store_id}/gob-licenses", payload, headers=headers,
        )

    def list_gob_licenses(self, store_id, headers, params=None):
        return self._request(
            "GET", f"/stores/{store_id}/gob-licenses", headers=headers, params=params,
        )

    def get_gob_license(self, license_id, headers):
        return self._request("GET", f"/gob-licenses/{license_id}", headers=headers)

    def decide_gob_license(self, license_id, payload, headers):
        return self._request(
            "POST", f"/gob-licenses/{license_id}/decision", payload, headers=headers,
        )

    def revoke_gob_license(self, license_id, payload, headers):
        return self._request(
            "POST", f"/gob-licenses/{license_id}/revoke", payload, headers=headers,
        )

    # ------------------------------------------------------------------
    # Markdown stages
    # ------------------------------------------------------------------
    def create_markdown_stage(self, store_id, payload, headers):
        return self._request(
            "POST", f"/stores/{store_id}/markdown-stages", payload, headers=headers,
        )

    def list_markdown_stages(self, store_id, headers, params=None):
        return self._request(
            "GET", f"/stores/{store_id}/markdown-stages", headers=headers, params=params,
        )

    def get_markdown_stage(self, stage_id, headers):
        return self._request("GET", f"/markdown-stages/{stage_id}", headers=headers)

    def activate_markdown_stage(self, stage_id, headers, payload=None):
        return self._request(
            "POST", f"/markdown-stages/{stage_id}/activate", payload, headers=headers,
        )

    def checkpoint_markdown_stage(self, stage_id, headers, payload=None):
        return self._request(
            "POST", f"/markdown-stages/{stage_id}/checkpoint", payload, headers=headers,
        )

    # ------------------------------------------------------------------
    # Augmentation consignments
    # ------------------------------------------------------------------
    def create_augmentation_consignment(self, store_id, payload, headers):
        return self._request(
            "POST", f"/stores/{store_id}/augmentation-consignments",
            payload, headers=headers,
        )

    def list_augmentation_consignments(self, store_id, headers, params=None):
        return self._request(
            "GET", f"/stores/{store_id}/augmentation-consignments",
            headers=headers, params=params,
        )

    def get_augmentation_consignment(self, consignment_id, headers):
        return self._request(
            "GET", f"/augmentation-consignments/{consignment_id}", headers=headers,
        )

    def file_consignment_disclosure(self, consignment_id, headers, payload=None):
        return self._request(
            "POST", f"/augmentation-consignments/{consignment_id}/file-disclosure",
            payload, headers=headers,
        )

    def receive_consignment(self, consignment_id, headers, payload=None):
        return self._request(
            "POST", f"/augmentation-consignments/{consignment_id}/receive",
            payload, headers=headers,
        )

    def return_unsold_consignment(self, consignment_id, headers, payload=None):
        return self._request(
            "POST", f"/augmentation-consignments/{consignment_id}/return-unsold",
            payload, headers=headers,
        )

    # ------------------------------------------------------------------
    # Employees
    # ------------------------------------------------------------------
    def create_employee(self, store_id, payload, headers):
        return self._request(
            "POST", f"/stores/{store_id}/employees", payload, headers=headers,
        )

    def list_employees(self, store_id, headers, params=None):
        return self._request(
            "GET", f"/stores/{store_id}/employees", headers=headers, params=params,
        )

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/employees/{employee_id}", headers=headers)

    def employment_action(self, employee_id, payload, headers):
        return self._request(
            "POST", f"/employees/{employee_id}/employment-action", payload, headers=headers,
        )

    def pay_bonus(self, employee_id, headers, payload=None):
        return self._request(
            "POST", f"/employees/{employee_id}/pay-bonus", payload, headers=headers,
        )

    # ------------------------------------------------------------------
    # Selling days
    # ------------------------------------------------------------------
    def create_sales_day(self, store_id, payload, headers):
        return self._request(
            "POST", f"/stores/{store_id}/sales-days", payload, headers=headers,
        )

    def list_sales_days(self, store_id, headers, params=None):
        return self._request(
            "GET", f"/stores/{store_id}/sales-days", headers=headers, params=params,
        )

    def review_sales_day(self, sales_day_id, payload, headers):
        return self._request(
            "POST", f"/sales-days/{sales_day_id}/review", payload, headers=headers,
        )

    # ------------------------------------------------------------------
    # Lease dispositions
    # ------------------------------------------------------------------
    def create_lease_disposition(self, store_id, payload, headers):
        return self._request(
            "POST", f"/stores/{store_id}/lease-dispositions", payload, headers=headers,
        )

    def list_lease_dispositions(self, store_id, headers, params=None):
        return self._request(
            "GET", f"/stores/{store_id}/lease-dispositions", headers=headers, params=params,
        )

    def get_lease_disposition(self, disposition_id, headers):
        return self._request("GET", f"/lease-dispositions/{disposition_id}", headers=headers)

    def send_lease_offer(self, disposition_id, payload, headers):
        return self._request(
            "POST", f"/lease-dispositions/{disposition_id}/offer", payload, headers=headers,
        )

    def record_landlord_response(self, disposition_id, payload, headers):
        return self._request(
            "POST", f"/lease-dispositions/{disposition_id}/landlord-response",
            payload, headers=headers,
        )

    def surrender_lease(self, disposition_id, payload, headers):
        return self._request(
            "POST", f"/lease-dispositions/{disposition_id}/surrender",
            payload, headers=headers,
        )


api_client = ApiClient()
