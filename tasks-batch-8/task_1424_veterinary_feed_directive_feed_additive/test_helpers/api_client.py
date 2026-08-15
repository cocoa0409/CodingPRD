"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/vfd/_clock/set_current_utc", payload, headers)

    # --- VeterinaryClinic ---
    def create_clinic(self, payload, headers):
        return self._request("POST", "/vfd/clinics", payload, headers)

    def get_clinic(self, clinic_id, headers):
        return self._request("GET", f"/vfd/clinics/{clinic_id}", headers=headers)

    def list_clinics(self, headers, params=None):
        return self._request("GET", "/vfd/clinics", headers=headers, params=params)

    # --- Veterinarian ---
    def create_veterinarian(self, clinic_id, payload, headers):
        return self._request("POST", f"/vfd/clinics/{clinic_id}/veterinarians", payload, headers)

    def get_veterinarian(self, vet_id, headers):
        return self._request("GET", f"/vfd/veterinarians/{vet_id}", headers=headers)

    def list_veterinarians(self, clinic_id, headers, params=None):
        return self._request("GET", f"/vfd/clinics/{clinic_id}/veterinarians", headers=headers, params=params)

    def suspend_veterinarian(self, vet_id, headers):
        return self._request("POST", f"/vfd/veterinarians/{vet_id}/suspend", {}, headers)

    def reinstate_veterinarian(self, vet_id, headers):
        return self._request("POST", f"/vfd/veterinarians/{vet_id}/reinstate", {}, headers)

    def revoke_veterinarian(self, vet_id, headers):
        return self._request("POST", f"/vfd/veterinarians/{vet_id}/revoke", {}, headers)

    # --- Producer ---
    def create_producer(self, payload, headers):
        return self._request("POST", "/vfd/producers", payload, headers)

    def get_producer(self, producer_id, headers):
        return self._request("GET", f"/vfd/producers/{producer_id}", headers=headers)

    def list_producers(self, headers, params=None):
        return self._request("GET", "/vfd/producers", headers=headers, params=params)

    # --- AnimalGroup ---
    def create_animal_group(self, producer_id, payload, headers):
        return self._request("POST", f"/vfd/producers/{producer_id}/animal-groups", payload, headers)

    def get_animal_group(self, group_id, headers):
        return self._request("GET", f"/vfd/animal-groups/{group_id}", headers=headers)

    def list_animal_groups(self, producer_id, headers, params=None):
        return self._request("GET", f"/vfd/producers/{producer_id}/animal-groups", headers=headers, params=params)

    # --- VfdDrug ---
    def create_drug(self, payload, headers):
        return self._request("POST", "/vfd/drugs", payload, headers)

    def get_drug(self, drug_id, headers):
        return self._request("GET", f"/vfd/drugs/{drug_id}", headers=headers)

    def list_drugs(self, headers, params=None):
        return self._request("GET", "/vfd/drugs", headers=headers, params=params)

    # --- VcpVerification ---
    def create_vcp_verification(self, payload, headers):
        return self._request("POST", "/vfd/vcp-verifications", payload, headers)

    def get_vcp_verification(self, vcp_id, headers):
        return self._request("GET", f"/vfd/vcp-verifications/{vcp_id}", headers=headers)

    def list_vcp_verifications(self, headers, params=None):
        return self._request("GET", "/vfd/vcp-verifications", headers=headers, params=params)

    def revoke_vcp_verification(self, vcp_id, payload, headers):
        return self._request("POST", f"/vfd/vcp-verifications/{vcp_id}/revoke", payload, headers)

    # --- VfdAuthorization ---
    def create_vfd_authorization(self, payload, headers):
        return self._request("POST", "/vfd/vfd-authorizations", payload, headers)

    def get_vfd_authorization(self, vfd_id, headers):
        return self._request("GET", f"/vfd/vfd-authorizations/{vfd_id}", headers=headers)

    def list_vfd_authorizations(self, headers, params=None):
        return self._request("GET", "/vfd/vfd-authorizations", headers=headers, params=params)

    def list_producer_vfd_authorizations(self, producer_id, headers, params=None):
        return self._request("GET", f"/vfd/producers/{producer_id}/vfd-authorizations", headers=headers, params=params)

    def revoke_vfd_authorization(self, vfd_id, headers):
        return self._request("POST", f"/vfd/vfd-authorizations/{vfd_id}/revoke", {}, headers)

    # --- FeedMill ---
    def create_feed_mill(self, payload, headers):
        return self._request("POST", "/vfd/feed-mills", payload, headers)

    def get_feed_mill(self, mill_id, headers):
        return self._request("GET", f"/vfd/feed-mills/{mill_id}", headers=headers)

    # --- FeedOrder ---
    def create_feed_order(self, mill_id, payload, headers):
        return self._request("POST", f"/vfd/feed-mills/{mill_id}/feed-orders", payload, headers)

    def get_feed_order(self, order_id, headers):
        return self._request("GET", f"/vfd/feed-orders/{order_id}", headers=headers)

    def list_mill_feed_orders(self, mill_id, headers, params=None):
        return self._request("GET", f"/vfd/feed-mills/{mill_id}/feed-orders", headers=headers, params=params)

    def list_feed_orders(self, headers, params=None):
        return self._request("GET", "/vfd/feed-orders", headers=headers, params=params)

    def validate_feed_order(self, order_id, payload, headers):
        return self._request("POST", f"/vfd/feed-orders/{order_id}/validate", payload, headers)

    def reject_feed_order(self, order_id, payload, headers):
        return self._request("POST", f"/vfd/feed-orders/{order_id}/reject", payload, headers)

    def cancel_feed_order(self, order_id, headers):
        return self._request("POST", f"/vfd/feed-orders/{order_id}/cancel", {}, headers)

    def ship_feed_order(self, order_id, payload, headers):
        return self._request("POST", f"/vfd/feed-orders/{order_id}/ship", payload, headers)

    # --- FeedShipment ---
    def get_feed_shipment(self, shipment_id, headers):
        return self._request("GET", f"/vfd/feed-shipments/{shipment_id}", headers=headers)

    def list_order_shipments(self, order_id, headers, params=None):
        return self._request("GET", f"/vfd/feed-orders/{order_id}/feed-shipments", headers=headers, params=params)

    def deliver_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/vfd/feed-shipments/{shipment_id}/deliver", payload, headers)

    def return_shipment(self, shipment_id, headers):
        return self._request("POST", f"/vfd/feed-shipments/{shipment_id}/return", {}, headers)

    def reject_receipt_shipment(self, shipment_id, headers):
        return self._request("POST", f"/vfd/feed-shipments/{shipment_id}/reject-receipt", {}, headers)

    # --- WithdrawalPlan ---
    def get_withdrawal_plan(self, plan_id, headers):
        return self._request("GET", f"/vfd/withdrawal-plans/{plan_id}", headers=headers)

    def list_order_withdrawal_plans(self, order_id, headers):
        return self._request("GET", f"/vfd/feed-orders/{order_id}/withdrawal-plans", headers=headers)

    # --- DistributorAcknowledgment ---
    def create_distributor_acknowledgment(self, mill_id, payload, headers):
        return self._request("POST", f"/vfd/feed-mills/{mill_id}/distributor-acknowledgments", payload, headers)

    def list_mill_acknowledgments(self, mill_id, headers, params=None):
        return self._request("GET", f"/vfd/feed-mills/{mill_id}/distributor-acknowledgments", headers=headers, params=params)

    def list_distributor_acknowledgments(self, headers, params=None):
        return self._request("GET", "/vfd/distributor-acknowledgments", headers=headers, params=params)

    def get_distributor_acknowledgment(self, ack_id, headers):
        return self._request("GET", f"/vfd/distributor-acknowledgments/{ack_id}", headers=headers)

    # --- ResidueCase ---
    def create_residue_case(self, producer_id, payload, headers):
        return self._request("POST", f"/vfd/producers/{producer_id}/residue-cases", payload, headers)

    def get_residue_case(self, case_id, headers):
        return self._request("GET", f"/vfd/residue-cases/{case_id}", headers=headers)

    def list_producer_residue_cases(self, producer_id, headers, params=None):
        return self._request("GET", f"/vfd/producers/{producer_id}/residue-cases", headers=headers, params=params)

    def list_residue_cases(self, headers, params=None):
        return self._request("GET", "/vfd/residue-cases", headers=headers, params=params)

    def open_residue_investigation(self, case_id, headers):
        return self._request("POST", f"/vfd/residue-cases/{case_id}/open-investigation", {}, headers)

    def confirm_residue_case(self, case_id, payload, headers):
        return self._request("POST", f"/vfd/residue-cases/{case_id}/confirm", payload, headers)

    def dismiss_residue_case(self, case_id, headers):
        return self._request("POST", f"/vfd/residue-cases/{case_id}/dismiss", {}, headers)

    # --- AuditBundle ---
    def create_audit_bundle(self, producer_id, payload, headers):
        return self._request("POST", f"/vfd/producers/{producer_id}/audit-bundles", payload, headers)

    def get_audit_bundle(self, audit_id, headers):
        return self._request("GET", f"/vfd/audit-bundles/{audit_id}", headers=headers)

    def list_producer_audit_bundles(self, producer_id, headers, params=None):
        return self._request("GET", f"/vfd/producers/{producer_id}/audit-bundles", headers=headers, params=params)

    def record_produced(self, audit_id, headers):
        return self._request("POST", f"/vfd/audit-bundles/{audit_id}/record-produced", {}, headers)

    def close_audit_bundle(self, audit_id, headers):
        return self._request("POST", f"/vfd/audit-bundles/{audit_id}/close", {}, headers)

    def mark_audit_deficient(self, audit_id, headers):
        return self._request("POST", f"/vfd/audit-bundles/{audit_id}/mark-deficient", {}, headers)


api_client = ApiClient()
