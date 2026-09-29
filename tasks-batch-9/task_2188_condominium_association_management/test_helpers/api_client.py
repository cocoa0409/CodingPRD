"""One method per endpoint of the condominium association management API.

Every method returns the raw ``requests.Response`` so that tests can assert on
status codes as well as bodies.  Header dicts are always supplied explicitly by
the caller, because most write endpoints are gated on both the actor's role and
the actor's identity.
"""

from __future__ import annotations

from typing import Any

import requests
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed facade over the association API surface."""

    def patch(self, path: str, json: Any = None, headers: dict[str, str] | None = None):
        return self._request("PATCH", path, payload=json, headers=headers)

    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: dict[str, str]) -> requests.Response:
        return self.post(
            "/_clock/set_current_utc", json={"current_utc": current_utc}, headers=headers
        )

    # ------------------------------------------------------------------
    # Association
    # ------------------------------------------------------------------
    def create_association(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.post("/associations", json=payload, headers=headers)

    def get_association(
        self, association_id: str, headers: dict[str, str]
    ) -> requests.Response:
        return self.get(f"/associations/{association_id}", headers=headers)

    def update_association(
        self, association_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.patch(f"/associations/{association_id}", json=payload, headers=headers)

    def get_reserve_adequacy(
        self,
        association_id: str,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self.get(
            f"/associations/{association_id}/reserve-adequacy",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Owners
    # ------------------------------------------------------------------
    def create_owner(
        self, association_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"/associations/{association_id}/owners", json=payload, headers=headers
        )

    def list_owners(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self.get("/owners", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Units
    # ------------------------------------------------------------------
    def create_unit(
        self, association_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"/associations/{association_id}/units", json=payload, headers=headers
        )

    def list_units(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self.get("/units", headers=headers, params=params)

    def get_unit(self, unit_id: str, headers: dict[str, str]) -> requests.Response:
        return self.get(f"/units/{unit_id}", headers=headers)

    def get_unit_statement(
        self, unit_id: str, headers: dict[str, str]
    ) -> requests.Response:
        return self.get(f"/units/{unit_id}/statement", headers=headers)

    def create_payment(
        self, unit_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.post(f"/units/{unit_id}/payments", json=payload, headers=headers)

    def create_charge(
        self, unit_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.post(f"/units/{unit_id}/charges", json=payload, headers=headers)

    def transfer_ownership(
        self, unit_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"/units/{unit_id}/transfer-ownership", json=payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Ledger entries
    # ------------------------------------------------------------------
    def reverse_ledger_entry(
        self,
        ledger_entry_id: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self.post(
            f"/ledger-entries/{ledger_entry_id}/reverse",
            json=payload or {},
            headers=headers,
        )

    def list_ledger_entries(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self.get("/ledger-entries", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Budgets
    # ------------------------------------------------------------------
    def create_budget(
        self, association_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"/associations/{association_id}/budgets", json=payload, headers=headers
        )

    def list_budgets(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self.get("/budgets", headers=headers, params=params)

    def propose_budget(
        self, budget_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ) -> requests.Response:
        return self.post(
            f"/budgets/{budget_id}/propose", json=payload or {}, headers=headers
        )

    def send_budget_notice(
        self, budget_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ) -> requests.Response:
        return self.post(
            f"/budgets/{budget_id}/send-notice", json=payload or {}, headers=headers
        )

    def return_budget_to_draft(
        self, budget_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ) -> requests.Response:
        return self.post(
            f"/budgets/{budget_id}/return-to-draft", json=payload or {}, headers=headers
        )

    def ratify_budget(
        self, budget_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ) -> requests.Response:
        return self.post(
            f"/budgets/{budget_id}/ratify", json=payload or {}, headers=headers
        )

    # ------------------------------------------------------------------
    # Billing runs
    # ------------------------------------------------------------------
    def create_billing_run(
        self, association_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"/associations/{association_id}/billing-runs", json=payload, headers=headers
        )

    def list_billing_runs(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self.get("/billing-runs", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Special assessments
    # ------------------------------------------------------------------
    def create_special_assessment(
        self, association_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"/associations/{association_id}/special-assessments",
            json=payload,
            headers=headers,
        )

    def list_special_assessments(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self.get("/special-assessments", headers=headers, params=params)

    def open_ballot(
        self,
        special_assessment_id: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self.post(
            f"/special-assessments/{special_assessment_id}/open-ballot",
            json=payload or {},
            headers=headers,
        )

    def close_ballot(
        self,
        special_assessment_id: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self.post(
            f"/special-assessments/{special_assessment_id}/close-ballot",
            json=payload or {},
            headers=headers,
        )

    def post_installment(
        self,
        special_assessment_id: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> requests.Response:
        return self.post(
            f"/special-assessments/{special_assessment_id}/installments",
            json=payload,
            headers=headers,
        )

    def rescind_special_assessment(
        self,
        special_assessment_id: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self.post(
            f"/special-assessments/{special_assessment_id}/rescind",
            json=payload or {},
            headers=headers,
        )

    def refund_special_assessment(
        self, special_assessment_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"/special-assessments/{special_assessment_id}/refund",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Votes
    # ------------------------------------------------------------------
    def cast_vote(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.post("/votes", json=payload, headers=headers)

    def list_votes(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self.get("/votes", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Board meetings
    # ------------------------------------------------------------------
    def create_board_meeting(
        self, association_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"/associations/{association_id}/board-meetings", json=payload, headers=headers
        )

    def list_board_meetings(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self.get("/board-meetings", headers=headers, params=params)

    def send_meeting_notice(
        self,
        board_meeting_id: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self.post(
            f"/board-meetings/{board_meeting_id}/send-notice",
            json=payload or {},
            headers=headers,
        )

    def convene_meeting(
        self, board_meeting_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"/board-meetings/{board_meeting_id}/convene", json=payload, headers=headers
        )

    def adjourn_meeting(
        self,
        board_meeting_id: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self.post(
            f"/board-meetings/{board_meeting_id}/adjourn",
            json=payload or {},
            headers=headers,
        )

    def cancel_meeting(
        self,
        board_meeting_id: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self.post(
            f"/board-meetings/{board_meeting_id}/cancel",
            json=payload or {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Common elements
    # ------------------------------------------------------------------
    def create_common_element(
        self, association_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"/associations/{association_id}/common-elements", json=payload, headers=headers
        )

    def list_common_elements(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self.get("/common-elements", headers=headers, params=params)

    def update_common_element(
        self, common_element_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.patch(
            f"/common-elements/{common_element_id}", json=payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Vendor contracts
    # ------------------------------------------------------------------
    def create_vendor_contract(
        self, association_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"/associations/{association_id}/vendor-contracts",
            json=payload,
            headers=headers,
        )

    def list_vendor_contracts(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self.get("/vendor-contracts", headers=headers, params=params)

    def update_insurance_certificate(
        self, vendor_contract_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.patch(
            f"/vendor-contracts/{vendor_contract_id}/insurance-certificate",
            json=payload,
            headers=headers,
        )

    def submit_contract(
        self,
        vendor_contract_id: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self.post(
            f"/vendor-contracts/{vendor_contract_id}/submit",
            json=payload or {},
            headers=headers,
        )

    def approve_contract(
        self,
        vendor_contract_id: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self.post(
            f"/vendor-contracts/{vendor_contract_id}/approve",
            json=payload or {},
            headers=headers,
        )

    def activate_contract(
        self,
        vendor_contract_id: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self.post(
            f"/vendor-contracts/{vendor_contract_id}/activate",
            json=payload or {},
            headers=headers,
        )

    def suspend_contract(
        self, vendor_contract_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"/vendor-contracts/{vendor_contract_id}/suspend",
            json=payload,
            headers=headers,
        )

    def reinstate_contract(
        self,
        vendor_contract_id: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self.post(
            f"/vendor-contracts/{vendor_contract_id}/reinstate",
            json=payload or {},
            headers=headers,
        )

    def terminate_contract(
        self,
        vendor_contract_id: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self.post(
            f"/vendor-contracts/{vendor_contract_id}/terminate",
            json=payload or {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Work orders
    # ------------------------------------------------------------------
    def create_work_order(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.post("/work-orders", json=payload, headers=headers)

    def list_work_orders(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self.get("/work-orders", headers=headers, params=params)

    def start_work_order(
        self,
        work_order_id: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self.post(
            f"/work-orders/{work_order_id}/start", json=payload or {}, headers=headers
        )

    def hold_work_order(
        self, work_order_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"/work-orders/{work_order_id}/hold", json=payload, headers=headers
        )

    def complete_work_order(
        self,
        work_order_id: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self.post(
            f"/work-orders/{work_order_id}/complete", json=payload or {}, headers=headers
        )

    def invoice_work_order(
        self, work_order_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"/work-orders/{work_order_id}/invoice", json=payload, headers=headers
        )

    def cancel_work_order(
        self,
        work_order_id: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self.post(
            f"/work-orders/{work_order_id}/cancel", json=payload or {}, headers=headers
        )

    # ------------------------------------------------------------------
    # Insurance claims
    # ------------------------------------------------------------------
    def create_insurance_claim(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.post("/insurance-claims", json=payload, headers=headers)

    def list_insurance_claims(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self.get("/insurance-claims", headers=headers, params=params)

    def assign_adjuster(
        self,
        insurance_claim_id: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self.post(
            f"/insurance-claims/{insurance_claim_id}/assign-adjuster",
            json=payload or {},
            headers=headers,
        )

    def adjust_claim(
        self, insurance_claim_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"/insurance-claims/{insurance_claim_id}/adjust", json=payload, headers=headers
        )

    def appeal_claim(
        self,
        insurance_claim_id: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self.post(
            f"/insurance-claims/{insurance_claim_id}/appeal",
            json=payload or {},
            headers=headers,
        )

    def set_litigation_stage(
        self, insurance_claim_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"/insurance-claims/{insurance_claim_id}/litigation-stage",
            json=payload,
            headers=headers,
        )

    def settle_claim(
        self,
        insurance_claim_id: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self.post(
            f"/insurance-claims/{insurance_claim_id}/settle",
            json=payload or {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Violation cases
    # ------------------------------------------------------------------
    def create_violation_case(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.post("/violation-cases", json=payload, headers=headers)

    def list_violation_cases(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self.get("/violation-cases", headers=headers, params=params)

    def send_case_notice(
        self,
        violation_case_id: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self.post(
            f"/violation-cases/{violation_case_id}/send-notice",
            json=payload or {},
            headers=headers,
        )

    def mark_case_cured(
        self,
        violation_case_id: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self.post(
            f"/violation-cases/{violation_case_id}/mark-cured",
            json=payload or {},
            headers=headers,
        )

    def schedule_hearing(
        self, violation_case_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"/violation-cases/{violation_case_id}/schedule-hearing",
            json=payload,
            headers=headers,
        )

    def hearing_decision(
        self, violation_case_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"/violation-cases/{violation_case_id}/hearing-decision",
            json=payload,
            headers=headers,
        )

    def appeal_case(
        self,
        violation_case_id: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self.post(
            f"/violation-cases/{violation_case_id}/appeal",
            json=payload or {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Resale certificates
    # ------------------------------------------------------------------
    def request_resale_certificate(
        self, unit_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"/units/{unit_id}/resale-certificates", json=payload, headers=headers
        )

    def list_resale_certificates(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self.get("/resale-certificates", headers=headers, params=params)

    def issue_resale_certificate(
        self,
        resale_certificate_id: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self.post(
            f"/resale-certificates/{resale_certificate_id}/issue",
            json=payload or {},
            headers=headers,
        )

    def void_resale_certificate(
        self,
        resale_certificate_id: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self.post(
            f"/resale-certificates/{resale_certificate_id}/void",
            json=payload or {},
            headers=headers,
        )

    def get_lender_questionnaire(
        self, resale_certificate_id: str, headers: dict[str, str]
    ) -> requests.Response:
        return self.get(
            f"/resale-certificates/{resale_certificate_id}/lender-questionnaire",
            headers=headers,
        )


api_client = ApiClient()
