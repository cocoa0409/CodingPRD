"""API client: one method per endpoint defined in the Wine-Storage Cellar PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Member ----
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def activate_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/activate", {}, headers)

    def suspend_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/suspend", {}, headers)

    def reactivate_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/reactivate", {}, headers)

    def close_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/close", {}, headers)

    def create_ledger_adjustment(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/ledger-adjustments", payload, headers)

    # ---- LedgerEntry ----
    def get_ledger_entry(self, ledger_entry_id, headers):
        return self._request("GET", f"/ledger-entries/{ledger_entry_id}", headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)

    # ---- Locker ----
    def create_locker(self, payload, headers):
        return self._request("POST", "/lockers", payload, headers)

    def get_locker(self, locker_id, headers):
        return self._request("GET", f"/lockers/{locker_id}", headers=headers)

    def list_lockers(self, headers, params=None):
        return self._request("GET", "/lockers", headers=headers, params=params)

    def assign_locker(self, locker_id, payload, headers):
        return self._request("POST", f"/lockers/{locker_id}/assign", payload, headers)

    def release_locker(self, locker_id, headers):
        return self._request("POST", f"/lockers/{locker_id}/release", {}, headers)

    def retire_locker(self, locker_id, headers):
        return self._request("POST", f"/lockers/{locker_id}/retire", {}, headers)

    # ---- Bottle ----
    def create_bottle(self, payload, headers):
        return self._request("POST", "/bottles", payload, headers)

    def get_bottle(self, bottle_id, headers):
        return self._request("GET", f"/bottles/{bottle_id}", headers=headers)

    def list_bottles(self, headers, params=None):
        return self._request("GET", "/bottles", headers=headers, params=params)

    def set_bottle_provenance(self, bottle_id, payload, headers):
        return self._request("POST", f"/bottles/{bottle_id}/provenance", payload, headers)

    # ---- Appraisal ----
    def create_appraisal(self, payload, headers):
        return self._request("POST", "/appraisals", payload, headers)

    def finalize_appraisal(self, appraisal_id, payload, headers):
        return self._request("POST", f"/appraisals/{appraisal_id}/finalize", payload, headers)

    def get_appraisal(self, appraisal_id, headers):
        return self._request("GET", f"/appraisals/{appraisal_id}", headers=headers)

    def list_appraisals(self, headers, params=None):
        return self._request("GET", "/appraisals", headers=headers, params=params)

    # ---- InsurancePolicy ----
    def create_insurance_policy(self, payload, headers):
        return self._request("POST", "/insurance-policies", payload, headers)

    def bind_insurance_policy(self, policy_id, headers):
        return self._request("POST", f"/insurance-policies/{policy_id}/bind", {}, headers)

    def cancel_insurance_policy(self, policy_id, headers):
        return self._request("POST", f"/insurance-policies/{policy_id}/cancel", {}, headers)

    def get_insurance_policy(self, policy_id, headers):
        return self._request("GET", f"/insurance-policies/{policy_id}", headers=headers)

    def list_insurance_policies(self, headers, params=None):
        return self._request("GET", "/insurance-policies", headers=headers, params=params)

    # ---- MovementRequest ----
    def create_movement_request(self, payload, headers):
        return self._request("POST", "/movement-requests", payload, headers)

    def approve_movement_request(self, movement_request_id, headers):
        return self._request("POST", f"/movement-requests/{movement_request_id}/approve", {}, headers)

    def reject_movement_request(self, movement_request_id, headers):
        return self._request("POST", f"/movement-requests/{movement_request_id}/reject", {}, headers)

    def complete_movement_request(self, movement_request_id, headers):
        return self._request("POST", f"/movement-requests/{movement_request_id}/complete", {}, headers)

    def cancel_movement_request(self, movement_request_id, headers):
        return self._request("POST", f"/movement-requests/{movement_request_id}/cancel", {}, headers)

    def get_movement_request(self, movement_request_id, headers):
        return self._request("GET", f"/movement-requests/{movement_request_id}", headers=headers)

    def list_movement_requests(self, headers, params=None):
        return self._request("GET", "/movement-requests", headers=headers, params=params)

    # ---- DeliveryOrder ----
    def create_delivery_order(self, payload, headers):
        return self._request("POST", "/delivery-orders", payload, headers)

    def deliver_delivery_order(self, delivery_order_id, headers):
        return self._request("POST", f"/delivery-orders/{delivery_order_id}/deliver", {}, headers)

    def cancel_delivery_order(self, delivery_order_id, headers):
        return self._request("POST", f"/delivery-orders/{delivery_order_id}/cancel", {}, headers)

    def get_delivery_order(self, delivery_order_id, headers):
        return self._request("GET", f"/delivery-orders/{delivery_order_id}", headers=headers)

    def list_delivery_orders(self, headers, params=None):
        return self._request("GET", "/delivery-orders", headers=headers, params=params)

    # ---- Consignment ----
    def create_consignment(self, payload, headers):
        return self._request("POST", "/consignments", payload, headers)

    def list_consignment(self, consignment_id, headers):
        return self._request("POST", f"/consignments/{consignment_id}/list", {}, headers)

    def offer_consignment(self, consignment_id, payload, headers):
        return self._request("POST", f"/consignments/{consignment_id}/offer", payload, headers)

    def counter_consignment(self, consignment_id, payload, headers):
        return self._request("POST", f"/consignments/{consignment_id}/counter", payload, headers)

    def accept_consignment(self, consignment_id, headers):
        return self._request("POST", f"/consignments/{consignment_id}/accept", {}, headers)

    def settle_consignment(self, consignment_id, payload, headers):
        return self._request("POST", f"/consignments/{consignment_id}/settle", payload, headers)

    def withdraw_consignment(self, consignment_id, headers):
        return self._request("POST", f"/consignments/{consignment_id}/withdraw", {}, headers)

    def get_consignment(self, consignment_id, headers):
        return self._request("GET", f"/consignments/{consignment_id}", headers=headers)

    def list_consignments(self, headers, params=None):
        return self._request("GET", "/consignments", headers=headers, params=params)

    # ---- WaitlistEntry ----
    def create_waitlist_entry(self, payload, headers):
        return self._request("POST", "/waitlist-entries", payload, headers)

    def accept_waitlist_entry(self, waitlist_entry_id, headers):
        return self._request("POST", f"/waitlist-entries/{waitlist_entry_id}/accept", {}, headers)

    def cancel_waitlist_entry(self, waitlist_entry_id, headers):
        return self._request("POST", f"/waitlist-entries/{waitlist_entry_id}/cancel", {}, headers)

    def get_waitlist_entry(self, waitlist_entry_id, headers):
        return self._request("GET", f"/waitlist-entries/{waitlist_entry_id}", headers=headers)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/waitlist-entries", headers=headers, params=params)

    # ---- MaintenanceWindow ----
    def create_maintenance_window(self, payload, headers):
        return self._request("POST", "/maintenance-windows", payload, headers)

    def activate_maintenance_window(self, maintenance_window_id, headers):
        return self._request("POST", f"/maintenance-windows/{maintenance_window_id}/activate", {}, headers)

    def complete_maintenance_window(self, maintenance_window_id, headers):
        return self._request("POST", f"/maintenance-windows/{maintenance_window_id}/complete", {}, headers)

    def cancel_maintenance_window(self, maintenance_window_id, headers):
        return self._request("POST", f"/maintenance-windows/{maintenance_window_id}/cancel", {}, headers)

    def get_maintenance_window(self, maintenance_window_id, headers):
        return self._request("GET", f"/maintenance-windows/{maintenance_window_id}", headers=headers)

    def list_maintenance_windows(self, headers, params=None):
        return self._request("GET", "/maintenance-windows", headers=headers, params=params)

    # ---- ClimateReading ----
    def create_climate_reading(self, payload, headers):
        return self._request("POST", "/climate-readings", payload, headers)

    def get_climate_reading(self, climate_reading_id, headers):
        return self._request("GET", f"/climate-readings/{climate_reading_id}", headers=headers)

    def list_climate_readings(self, headers, params=None):
        return self._request("GET", "/climate-readings", headers=headers, params=params)

    # ---- Operations / clock ----
    def run_operations_cycle(self, headers):
        return self._request("POST", "/operations/cycle", {}, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
