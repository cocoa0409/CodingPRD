"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Physicians ---
    def create_physician(self, payload, headers):
        return self._request("POST", "/onboarding/physicians", payload, headers)

    def get_physician(self, physician_id, headers):
        return self._request("GET", f"/onboarding/physicians/{physician_id}", headers=headers)

    def list_physicians(self, headers, params=None):
        return self._request("GET", "/onboarding/physicians", headers=headers, params=params)

    def separate_physician(self, physician_id, payload, headers):
        return self._request("POST", f"/onboarding/physicians/{physician_id}/separate", payload, headers)

    def mark_physician_active(self, physician_id, headers):
        return self._request("POST", f"/onboarding/physicians/{physician_id}/mark-active", {}, headers)

    # --- Onboarding cases ---
    def create_onboarding_case(self, payload, headers):
        return self._request("POST", "/onboarding/onboarding-cases", payload, headers)

    def get_onboarding_case(self, case_id, headers):
        return self._request("GET", f"/onboarding/onboarding-cases/{case_id}", headers=headers)

    def list_onboarding_cases(self, headers, params=None):
        return self._request("GET", "/onboarding/onboarding-cases", headers=headers, params=params)

    # --- Offers ---
    def create_offer(self, payload, headers):
        return self._request("POST", "/onboarding/offers", payload, headers)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/onboarding/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/onboarding/offers", headers=headers, params=params)

    def extend_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/onboarding/offers/{offer_id}/extend", payload, headers)

    def counter_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/onboarding/offers/{offer_id}/counter", payload, headers)

    def accept_offer(self, offer_id, headers):
        return self._request("POST", f"/onboarding/offers/{offer_id}/accept", {}, headers)

    def execute_offer(self, offer_id, headers):
        return self._request("POST", f"/onboarding/offers/{offer_id}/execute", {}, headers)

    def withdraw_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/onboarding/offers/{offer_id}/withdraw", payload, headers)

    def decline_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/onboarding/offers/{offer_id}/decline", payload, headers)

    # --- Credential items ---
    def create_credential_item(self, payload, headers):
        return self._request("POST", "/onboarding/credential-items", payload, headers)

    def get_credential_item(self, item_id, headers):
        return self._request("GET", f"/onboarding/credential-items/{item_id}", headers=headers)

    def list_credential_items(self, headers, params=None):
        return self._request("GET", "/onboarding/credential-items", headers=headers, params=params)

    def submit_credential_docs(self, item_id, payload, headers):
        return self._request("POST", f"/onboarding/credential-items/{item_id}/submit-docs", payload, headers)

    def verify_credential_item(self, item_id, payload, headers):
        return self._request("POST", f"/onboarding/credential-items/{item_id}/verify", payload, headers)

    def file_credential_item(self, item_id, payload, headers):
        return self._request("POST", f"/onboarding/credential-items/{item_id}/file", payload, headers)

    def approve_credential_item(self, item_id, headers):
        return self._request("POST", f"/onboarding/credential-items/{item_id}/approve", {}, headers)

    def reject_credential_item(self, item_id, payload, headers):
        return self._request("POST", f"/onboarding/credential-items/{item_id}/reject", payload, headers)

    # --- Training ---
    def get_training_plan(self, plan_id, headers):
        return self._request("GET", f"/onboarding/training-plans/{plan_id}", headers=headers)

    def list_training_plans(self, headers, params=None):
        return self._request("GET", "/onboarding/training-plans", headers=headers, params=params)

    def signoff_training_plan(self, plan_id, headers):
        return self._request("POST", f"/onboarding/training-plans/{plan_id}/signoff", {}, headers)

    def create_training_module(self, payload, headers):
        return self._request("POST", "/onboarding/training-modules", payload, headers)

    def get_training_module(self, module_id, headers):
        return self._request("GET", f"/onboarding/training-modules/{module_id}", headers=headers)

    def list_training_modules(self, headers, params=None):
        return self._request("GET", "/onboarding/training-modules", headers=headers, params=params)

    def schedule_training_module(self, module_id, payload, headers):
        return self._request("POST", f"/onboarding/training-modules/{module_id}/schedule", payload, headers)

    def complete_training_module(self, module_id, payload, headers):
        return self._request("POST", f"/onboarding/training-modules/{module_id}/complete", payload, headers)

    # --- Schedule templates ---
    def create_schedule_template(self, payload, headers):
        return self._request("POST", "/onboarding/schedule-templates", payload, headers)

    def get_schedule_template(self, template_id, headers):
        return self._request("GET", f"/onboarding/schedule-templates/{template_id}", headers=headers)

    def list_schedule_templates(self, headers, params=None):
        return self._request("GET", "/onboarding/schedule-templates", headers=headers, params=params)

    def activate_schedule_template(self, template_id, headers):
        return self._request("POST", f"/onboarding/schedule-templates/{template_id}/activate", {}, headers)

    def retire_schedule_template(self, template_id, headers):
        return self._request("POST", f"/onboarding/schedule-templates/{template_id}/retire", {}, headers)

    # --- Panels ---
    def get_panel(self, panel_id, headers):
        return self._request("GET", f"/onboarding/panels/{panel_id}", headers=headers)

    def list_panels(self, headers, params=None):
        return self._request("GET", "/onboarding/panels", headers=headers, params=params)

    def open_panel(self, panel_id, headers):
        return self._request("POST", f"/onboarding/panels/{panel_id}/open", {}, headers)

    def freeze_panel(self, panel_id, headers):
        return self._request("POST", f"/onboarding/panels/{panel_id}/freeze", {}, headers)

    def unfreeze_panel(self, panel_id, headers):
        return self._request("POST", f"/onboarding/panels/{panel_id}/unfreeze", {}, headers)

    def adjust_panel_census(self, panel_id, payload, headers):
        return self._request("POST", f"/onboarding/panels/{panel_id}/census-adjustments", payload, headers)

    # --- Referral campaigns ---
    def create_referral_campaign(self, payload, headers):
        return self._request("POST", "/onboarding/referral-campaigns", payload, headers)

    def get_referral_campaign(self, campaign_id, headers):
        return self._request("GET", f"/onboarding/referral-campaigns/{campaign_id}", headers=headers)

    def list_referral_campaigns(self, headers, params=None):
        return self._request("GET", "/onboarding/referral-campaigns", headers=headers, params=params)

    def activate_referral_campaign(self, campaign_id, headers):
        return self._request("POST", f"/onboarding/referral-campaigns/{campaign_id}/activate", {}, headers)

    def complete_referral_campaign(self, campaign_id, headers):
        return self._request("POST", f"/onboarding/referral-campaigns/{campaign_id}/complete", {}, headers)

    # --- Campaign events ---
    def create_campaign_event(self, payload, headers):
        return self._request("POST", "/onboarding/campaign-events", payload, headers)

    def get_campaign_event(self, event_id, headers):
        return self._request("GET", f"/onboarding/campaign-events/{event_id}", headers=headers)

    def list_campaign_events(self, headers, params=None):
        return self._request("GET", "/onboarding/campaign-events", headers=headers, params=params)

    def hold_campaign_event(self, event_id, payload, headers):
        return self._request("POST", f"/onboarding/campaign-events/{event_id}/hold", payload, headers)

    def cancel_campaign_event(self, event_id, headers):
        return self._request("POST", f"/onboarding/campaign-events/{event_id}/cancel", {}, headers)

    # --- Income guarantees ---
    def get_income_guarantee(self, guarantee_id, headers):
        return self._request("GET", f"/onboarding/income-guarantees/{guarantee_id}", headers=headers)

    def list_income_guarantees(self, headers, params=None):
        return self._request("GET", "/onboarding/income-guarantees", headers=headers, params=params)

    def activate_income_guarantee(self, guarantee_id, headers):
        return self._request("POST", f"/onboarding/income-guarantees/{guarantee_id}/activate", {}, headers)

    def reconcile_income_guarantee(self, guarantee_id, headers):
        return self._request("POST", f"/onboarding/income-guarantees/{guarantee_id}/reconcile", {}, headers)

    def post_guarantee_repayment(self, guarantee_id, payload, headers):
        return self._request("POST", f"/onboarding/income-guarantees/{guarantee_id}/repayments", payload, headers)

    # --- Ramp milestones ---
    def get_ramp_milestone(self, milestone_id, headers):
        return self._request("GET", f"/onboarding/ramp-milestones/{milestone_id}", headers=headers)

    def list_ramp_milestones(self, headers, params=None):
        return self._request("GET", "/onboarding/ramp-milestones", headers=headers, params=params)

    def report_ramp_milestone(self, milestone_id, payload, headers):
        return self._request("POST", f"/onboarding/ramp-milestones/{milestone_id}/report", payload, headers)

    def attest_ramp_milestone(self, milestone_id, headers):
        return self._request("POST", f"/onboarding/ramp-milestones/{milestone_id}/attest", {}, headers)

    # --- Mentorship & check-ins ---
    def create_mentorship_assignment(self, payload, headers):
        return self._request("POST", "/onboarding/mentorship-assignments", payload, headers)

    def get_mentorship_assignment(self, assignment_id, headers):
        return self._request("GET", f"/onboarding/mentorship-assignments/{assignment_id}", headers=headers)

    def list_mentorship_assignments(self, headers, params=None):
        return self._request("GET", "/onboarding/mentorship-assignments", headers=headers, params=params)

    def complete_mentorship_assignment(self, assignment_id, headers):
        return self._request("POST", f"/onboarding/mentorship-assignments/{assignment_id}/complete", {}, headers)

    def record_check_in(self, assignment_id, payload, headers):
        return self._request("POST", f"/onboarding/mentorship-assignments/{assignment_id}/check-ins", payload, headers)

    def list_check_ins(self, assignment_id, headers, params=None):
        return self._request("GET", f"/onboarding/mentorship-assignments/{assignment_id}/check-ins", headers=headers, params=params)

    # --- Retention risk snapshots ---
    def create_retention_snapshot(self, payload, headers):
        return self._request("POST", "/onboarding/retention-snapshots", payload, headers)

    def get_retention_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/onboarding/retention-snapshots/{snapshot_id}", headers=headers)

    def list_retention_snapshots(self, headers, params=None):
        return self._request("GET", "/onboarding/retention-snapshots", headers=headers, params=params)

    # --- Operator surface ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def run_epoch(self, headers):
        return self._request("POST", "/_ops/run_epoch", {}, headers)


api_client = ApiClient()
