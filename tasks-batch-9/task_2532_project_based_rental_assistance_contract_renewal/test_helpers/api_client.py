"""Typed API client: one method per endpoint of the contract-renewal API."""
from __future__ import annotations

from typing import Any, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/pbra"


def _query(**kwargs: Any) -> Optional[dict[str, Any]]:
    """Drop unset query parameters so an omitted parameter really is omitted."""
    params = {k: v for k, v in kwargs.items() if v is not None}
    return params or None


class ApiClient(GenericApiClient):
    """One method per published endpoint. Every method returns the raw response."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers=None) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Owners
    # ------------------------------------------------------------------
    def create_owner(self, payload: dict, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/owners", payload, headers)

    def get_owner(self, owner_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/owners/{owner_id}", None, headers)

    def list_owner_properties(
        self, owner_id: str, headers=None, limit=None, offset=None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/owners/{owner_id}/properties",
            None,
            headers,
            _query(limit=limit, offset=offset),
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    def create_property(self, payload: dict, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/properties", payload, headers)

    def get_property(self, property_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/properties/{property_id}", None, headers)

    def list_property_hap_contracts(
        self, property_id: str, headers=None, limit=None, offset=None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/properties/{property_id}/hap-contracts",
            None,
            headers,
            _query(limit=limit, offset=offset),
        )

    def list_property_tenant_households(
        self, property_id: str, headers=None, status=None, limit=None, offset=None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/properties/{property_id}/tenant-households",
            None,
            headers,
            _query(status=status, limit=limit, offset=offset),
        )

    def list_property_utility_allowance_analyses(
        self, property_id: str, headers=None, state=None, limit=None, offset=None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/properties/{property_id}/utility-allowance-analyses",
            None,
            headers,
            _query(state=state, limit=limit, offset=offset),
        )

    # ------------------------------------------------------------------
    # HAP contracts
    # ------------------------------------------------------------------
    def create_hap_contract(self, payload: dict, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/hap-contracts", payload, headers)

    def get_hap_contract(self, contract_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/hap-contracts/{contract_id}", None, headers)

    def list_contract_renewal_cases(
        self, contract_id: str, headers=None, limit=None, offset=None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/hap-contracts/{contract_id}/renewal-cases",
            None,
            headers,
            _query(limit=limit, offset=offset),
        )

    def list_contract_voucher_submissions(
        self, contract_id: str, headers=None, state=None, limit=None, offset=None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/hap-contracts/{contract_id}/voucher-submissions",
            None,
            headers,
            _query(state=state, limit=limit, offset=offset),
        )

    def list_contract_special_claims(
        self, contract_id: str, headers=None, state=None, limit=None, offset=None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/hap-contracts/{contract_id}/special-claims",
            None,
            headers,
            _query(state=state, limit=limit, offset=offset),
        )

    def get_contract_reconciliation(
        self, contract_id: str, headers=None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/hap-contracts/{contract_id}/reconciliation", None, headers
        )

    # ------------------------------------------------------------------
    # Renewal cases
    # ------------------------------------------------------------------
    def create_renewal_case(self, payload: dict, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/renewal-cases", payload, headers)

    def get_renewal_case(self, case_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/renewal-cases/{case_id}", None, headers)

    def select_option(self, case_id: str, payload: dict, headers=None) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/renewal-cases/{case_id}/select-option", payload, headers
        )

    def elect_adjustment(
        self, case_id: str, payload: dict, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/renewal-cases/{case_id}/elect-adjustment", payload, headers
        )

    def approve_rents(self, case_id: str, headers=None, payload=None) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/renewal-cases/{case_id}/approve-rents", payload or {}, headers
        )

    def execute_renewal(
        self, case_id: str, payload: dict, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/renewal-cases/{case_id}/execute-renewal", payload, headers
        )

    def record_opt_out(
        self, case_id: str, headers=None, payload=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/renewal-cases/{case_id}/record-opt-out", payload or {}, headers
        )

    def finalize_opt_out(
        self, case_id: str, headers=None, payload=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/renewal-cases/{case_id}/finalize-opt-out",
            payload or {},
            headers,
        )

    def list_case_studies(
        self, case_id: str, headers=None, limit=None, offset=None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/renewal-cases/{case_id}/rent-comparability-studies",
            None,
            headers,
            _query(limit=limit, offset=offset),
        )

    def list_case_tenant_notices(
        self, case_id: str, headers=None, notice_type=None, status=None, limit=None, offset=None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/renewal-cases/{case_id}/tenant-notices",
            None,
            headers,
            _query(notice_type=notice_type, status=status, limit=limit, offset=offset),
        )

    def list_case_restructuring_determinations(
        self, case_id: str, headers=None, limit=None, offset=None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/renewal-cases/{case_id}/restructuring-determinations",
            None,
            headers,
            _query(limit=limit, offset=offset),
        )

    def list_case_enhanced_vouchers(
        self, case_id: str, headers=None, state=None, limit=None, offset=None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/renewal-cases/{case_id}/enhanced-vouchers",
            None,
            headers,
            _query(state=state, limit=limit, offset=offset),
        )

    # ------------------------------------------------------------------
    # Rent comparability studies and comparables
    # ------------------------------------------------------------------
    def create_study(self, payload: dict, headers=None) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/rent-comparability-studies", payload, headers
        )

    def get_study(self, study_id: str, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/rent-comparability-studies/{study_id}", None, headers
        )

    def list_studies(
        self,
        headers=None,
        renewal_case_id=None,
        supersedes_study_id=None,
        state=None,
        limit=None,
        offset=None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/rent-comparability-studies",
            None,
            headers,
            _query(
                renewal_case_id=renewal_case_id,
                supersedes_study_id=supersedes_study_id,
                state=state,
                limit=limit,
                offset=offset,
            ),
        )

    def create_comparable(self, payload: dict, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/comparables", payload, headers)

    def list_study_comparables(
        self, study_id: str, headers=None, status=None, limit=None, offset=None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/rent-comparability-studies/{study_id}/comparables",
            None,
            headers,
            _query(status=status, limit=limit, offset=offset),
        )

    def submit_study(self, study_id: str, headers=None, payload=None) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/rent-comparability-studies/{study_id}/submit",
            payload or {},
            headers,
        )

    def challenge_study(
        self, study_id: str, payload: dict, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/rent-comparability-studies/{study_id}/challenge",
            payload,
            headers,
        )

    def decide_study(self, study_id: str, payload: dict, headers=None) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/rent-comparability-studies/{study_id}/decide",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Utility allowance analyses
    # ------------------------------------------------------------------
    def create_utility_allowance_analysis(
        self, payload: dict, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/utility-allowance-analyses", payload, headers
        )

    def get_utility_allowance_analysis(
        self, analysis_id: str, headers=None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/utility-allowance-analyses/{analysis_id}", None, headers
        )

    def submit_utility_allowance_analysis(
        self, analysis_id: str, headers=None, payload=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/utility-allowance-analyses/{analysis_id}/submit",
            payload or {},
            headers,
        )

    def decide_utility_allowance_analysis(
        self, analysis_id: str, payload: dict, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/utility-allowance-analyses/{analysis_id}/decide",
            payload,
            headers,
        )

    def apply_utility_allowance_analysis(
        self, analysis_id: str, payload: dict, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/utility-allowance-analyses/{analysis_id}/apply",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Tenant households and certifications
    # ------------------------------------------------------------------
    def create_tenant_household(self, payload: dict, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/tenant-households", payload, headers)

    def get_tenant_household(self, tenant_id: str, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/tenant-households/{tenant_id}", None, headers
        )

    def move_out_tenant_household(
        self, tenant_id: str, payload: dict, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/tenant-households/{tenant_id}/move-out", payload, headers
        )

    def create_tenant_certification(self, payload: dict, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/tenant-certifications", payload, headers)

    def get_tenant_certification(
        self, certification_id: str, headers=None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/tenant-certifications/{certification_id}", None, headers
        )

    def list_household_certifications(
        self,
        tenant_id: str,
        headers=None,
        status=None,
        cert_type=None,
        limit=None,
        offset=None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/tenant-households/{tenant_id}/certifications",
            None,
            headers,
            _query(status=status, cert_type=cert_type, limit=limit, offset=offset),
        )

    def list_household_notices(
        self, tenant_id: str, headers=None, status=None, limit=None, offset=None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/tenant-households/{tenant_id}/notices",
            None,
            headers,
            _query(status=status, limit=limit, offset=offset),
        )

    def list_household_enhanced_vouchers(
        self, tenant_id: str, headers=None, state=None, limit=None, offset=None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/tenant-households/{tenant_id}/enhanced-vouchers",
            None,
            headers,
            _query(state=state, limit=limit, offset=offset),
        )

    # ------------------------------------------------------------------
    # Tenant notices
    # ------------------------------------------------------------------
    def create_tenant_notice(self, payload: dict, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/tenant-notices", payload, headers)

    def get_tenant_notice(self, notice_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/tenant-notices/{notice_id}", None, headers)

    def rescind_tenant_notice(
        self, notice_id: str, payload: dict, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/tenant-notices/{notice_id}/rescind", payload, headers
        )

    # ------------------------------------------------------------------
    # Restructuring determinations
    # ------------------------------------------------------------------
    def create_restructuring_determination(
        self, payload: dict, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/restructuring-determinations", payload, headers
        )

    def evaluate_restructuring_determination(
        self, determination_id: str, headers=None, payload=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/restructuring-determinations/{determination_id}/evaluate",
            payload or {},
            headers,
        )

    def approve_restructuring_determination(
        self, determination_id: str, headers=None, payload=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/restructuring-determinations/{determination_id}/approve",
            payload or {},
            headers,
        )

    def get_restructuring_determination(
        self, determination_id: str, headers=None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/restructuring-determinations/{determination_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Enhanced vouchers
    # ------------------------------------------------------------------
    def get_enhanced_voucher(self, voucher_id: str, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/enhanced-vouchers/{voucher_id}", None, headers
        )

    def issue_enhanced_voucher(
        self, voucher_id: str, headers=None, payload=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/enhanced-vouchers/{voucher_id}/issue",
            payload or {},
            headers,
        )

    def rescind_enhanced_voucher(
        self, voucher_id: str, payload: dict, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/enhanced-vouchers/{voucher_id}/rescind", payload, headers
        )

    # ------------------------------------------------------------------
    # Voucher submissions
    # ------------------------------------------------------------------
    def create_voucher_submission(self, payload: dict, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/voucher-submissions", payload, headers)

    def get_voucher_submission(self, voucher_id: str, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/voucher-submissions/{voucher_id}", None, headers
        )

    def submit_voucher_submission(
        self, voucher_id: str, headers=None, payload=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/voucher-submissions/{voucher_id}/submit",
            payload or {},
            headers,
        )

    def pay_voucher_submission(
        self, voucher_id: str, headers=None, payload=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/voucher-submissions/{voucher_id}/pay", payload or {}, headers
        )

    def reverse_voucher_submission(
        self, voucher_id: str, payload: dict, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/voucher-submissions/{voucher_id}/reverse", payload, headers
        )

    # ------------------------------------------------------------------
    # Special claims
    # ------------------------------------------------------------------
    def create_special_claim(self, payload: dict, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/special-claims", payload, headers)

    def get_special_claim(self, claim_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/special-claims/{claim_id}", None, headers)

    def submit_special_claim(
        self, claim_id: str, headers=None, payload=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/special-claims/{claim_id}/submit", payload or {}, headers
        )

    def decide_special_claim(
        self, claim_id: str, payload: dict, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/special-claims/{claim_id}/decide", payload, headers
        )

    def pay_special_claim(
        self, claim_id: str, headers=None, payload=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/special-claims/{claim_id}/pay", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Raw escape hatch, for authentication and pagination probes
    # ------------------------------------------------------------------
    def raw(
        self, method: str, path: str, payload=None, headers=None, params=None
    ) -> requests.Response:
        return self._request(method, path, payload, headers, params)


api_client = ApiClient()
