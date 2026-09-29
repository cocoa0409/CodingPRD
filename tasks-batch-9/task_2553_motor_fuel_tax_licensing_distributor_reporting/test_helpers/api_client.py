"""Typed HTTP client for every endpoint the PRD defines under `/mft`."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient, build_user_headers

from .constants import API_PREFIX, CLOCK_PATH
from .test_users import (
    ROLE_LICENSEE_AGENT,
    ROLE_LICENSING_OFFICER,
    ROLE_RETURNS_EXAMINER,
    ROLE_TAX_SUPERVISOR,
    ROLE_AUDIT_MANAGER,
    ROLE_FIELD_INSPECTOR,
    LICENSING_OFFICER_ID,
    RETURNS_EXAMINER_ID,
    TAX_SUPERVISOR_ID,
    AUDIT_MANAGER_ID,
    FIELD_INSPECTOR_ID,
)

Json = Dict[str, Any]


# --------------------------------------------------------------------------
# Identity threading
# --------------------------------------------------------------------------


def make_licensee_agent_headers(licensee_id: str) -> Dict[str, str]:
    """Headers for a `LicenseeAgent` acting for the licensee whose id is given."""
    return build_user_headers(licensee_id, ROLE_LICENSEE_AGENT)


def make_licensing_officer_headers(user_id: str = LICENSING_OFFICER_ID):
    return build_user_headers(user_id, ROLE_LICENSING_OFFICER)


def make_returns_examiner_headers(user_id: str = RETURNS_EXAMINER_ID):
    return build_user_headers(user_id, ROLE_RETURNS_EXAMINER)


def make_tax_supervisor_headers(user_id: str = TAX_SUPERVISOR_ID):
    return build_user_headers(user_id, ROLE_TAX_SUPERVISOR)


def make_audit_manager_headers(user_id: str = AUDIT_MANAGER_ID):
    return build_user_headers(user_id, ROLE_AUDIT_MANAGER)


def make_field_inspector_headers(user_id: str = FIELD_INSPECTOR_ID):
    return build_user_headers(user_id, ROLE_FIELD_INSPECTOR)


class ApiClient(GenericApiClient):
    """One method per PRD endpoint, so tests never spell out a path."""

    # ---------------- logical clock ----------------

    def set_clock(self, to_iso8601: str, headers: Json) -> Any:
        return self.post(CLOCK_PATH, {"to_iso8601": to_iso8601}, headers=headers)

    # ---------------- licensees ----------------

    def create_licensee(self, payload: Json, headers: Json) -> Any:
        return self.post(f"{API_PREFIX}/licensees", payload, headers=headers)

    def get_licensee(self, licensee_id: str, headers: Json) -> Any:
        return self.get(f"{API_PREFIX}/licensees/{licensee_id}", headers=headers)

    def list_licensees(self, headers: Json, params: Optional[Json] = None) -> Any:
        return self.get(f"{API_PREFIX}/licensees", headers=headers, params=params)

    def activate_licensee(self, licensee_id: str, headers: Json, payload: Optional[Json] = None):
        return self.post(
            f"{API_PREFIX}/licensees/{licensee_id}/activate", payload or {}, headers=headers
        )

    def suspend_licensee(self, licensee_id: str, reason: str, headers: Json) -> Any:
        return self.post(
            f"{API_PREFIX}/licensees/{licensee_id}/suspend", {"reason": reason}, headers=headers
        )

    def revoke_licensee(self, licensee_id: str, reason: str, headers: Json) -> Any:
        return self.post(
            f"{API_PREFIX}/licensees/{licensee_id}/revoke", {"reason": reason}, headers=headers
        )

    # ---------------- bonds ----------------

    def post_bond(self, licensee_id: str, payload: Json, headers: Json) -> Any:
        return self.post(f"{API_PREFIX}/licensees/{licensee_id}/bonds", payload, headers=headers)

    def list_bonds(self, licensee_id: str, headers: Json, params: Optional[Json] = None) -> Any:
        return self.get(
            f"{API_PREFIX}/licensees/{licensee_id}/bonds", headers=headers, params=params
        )

    def release_bond(self, bond_id: str, headers: Json, payload: Optional[Json] = None) -> Any:
        return self.post(f"{API_PREFIX}/bonds/{bond_id}/release", payload or {}, headers=headers)

    def get_bond_status(self, licensee_id: str, headers: Json) -> Any:
        return self.get(f"{API_PREFIX}/licensees/{licensee_id}/bond-status", headers=headers)

    # ---------------- ledger, payments, risk ----------------

    def list_ledger_entries(
        self, licensee_id: str, headers: Json, params: Optional[Json] = None
    ) -> Any:
        return self.get(
            f"{API_PREFIX}/licensees/{licensee_id}/ledger-entries", headers=headers, params=params
        )

    def create_payment(self, licensee_id: str, payload: Json, headers: Json) -> Any:
        return self.post(
            f"{API_PREFIX}/licensees/{licensee_id}/payments", payload, headers=headers
        )

    def get_risk_profile(self, licensee_id: str, headers: Json) -> Any:
        return self.get(f"{API_PREFIX}/licensees/{licensee_id}/risk-profile", headers=headers)

    # ---------------- terminals ----------------

    def create_terminal(self, payload: Json, headers: Json) -> Any:
        return self.post(f"{API_PREFIX}/terminals", payload, headers=headers)

    def get_terminal(self, terminal_id: str, headers: Json) -> Any:
        return self.get(f"{API_PREFIX}/terminals/{terminal_id}", headers=headers)

    def list_terminals(self, headers: Json, params: Optional[Json] = None) -> Any:
        return self.get(f"{API_PREFIX}/terminals", headers=headers, params=params)

    # ---------------- exemption certificates ----------------

    def create_certificate(self, payload: Json, headers: Json) -> Any:
        return self.post(f"{API_PREFIX}/exemption-certificates", payload, headers=headers)

    def get_certificate(self, certificate_id: str, headers: Json) -> Any:
        return self.get(
            f"{API_PREFIX}/exemption-certificates/{certificate_id}", headers=headers
        )

    def list_certificates(self, headers: Json, params: Optional[Json] = None) -> Any:
        return self.get(
            f"{API_PREFIX}/exemption-certificates", headers=headers, params=params
        )

    def revoke_certificate(self, certificate_id: str, reason: str, headers: Json) -> Any:
        return self.post(
            f"{API_PREFIX}/exemption-certificates/{certificate_id}/revoke",
            {"reason": reason},
            headers=headers,
        )

    # ---------------- rack removals ----------------

    def create_rack_removal(self, payload: Json, headers: Json) -> Any:
        return self.post(f"{API_PREFIX}/rack-removals", payload, headers=headers)

    def get_rack_removal(self, removal_id: str, headers: Json) -> Any:
        return self.get(f"{API_PREFIX}/rack-removals/{removal_id}", headers=headers)

    def list_rack_removals(self, headers: Json, params: Optional[Json] = None) -> Any:
        return self.get(f"{API_PREFIX}/rack-removals", headers=headers, params=params)

    # ---------------- returns, schedules, lines ----------------

    def create_return(self, payload: Json, headers: Json) -> Any:
        return self.post(f"{API_PREFIX}/returns", payload, headers=headers)

    def get_return(self, return_id: str, headers: Json) -> Any:
        return self.get(f"{API_PREFIX}/returns/{return_id}", headers=headers)

    def list_returns(self, headers: Json, params: Optional[Json] = None) -> Any:
        return self.get(f"{API_PREFIX}/returns", headers=headers, params=params)

    def create_schedule(self, return_id: str, payload: Json, headers: Json) -> Any:
        return self.post(f"{API_PREFIX}/returns/{return_id}/schedules", payload, headers=headers)

    def list_schedules(self, return_id: str, headers: Json, params: Optional[Json] = None) -> Any:
        return self.get(
            f"{API_PREFIX}/returns/{return_id}/schedules", headers=headers, params=params
        )

    def get_schedule(self, schedule_id: str, headers: Json) -> Any:
        return self.get(f"{API_PREFIX}/schedules/{schedule_id}", headers=headers)

    def create_line(self, schedule_id: str, payload: Json, headers: Json) -> Any:
        return self.post(f"{API_PREFIX}/schedules/{schedule_id}/lines", payload, headers=headers)

    def list_schedule_lines_of(
        self, schedule_id: str, headers: Json, params: Optional[Json] = None
    ) -> Any:
        return self.get(
            f"{API_PREFIX}/schedules/{schedule_id}/lines", headers=headers, params=params
        )

    def get_schedule_line(self, line_id: str, headers: Json) -> Any:
        return self.get(f"{API_PREFIX}/schedule-lines/{line_id}", headers=headers)

    def list_schedule_lines(self, headers: Json, params: Optional[Json] = None) -> Any:
        return self.get(f"{API_PREFIX}/schedule-lines", headers=headers, params=params)

    def file_return(self, return_id: str, attest_name: str, headers: Json) -> Any:
        return self.post(
            f"{API_PREFIX}/returns/{return_id}/file",
            {"attest_name": attest_name},
            headers=headers,
        )

    def create_amendment(self, return_id: str, payload: Json, headers: Json) -> Any:
        return self.post(
            f"{API_PREFIX}/returns/{return_id}/amendments", payload, headers=headers
        )

    # ---------------- cross-matching ----------------

    def create_cross_match_run(self, payload: Json, headers: Json) -> Any:
        return self.post(f"{API_PREFIX}/cross-match-runs", payload, headers=headers)

    def get_cross_match_run(self, run_id: str, headers: Json) -> Any:
        return self.get(f"{API_PREFIX}/cross-match-runs/{run_id}", headers=headers)

    def list_cross_match_runs(self, headers: Json, params: Optional[Json] = None) -> Any:
        return self.get(f"{API_PREFIX}/cross-match-runs", headers=headers, params=params)

    def get_discrepancy(self, discrepancy_id: str, headers: Json) -> Any:
        return self.get(f"{API_PREFIX}/discrepancies/{discrepancy_id}", headers=headers)

    def list_discrepancies(self, headers: Json, params: Optional[Json] = None) -> Any:
        return self.get(f"{API_PREFIX}/discrepancies", headers=headers, params=params)

    def send_inquiry(self, discrepancy_id: str, payload: Json, headers: Json) -> Any:
        return self.post(
            f"{API_PREFIX}/discrepancies/{discrepancy_id}/inquiries", payload, headers=headers
        )

    def post_response(self, discrepancy_id: str, payload: Json, headers: Json) -> Any:
        return self.post(
            f"{API_PREFIX}/discrepancies/{discrepancy_id}/responses", payload, headers=headers
        )

    def resolve_discrepancy(self, discrepancy_id: str, payload: Json, headers: Json) -> Any:
        return self.post(
            f"{API_PREFIX}/discrepancies/{discrepancy_id}/resolve", payload, headers=headers
        )

    # ---------------- refund claims ----------------

    def create_refund_claim(self, payload: Json, headers: Json) -> Any:
        return self.post(f"{API_PREFIX}/refund-claims", payload, headers=headers)

    def get_refund_claim(self, claim_id: str, headers: Json) -> Any:
        return self.get(f"{API_PREFIX}/refund-claims/{claim_id}", headers=headers)

    def list_refund_claims(self, headers: Json, params: Optional[Json] = None) -> Any:
        return self.get(f"{API_PREFIX}/refund-claims", headers=headers, params=params)

    def review_claim(self, claim_id: str, payload: Json, headers: Json) -> Any:
        return self.post(
            f"{API_PREFIX}/refund-claims/{claim_id}/review", payload, headers=headers
        )

    def decide_claim(self, claim_id: str, payload: Json, headers: Json) -> Any:
        return self.post(
            f"{API_PREFIX}/refund-claims/{claim_id}/decide", payload, headers=headers
        )

    def pay_claim(self, claim_id: str, payload: Json, headers: Json) -> Any:
        return self.post(f"{API_PREFIX}/refund-claims/{claim_id}/pay", payload, headers=headers)

    # ---------------- roadside inspections ----------------

    def create_inspection(self, payload: Json, headers: Json) -> Any:
        return self.post(f"{API_PREFIX}/roadside-inspections", payload, headers=headers)

    def get_inspection(self, inspection_id: str, headers: Json) -> Any:
        return self.get(f"{API_PREFIX}/roadside-inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers: Json, params: Optional[Json] = None) -> Any:
        return self.get(f"{API_PREFIX}/roadside-inspections", headers=headers, params=params)

    def dismiss_inspection(self, inspection_id: str, dismissal_reason: str, headers: Json) -> Any:
        return self.post(
            f"{API_PREFIX}/roadside-inspections/{inspection_id}/dismiss",
            {"dismissal_reason": dismissal_reason},
            headers=headers,
        )

    # ---------------- audit cases ----------------

    def create_audit_case(self, payload: Json, headers: Json) -> Any:
        return self.post(f"{API_PREFIX}/audit-cases", payload, headers=headers)

    def get_audit_case(self, case_id: str, headers: Json) -> Any:
        return self.get(f"{API_PREFIX}/audit-cases/{case_id}", headers=headers)

    def list_audit_cases(self, headers: Json, params: Optional[Json] = None) -> Any:
        return self.get(f"{API_PREFIX}/audit-cases", headers=headers, params=params)

    def advance_case(self, case_id: str, to_status: str, headers: Json) -> Any:
        return self.post(
            f"{API_PREFIX}/audit-cases/{case_id}/advance",
            {"to_status": to_status},
            headers=headers,
        )

    def issue_assessment(self, case_id: str, payload: Json, headers: Json) -> Any:
        return self.post(
            f"{API_PREFIX}/audit-cases/{case_id}/assessments", payload, headers=headers
        )

    def abate_assessment(self, case_id: str, abatement_reason: str, headers: Json) -> Any:
        return self.post(
            f"{API_PREFIX}/audit-cases/{case_id}/abate",
            {"abatement_reason": abatement_reason},
            headers=headers,
        )

    def protest_assessment(self, case_id: str, protest_grounds: str, headers: Json) -> Any:
        return self.post(
            f"{API_PREFIX}/audit-cases/{case_id}/protest",
            {"protest_grounds": protest_grounds},
            headers=headers,
        )

    def finalize_assessment(self, case_id: str, headers: Json, payload: Optional[Json] = None):
        return self.post(
            f"{API_PREFIX}/audit-cases/{case_id}/finalize", payload or {}, headers=headers
        )

    # ---------------- raw escape hatch ----------------

    def raw(
        self,
        method: str,
        path: str,
        payload: Optional[Json] = None,
        headers: Optional[Json] = None,
        params: Optional[Json] = None,
    ) -> Any:
        """Send a request exactly as given, for header and pagination probes."""
        return self._request(method, path, payload=payload, headers=headers, params=params)


#: Module-level client shared by the suite.
api_client = ApiClient()

__all__ = [
    "ApiClient",
    "api_client",
    "make_licensee_agent_headers",
    "make_licensing_officer_headers",
    "make_returns_examiner_headers",
    "make_tax_supervisor_headers",
    "make_audit_manager_headers",
    "make_field_inspector_headers",
]
