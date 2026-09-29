"""One named method per documented route of the Content Moderation API.

Tests never build a URL string. Every method returns the raw
``requests.Response`` so a test can assert on success bodies or on error
envelopes with equal convenience.
"""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


def _compact(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is the sentinel ``None`` placeholder.

    A test that wants to send an explicit JSON null passes ``NULL`` from this
    module; a test that simply omits an optional input leaves the keyword out
    or passes ``None``.
    """
    return {k: v for k, v in payload.items() if v is not None}


class ApiClient(GenericApiClient):
    """Route-aware client for the Content Moderation Operations API."""

    # -- Clock ------------------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/_clock/set_current_utc",
            json={"to_iso8601": to_iso8601},
            headers=headers,
        )

    def set_clock_raw(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.post(f"{API_PREFIX}/_clock/set_current_utc", json=payload, headers=headers)

    # -- Accounts ---------------------------------------------------------

    def create_account(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.post(f"{API_PREFIX}/accounts", json=payload, headers=headers)

    def get_account(self, account_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/accounts/{account_id}", headers=headers)

    # -- Content items ----------------------------------------------------

    def create_content_item(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.post(f"{API_PREFIX}/content-items", json=payload, headers=headers)

    def get_content_item(self, content_item_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/content-items/{content_item_id}", headers=headers)

    def list_content_items(
        self,
        headers: Optional[Dict[str, str]] = None,
        account_id: Optional[str] = None,
        visibility_status: Optional[str] = None,
        review_status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        params = _compact(
            {
                "account_id": account_id,
                "visibility_status": visibility_status,
                "review_status": review_status,
                "limit": limit,
                "offset": offset,
            }
        )
        return self.get(f"{API_PREFIX}/content-items", headers=headers, params=params)

    def list_content_item_detection_signals(
        self,
        content_item_id: str,
        headers: Optional[Dict[str, str]] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        params = _compact({"limit": limit, "offset": offset})
        return self.get(
            f"{API_PREFIX}/content-items/{content_item_id}/detection-signals",
            headers=headers,
            params=params,
        )

    # -- Policy categories ------------------------------------------------

    def create_policy_category(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.post(f"{API_PREFIX}/policy-categories", json=payload, headers=headers)

    def get_policy_category(self, category_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/policy-categories/{category_id}", headers=headers)

    def list_policy_categories(
        self,
        headers: Optional[Dict[str, str]] = None,
        parent_category_id: Optional[str] = None,
        status: Optional[str] = None,
        specialty: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        params = _compact(
            {
                "parent_category_id": parent_category_id,
                "status": status,
                "specialty": specialty,
                "limit": limit,
                "offset": offset,
            }
        )
        return self.get(f"{API_PREFIX}/policy-categories", headers=headers, params=params)

    # -- Policy versions --------------------------------------------------

    def create_policy_version(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.post(f"{API_PREFIX}/policy-versions", json=payload, headers=headers)

    def back_test_policy_version(
        self,
        policy_version_id: str,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/policy-versions/{policy_version_id}/back-test",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def revise_policy_version(
        self,
        policy_version_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/policy-versions/{policy_version_id}/revise",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def activate_policy_version(
        self,
        policy_version_id: str,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/policy-versions/{policy_version_id}/activate",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def get_policy_version(self, policy_version_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/policy-versions/{policy_version_id}", headers=headers)

    def list_policy_versions(
        self,
        headers: Optional[Dict[str, str]] = None,
        policy_category_id: Optional[str] = None,
        supersedes_version_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        params = _compact(
            {
                "policy_category_id": policy_category_id,
                "supersedes_version_id": supersedes_version_id,
                "status": status,
                "limit": limit,
                "offset": offset,
            }
        )
        return self.get(f"{API_PREFIX}/policy-versions", headers=headers, params=params)

    # -- Review queues ----------------------------------------------------

    def create_review_queue(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.post(f"{API_PREFIX}/review-queues", json=payload, headers=headers)

    def get_review_queue(self, queue_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/review-queues/{queue_id}", headers=headers)

    def list_review_queues(
        self,
        headers: Optional[Dict[str, str]] = None,
        policy_category_id: Optional[str] = None,
        language: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        params = _compact(
            {
                "policy_category_id": policy_category_id,
                "language": language,
                "limit": limit,
                "offset": offset,
            }
        )
        return self.get(f"{API_PREFIX}/review-queues", headers=headers, params=params)

    # -- Reviewers --------------------------------------------------------

    def create_reviewer(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.post(f"{API_PREFIX}/reviewers", json=payload, headers=headers)

    def grant_certification(
        self,
        reviewer_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/reviewers/{reviewer_id}/certifications",
            json=payload,
            headers=headers,
        )

    def start_wellness_break(
        self,
        reviewer_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/reviewers/{reviewer_id}/wellness-break",
            json=payload,
            headers=headers,
        )

    def return_to_duty(
        self,
        reviewer_id: str,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/reviewers/{reviewer_id}/return-to-duty",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def get_reviewer(self, reviewer_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/reviewers/{reviewer_id}", headers=headers)

    def list_reviewers(
        self,
        headers: Optional[Dict[str, str]] = None,
        status: Optional[str] = None,
        language: Optional[str] = None,
        specialty: Optional[str] = None,
        role_class: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        params = _compact(
            {
                "status": status,
                "language": language,
                "specialty": specialty,
                "role_class": role_class,
                "limit": limit,
                "offset": offset,
            }
        )
        return self.get(f"{API_PREFIX}/reviewers", headers=headers, params=params)

    # -- Detection signals ------------------------------------------------

    def create_detection_signal(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.post(f"{API_PREFIX}/detection-signals", json=payload, headers=headers)

    def get_detection_signal(self, signal_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/detection-signals/{signal_id}", headers=headers)

    # -- Moderation cases -------------------------------------------------

    def create_moderation_case(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.post(f"{API_PREFIX}/moderation-cases", json=payload, headers=headers)

    def assign_case(
        self,
        case_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/moderation-cases/{case_id}/assign",
            json=payload,
            headers=headers,
        )

    def decide_case(
        self,
        case_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/moderation-cases/{case_id}/decide",
            json=payload,
            headers=headers,
        )

    def escalate_case(
        self,
        case_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/moderation-cases/{case_id}/escalate",
            json=payload,
            headers=headers,
        )

    def return_case_to_queue(
        self,
        case_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/moderation-cases/{case_id}/return-to-queue",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def get_moderation_case(self, case_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/moderation-cases/{case_id}", headers=headers)

    def list_moderation_cases(
        self,
        headers: Optional[Dict[str, str]] = None,
        content_item_id: Optional[str] = None,
        detection_signal_id: Optional[str] = None,
        policy_version_id: Optional[str] = None,
        queue_id: Optional[str] = None,
        assigned_reviewer_id: Optional[str] = None,
        decided_by_reviewer_id: Optional[str] = None,
        status: Optional[str] = None,
        origin: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        params = _compact(
            {
                "content_item_id": content_item_id,
                "detection_signal_id": detection_signal_id,
                "policy_version_id": policy_version_id,
                "queue_id": queue_id,
                "assigned_reviewer_id": assigned_reviewer_id,
                "decided_by_reviewer_id": decided_by_reviewer_id,
                "status": status,
                "origin": origin,
                "limit": limit,
                "offset": offset,
            }
        )
        return self.get(f"{API_PREFIX}/moderation-cases", headers=headers, params=params)

    # -- Appeals ----------------------------------------------------------

    def create_appeal(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.post(f"{API_PREFIX}/appeals", json=payload, headers=headers)

    def assign_appeal_reviewer(
        self,
        appeal_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/appeals/{appeal_id}/assign-reviewer",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def resolve_appeal(
        self,
        appeal_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/appeals/{appeal_id}/resolve",
            json=payload,
            headers=headers,
        )

    def get_appeal(self, appeal_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/appeals/{appeal_id}", headers=headers)

    def list_appeals(
        self,
        headers: Optional[Dict[str, str]] = None,
        case_id: Optional[str] = None,
        account_id: Optional[str] = None,
        independent_reviewer_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        params = _compact(
            {
                "case_id": case_id,
                "account_id": account_id,
                "independent_reviewer_id": independent_reviewer_id,
                "status": status,
                "limit": limit,
                "offset": offset,
            }
        )
        return self.get(f"{API_PREFIX}/appeals", headers=headers, params=params)

    # -- Audit samples ----------------------------------------------------

    def create_audit_sample(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.post(f"{API_PREFIX}/audit-samples", json=payload, headers=headers)

    def record_audit_verdict(
        self,
        audit_sample_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/audit-samples/{audit_sample_id}/audit",
            json=payload,
            headers=headers,
        )

    def dispute_audit_sample(
        self,
        audit_sample_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/audit-samples/{audit_sample_id}/dispute",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def get_audit_sample(self, audit_sample_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/audit-samples/{audit_sample_id}", headers=headers)

    def list_audit_samples(
        self,
        headers: Optional[Dict[str, str]] = None,
        case_id: Optional[str] = None,
        auditor_reviewer_id: Optional[str] = None,
        status: Optional[str] = None,
        verdict: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        params = _compact(
            {
                "case_id": case_id,
                "auditor_reviewer_id": auditor_reviewer_id,
                "status": status,
                "verdict": verdict,
                "limit": limit,
                "offset": offset,
            }
        )
        return self.get(f"{API_PREFIX}/audit-samples", headers=headers, params=params)

    # -- Transparency reports ---------------------------------------------

    def create_transparency_report(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.post(f"{API_PREFIX}/transparency-reports", json=payload, headers=headers)

    def compute_transparency_report(
        self,
        report_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/transparency-reports/{report_id}/compute",
            json=payload,
            headers=headers,
        )

    def publish_transparency_report(
        self,
        report_id: str,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/transparency-reports/{report_id}/publish",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def get_transparency_report(self, report_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/transparency-reports/{report_id}", headers=headers)

    # -- Raw escape hatches ------------------------------------------------

    def raw_get(self, path: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self.get(path, headers=headers, params=params)

    def raw_post(self, path: str, payload: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.post(path, json=payload if payload is not None else {}, headers=headers)


# A single shared client instance the whole suite imports.
api_client = ApiClient()
