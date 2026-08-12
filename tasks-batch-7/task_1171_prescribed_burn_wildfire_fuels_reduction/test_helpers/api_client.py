"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Associations ---
    def create_association(self, payload, headers):
        return self._request("POST", "/associations", payload, headers)

    def get_association(self, assoc_id, headers):
        return self._request("GET", f"/associations/{assoc_id}", headers=headers)

    def deposit_fund(self, assoc_id, payload, headers):
        return self._request("POST", f"/associations/{assoc_id}/fund-deposits", payload, headers)

    # --- Landowners ---
    def create_landowner(self, payload, headers):
        return self._request("POST", "/landowners", payload, headers)

    def get_landowner(self, landowner_id, headers):
        return self._request("GET", f"/landowners/{landowner_id}", headers=headers)

    def list_landowners(self, headers, params=None):
        return self._request("GET", "/landowners", headers=headers, params=params)

    # --- Parcels ---
    def create_parcel(self, payload, headers):
        return self._request("POST", "/parcels", payload, headers)

    def get_parcel(self, parcel_id, headers):
        return self._request("GET", f"/parcels/{parcel_id}", headers=headers)

    def list_parcels(self, headers, params=None):
        return self._request("GET", "/parcels", headers=headers, params=params)

    # --- Burn bosses ---
    def create_burn_boss(self, payload, headers):
        return self._request("POST", "/burn-bosses", payload, headers)

    def get_burn_boss(self, boss_id, headers):
        return self._request("GET", f"/burn-bosses/{boss_id}", headers=headers)

    # --- Contractors ---
    def create_contractor(self, payload, headers):
        return self._request("POST", "/contractors", payload, headers)

    def get_contractor(self, contractor_id, headers):
        return self._request("GET", f"/contractors/{contractor_id}", headers=headers)

    def list_contractors(self, headers, params=None):
        return self._request("GET", "/contractors", headers=headers, params=params)

    def list_contractor_assignments(self, contractor_id, headers, params=None):
        return self._request("GET", f"/contractors/{contractor_id}/assignments", headers=headers, params=params)

    # --- Burn plans ---
    def create_burn_plan(self, payload, headers):
        return self._request("POST", "/burn-plans", payload, headers)

    def get_burn_plan(self, plan_id, headers):
        return self._request("GET", f"/burn-plans/{plan_id}", headers=headers)

    def list_burn_plans(self, headers, params=None):
        return self._request("GET", "/burn-plans", headers=headers, params=params)

    def submit_plan(self, plan_id, headers):
        return self._request("POST", f"/burn-plans/{plan_id}/submit", {}, headers)

    def request_plan_revision(self, plan_id, headers):
        return self._request("POST", f"/burn-plans/{plan_id}/request-revision", {}, headers)

    def revise_plan(self, plan_id, headers):
        return self._request("POST", f"/burn-plans/{plan_id}/revise", {}, headers)

    def approve_plan(self, plan_id, headers):
        return self._request("POST", f"/burn-plans/{plan_id}/approve", {}, headers)

    def cancel_plan(self, plan_id, headers):
        return self._request("POST", f"/burn-plans/{plan_id}/cancel", {}, headers)

    # --- Permits & notifications ---
    def create_permit(self, plan_id, payload, headers):
        return self._request("POST", f"/burn-plans/{plan_id}/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    def list_plan_permits(self, plan_id, headers, params=None):
        return self._request("GET", f"/burn-plans/{plan_id}/permits", headers=headers, params=params)

    def create_notification(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/notifications", payload, headers)

    def list_notifications(self, permit_id, headers, params=None):
        return self._request("GET", f"/permits/{permit_id}/notifications", headers=headers, params=params)

    def confirm_notification(self, notification_id, headers):
        return self._request("POST", f"/notifications/{notification_id}/confirm", {}, headers)

    def issue_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/issue", {}, headers)

    def deny_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/deny", {}, headers)

    def suspend_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/suspend", {}, headers)

    def reinstate_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/reinstate", {}, headers)

    def revoke_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/revoke", {}, headers)

    # --- Smoke management ---
    def create_smoke_approval(self, plan_id, payload, headers):
        return self._request("POST", f"/burn-plans/{plan_id}/smoke-approvals", payload, headers)

    def get_smoke_approval(self, smoke_id, headers):
        return self._request("GET", f"/smoke-approvals/{smoke_id}", headers=headers)

    def list_plan_smoke_approvals(self, plan_id, headers, params=None):
        return self._request("GET", f"/burn-plans/{plan_id}/smoke-approvals", headers=headers, params=params)

    def decide_smoke_approval(self, smoke_id, payload, headers):
        return self._request("POST", f"/smoke-approvals/{smoke_id}/decide", payload, headers)

    def withdraw_smoke_approval(self, smoke_id, headers):
        return self._request("POST", f"/smoke-approvals/{smoke_id}/withdraw", {}, headers)

    def clear_smoke_conditions(self, smoke_id, headers):
        return self._request("POST", f"/smoke-approvals/{smoke_id}/clear-conditions", {}, headers)

    # --- Contingency plans ---
    def create_contingency_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/burn-plans/{plan_id}/contingency-plans", payload, headers)

    def get_contingency_plan(self, cont_id, headers):
        return self._request("GET", f"/contingency-plans/{cont_id}", headers=headers)

    def list_plan_contingency_plans(self, plan_id, headers, params=None):
        return self._request("GET", f"/burn-plans/{plan_id}/contingency-plans", headers=headers, params=params)

    def accept_contingency_plan(self, cont_id, headers):
        return self._request("POST", f"/contingency-plans/{cont_id}/accept", {}, headers)

    def reject_contingency_plan(self, cont_id, payload, headers):
        return self._request("POST", f"/contingency-plans/{cont_id}/reject", payload, headers)

    def revise_contingency_plan(self, cont_id, headers):
        return self._request("POST", f"/contingency-plans/{cont_id}/revise", {}, headers)

    # --- Ignition plans ---
    def create_ignition_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/burn-plans/{plan_id}/ignition-plans", payload, headers)

    def get_ignition_plan(self, ign_id, headers):
        return self._request("GET", f"/ignition-plans/{ign_id}", headers=headers)

    def list_plan_ignition_plans(self, plan_id, headers, params=None):
        return self._request("GET", f"/burn-plans/{plan_id}/ignition-plans", headers=headers, params=params)

    def accept_ignition_plan(self, ign_id, headers):
        return self._request("POST", f"/ignition-plans/{ign_id}/accept", {}, headers)

    def reject_ignition_plan(self, ign_id, payload, headers):
        return self._request("POST", f"/ignition-plans/{ign_id}/reject", payload, headers)

    def revise_ignition_plan(self, ign_id, headers):
        return self._request("POST", f"/ignition-plans/{ign_id}/revise", {}, headers)

    # --- Resource orders & crew assignments ---
    def create_resource_order(self, plan_id, payload, headers):
        return self._request("POST", f"/burn-plans/{plan_id}/resource-orders", payload, headers)

    def get_resource_order(self, order_id, headers):
        return self._request("GET", f"/resource-orders/{order_id}", headers=headers)

    def list_plan_resource_orders(self, plan_id, headers, params=None):
        return self._request("GET", f"/burn-plans/{plan_id}/resource-orders", headers=headers, params=params)

    def submit_resource_order(self, order_id, headers):
        return self._request("POST", f"/resource-orders/{order_id}/submit", {}, headers)

    def create_assignment(self, order_id, payload, headers):
        return self._request("POST", f"/resource-orders/{order_id}/assignments", payload, headers)

    def list_order_assignments(self, order_id, headers, params=None):
        return self._request("GET", f"/resource-orders/{order_id}/assignments", headers=headers, params=params)

    def confirm_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/confirm", {}, headers)

    def decline_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/decline", {}, headers)

    def release_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/release", {}, headers)

    def mark_assignment_no_show(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/mark-no-show", {}, headers)

    # --- Burn executions ---
    def create_execution(self, plan_id, payload, headers):
        return self._request("POST", f"/burn-plans/{plan_id}/executions", payload, headers)

    def get_execution(self, execution_id, headers):
        return self._request("GET", f"/executions/{execution_id}", headers=headers)

    def list_plan_executions(self, plan_id, headers, params=None):
        return self._request("GET", f"/burn-plans/{plan_id}/executions", headers=headers, params=params)

    def cancel_execution(self, execution_id, headers):
        return self._request("POST", f"/executions/{execution_id}/cancel", {}, headers)

    def brief_execution(self, execution_id, headers):
        return self._request("POST", f"/executions/{execution_id}/brief", {}, headers)

    def create_weather_observation(self, execution_id, payload, headers):
        return self._request("POST", f"/executions/{execution_id}/weather-observations", payload, headers)

    def list_weather_observations(self, execution_id, headers, params=None):
        return self._request("GET", f"/executions/{execution_id}/weather-observations", headers=headers, params=params)

    def submit_go_no_go(self, execution_id, payload, headers):
        return self._request("POST", f"/executions/{execution_id}/go-no-go", payload, headers)

    def list_checklists(self, execution_id, headers, params=None):
        return self._request("GET", f"/executions/{execution_id}/checklists", headers=headers, params=params)

    def start_ignition(self, execution_id, headers):
        return self._request("POST", f"/executions/{execution_id}/start-ignition", {}, headers)

    def complete_ignition(self, execution_id, payload, headers):
        return self._request("POST", f"/executions/{execution_id}/complete-ignition", payload, headers)

    def begin_patrol(self, execution_id, headers):
        return self._request("POST", f"/executions/{execution_id}/begin-patrol", {}, headers)

    def begin_mop_up(self, execution_id, headers):
        return self._request("POST", f"/executions/{execution_id}/begin-mop-up", {}, headers)

    def close_execution(self, execution_id, payload, headers):
        return self._request("POST", f"/executions/{execution_id}/close", payload, headers)

    def stand_down_execution(self, execution_id, headers):
        return self._request("POST", f"/executions/{execution_id}/stand-down", {}, headers)

    def declare_escape(self, execution_id, headers):
        return self._request("POST", f"/executions/{execution_id}/declare-escape", {}, headers)

    # --- Incidents ---
    def report_incident(self, execution_id, payload, headers):
        return self._request("POST", f"/executions/{execution_id}/incidents", payload, headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/incidents/{incident_id}", headers=headers)

    def list_execution_incidents(self, execution_id, headers, params=None):
        return self._request("GET", f"/executions/{execution_id}/incidents", headers=headers, params=params)

    def confirm_incident(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/confirm", {}, headers)

    def dismiss_incident(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/dismiss", {}, headers)

    def declare_incident_wildfire(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/declare-wildfire", {}, headers)

    def mark_incident_contained(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/mark-contained", {}, headers)

    def close_incident(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/close", {}, headers)

    def assess_incident_costs(self, incident_id, payload, headers):
        return self._request("POST", f"/incidents/{incident_id}/assess-costs", payload, headers)

    # --- Monitoring reports ---
    def get_monitoring_report(self, report_id, headers):
        return self._request("GET", f"/monitoring-reports/{report_id}", headers=headers)

    def list_execution_monitoring_reports(self, execution_id, headers, params=None):
        return self._request("GET", f"/executions/{execution_id}/monitoring-reports", headers=headers, params=params)

    def submit_monitoring_report(self, report_id, payload, headers):
        return self._request("POST", f"/monitoring-reports/{report_id}/submit", payload, headers)

    def accept_monitoring_report(self, report_id, headers):
        return self._request("POST", f"/monitoring-reports/{report_id}/accept", {}, headers)

    def mark_report_deficient(self, report_id, payload, headers):
        return self._request("POST", f"/monitoring-reports/{report_id}/mark-deficient", payload, headers)

    # --- Cost-share agreements ---
    def create_cost_share_agreement(self, payload, headers):
        return self._request("POST", "/cost-share-agreements", payload, headers)

    def get_cost_share_agreement(self, agreement_id, headers):
        return self._request("GET", f"/cost-share-agreements/{agreement_id}", headers=headers)

    def list_cost_share_agreements(self, headers, params=None):
        return self._request("GET", "/cost-share-agreements", headers=headers, params=params)

    def begin_agreement_review(self, agreement_id, headers):
        return self._request("POST", f"/cost-share-agreements/{agreement_id}/begin-review", {}, headers)

    def approve_agreement(self, agreement_id, headers):
        return self._request("POST", f"/cost-share-agreements/{agreement_id}/approve", {}, headers)

    def deny_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/cost-share-agreements/{agreement_id}/deny", payload, headers)

    def disburse_agreement(self, agreement_id, headers):
        return self._request("POST", f"/cost-share-agreements/{agreement_id}/disburse", {}, headers)

    def reinstate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/cost-share-agreements/{agreement_id}/reinstate", {}, headers)

    def cancel_agreement(self, agreement_id, headers):
        return self._request("POST", f"/cost-share-agreements/{agreement_id}/cancel", {}, headers)

    # --- Liability claims ---
    def create_liability_claim(self, incident_id, payload, headers):
        return self._request("POST", f"/incidents/{incident_id}/liability-claims", payload, headers)

    def get_liability_claim(self, claim_id, headers):
        return self._request("GET", f"/liability-claims/{claim_id}", headers=headers)

    def list_incident_liability_claims(self, incident_id, headers, params=None):
        return self._request("GET", f"/incidents/{incident_id}/liability-claims", headers=headers, params=params)

    def begin_claim_investigation(self, claim_id, headers):
        return self._request("POST", f"/liability-claims/{claim_id}/begin-investigation", {}, headers)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/liability-claims/{claim_id}/adjudicate", payload, headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/liability-claims/{claim_id}/pay", {}, headers)

    def reverse_claim_payment(self, claim_id, headers):
        return self._request("POST", f"/liability-claims/{claim_id}/reverse-payment", {}, headers)

    def close_claim(self, claim_id, headers):
        return self._request("POST", f"/liability-claims/{claim_id}/close", {}, headers)


api_client = ApiClient()
