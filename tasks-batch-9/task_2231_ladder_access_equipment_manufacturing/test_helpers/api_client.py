"""API client: one method per endpoint defined in the PRD (§4).

All business resources are mounted under `/ladder-ops`; the logical-clock
capability sits outside that mount.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/ladder-ops"


class ApiClient(GenericApiClient):
    """Thin PRD-shaped wrapper: every method maps to exactly one endpoint row."""

    # -----------------------------------------------------------------
    # Logical clock
    # -----------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Optional[Dict[str, str]] = None):
        """POST /_clock/set_current_utc — set the deterministic logical clock."""
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # -----------------------------------------------------------------
    # Products
    # -----------------------------------------------------------------
    def create_product(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/products", payload, headers)

    def get_product(self, product_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/products/{product_id}", headers=headers)

    def list_products(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/products", headers=headers, params=params)

    def freeze_design(
        self, product_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/products/{product_id}/freeze-design", payload, headers
        )

    def release_to_retail(
        self,
        product_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/products/{product_id}/release-to-retail",
            payload if payload is not None else {},
            headers,
        )

    def stop_ship(
        self, product_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/products/{product_id}/stop-ship", payload, headers
        )

    def resume_ship(
        self,
        product_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/products/{product_id}/resume-ship",
            payload if payload is not None else {},
            headers,
        )

    def list_product_documents(
        self, product_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{BASE}/products/{product_id}/documents", headers=headers, params=params
        )

    def get_liability_dossier(self, product_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/products/{product_id}/liability-dossier", headers=headers
        )

    # -----------------------------------------------------------------
    # Design revisions
    # -----------------------------------------------------------------
    def create_design_revision(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/design-revisions", payload, headers)

    def get_design_revision(self, revision_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/design-revisions/{revision_id}", headers=headers
        )

    def list_design_revisions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{BASE}/design-revisions", headers=headers, params=params
        )

    def submit_design_revision(
        self,
        revision_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/design-revisions/{revision_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def review_design_revision(
        self, revision_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/design-revisions/{revision_id}/review", payload, headers
        )

    def revise_design_revision(
        self,
        revision_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/design-revisions/{revision_id}/revise",
            payload if payload is not None else {},
            headers,
        )

    # -----------------------------------------------------------------
    # Product documents
    # -----------------------------------------------------------------
    def create_product_document(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/product-documents", payload, headers)

    def approve_product_document(
        self,
        document_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/product-documents/{document_id}/approve",
            payload if payload is not None else {},
            headers,
        )

    # -----------------------------------------------------------------
    # Test benches
    # -----------------------------------------------------------------
    def create_test_bench(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/test-benches", payload, headers)

    def get_test_bench(self, bench_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/test-benches/{bench_id}", headers=headers)

    # -----------------------------------------------------------------
    # Bench reservations
    # -----------------------------------------------------------------
    def create_bench_reservation(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"{BASE}/bench-reservations", payload, headers)

    def get_bench_reservation(self, reservation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/bench-reservations/{reservation_id}", headers=headers
        )

    def list_bench_reservations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{BASE}/bench-reservations", headers=headers, params=params
        )

    def cancel_bench_reservation(
        self,
        reservation_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/bench-reservations/{reservation_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    # -----------------------------------------------------------------
    # Test campaigns
    # -----------------------------------------------------------------
    def create_test_campaign(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/test-campaigns", payload, headers)

    def get_test_campaign(self, campaign_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/test-campaigns/{campaign_id}", headers=headers
        )

    def list_test_campaigns(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{BASE}/test-campaigns", headers=headers, params=params
        )

    def start_test_campaign(
        self, campaign_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/test-campaigns/{campaign_id}/start", payload, headers
        )

    def create_load_test(
        self, campaign_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/test-campaigns/{campaign_id}/load-tests", payload, headers
        )

    def list_load_tests(
        self, campaign_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{BASE}/test-campaigns/{campaign_id}/load-tests",
            headers=headers,
            params=params,
        )

    def conclude_test_campaign(
        self,
        campaign_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/test-campaigns/{campaign_id}/conclude",
            payload if payload is not None else {},
            headers,
        )

    # -----------------------------------------------------------------
    # Production lots
    # -----------------------------------------------------------------
    def create_production_lot(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/production-lots", payload, headers)

    def get_production_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/production-lots/{lot_id}", headers=headers)

    def list_production_lots(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{BASE}/production-lots", headers=headers, params=params
        )

    def start_production(
        self, lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/production-lots/{lot_id}/start-production", payload, headers
        )

    def create_joint_sample(
        self, lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/production-lots/{lot_id}/joint-samples", payload, headers
        )

    def list_joint_samples(
        self, lot_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{BASE}/production-lots/{lot_id}/joint-samples",
            headers=headers,
            params=params,
        )

    def release_production_lot(
        self,
        lot_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/production-lots/{lot_id}/release",
            payload if payload is not None else {},
            headers,
        )

    def quarantine_production_lot(
        self, lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/production-lots/{lot_id}/quarantine", payload, headers
        )

    def disposition_production_lot(
        self, lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/production-lots/{lot_id}/disposition", payload, headers
        )

    # -----------------------------------------------------------------
    # Listing bodies and listing records
    # -----------------------------------------------------------------
    def create_listing_body(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/listing-bodies", payload, headers)

    def create_listing_record(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/listing-records", payload, headers)

    def get_listing_record(self, record_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/listing-records/{record_id}", headers=headers
        )

    def list_listing_records(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{BASE}/listing-records", headers=headers, params=params
        )

    def grant_listing(
        self,
        record_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/listing-records/{record_id}/list",
            payload if payload is not None else {},
            headers,
        )

    def suspend_listing(
        self, record_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/listing-records/{record_id}/suspend", payload, headers
        )

    # -----------------------------------------------------------------
    # Consumer registrations
    # -----------------------------------------------------------------
    def create_consumer_registration(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"{BASE}/consumer-registrations", payload, headers)

    def get_consumer_registration(
        self, registration_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET", f"{BASE}/consumer-registrations/{registration_id}", headers=headers
        )

    def list_consumer_registrations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{BASE}/consumer-registrations", headers=headers, params=params
        )

    def acknowledge_recall(
        self, registration_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{BASE}/consumer-registrations/{registration_id}/acknowledge",
            payload,
            headers,
        )

    # -----------------------------------------------------------------
    # Field incidents
    # -----------------------------------------------------------------
    def create_field_incident(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/field-incidents", payload, headers)

    def get_field_incident(self, incident_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/field-incidents/{incident_id}", headers=headers
        )

    def list_field_incidents(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{BASE}/field-incidents", headers=headers, params=params
        )

    def investigate_field_incident(
        self,
        incident_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/field-incidents/{incident_id}/investigate",
            payload if payload is not None else {},
            headers,
        )

    def resolve_investigation(
        self, incident_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{BASE}/field-incidents/{incident_id}/resolve-investigation",
            payload,
            headers,
        )

    # -----------------------------------------------------------------
    # Corrective actions
    # -----------------------------------------------------------------
    def create_corrective_action(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"{BASE}/corrective-actions", payload, headers)

    def get_corrective_action(self, action_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/corrective-actions/{action_id}", headers=headers
        )

    def list_corrective_actions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{BASE}/corrective-actions", headers=headers, params=params
        )

    def verify_corrective_action(
        self,
        action_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/corrective-actions/{action_id}/verify",
            payload if payload is not None else {},
            headers,
        )

    # -----------------------------------------------------------------
    # Recall events
    # -----------------------------------------------------------------
    def create_recall_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/recall-events", payload, headers)

    def get_recall_event(self, recall_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/recall-events/{recall_id}", headers=headers)

    def list_recall_events(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{BASE}/recall-events", headers=headers, params=params
        )

    def announce_recall(
        self,
        recall_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/recall-events/{recall_id}/announce",
            payload if payload is not None else {},
            headers,
        )

    def notify_recall(
        self,
        recall_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/recall-events/{recall_id}/notify",
            payload if payload is not None else {},
            headers,
        )

    def close_recall(
        self,
        recall_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/recall-events/{recall_id}/close",
            payload if payload is not None else {},
            headers,
        )


api_client = ApiClient()
