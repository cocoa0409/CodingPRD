"""API client: one method per endpoint published by the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- logical clock ----------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ---------------- concessionaires ----------------
    def create_concessionaire(self, payload, headers):
        return self._request("POST", "/ppp/concessionaires", payload, headers)

    def get_concessionaire(self, concessionaire_id, headers):
        return self._request(
            "GET", f"/ppp/concessionaires/{concessionaire_id}", headers=headers
        )

    def list_concessionaires(self, headers, params=None):
        return self._request(
            "GET", "/ppp/concessionaires", headers=headers, params=params
        )

    # ---------------- concessions ----------------
    def create_concession(self, payload, headers):
        return self._request("POST", "/ppp/concessions", payload, headers)

    def get_concession(self, concession_id, headers):
        return self._request("GET", f"/ppp/concessions/{concession_id}", headers=headers)

    def list_concessions(self, headers, params=None):
        return self._request("GET", "/ppp/concessions", headers=headers, params=params)

    def amend_concession(self, concession_id, payload, headers):
        return self._request(
            "PATCH", f"/ppp/concessions/{concession_id}", payload, headers
        )

    def get_payment_summary(self, concession_id, headers):
        return self._request(
            "GET", f"/ppp/concessions/{concession_id}/payment-summary", headers=headers
        )

    def financial_close(self, concession_id, payload, headers):
        return self._request(
            "POST", f"/ppp/concessions/{concession_id}/financial-close", payload, headers
        )

    def certify_service_commencement(self, concession_id, payload, headers):
        return self._request(
            "POST",
            f"/ppp/concessions/{concession_id}/certify-service-commencement",
            payload,
            headers,
        )

    def handback_survey(self, concession_id, payload, headers):
        return self._request(
            "POST", f"/ppp/concessions/{concession_id}/handback-survey", payload, headers
        )

    # ---------------- drawdown milestones ----------------
    def create_drawdown_milestone(self, concession_id, payload, headers):
        return self._request(
            "POST",
            f"/ppp/concessions/{concession_id}/drawdown-milestones",
            payload,
            headers,
        )

    def get_drawdown_milestone(self, milestone_id, headers):
        return self._request(
            "GET", f"/ppp/drawdown-milestones/{milestone_id}", headers=headers
        )

    def list_drawdown_milestones(self, headers, params=None):
        return self._request(
            "GET", "/ppp/drawdown-milestones", headers=headers, params=params
        )

    def approve_drawdown_milestone(self, milestone_id, payload, headers):
        return self._request(
            "POST", f"/ppp/drawdown-milestones/{milestone_id}/approve", payload, headers
        )

    def reject_drawdown_milestone(self, milestone_id, payload, headers):
        return self._request(
            "POST", f"/ppp/drawdown-milestones/{milestone_id}/reject", payload, headers
        )

    def disburse_drawdown_milestone(self, milestone_id, headers, payload=None):
        return self._request(
            "POST",
            f"/ppp/drawdown-milestones/{milestone_id}/disburse",
            payload if payload is not None else {},
            headers,
        )

    # ---------------- service periods ----------------
    def create_service_period(self, concession_id, payload, headers):
        return self._request(
            "POST", f"/ppp/concessions/{concession_id}/service-periods", payload, headers
        )

    def get_service_period(self, service_period_id, headers):
        return self._request(
            "GET", f"/ppp/service-periods/{service_period_id}", headers=headers
        )

    def list_service_periods(self, headers, params=None):
        return self._request(
            "GET", "/ppp/service-periods", headers=headers, params=params
        )

    def verify_service_period(self, service_period_id, payload, headers):
        return self._request(
            "POST", f"/ppp/service-periods/{service_period_id}/verify", payload, headers
        )

    def invoice_service_period(self, service_period_id, headers, payload=None):
        return self._request(
            "POST",
            f"/ppp/service-periods/{service_period_id}/invoice",
            payload if payload is not None else {},
            headers,
        )

    def pay_service_period(self, service_period_id, payload, headers):
        return self._request(
            "POST", f"/ppp/service-periods/{service_period_id}/pay", payload, headers
        )

    # ---------------- performance reports ----------------
    def create_performance_report(self, service_period_id, payload, headers):
        return self._request(
            "POST",
            f"/ppp/service-periods/{service_period_id}/performance-reports",
            payload,
            headers,
        )

    def get_performance_report(self, performance_report_id, headers):
        return self._request(
            "GET", f"/ppp/performance-reports/{performance_report_id}", headers=headers
        )

    def list_performance_reports(self, headers, params=None):
        return self._request(
            "GET", "/ppp/performance-reports", headers=headers, params=params
        )

    def reject_performance_report(self, performance_report_id, payload, headers):
        return self._request(
            "POST",
            f"/ppp/performance-reports/{performance_report_id}/reject",
            payload,
            headers,
        )

    # ---------------- deduction events ----------------
    def create_deduction_event(self, service_period_id, payload, headers):
        return self._request(
            "POST",
            f"/ppp/service-periods/{service_period_id}/deduction-events",
            payload,
            headers,
        )

    def get_deduction_event(self, deduction_event_id, headers):
        return self._request(
            "GET", f"/ppp/deduction-events/{deduction_event_id}", headers=headers
        )

    def list_deduction_events(self, headers, params=None):
        return self._request(
            "GET", "/ppp/deduction-events", headers=headers, params=params
        )

    def withdraw_deduction_event(self, deduction_event_id, payload, headers):
        return self._request(
            "POST",
            f"/ppp/deduction-events/{deduction_event_id}/withdraw",
            payload,
            headers,
        )

    # ---------------- deduction disputes ----------------
    def create_deduction_dispute(self, deduction_event_id, payload, headers):
        return self._request(
            "POST",
            f"/ppp/deduction-events/{deduction_event_id}/disputes",
            payload,
            headers,
        )

    def get_deduction_dispute(self, dispute_id, headers):
        return self._request(
            "GET", f"/ppp/deduction-disputes/{dispute_id}", headers=headers
        )

    def list_deduction_disputes(self, headers, params=None):
        return self._request(
            "GET", "/ppp/deduction-disputes", headers=headers, params=params
        )

    def refer_back_deduction_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/ppp/deduction-disputes/{dispute_id}/refer-back", payload, headers
        )

    def resubmit_deduction_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/ppp/deduction-disputes/{dispute_id}/resubmit", payload, headers
        )

    def adjudicate_deduction_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/ppp/deduction-disputes/{dispute_id}/adjudicate", payload, headers
        )

    # ---------------- relief claims ----------------
    def create_relief_claim(self, concession_id, payload, headers):
        return self._request(
            "POST", f"/ppp/concessions/{concession_id}/relief-claims", payload, headers
        )

    def get_relief_claim(self, relief_claim_id, headers):
        return self._request(
            "GET", f"/ppp/relief-claims/{relief_claim_id}", headers=headers
        )

    def list_relief_claims(self, headers, params=None):
        return self._request("GET", "/ppp/relief-claims", headers=headers, params=params)

    def determine_relief_claim(self, relief_claim_id, payload, headers):
        return self._request(
            "POST", f"/ppp/relief-claims/{relief_claim_id}/determine", payload, headers
        )

    # ---------------- lifecycle reserve ledger ----------------
    def create_reserve_transaction(self, concession_id, payload, headers):
        return self._request(
            "POST",
            f"/ppp/concessions/{concession_id}/reserve-transactions",
            payload,
            headers,
        )

    def get_reserve_transaction(self, transaction_id, headers):
        return self._request(
            "GET", f"/ppp/reserve-transactions/{transaction_id}", headers=headers
        )

    def list_reserve_transactions(self, headers, params=None):
        return self._request(
            "GET", "/ppp/reserve-transactions", headers=headers, params=params
        )

    def reverse_reserve_transaction(self, transaction_id, payload, headers):
        return self._request(
            "POST",
            f"/ppp/reserve-transactions/{transaction_id}/reverse",
            payload,
            headers,
        )

    # ---------------- refinancing ----------------
    def create_refinancing_event(self, concession_id, payload, headers):
        return self._request(
            "POST",
            f"/ppp/concessions/{concession_id}/refinancing-events",
            payload,
            headers,
        )

    def get_refinancing_event(self, refinancing_event_id, headers):
        return self._request(
            "GET", f"/ppp/refinancing-events/{refinancing_event_id}", headers=headers
        )

    def list_refinancing_events(self, headers, params=None):
        return self._request(
            "GET", "/ppp/refinancing-events", headers=headers, params=params
        )

    def consent_refinancing_event(self, refinancing_event_id, payload, headers):
        return self._request(
            "POST",
            f"/ppp/refinancing-events/{refinancing_event_id}/consent",
            payload,
            headers,
        )

    # ---------------- enforcement ----------------
    def create_enforcement_action(self, concession_id, payload, headers):
        return self._request(
            "POST",
            f"/ppp/concessions/{concession_id}/enforcement-actions",
            payload,
            headers,
        )

    def get_enforcement_action(self, enforcement_action_id, headers):
        return self._request(
            "GET", f"/ppp/enforcement-actions/{enforcement_action_id}", headers=headers
        )

    def list_enforcement_actions(self, headers, params=None):
        return self._request(
            "GET", "/ppp/enforcement-actions", headers=headers, params=params
        )

    def cure_enforcement_action(self, enforcement_action_id, payload, headers):
        return self._request(
            "POST",
            f"/ppp/enforcement-actions/{enforcement_action_id}/cure",
            payload,
            headers,
        )

    def escalate_enforcement_action(self, enforcement_action_id, headers, payload=None):
        return self._request(
            "POST",
            f"/ppp/enforcement-actions/{enforcement_action_id}/escalate",
            payload if payload is not None else {},
            headers,
        )

    def calculate_compensation(self, enforcement_action_id, payload, headers):
        return self._request(
            "POST",
            f"/ppp/enforcement-actions/{enforcement_action_id}/calculate-compensation",
            payload,
            headers,
        )

    def settle_enforcement_action(self, enforcement_action_id, payload, headers):
        return self._request(
            "POST",
            f"/ppp/enforcement-actions/{enforcement_action_id}/settle",
            payload,
            headers,
        )


api_client = ApiClient()
