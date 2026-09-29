"""Endpoint methods for the gluten-free certification API.

Every method returns the raw ``requests.Response`` so tests can assert on status
codes as well as bodies. All paths sit under the ``/gfco`` prefix.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


def _clean(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is ``None`` so optional inputs stay omitted."""
    return {k: v for k, v in payload.items() if v is not None}


class ApiClient(GenericApiClient):
    """One method per endpoint declared by the PRD."""

    # ------------------------------------------------------------------
    # logical clock and surveillance sweep
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            payload={"to_iso8601": to_iso8601},
            headers=headers,
        )

    def run_surveillance(self, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/surveillance-runs", payload={}, headers=headers
        )

    # ------------------------------------------------------------------
    # applicants
    # ------------------------------------------------------------------
    def create_applicant(
        self,
        headers: Dict[str, str],
        legal_name: Optional[str] = None,
        contact_email: Optional[str] = None,
        country_code: Optional[str] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean(
            {
                "legal_name": legal_name,
                "contact_email": contact_email,
                "country_code": country_code,
            }
        )
        payload.update(extra)
        return self._request(
            "POST", f"{API_PREFIX}/applicants", payload=payload, headers=headers
        )

    def get_applicant(self, applicant_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/applicants/{applicant_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # suppliers
    # ------------------------------------------------------------------
    def create_supplier(
        self,
        headers: Dict[str, str],
        name: Optional[str] = None,
        country_code: Optional[str] = None,
        gluten_handling_disclosed: Optional[bool] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean(
            {
                "name": name,
                "country_code": country_code,
                "gluten_handling_disclosed": gluten_handling_disclosed,
            }
        )
        payload.update(extra)
        return self._request(
            "POST", f"{API_PREFIX}/suppliers", payload=payload, headers=headers
        )

    def get_supplier(self, supplier_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/suppliers/{supplier_id}", headers=headers
        )

    def set_supplier_status(
        self, supplier_id: str, status: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/suppliers/{supplier_id}/status",
            payload={"status": status},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # facilities
    # ------------------------------------------------------------------
    def create_facility(
        self,
        headers: Dict[str, str],
        applicant_id: Optional[str] = None,
        site_name: Optional[str] = None,
        air_handling_class: Optional[str] = None,
        shared_equipment_present: Optional[bool] = None,
        gluten_containing_operations: Optional[str] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean(
            {
                "applicant_id": applicant_id,
                "site_name": site_name,
                "air_handling_class": air_handling_class,
                "shared_equipment_present": shared_equipment_present,
                "gluten_containing_operations": gluten_containing_operations,
            }
        )
        payload.update(extra)
        return self._request(
            "POST", f"{API_PREFIX}/facilities", payload=payload, headers=headers
        )

    def get_facility(self, facility_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/facilities/{facility_id}", headers=headers
        )

    def list_facilities(
        self, headers: Dict[str, str], **params: Any
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/facilities", params=_clean(params), headers=headers
        )

    def validate_sanitation(
        self,
        facility_id: str,
        headers: Dict[str, str],
        swab_ppm: Optional[float] = None,
        method: Optional[str] = None,
        validated_on: Optional[str] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean(
            {"swab_ppm": swab_ppm, "method": method, "validated_on": validated_on}
        )
        payload.update(extra)
        return self._request(
            "POST",
            f"{API_PREFIX}/facilities/{facility_id}/sanitation-validation",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # supplier documents
    # ------------------------------------------------------------------
    def create_supplier_document(
        self,
        headers: Dict[str, str],
        supplier_id: Optional[str] = None,
        ingredient_id: Optional[str] = None,
        doc_type: Optional[str] = None,
        issued_on: Optional[str] = None,
        expires_on: Optional[str] = None,
        lab_ppm_claim: Optional[float] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean(
            {
                "supplier_id": supplier_id,
                "ingredient_id": ingredient_id,
                "doc_type": doc_type,
                "issued_on": issued_on,
                "expires_on": expires_on,
                "lab_ppm_claim": lab_ppm_claim,
            }
        )
        payload.update(extra)
        return self._request(
            "POST", f"{API_PREFIX}/supplier-documents", payload=payload, headers=headers
        )

    def get_supplier_document(
        self, document_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/supplier-documents/{document_id}", headers=headers
        )

    def list_supplier_documents(
        self, headers: Dict[str, str], **params: Any
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/supplier-documents",
            params=_clean(params),
            headers=headers,
        )

    def verify_supplier_document(
        self,
        document_id: str,
        headers: Dict[str, str],
        decision: Optional[str] = None,
        rejection_reason: Optional[str] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean({"decision": decision, "rejection_reason": rejection_reason})
        payload.update(extra)
        return self._request(
            "POST",
            f"{API_PREFIX}/supplier-documents/{document_id}/verification",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # ingredients
    # ------------------------------------------------------------------
    def create_ingredient(
        self,
        headers: Dict[str, str],
        applicant_id: Optional[str] = None,
        supplier_id: Optional[str] = None,
        name: Optional[str] = None,
        risk_class: Optional[str] = None,
        parent_ingredient_id: Optional[str] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean(
            {
                "applicant_id": applicant_id,
                "supplier_id": supplier_id,
                "name": name,
                "risk_class": risk_class,
                "parent_ingredient_id": parent_ingredient_id,
            }
        )
        payload.update(extra)
        return self._request(
            "POST", f"{API_PREFIX}/ingredients", payload=payload, headers=headers
        )

    def get_ingredient(
        self, ingredient_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/ingredients/{ingredient_id}", headers=headers
        )

    def list_ingredients(self, headers: Dict[str, str], **params: Any) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/ingredients", params=_clean(params), headers=headers
        )

    def submit_ingredient(
        self, ingredient_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/ingredients/{ingredient_id}/submission",
            payload={},
            headers=headers,
        )

    def review_ingredient(
        self,
        ingredient_id: str,
        headers: Dict[str, str],
        decision: Optional[str] = None,
        rejection_reason: Optional[str] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean({"decision": decision, "rejection_reason": rejection_reason})
        payload.update(extra)
        return self._request(
            "POST",
            f"{API_PREFIX}/ingredients/{ingredient_id}/review",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # products and formula lines
    # ------------------------------------------------------------------
    def create_product(
        self,
        headers: Dict[str, str],
        applicant_id: Optional[str] = None,
        facility_id: Optional[str] = None,
        name: Optional[str] = None,
        sku: Optional[str] = None,
        requested_mark_tier: Optional[str] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean(
            {
                "applicant_id": applicant_id,
                "facility_id": facility_id,
                "name": name,
                "sku": sku,
                "requested_mark_tier": requested_mark_tier,
            }
        )
        payload.update(extra)
        return self._request(
            "POST", f"{API_PREFIX}/products", payload=payload, headers=headers
        )

    def get_product(self, product_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/products/{product_id}", headers=headers
        )

    def list_products(self, headers: Dict[str, str], **params: Any) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/products", params=_clean(params), headers=headers
        )

    def link_product_ingredient(
        self,
        headers: Dict[str, str],
        product_id: Optional[str] = None,
        ingredient_id: Optional[str] = None,
        inclusion_pct: Optional[float] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean(
            {
                "product_id": product_id,
                "ingredient_id": ingredient_id,
                "inclusion_pct": inclusion_pct,
            }
        )
        payload.update(extra)
        return self._request(
            "POST", f"{API_PREFIX}/product-ingredients", payload=payload, headers=headers
        )

    def get_product_ingredient(
        self, link_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/product-ingredients/{link_id}", headers=headers
        )

    def list_product_ingredients(
        self, headers: Dict[str, str], **params: Any
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/product-ingredients",
            params=_clean(params),
            headers=headers,
        )

    def review_formula(
        self,
        product_id: str,
        headers: Dict[str, str],
        decision: Optional[str] = None,
        rejection_reason: Optional[str] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean({"decision": decision, "rejection_reason": rejection_reason})
        payload.update(extra)
        return self._request(
            "POST",
            f"{API_PREFIX}/products/{product_id}/formula-review",
            payload=payload,
            headers=headers,
        )

    def activate_testing_plan(
        self,
        product_id: str,
        headers: Dict[str, str],
        expected_product_version: Optional[int] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean({"expected_product_version": expected_product_version})
        payload.update(extra)
        return self._request(
            "POST",
            f"{API_PREFIX}/products/{product_id}/testing-plan",
            payload=payload,
            headers=headers,
        )

    def review_label(
        self,
        product_id: str,
        headers: Dict[str, str],
        decision: Optional[str] = None,
        mark_tier_granted: Optional[str] = None,
        rejection_reason: Optional[str] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean(
            {
                "decision": decision,
                "mark_tier_granted": mark_tier_granted,
                "rejection_reason": rejection_reason,
            }
        )
        payload.update(extra)
        return self._request(
            "POST",
            f"{API_PREFIX}/products/{product_id}/label-review",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # lot tests
    # ------------------------------------------------------------------
    def create_lot_test(
        self,
        headers: Dict[str, str],
        product_id: Optional[str] = None,
        lot_code: Optional[str] = None,
        test_type: Optional[str] = None,
        sample_collected_on: Optional[str] = None,
        ppm_result: Optional[float] = None,
        lab_method: Optional[str] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean(
            {
                "product_id": product_id,
                "lot_code": lot_code,
                "test_type": test_type,
                "sample_collected_on": sample_collected_on,
                "ppm_result": ppm_result,
                "lab_method": lab_method,
            }
        )
        payload.update(extra)
        return self._request(
            "POST", f"{API_PREFIX}/lot-tests", payload=payload, headers=headers
        )

    def get_lot_test(self, lot_test_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/lot-tests/{lot_test_id}", headers=headers
        )

    def list_lot_tests(self, headers: Dict[str, str], **params: Any) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/lot-tests", params=_clean(params), headers=headers
        )

    # ------------------------------------------------------------------
    # audits
    # ------------------------------------------------------------------
    def create_audit(
        self,
        headers: Dict[str, str],
        facility_id: Optional[str] = None,
        audit_type: Optional[str] = None,
        onsite_start_at: Optional[str] = None,
        onsite_end_at: Optional[str] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean(
            {
                "facility_id": facility_id,
                "audit_type": audit_type,
                "onsite_start_at": onsite_start_at,
                "onsite_end_at": onsite_end_at,
            }
        )
        payload.update(extra)
        return self._request(
            "POST", f"{API_PREFIX}/audits", payload=payload, headers=headers
        )

    def get_audit(self, audit_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/audits/{audit_id}", headers=headers)

    def list_audits(self, headers: Dict[str, str], **params: Any) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/audits", params=_clean(params), headers=headers
        )

    def start_audit(self, audit_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/audits/{audit_id}/start", payload={}, headers=headers
        )

    def close_audit(
        self,
        audit_id: str,
        headers: Dict[str, str],
        shared_equipment_verified: Optional[bool] = None,
        air_handling_verified: Optional[bool] = None,
        sanitation_validation_reviewed: Optional[bool] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean(
            {
                "shared_equipment_verified": shared_equipment_verified,
                "air_handling_verified": air_handling_verified,
                "sanitation_validation_reviewed": sanitation_validation_reviewed,
            }
        )
        payload.update(extra)
        return self._request(
            "POST",
            f"{API_PREFIX}/audits/{audit_id}/close",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # nonconformances and corrective actions
    # ------------------------------------------------------------------
    def create_nonconformance(
        self,
        headers: Dict[str, str],
        applicant_id: Optional[str] = None,
        source_type: Optional[str] = None,
        category: Optional[str] = None,
        severity: Optional[str] = None,
        description: Optional[str] = None,
        certificate_id: Optional[str] = None,
        audit_id: Optional[str] = None,
        lot_test_id: Optional[str] = None,
        complaint_id: Optional[str] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean(
            {
                "applicant_id": applicant_id,
                "source_type": source_type,
                "category": category,
                "severity": severity,
                "description": description,
                "certificate_id": certificate_id,
                "audit_id": audit_id,
                "lot_test_id": lot_test_id,
                "complaint_id": complaint_id,
            }
        )
        payload.update(extra)
        return self._request(
            "POST", f"{API_PREFIX}/nonconformances", payload=payload, headers=headers
        )

    def get_nonconformance(
        self, nonconformance_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/nonconformances/{nonconformance_id}", headers=headers
        )

    def list_nonconformances(
        self, headers: Dict[str, str], **params: Any
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/nonconformances",
            params=_clean(params),
            headers=headers,
        )

    def submit_corrective_action_plan(
        self,
        nonconformance_id: str,
        headers: Dict[str, str],
        expected_nonconformance_version: Optional[int] = None,
        ca_plan_text: Optional[str] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean(
            {
                "expected_nonconformance_version": expected_nonconformance_version,
                "ca_plan_text": ca_plan_text,
            }
        )
        payload.update(extra)
        return self._request(
            "POST",
            f"{API_PREFIX}/nonconformances/{nonconformance_id}/corrective-action-plan",
            payload=payload,
            headers=headers,
        )

    def decide_corrective_action(
        self,
        nonconformance_id: str,
        headers: Dict[str, str],
        decision: Optional[str] = None,
        ca_rejection_reason: Optional[str] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean(
            {"decision": decision, "ca_rejection_reason": ca_rejection_reason}
        )
        payload.update(extra)
        return self._request(
            "POST",
            f"{API_PREFIX}/nonconformances/{nonconformance_id}/corrective-action-decision",
            payload=payload,
            headers=headers,
        )

    def verify_nonconformance(
        self,
        nonconformance_id: str,
        headers: Dict[str, str],
        effectiveness_confirmed: Optional[bool] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean({"effectiveness_confirmed": effectiveness_confirmed})
        payload.update(extra)
        return self._request(
            "POST",
            f"{API_PREFIX}/nonconformances/{nonconformance_id}/verification",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # certificates
    # ------------------------------------------------------------------
    def issue_certificate(
        self,
        headers: Dict[str, str],
        product_id: Optional[str] = None,
        expected_product_version: Optional[int] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean(
            {
                "product_id": product_id,
                "expected_product_version": expected_product_version,
            }
        )
        payload.update(extra)
        return self._request(
            "POST", f"{API_PREFIX}/certificates", payload=payload, headers=headers
        )

    def get_certificate(
        self, certificate_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/certificates/{certificate_id}", headers=headers
        )

    def list_certificates(
        self, headers: Dict[str, str], **params: Any
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/certificates", params=_clean(params), headers=headers
        )

    def suspend_certificate(
        self,
        certificate_id: str,
        headers: Dict[str, str],
        suspension_reason: Optional[str] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean({"suspension_reason": suspension_reason})
        payload.update(extra)
        return self._request(
            "POST",
            f"{API_PREFIX}/certificates/{certificate_id}/suspension",
            payload=payload,
            headers=headers,
        )

    def reinstate_certificate(
        self, certificate_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/certificates/{certificate_id}/reinstatement",
            payload={},
            headers=headers,
        )

    def revoke_certificate(
        self,
        certificate_id: str,
        headers: Dict[str, str],
        revocation_reason: Optional[str] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean({"revocation_reason": revocation_reason})
        payload.update(extra)
        return self._request(
            "POST",
            f"{API_PREFIX}/certificates/{certificate_id}/revocation",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # consumer complaints
    # ------------------------------------------------------------------
    def create_complaint(
        self,
        headers: Dict[str, str],
        certificate_id: Optional[str] = None,
        exposure_date: Optional[str] = None,
        symptom_severity: Optional[str] = None,
        lot_code: Optional[str] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean(
            {
                "certificate_id": certificate_id,
                "exposure_date": exposure_date,
                "symptom_severity": symptom_severity,
                "lot_code": lot_code,
            }
        )
        payload.update(extra)
        return self._request(
            "POST", f"{API_PREFIX}/consumer-complaints", payload=payload, headers=headers
        )

    def get_complaint(self, complaint_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/consumer-complaints/{complaint_id}", headers=headers
        )

    def list_complaints(self, headers: Dict[str, str], **params: Any) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/consumer-complaints",
            params=_clean(params),
            headers=headers,
        )

    def triage_complaint(
        self, complaint_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/consumer-complaints/{complaint_id}/triage",
            payload={},
            headers=headers,
        )

    def record_investigation_outcome(
        self,
        complaint_id: str,
        headers: Dict[str, str],
        outcome: Optional[str] = None,
        outcome_evidence: Optional[str] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean({"outcome": outcome, "outcome_evidence": outcome_evidence})
        payload.update(extra)
        return self._request(
            "POST",
            f"{API_PREFIX}/consumer-complaints/{complaint_id}/investigation-outcome",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # change notifications
    # ------------------------------------------------------------------
    def create_change_notification(
        self,
        headers: Dict[str, str],
        certificate_id: Optional[str] = None,
        change_type: Optional[str] = None,
        effective_on: Optional[str] = None,
        description: Optional[str] = None,
        replacement_ingredient_id: Optional[str] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean(
            {
                "certificate_id": certificate_id,
                "change_type": change_type,
                "effective_on": effective_on,
                "description": description,
                "replacement_ingredient_id": replacement_ingredient_id,
            }
        )
        payload.update(extra)
        return self._request(
            "POST",
            f"{API_PREFIX}/change-notifications",
            payload=payload,
            headers=headers,
        )

    def get_change_notification(
        self, notification_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/change-notifications/{notification_id}",
            headers=headers,
        )

    def list_change_notifications(
        self, headers: Dict[str, str], **params: Any
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/change-notifications",
            params=_clean(params),
            headers=headers,
        )

    def assess_change_notification(
        self,
        notification_id: str,
        headers: Dict[str, str],
        decision: Optional[str] = None,
        impact_level: Optional[str] = None,
        **extra: Any,
    ) -> requests.Response:
        payload = _clean({"decision": decision, "impact_level": impact_level})
        payload.update(extra)
        return self._request(
            "POST",
            f"{API_PREFIX}/change-notifications/{notification_id}/assessment",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # raw escape hatches (for request-shape and unknown-path probes)
    # ------------------------------------------------------------------
    def raw_get(
        self, path: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}{path}", params=params, headers=headers)

    def raw_post(
        self, path: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}{path}", payload=payload, headers=headers)
