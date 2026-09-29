"""Typed API client: one method per endpoint of the compliance API."""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX

Headers = Optional[Dict[str, str]]
Payload = Optional[Dict[str, Any]]
Params = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """Every path is served under the /compliance prefix (PRD 4)."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            payload={"to_iso8601": to_iso8601},
            headers=headers,
        )

    def set_clock_raw(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Applicable rules
    # ------------------------------------------------------------------

    def create_rule(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/applicable-rules", payload=payload, headers=headers
        )

    def get_rule(self, rule_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/applicable-rules/{rule_id}", headers=headers
        )

    def list_rules(self, params: Params = None, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/applicable-rules", params=params, headers=headers
        )

    # ------------------------------------------------------------------
    # Product categories
    # ------------------------------------------------------------------

    def create_category(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/product-categories", payload=payload, headers=headers
        )

    def get_category(self, category_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/product-categories/{category_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Category-rule mappings
    # ------------------------------------------------------------------

    def create_mapping(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/category-rule-mappings",
            payload=payload,
            headers=headers,
        )

    def get_mapping(self, mapping_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/category-rule-mappings/{mapping_id}", headers=headers
        )

    def list_mappings(self, params: Params = None, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/category-rule-mappings", params=params, headers=headers
        )

    def retire_mapping(self, mapping_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/category-rule-mappings/{mapping_id}/retire",
            payload={},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Suppliers
    # ------------------------------------------------------------------

    def create_supplier(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/suppliers", payload=payload, headers=headers
        )

    def get_supplier(self, supplier_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/suppliers/{supplier_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Laboratories and accreditation scopes
    # ------------------------------------------------------------------

    def create_laboratory(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/laboratories", payload=payload, headers=headers
        )

    def get_laboratory(self, laboratory_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/laboratories/{laboratory_id}", headers=headers
        )

    def record_attestation(
        self, laboratory_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/laboratories/{laboratory_id}/independence-attestations",
            payload=payload,
            headers=headers,
        )

    def set_laboratory_operational_state(
        self, laboratory_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/laboratories/{laboratory_id}/operational-state",
            payload=payload,
            headers=headers,
        )

    def create_accreditation(
        self, laboratory_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/laboratories/{laboratory_id}/accreditations",
            payload=payload,
            headers=headers,
        )

    def get_accreditation(
        self, accreditation_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/lab-accreditations/{accreditation_id}", headers=headers
        )

    def list_accreditations(
        self, params: Params = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/lab-accreditations", params=params, headers=headers
        )

    def suspend_accreditation(
        self, accreditation_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/lab-accreditations/{accreditation_id}/suspend",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------

    def create_product(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/products", payload=payload, headers=headers
        )

    def get_product(self, product_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/products/{product_id}", headers=headers
        )

    def list_products(self, params: Params = None, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/products", params=params, headers=headers
        )

    def get_compliance_summary(
        self, product_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/products/{product_id}/compliance-summary",
            headers=headers,
        )

    def submit_for_certification(
        self, product_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/products/{product_id}/submit-for-certification",
            payload=payload,
            headers=headers,
        )

    def archive_product(self, product_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/products/{product_id}/archive",
            payload={},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Component parts and their certificates
    # ------------------------------------------------------------------

    def create_component_part(
        self, product_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/products/{product_id}/component-parts",
            payload=payload,
            headers=headers,
        )

    def get_component_part(self, part_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/component-parts/{part_id}", headers=headers
        )

    def list_component_parts(
        self, params: Params = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/component-parts", params=params, headers=headers
        )

    def submit_part_certificate(
        self, part_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/component-parts/{part_id}/certificates",
            payload=payload,
            headers=headers,
        )

    def get_part_certificate(
        self, certificate_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/component-part-certificates/{certificate_id}",
            headers=headers,
        )

    def list_part_certificates(
        self, params: Params = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/component-part-certificates",
            params=params,
            headers=headers,
        )

    def record_reliance_documentation(
        self, certificate_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/component-part-certificates/{certificate_id}"
            "/reliance-documentation",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Sampling plans
    # ------------------------------------------------------------------

    def create_sampling_plan(
        self, product_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/products/{product_id}/sampling-plans",
            payload=payload,
            headers=headers,
        )

    def get_sampling_plan(self, plan_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/sampling-plans/{plan_id}", headers=headers
        )

    def list_sampling_plans(
        self, params: Params = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/sampling-plans", params=params, headers=headers
        )

    def activate_sampling_plan(
        self, plan_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/sampling-plans/{plan_id}/activate",
            payload={},
            headers=headers,
        )

    def periodic_review(self, plan_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/sampling-plans/{plan_id}/periodic-review",
            payload={},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Test orders
    # ------------------------------------------------------------------

    def create_test_order(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/test-orders", payload=payload, headers=headers
        )

    def get_test_order(self, order_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/test-orders/{order_id}", headers=headers
        )

    def list_test_orders(
        self, params: Params = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/test-orders", params=params, headers=headers
        )

    def start_testing(self, order_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/test-orders/{order_id}/start-testing",
            payload={},
            headers=headers,
        )

    def report_result(
        self, order_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/test-orders/{order_id}/report-result",
            payload=payload,
            headers=headers,
        )

    def cancel_test_order(self, order_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/test-orders/{order_id}/cancel",
            payload={},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Children's product certificates
    # ------------------------------------------------------------------

    def draft_certificate(
        self, product_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/products/{product_id}/certificates",
            payload=payload,
            headers=headers,
        )

    def get_certificate(self, certificate_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/certificates/{certificate_id}", headers=headers
        )

    def list_certificates(
        self, params: Params = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/certificates", params=params, headers=headers
        )

    def issue_certificate(
        self, certificate_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/certificates/{certificate_id}/issue",
            payload={},
            headers=headers,
        )

    def void_certificate(
        self, certificate_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/certificates/{certificate_id}/void",
            payload={},
            headers=headers,
        )

    def furnish_certificate(
        self, certificate_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/certificates/{certificate_id}/furnish",
            payload={},
            headers=headers,
        )

    def recall_accompaniment(
        self, certificate_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/certificates/{certificate_id}/recall-accompaniment",
            payload={},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Production batches
    # ------------------------------------------------------------------

    def create_production_batch(
        self, product_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/products/{product_id}/production-batches",
            payload=payload,
            headers=headers,
        )

    def get_production_batch(self, batch_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/production-batches/{batch_id}", headers=headers
        )

    def list_production_batches(
        self, params: Params = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/production-batches", params=params, headers=headers
        )

    def update_tracking_label(
        self, batch_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/production-batches/{batch_id}/tracking-label",
            payload=payload,
            headers=headers,
        )

    def release_batch(self, batch_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/production-batches/{batch_id}/release",
            payload={},
            headers=headers,
        )

    def rescind_release(self, batch_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/production-batches/{batch_id}/rescind-release",
            payload={},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Noncompliance cases
    # ------------------------------------------------------------------

    def get_case(self, case_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/noncompliance-cases/{case_id}", headers=headers
        )

    def list_cases(self, params: Params = None, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/noncompliance-cases", params=params, headers=headers
        )

    def issue_stop_distribution(
        self, case_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/noncompliance-cases/{case_id}/issue-stop-distribution",
            payload=payload,
            headers=headers,
        )

    def order_retest(
        self, case_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/noncompliance-cases/{case_id}/order-retest",
            payload=payload,
            headers=headers,
        )

    def file_corrective_action(
        self, case_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/noncompliance-cases/{case_id}/corrective-actions",
            payload=payload,
            headers=headers,
        )

    def close_case(self, case_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/noncompliance-cases/{case_id}/close",
            payload={},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Material change log
    # ------------------------------------------------------------------

    def record_material_change(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/material-change-events",
            payload=payload,
            headers=headers,
        )

    def get_material_change(self, event_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/material-change-events/{event_id}", headers=headers
        )

    def list_material_changes(
        self, params: Params = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/material-change-events", params=params, headers=headers
        )


api_client = ApiClient()
