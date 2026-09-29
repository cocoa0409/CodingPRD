"""API client: one method per endpoint published by the PRD."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed endpoint surface for the military household-goods move API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ------------------------------------------------------------------
    # Service members
    # ------------------------------------------------------------------

    def create_service_member(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/hhg/service-members", payload, headers)

    def get_service_member(self, member_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/hhg/service-members/{member_id}", headers=headers
        )

    def list_service_member_orders(
        self, member_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/hhg/service-members/{member_id}/orders", headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # PCS orders
    # ------------------------------------------------------------------

    def create_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/hhg/orders", payload, headers)

    def get_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/hhg/orders/{order_id}", headers=headers)

    def amend_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/hhg/orders/{order_id}/amend", payload, headers)

    def list_order_counseling_sessions(
        self, order_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/hhg/orders/{order_id}/counseling-sessions", headers=headers,
            params=params,
        )

    def list_order_entitlements(
        self, order_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/hhg/orders/{order_id}/entitlements", headers=headers,
            params=params,
        )

    def list_order_shipments(
        self, order_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/hhg/orders/{order_id}/shipments", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Counseling sessions
    # ------------------------------------------------------------------

    def create_counseling_session(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/hhg/counseling-sessions", payload, headers)

    def get_counseling_session(self, session_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/hhg/counseling-sessions/{session_id}", headers=headers
        )

    def complete_counseling_session(
        self, session_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/counseling-sessions/{session_id}/complete", payload, headers
        )

    def list_counseling_session_entitlements(
        self, session_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/hhg/counseling-sessions/{session_id}/entitlements",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Entitlements
    # ------------------------------------------------------------------

    def get_entitlement(self, entitlement_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/hhg/entitlements/{entitlement_id}", headers=headers
        )

    def authorize_entitlement(
        self, entitlement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/entitlements/{entitlement_id}/authorize", payload, headers
        )

    def create_excess_cost_waiver(
        self, entitlement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/entitlements/{entitlement_id}/excess-cost-waivers",
            payload, headers,
        )

    def revoke_waiver(
        self,
        entitlement_id: str,
        payload: Optional[Dict[str, Any]],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/hhg/entitlements/{entitlement_id}/revoke-waiver",
            payload, headers,
        )

    def resume_entitlement(
        self,
        entitlement_id: str,
        payload: Optional[Dict[str, Any]],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/hhg/entitlements/{entitlement_id}/resume", payload, headers
        )

    def list_entitlement_shipments(
        self, entitlement_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/hhg/entitlements/{entitlement_id}/shipments", headers=headers,
            params=params,
        )

    def get_weight_ledger(self, entitlement_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/hhg/entitlements/{entitlement_id}/weight-ledger", headers=headers
        )

    # ------------------------------------------------------------------
    # Transportation service providers
    # ------------------------------------------------------------------

    def create_tsp(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/hhg/tsps", payload, headers)

    def get_tsp(self, tsp_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/hhg/tsps/{tsp_id}", headers=headers)

    def list_tsp_capacity_blocks(
        self, tsp_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/hhg/tsps/{tsp_id}/capacity-blocks", headers=headers, params=params
        )

    def list_tsp_shipments(
        self, tsp_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/hhg/tsps/{tsp_id}/shipments", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Capacity blocks
    # ------------------------------------------------------------------

    def create_capacity_block(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/hhg/capacity-blocks", payload, headers)

    def get_capacity_block(self, block_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/hhg/capacity-blocks/{block_id}", headers=headers)

    def create_award(
        self, block_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/capacity-blocks/{block_id}/awards", payload, headers
        )

    def release_award(
        self, block_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/capacity-blocks/{block_id}/release-award", payload, headers
        )

    def list_capacity_block_shipments(
        self, block_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/hhg/capacity-blocks/{block_id}/shipments", headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Shipments
    # ------------------------------------------------------------------

    def create_shipment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/hhg/shipments", payload, headers)

    def list_shipments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/hhg/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/hhg/shipments/{shipment_id}", headers=headers)

    def list_superseding_shipments(
        self, shipment_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/hhg/shipments/{shipment_id}/superseding-shipments",
            headers=headers, params=params,
        )

    def survey_shipment(
        self, shipment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/shipments/{shipment_id}/survey", payload, headers
        )

    def pack_shipment(
        self, shipment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/shipments/{shipment_id}/pack", payload, headers
        )

    def pickup_shipment(
        self, shipment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/shipments/{shipment_id}/pickup", payload, headers
        )

    def record_actual_weight(
        self, shipment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/shipments/{shipment_id}/record-actual-weight",
            payload, headers,
        )

    def dispute_weight(
        self, shipment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/shipments/{shipment_id}/dispute-weight", payload, headers
        )

    def reweigh_shipment(
        self, shipment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/shipments/{shipment_id}/reweigh", payload, headers
        )

    def reconcile_weight(
        self,
        shipment_id: str,
        payload: Optional[Dict[str, Any]],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/hhg/shipments/{shipment_id}/reconcile-weight", payload, headers
        )

    def deliver_shipment(
        self, shipment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/shipments/{shipment_id}/deliver", payload, headers
        )

    def cancel_shipment(
        self, shipment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/shipments/{shipment_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------
    # Pro-gear declarations
    # ------------------------------------------------------------------

    def create_pro_gear_declaration(
        self, shipment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/shipments/{shipment_id}/pro-gear-declarations",
            payload, headers,
        )

    def list_shipment_pro_gear_declarations(
        self, shipment_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/hhg/shipments/{shipment_id}/pro-gear-declarations",
            headers=headers, params=params,
        )

    def get_pro_gear_declaration(self, declaration_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/hhg/pro-gear-declarations/{declaration_id}", headers=headers
        )

    def verify_pro_gear_declaration(
        self, declaration_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/pro-gear-declarations/{declaration_id}/verify",
            payload, headers,
        )

    def reject_pro_gear_declaration(
        self, declaration_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/pro-gear-declarations/{declaration_id}/reject",
            payload, headers,
        )

    def resubmit_pro_gear_declaration(
        self, declaration_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/pro-gear-declarations/{declaration_id}/resubmit",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Storage in transit
    # ------------------------------------------------------------------

    def create_sit_authorization(
        self, shipment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/shipments/{shipment_id}/sit-authorizations", payload, headers
        )

    def list_shipment_sit_authorizations(
        self, shipment_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/hhg/shipments/{shipment_id}/sit-authorizations", headers=headers,
            params=params,
        )

    def get_sit_authorization(self, sit_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/hhg/sit-authorizations/{sit_id}", headers=headers
        )

    def authorize_sit(
        self, sit_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/sit-authorizations/{sit_id}/authorize", payload, headers
        )

    def extend_sit(
        self, sit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/sit-authorizations/{sit_id}/extend", payload, headers
        )

    def release_sit(
        self, sit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/sit-authorizations/{sit_id}/release", payload, headers
        )

    # ------------------------------------------------------------------
    # Loss and damage claims
    # ------------------------------------------------------------------

    def create_claim(
        self, shipment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/shipments/{shipment_id}/claims", payload, headers
        )

    def list_shipment_claims(
        self, shipment_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/hhg/shipments/{shipment_id}/claims", headers=headers, params=params
        )

    def get_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/hhg/claims/{claim_id}", headers=headers)

    def create_claim_item(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/claims/{claim_id}/claim-items", payload, headers
        )

    def list_claim_items(
        self, claim_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/hhg/claims/{claim_id}/claim-items", headers=headers, params=params
        )

    def get_claim_item(self, item_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/hhg/claim-items/{item_id}", headers=headers)

    def submit_claim(
        self, claim_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/claims/{claim_id}/submit", payload, headers
        )

    def review_claim(
        self, claim_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/claims/{claim_id}/review", payload, headers
        )

    def request_claim_info(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/claims/{claim_id}/request-info", payload, headers
        )

    def provide_claim_info(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/claims/{claim_id}/provide-info", payload, headers
        )

    def disposition_claim_item(
        self, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/claim-items/{item_id}/disposition", payload, headers
        )

    def settle_claim(
        self, claim_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/claims/{claim_id}/settle", payload, headers
        )

    def deny_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/hhg/claims/{claim_id}/deny", payload, headers)

    # ------------------------------------------------------------------
    # Personally procured moves
    # ------------------------------------------------------------------

    def create_ppm_submission(
        self, shipment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/shipments/{shipment_id}/ppm-submissions", payload, headers
        )

    def list_shipment_ppm_submissions(
        self, shipment_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/hhg/shipments/{shipment_id}/ppm-submissions", headers=headers,
            params=params,
        )

    def get_ppm_submission(self, ppm_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/hhg/ppm-submissions/{ppm_id}", headers=headers)

    def approve_ppm_submission(
        self, ppm_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/ppm-submissions/{ppm_id}/approve", payload, headers
        )

    # ------------------------------------------------------------------
    # Notification obligations
    # ------------------------------------------------------------------

    def list_shipment_notifications(
        self, shipment_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/hhg/shipments/{shipment_id}/notifications", headers=headers,
            params=params,
        )

    def get_notification(self, notification_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/hhg/notifications/{notification_id}", headers=headers
        )

    def dispatch_notification(
        self, notification_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hhg/notifications/{notification_id}/dispatch", payload, headers
        )


api_client = ApiClient()
