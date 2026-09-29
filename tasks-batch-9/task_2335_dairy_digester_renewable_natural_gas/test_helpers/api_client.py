"""API client: one method per endpoint defined in the PRD (§4)."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

Headers = Dict[str, str]
Payload = Optional[Dict[str, Any]]
Params = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """Thin, explicit wrapper around every path the PRD declares."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload: Payload, headers: Headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def set_clock_to(self, to_iso8601: str, headers: Headers):
        return self.set_clock({"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Dairies
    # ------------------------------------------------------------------
    def create_dairy(self, payload: Payload, headers: Headers):
        return self._request("POST", "/dairies", payload, headers)

    def list_dairies(self, headers: Headers, params: Params = None):
        return self._request("GET", "/dairies", headers=headers, params=params)

    def get_dairy(self, dairy_id: str, headers: Headers):
        return self._request("GET", f"/dairies/{dairy_id}", headers=headers)

    # ------------------------------------------------------------------
    # Digester facilities
    # ------------------------------------------------------------------
    def create_facility(self, payload: Payload, headers: Headers):
        return self._request("POST", "/facilities", payload, headers)

    def list_facilities(self, headers: Headers, params: Params = None):
        return self._request("GET", "/facilities", headers=headers, params=params)

    def get_facility(self, facility_id: str, headers: Headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def fund_reserve(self, facility_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/facilities/{facility_id}/reserve-funding", payload, headers
        )

    def override_posture(self, facility_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/facilities/{facility_id}/posture-override", payload, headers
        )

    def get_financial_summary(self, facility_id: str, headers: Headers):
        return self._request(
            "GET", f"/facilities/{facility_id}/financial-summary", headers=headers
        )

    # ------------------------------------------------------------------
    # Feedstock agreements
    # ------------------------------------------------------------------
    def create_agreement(self, payload: Payload, headers: Headers):
        return self._request("POST", "/feedstock-agreements", payload, headers)

    def list_agreements(self, headers: Headers, params: Params = None):
        return self._request("GET", "/feedstock-agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id: str, headers: Headers):
        return self._request("GET", f"/feedstock-agreements/{agreement_id}", headers=headers)

    def offer_agreement(self, agreement_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/feedstock-agreements/{agreement_id}/offer", payload, headers
        )

    def counter_agreement(self, agreement_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/feedstock-agreements/{agreement_id}/counter", payload, headers
        )

    def revise_agreement(self, agreement_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/feedstock-agreements/{agreement_id}/revise", payload, headers
        )

    def sign_agreement(self, agreement_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/feedstock-agreements/{agreement_id}/sign", payload, headers
        )

    def change_agreement_status(self, agreement_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/feedstock-agreements/{agreement_id}/status-change", payload, headers
        )

    # ------------------------------------------------------------------
    # Feedstock deliveries
    # ------------------------------------------------------------------
    def create_delivery(self, payload: Payload, headers: Headers):
        return self._request("POST", "/feedstock-deliveries", payload, headers)

    def list_deliveries(self, headers: Headers, params: Params = None):
        return self._request("GET", "/feedstock-deliveries", headers=headers, params=params)

    def get_delivery(self, delivery_id: str, headers: Headers):
        return self._request("GET", f"/feedstock-deliveries/{delivery_id}", headers=headers)

    def reject_delivery(self, delivery_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/feedstock-deliveries/{delivery_id}/reject", payload, headers
        )

    # ------------------------------------------------------------------
    # Operations days
    # ------------------------------------------------------------------
    def create_ops_day(self, payload: Payload, headers: Headers):
        return self._request("POST", "/ops-days", payload, headers)

    def list_ops_days(self, headers: Headers, params: Params = None):
        return self._request("GET", "/ops-days", headers=headers, params=params)

    def get_ops_day(self, ops_day_id: str, headers: Headers):
        return self._request("GET", f"/ops-days/{ops_day_id}", headers=headers)

    def close_ops_day(self, ops_day_id: str, payload: Payload, headers: Headers):
        return self._request("POST", f"/ops-days/{ops_day_id}/close", payload, headers)

    def reopen_ops_day(self, ops_day_id: str, payload: Payload, headers: Headers):
        return self._request("POST", f"/ops-days/{ops_day_id}/reopen", payload, headers)

    def condition_gas(self, ops_day_id: str, payload: Payload, headers: Headers):
        return self._request("POST", f"/ops-days/{ops_day_id}/condition-gas", payload, headers)

    def record_separation(self, ops_day_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/ops-days/{ops_day_id}/record-separation", payload, headers
        )

    # ------------------------------------------------------------------
    # Interconnect agreements
    # ------------------------------------------------------------------
    def create_interconnect(self, payload: Payload, headers: Headers):
        return self._request("POST", "/interconnect-agreements", payload, headers)

    def list_interconnects(self, headers: Headers, params: Params = None):
        return self._request(
            "GET", "/interconnect-agreements", headers=headers, params=params
        )

    def get_interconnect(self, interconnect_id: str, headers: Headers):
        return self._request(
            "GET", f"/interconnect-agreements/{interconnect_id}", headers=headers
        )

    def change_interconnect_status(
        self, interconnect_id: str, payload: Payload, headers: Headers
    ):
        return self._request(
            "POST",
            f"/interconnect-agreements/{interconnect_id}/status-change",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Injection nominations
    # ------------------------------------------------------------------
    def create_nomination(self, payload: Payload, headers: Headers):
        return self._request("POST", "/injection-nominations", payload, headers)

    def list_nominations(self, headers: Headers, params: Params = None):
        return self._request("GET", "/injection-nominations", headers=headers, params=params)

    def get_nomination(self, nomination_id: str, headers: Headers):
        return self._request("GET", f"/injection-nominations/{nomination_id}", headers=headers)

    def schedule_decision(self, nomination_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/injection-nominations/{nomination_id}/schedule-decision", payload, headers
        )

    def deliver_nomination(self, nomination_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/injection-nominations/{nomination_id}/deliver", payload, headers
        )

    # ------------------------------------------------------------------
    # Credit pathways
    # ------------------------------------------------------------------
    def create_pathway(self, payload: Payload, headers: Headers):
        return self._request("POST", "/credit-pathways", payload, headers)

    def list_pathways(self, headers: Headers, params: Params = None):
        return self._request("GET", "/credit-pathways", headers=headers, params=params)

    def get_pathway(self, pathway_id: str, headers: Headers):
        return self._request("GET", f"/credit-pathways/{pathway_id}", headers=headers)

    def certification_decision(self, pathway_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/credit-pathways/{pathway_id}/certification-decision", payload, headers
        )

    def get_credit_ledger(self, pathway_id: str, headers: Headers):
        return self._request(
            "GET", f"/credit-pathways/{pathway_id}/credit-ledger", headers=headers
        )

    # ------------------------------------------------------------------
    # Credit batches
    # ------------------------------------------------------------------
    def create_batch(self, payload: Payload, headers: Headers):
        return self._request("POST", "/credit-batches", payload, headers)

    def list_batches(self, headers: Headers, params: Params = None):
        return self._request("GET", "/credit-batches", headers=headers, params=params)

    def get_batch(self, batch_id: str, headers: Headers):
        return self._request("GET", f"/credit-batches/{batch_id}", headers=headers)

    def claim_batch(self, batch_id: str, payload: Payload, headers: Headers):
        return self._request("POST", f"/credit-batches/{batch_id}/claim", payload, headers)

    def verify_batch(self, batch_id: str, payload: Payload, headers: Headers):
        return self._request("POST", f"/credit-batches/{batch_id}/verify", payload, headers)

    def issue_batch(self, batch_id: str, payload: Payload, headers: Headers):
        return self._request("POST", f"/credit-batches/{batch_id}/issue", payload, headers)

    def reverse_batch(self, batch_id: str, payload: Payload, headers: Headers):
        return self._request("POST", f"/credit-batches/{batch_id}/reverse", payload, headers)

    # ------------------------------------------------------------------
    # Verification audits
    # ------------------------------------------------------------------
    def create_audit(self, payload: Payload, headers: Headers):
        return self._request("POST", "/verification-audits", payload, headers)

    def list_audits(self, headers: Headers, params: Params = None):
        return self._request("GET", "/verification-audits", headers=headers, params=params)

    def get_audit(self, audit_id: str, headers: Headers):
        return self._request("GET", f"/verification-audits/{audit_id}", headers=headers)

    def record_fieldwork(self, audit_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/verification-audits/{audit_id}/fieldwork", payload, headers
        )

    def issue_findings(self, audit_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/verification-audits/{audit_id}/findings", payload, headers
        )

    def open_remediation(self, audit_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/verification-audits/{audit_id}/remediation", payload, headers
        )

    def close_audit(self, audit_id: str, payload: Payload, headers: Headers):
        return self._request("POST", f"/verification-audits/{audit_id}/close", payload, headers)

    # ------------------------------------------------------------------
    # Nutrient applications
    # ------------------------------------------------------------------
    def create_nutrient_application(self, payload: Payload, headers: Headers):
        return self._request("POST", "/nutrient-applications", payload, headers)

    def list_nutrient_applications(self, headers: Headers, params: Params = None):
        return self._request("GET", "/nutrient-applications", headers=headers, params=params)

    def get_nutrient_application(self, application_id: str, headers: Headers):
        return self._request(
            "GET", f"/nutrient-applications/{application_id}", headers=headers
        )

    def apply_nutrient_application(self, application_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/nutrient-applications/{application_id}/apply", payload, headers
        )

    def void_nutrient_application(self, application_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/nutrient-applications/{application_id}/void", payload, headers
        )

    # ------------------------------------------------------------------
    # Revenue statements
    # ------------------------------------------------------------------
    def create_statement(self, payload: Payload, headers: Headers):
        return self._request("POST", "/revenue-statements", payload, headers)

    def list_statements(self, headers: Headers, params: Params = None):
        return self._request("GET", "/revenue-statements", headers=headers, params=params)

    def get_statement(self, statement_id: str, headers: Headers):
        return self._request("GET", f"/revenue-statements/{statement_id}", headers=headers)

    def approve_statement(self, statement_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/revenue-statements/{statement_id}/approve", payload, headers
        )

    def pay_statement(self, statement_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/revenue-statements/{statement_id}/pay", payload, headers
        )

    def claw_back_statement(self, statement_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/revenue-statements/{statement_id}/claw-back", payload, headers
        )


api_client = ApiClient()
