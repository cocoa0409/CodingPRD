"""API client: one method per endpoint defined in the PRD.

Subclasses the framework GenericApiClient; the base _request() is inherited.
GET calls pass the params dict as query parameters; POST calls send a JSON body.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- Marina ----
    def create_marina(self, payload, headers):
        return self._request("POST", "/marina/marinas", payload, headers)

    def get_marina(self, marina_id, headers):
        return self._request("GET", f"/marina/marinas/{marina_id}", headers=headers)

    def list_marinas(self, headers, params=None):
        return self._request("GET", "/marina/marinas", headers=headers, params=params)

    # ---- Forklift ----
    def create_forklift(self, payload, headers):
        return self._request("POST", "/marina/forklifts", payload, headers)

    def get_forklift(self, forklift_id, headers):
        return self._request("GET", f"/marina/forklifts/{forklift_id}", headers=headers)

    def list_forklifts(self, headers, params=None):
        return self._request("GET", "/marina/forklifts", headers=headers, params=params)

    # ---- Rack ----
    def create_rack(self, payload, headers):
        return self._request("POST", "/marina/racks", payload, headers)

    def get_rack(self, rack_id, headers):
        return self._request("GET", f"/marina/racks/{rack_id}", headers=headers)

    def list_racks(self, headers, params=None):
        return self._request("GET", "/marina/racks", headers=headers, params=params)

    # ---- BoatOwnerAccount ----
    def create_owner(self, payload, headers):
        return self._request("POST", "/marina/owners", payload, headers)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/marina/owners/{owner_id}", headers=headers)

    def list_owners(self, headers, params=None):
        return self._request("GET", "/marina/owners", headers=headers, params=params)

    # ---- Vessel ----
    def create_vessel(self, payload, headers):
        return self._request("POST", "/marina/vessels", payload, headers)

    def get_vessel(self, vessel_id, headers):
        return self._request("GET", f"/marina/vessels/{vessel_id}", headers=headers)

    def list_vessels(self, headers, params=None):
        return self._request("GET", "/marina/vessels", headers=headers, params=params)

    # ---- InsurancePolicy ----
    def create_insurance_policy(self, payload, headers):
        return self._request("POST", "/marina/insurance-policies", payload, headers)

    def get_insurance_policy(self, policy_id, headers):
        return self._request("GET", f"/marina/insurance-policies/{policy_id}", headers=headers)

    def list_insurance_policies(self, headers, params=None):
        return self._request("GET", "/marina/insurance-policies", headers=headers, params=params)

    def verify_insurance_policy(self, policy_id, headers):
        return self._request("POST", f"/marina/insurance-policies/{policy_id}/verify", {}, headers)

    def reject_insurance_policy(self, policy_id, headers):
        return self._request("POST", f"/marina/insurance-policies/{policy_id}/reject", {}, headers)

    def expire_insurance_policy(self, policy_id, headers):
        return self._request("POST", f"/marina/insurance-policies/{policy_id}/expire", {}, headers)

    # ---- StorageAgreement ----
    def create_storage_agreement(self, payload, headers):
        return self._request("POST", "/marina/storage-agreements", payload, headers)

    def get_storage_agreement(self, agreement_id, headers):
        return self._request("GET", f"/marina/storage-agreements/{agreement_id}", headers=headers)

    def list_storage_agreements(self, headers, params=None):
        return self._request("GET", "/marina/storage-agreements", headers=headers, params=params)

    def activate_storage_agreement(self, agreement_id, expected_rack_version, headers):
        return self._request("POST", f"/marina/storage-agreements/{agreement_id}/activate",
                             {"expected_rack_version": expected_rack_version}, headers)

    def winterize_storage_agreement(self, agreement_id, headers):
        return self._request("POST", f"/marina/storage-agreements/{agreement_id}/winterize", {}, headers)

    def reactivate_storage_agreement(self, agreement_id, headers):
        return self._request("POST", f"/marina/storage-agreements/{agreement_id}/reactivate", {}, headers)

    def terminate_storage_agreement(self, agreement_id, headers):
        return self._request("POST", f"/marina/storage-agreements/{agreement_id}/terminate", {}, headers)

    # ---- WaitlistEntry ----
    def create_waitlist_entry(self, payload, headers):
        return self._request("POST", "/marina/waitlist", payload, headers)

    def get_waitlist_entry(self, entry_id, headers):
        return self._request("GET", f"/marina/waitlist/{entry_id}", headers=headers)

    def list_waitlist(self, headers, params=None):
        return self._request("GET", "/marina/waitlist", headers=headers, params=params)

    def promote_waitlist(self, payload, headers):
        return self._request("POST", "/marina/waitlist/promote", payload, headers)

    def accept_waitlist_offer(self, entry_id, expected_rack_version, headers):
        return self._request("POST", f"/marina/waitlist/{entry_id}/accept",
                             {"expected_rack_version": expected_rack_version}, headers)

    def lapse_waitlist_offer(self, entry_id, headers):
        return self._request("POST", f"/marina/waitlist/{entry_id}/lapse", {}, headers)

    def withdraw_waitlist_entry(self, entry_id, headers):
        return self._request("POST", f"/marina/waitlist/{entry_id}/withdraw", {}, headers)

    # ---- LaunchRequest ----
    def create_launch_request(self, payload, headers):
        return self._request("POST", "/marina/launch-requests", payload, headers)

    def get_launch_request(self, launch_id, headers):
        return self._request("GET", f"/marina/launch-requests/{launch_id}", headers=headers)

    def list_launch_requests(self, headers, params=None):
        return self._request("GET", "/marina/launch-requests", headers=headers, params=params)

    def schedule_launch(self, launch_id, headers):
        return self._request("POST", f"/marina/launch-requests/{launch_id}/schedule", {}, headers)

    def unschedule_launch(self, launch_id, headers):
        return self._request("POST", f"/marina/launch-requests/{launch_id}/unschedule", {}, headers)

    def splash_launch(self, launch_id, headers):
        return self._request("POST", f"/marina/launch-requests/{launch_id}/splash", {}, headers)

    def haul_back_launch(self, launch_id, headers):
        return self._request("POST", f"/marina/launch-requests/{launch_id}/haul-back", {}, headers)

    def cancel_launch(self, launch_id, headers):
        return self._request("POST", f"/marina/launch-requests/{launch_id}/cancel", {}, headers)

    # ---- ForkliftSlot ----
    def get_forklift_slot(self, slot_id, headers):
        return self._request("GET", f"/marina/forklift-slots/{slot_id}", headers=headers)

    def list_forklift_slots(self, headers, params=None):
        return self._request("GET", "/marina/forklift-slots", headers=headers, params=params)

    # ---- ServiceOrder ----
    def create_service_order(self, payload, headers):
        return self._request("POST", "/marina/service-orders", payload, headers)

    def get_service_order(self, order_id, headers):
        return self._request("GET", f"/marina/service-orders/{order_id}", headers=headers)

    def list_service_orders(self, headers, params=None):
        return self._request("GET", "/marina/service-orders", headers=headers, params=params)

    def fulfill_service_order(self, order_id, headers):
        return self._request("POST", f"/marina/service-orders/{order_id}/fulfill", {}, headers)

    def cancel_service_order(self, order_id, headers):
        return self._request("POST", f"/marina/service-orders/{order_id}/cancel", {}, headers)

    # ---- StorageInvoice ----
    def create_invoice(self, payload, headers):
        return self._request("POST", "/marina/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/marina/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/marina/invoices", headers=headers, params=params)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/marina/invoices/{invoice_id}/pay", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/marina/invoices/{invoice_id}/void", {}, headers)


api_client = ApiClient()
