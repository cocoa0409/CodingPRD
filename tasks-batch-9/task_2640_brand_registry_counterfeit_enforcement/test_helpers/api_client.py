"""Typed HTTP client covering every endpoint of the brand-protection API.

One method per endpoint. Every method takes the caller's headers explicitly so
tests can exercise the role model and the representative identity rules.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/brand-protection"


class ApiClient(GenericApiClient):
    """Thin per-endpoint wrapper over the generic request machinery."""

    # ------------------------------------------------------------------ clock
    def set_clock(self, to_iso8601: str, headers: Optional[Dict] = None):
        return self.post("/_clock/set_current_utc", json={"to_iso8601": to_iso8601}, headers=headers)

    # ----------------------------------------------------------------- brands
    def create_brand(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self.post(f"{BASE}/brands", json=payload, headers=headers)

    def get_brand(self, brand_id: str, headers: Optional[Dict] = None):
        return self.get(f"{BASE}/brands/{brand_id}", headers=headers)

    def list_brands(self, headers: Optional[Dict] = None, **params):
        return self.get(f"{BASE}/brands", headers=headers, params=params or None)

    def get_enforcement_metrics(self, brand_id: str, headers: Optional[Dict] = None):
        return self.get(f"{BASE}/brands/{brand_id}/enforcement-metrics", headers=headers)

    # -------------------------------------------------- trademark registrations
    def create_registration(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self.post(f"{BASE}/trademark-registrations", json=payload, headers=headers)

    def get_registration(self, registration_id: str, headers: Optional[Dict] = None):
        return self.get(f"{BASE}/trademark-registrations/{registration_id}", headers=headers)

    def list_registrations(self, headers: Optional[Dict] = None, **params):
        return self.get(f"{BASE}/trademark-registrations", headers=headers, params=params or None)

    # ------------------------------------------------------------ enrollments
    def create_enrollment(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self.post(f"{BASE}/enrollments", json=payload, headers=headers)

    def get_enrollment(self, enrollment_id: str, headers: Optional[Dict] = None):
        return self.get(f"{BASE}/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers: Optional[Dict] = None, **params):
        return self.get(f"{BASE}/enrollments", headers=headers, params=params or None)

    def activate_enrollment(self, enrollment_id: str, headers: Optional[Dict] = None):
        return self.post(f"{BASE}/enrollments/{enrollment_id}/activate", json={}, headers=headers)

    def suspend_enrollment(self, enrollment_id: str, reason_code: str, headers: Optional[Dict] = None):
        return self.post(
            f"{BASE}/enrollments/{enrollment_id}/suspend",
            json={"reason_code": reason_code},
            headers=headers,
        )

    # -------------------------------------------------------- representatives
    def create_representative(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self.post(f"{BASE}/representatives", json=payload, headers=headers)

    def get_representative(self, representative_id: str, headers: Optional[Dict] = None):
        return self.get(f"{BASE}/representatives/{representative_id}", headers=headers)

    def list_representatives(self, headers: Optional[Dict] = None, **params):
        return self.get(f"{BASE}/representatives", headers=headers, params=params or None)

    def revoke_representative(self, representative_id: str, reason_code: Optional[str] = None,
                              headers: Optional[Dict] = None):
        payload: Dict[str, Any] = {}
        if reason_code is not None:
            payload["reason_code"] = reason_code
        return self.post(f"{BASE}/representatives/{representative_id}/revoke", json=payload, headers=headers)

    # ---------------------------------------------------------------- sellers
    def create_seller(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self.post(f"{BASE}/sellers", json=payload, headers=headers)

    def get_seller(self, seller_id: str, headers: Optional[Dict] = None):
        return self.get(f"{BASE}/sellers/{seller_id}", headers=headers)

    def list_sellers(self, headers: Optional[Dict] = None, **params):
        return self.get(f"{BASE}/sellers", headers=headers, params=params or None)

    def link_alias(self, seller_id: str, canonical_seller_id: str,
                   expected_canonical_seller_version: int, headers: Optional[Dict] = None):
        return self.post(
            f"{BASE}/sellers/{seller_id}/link-alias",
            json={
                "canonical_seller_id": canonical_seller_id,
                "expected_canonical_seller_version": expected_canonical_seller_version,
            },
            headers=headers,
        )

    # --------------------------------------------------------------- listings
    def create_listing(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self.post(f"{BASE}/listings", json=payload, headers=headers)

    def get_listing(self, listing_id: str, headers: Optional[Dict] = None):
        return self.get(f"{BASE}/listings/{listing_id}", headers=headers)

    def list_listings(self, headers: Optional[Dict] = None, **params):
        return self.get(f"{BASE}/listings", headers=headers, params=params or None)

    def screen_listing(self, listing_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self.post(f"{BASE}/listings/{listing_id}/screen", json=payload, headers=headers)

    # ----------------------------------------------------------------- claims
    def create_claim(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self.post(f"{BASE}/claims", json=payload, headers=headers)

    def get_claim(self, claim_id: str, headers: Optional[Dict] = None):
        return self.get(f"{BASE}/claims/{claim_id}", headers=headers)

    def list_claims(self, headers: Optional[Dict] = None, **params):
        return self.get(f"{BASE}/claims", headers=headers, params=params or None)

    def substantiate_claim(self, claim_id: str, headers: Optional[Dict] = None):
        return self.post(f"{BASE}/claims/{claim_id}/substantiate", json={}, headers=headers)

    def dismiss_claim(self, claim_id: str, reason_code: str, headers: Optional[Dict] = None):
        return self.post(f"{BASE}/claims/{claim_id}/dismiss",
                         json={"reason_code": reason_code}, headers=headers)

    # -------------------------------------------------------------- test buys
    def create_test_buy(self, claim_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self.post(f"{BASE}/claims/{claim_id}/test-buys", json=payload, headers=headers)

    def get_test_buy(self, test_buy_id: str, headers: Optional[Dict] = None):
        return self.get(f"{BASE}/test-buys/{test_buy_id}", headers=headers)

    def list_test_buys(self, headers: Optional[Dict] = None, **params):
        return self.get(f"{BASE}/test-buys", headers=headers, params=params or None)

    def receive_test_buy(self, test_buy_id: str, lot_code: str,
                         chain_of_custody_ref: Optional[str] = None, headers: Optional[Dict] = None):
        payload: Dict[str, Any] = {"lot_code": lot_code}
        if chain_of_custody_ref is not None:
            payload["chain_of_custody_ref"] = chain_of_custody_ref
        return self.post(f"{BASE}/test-buys/{test_buy_id}/receive", json=payload, headers=headers)

    def authenticate_test_buy(self, test_buy_id: str, authentication_result: str, lab_ref: str,
                              headers: Optional[Dict] = None):
        return self.post(
            f"{BASE}/test-buys/{test_buy_id}/authenticate",
            json={"authentication_result": authentication_result, "lab_ref": lab_ref},
            headers=headers,
        )

    def cancel_test_buy(self, test_buy_id: str, reason_code: str, headers: Optional[Dict] = None):
        return self.post(f"{BASE}/test-buys/{test_buy_id}/cancel",
                         json={"reason_code": reason_code}, headers=headers)

    # ------------------------------------------------------- evidence packages
    def create_evidence_package(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self.post(f"{BASE}/evidence-packages", json=payload, headers=headers)

    def get_evidence_package(self, package_id: str, headers: Optional[Dict] = None):
        return self.get(f"{BASE}/evidence-packages/{package_id}", headers=headers)

    def list_evidence_packages(self, headers: Optional[Dict] = None, **params):
        return self.get(f"{BASE}/evidence-packages", headers=headers, params=params or None)

    def append_evidence_item(self, package_id: str, item_type: str, item_ref: str,
                             headers: Optional[Dict] = None):
        return self.post(
            f"{BASE}/evidence-packages/{package_id}/items",
            json={"item_type": item_type, "item_ref": item_ref},
            headers=headers,
        )

    def seal_evidence_package(self, package_id: str, headers: Optional[Dict] = None):
        return self.post(f"{BASE}/evidence-packages/{package_id}/seal", json={}, headers=headers)

    def withdraw_evidence_package(self, package_id: str, reason_code: Optional[str] = None,
                                  headers: Optional[Dict] = None):
        payload: Dict[str, Any] = {}
        if reason_code is not None:
            payload["reason_code"] = reason_code
        return self.post(f"{BASE}/evidence-packages/{package_id}/withdraw", json=payload, headers=headers)

    # -------------------------------------------------------------- takedowns
    def create_takedown(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self.post(f"{BASE}/takedowns", json=payload, headers=headers)

    def get_takedown(self, takedown_id: str, headers: Optional[Dict] = None):
        return self.get(f"{BASE}/takedowns/{takedown_id}", headers=headers)

    def list_takedowns(self, headers: Optional[Dict] = None, **params):
        return self.get(f"{BASE}/takedowns", headers=headers, params=params or None)

    def submit_takedown(self, takedown_id: str, headers: Optional[Dict] = None):
        return self.post(f"{BASE}/takedowns/{takedown_id}/submit", json={}, headers=headers)

    def decide_takedown(self, takedown_id: str, decision: str, marketplace_case_ref: str,
                        headers: Optional[Dict] = None):
        return self.post(
            f"{BASE}/takedowns/{takedown_id}/marketplace-decision",
            json={"decision": decision, "marketplace_case_ref": marketplace_case_ref},
            headers=headers,
        )

    def resubmit_takedown(self, takedown_id: str, evidence_package_id: str,
                          headers: Optional[Dict] = None):
        return self.post(
            f"{BASE}/takedowns/{takedown_id}/resubmit",
            json={"evidence_package_id": evidence_package_id},
            headers=headers,
        )

    # --------------------------------------------------------- counter notices
    def create_counter_notice(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self.post(f"{BASE}/counter-notices", json=payload, headers=headers)

    def get_counter_notice(self, counter_notice_id: str, headers: Optional[Dict] = None):
        return self.get(f"{BASE}/counter-notices/{counter_notice_id}", headers=headers)

    def list_counter_notices(self, headers: Optional[Dict] = None, **params):
        return self.get(f"{BASE}/counter-notices", headers=headers, params=params or None)

    def resolve_counter_notice(self, counter_notice_id: str, resolution: str,
                               rebuttal_ref: Optional[str] = None, headers: Optional[Dict] = None):
        payload: Dict[str, Any] = {"resolution": resolution}
        if rebuttal_ref is not None:
            payload["rebuttal_ref"] = rebuttal_ref
        return self.post(f"{BASE}/counter-notices/{counter_notice_id}/resolve",
                         json=payload, headers=headers)

    # ------------------------------------------------------------------ cases
    def create_case(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self.post(f"{BASE}/cases", json=payload, headers=headers)

    def get_case(self, case_id: str, headers: Optional[Dict] = None):
        return self.get(f"{BASE}/cases/{case_id}", headers=headers)

    def list_cases(self, headers: Optional[Dict] = None, **params):
        return self.get(f"{BASE}/cases", headers=headers, params=params or None)

    def send_cease_desist(self, case_id: str, letter_ref: str, headers: Optional[Dict] = None):
        return self.post(f"{BASE}/cases/{case_id}/cease-desist",
                         json={"letter_ref": letter_ref}, headers=headers)

    def record_case_response(self, case_id: str, response_ref: str, response_kind: str,
                             headers: Optional[Dict] = None):
        return self.post(
            f"{BASE}/cases/{case_id}/record-response",
            json={"response_ref": response_ref, "response_kind": response_kind},
            headers=headers,
        )

    def authorize_litigation(self, case_id: str, authorization_ref: str, headers: Optional[Dict] = None):
        return self.post(f"{BASE}/cases/{case_id}/authorize-litigation",
                         json={"authorization_ref": authorization_ref}, headers=headers)

    def file_suit(self, case_id: str, docket_ref: str, court_code: str, headers: Optional[Dict] = None):
        return self.post(f"{BASE}/cases/{case_id}/file-suit",
                         json={"docket_ref": docket_ref, "court_code": court_code}, headers=headers)

    def close_case(self, case_id: str, outcome: str, closure_note: Optional[str] = None,
                   headers: Optional[Dict] = None):
        payload: Dict[str, Any] = {"outcome": outcome}
        if closure_note is not None:
            payload["closure_note"] = closure_note
        return self.post(f"{BASE}/cases/{case_id}/close", json=payload, headers=headers)

    # ---------------------------------------------------- customs recordations
    def create_recordation(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self.post(f"{BASE}/customs-recordations", json=payload, headers=headers)

    def get_recordation(self, recordation_id: str, headers: Optional[Dict] = None):
        return self.get(f"{BASE}/customs-recordations/{recordation_id}", headers=headers)

    def list_recordations(self, headers: Optional[Dict] = None, **params):
        return self.get(f"{BASE}/customs-recordations", headers=headers, params=params or None)

    def record_recordation(self, recordation_id: str, recordation_number: str,
                           headers: Optional[Dict] = None):
        return self.post(f"{BASE}/customs-recordations/{recordation_id}/record",
                         json={"recordation_number": recordation_number}, headers=headers)

    # ------------------------------------------------ diversion investigations
    def create_investigation(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self.post(f"{BASE}/diversion-investigations", json=payload, headers=headers)

    def get_investigation(self, investigation_id: str, headers: Optional[Dict] = None):
        return self.get(f"{BASE}/diversion-investigations/{investigation_id}", headers=headers)

    def list_investigations(self, headers: Optional[Dict] = None, **params):
        return self.get(f"{BASE}/diversion-investigations", headers=headers, params=params or None)

    def submit_investigation_evidence(self, investigation_id: str, evidence_ref: str,
                                     suspected_distributor_ref: str, headers: Optional[Dict] = None):
        return self.post(
            f"{BASE}/diversion-investigations/{investigation_id}/submit-evidence",
            json={"evidence_ref": evidence_ref,
                  "suspected_distributor_ref": suspected_distributor_ref},
            headers=headers,
        )

    def conclude_investigation(self, investigation_id: str, outcome: str, findings_ref: str,
                               headers: Optional[Dict] = None):
        return self.post(
            f"{BASE}/diversion-investigations/{investigation_id}/conclude",
            json={"outcome": outcome, "findings_ref": findings_ref},
            headers=headers,
        )

    # ------------------------------------------------------------------- ops
    def run_enforcement_sweep(self, headers: Optional[Dict] = None):
        return self.post(f"{BASE}/ops/run-enforcement-sweep", json={}, headers=headers)


api_client = ApiClient()
