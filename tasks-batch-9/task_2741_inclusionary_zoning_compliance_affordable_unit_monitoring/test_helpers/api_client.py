"""Typed HTTP client: one method per declared endpoint."""

from typing import Any, Dict, List, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/iz-compliance"


def _compact(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is the sentinel ``...`` (i.e. never supplied)."""
    return {k: v for k, v in payload.items() if v is not ...}


class ApiClient(GenericApiClient):
    """Every declared endpoint of the inclusionary-zoning compliance service."""

    # ---- logical clock ------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Optional[dict] = None) -> requests.Response:
        return self.post("/_clock/set_current_utc", {"current_utc": current_utc}, headers=headers)

    def set_clock_raw(self, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self.post("/_clock/set_current_utc", payload, headers=headers)

    # ---- ordinances ---------------------------------------------------------
    def create_ordinance(self, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/ordinances", payload, headers=headers)

    def get_ordinance(self, ordinance_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self.get(f"{BASE}/ordinances/{ordinance_id}", headers=headers)

    def list_ordinances(
        self,
        status: Any = ...,
        limit: Any = ...,
        offset: Any = ...,
        headers: Optional[dict] = None,
    ) -> requests.Response:
        params = _compact({"status": status, "limit": limit, "offset": offset})
        return self.get(f"{BASE}/ordinances", headers=headers, params=params)

    # ---- AMI schedules ------------------------------------------------------
    def create_ami_schedule(self, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/ami-schedules", payload, headers=headers)

    def get_ami_schedule(self, ami_schedule_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self.get(f"{BASE}/ami-schedules/{ami_schedule_id}", headers=headers)

    def list_ami_schedules(
        self,
        status: Any = ...,
        limit: Any = ...,
        offset: Any = ...,
        headers: Optional[dict] = None,
    ) -> requests.Response:
        params = _compact({"status": status, "limit": limit, "offset": offset})
        return self.get(f"{BASE}/ami-schedules", headers=headers, params=params)

    # ---- projects -----------------------------------------------------------
    def create_project(self, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/projects", payload, headers=headers)

    def get_project(self, project_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self.get(f"{BASE}/projects/{project_id}", headers=headers)

    def list_projects(
        self,
        ordinance_id: Any = ...,
        state: Any = ...,
        applicability: Any = ...,
        compliance_posture: Any = ...,
        limit: Any = ...,
        offset: Any = ...,
        headers: Optional[dict] = None,
    ) -> requests.Response:
        params = _compact(
            {
                "ordinance_id": ordinance_id,
                "state": state,
                "applicability": applicability,
                "compliance_posture": compliance_posture,
                "limit": limit,
                "offset": offset,
            }
        )
        return self.get(f"{BASE}/projects", headers=headers, params=params)

    def patch_project(self, project_id: str, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self._request("PATCH", f"{BASE}/projects/{project_id}", payload, headers=headers)

    def screen_project(self, project_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/projects/{project_id}/screen", {}, headers=headers)

    def elect_path(self, project_id: str, compliance_path: str, headers: Optional[dict] = None) -> requests.Response:
        return self.post(
            f"{BASE}/projects/{project_id}/elect-path", {"compliance_path": compliance_path}, headers=headers
        )

    def elect_path_raw(self, project_id: str, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/projects/{project_id}/elect-path", payload, headers=headers)

    def close_out_project(self, project_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/projects/{project_id}/close-out", {}, headers=headers)

    # ---- regulatory agreements ---------------------------------------------
    def create_agreement(self, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/regulatory-agreements", payload, headers=headers)

    def get_agreement(self, agreement_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self.get(f"{BASE}/regulatory-agreements/{agreement_id}", headers=headers)

    def list_agreements(
        self,
        project_id: Any = ...,
        state: Any = ...,
        limit: Any = ...,
        offset: Any = ...,
        headers: Optional[dict] = None,
    ) -> requests.Response:
        params = _compact({"project_id": project_id, "state": state, "limit": limit, "offset": offset})
        return self.get(f"{BASE}/regulatory-agreements", headers=headers, params=params)

    def record_agreement(
        self, agreement_id: str, doc_number: str, recorded_at: str, headers: Optional[dict] = None
    ) -> requests.Response:
        return self.post(
            f"{BASE}/regulatory-agreements/{agreement_id}/record",
            {"doc_number": doc_number, "recorded_at": recorded_at},
            headers=headers,
        )

    # ---- affordable units ---------------------------------------------------
    def create_unit(self, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/affordable-units", payload, headers=headers)

    def get_unit(self, unit_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self.get(f"{BASE}/affordable-units/{unit_id}", headers=headers)

    def list_units(
        self,
        project_id: Any = ...,
        agreement_id: Any = ...,
        occupant_household_id: Any = ...,
        occupancy_status: Any = ...,
        compliance_status: Any = ...,
        restriction_state: Any = ...,
        tenure: Any = ...,
        limit: Any = ...,
        offset: Any = ...,
        headers: Optional[dict] = None,
    ) -> requests.Response:
        params = _compact(
            {
                "project_id": project_id,
                "agreement_id": agreement_id,
                "occupant_household_id": occupant_household_id,
                "occupancy_status": occupancy_status,
                "compliance_status": compliance_status,
                "restriction_state": restriction_state,
                "tenure": tenure,
                "limit": limit,
                "offset": offset,
            }
        )
        return self.get(f"{BASE}/affordable-units", headers=headers, params=params)

    def withdraw_unit(self, unit_id: str, reason: str, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/affordable-units/{unit_id}/withdraw", {"reason": reason}, headers=headers)

    def reinstate_unit(self, unit_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/affordable-units/{unit_id}/reinstate", {}, headers=headers)

    def record_restriction(
        self,
        unit_id: str,
        original_purchase_price_cents: int,
        recorded_at: str,
        headers: Optional[dict] = None,
    ) -> requests.Response:
        return self.post(
            f"{BASE}/affordable-units/{unit_id}/record-restriction",
            {"original_purchase_price_cents": original_purchase_price_cents, "recorded_at": recorded_at},
            headers=headers,
        )

    def release_restriction(self, unit_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/affordable-units/{unit_id}/release-restriction", {}, headers=headers)

    def refinance_review(
        self, unit_id: str, requested_balance_cents: int, headers: Optional[dict] = None
    ) -> requests.Response:
        return self.post(
            f"{BASE}/affordable-units/{unit_id}/refinance-review",
            {"requested_balance_cents": requested_balance_cents},
            headers=headers,
        )

    # ---- marketing plans ----------------------------------------------------
    def create_marketing_plan(self, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/marketing-plans", payload, headers=headers)

    def get_marketing_plan(self, marketing_plan_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self.get(f"{BASE}/marketing-plans/{marketing_plan_id}", headers=headers)

    def list_marketing_plans(
        self,
        project_id: Any = ...,
        state: Any = ...,
        limit: Any = ...,
        offset: Any = ...,
        headers: Optional[dict] = None,
    ) -> requests.Response:
        params = _compact({"project_id": project_id, "state": state, "limit": limit, "offset": offset})
        return self.get(f"{BASE}/marketing-plans", headers=headers, params=params)

    def review_marketing_plan(
        self, marketing_plan_id: str, decision: str, review_note: Any = ..., headers: Optional[dict] = None
    ) -> requests.Response:
        payload = _compact({"decision": decision, "review_note": review_note})
        return self.post(f"{BASE}/marketing-plans/{marketing_plan_id}/review", payload, headers=headers)

    def resubmit_marketing_plan(
        self, marketing_plan_id: str, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        return self.post(f"{BASE}/marketing-plans/{marketing_plan_id}/resubmit", payload, headers=headers)

    # ---- lottery events -----------------------------------------------------
    def create_lottery_event(self, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/lottery-events", payload, headers=headers)

    def get_lottery_event(self, lottery_event_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self.get(f"{BASE}/lottery-events/{lottery_event_id}", headers=headers)

    def list_lottery_events(
        self,
        marketing_plan_id: Any = ...,
        state: Any = ...,
        limit: Any = ...,
        offset: Any = ...,
        headers: Optional[dict] = None,
    ) -> requests.Response:
        params = _compact(
            {"marketing_plan_id": marketing_plan_id, "state": state, "limit": limit, "offset": offset}
        )
        return self.get(f"{BASE}/lottery-events", headers=headers, params=params)

    def draw_lottery(self, lottery_event_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/lottery-events/{lottery_event_id}/draw", {}, headers=headers)

    def redraw_lottery(self, lottery_event_id: str, reason: str, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/lottery-events/{lottery_event_id}/redraw", {"reason": reason}, headers=headers)

    # ---- households ---------------------------------------------------------
    def create_household(self, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/households", payload, headers=headers)

    def get_household(self, household_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self.get(f"{BASE}/households/{household_id}", headers=headers)

    def list_households(
        self,
        lottery_event_id: Any = ...,
        state: Any = ...,
        limit: Any = ...,
        offset: Any = ...,
        headers: Optional[dict] = None,
    ) -> requests.Response:
        params = _compact({"lottery_event_id": lottery_event_id, "state": state, "limit": limit, "offset": offset})
        return self.get(f"{BASE}/households", headers=headers, params=params)

    def apply_household(
        self,
        household_id: str,
        lottery_event_id: str,
        preference_claims: Any = ...,
        headers: Optional[dict] = None,
    ) -> requests.Response:
        payload = _compact({"lottery_event_id": lottery_event_id, "preference_claims": preference_claims})
        return self.post(f"{BASE}/households/{household_id}/apply", payload, headers=headers)

    # ---- income certifications ---------------------------------------------
    def create_certification(self, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/income-certifications", payload, headers=headers)

    def get_certification(self, certification_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self.get(f"{BASE}/income-certifications/{certification_id}", headers=headers)

    def list_certifications(
        self,
        household_id: Any = ...,
        unit_id: Any = ...,
        state: Any = ...,
        is_recertification: Any = ...,
        limit: Any = ...,
        offset: Any = ...,
        headers: Optional[dict] = None,
    ) -> requests.Response:
        params = _compact(
            {
                "household_id": household_id,
                "unit_id": unit_id,
                "state": state,
                "is_recertification": is_recertification,
                "limit": limit,
                "offset": offset,
            }
        )
        return self.get(f"{BASE}/income-certifications", headers=headers, params=params)

    def recertify(
        self,
        certification_id: str,
        certified_income_cents: int,
        contract_rent_cents: int,
        headers: Optional[dict] = None,
    ) -> requests.Response:
        return self.post(
            f"{BASE}/income-certifications/{certification_id}/recertify",
            {"certified_income_cents": certified_income_cents, "contract_rent_cents": contract_rent_cents},
            headers=headers,
        )

    # ---- monitoring reviews -------------------------------------------------
    def create_monitoring_review(self, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/monitoring-reviews", payload, headers=headers)

    def get_monitoring_review(self, monitoring_review_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self.get(f"{BASE}/monitoring-reviews/{monitoring_review_id}", headers=headers)

    def list_monitoring_reviews(
        self,
        unit_id: Any = ...,
        state: Any = ...,
        review_year: Any = ...,
        limit: Any = ...,
        offset: Any = ...,
        headers: Optional[dict] = None,
    ) -> requests.Response:
        params = _compact(
            {"unit_id": unit_id, "state": state, "review_year": review_year, "limit": limit, "offset": offset}
        )
        return self.get(f"{BASE}/monitoring-reviews", headers=headers, params=params)

    def submit_cure(
        self, monitoring_review_id: str, corrected_rent_cents: int, headers: Optional[dict] = None
    ) -> requests.Response:
        return self.post(
            f"{BASE}/monitoring-reviews/{monitoring_review_id}/submit-cure",
            {"corrected_rent_cents": corrected_rent_cents},
            headers=headers,
        )

    def clear_cure(self, monitoring_review_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/monitoring-reviews/{monitoring_review_id}/clear-cure", {}, headers=headers)

    def escalate_review(self, monitoring_review_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/monitoring-reviews/{monitoring_review_id}/escalate", {}, headers=headers)

    # ---- resale transactions ------------------------------------------------
    def create_resale(self, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/resale-transactions", payload, headers=headers)

    def get_resale(self, resale_transaction_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self.get(f"{BASE}/resale-transactions/{resale_transaction_id}", headers=headers)

    def list_resales(
        self,
        unit_id: Any = ...,
        prior_transaction_id: Any = ...,
        seller_household_id: Any = ...,
        buyer_household_id: Any = ...,
        buyer_certification_id: Any = ...,
        state: Any = ...,
        limit: Any = ...,
        offset: Any = ...,
        headers: Optional[dict] = None,
    ) -> requests.Response:
        params = _compact(
            {
                "unit_id": unit_id,
                "prior_transaction_id": prior_transaction_id,
                "seller_household_id": seller_household_id,
                "buyer_household_id": buyer_household_id,
                "buyer_certification_id": buyer_certification_id,
                "state": state,
                "limit": limit,
                "offset": offset,
            }
        )
        return self.get(f"{BASE}/resale-transactions", headers=headers, params=params)

    def approve_resale_price(self, resale_transaction_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/resale-transactions/{resale_transaction_id}/approve-price", {}, headers=headers)

    def rofr_decision(
        self, resale_transaction_id: str, decision: str, headers: Optional[dict] = None
    ) -> requests.Response:
        return self.post(
            f"{BASE}/resale-transactions/{resale_transaction_id}/rofr-decision",
            {"decision": decision},
            headers=headers,
        )

    def certify_buyer(
        self,
        resale_transaction_id: str,
        buyer_household_id: str,
        certification_id: str,
        headers: Optional[dict] = None,
    ) -> requests.Response:
        return self.post(
            f"{BASE}/resale-transactions/{resale_transaction_id}/certify-buyer",
            {"buyer_household_id": buyer_household_id, "certification_id": certification_id},
            headers=headers,
        )

    def close_resale(self, resale_transaction_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/resale-transactions/{resale_transaction_id}/close", {}, headers=headers)

    # ---- in-lieu fees -------------------------------------------------------
    def create_in_lieu_fee(self, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/in-lieu-fees", payload, headers=headers)

    def get_in_lieu_fee(self, fee_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self.get(f"{BASE}/in-lieu-fees/{fee_id}", headers=headers)

    def list_in_lieu_fees(
        self,
        project_id: Any = ...,
        ordinance_id: Any = ...,
        superseded_by_fee_id: Any = ...,
        basis: Any = ...,
        state: Any = ...,
        limit: Any = ...,
        offset: Any = ...,
        headers: Optional[dict] = None,
    ) -> requests.Response:
        params = _compact(
            {
                "project_id": project_id,
                "ordinance_id": ordinance_id,
                "superseded_by_fee_id": superseded_by_fee_id,
                "basis": basis,
                "state": state,
                "limit": limit,
                "offset": offset,
            }
        )
        return self.get(f"{BASE}/in-lieu-fees", headers=headers, params=params)

    def pay_in_lieu_fee(self, fee_id: str, amount_cents: int, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/in-lieu-fees/{fee_id}/payments", {"amount_cents": amount_cents}, headers=headers)

    # ---- housing trust fund -------------------------------------------------
    def create_disbursement(self, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/trust-fund-disbursements", payload, headers=headers)

    def get_disbursement(self, disbursement_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self.get(f"{BASE}/trust-fund-disbursements/{disbursement_id}", headers=headers)

    def list_disbursements(
        self,
        source_fee_id: Any = ...,
        eligible_use: Any = ...,
        state: Any = ...,
        limit: Any = ...,
        offset: Any = ...,
        headers: Optional[dict] = None,
    ) -> requests.Response:
        params = _compact(
            {
                "source_fee_id": source_fee_id,
                "eligible_use": eligible_use,
                "state": state,
                "limit": limit,
                "offset": offset,
            }
        )
        return self.get(f"{BASE}/trust-fund-disbursements", headers=headers, params=params)

    def disburse(self, disbursement_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self.post(f"{BASE}/trust-fund-disbursements/{disbursement_id}/disburse", {}, headers=headers)

    def void_disbursement(
        self, disbursement_id: str, void_reason: str, headers: Optional[dict] = None
    ) -> requests.Response:
        return self.post(
            f"{BASE}/trust-fund-disbursements/{disbursement_id}/void",
            {"void_reason": void_reason},
            headers=headers,
        )

    def get_trust_fund_summary(self, headers: Optional[dict] = None) -> requests.Response:
        return self.get(f"{BASE}/trust-fund-summary", headers=headers)

    def get_funder_report(
        self,
        project_id: str,
        basis: str,
        limit: Any = ...,
        offset: Any = ...,
        headers: Optional[dict] = None,
    ) -> requests.Response:
        params = _compact({"project_id": project_id, "basis": basis, "limit": limit, "offset": offset})
        return self.get(f"{BASE}/funder-reports", headers=headers, params=params)


api_client = ApiClient()
