"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Zone
    # ------------------------------------------------------------------
    def create_zone(self, payload, headers):
        return self._request("POST", "/zones", payload, headers)

    def list_zones(self, headers, params=None):
        return self._request("GET", "/zones", headers=headers, params=params)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/zones/{zone_id}", headers=headers)

    def transition_zone(self, zone_id, payload, headers):
        return self._request("POST", f"/zones/{zone_id}/transition", payload, headers)

    # ------------------------------------------------------------------
    # Admission
    # ------------------------------------------------------------------
    def create_admission(self, payload, headers):
        return self._request("POST", "/zones/admissions", payload, headers)

    def list_admissions(self, headers, params=None):
        return self._request("GET", "/zones/admissions", headers=headers, params=params)

    def get_admission(self, admission_id, headers):
        return self._request("GET", f"/zones/admissions/{admission_id}", headers=headers)

    def submit_admission(self, admission_id, headers):
        return self._request("POST", f"/zones/admissions/{admission_id}/submit", headers=headers)

    def admit_admission(self, admission_id, headers):
        return self._request("POST", f"/zones/admissions/{admission_id}/admit", headers=headers)

    def return_admission(self, admission_id, headers):
        return self._request("POST", f"/zones/admissions/{admission_id}/return", headers=headers)

    def cancel_admission(self, admission_id, headers):
        return self._request("POST", f"/zones/admissions/{admission_id}/cancel", headers=headers)

    # ------------------------------------------------------------------
    # InventoryLot (read-only)
    # ------------------------------------------------------------------
    def list_lots(self, headers, params=None):
        return self._request("GET", "/zones/lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/zones/lots/{lot_id}", headers=headers)

    # ------------------------------------------------------------------
    # ManipulationOrder
    # ------------------------------------------------------------------
    def create_manipulation_order(self, payload, headers):
        return self._request("POST", "/zones/manipulation-orders", payload, headers)

    def list_manipulation_orders(self, headers, params=None):
        return self._request("GET", "/zones/manipulation-orders", headers=headers, params=params)

    def get_manipulation_order(self, order_id, headers):
        return self._request("GET", f"/zones/manipulation-orders/{order_id}", headers=headers)

    def approve_manipulation_order(self, order_id, headers):
        return self._request("POST", f"/zones/manipulation-orders/{order_id}/approve", headers=headers)

    def complete_manipulation_order(self, order_id, headers):
        return self._request("POST", f"/zones/manipulation-orders/{order_id}/complete", headers=headers)

    def reject_manipulation_order(self, order_id, headers):
        return self._request("POST", f"/zones/manipulation-orders/{order_id}/reject", headers=headers)

    def cancel_manipulation_order(self, order_id, headers):
        return self._request("POST", f"/zones/manipulation-orders/{order_id}/cancel", headers=headers)

    # ------------------------------------------------------------------
    # Withdrawal
    # ------------------------------------------------------------------
    def create_withdrawal(self, payload, headers):
        return self._request("POST", "/zones/withdrawals", payload, headers)

    def list_withdrawals(self, headers, params=None):
        return self._request("GET", "/zones/withdrawals", headers=headers, params=params)

    def get_withdrawal(self, withdrawal_id, headers):
        return self._request("GET", f"/zones/withdrawals/{withdrawal_id}", headers=headers)

    def file_withdrawal(self, withdrawal_id, headers):
        return self._request("POST", f"/zones/withdrawals/{withdrawal_id}/file", headers=headers)

    def pay_duty_withdrawal(self, withdrawal_id, headers):
        return self._request("POST", f"/zones/withdrawals/{withdrawal_id}/pay-duty", headers=headers)

    def confirm_export_withdrawal(self, withdrawal_id, headers):
        return self._request("POST", f"/zones/withdrawals/{withdrawal_id}/confirm-export", headers=headers)

    def cancel_withdrawal(self, withdrawal_id, headers):
        return self._request("POST", f"/zones/withdrawals/{withdrawal_id}/cancel", headers=headers)

    # ------------------------------------------------------------------
    # WeeklyEntry
    # ------------------------------------------------------------------
    def create_weekly_entry(self, payload, headers):
        return self._request("POST", "/zones/weekly-entries", payload, headers)

    def list_weekly_entries(self, headers, params=None):
        return self._request("GET", "/zones/weekly-entries", headers=headers, params=params)

    def get_weekly_entry(self, entry_id, headers):
        return self._request("GET", f"/zones/weekly-entries/{entry_id}", headers=headers)

    def file_weekly_entry(self, entry_id, headers):
        return self._request("POST", f"/zones/weekly-entries/{entry_id}/file", headers=headers)

    def transition_weekly_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/zones/weekly-entries/{entry_id}/transition", payload, headers)

    # ------------------------------------------------------------------
    # AnnualReconciliation
    # ------------------------------------------------------------------
    def create_annual_reconciliation(self, payload, headers):
        return self._request("POST", "/zones/annual-reconciliations", payload, headers)

    def list_annual_reconciliations(self, headers, params=None):
        return self._request("GET", "/zones/annual-reconciliations", headers=headers, params=params)

    def get_annual_reconciliation(self, recon_id, headers):
        return self._request("GET", f"/zones/annual-reconciliations/{recon_id}", headers=headers)

    def submit_annual_reconciliation(self, recon_id, headers):
        return self._request("POST", f"/zones/annual-reconciliations/{recon_id}/submit", headers=headers)

    def accept_annual_reconciliation(self, recon_id, headers):
        return self._request("POST", f"/zones/annual-reconciliations/{recon_id}/accept", headers=headers)

    # ------------------------------------------------------------------
    # AccessBadge
    # ------------------------------------------------------------------
    def create_access_badge(self, payload, headers):
        return self._request("POST", "/zones/access-badges", payload, headers)

    def list_access_badges(self, headers, params=None):
        return self._request("GET", "/zones/access-badges", headers=headers, params=params)

    def get_access_badge(self, badge_id, headers):
        return self._request("GET", f"/zones/access-badges/{badge_id}", headers=headers)

    def transition_access_badge(self, badge_id, payload, headers):
        return self._request("POST", f"/zones/access-badges/{badge_id}/transition", payload, headers)

    # ------------------------------------------------------------------
    # ZoneAccessEvent (append-only)
    # ------------------------------------------------------------------
    def create_access_event(self, payload, headers):
        return self._request("POST", "/zones/access-events", payload, headers)

    def list_access_events(self, headers, params=None):
        return self._request("GET", "/zones/access-events", headers=headers, params=params)

    def get_access_event(self, event_id, headers):
        return self._request("GET", f"/zones/access-events/{event_id}", headers=headers)

    # ------------------------------------------------------------------
    # Logical clock (test-driving)
    # ------------------------------------------------------------------
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
