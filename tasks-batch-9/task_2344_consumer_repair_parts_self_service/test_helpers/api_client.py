"""API client: one method per endpoint defined in the PRD (§4).

Every path is mounted under the /repair-program prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/repair-program"


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- models #
    def create_product_model(self, payload, headers):
        return self._request("POST", f"{PREFIX}/product-models", payload, headers)

    def get_product_model(self, model_id, headers):
        return self._request("GET", f"{PREFIX}/product-models/{model_id}", headers=headers)

    def list_product_models(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/product-models", headers=headers, params=params)

    def end_production(self, model_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/product-models/{model_id}/end-production", payload, headers
        )

    def end_support(self, model_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/product-models/{model_id}/end-support", payload, headers
        )

    def list_model_compliance_obligations(self, model_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/product-models/{model_id}/compliance-obligations",
            headers=headers,
            params=params,
        )

    def list_model_part_compatibilities(self, model_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/product-models/{model_id}/part-compatibilities",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------ regional profiles #
    def create_compliance_profile(self, payload, headers):
        return self._request("POST", f"{PREFIX}/compliance-profiles", payload, headers)

    def list_compliance_profiles(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/compliance-profiles", headers=headers, params=params
        )

    # ----------------------------------------------------------- obligations #
    def create_compliance_obligation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/compliance-obligations", payload, headers)

    def attest_obligation(self, obligation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/compliance-obligations/{obligation_id}/attest", payload, headers
        )

    def get_compliance_obligation(self, obligation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/compliance-obligations/{obligation_id}", headers=headers
        )

    def list_compliance_obligations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/compliance-obligations", headers=headers, params=params
        )

    def run_compliance_sweep(self, payload, headers):
        return self._request("POST", f"{PREFIX}/compliance-sweeps", payload, headers)

    # -------------------------------------------------------------- catalog #
    def create_part_catalog_item(self, payload, headers):
        return self._request("POST", f"{PREFIX}/part-catalog-items", payload, headers)

    def get_part_catalog_item(self, part_id, headers):
        return self._request("GET", f"{PREFIX}/part-catalog-items/{part_id}", headers=headers)

    def list_part_catalog_items(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/part-catalog-items", headers=headers, params=params
        )

    def list_part_successors(self, part_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/part-catalog-items/{part_id}/successors",
            headers=headers,
            params=params,
        )

    def list_compatibilities_for_part(self, part_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/part-catalog-items/{part_id}/part-compatibilities",
            headers=headers,
            params=params,
        )

    def list_order_lines_for_part(self, part_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/part-catalog-items/{part_id}/order-lines",
            headers=headers,
            params=params,
        )

    def publish_part_catalog_item(self, part_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/part-catalog-items/{part_id}/publish", payload or {}, headers
        )

    def repoint_supersession(self, part_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/part-catalog-items/{part_id}/supersession", payload, headers
        )

    def restrict_part_catalog_item(self, part_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/part-catalog-items/{part_id}/restrict", payload, headers
        )

    def get_demand_forecast(self, part_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/part-catalog-items/{part_id}/demand-forecast",
            headers=headers,
            params=params,
        )

    # -------------------------------------------------------- compatibility #
    def create_part_compatibility(self, payload, headers):
        return self._request("POST", f"{PREFIX}/part-compatibilities", payload, headers)

    def get_part_compatibility(self, compatibility_id, headers):
        return self._request(
            "GET", f"{PREFIX}/part-compatibilities/{compatibility_id}", headers=headers
        )

    def list_part_compatibilities(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/part-compatibilities", headers=headers, params=params
        )

    # ----------------------------------------------------- manual revisions #
    def create_manual_revision(self, payload, headers):
        return self._request("POST", f"{PREFIX}/manual-revisions", payload, headers)

    def get_manual_revision(self, revision_id, headers):
        return self._request("GET", f"{PREFIX}/manual-revisions/{revision_id}", headers=headers)

    def list_manual_revisions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/manual-revisions", headers=headers, params=params
        )

    def submit_manual_revision(self, revision_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/manual-revisions/{revision_id}/submit", payload or {}, headers
        )

    def review_manual_revision(self, revision_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/manual-revisions/{revision_id}/review-decision", payload, headers
        )

    def publish_manual_revision(self, revision_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/manual-revisions/{revision_id}/publish", payload or {}, headers
        )

    # ------------------------------------------------ eligibility assessments #
    def create_eligibility_assessment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/eligibility-assessments", payload, headers)

    def get_eligibility_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/eligibility-assessments/{assessment_id}", headers=headers
        )

    def list_eligibility_assessments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/eligibility-assessments", headers=headers, params=params
        )

    # ---------------------------------------------------------- parts orders #
    def create_parts_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/parts-orders", payload, headers)

    def get_parts_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/parts-orders/{order_id}", headers=headers)

    def list_parts_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/parts-orders", headers=headers, params=params)

    def append_order_line(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/parts-orders/{order_id}/lines", payload, headers
        )

    def list_lines_for_order(self, order_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/parts-orders/{order_id}/lines", headers=headers, params=params
        )

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"{PREFIX}/order-lines/{line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/order-lines", headers=headers, params=params)

    def request_disclosure(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/parts-orders/{order_id}/request-disclosure", payload or {}, headers
        )

    def create_acknowledgment(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/parts-orders/{order_id}/acknowledgments", payload, headers
        )

    def list_acknowledgments_for_order(self, order_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/parts-orders/{order_id}/acknowledgments",
            headers=headers,
            params=params,
        )

    def get_disclosure_acknowledgment(self, acknowledgment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/disclosure-acknowledgments/{acknowledgment_id}", headers=headers
        )

    def list_disclosure_acknowledgments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/disclosure-acknowledgments", headers=headers, params=params
        )

    def confirm_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/parts-orders/{order_id}/confirm", payload or {}, headers
        )

    def deliver_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/parts-orders/{order_id}/deliver", payload or {}, headers
        )

    def cancel_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/parts-orders/{order_id}/cancel", payload, headers
        )

    def book_core_return(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/parts-orders/{order_id}/core-returns", payload, headers
        )

    def authenticate_line(self, order_id, line_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/parts-orders/{order_id}/lines/{line_id}/authenticate",
            payload,
            headers,
        )

    def calibrate_line(self, order_id, line_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/parts-orders/{order_id}/lines/{line_id}/calibrate",
            payload,
            headers,
        )

    # ------------------------------------------------------ repair providers #
    def create_repair_provider(self, payload, headers):
        return self._request("POST", f"{PREFIX}/repair-providers", payload, headers)

    def get_repair_provider(self, provider_id, headers):
        return self._request("GET", f"{PREFIX}/repair-providers/{provider_id}", headers=headers)

    def list_repair_providers(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/repair-providers", headers=headers, params=params
        )

    def begin_provider_training(self, provider_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/repair-providers/{provider_id}/begin-training", payload, headers
        )

    def decide_provider_authorization(self, provider_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/repair-providers/{provider_id}/authorization-decision",
            payload,
            headers,
        )

    def get_provider_compliance_score(self, provider_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/repair-providers/{provider_id}/compliance-score",
            headers=headers,
            params=params,
        )

    def list_provider_certifications(self, provider_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/repair-providers/{provider_id}/training-certifications",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------ training certifications #
    def get_training_certification(self, certification_id, headers):
        return self._request(
            "GET", f"{PREFIX}/training-certifications/{certification_id}", headers=headers
        )

    def list_training_certifications(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/training-certifications", headers=headers, params=params
        )

    def create_training_certification(self, payload, headers):
        return self._request("POST", f"{PREFIX}/training-certifications", payload, headers)

    def void_training_certification(self, certification_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/training-certifications/{certification_id}/void",
            payload,
            headers,
        )

    # ------------------------------------------------------ defective returns #
    def create_defective_return(self, payload, headers):
        return self._request("POST", f"{PREFIX}/defective-returns", payload, headers)

    def get_defective_return(self, case_id, headers):
        return self._request("GET", f"{PREFIX}/defective-returns/{case_id}", headers=headers)

    def list_defective_returns(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/defective-returns", headers=headers, params=params
        )

    def receive_defective_return(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/defective-returns/{case_id}/receive", payload or {}, headers
        )

    def record_failure_analysis(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/defective-returns/{case_id}/analysis", payload, headers
        )

    def decide_defective_credit(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/defective-returns/{case_id}/credit-decision", payload, headers
        )

    # ------------------------------------------------------------ the clock #
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
