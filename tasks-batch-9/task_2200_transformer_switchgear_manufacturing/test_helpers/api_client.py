"""Endpoint methods for the transformer & switchgear manufacturing API.

PRD 4: "Paths are absolute and are not nested beneath any single root
resource: the API is organised as twenty-one sibling resource families plus one
administrative clock family". No prefix is prepended to any path below.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import CLOCK_ENDPOINT

Json = Optional[Dict[str, Any]]
Headers = Optional[Dict[str, str]]


class ApiClient(GenericApiClient):
    """One method per row of the PRD 4 endpoint table."""

    # ----- logical clock ------------------------------------------------
    def set_clock(self, current_utc: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", CLOCK_ENDPOINT, {"current_utc": current_utc}, headers
        )

    # ----- engineered orders --------------------------------------------
    def create_engineered_order(self, payload: Json, headers: Headers):
        return self._request("POST", "/engineered-orders", payload, headers)

    def list_engineered_orders(self, headers: Headers, params: Json = None):
        return self._request("GET", "/engineered-orders", params, headers)

    def get_engineered_order(self, order_id: str, headers: Headers):
        return self._request("GET", f"/engineered-orders/{order_id}", None, headers)

    def patch_engineered_order(self, order_id: str, payload: Json, headers: Headers):
        return self._request("PATCH", f"/engineered-orders/{order_id}", payload, headers)

    def start_production(self, order_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/engineered-orders/{order_id}/start-production", payload, headers
        )

    def close_engineering(self, order_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/engineered-orders/{order_id}/close-engineering", payload, headers
        )

    def cancel_engineered_order(self, order_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/engineered-orders/{order_id}/cancel", payload, headers
        )

    def get_order_posture(self, order_id: str, headers: Headers):
        return self._request(
            "GET", f"/engineered-orders/{order_id}/posture", None, headers
        )

    def get_order_financial_summary(self, order_id: str, headers: Headers):
        return self._request(
            "GET", f"/engineered-orders/{order_id}/financial-summary", None, headers
        )

    # ----- submittal drawings -------------------------------------------
    def create_submittal_drawing(self, order_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/engineered-orders/{order_id}/submittal-drawings", payload, headers
        )

    def list_order_submittal_drawings(
        self, order_id: str, headers: Headers, params: Json = None
    ):
        return self._request(
            "GET", f"/engineered-orders/{order_id}/submittal-drawings", params, headers
        )

    def list_submittal_drawings(self, headers: Headers, params: Json = None):
        return self._request("GET", "/submittal-drawings", params, headers)

    def get_submittal_drawing(self, drawing_id: str, headers: Headers):
        return self._request("GET", f"/submittal-drawings/{drawing_id}", None, headers)

    def submit_drawing(self, drawing_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/submittal-drawings/{drawing_id}/submit", payload, headers
        )

    def begin_review_drawing(self, drawing_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/submittal-drawings/{drawing_id}/begin-review", payload, headers
        )

    def disposition_drawing(self, drawing_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/submittal-drawings/{drawing_id}/disposition", payload, headers
        )

    # ----- escalation clauses and index points --------------------------
    def create_escalation_clause(self, order_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST",
            f"/engineered-orders/{order_id}/escalation-clauses",
            payload,
            headers,
        )

    def list_order_escalation_clauses(
        self, order_id: str, headers: Headers, params: Json = None
    ):
        return self._request(
            "GET", f"/engineered-orders/{order_id}/escalation-clauses", params, headers
        )

    def get_escalation_clause(self, clause_id: str, headers: Headers):
        return self._request("GET", f"/escalation-clauses/{clause_id}", None, headers)

    def create_commodity_index_point(self, payload: Json, headers: Headers):
        return self._request("POST", "/commodity-index-points", payload, headers)

    def list_commodity_index_points(self, headers: Headers, params: Json = None):
        return self._request("GET", "/commodity-index-points", params, headers)

    def get_commodity_index_point(self, point_id: str, headers: Headers):
        return self._request(
            "GET", f"/commodity-index-points/{point_id}", None, headers
        )

    def patch_commodity_index_point(
        self, point_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "PATCH", f"/commodity-index-points/{point_id}", payload, headers
        )

    # ----- escalation adjustments ---------------------------------------
    def create_escalation_adjustment(
        self, order_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "POST",
            f"/engineered-orders/{order_id}/escalation-adjustments",
            payload,
            headers,
        )

    def list_escalation_adjustments(self, headers: Headers, params: Json = None):
        return self._request("GET", "/escalation-adjustments", params, headers)

    def get_escalation_adjustment(self, adjustment_id: str, headers: Headers):
        return self._request(
            "GET", f"/escalation-adjustments/{adjustment_id}", None, headers
        )

    def submit_escalation_adjustment(
        self, adjustment_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "POST", f"/escalation-adjustments/{adjustment_id}/submit", payload, headers
        )

    def accept_escalation_adjustment(
        self, adjustment_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "POST", f"/escalation-adjustments/{adjustment_id}/accept", payload, headers
        )

    def dispute_escalation_adjustment(
        self, adjustment_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "POST", f"/escalation-adjustments/{adjustment_id}/dispute", payload, headers
        )

    def recalculate_escalation_adjustment(
        self, adjustment_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "POST",
            f"/escalation-adjustments/{adjustment_id}/recalculate",
            payload,
            headers,
        )

    def withdraw_escalation_adjustment(
        self, adjustment_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "POST",
            f"/escalation-adjustments/{adjustment_id}/withdraw",
            payload,
            headers,
        )

    # ----- suppliers -----------------------------------------------------
    def create_supplier(self, payload: Json, headers: Headers):
        return self._request("POST", "/suppliers", payload, headers)

    def list_suppliers(self, headers: Headers, params: Json = None):
        return self._request("GET", "/suppliers", params, headers)

    def get_supplier(self, supplier_id: str, headers: Headers):
        return self._request("GET", f"/suppliers/{supplier_id}", None, headers)

    def create_receipt_event(self, supplier_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/suppliers/{supplier_id}/receipt-events", payload, headers
        )

    def suspend_supplier(self, supplier_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/suppliers/{supplier_id}/suspend", payload, headers
        )

    def get_supplier_quality_summary(self, supplier_id: str, headers: Headers):
        return self._request(
            "GET", f"/suppliers/{supplier_id}/quality-summary", None, headers
        )

    # ----- long lead components -----------------------------------------
    def create_long_lead_component(
        self, supplier_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "POST", f"/suppliers/{supplier_id}/long-lead-components", payload, headers
        )

    def list_supplier_long_lead_components(
        self, supplier_id: str, headers: Headers, params: Json = None
    ):
        return self._request(
            "GET", f"/suppliers/{supplier_id}/long-lead-components", params, headers
        )

    def list_long_lead_components(self, headers: Headers, params: Json = None):
        return self._request("GET", "/long-lead-components", params, headers)

    def get_long_lead_component(self, component_id: str, headers: Headers):
        return self._request(
            "GET", f"/long-lead-components/{component_id}", None, headers
        )

    def create_component_receipt(
        self, component_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "POST", f"/long-lead-components/{component_id}/receipts", payload, headers
        )

    def release_component_quarantine(
        self, component_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "POST",
            f"/long-lead-components/{component_id}/release-quarantine",
            payload,
            headers,
        )

    def obsolete_component(self, component_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/long-lead-components/{component_id}/obsolete", payload, headers
        )

    # ----- component allocations ----------------------------------------
    def create_component_allocation(self, payload: Json, headers: Headers):
        return self._request("POST", "/component-allocations", payload, headers)

    def list_component_allocations(self, headers: Headers, params: Json = None):
        return self._request("GET", "/component-allocations", params, headers)

    def get_component_allocation(self, allocation_id: str, headers: Headers):
        return self._request(
            "GET", f"/component-allocations/{allocation_id}", None, headers
        )

    def commit_component_allocation(
        self, allocation_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "POST", f"/component-allocations/{allocation_id}/commit", payload, headers
        )

    def release_component_allocation(
        self, allocation_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "POST", f"/component-allocations/{allocation_id}/release", payload, headers
        )

    # ----- test bays -----------------------------------------------------
    def create_test_bay(self, payload: Json, headers: Headers):
        return self._request("POST", "/test-bays", payload, headers)

    def list_test_bays(self, headers: Headers, params: Json = None):
        return self._request("GET", "/test-bays", params, headers)

    def get_test_bay(self, bay_id: str, headers: Headers):
        return self._request("GET", f"/test-bays/{bay_id}", None, headers)

    def patch_test_bay(self, bay_id: str, payload: Json, headers: Headers):
        return self._request("PATCH", f"/test-bays/{bay_id}", payload, headers)

    def get_test_bay_schedule(self, bay_id: str, headers: Headers, params: Json = None):
        return self._request("GET", f"/test-bays/{bay_id}/schedule", params, headers)

    # ----- factory acceptance tests -------------------------------------
    def create_factory_acceptance_test(self, payload: Json, headers: Headers):
        return self._request("POST", "/factory-acceptance-tests", payload, headers)

    def list_factory_acceptance_tests(self, headers: Headers, params: Json = None):
        return self._request("GET", "/factory-acceptance-tests", params, headers)

    def get_factory_acceptance_test(self, fat_id: str, headers: Headers):
        return self._request(
            "GET", f"/factory-acceptance-tests/{fat_id}", None, headers
        )

    def schedule_factory_acceptance_test(
        self, fat_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "POST", f"/factory-acceptance-tests/{fat_id}/schedule", payload, headers
        )

    def start_factory_acceptance_test(
        self, fat_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "POST", f"/factory-acceptance-tests/{fat_id}/start", payload, headers
        )

    def conclude_factory_acceptance_test(
        self, fat_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "POST", f"/factory-acceptance-tests/{fat_id}/conclude", payload, headers
        )

    def abandon_factory_acceptance_test(
        self, fat_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "POST", f"/factory-acceptance-tests/{fat_id}/abandon", payload, headers
        )

    # ----- witness parties ----------------------------------------------
    def create_witness_party(self, payload: Json, headers: Headers):
        return self._request("POST", "/witness-parties", payload, headers)

    def list_witness_parties(self, headers: Headers, params: Json = None):
        return self._request("GET", "/witness-parties", params, headers)

    def get_witness_party(self, party_id: str, headers: Headers):
        return self._request("GET", f"/witness-parties/{party_id}", None, headers)

    def patch_witness_party(self, party_id: str, payload: Json, headers: Headers):
        return self._request("PATCH", f"/witness-parties/{party_id}", payload, headers)

    def get_witness_party_load(
        self, party_id: str, headers: Headers, params: Json = None
    ):
        return self._request(
            "GET", f"/witness-parties/{party_id}/load", params, headers
        )

    # ----- witness assignments ------------------------------------------
    def create_witness_assignment(self, fat_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST",
            f"/factory-acceptance-tests/{fat_id}/witness-assignments",
            payload,
            headers,
        )

    def list_fat_witness_assignments(
        self, fat_id: str, headers: Headers, params: Json = None
    ):
        return self._request(
            "GET",
            f"/factory-acceptance-tests/{fat_id}/witness-assignments",
            params,
            headers,
        )

    def list_witness_assignments(self, headers: Headers, params: Json = None):
        return self._request("GET", "/witness-assignments", params, headers)

    def get_witness_assignment(self, assignment_id: str, headers: Headers):
        return self._request(
            "GET", f"/witness-assignments/{assignment_id}", None, headers
        )

    def confirm_witness_assignment(
        self, assignment_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "POST", f"/witness-assignments/{assignment_id}/confirm", payload, headers
        )

    def decline_witness_assignment(
        self, assignment_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "POST", f"/witness-assignments/{assignment_id}/decline", payload, headers
        )

    def reinvite_witness_assignment(
        self, assignment_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "POST", f"/witness-assignments/{assignment_id}/reinvite", payload, headers
        )

    def waive_witness_assignment(
        self, assignment_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "POST", f"/witness-assignments/{assignment_id}/waive", payload, headers
        )

    # ----- test reports --------------------------------------------------
    def create_test_report(self, fat_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/factory-acceptance-tests/{fat_id}/test-reports", payload, headers
        )

    def list_fat_test_reports(self, fat_id: str, headers: Headers, params: Json = None):
        return self._request(
            "GET", f"/factory-acceptance-tests/{fat_id}/test-reports", params, headers
        )

    def get_test_report(self, report_id: str, headers: Headers):
        return self._request("GET", f"/test-reports/{report_id}", None, headers)

    def issue_test_report(self, report_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/test-reports/{report_id}/issue", payload, headers
        )

    # ----- compliance labels --------------------------------------------
    def create_compliance_label(self, order_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST",
            f"/engineered-orders/{order_id}/compliance-labels",
            payload,
            headers,
        )

    def list_order_compliance_labels(
        self, order_id: str, headers: Headers, params: Json = None
    ):
        return self._request(
            "GET", f"/engineered-orders/{order_id}/compliance-labels", params, headers
        )

    def list_compliance_labels(self, headers: Headers, params: Json = None):
        return self._request("GET", "/compliance-labels", params, headers)

    def get_compliance_label(self, label_id: str, headers: Headers):
        return self._request("GET", f"/compliance-labels/{label_id}", None, headers)

    def generate_compliance_label(self, label_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/compliance-labels/{label_id}/generate", payload, headers
        )

    def verify_compliance_label(self, label_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/compliance-labels/{label_id}/verify", payload, headers
        )

    def issue_compliance_label(self, label_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/compliance-labels/{label_id}/issue", payload, headers
        )

    def void_compliance_label(self, label_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/compliance-labels/{label_id}/void", payload, headers
        )

    # ----- shipment releases ---------------------------------------------
    def create_shipment_release(self, order_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/engineered-orders/{order_id}/shipment-releases", payload, headers
        )

    def list_order_shipment_releases(
        self, order_id: str, headers: Headers, params: Json = None
    ):
        return self._request(
            "GET", f"/engineered-orders/{order_id}/shipment-releases", params, headers
        )

    def get_shipment_release(self, release_id: str, headers: Headers):
        return self._request("GET", f"/shipment-releases/{release_id}", None, headers)

    def clear_shipment_release(self, release_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/shipment-releases/{release_id}/clear", payload, headers
        )

    def stage_shipment_release(self, release_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/shipment-releases/{release_id}/stage", payload, headers
        )

    def ship_shipment_release(self, release_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/shipment-releases/{release_id}/ship", payload, headers
        )

    def deliver_shipment_release(self, release_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/shipment-releases/{release_id}/deliver", payload, headers
        )

    # ----- site storage agreements ---------------------------------------
    def create_site_storage_agreement(
        self, release_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "POST",
            f"/shipment-releases/{release_id}/site-storage-agreements",
            payload,
            headers,
        )

    def list_release_site_storage_agreements(
        self, release_id: str, headers: Headers, params: Json = None
    ):
        return self._request(
            "GET",
            f"/shipment-releases/{release_id}/site-storage-agreements",
            params,
            headers,
        )

    def get_site_storage_agreement(self, agreement_id: str, headers: Headers):
        return self._request(
            "GET", f"/site-storage-agreements/{agreement_id}", None, headers
        )

    def close_site_storage_agreement(
        self, agreement_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "POST", f"/site-storage-agreements/{agreement_id}/close", payload, headers
        )

    def waive_site_storage_agreement(
        self, agreement_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "POST", f"/site-storage-agreements/{agreement_id}/waive", payload, headers
        )

    # ----- commissioning jobs --------------------------------------------
    def create_commissioning_job(self, order_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST",
            f"/engineered-orders/{order_id}/commissioning-jobs",
            payload,
            headers,
        )

    def list_commissioning_jobs(self, headers: Headers, params: Json = None):
        return self._request("GET", "/commissioning-jobs", params, headers)

    def get_commissioning_job(self, job_id: str, headers: Headers):
        return self._request("GET", f"/commissioning-jobs/{job_id}", None, headers)

    def mobilize_commissioning_job(self, job_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/commissioning-jobs/{job_id}/mobilize", payload, headers
        )

    def request_energization(self, job_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST",
            f"/commissioning-jobs/{job_id}/request-energization",
            payload,
            headers,
        )

    def energize_commissioning_job(self, job_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/commissioning-jobs/{job_id}/energize", payload, headers
        )

    def demobilize_commissioning_job(
        self, job_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "POST", f"/commissioning-jobs/{job_id}/demobilize", payload, headers
        )

    def cancel_commissioning_job(self, job_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/commissioning-jobs/{job_id}/cancel", payload, headers
        )

    # ----- punch list items ----------------------------------------------
    def create_punch_list_item(self, job_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/commissioning-jobs/{job_id}/punch-list-items", payload, headers
        )

    def list_job_punch_list_items(
        self, job_id: str, headers: Headers, params: Json = None
    ):
        return self._request(
            "GET", f"/commissioning-jobs/{job_id}/punch-list-items", params, headers
        )

    def get_punch_list_item(self, item_id: str, headers: Headers):
        return self._request("GET", f"/punch-list-items/{item_id}", None, headers)

    def assign_punch_list_item(self, item_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/punch-list-items/{item_id}/assign", payload, headers
        )

    def resolve_punch_list_item(self, item_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/punch-list-items/{item_id}/resolve", payload, headers
        )

    def close_punch_list_item(self, item_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/punch-list-items/{item_id}/close", payload, headers
        )

    def reject_punch_list_item(self, item_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/punch-list-items/{item_id}/reject", payload, headers
        )

    # ----- warranty claims ------------------------------------------------
    def create_warranty_claim(self, order_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/engineered-orders/{order_id}/warranty-claims", payload, headers
        )

    def list_warranty_claims(self, headers: Headers, params: Json = None):
        return self._request("GET", "/warranty-claims", params, headers)

    def get_warranty_claim(self, claim_id: str, headers: Headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", None, headers)

    def issue_rma(self, claim_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/issue-rma", payload, headers
        )

    def receive_unit(self, claim_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/receive-unit", payload, headers
        )

    def settle_warranty_claim(self, claim_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/settle", payload, headers
        )

    def reject_warranty_claim(self, claim_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/reject", payload, headers
        )

    # ----- failure analysis reports ---------------------------------------
    def create_failure_analysis_report(
        self, claim_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "POST",
            f"/warranty-claims/{claim_id}/failure-analysis-reports",
            payload,
            headers,
        )

    def list_claim_failure_analysis_reports(
        self, claim_id: str, headers: Headers, params: Json = None
    ):
        return self._request(
            "GET",
            f"/warranty-claims/{claim_id}/failure-analysis-reports",
            params,
            headers,
        )

    def list_failure_analysis_reports(self, headers: Headers, params: Json = None):
        return self._request("GET", "/failure-analysis-reports", params, headers)

    def get_failure_analysis_report(self, report_id: str, headers: Headers):
        return self._request(
            "GET", f"/failure-analysis-reports/{report_id}", None, headers
        )

    def publish_failure_analysis_report(
        self, report_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "POST", f"/failure-analysis-reports/{report_id}/publish", payload, headers
        )

    def retract_failure_analysis_report(
        self, report_id: str, payload: Json, headers: Headers
    ):
        return self._request(
            "POST", f"/failure-analysis-reports/{report_id}/retract", payload, headers
        )
