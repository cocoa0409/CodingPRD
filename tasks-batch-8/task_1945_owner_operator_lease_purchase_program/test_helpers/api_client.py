"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/lease-program"


class ApiClient(GenericApiClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The harness restarts the server (SIGKILL + respawn) before every
        # test under per-test-server isolation. A keep-alive connection pooled
        # from the previous server process then surfaces as RemoteDisconnected
        # or ConnectionResetError when reused mid-test. Forcing
        # `Connection: close` on every request keeps the session pool free of
        # stale sockets; transport hygiene only, no semantic effect.
        self.session.headers["Connection"] = "close"

    # --- OwnerOperator ---
    def create_owner_operator(self, payload, headers):
        return self._request("POST", f"{PREFIX}/owner-operators", payload, headers)

    def get_owner_operator(self, operator_id, headers):
        return self._request("GET", f"{PREFIX}/owner-operators/{operator_id}", headers=headers)

    # --- Truck ---
    def create_truck(self, payload, headers):
        return self._request("POST", f"{PREFIX}/trucks", payload, headers)

    def get_truck(self, truck_id, headers):
        return self._request("GET", f"{PREFIX}/trucks/{truck_id}", headers=headers)

    def confirm_truck_return(self, truck_id, headers):
        return self._request("POST", f"{PREFIX}/trucks/{truck_id}/confirm-return", {}, headers)

    def relist_truck(self, truck_id, headers):
        return self._request("POST", f"{PREFIX}/trucks/{truck_id}/relist", {}, headers)

    # --- LeaseAgreement ---
    def create_lease_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/lease-agreements", payload, headers)

    def list_lease_agreements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/lease-agreements", headers=headers, params=params)

    def get_lease_agreement(self, lease_id, headers):
        return self._request("GET", f"{PREFIX}/lease-agreements/{lease_id}", headers=headers)

    def activate_lease(self, lease_id, headers):
        return self._request("POST", f"{PREFIX}/lease-agreements/{lease_id}/activate", {}, headers)

    def declare_default(self, lease_id, headers):
        return self._request("POST", f"{PREFIX}/lease-agreements/{lease_id}/declare-default", {}, headers)

    def cure_default(self, lease_id, payload, headers):
        return self._request("POST", f"{PREFIX}/lease-agreements/{lease_id}/cure-default", payload, headers)

    def terminate_lease(self, lease_id, headers):
        return self._request("POST", f"{PREFIX}/lease-agreements/{lease_id}/terminate", {}, headers)

    def complete_lease(self, lease_id, headers):
        return self._request("POST", f"{PREFIX}/lease-agreements/{lease_id}/complete", {}, headers)

    # --- SettlementStatement ---
    def create_settlement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/settlement-statements", payload, headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/settlement-statements", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"{PREFIX}/settlement-statements/{settlement_id}", headers=headers)

    def issue_settlement(self, settlement_id, headers):
        return self._request("POST", f"{PREFIX}/settlement-statements/{settlement_id}/issue", {}, headers)

    def dispute_settlement(self, settlement_id, headers):
        return self._request("POST", f"{PREFIX}/settlement-statements/{settlement_id}/dispute", {}, headers)

    def reissue_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"{PREFIX}/settlement-statements/{settlement_id}/reissue", payload, headers)

    def finalize_settlement(self, settlement_id, headers):
        return self._request("POST", f"{PREFIX}/settlement-statements/{settlement_id}/finalize", {}, headers)

    # --- EscrowAccount ---
    def list_escrow_accounts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/escrow-accounts", headers=headers, params=params)

    def get_escrow_account(self, escrow_id, headers):
        return self._request("GET", f"{PREFIX}/escrow-accounts/{escrow_id}", headers=headers)

    def disburse_escrow(self, escrow_id, headers):
        return self._request("POST", f"{PREFIX}/escrow-accounts/{escrow_id}/disburse", {}, headers)

    # --- LaneAssignment ---
    def create_lane_assignment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/lane-assignments", payload, headers)

    def list_lane_assignments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/lane-assignments", headers=headers, params=params)

    def get_lane_assignment(self, lane_id, headers):
        return self._request("GET", f"{PREFIX}/lane-assignments/{lane_id}", headers=headers)

    def accept_lane(self, lane_id, headers):
        return self._request("POST", f"{PREFIX}/lane-assignments/{lane_id}/accept", {}, headers)

    def decline_lane(self, lane_id, headers):
        return self._request("POST", f"{PREFIX}/lane-assignments/{lane_id}/decline", {}, headers)

    def revoke_lane(self, lane_id, headers):
        return self._request("POST", f"{PREFIX}/lane-assignments/{lane_id}/revoke", {}, headers)

    # --- ServiceBay ---
    def create_service_bay(self, payload, headers):
        return self._request("POST", f"{PREFIX}/service-bays", payload, headers)

    def get_service_bay(self, bay_id, headers):
        return self._request("GET", f"{PREFIX}/service-bays/{bay_id}", headers=headers)

    # --- MaintenanceWorkOrder ---
    def create_work_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/maintenance-work-orders", payload, headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/maintenance-work-orders", headers=headers, params=params)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"{PREFIX}/maintenance-work-orders/{work_order_id}", headers=headers)

    def complete_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/maintenance-work-orders/{work_order_id}/complete", payload, headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"{PREFIX}/maintenance-work-orders/{work_order_id}/cancel", {}, headers)

    # --- ComplianceDocument ---
    def create_compliance_document(self, payload, headers):
        return self._request("POST", f"{PREFIX}/compliance-documents", payload, headers)

    def list_compliance_documents(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/compliance-documents", headers=headers, params=params)

    def get_compliance_document(self, doc_id, headers):
        return self._request("GET", f"{PREFIX}/compliance-documents/{doc_id}", headers=headers)

    def verify_compliance_document(self, doc_id, headers):
        return self._request("POST", f"{PREFIX}/compliance-documents/{doc_id}/verify", {}, headers)

    def reject_compliance_document(self, doc_id, payload, headers):
        return self._request("POST", f"{PREFIX}/compliance-documents/{doc_id}/reject", payload, headers)

    # --- BuyoutQuote ---
    def create_buyout_quote(self, payload, headers):
        return self._request("POST", f"{PREFIX}/buyout-quotes", payload, headers)

    def list_buyout_quotes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/buyout-quotes", headers=headers, params=params)

    def get_buyout_quote(self, quote_id, headers):
        return self._request("GET", f"{PREFIX}/buyout-quotes/{quote_id}", headers=headers)

    def accept_buyout_quote(self, quote_id, headers):
        return self._request("POST", f"{PREFIX}/buyout-quotes/{quote_id}/accept", {}, headers)

    def decline_buyout_quote(self, quote_id, headers):
        return self._request("POST", f"{PREFIX}/buyout-quotes/{quote_id}/decline", {}, headers)

    # --- Test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
