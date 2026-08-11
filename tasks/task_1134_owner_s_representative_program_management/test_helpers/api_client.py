"""API client: one method per endpoint defined in the PRD §4 table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------- Program ----------
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def activate_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/activate", {}, headers)

    def begin_closing_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/begin-closing", {}, headers)

    def close_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/close", {}, headers)

    def reopen_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/reopen", {}, headers)

    # ---------- Charter ----------
    def create_charter(self, payload, headers):
        return self._request("POST", "/charters", payload, headers)

    def list_charters(self, headers, params=None):
        return self._request("GET", "/charters", headers=headers, params=params)

    def get_charter(self, charter_id, headers):
        return self._request("GET", f"/charters/{charter_id}", headers=headers)

    def submit_charter(self, charter_id, headers):
        return self._request("POST", f"/charters/{charter_id}/submit", {}, headers)

    def decide_charter(self, charter_id, payload, headers):
        return self._request("POST", f"/charters/{charter_id}/decide", payload, headers)

    def revise_charter(self, charter_id, payload, headers):
        return self._request("POST", f"/charters/{charter_id}/revise", payload, headers)

    # ---------- Baseline ----------
    def create_baseline(self, payload, headers):
        return self._request("POST", "/baselines", payload, headers)

    def list_baselines(self, headers, params=None):
        return self._request("GET", "/baselines", headers=headers, params=params)

    def get_baseline(self, baseline_id, headers):
        return self._request("GET", f"/baselines/{baseline_id}", headers=headers)

    def submit_baseline(self, baseline_id, headers):
        return self._request("POST", f"/baselines/{baseline_id}/submit", {}, headers)

    def decide_baseline(self, baseline_id, payload, headers):
        return self._request("POST", f"/baselines/{baseline_id}/decide", payload, headers)

    def revise_baseline(self, baseline_id, payload, headers):
        return self._request("POST", f"/baselines/{baseline_id}/revise", payload, headers)

    # ---------- Contract ----------
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def begin_negotiation(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/begin-negotiation", {}, headers)

    def counter_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/counter", payload, headers)

    def execute_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/execute", payload, headers)

    def complete_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/complete", {}, headers)

    # ---------- ChangeOrder ----------
    def create_change_order(self, payload, headers):
        return self._request("POST", "/change-orders", payload, headers)

    def list_change_orders(self, headers, params=None):
        return self._request("GET", "/change-orders", headers=headers, params=params)

    def get_change_order(self, co_id, headers):
        return self._request("GET", f"/change-orders/{co_id}", headers=headers)

    def submit_change_order(self, co_id, headers):
        return self._request("POST", f"/change-orders/{co_id}/submit", {}, headers)

    def request_revision_change_order(self, co_id, payload, headers):
        return self._request("POST", f"/change-orders/{co_id}/request-revision", payload, headers)

    def recommend_change_order(self, co_id, payload, headers):
        return self._request("POST", f"/change-orders/{co_id}/recommend", payload, headers)

    def decide_change_order(self, co_id, payload, headers):
        return self._request("POST", f"/change-orders/{co_id}/decide", payload, headers)

    def void_change_order(self, co_id, payload, headers):
        return self._request("POST", f"/change-orders/{co_id}/void", payload, headers)

    # ---------- RiskEntry ----------
    def create_risk_entry(self, payload, headers):
        return self._request("POST", "/risk-entries", payload, headers)

    def list_risk_entries(self, headers, params=None):
        return self._request("GET", "/risk-entries", headers=headers, params=params)

    def get_risk_entry(self, risk_id, headers):
        return self._request("GET", f"/risk-entries/{risk_id}", headers=headers)

    def assess_risk(self, risk_id, payload, headers):
        return self._request("POST", f"/risk-entries/{risk_id}/assess", payload, headers)

    def mitigate_risk(self, risk_id, payload, headers):
        return self._request("POST", f"/risk-entries/{risk_id}/mitigate", payload, headers)

    def monitor_risk(self, risk_id, headers):
        return self._request("POST", f"/risk-entries/{risk_id}/monitor", {}, headers)

    def realize_risk(self, risk_id, payload, headers):
        return self._request("POST", f"/risk-entries/{risk_id}/realize", payload, headers)

    def close_risk(self, risk_id, headers):
        return self._request("POST", f"/risk-entries/{risk_id}/close", {}, headers)

    # ---------- ContingencyDrawdown ----------
    def create_drawdown(self, payload, headers):
        return self._request("POST", "/contingency-drawdowns", payload, headers)

    def list_drawdowns(self, headers, params=None):
        return self._request("GET", "/contingency-drawdowns", headers=headers, params=params)

    def get_drawdown(self, dd_id, headers):
        return self._request("GET", f"/contingency-drawdowns/{dd_id}", headers=headers)

    def commit_drawdown(self, dd_id, headers):
        return self._request("POST", f"/contingency-drawdowns/{dd_id}/commit", {}, headers)

    def draw_drawdown(self, dd_id, headers):
        return self._request("POST", f"/contingency-drawdowns/{dd_id}/draw", {}, headers)

    def release_drawdown(self, dd_id, headers):
        return self._request("POST", f"/contingency-drawdowns/{dd_id}/release", {}, headers)

    # ---------- OwnerReport ----------
    def create_owner_report(self, payload, headers):
        return self._request("POST", "/owner-reports", payload, headers)

    def list_owner_reports(self, headers, params=None):
        return self._request("GET", "/owner-reports", headers=headers, params=params)

    def get_owner_report(self, report_id, headers):
        return self._request("GET", f"/owner-reports/{report_id}", headers=headers)

    def submit_owner_report(self, report_id, headers):
        return self._request("POST", f"/owner-reports/{report_id}/submit", {}, headers)

    def accept_owner_report(self, report_id, headers):
        return self._request("POST", f"/owner-reports/{report_id}/accept", {}, headers)

    def return_owner_report(self, report_id, payload, headers):
        return self._request("POST", f"/owner-reports/{report_id}/return", payload, headers)

    # ---------- StakeholderGroup ----------
    def create_stakeholder_group(self, payload, headers):
        return self._request("POST", "/stakeholder-groups", payload, headers)

    def list_stakeholder_groups(self, headers, params=None):
        return self._request("GET", "/stakeholder-groups", headers=headers, params=params)

    def get_stakeholder_group(self, group_id, headers):
        return self._request("GET", f"/stakeholder-groups/{group_id}", headers=headers)

    # ---------- EngagementItem ----------
    def create_engagement(self, payload, headers):
        return self._request("POST", "/engagements", payload, headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", "/engagements", headers=headers, params=params)

    def get_engagement(self, eng_id, headers):
        return self._request("GET", f"/engagements/{eng_id}", headers=headers)

    def schedule_engagement(self, eng_id, headers):
        return self._request("POST", f"/engagements/{eng_id}/schedule", {}, headers)

    def complete_engagement(self, eng_id, headers):
        return self._request("POST", f"/engagements/{eng_id}/complete", {}, headers)

    def cancel_engagement(self, eng_id, headers):
        return self._request("POST", f"/engagements/{eng_id}/cancel", {}, headers)

    # ---------- OccupancyPlan ----------
    def create_occupancy_plan(self, payload, headers):
        return self._request("POST", "/occupancy-plans", payload, headers)

    def list_occupancy_plans(self, headers, params=None):
        return self._request("GET", "/occupancy-plans", headers=headers, params=params)

    def get_occupancy_plan(self, plan_id, headers):
        return self._request("GET", f"/occupancy-plans/{plan_id}", headers=headers)

    def coordinate_occupancy_plan(self, plan_id, headers):
        return self._request("POST", f"/occupancy-plans/{plan_id}/coordinate", {}, headers)

    def mark_ready_occupancy_plan(self, plan_id, headers):
        return self._request("POST", f"/occupancy-plans/{plan_id}/mark-ready", {}, headers)

    def execute_occupancy_plan(self, plan_id, headers):
        return self._request("POST", f"/occupancy-plans/{plan_id}/execute", {}, headers)

    def complete_occupancy_plan(self, plan_id, headers):
        return self._request("POST", f"/occupancy-plans/{plan_id}/complete", {}, headers)

    # ---------- MoveInWave ----------
    def create_move_in_wave(self, payload, headers):
        return self._request("POST", "/move-in-waves", payload, headers)

    def list_move_in_waves(self, headers, params=None):
        return self._request("GET", "/move-in-waves", headers=headers, params=params)

    def get_move_in_wave(self, wave_id, headers):
        return self._request("GET", f"/move-in-waves/{wave_id}", headers=headers)

    def confirm_move_in_wave(self, wave_id, headers):
        return self._request("POST", f"/move-in-waves/{wave_id}/confirm", {}, headers)

    def complete_move_in_wave(self, wave_id, headers):
        return self._request("POST", f"/move-in-waves/{wave_id}/complete", {}, headers)

    def cancel_move_in_wave(self, wave_id, headers):
        return self._request("POST", f"/move-in-waves/{wave_id}/cancel", {}, headers)

    # ---------- CloseoutItem ----------
    def create_closeout_item(self, payload, headers):
        return self._request("POST", "/closeout-items", payload, headers)

    def list_closeout_items(self, headers, params=None):
        return self._request("GET", "/closeout-items", headers=headers, params=params)

    def get_closeout_item(self, item_id, headers):
        return self._request("GET", f"/closeout-items/{item_id}", headers=headers)

    def submit_closeout_item(self, item_id, headers):
        return self._request("POST", f"/closeout-items/{item_id}/submit", {}, headers)

    def verify_closeout_item(self, item_id, headers):
        return self._request("POST", f"/closeout-items/{item_id}/verify", {}, headers)

    def reject_closeout_item(self, item_id, payload, headers):
        return self._request("POST", f"/closeout-items/{item_id}/reject", payload, headers)

    # ---------- LessonEntry ----------
    def create_lesson_entry(self, payload, headers):
        return self._request("POST", "/lesson-entries", payload, headers)

    def list_lesson_entries(self, headers, params=None):
        return self._request("GET", "/lesson-entries", headers=headers, params=params)

    def get_lesson_entry(self, lesson_id, headers):
        return self._request("GET", f"/lesson-entries/{lesson_id}", headers=headers)


api_client = ApiClient()
