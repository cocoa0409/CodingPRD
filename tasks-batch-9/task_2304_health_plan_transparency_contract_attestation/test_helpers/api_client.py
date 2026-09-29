"""HTTP client exposing one method per endpoint of the compliance API.

Every method returns the raw ``requests.Response`` so tests can assert on the
status code as well as the body. All paths are mounted under the
``/compliance`` prefix.
"""

from __future__ import annotations

from typing import Any, Mapping

import requests

from prd_bench_local_runner.testing import GenericApiClient

JsonDict = dict[str, Any]
Headers = Mapping[str, str]

PREFIX = "/compliance"


class ApiClient(GenericApiClient):
    """Endpoint methods for the Health Plan Transparency Compliance API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, payload: JsonDict, headers: Headers) -> requests.Response:
        """POST /compliance/_clock/set_current_utc"""
        return self._request(
            "POST",
            f"{PREFIX}/_clock/set_current_utc",
            payload=payload,
            headers=dict(headers),
        )

    # ------------------------------------------------------------------
    # Plan years
    # ------------------------------------------------------------------

    def create_plan_year(
        self, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/plan-years"""
        return self._request(
            "POST", f"{PREFIX}/plan-years", payload=payload, headers=dict(headers)
        )

    def get_plan_year(self, plan_year_id: str, headers: Headers) -> requests.Response:
        """GET /compliance/plan-years/{id}"""
        return self._request(
            "GET", f"{PREFIX}/plan-years/{plan_year_id}", headers=dict(headers)
        )

    def list_plan_years(
        self, headers: Headers, params: JsonDict | None = None
    ) -> requests.Response:
        """GET /compliance/plan-years"""
        return self._request(
            "GET", f"{PREFIX}/plan-years", headers=dict(headers), params=params
        )

    def activate_plan_year(
        self, plan_year_id: str, headers: Headers, payload: JsonDict | None = None
    ) -> requests.Response:
        """POST /compliance/plan-years/{id}/activate"""
        return self._request(
            "POST",
            f"{PREFIX}/plan-years/{plan_year_id}/activate",
            payload=payload if payload is not None else {},
            headers=dict(headers),
        )

    def close_reporting(
        self, plan_year_id: str, headers: Headers, payload: JsonDict | None = None
    ) -> requests.Response:
        """POST /compliance/plan-years/{id}/close-reporting"""
        return self._request(
            "POST",
            f"{PREFIX}/plan-years/{plan_year_id}/close-reporting",
            payload=payload if payload is not None else {},
            headers=dict(headers),
        )

    def freeze_plan_year(
        self, plan_year_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/plan-years/{id}/freeze"""
        return self._request(
            "POST",
            f"{PREFIX}/plan-years/{plan_year_id}/freeze",
            payload=payload,
            headers=dict(headers),
        )

    def unfreeze_plan_year(
        self, plan_year_id: str, headers: Headers, payload: JsonDict | None = None
    ) -> requests.Response:
        """POST /compliance/plan-years/{id}/unfreeze"""
        return self._request(
            "POST",
            f"{PREFIX}/plan-years/{plan_year_id}/unfreeze",
            payload=payload if payload is not None else {},
            headers=dict(headers),
        )

    def run_compliance(
        self, plan_year_id: str, headers: Headers, payload: JsonDict | None = None
    ) -> requests.Response:
        """POST /compliance/plan-years/{id}/compliance-runs"""
        return self._request(
            "POST",
            f"{PREFIX}/plan-years/{plan_year_id}/compliance-runs",
            payload=payload if payload is not None else {},
            headers=dict(headers),
        )

    def get_penalty_projection(
        self, plan_year_id: str, headers: Headers, params: JsonDict | None = None
    ) -> requests.Response:
        """GET /compliance/plan-years/{id}/penalty-projection"""
        return self._request(
            "GET",
            f"{PREFIX}/plan-years/{plan_year_id}/penalty-projection",
            headers=dict(headers),
            params=params,
        )

    # ------------------------------------------------------------------
    # Vendors
    # ------------------------------------------------------------------

    def create_vendor(self, payload: JsonDict, headers: Headers) -> requests.Response:
        """POST /compliance/vendors"""
        return self._request(
            "POST", f"{PREFIX}/vendors", payload=payload, headers=dict(headers)
        )

    def get_vendor(self, vendor_id: str, headers: Headers) -> requests.Response:
        """GET /compliance/vendors/{id}"""
        return self._request(
            "GET", f"{PREFIX}/vendors/{vendor_id}", headers=dict(headers)
        )

    def list_vendors(
        self, headers: Headers, params: JsonDict | None = None
    ) -> requests.Response:
        """GET /compliance/vendors"""
        return self._request(
            "GET", f"{PREFIX}/vendors", headers=dict(headers), params=params
        )

    # ------------------------------------------------------------------
    # Service provider contracts
    # ------------------------------------------------------------------

    def create_contract(
        self, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/contracts"""
        return self._request(
            "POST", f"{PREFIX}/contracts", payload=payload, headers=dict(headers)
        )

    def get_contract(self, contract_id: str, headers: Headers) -> requests.Response:
        """GET /compliance/contracts/{id}"""
        return self._request(
            "GET", f"{PREFIX}/contracts/{contract_id}", headers=dict(headers)
        )

    def list_contracts(
        self, headers: Headers, params: JsonDict | None = None
    ) -> requests.Response:
        """GET /compliance/contracts"""
        return self._request(
            "GET", f"{PREFIX}/contracts", headers=dict(headers), params=params
        )

    def gag_review(
        self, contract_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/contracts/{id}/gag-review"""
        return self._request(
            "POST",
            f"{PREFIX}/contracts/{contract_id}/gag-review",
            payload=payload,
            headers=dict(headers),
        )

    def request_remediation(
        self, contract_id: str, headers: Headers, payload: JsonDict | None = None
    ) -> requests.Response:
        """POST /compliance/contracts/{id}/request-remediation"""
        return self._request(
            "POST",
            f"{PREFIX}/contracts/{contract_id}/request-remediation",
            payload=payload if payload is not None else {},
            headers=dict(headers),
        )

    def submit_remediation(
        self, contract_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/contracts/{id}/submit-remediation"""
        return self._request(
            "POST",
            f"{PREFIX}/contracts/{contract_id}/submit-remediation",
            payload=payload,
            headers=dict(headers),
        )

    def clear_gag(
        self, contract_id: str, headers: Headers, payload: JsonDict | None = None
    ) -> requests.Response:
        """POST /compliance/contracts/{id}/clear-gag"""
        return self._request(
            "POST",
            f"{PREFIX}/contracts/{contract_id}/clear-gag",
            payload=payload if payload is not None else {},
            headers=dict(headers),
        )

    def escalate_gag(
        self, contract_id: str, headers: Headers, payload: JsonDict | None = None
    ) -> requests.Response:
        """POST /compliance/contracts/{id}/escalate-gag"""
        return self._request(
            "POST",
            f"{PREFIX}/contracts/{contract_id}/escalate-gag",
            payload=payload if payload is not None else {},
            headers=dict(headers),
        )

    # ------------------------------------------------------------------
    # Contract amendments
    # ------------------------------------------------------------------

    def create_amendment(
        self, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/contract-amendments"""
        return self._request(
            "POST",
            f"{PREFIX}/contract-amendments",
            payload=payload,
            headers=dict(headers),
        )

    def get_amendment(self, amendment_id: str, headers: Headers) -> requests.Response:
        """GET /compliance/contract-amendments/{id}"""
        return self._request(
            "GET",
            f"{PREFIX}/contract-amendments/{amendment_id}",
            headers=dict(headers),
        )

    def list_amendments(
        self, headers: Headers, params: JsonDict | None = None
    ) -> requests.Response:
        """GET /compliance/contract-amendments"""
        return self._request(
            "GET",
            f"{PREFIX}/contract-amendments",
            headers=dict(headers),
            params=params,
        )

    def counter_amendment(
        self, amendment_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/contract-amendments/{id}/counter"""
        return self._request(
            "POST",
            f"{PREFIX}/contract-amendments/{amendment_id}/counter",
            payload=payload,
            headers=dict(headers),
        )

    def revise_proposal(
        self, amendment_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/contract-amendments/{id}/revise-proposal"""
        return self._request(
            "POST",
            f"{PREFIX}/contract-amendments/{amendment_id}/revise-proposal",
            payload=payload,
            headers=dict(headers),
        )

    def execute_amendment(
        self, amendment_id: str, headers: Headers, payload: JsonDict | None = None
    ) -> requests.Response:
        """POST /compliance/contract-amendments/{id}/execute"""
        return self._request(
            "POST",
            f"{PREFIX}/contract-amendments/{amendment_id}/execute",
            payload=payload if payload is not None else {},
            headers=dict(headers),
        )

    # ------------------------------------------------------------------
    # Compensation disclosures
    # ------------------------------------------------------------------

    def create_compensation_disclosure(
        self, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/compensation-disclosures"""
        return self._request(
            "POST",
            f"{PREFIX}/compensation-disclosures",
            payload=payload,
            headers=dict(headers),
        )

    def get_compensation_disclosure(
        self, disclosure_id: str, headers: Headers
    ) -> requests.Response:
        """GET /compliance/compensation-disclosures/{id}"""
        return self._request(
            "GET",
            f"{PREFIX}/compensation-disclosures/{disclosure_id}",
            headers=dict(headers),
        )

    def list_compensation_disclosures(
        self, headers: Headers, params: JsonDict | None = None
    ) -> requests.Response:
        """GET /compliance/compensation-disclosures"""
        return self._request(
            "GET",
            f"{PREFIX}/compensation-disclosures",
            headers=dict(headers),
            params=params,
        )

    def assess_compensation_disclosure(
        self, disclosure_id: str, headers: Headers, payload: JsonDict | None = None
    ) -> requests.Response:
        """POST /compliance/compensation-disclosures/{id}/assess"""
        return self._request(
            "POST",
            f"{PREFIX}/compensation-disclosures/{disclosure_id}/assess",
            payload=payload if payload is not None else {},
            headers=dict(headers),
        )

    # ------------------------------------------------------------------
    # Machine-readable files
    # ------------------------------------------------------------------

    def create_mrf(self, payload: JsonDict, headers: Headers) -> requests.Response:
        """POST /compliance/machine-readable-files"""
        return self._request(
            "POST",
            f"{PREFIX}/machine-readable-files",
            payload=payload,
            headers=dict(headers),
        )

    def get_mrf(self, mrf_id: str, headers: Headers) -> requests.Response:
        """GET /compliance/machine-readable-files/{id}"""
        return self._request(
            "GET",
            f"{PREFIX}/machine-readable-files/{mrf_id}",
            headers=dict(headers),
        )

    def list_mrfs(
        self, headers: Headers, params: JsonDict | None = None
    ) -> requests.Response:
        """GET /compliance/machine-readable-files"""
        return self._request(
            "GET",
            f"{PREFIX}/machine-readable-files",
            headers=dict(headers),
            params=params,
        )

    def validate_mrf(
        self, mrf_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/machine-readable-files/{id}/validate"""
        return self._request(
            "POST",
            f"{PREFIX}/machine-readable-files/{mrf_id}/validate",
            payload=payload,
            headers=dict(headers),
        )

    def revise_mrf(
        self, mrf_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/machine-readable-files/{id}/revise"""
        return self._request(
            "POST",
            f"{PREFIX}/machine-readable-files/{mrf_id}/revise",
            payload=payload,
            headers=dict(headers),
        )

    # ------------------------------------------------------------------
    # Refresh cycles
    # ------------------------------------------------------------------

    def create_refresh_cycle(
        self, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/refresh-cycles"""
        return self._request(
            "POST", f"{PREFIX}/refresh-cycles", payload=payload, headers=dict(headers)
        )

    def get_refresh_cycle(self, cycle_id: str, headers: Headers) -> requests.Response:
        """GET /compliance/refresh-cycles/{id}"""
        return self._request(
            "GET", f"{PREFIX}/refresh-cycles/{cycle_id}", headers=dict(headers)
        )

    def list_refresh_cycles(
        self, headers: Headers, params: JsonDict | None = None
    ) -> requests.Response:
        """GET /compliance/refresh-cycles"""
        return self._request(
            "GET", f"{PREFIX}/refresh-cycles", headers=dict(headers), params=params
        )

    def certify_refresh_cycle(
        self, cycle_id: str, headers: Headers, payload: JsonDict | None = None
    ) -> requests.Response:
        """POST /compliance/refresh-cycles/{id}/certify"""
        return self._request(
            "POST",
            f"{PREFIX}/refresh-cycles/{cycle_id}/certify",
            payload=payload if payload is not None else {},
            headers=dict(headers),
        )

    # ------------------------------------------------------------------
    # Price comparison tools
    # ------------------------------------------------------------------

    def create_price_comparison_tool(
        self, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/price-comparison-tools"""
        return self._request(
            "POST",
            f"{PREFIX}/price-comparison-tools",
            payload=payload,
            headers=dict(headers),
        )

    def get_price_comparison_tool(
        self, tool_id: str, headers: Headers
    ) -> requests.Response:
        """GET /compliance/price-comparison-tools/{id}"""
        return self._request(
            "GET",
            f"{PREFIX}/price-comparison-tools/{tool_id}",
            headers=dict(headers),
        )

    def list_price_comparison_tools(
        self, headers: Headers, params: JsonDict | None = None
    ) -> requests.Response:
        """GET /compliance/price-comparison-tools"""
        return self._request(
            "GET",
            f"{PREFIX}/price-comparison-tools",
            headers=dict(headers),
            params=params,
        )

    def launch_price_comparison_tool(
        self, tool_id: str, headers: Headers, payload: JsonDict | None = None
    ) -> requests.Response:
        """POST /compliance/price-comparison-tools/{id}/launch"""
        return self._request(
            "POST",
            f"{PREFIX}/price-comparison-tools/{tool_id}/launch",
            payload=payload if payload is not None else {},
            headers=dict(headers),
        )

    def append_outage_window(
        self, tool_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/price-comparison-tools/{id}/outage-windows"""
        return self._request(
            "POST",
            f"{PREFIX}/price-comparison-tools/{tool_id}/outage-windows",
            payload=payload,
            headers=dict(headers),
        )

    def evaluate_price_comparison_tool(
        self, tool_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/price-comparison-tools/{id}/evaluations"""
        return self._request(
            "POST",
            f"{PREFIX}/price-comparison-tools/{tool_id}/evaluations",
            payload=payload,
            headers=dict(headers),
        )

    # ------------------------------------------------------------------
    # Prescription-drug data submissions
    # ------------------------------------------------------------------

    def create_rx_submission(
        self, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/rx-data-submissions"""
        return self._request(
            "POST",
            f"{PREFIX}/rx-data-submissions",
            payload=payload,
            headers=dict(headers),
        )

    def get_rx_submission(
        self, submission_id: str, headers: Headers
    ) -> requests.Response:
        """GET /compliance/rx-data-submissions/{id}"""
        return self._request(
            "GET",
            f"{PREFIX}/rx-data-submissions/{submission_id}",
            headers=dict(headers),
        )

    def list_rx_submissions(
        self, headers: Headers, params: JsonDict | None = None
    ) -> requests.Response:
        """GET /compliance/rx-data-submissions"""
        return self._request(
            "GET",
            f"{PREFIX}/rx-data-submissions",
            headers=dict(headers),
            params=params,
        )

    def reconcile_rx_submission(
        self, submission_id: str, headers: Headers, payload: JsonDict | None = None
    ) -> requests.Response:
        """POST /compliance/rx-data-submissions/{id}/reconcile"""
        return self._request(
            "POST",
            f"{PREFIX}/rx-data-submissions/{submission_id}/reconcile",
            payload=payload if payload is not None else {},
            headers=dict(headers),
        )

    def submit_rx_submission(
        self, submission_id: str, headers: Headers, payload: JsonDict | None = None
    ) -> requests.Response:
        """POST /compliance/rx-data-submissions/{id}/submit"""
        return self._request(
            "POST",
            f"{PREFIX}/rx-data-submissions/{submission_id}/submit",
            payload=payload if payload is not None else {},
            headers=dict(headers),
        )

    # ------------------------------------------------------------------
    # Vendor data packages
    # ------------------------------------------------------------------

    def create_vendor_data_package(
        self, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/vendor-data-packages"""
        return self._request(
            "POST",
            f"{PREFIX}/vendor-data-packages",
            payload=payload,
            headers=dict(headers),
        )

    def get_vendor_data_package(
        self, package_id: str, headers: Headers
    ) -> requests.Response:
        """GET /compliance/vendor-data-packages/{id}"""
        return self._request(
            "GET",
            f"{PREFIX}/vendor-data-packages/{package_id}",
            headers=dict(headers),
        )

    def list_vendor_data_packages(
        self, headers: Headers, params: JsonDict | None = None
    ) -> requests.Response:
        """GET /compliance/vendor-data-packages"""
        return self._request(
            "GET",
            f"{PREFIX}/vendor-data-packages",
            headers=dict(headers),
            params=params,
        )

    def deliver_package(
        self, package_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/vendor-data-packages/{id}/deliver"""
        return self._request(
            "POST",
            f"{PREFIX}/vendor-data-packages/{package_id}/deliver",
            payload=payload,
            headers=dict(headers),
        )

    def validate_package(
        self, package_id: str, headers: Headers, payload: JsonDict | None = None
    ) -> requests.Response:
        """POST /compliance/vendor-data-packages/{id}/validate"""
        return self._request(
            "POST",
            f"{PREFIX}/vendor-data-packages/{package_id}/validate",
            payload=payload if payload is not None else {},
            headers=dict(headers),
        )

    def reject_package(
        self, package_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/vendor-data-packages/{id}/reject"""
        return self._request(
            "POST",
            f"{PREFIX}/vendor-data-packages/{package_id}/reject",
            payload=payload,
            headers=dict(headers),
        )

    def resubmit_package(
        self, package_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/vendor-data-packages/{id}/resubmit"""
        return self._request(
            "POST",
            f"{PREFIX}/vendor-data-packages/{package_id}/resubmit",
            payload=payload,
            headers=dict(headers),
        )

    # ------------------------------------------------------------------
    # Attestations
    # ------------------------------------------------------------------

    def create_attestation(
        self, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/attestations"""
        return self._request(
            "POST", f"{PREFIX}/attestations", payload=payload, headers=dict(headers)
        )

    def get_attestation(
        self, attestation_id: str, headers: Headers
    ) -> requests.Response:
        """GET /compliance/attestations/{id}"""
        return self._request(
            "GET", f"{PREFIX}/attestations/{attestation_id}", headers=dict(headers)
        )

    def list_attestations(
        self, headers: Headers, params: JsonDict | None = None
    ) -> requests.Response:
        """GET /compliance/attestations"""
        return self._request(
            "GET", f"{PREFIX}/attestations", headers=dict(headers), params=params
        )

    def submit_attestation(
        self, attestation_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/attestations/{id}/submit"""
        return self._request(
            "POST",
            f"{PREFIX}/attestations/{attestation_id}/submit",
            payload=payload,
            headers=dict(headers),
        )

    def accept_attestation(
        self, attestation_id: str, headers: Headers, payload: JsonDict | None = None
    ) -> requests.Response:
        """POST /compliance/attestations/{id}/accept"""
        return self._request(
            "POST",
            f"{PREFIX}/attestations/{attestation_id}/accept",
            payload=payload if payload is not None else {},
            headers=dict(headers),
        )

    def reject_attestation(
        self, attestation_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/attestations/{id}/reject"""
        return self._request(
            "POST",
            f"{PREFIX}/attestations/{attestation_id}/reject",
            payload=payload,
            headers=dict(headers),
        )

    def revise_attestation(
        self, attestation_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/attestations/{id}/revise"""
        return self._request(
            "POST",
            f"{PREFIX}/attestations/{attestation_id}/revise",
            payload=payload,
            headers=dict(headers),
        )

    # ------------------------------------------------------------------
    # Penalty ledger
    # ------------------------------------------------------------------

    def get_ledger_entry(self, entry_id: str, headers: Headers) -> requests.Response:
        """GET /compliance/penalty-ledger-entries/{id}"""
        return self._request(
            "GET",
            f"{PREFIX}/penalty-ledger-entries/{entry_id}",
            headers=dict(headers),
        )

    def list_ledger_entries(
        self, headers: Headers, params: JsonDict | None = None
    ) -> requests.Response:
        """GET /compliance/penalty-ledger-entries"""
        return self._request(
            "GET",
            f"{PREFIX}/penalty-ledger-entries",
            headers=dict(headers),
            params=params,
        )

    def reverse_ledger_entry(
        self, entry_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/penalty-ledger-entries/{id}/reverse"""
        return self._request(
            "POST",
            f"{PREFIX}/penalty-ledger-entries/{entry_id}/reverse",
            payload=payload,
            headers=dict(headers),
        )

    # ------------------------------------------------------------------
    # Remediation plans
    # ------------------------------------------------------------------

    def create_remediation_plan(
        self, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/remediation-plans"""
        return self._request(
            "POST",
            f"{PREFIX}/remediation-plans",
            payload=payload,
            headers=dict(headers),
        )

    def get_remediation_plan(
        self, plan_id: str, headers: Headers
    ) -> requests.Response:
        """GET /compliance/remediation-plans/{id}"""
        return self._request(
            "GET", f"{PREFIX}/remediation-plans/{plan_id}", headers=dict(headers)
        )

    def list_remediation_plans(
        self, headers: Headers, params: JsonDict | None = None
    ) -> requests.Response:
        """GET /compliance/remediation-plans"""
        return self._request(
            "GET", f"{PREFIX}/remediation-plans", headers=dict(headers), params=params
        )

    def record_milestone_completion(
        self, plan_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        """POST /compliance/remediation-plans/{id}/milestone-completions"""
        return self._request(
            "POST",
            f"{PREFIX}/remediation-plans/{plan_id}/milestone-completions",
            payload=payload,
            headers=dict(headers),
        )

    def complete_remediation_plan(
        self, plan_id: str, headers: Headers, payload: JsonDict | None = None
    ) -> requests.Response:
        """POST /compliance/remediation-plans/{id}/complete"""
        return self._request(
            "POST",
            f"{PREFIX}/remediation-plans/{plan_id}/complete",
            payload=payload if payload is not None else {},
            headers=dict(headers),
        )
