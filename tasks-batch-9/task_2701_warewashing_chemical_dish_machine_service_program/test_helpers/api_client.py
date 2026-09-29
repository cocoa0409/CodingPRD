"""
Endpoint client for the Warewashing API — one method per row of the §4 table.

Every path is mounted under the `/warewashing` prefix. Methods return the raw
`requests.Response` so tests can assert on status codes as well as bodies.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/warewashing"


class WarewashingApiClient(GenericApiClient):
    """One method per endpoint of §4."""

    # ─── Logical clock (§2.4) ──────────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        """POST /warewashing/_clock/set_current_utc"""
        return self._request(
            "POST", f"{BASE}/_clock/set_current_utc", payload, headers
        )

    # ─── Customers (§3.1) ──────────────────────────────────────────────

    def create_customer(self, payload: Dict[str, Any], headers: Dict):
        """POST /warewashing/customers"""
        return self._request("POST", f"{BASE}/customers", payload, headers)

    def get_customer(self, customer_id: str, headers: Dict):
        """GET /warewashing/customers/{customer_id}"""
        return self._request("GET", f"{BASE}/customers/{customer_id}", None, headers)

    # ─── Sites (§3.1) ──────────────────────────────────────────────────

    def create_site(self, payload: Dict[str, Any], headers: Dict):
        """POST /warewashing/sites"""
        return self._request("POST", f"{BASE}/sites", payload, headers)

    def get_site(self, site_id: str, headers: Dict):
        """GET /warewashing/sites/{site_id}"""
        return self._request("GET", f"{BASE}/sites/{site_id}", None, headers)

    def list_sites(self, headers: Dict, params: Optional[Dict] = None):
        """GET /warewashing/sites"""
        return self._request("GET", f"{BASE}/sites", params, headers)

    # ─── Chemical catalog (§3.1) ───────────────────────────────────────

    def create_chemical_product(self, payload: Dict[str, Any], headers: Dict):
        """POST /warewashing/chemical-products"""
        return self._request("POST", f"{BASE}/chemical-products", payload, headers)

    def get_chemical_product(self, product_id: str, headers: Dict):
        """GET /warewashing/chemical-products/{product_id}"""
        return self._request(
            "GET", f"{BASE}/chemical-products/{product_id}", None, headers
        )

    # ─── Machine catalog (§3.1) ────────────────────────────────────────

    def create_machine_model(self, payload: Dict[str, Any], headers: Dict):
        """POST /warewashing/machine-models"""
        return self._request("POST", f"{BASE}/machine-models", payload, headers)

    def get_machine_model(self, model_id: str, headers: Dict):
        """GET /warewashing/machine-models/{model_id}"""
        return self._request("GET", f"{BASE}/machine-models/{model_id}", None, headers)

    # ─── Technician roster (§3.1) ──────────────────────────────────────

    def create_technician(self, payload: Dict[str, Any], headers: Dict):
        """POST /warewashing/technicians"""
        return self._request("POST", f"{BASE}/technicians", payload, headers)

    def get_technician(self, technician_id: str, headers: Dict):
        """GET /warewashing/technicians/{technician_id}"""
        return self._request(
            "GET", f"{BASE}/technicians/{technician_id}", None, headers
        )

    def update_technician(
        self, technician_id: str, payload: Dict[str, Any], headers: Dict
    ):
        """PATCH /warewashing/technicians/{technician_id}"""
        return self._request(
            "PATCH", f"{BASE}/technicians/{technician_id}", payload, headers
        )

    # ─── Service agreements (§3.2) ─────────────────────────────────────

    def create_service_agreement(self, payload: Dict[str, Any], headers: Dict):
        """POST /warewashing/service-agreements"""
        return self._request("POST", f"{BASE}/service-agreements", payload, headers)

    def get_service_agreement(self, agreement_id: str, headers: Dict):
        """GET /warewashing/service-agreements/{agreement_id}"""
        return self._request(
            "GET", f"{BASE}/service-agreements/{agreement_id}", None, headers
        )

    def list_service_agreements(self, headers: Dict, params: Optional[Dict] = None):
        """GET /warewashing/service-agreements"""
        return self._request("GET", f"{BASE}/service-agreements", params, headers)

    def activate_service_agreement(
        self, agreement_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        """POST /warewashing/service-agreements/{agreement_id}/activate"""
        return self._request(
            "POST",
            f"{BASE}/service-agreements/{agreement_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    def renew_service_agreement(
        self, agreement_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        """POST /warewashing/service-agreements/{agreement_id}/renewal"""
        return self._request(
            "POST",
            f"{BASE}/service-agreements/{agreement_id}/renewal",
            payload if payload is not None else {},
            headers,
        )

    def terminate_service_agreement(
        self, agreement_id: str, payload: Dict[str, Any], headers: Dict
    ):
        """POST /warewashing/service-agreements/{agreement_id}/terminate"""
        return self._request(
            "POST",
            f"{BASE}/service-agreements/{agreement_id}/terminate",
            payload,
            headers,
        )

    # ─── Machine placements (§3.3) ─────────────────────────────────────

    def create_machine_placement(self, payload: Dict[str, Any], headers: Dict):
        """POST /warewashing/machine-placements"""
        return self._request("POST", f"{BASE}/machine-placements", payload, headers)

    def get_machine_placement(self, placement_id: str, headers: Dict):
        """GET /warewashing/machine-placements/{placement_id}"""
        return self._request(
            "GET", f"{BASE}/machine-placements/{placement_id}", None, headers
        )

    def list_machine_placements(self, headers: Dict, params: Optional[Dict] = None):
        """GET /warewashing/machine-placements"""
        return self._request("GET", f"{BASE}/machine-placements", params, headers)

    def install_machine_placement(
        self, placement_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        """POST /warewashing/machine-placements/{placement_id}/install"""
        return self._request(
            "POST",
            f"{BASE}/machine-placements/{placement_id}/install",
            payload if payload is not None else {},
            headers,
        )

    def create_retrieval_order(
        self, placement_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        """POST /warewashing/machine-placements/{placement_id}/retrieval-order"""
        return self._request(
            "POST",
            f"{BASE}/machine-placements/{placement_id}/retrieval-order",
            payload if payload is not None else {},
            headers,
        )

    def complete_retrieval(
        self, placement_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        """POST /warewashing/machine-placements/{placement_id}/retrieval-completion"""
        return self._request(
            "POST",
            f"{BASE}/machine-placements/{placement_id}/retrieval-completion",
            payload if payload is not None else {},
            headers,
        )

    # ─── Dispensers (§3.4) ─────────────────────────────────────────────

    def create_dispenser(self, payload: Dict[str, Any], headers: Dict):
        """POST /warewashing/dispensers"""
        return self._request("POST", f"{BASE}/dispensers", payload, headers)

    def get_dispenser(self, dispenser_id: str, headers: Dict):
        """GET /warewashing/dispensers/{dispenser_id}"""
        return self._request("GET", f"{BASE}/dispensers/{dispenser_id}", None, headers)

    def list_dispensers(self, headers: Dict, params: Optional[Dict] = None):
        """GET /warewashing/dispensers"""
        return self._request("GET", f"{BASE}/dispensers", params, headers)

    # ─── Calibration records (§3.6, read flat per §2.9) ────────────────

    def get_calibration_record(self, record_id: str, headers: Dict):
        """GET /warewashing/calibration-records/{record_id}"""
        return self._request(
            "GET", f"{BASE}/calibration-records/{record_id}", None, headers
        )

    def list_calibration_records(self, headers: Dict, params: Optional[Dict] = None):
        """GET /warewashing/calibration-records"""
        return self._request("GET", f"{BASE}/calibration-records", params, headers)

    def create_calibration_record(
        self, visit_id: str, payload: Dict[str, Any], headers: Dict
    ):
        """POST /warewashing/service-visits/{visit_id}/calibration-records"""
        return self._request(
            "POST",
            f"{BASE}/service-visits/{visit_id}/calibration-records",
            payload,
            headers,
        )

    # ─── Telemetry (§3.4) ──────────────────────────────────────────────

    def create_telemetry_reading(
        self, placement_id: str, payload: Dict[str, Any], headers: Dict
    ):
        """POST /warewashing/machine-placements/{placement_id}/telemetry-readings"""
        return self._request(
            "POST",
            f"{BASE}/machine-placements/{placement_id}/telemetry-readings",
            payload,
            headers,
        )

    def get_telemetry_reading(self, reading_id: str, headers: Dict):
        """GET /warewashing/telemetry-readings/{reading_id}"""
        return self._request(
            "GET", f"{BASE}/telemetry-readings/{reading_id}", None, headers
        )

    def list_telemetry_readings(self, headers: Dict, params: Optional[Dict] = None):
        """GET /warewashing/telemetry-readings"""
        return self._request("GET", f"{BASE}/telemetry-readings", params, headers)

    def get_telemetry_alert(self, alert_id: str, headers: Dict):
        """GET /warewashing/telemetry-alerts/{alert_id}"""
        return self._request(
            "GET", f"{BASE}/telemetry-alerts/{alert_id}", None, headers
        )

    def list_telemetry_alerts(self, headers: Dict, params: Optional[Dict] = None):
        """GET /warewashing/telemetry-alerts"""
        return self._request("GET", f"{BASE}/telemetry-alerts", params, headers)

    def acknowledge_telemetry_alert(
        self, alert_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        """POST /warewashing/telemetry-alerts/{alert_id}/acknowledge"""
        return self._request(
            "POST",
            f"{BASE}/telemetry-alerts/{alert_id}/acknowledge",
            payload if payload is not None else {},
            headers,
        )

    # ─── Service tickets (§3.5) ────────────────────────────────────────

    def create_service_ticket(self, payload: Dict[str, Any], headers: Dict):
        """POST /warewashing/service-tickets"""
        return self._request("POST", f"{BASE}/service-tickets", payload, headers)

    def get_service_ticket(self, ticket_id: str, headers: Dict):
        """GET /warewashing/service-tickets/{ticket_id}"""
        return self._request(
            "GET", f"{BASE}/service-tickets/{ticket_id}", None, headers
        )

    def list_service_tickets(self, headers: Dict, params: Optional[Dict] = None):
        """GET /warewashing/service-tickets"""
        return self._request("GET", f"{BASE}/service-tickets", params, headers)

    def dispatch_service_ticket(
        self, ticket_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        """POST /warewashing/service-tickets/{ticket_id}/dispatch"""
        return self._request(
            "POST",
            f"{BASE}/service-tickets/{ticket_id}/dispatch",
            payload if payload is not None else {},
            headers,
        )

    # ─── Service visits (§3.6) ─────────────────────────────────────────

    def create_service_visit(self, payload: Dict[str, Any], headers: Dict):
        """POST /warewashing/service-visits"""
        return self._request("POST", f"{BASE}/service-visits", payload, headers)

    def get_service_visit(self, visit_id: str, headers: Dict):
        """GET /warewashing/service-visits/{visit_id}"""
        return self._request(
            "GET", f"{BASE}/service-visits/{visit_id}", None, headers
        )

    def list_service_visits(self, headers: Dict, params: Optional[Dict] = None):
        """GET /warewashing/service-visits"""
        return self._request("GET", f"{BASE}/service-visits", params, headers)

    def arrive_service_visit(
        self, visit_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        """POST /warewashing/service-visits/{visit_id}/arrive"""
        return self._request(
            "POST",
            f"{BASE}/service-visits/{visit_id}/arrive",
            payload if payload is not None else {},
            headers,
        )

    def submit_service_visit(
        self, visit_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        """POST /warewashing/service-visits/{visit_id}/submit"""
        return self._request(
            "POST",
            f"{BASE}/service-visits/{visit_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def verify_service_visit(
        self, visit_id: str, payload: Dict[str, Any], headers: Dict
    ):
        """POST /warewashing/service-visits/{visit_id}/verify"""
        return self._request(
            "POST", f"{BASE}/service-visits/{visit_id}/verify", payload, headers
        )

    # ─── Chemical deliveries (§3.7) ────────────────────────────────────

    def create_chemical_delivery(self, payload: Dict[str, Any], headers: Dict):
        """POST /warewashing/chemical-deliveries"""
        return self._request("POST", f"{BASE}/chemical-deliveries", payload, headers)

    def get_chemical_delivery(self, delivery_id: str, headers: Dict):
        """GET /warewashing/chemical-deliveries/{delivery_id}"""
        return self._request(
            "GET", f"{BASE}/chemical-deliveries/{delivery_id}", None, headers
        )

    def list_chemical_deliveries(self, headers: Dict, params: Optional[Dict] = None):
        """GET /warewashing/chemical-deliveries"""
        return self._request("GET", f"{BASE}/chemical-deliveries", params, headers)

    def void_chemical_delivery(
        self, delivery_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        """POST /warewashing/chemical-deliveries/{delivery_id}/void"""
        return self._request(
            "POST",
            f"{BASE}/chemical-deliveries/{delivery_id}/void",
            payload if payload is not None else {},
            headers,
        )

    # ─── Usage variance reviews (§3.7) ─────────────────────────────────

    def create_usage_variance_review(self, payload: Dict[str, Any], headers: Dict):
        """POST /warewashing/usage-variance-reviews"""
        return self._request(
            "POST", f"{BASE}/usage-variance-reviews", payload, headers
        )

    def get_usage_variance_review(self, review_id: str, headers: Dict):
        """GET /warewashing/usage-variance-reviews/{review_id}"""
        return self._request(
            "GET", f"{BASE}/usage-variance-reviews/{review_id}", None, headers
        )

    def list_usage_variance_reviews(self, headers: Dict, params: Optional[Dict] = None):
        """GET /warewashing/usage-variance-reviews"""
        return self._request("GET", f"{BASE}/usage-variance-reviews", params, headers)

    def publish_usage_variance_review(
        self, review_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        """POST /warewashing/usage-variance-reviews/{review_id}/publish"""
        return self._request(
            "POST",
            f"{BASE}/usage-variance-reviews/{review_id}/publish",
            payload if payload is not None else {},
            headers,
        )

    def close_usage_variance_review(
        self, review_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        """POST /warewashing/usage-variance-reviews/{review_id}/close"""
        return self._request(
            "POST",
            f"{BASE}/usage-variance-reviews/{review_id}/close",
            payload if payload is not None else {},
            headers,
        )

    # ─── Investigation cases (§3.8) ────────────────────────────────────

    def create_investigation_case(self, payload: Dict[str, Any], headers: Dict):
        """POST /warewashing/investigation-cases"""
        return self._request("POST", f"{BASE}/investigation-cases", payload, headers)

    def get_investigation_case(self, case_id: str, headers: Dict):
        """GET /warewashing/investigation-cases/{case_id}"""
        return self._request(
            "GET", f"{BASE}/investigation-cases/{case_id}", None, headers
        )

    def list_investigation_cases(self, headers: Dict, params: Optional[Dict] = None):
        """GET /warewashing/investigation-cases"""
        return self._request("GET", f"{BASE}/investigation-cases", params, headers)

    def submit_case_for_review(
        self, case_id: str, payload: Dict[str, Any], headers: Dict
    ):
        """POST /warewashing/investigation-cases/{case_id}/submit-for-review"""
        return self._request(
            "POST",
            f"{BASE}/investigation-cases/{case_id}/submit-for-review",
            payload,
            headers,
        )

    def review_investigation_case(
        self, case_id: str, payload: Dict[str, Any], headers: Dict
    ):
        """POST /warewashing/investigation-cases/{case_id}/review"""
        return self._request(
            "POST", f"{BASE}/investigation-cases/{case_id}/review", payload, headers
        )

    # ─── Computed reads (§3.9) ─────────────────────────────────────────

    def get_sustainability_report(
        self, site_id: str, headers: Dict, params: Optional[Dict] = None
    ):
        """GET /warewashing/sites/{site_id}/sustainability-report"""
        return self._request(
            "GET", f"{BASE}/sites/{site_id}/sustainability-report", params, headers
        )

    def get_inspection_dossier(
        self, site_id: str, headers: Dict, params: Optional[Dict] = None
    ):
        """GET /warewashing/sites/{site_id}/inspection-dossier"""
        return self._request(
            "GET", f"{BASE}/sites/{site_id}/inspection-dossier", params, headers
        )
