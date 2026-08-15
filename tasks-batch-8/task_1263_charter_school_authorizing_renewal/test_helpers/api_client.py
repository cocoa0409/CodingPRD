"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving (logical clock) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/authorizer/_clock/set_current_utc", payload, headers)

    # --- Applications ---
    def create_application(self, payload, headers):
        return self._request("POST", "/authorizer/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/authorizer/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/authorizer/applications/{application_id}", headers=headers)

    def accept_intake(self, application_id, headers):
        return self._request("POST", f"/authorizer/applications/{application_id}/accept-intake", {}, headers)

    def post_application_score(self, application_id, payload, headers):
        return self._request("POST", f"/authorizer/applications/{application_id}/scores", payload, headers)

    def schedule_interview(self, application_id, payload, headers):
        return self._request("POST", f"/authorizer/applications/{application_id}/interviews", payload, headers)

    def list_interviews(self, application_id, headers):
        return self._request("GET", f"/authorizer/applications/{application_id}/interviews", headers=headers)

    def list_application_schools(self, application_id, headers):
        return self._request("GET", f"/authorizer/applications/{application_id}/schools", headers=headers)

    def advance_to_board(self, application_id, headers):
        return self._request("POST", f"/authorizer/applications/{application_id}/advance-to-board", {}, headers)

    def decide_application(self, application_id, payload, headers):
        return self._request("POST", f"/authorizer/applications/{application_id}/decide", payload, headers)

    def score_interview(self, interview_id, payload, headers):
        return self._request("POST", f"/authorizer/interviews/{interview_id}/score", payload, headers)

    # --- Schools ---
    def list_schools(self, headers, params=None):
        return self._request("GET", "/authorizer/schools", headers=headers, params=params)

    def get_school(self, school_id, headers):
        return self._request("GET", f"/authorizer/schools/{school_id}", headers=headers)

    # --- Contracts ---
    def create_contract(self, school_id, payload, headers):
        return self._request("POST", f"/authorizer/schools/{school_id}/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/authorizer/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/authorizer/contracts/{contract_id}", headers=headers)

    def add_contract_target(self, contract_id, payload, headers):
        return self._request("POST", f"/authorizer/contracts/{contract_id}/targets", payload, headers)

    def list_contract_targets(self, contract_id, headers):
        return self._request("GET", f"/authorizer/contracts/{contract_id}/targets", headers=headers)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/authorizer/contracts/{contract_id}/activate", {}, headers)

    # --- Monitoring ---
    def create_monitoring_report(self, school_id, payload, headers):
        return self._request("POST", f"/authorizer/schools/{school_id}/monitoring-reports", payload, headers)

    def list_monitoring_reports(self, school_id, headers):
        return self._request("GET", f"/authorizer/schools/{school_id}/monitoring-reports", headers=headers)

    def resubmit_monitoring_report(self, report_id, headers):
        return self._request("POST", f"/authorizer/monitoring-reports/{report_id}/submit", {}, headers)

    def accept_monitoring_report(self, report_id, headers):
        return self._request("POST", f"/authorizer/monitoring-reports/{report_id}/accept", {}, headers)

    def return_monitoring_report(self, report_id, payload, headers):
        return self._request("POST", f"/authorizer/monitoring-reports/{report_id}/return", payload, headers)

    # --- Lottery ---
    def create_lottery(self, school_id, payload, headers):
        return self._request("POST", f"/authorizer/schools/{school_id}/lotteries", payload, headers)

    def list_lotteries(self, school_id, headers):
        return self._request("GET", f"/authorizer/schools/{school_id}/lotteries", headers=headers)

    def get_lottery(self, lottery_id, headers):
        return self._request("GET", f"/authorizer/lotteries/{lottery_id}", headers=headers)

    def open_lottery(self, lottery_id, headers):
        return self._request("POST", f"/authorizer/lotteries/{lottery_id}/open", {}, headers)

    def add_lottery_entry(self, lottery_id, payload, headers):
        return self._request("POST", f"/authorizer/lotteries/{lottery_id}/entries", payload, headers)

    def list_lottery_entries(self, lottery_id, headers):
        return self._request("GET", f"/authorizer/lotteries/{lottery_id}/entries", headers=headers)

    def verify_preference(self, entry_id, payload, headers):
        return self._request("POST", f"/authorizer/lottery-entries/{entry_id}/verify-preference", payload, headers)

    def seal_lottery(self, lottery_id, headers):
        return self._request("POST", f"/authorizer/lotteries/{lottery_id}/seal", {}, headers)

    def execute_lottery(self, lottery_id, headers):
        return self._request("POST", f"/authorizer/lotteries/{lottery_id}/execute", {}, headers)

    def decline_entry(self, entry_id, headers):
        return self._request("POST", f"/authorizer/lottery-entries/{entry_id}/decline", {}, headers)

    def certify_lottery(self, lottery_id, payload, headers):
        return self._request("POST", f"/authorizer/lotteries/{lottery_id}/certify", payload, headers)

    # --- Interventions & corrective action ---
    def create_intervention(self, school_id, payload, headers):
        return self._request("POST", f"/authorizer/schools/{school_id}/interventions", payload, headers)

    def list_interventions(self, school_id, headers):
        return self._request("GET", f"/authorizer/schools/{school_id}/interventions", headers=headers)

    def get_intervention(self, notice_id, headers):
        return self._request("GET", f"/authorizer/interventions/{notice_id}", headers=headers)

    def issue_intervention(self, notice_id, headers):
        return self._request("POST", f"/authorizer/interventions/{notice_id}/issue", {}, headers)

    def escalate_intervention(self, notice_id, headers):
        return self._request("POST", f"/authorizer/interventions/{notice_id}/escalate", {}, headers)

    def resolve_intervention(self, notice_id, headers):
        return self._request("POST", f"/authorizer/interventions/{notice_id}/resolve", {}, headers)

    def create_corrective_plan(self, notice_id, payload, headers):
        return self._request("POST", f"/authorizer/interventions/{notice_id}/corrective-plans", payload, headers)

    def list_corrective_plans(self, notice_id, headers):
        return self._request("GET", f"/authorizer/interventions/{notice_id}/corrective-plans", headers=headers)

    def review_corrective_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/authorizer/corrective-plans/{plan_id}/review", payload, headers)

    def resubmit_corrective_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/authorizer/corrective-plans/{plan_id}/resubmit", payload, headers)

    # --- Renewal ---
    def create_renewal_decision(self, school_id, payload, headers):
        return self._request("POST", f"/authorizer/schools/{school_id}/renewal-decisions", payload, headers)

    def list_renewal_decisions(self, headers, params=None):
        return self._request("GET", "/authorizer/renewal-decisions", headers=headers, params=params)

    def get_renewal_decision(self, decision_id, headers):
        return self._request("GET", f"/authorizer/renewal-decisions/{decision_id}", headers=headers)

    def decide_renewal(self, decision_id, payload, headers):
        return self._request("POST", f"/authorizer/renewal-decisions/{decision_id}/decide", payload, headers)

    def finalize_renewal(self, decision_id, headers):
        return self._request("POST", f"/authorizer/renewal-decisions/{decision_id}/finalize", {}, headers)

    # --- Closure ---
    def create_closure_plan(self, school_id, payload, headers):
        return self._request("POST", f"/authorizer/schools/{school_id}/closure-plans", payload, headers)

    def list_closure_plans(self, school_id, headers):
        return self._request("GET", f"/authorizer/schools/{school_id}/closure-plans", headers=headers)

    def get_closure_plan(self, plan_id, headers):
        return self._request("GET", f"/authorizer/closure-plans/{plan_id}", headers=headers)

    def add_student_transition(self, plan_id, payload, headers):
        return self._request("POST", f"/authorizer/closure-plans/{plan_id}/student-transitions", payload, headers)

    def list_student_transitions(self, plan_id, headers):
        return self._request("GET", f"/authorizer/closure-plans/{plan_id}/student-transitions", headers=headers)

    def place_student_transition(self, transition_id, payload, headers):
        return self._request("POST", f"/authorizer/student-transitions/{transition_id}/place", payload, headers)

    def records_sent_student_transition(self, transition_id, headers):
        return self._request("POST", f"/authorizer/student-transitions/{transition_id}/records-sent", {}, headers)

    def advance_closure_plan(self, plan_id, headers):
        return self._request("POST", f"/authorizer/closure-plans/{plan_id}/advance", {}, headers)

    # --- Authorizer fees ---
    def create_fee_invoice(self, school_id, payload, headers):
        return self._request("POST", f"/authorizer/schools/{school_id}/fee-invoices", payload, headers)

    def list_fee_invoices(self, school_id, headers):
        return self._request("GET", f"/authorizer/schools/{school_id}/fee-invoices", headers=headers)

    def finalize_fee_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/authorizer/fee-invoices/{invoice_id}/finalize", payload, headers)

    def pay_fee_invoice(self, invoice_id, headers):
        return self._request("POST", f"/authorizer/fee-invoices/{invoice_id}/pay", {}, headers)

    def waive_fee_invoice(self, invoice_id, headers):
        return self._request("POST", f"/authorizer/fee-invoices/{invoice_id}/waive", {}, headers)

    # --- Appeals ---
    def file_appeal(self, payload, headers):
        return self._request("POST", "/authorizer/appeals", payload, headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/authorizer/appeals", headers=headers, params=params)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/authorizer/appeals/{appeal_id}", headers=headers)

    def schedule_hearing(self, appeal_id, payload, headers):
        return self._request("POST", f"/authorizer/appeals/{appeal_id}/schedule-hearing", payload, headers)

    def rule_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/authorizer/appeals/{appeal_id}/rule", payload, headers)


api_client = ApiClient()
