"""API client: one method per endpoint defined in the PRD."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Broadband Consumer Label Compliance API client."""

    # ---------------- logical clock ----------------

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---------------- service plans ----------------

    def create_service_plan(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/service-plans", payload, headers)

    def get_service_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/service-plans/{plan_id}", headers=headers)

    def amend_service_plan(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PATCH", f"/service-plans/{plan_id}", payload, headers)

    def add_fee_line_item(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/service-plans/{plan_id}/fee-line-items", payload, headers
        )

    def list_fee_line_items(
        self, plan_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/service-plans/{plan_id}/fee-line-items", headers=headers, params=params
        )

    # ---------------- methodology documents ----------------

    def create_methodology_document(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/methodology-documents", payload, headers)

    def get_methodology_document(self, doc_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/methodology-documents/{doc_id}", headers=headers)

    def publish_methodology_document(self, doc_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/methodology-documents/{doc_id}/publish", {}, headers
        )

    # ---------------- measurement probes ----------------

    def create_measurement_probe(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/measurement-probes", payload, headers)

    def get_measurement_probe(self, probe_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/measurement-probes/{probe_id}", headers=headers)

    # ---------------- test runs ----------------

    def create_test_run(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/test-runs", payload, headers)

    def get_test_run(self, run_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/test-runs/{run_id}", headers=headers)

    def list_test_runs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/test-runs", headers=headers, params=params)

    def invalidate_test_run(
        self, run_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/test-runs/{run_id}/invalidate", payload, headers)

    # ---------------- performance attestations ----------------

    def create_performance_attestation(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/performance-attestations", payload, headers)

    def certify_performance_attestation(self, attestation_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/performance-attestations/{attestation_id}/certify", {}, headers
        )

    def get_performance_attestation(self, attestation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/performance-attestations/{attestation_id}", headers=headers
        )

    def list_performance_attestations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/performance-attestations", headers=headers, params=params
        )

    # ---------------- label versions ----------------

    def create_label_version(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/label-versions", payload, headers)

    def get_label_version(self, label_version_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/label-versions/{label_version_id}", headers=headers)

    def list_label_versions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/label-versions", headers=headers, params=params)

    def publish_label_version(self, label_version_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/label-versions/{label_version_id}/publish", {}, headers
        )

    def withdraw_label_version(
        self, label_version_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/label-versions/{label_version_id}/withdraw", payload, headers
        )

    def create_label_translation(
        self, label_version_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/label-versions/{label_version_id}/translations", payload, headers
        )

    def list_label_translations(
        self,
        label_version_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"/label-versions/{label_version_id}/translations",
            headers=headers,
            params=params,
        )

    def verify_label_translation(
        self, label_version_id: str, translation_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/label-versions/{label_version_id}/translations/{translation_id}/verify",
            {},
            headers,
        )

    def list_label_version_disclosures(
        self,
        label_version_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"/label-versions/{label_version_id}/disclosures",
            headers=headers,
            params=params,
        )

    # ---------------- subscriber accounts and disclosures ----------------

    def create_subscriber_account(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/subscriber-accounts", payload, headers)

    def get_subscriber_account(self, account_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/subscriber-accounts/{account_id}", headers=headers)

    def list_subscriber_accounts(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/subscriber-accounts", headers=headers, params=params)

    def record_label_disclosure(
        self, account_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/subscriber-accounts/{account_id}/label-disclosures", payload, headers
        )

    def list_account_label_disclosures(
        self, account_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/subscriber-accounts/{account_id}/label-disclosures",
            headers=headers,
            params=params,
        )

    # ---------------- complaints ----------------

    def create_complaint(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/complaints", payload, headers)

    def get_complaint(self, complaint_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def list_complaints(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/complaints", headers=headers, params=params)

    def triage_complaint(
        self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/complaints/{complaint_id}/triage", payload, headers)

    def investigate_complaint(self, complaint_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/complaints/{complaint_id}/investigate", {}, headers)

    def request_complaint_info(
        self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/complaints/{complaint_id}/request-info", payload, headers
        )

    def resolve_complaint(
        self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/complaints/{complaint_id}/resolve", payload, headers
        )

    def reopen_complaint(
        self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/complaints/{complaint_id}/reopen", payload, headers)

    def withdraw_complaint(
        self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/complaints/{complaint_id}/withdraw", payload, headers
        )

    # ---------------- remediation credits ----------------

    def list_complaint_remediation_credits(
        self, complaint_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/complaints/{complaint_id}/remediation-credits",
            headers=headers,
            params=params,
        )

    def get_remediation_credit(self, credit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/remediation-credits/{credit_id}", headers=headers)

    def void_remediation_credit(
        self, credit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/remediation-credits/{credit_id}/void", payload, headers
        )

    # ---------------- regulator inquiries ----------------

    def create_regulator_inquiry(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/regulator-inquiries", payload, headers)

    def get_regulator_inquiry(self, inquiry_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/regulator-inquiries/{inquiry_id}", headers=headers)

    def list_regulator_inquiries(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/regulator-inquiries", headers=headers, params=params)

    def file_inquiry_filing(
        self, inquiry_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/regulator-inquiries/{inquiry_id}/filings", payload, headers
        )

    def close_regulator_inquiry(
        self, inquiry_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/regulator-inquiries/{inquiry_id}/close", payload, headers
        )

    # ---------------- plan change notices ----------------

    def create_plan_change_notice(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/plan-change-notices", payload, headers)

    def get_plan_change_notice(self, notice_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/plan-change-notices/{notice_id}", headers=headers)

    def list_plan_change_notices(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/plan-change-notices", headers=headers, params=params)

    def acknowledge_plan_change_notice(self, notice_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/plan-change-notices/{notice_id}/acknowledge", {}, headers
        )

    def effect_plan_change_notice(self, notice_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/plan-change-notices/{notice_id}/effect", {}, headers
        )


api_client = ApiClient()
