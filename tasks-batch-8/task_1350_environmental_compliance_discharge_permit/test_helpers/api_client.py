"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Permits ---
    def create_permit(self, payload, headers):
        return self._request("POST", "/npdes/permits", payload, headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/npdes/permits", headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/npdes/permits/{permit_id}", headers=headers)

    def issue_permit(self, permit_id, headers):
        return self._request("POST", f"/npdes/permits/{permit_id}/issue", headers=headers)

    def terminate_permit(self, permit_id, headers):
        return self._request("POST", f"/npdes/permits/{permit_id}/terminate", headers=headers)

    # --- Outfalls ---
    def create_outfall(self, payload, headers):
        return self._request("POST", "/npdes/outfalls", payload, headers)

    def list_outfalls(self, headers, params=None):
        return self._request("GET", "/npdes/outfalls", headers=headers, params=params)

    def get_outfall(self, outfall_id, headers):
        return self._request("GET", f"/npdes/outfalls/{outfall_id}", headers=headers)

    def deactivate_outfall(self, outfall_id, headers):
        return self._request("POST", f"/npdes/outfalls/{outfall_id}/deactivate", headers=headers)

    def reactivate_outfall(self, outfall_id, headers):
        return self._request("POST", f"/npdes/outfalls/{outfall_id}/reactivate", headers=headers)

    # --- Effluent limits ---
    def create_effluent_limit(self, payload, headers):
        return self._request("POST", "/npdes/effluent-limits", payload, headers)

    def list_effluent_limits(self, headers, params=None):
        return self._request("GET", "/npdes/effluent-limits", headers=headers, params=params)

    def get_effluent_limit(self, limit_id, headers):
        return self._request("GET", f"/npdes/effluent-limits/{limit_id}", headers=headers)

    def rescind_effluent_limit(self, limit_id, headers):
        return self._request("POST", f"/npdes/effluent-limits/{limit_id}/rescind", headers=headers)

    # --- Sampling events & custody ---
    def create_sampling_event(self, payload, headers):
        return self._request("POST", "/npdes/sampling-events", payload, headers)

    def list_sampling_events(self, headers, params=None):
        return self._request("GET", "/npdes/sampling-events", headers=headers, params=params)

    def get_sampling_event(self, event_id, headers):
        return self._request("GET", f"/npdes/sampling-events/{event_id}", headers=headers)

    def collect_sampling_event(self, event_id, headers):
        return self._request("POST", f"/npdes/sampling-events/{event_id}/collect", headers=headers)

    def cancel_sampling_event(self, event_id, headers):
        return self._request("POST", f"/npdes/sampling-events/{event_id}/cancel", headers=headers)

    def append_custody_event(self, event_id, payload, headers):
        return self._request("POST", f"/npdes/sampling-events/{event_id}/custody-events", payload, headers)

    def list_custody_events(self, event_id, headers):
        return self._request("GET", f"/npdes/sampling-events/{event_id}/custody-events", headers=headers)

    # --- Lab results ---
    def create_lab_result(self, payload, headers):
        return self._request("POST", "/npdes/lab-results", payload, headers)

    def list_lab_results(self, headers, params=None):
        return self._request("GET", "/npdes/lab-results", headers=headers, params=params)

    def get_lab_result(self, result_id, headers):
        return self._request("GET", f"/npdes/lab-results/{result_id}", headers=headers)

    def validate_lab_result(self, result_id, headers):
        return self._request("POST", f"/npdes/lab-results/{result_id}/validate", headers=headers)

    def reject_lab_result(self, result_id, payload, headers):
        return self._request("POST", f"/npdes/lab-results/{result_id}/reject", payload, headers)

    def resubmit_lab_result(self, result_id, payload, headers):
        return self._request("POST", f"/npdes/lab-results/{result_id}/resubmit", payload, headers)

    # --- Exceedances ---
    def list_exceedances(self, headers, params=None):
        return self._request("GET", "/npdes/exceedances", headers=headers, params=params)

    def get_exceedance(self, exceedance_id, headers):
        return self._request("GET", f"/npdes/exceedances/{exceedance_id}", headers=headers)

    def notify_exceedance(self, exceedance_id, headers):
        return self._request("POST", f"/npdes/exceedances/{exceedance_id}/notify", headers=headers)

    def file_exceedance_report(self, exceedance_id, payload, headers):
        return self._request("POST", f"/npdes/exceedances/{exceedance_id}/file-report", payload, headers)

    def close_exceedance(self, exceedance_id, headers):
        return self._request("POST", f"/npdes/exceedances/{exceedance_id}/close", headers=headers)

    # --- DMRs ---
    def create_dmr(self, payload, headers):
        return self._request("POST", "/npdes/dmrs", payload, headers)

    def list_dmrs(self, headers, params=None):
        return self._request("GET", "/npdes/dmrs", headers=headers, params=params)

    def get_dmr(self, dmr_id, headers):
        return self._request("GET", f"/npdes/dmrs/{dmr_id}", headers=headers)

    def certify_dmr(self, dmr_id, headers):
        return self._request("POST", f"/npdes/dmrs/{dmr_id}/certify", headers=headers)

    def submit_dmr(self, dmr_id, headers):
        return self._request("POST", f"/npdes/dmrs/{dmr_id}/submit", headers=headers)

    def review_dmr(self, dmr_id, payload, headers):
        return self._request("POST", f"/npdes/dmrs/{dmr_id}/agency-review", payload, headers)

    def revise_dmr(self, dmr_id, headers):
        return self._request("POST", f"/npdes/dmrs/{dmr_id}/revise", headers=headers)

    # --- SWPPP plans & inspections ---
    def create_swppp_plan(self, payload, headers):
        return self._request("POST", "/npdes/swppp-plans", payload, headers)

    def list_swppp_plans(self, headers, params=None):
        return self._request("GET", "/npdes/swppp-plans", headers=headers, params=params)

    def get_swppp_plan(self, plan_id, headers):
        return self._request("GET", f"/npdes/swppp-plans/{plan_id}", headers=headers)

    def activate_swppp_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/npdes/swppp-plans/{plan_id}/activate", payload, headers)

    def create_inspection(self, payload, headers):
        return self._request("POST", "/npdes/inspections", payload, headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/npdes/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/npdes/inspections/{inspection_id}", headers=headers)

    def complete_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/npdes/inspections/{inspection_id}/complete", payload, headers)

    def cancel_inspection(self, inspection_id, headers):
        return self._request("POST", f"/npdes/inspections/{inspection_id}/cancel", headers=headers)

    # --- Corrective actions ---
    def list_corrective_actions(self, headers, params=None):
        return self._request("GET", "/npdes/corrective-actions", headers=headers, params=params)

    def get_corrective_action(self, action_id, headers):
        return self._request("GET", f"/npdes/corrective-actions/{action_id}", headers=headers)

    def start_corrective_action(self, action_id, headers):
        return self._request("POST", f"/npdes/corrective-actions/{action_id}/start", headers=headers)

    def complete_corrective_action(self, action_id, payload, headers):
        return self._request("POST", f"/npdes/corrective-actions/{action_id}/complete", payload, headers)

    def verify_corrective_action(self, action_id, headers):
        return self._request("POST", f"/npdes/corrective-actions/{action_id}/verify", headers=headers)

    def reopen_corrective_action(self, action_id, payload, headers):
        return self._request("POST", f"/npdes/corrective-actions/{action_id}/reopen", payload, headers)

    def close_corrective_action(self, action_id, headers):
        return self._request("POST", f"/npdes/corrective-actions/{action_id}/close", headers=headers)

    # --- Renewal applications ---
    def create_renewal_application(self, payload, headers):
        return self._request("POST", "/npdes/renewal-applications", payload, headers)

    def list_renewal_applications(self, headers, params=None):
        return self._request("GET", "/npdes/renewal-applications", headers=headers, params=params)

    def get_renewal_application(self, renewal_id, headers):
        return self._request("GET", f"/npdes/renewal-applications/{renewal_id}", headers=headers)

    def start_renewal_review(self, renewal_id, headers):
        return self._request("POST", f"/npdes/renewal-applications/{renewal_id}/start-review", headers=headers)

    def request_renewal_info(self, renewal_id, payload, headers):
        return self._request("POST", f"/npdes/renewal-applications/{renewal_id}/request-info", payload, headers)

    def resume_renewal_review(self, renewal_id, headers):
        return self._request("POST", f"/npdes/renewal-applications/{renewal_id}/resume-review", headers=headers)

    def approve_renewal(self, renewal_id, payload, headers):
        return self._request("POST", f"/npdes/renewal-applications/{renewal_id}/approve", payload, headers)

    def deny_renewal(self, renewal_id, payload, headers):
        return self._request("POST", f"/npdes/renewal-applications/{renewal_id}/deny", payload, headers)

    # --- Consent orders & penalty ledger ---
    def create_consent_order(self, payload, headers):
        return self._request("POST", "/npdes/consent-orders", payload, headers)

    def list_consent_orders(self, headers, params=None):
        return self._request("GET", "/npdes/consent-orders", headers=headers, params=params)

    def get_consent_order(self, order_id, headers):
        return self._request("GET", f"/npdes/consent-orders/{order_id}", headers=headers)

    def issue_consent_order(self, order_id, headers):
        return self._request("POST", f"/npdes/consent-orders/{order_id}/issue", headers=headers)

    def appeal_consent_order(self, order_id, payload, headers):
        return self._request("POST", f"/npdes/consent-orders/{order_id}/appeal", payload, headers)

    def finalize_consent_order(self, order_id, headers):
        return self._request("POST", f"/npdes/consent-orders/{order_id}/finalize", headers=headers)

    def post_payment(self, order_id, payload, headers):
        return self._request("POST", f"/npdes/consent-orders/{order_id}/payments", payload, headers)

    def list_payments(self, order_id, headers):
        return self._request("GET", f"/npdes/consent-orders/{order_id}/payments", headers=headers)

    # --- Audit chain & logical clock ---
    def list_audit_entries(self, headers, params=None):
        return self._request("GET", "/npdes/audit-entries", headers=headers, params=params)

    def set_clock(self, payload, headers):
        return self._request("POST", "/npdes/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
