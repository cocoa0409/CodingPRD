"""
Typed HTTP client for the De Novo Bank Charter Application API.

One method per endpoint declared in PRD section 4, all mounted under the
`/de-novo` prefix. Every method returns the raw requests.Response so callers
can assert on status codes as well as bodies.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/de-novo"


class DeNovoApiClient(GenericApiClient):
    """Endpoint-per-method client for the chartering service."""

    # =====================================================================
    # Reads: single resources (PRD 4)
    # =====================================================================
    def get_organizing_group(self, group_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/organizing-groups/{group_id}", headers=headers)

    def get_organizer(self, organizer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/organizers/{organizer_id}", headers=headers)

    def get_business_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/business-plans/{plan_id}", headers=headers)

    def get_stress_scenario(self, scenario_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/stress-scenarios/{scenario_id}", headers=headers)

    def get_capital_raise(self, raise_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/capital-raises/{raise_id}", headers=headers)

    def get_subscription(self, subscription_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/subscriptions/{subscription_id}", headers=headers)

    def get_regulatory_filing(self, filing_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/regulatory-filings/{filing_id}", headers=headers)

    def get_approval_condition(self, condition_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/approval-conditions/{condition_id}", headers=headers)

    def get_policy_document(self, policy_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/policy-documents/{policy_id}", headers=headers)

    def get_vendor_contract(self, contract_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/vendor-contracts/{contract_id}", headers=headers)

    def get_conversion_window(self, window_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/conversion-windows/{window_id}", headers=headers)

    def get_readiness_exam(self, exam_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/readiness-exams/{exam_id}", headers=headers)

    def get_deviation_request(self, deviation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/deviation-requests/{deviation_id}", headers=headers)

    # =====================================================================
    # Reads: collections (PRD 2.3, 4)
    # =====================================================================
    def list_organizers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/organizers", headers=headers, params=params)

    def list_business_plans(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/business-plans", headers=headers, params=params)

    def list_stress_scenarios(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/stress-scenarios", headers=headers, params=params)

    def list_capital_raises(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/capital-raises", headers=headers, params=params)

    def list_subscriptions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/subscriptions", headers=headers, params=params)

    def list_regulatory_filings(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/regulatory-filings", headers=headers, params=params)

    def list_approval_conditions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/approval-conditions", headers=headers, params=params)

    def list_policy_documents(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/policy-documents", headers=headers, params=params)

    def list_vendor_contracts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/vendor-contracts", headers=headers, params=params)

    def list_conversion_windows(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/conversion-windows", headers=headers, params=params)

    def list_readiness_exams(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/readiness-exams", headers=headers, params=params)

    def list_deviation_requests(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/deviation-requests", headers=headers, params=params)

    # =====================================================================
    # Computed read (PRD 3.3)
    # =====================================================================
    def get_capital_adequacy(
        self,
        group_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/organizing-groups/{group_id}/capital-adequacy",
            headers=headers,
            params=params,
        )

    # =====================================================================
    # Organizing group and organizers (PRD 3.1)
    # =====================================================================
    def create_organizing_group(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/organizing-groups", payload, headers)

    def create_organizer(self, group_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/organizing-groups/{group_id}/organizers", payload, headers
        )

    def record_background_result(
        self, organizer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/organizers/{organizer_id}/background-result", payload, headers
        )

    def grant_qualification_waiver(
        self, organizer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/organizers/{organizer_id}/qualification-waiver", payload, headers
        )

    def advance_group(self, group_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/organizing-groups/{group_id}/advance", payload, headers
        )

    # =====================================================================
    # Business plan and stress overlays (PRD 3.2, 3.3)
    # =====================================================================
    def create_business_plan(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/business-plans", payload, headers)

    def create_stress_scenario(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/business-plans/{plan_id}/stress-scenarios", payload, headers
        )

    def submit_business_plan(
        self, plan_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/business-plans/{plan_id}/submit", payload or {}, headers
        )

    # =====================================================================
    # Capital raise, subscriptions and escrow (PRD 3.4)
    # =====================================================================
    def create_capital_raise(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/capital-raises", payload, headers)

    def open_capital_raise(
        self, raise_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/capital-raises/{raise_id}/open", payload or {}, headers
        )

    def lock_escrow(
        self, raise_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/capital-raises/{raise_id}/lock-escrow", payload or {}, headers
        )

    def release_escrow(
        self, raise_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/capital-raises/{raise_id}/release-escrow", payload or {}, headers
        )

    def create_subscription(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/subscriptions", payload, headers)

    def record_funding_event(
        self, subscription_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/subscriptions/{subscription_id}/funding", payload, headers
        )

    def record_screening_result(
        self, subscription_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/subscriptions/{subscription_id}/screening-result", payload, headers
        )

    # =====================================================================
    # Filings and conditions of approval (PRD 3.5, 3.6)
    # =====================================================================
    def create_regulatory_filing(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/regulatory-filings", payload, headers)

    def file_regulatory_filing(
        self, filing_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/regulatory-filings/{filing_id}/file", payload or {}, headers
        )

    def record_filing_decision(
        self, filing_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/regulatory-filings/{filing_id}/decision", payload, headers
        )

    def create_approval_condition(
        self, filing_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/regulatory-filings/{filing_id}/conditions", payload, headers
        )

    def submit_condition_evidence(
        self, condition_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/approval-conditions/{condition_id}/evidence", payload, headers
        )

    def adjudicate_condition(
        self, condition_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/approval-conditions/{condition_id}/adjudicate", payload, headers
        )

    # =====================================================================
    # Policies, vendors and conversion windows (PRD 3.7)
    # =====================================================================
    def create_policy_document(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/policy-documents", payload, headers)

    def adopt_policy_document(
        self, policy_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/policy-documents/{policy_id}/adopt", payload or {}, headers
        )

    def review_policy_document(
        self, policy_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/policy-documents/{policy_id}/examiner-review", payload, headers
        )

    def create_vendor_contract(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/vendor-contracts", payload, headers)

    def advance_vendor_contract(
        self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/vendor-contracts/{contract_id}/advance", payload, headers
        )

    def create_conversion_window(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/conversion-windows", payload, headers)

    def confirm_conversion_window(
        self, window_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/conversion-windows/{window_id}/confirm", payload or {}, headers
        )

    # =====================================================================
    # Readiness examination (PRD 3.8)
    # =====================================================================
    def create_readiness_exam(
        self, group_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/organizing-groups/{group_id}/readiness-exams", payload, headers
        )

    def record_exam_result(self, exam_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/readiness-exams/{exam_id}/result", payload, headers
        )

    # =====================================================================
    # Heightened supervision (PRD 3.9)
    # =====================================================================
    def create_deviation_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/deviation-requests", payload, headers)

    def record_deviation_decision(
        self, deviation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/deviation-requests/{deviation_id}/decision", payload, headers
        )

    # =====================================================================
    # Logical clock (PRD 2.4)
    # =====================================================================
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )
