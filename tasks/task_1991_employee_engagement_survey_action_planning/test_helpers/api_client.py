"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Item banks & items ---
    def create_item_bank(self, payload, headers):
        return self._request("POST", "/engagement/item-banks", payload, headers)

    def list_item_banks(self, headers, params=None):
        return self._request("GET", "/engagement/item-banks", headers=headers, params=params)

    def get_item_bank(self, bank_id, headers):
        return self._request("GET", f"/engagement/item-banks/{bank_id}", headers=headers)

    def add_survey_item(self, bank_id, payload, headers):
        return self._request("POST", f"/engagement/item-banks/{bank_id}/items", payload, headers)

    def list_survey_items(self, bank_id, headers, params=None):
        return self._request("GET", f"/engagement/item-banks/{bank_id}/items", headers=headers, params=params)

    def activate_item_bank(self, bank_id, headers):
        return self._request("POST", f"/engagement/item-banks/{bank_id}/activate", {}, headers)

    def retire_item_bank(self, bank_id, headers):
        return self._request("POST", f"/engagement/item-banks/{bank_id}/retire", {}, headers)

    # --- Org units & employees ---
    def create_org_unit(self, payload, headers):
        return self._request("POST", "/engagement/org-units", payload, headers)

    def list_org_units(self, headers, params=None):
        return self._request("GET", "/engagement/org-units", headers=headers, params=params)

    def get_org_unit(self, unit_id, headers):
        return self._request("GET", f"/engagement/org-units/{unit_id}", headers=headers)

    def update_org_unit(self, unit_id, payload, headers):
        return self._request("PATCH", f"/engagement/org-units/{unit_id}", payload, headers)

    def create_employee(self, payload, headers):
        return self._request("POST", "/engagement/employees", payload, headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/engagement/employees", headers=headers, params=params)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/engagement/employees/{employee_id}", headers=headers)

    def terminate_employee(self, employee_id, payload, headers):
        return self._request("POST", f"/engagement/employees/{employee_id}/terminate", payload, headers)

    # --- Survey cycles ---
    def create_survey_cycle(self, payload, headers):
        return self._request("POST", "/engagement/survey-cycles", payload, headers)

    def list_survey_cycles(self, headers, params=None):
        return self._request("GET", "/engagement/survey-cycles", headers=headers, params=params)

    def get_survey_cycle(self, cycle_id, headers):
        return self._request("GET", f"/engagement/survey-cycles/{cycle_id}", headers=headers)

    def pin_cycle_item(self, cycle_id, payload, headers):
        return self._request("POST", f"/engagement/survey-cycles/{cycle_id}/items", payload, headers)

    def list_cycle_items_of_cycle(self, cycle_id, headers, params=None):
        return self._request("GET", f"/engagement/survey-cycles/{cycle_id}/items", headers=headers, params=params)

    def list_cycle_items(self, headers, params=None):
        return self._request("GET", "/engagement/cycle-items", headers=headers, params=params)

    def get_cycle_item(self, cycle_item_id, headers):
        return self._request("GET", f"/engagement/cycle-items/{cycle_item_id}", headers=headers)

    def configure_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/engagement/survey-cycles/{cycle_id}/configure", payload, headers)

    def open_cycle(self, cycle_id, headers):
        return self._request("POST", f"/engagement/survey-cycles/{cycle_id}/open", {}, headers)

    def close_cycle(self, cycle_id, headers):
        return self._request("POST", f"/engagement/survey-cycles/{cycle_id}/close", {}, headers)

    def score_cycle(self, cycle_id, headers):
        return self._request("POST", f"/engagement/survey-cycles/{cycle_id}/score", {}, headers)

    def publish_cycle(self, cycle_id, headers):
        return self._request("POST", f"/engagement/survey-cycles/{cycle_id}/publish", {}, headers)

    def archive_cycle(self, cycle_id, headers):
        return self._request("POST", f"/engagement/survey-cycles/{cycle_id}/archive", {}, headers)

    def remind_cycle(self, cycle_id, headers):
        return self._request("POST", f"/engagement/survey-cycles/{cycle_id}/remind", {}, headers)

    # --- Invites & responses ---
    def list_survey_invites(self, headers, params=None):
        return self._request("GET", "/engagement/survey-invites", headers=headers, params=params)

    def get_survey_invite(self, invite_id, headers):
        return self._request("GET", f"/engagement/survey-invites/{invite_id}", headers=headers)

    def submit_invite(self, invite_id, payload, headers):
        return self._request("POST", f"/engagement/survey-invites/{invite_id}/submit", payload, headers)

    def submit_invite_partial(self, invite_id, payload, headers):
        return self._request("POST", f"/engagement/survey-invites/{invite_id}/submit-partial", payload, headers)

    def get_invite_response(self, invite_id, headers):
        return self._request("GET", f"/engagement/survey-invites/{invite_id}/response", headers=headers)

    def list_invite_reminders(self, invite_id, headers, params=None):
        return self._request("GET", f"/engagement/survey-invites/{invite_id}/reminders", headers=headers, params=params)

    # --- Reports & benchmarks ---
    def list_report_snapshots(self, headers, params=None):
        return self._request("GET", "/engagement/report-snapshots", headers=headers, params=params)

    def get_report_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/engagement/report-snapshots/{snapshot_id}", headers=headers)

    def recompute_report_snapshot(self, snapshot_id, headers):
        return self._request("POST", f"/engagement/report-snapshots/{snapshot_id}/recompute", {}, headers)

    def get_snapshot_verbatims(self, snapshot_id, headers, params=None):
        return self._request("GET", f"/engagement/report-snapshots/{snapshot_id}/verbatims", headers=headers, params=params)

    def create_benchmark_set(self, payload, headers):
        return self._request("POST", "/engagement/benchmark-sets", payload, headers)

    def retire_benchmark_set(self, benchmark_id, headers):
        return self._request("POST", f"/engagement/benchmark-sets/{benchmark_id}/retire", {}, headers)

    def list_benchmark_sets(self, headers, params=None):
        return self._request("GET", "/engagement/benchmark-sets", headers=headers, params=params)

    # --- Action plans & items ---
    def create_action_plan(self, payload, headers):
        return self._request("POST", "/engagement/action-plans", payload, headers)

    def list_action_plans(self, headers, params=None):
        return self._request("GET", "/engagement/action-plans", headers=headers, params=params)

    def get_action_plan(self, plan_id, headers):
        return self._request("GET", f"/engagement/action-plans/{plan_id}", headers=headers)

    def add_action_item(self, plan_id, payload, headers):
        return self._request("POST", f"/engagement/action-plans/{plan_id}/items", payload, headers)

    def list_action_items(self, plan_id, headers, params=None):
        return self._request("GET", f"/engagement/action-plans/{plan_id}/items", headers=headers, params=params)

    def submit_action_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/engagement/action-plans/{plan_id}/submit", payload, headers)

    def approve_action_plan(self, plan_id, headers):
        return self._request("POST", f"/engagement/action-plans/{plan_id}/approve", {}, headers)

    def reject_action_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/engagement/action-plans/{plan_id}/reject", payload, headers)

    def revise_action_plan(self, plan_id, headers):
        return self._request("POST", f"/engagement/action-plans/{plan_id}/revise", {}, headers)

    def start_action_plan(self, plan_id, headers):
        return self._request("POST", f"/engagement/action-plans/{plan_id}/start", {}, headers)

    def abandon_action_plan(self, plan_id, headers):
        return self._request("POST", f"/engagement/action-plans/{plan_id}/abandon", {}, headers)

    def complete_action_item(self, item_id, headers):
        return self._request("POST", f"/engagement/action-items/{item_id}/complete", {}, headers)

    def drop_action_item(self, item_id, headers):
        return self._request("POST", f"/engagement/action-items/{item_id}/drop", {}, headers)

    # --- Outcome linkages ---
    def create_outcome_linkage(self, employee_id, payload, headers):
        return self._request("POST", f"/engagement/employees/{employee_id}/outcome-linkages", payload, headers)

    def list_employee_outcome_linkages(self, employee_id, headers, params=None):
        return self._request("GET", f"/engagement/employees/{employee_id}/outcome-linkages", headers=headers, params=params)

    def list_outcome_linkages(self, headers, params=None):
        return self._request("GET", "/engagement/outcome-linkages", headers=headers, params=params)

    def get_outcome_linkage(self, linkage_id, headers):
        return self._request("GET", f"/engagement/outcome-linkages/{linkage_id}", headers=headers)

    # --- Logical clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/engagement/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
