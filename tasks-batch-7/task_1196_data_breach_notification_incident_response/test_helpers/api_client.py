"""API client: one method per endpoint defined in PRD §4."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_current_utc(self, to_iso8601: str, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ------------------------------------------------------------------
    # Incidents
    # ------------------------------------------------------------------
    def create_incident(self, payload, headers):
        return self._request("POST", "/incidents", payload, headers)

    def list_incidents(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/incidents/{incident_id}", headers=headers)

    def confirm_incident(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/confirm", {}, headers)

    def contain_incident(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/contain", {}, headers)

    def close_incident(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Forensic scopes
    # ------------------------------------------------------------------
    def create_forensic_scope(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/incidents/{incident_id}/forensic-scopes", payload, headers,
        )

    def list_forensic_scopes(self, incident_id, headers, params=None):
        return self._request(
            "GET", f"/incidents/{incident_id}/forensic-scopes",
            headers=headers, params=params,
        )

    def get_forensic_scope(self, incident_id, scope_id, headers):
        return self._request(
            "GET", f"/incidents/{incident_id}/forensic-scopes/{scope_id}",
            headers=headers,
        )

    def baseline_forensic_scope(self, incident_id, scope_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/forensic-scopes/{scope_id}/baseline",
            {}, headers,
        )

    def amend_forensic_scope(self, incident_id, scope_id, payload, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/forensic-scopes/{scope_id}/amend",
            payload, headers,
        )

    def re_baseline_forensic_scope(self, incident_id, scope_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/forensic-scopes/{scope_id}/re-baseline",
            {}, headers,
        )

    def finalize_forensic_scope(self, incident_id, scope_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/forensic-scopes/{scope_id}/finalize",
            {}, headers,
        )

    # ------------------------------------------------------------------
    # Evidence items
    # ------------------------------------------------------------------
    def create_evidence_item(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/incidents/{incident_id}/evidence-items", payload, headers,
        )

    def list_evidence_items(self, incident_id, headers, params=None):
        return self._request(
            "GET", f"/incidents/{incident_id}/evidence-items",
            headers=headers, params=params,
        )

    def get_evidence_item(self, incident_id, item_id, headers):
        return self._request(
            "GET", f"/incidents/{incident_id}/evidence-items/{item_id}",
            headers=headers,
        )

    def seal_evidence_item(self, incident_id, item_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/evidence-items/{item_id}/seal",
            {}, headers,
        )

    def release_evidence_item(self, incident_id, item_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/evidence-items/{item_id}/release",
            {}, headers,
        )

    def destroy_evidence_item(self, incident_id, item_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/evidence-items/{item_id}/destroy",
            {}, headers,
        )

    # ------------------------------------------------------------------
    # Custody logs
    # ------------------------------------------------------------------
    def create_custody_log(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/incidents/{incident_id}/custody-logs", payload, headers,
        )

    def list_custody_logs(self, incident_id, headers, params=None):
        return self._request(
            "GET", f"/incidents/{incident_id}/custody-logs",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Affected subjects
    # ------------------------------------------------------------------
    def create_affected_subject(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/incidents/{incident_id}/affected-subjects", payload, headers,
        )

    def list_affected_subjects(self, incident_id, headers, params=None):
        return self._request(
            "GET", f"/incidents/{incident_id}/affected-subjects",
            headers=headers, params=params,
        )

    def get_affected_subject(self, incident_id, subject_id, headers):
        return self._request(
            "GET", f"/incidents/{incident_id}/affected-subjects/{subject_id}",
            headers=headers,
        )

    def verify_affected_subject(self, incident_id, subject_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/affected-subjects/{subject_id}/verify",
            {}, headers,
        )

    def exclude_affected_subject(self, incident_id, subject_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/affected-subjects/{subject_id}/exclude",
            {}, headers,
        )

    # ------------------------------------------------------------------
    # Jurisdiction evaluations
    # ------------------------------------------------------------------
    def create_jurisdiction_evaluation(self, incident_id, payload, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/jurisdiction-evaluations",
            payload, headers,
        )

    def list_jurisdiction_evaluations(self, incident_id, headers, params=None):
        return self._request(
            "GET", f"/incidents/{incident_id}/jurisdiction-evaluations",
            headers=headers, params=params,
        )

    def get_jurisdiction_evaluation(self, incident_id, evaluation_id, headers):
        return self._request(
            "GET",
            f"/incidents/{incident_id}/jurisdiction-evaluations/{evaluation_id}",
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Notices
    # ------------------------------------------------------------------
    def create_notice(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/incidents/{incident_id}/notices", payload, headers,
        )

    def list_notices(self, incident_id, headers, params=None):
        return self._request(
            "GET", f"/incidents/{incident_id}/notices",
            headers=headers, params=params,
        )

    def get_notice(self, incident_id, notice_id, headers):
        return self._request(
            "GET", f"/incidents/{incident_id}/notices/{notice_id}",
            headers=headers,
        )

    def submit_notice_for_review(self, incident_id, notice_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/notices/{notice_id}/submit-for-review",
            {}, headers,
        )

    def approve_notice(self, incident_id, notice_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/notices/{notice_id}/approve",
            {}, headers,
        )

    def request_changes_notice(self, incident_id, notice_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/notices/{notice_id}/request-changes",
            {}, headers,
        )

    def lock_notice_for_mail(self, incident_id, notice_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/notices/{notice_id}/lock-for-mail",
            {}, headers,
        )

    # ------------------------------------------------------------------
    # Mailing batches
    # ------------------------------------------------------------------
    def create_mailing_batch(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/incidents/{incident_id}/mailing-batches", payload, headers,
        )

    def list_mailing_batches(self, incident_id, headers, params=None):
        return self._request(
            "GET", f"/incidents/{incident_id}/mailing-batches",
            headers=headers, params=params,
        )

    def get_mailing_batch(self, incident_id, batch_id, headers):
        return self._request(
            "GET", f"/incidents/{incident_id}/mailing-batches/{batch_id}",
            headers=headers,
        )

    def start_production_mailing_batch(self, incident_id, batch_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/mailing-batches/{batch_id}/start-production",
            {}, headers,
        )

    def mark_shipped_mailing_batch(self, incident_id, batch_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/mailing-batches/{batch_id}/mark-shipped",
            {}, headers,
        )

    def confirm_delivery_mailing_batch(self, incident_id, batch_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/mailing-batches/{batch_id}/confirm-delivery",
            {}, headers,
        )

    def fail_mailing_batch(self, incident_id, batch_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/mailing-batches/{batch_id}/fail",
            {}, headers,
        )

    # ------------------------------------------------------------------
    # Credit-monitoring offers
    # ------------------------------------------------------------------
    def create_credit_monitoring_offer(self, incident_id, payload, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/credit-monitoring-offers",
            payload, headers,
        )

    def list_credit_monitoring_offers(self, incident_id, headers, params=None):
        return self._request(
            "GET", f"/incidents/{incident_id}/credit-monitoring-offers",
            headers=headers, params=params,
        )

    def get_credit_monitoring_offer(self, incident_id, offer_id, headers):
        return self._request(
            "GET",
            f"/incidents/{incident_id}/credit-monitoring-offers/{offer_id}",
            headers=headers,
        )

    def redeem_credit_monitoring_offer(self, incident_id, offer_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/credit-monitoring-offers/{offer_id}/redeem",
            {}, headers,
        )

    def decline_credit_monitoring_offer(self, incident_id, offer_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/credit-monitoring-offers/{offer_id}/decline",
            {}, headers,
        )

    def cancel_credit_monitoring_offer(self, incident_id, offer_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/credit-monitoring-offers/{offer_id}/cancel",
            {}, headers,
        )

    # ------------------------------------------------------------------
    # Call-center staffing plans
    # ------------------------------------------------------------------
    def create_call_center_staffing_plan(self, incident_id, payload, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/call-center-staffing-plans",
            payload, headers,
        )

    def list_call_center_staffing_plans(self, incident_id, headers, params=None):
        return self._request(
            "GET",
            f"/incidents/{incident_id}/call-center-staffing-plans",
            headers=headers, params=params,
        )

    def get_call_center_staffing_plan(self, incident_id, plan_id, headers):
        return self._request(
            "GET",
            f"/incidents/{incident_id}/call-center-staffing-plans/{plan_id}",
            headers=headers,
        )

    def close_call_center_staffing_plan(self, incident_id, plan_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/call-center-staffing-plans/{plan_id}/close",
            {}, headers,
        )

    # ------------------------------------------------------------------
    # Regulator submissions
    # ------------------------------------------------------------------
    def create_regulator_submission(self, incident_id, payload, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/regulator-submissions",
            payload, headers,
        )

    def list_regulator_submissions(self, incident_id, headers, params=None):
        return self._request(
            "GET", f"/incidents/{incident_id}/regulator-submissions",
            headers=headers, params=params,
        )

    def get_regulator_submission(self, incident_id, sub_id, headers):
        return self._request(
            "GET",
            f"/incidents/{incident_id}/regulator-submissions/{sub_id}",
            headers=headers,
        )

    def submit_regulator_submission(self, incident_id, sub_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/regulator-submissions/{sub_id}/submit",
            {}, headers,
        )

    def acknowledge_regulator_submission(self, incident_id, sub_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/regulator-submissions/{sub_id}/acknowledge",
            {}, headers,
        )

    def open_inquiry_regulator_submission(self, incident_id, sub_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/regulator-submissions/{sub_id}/open-inquiry",
            {}, headers,
        )

    def respond_inquiry_regulator_submission(self, incident_id, sub_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/regulator-submissions/{sub_id}/respond-inquiry",
            {}, headers,
        )

    def close_regulator_submission(self, incident_id, sub_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/regulator-submissions/{sub_id}/close",
            {}, headers,
        )

    # ------------------------------------------------------------------
    # Remediation actions
    # ------------------------------------------------------------------
    def create_remediation_action(self, incident_id, payload, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/remediation-actions",
            payload, headers,
        )

    def list_remediation_actions(self, incident_id, headers, params=None):
        return self._request(
            "GET", f"/incidents/{incident_id}/remediation-actions",
            headers=headers, params=params,
        )

    def get_remediation_action(self, incident_id, action_id, headers):
        return self._request(
            "GET",
            f"/incidents/{incident_id}/remediation-actions/{action_id}",
            headers=headers,
        )

    def start_remediation_action(self, incident_id, action_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/remediation-actions/{action_id}/start",
            {}, headers,
        )

    def complete_remediation_action(self, incident_id, action_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/remediation-actions/{action_id}/complete",
            {}, headers,
        )

    def verify_remediation_action(self, incident_id, action_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/remediation-actions/{action_id}/verify",
            {}, headers,
        )

    def cancel_remediation_action(self, incident_id, action_id, headers):
        return self._request(
            "POST",
            f"/incidents/{incident_id}/remediation-actions/{action_id}/cancel",
            {}, headers,
        )

    # ------------------------------------------------------------------
    # Cost summary (computed read)
    # ------------------------------------------------------------------
    def get_cost_summary(self, incident_id, headers):
        return self._request(
            "GET", f"/incidents/{incident_id}/cost-summary", headers=headers,
        )


api_client = ApiClient()
