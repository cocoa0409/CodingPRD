"""API client: one method per endpoint defined in the PRD."""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin typed wrapper over the keg pool tracking HTTP surface."""

    # --- Logical clock ---------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Brewers ---------------------------------------------------------

    def create_brewer(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/brewers", payload, headers)

    def get_brewer(self, brewer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/brewers/{brewer_id}", headers=headers)

    def get_brewer_loss_rate(
        self, brewer_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/brewers/{brewer_id}/loss-rate", headers=headers, params=params
        )

    def set_brewer_status(self, brewer_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/brewers/{brewer_id}/status", payload, headers
        )

    # --- Distributors ----------------------------------------------------

    def create_distributor(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/distributors", payload, headers)

    def get_distributor(self, distributor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/distributors/{distributor_id}", headers=headers)

    def set_cooperation_agreement(
        self, distributor_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/distributors/{distributor_id}/cooperation-agreement",
            payload,
            headers,
        )

    # --- Pools and kegs --------------------------------------------------

    def create_pool(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/pools", payload, headers)

    def get_pool(self, pool_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/pools/{pool_id}", headers=headers)

    def import_keg(self, pool_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"/pools/{pool_id}/kegs", payload, headers)

    def list_pool_kegs(
        self, pool_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/pools/{pool_id}/kegs", headers=headers, params=params
        )

    def get_keg(self, keg_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/kegs/{keg_id}", headers=headers)

    def list_kegs(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/kegs", headers=headers, params=params)

    def scan_keg(self, keg_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"/kegs/{keg_id}/scan", payload, headers)

    def get_keg_dwell(self, keg_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/kegs/{keg_id}/dwell", headers=headers)

    def replenishment_sweep(self, pool_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/pools/{pool_id}/replenishment-sweep", {}, headers
        )

    # --- Scan events -----------------------------------------------------

    def get_scan_event(self, scan_event_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/scan-events/{scan_event_id}", headers=headers)

    def list_scan_events(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/scan-events", headers=headers, params=params)

    # --- Float agreements ------------------------------------------------

    def create_float_agreement(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/float-agreements", payload, headers)

    def activate_float_agreement(
        self, agreement_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/float-agreements/{agreement_id}/activate", payload, headers
        )

    def terminate_float_agreement(
        self, agreement_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/float-agreements/{agreement_id}/terminate", payload, headers
        )

    def get_float_agreement(self, agreement_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/float-agreements/{agreement_id}", headers=headers
        )

    def list_float_agreements(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request("GET", "/float-agreements", headers=headers, params=params)

    # --- Issuance orders -------------------------------------------------

    def create_issuance_order(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/issuance-orders", payload, headers)

    def allocate_issuance_order(
        self, order_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/issuance-orders/{order_id}/allocate", payload, headers
        )

    def dispatch_issuance_order(
        self, order_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/issuance-orders/{order_id}/dispatch", payload, headers
        )

    def cancel_issuance_order(
        self, order_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/issuance-orders/{order_id}/cancel", payload, headers
        )

    def get_issuance_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/issuance-orders/{order_id}", headers=headers)

    def list_issuance_orders(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request("GET", "/issuance-orders", headers=headers, params=params)

    # --- Service centres and cycles --------------------------------------

    def create_service_center(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/service-centers", payload, headers)

    def get_service_center(self, center_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/service-centers/{center_id}", headers=headers)

    def create_service_cycle(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/service-cycles", payload, headers)

    def record_service_step(
        self, cycle_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/service-cycles/{cycle_id}/record-step", payload, headers
        )

    def release_service_cycle(
        self, cycle_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/service-cycles/{cycle_id}/release", payload, headers
        )

    def get_service_cycle(self, cycle_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/service-cycles/{cycle_id}", headers=headers)

    def list_service_cycles(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request("GET", "/service-cycles", headers=headers, params=params)

    # --- Loss assessments and chargebacks --------------------------------

    def create_loss_assessment(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/loss-assessments", payload, headers)

    def dispute_loss_assessment(
        self, assessment_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/loss-assessments/{assessment_id}/dispute", payload, headers
        )

    def resolve_loss_assessment(
        self, assessment_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/loss-assessments/{assessment_id}/resolve", payload, headers
        )

    def chargeback_resolution(
        self, assessment_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/loss-assessments/{assessment_id}/chargeback-resolution",
            payload,
            headers,
        )

    def get_loss_assessment(self, assessment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/loss-assessments/{assessment_id}", headers=headers
        )

    def list_loss_assessments(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request("GET", "/loss-assessments", headers=headers, params=params)

    # --- Reconciliation claims -------------------------------------------

    def create_reconciliation_claim(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/reconciliation-claims", payload, headers)

    def respond_reconciliation_claim(
        self, claim_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/reconciliation-claims/{claim_id}/respond", payload, headers
        )

    def get_reconciliation_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/reconciliation-claims/{claim_id}", headers=headers
        )

    def list_reconciliation_claims(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", "/reconciliation-claims", headers=headers, params=params
        )

    # --- Return incentives -----------------------------------------------

    def get_return_incentive(self, accrual_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/return-incentives/{accrual_id}", headers=headers)

    def list_return_incentives(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request("GET", "/return-incentives", headers=headers, params=params)

    def pay_return_incentive(
        self, accrual_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/return-incentives/{accrual_id}/pay", payload, headers
        )

    # --- Theft investigations --------------------------------------------

    def create_theft_investigation(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/theft-investigations", payload, headers)

    def set_investigation_status(
        self, investigation_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/theft-investigations/{investigation_id}/status",
            payload,
            headers,
        )

    def get_theft_investigation(self, investigation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/theft-investigations/{investigation_id}", headers=headers
        )

    def list_theft_investigations(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", "/theft-investigations", headers=headers, params=params
        )

    # --- Commodity index -------------------------------------------------

    def post_commodity_index(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/commodity-index", payload, headers)

    def list_commodity_index(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request("GET", "/commodity-index", headers=headers, params=params)

    # --- Raw escape hatch -------------------------------------------------

    def raw(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[dict] = None,
    ):
        """Send an arbitrary request; used by header/authentication probes."""
        return self._request(method, path, payload, headers, params)


api_client = ApiClient()
