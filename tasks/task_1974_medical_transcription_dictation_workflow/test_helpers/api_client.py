"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- ClinicAccount ---
    def create_clinic_account(self, payload, headers):
        return self._request("POST", "/clinic-accounts", payload, headers)

    def get_clinic_account(self, clinic_id, headers):
        return self._request("GET", f"/clinic-accounts/{clinic_id}", headers=headers)

    def list_clinic_providers(self, clinic_id, headers):
        return self._request("GET", f"/clinic-accounts/{clinic_id}/providers", headers=headers)

    def list_clinic_sla_policies(self, clinic_id, headers):
        return self._request("GET", f"/clinic-accounts/{clinic_id}/sla-policies", headers=headers)

    def list_clinic_billing_periods(self, clinic_id, headers):
        return self._request("GET", f"/clinic-accounts/{clinic_id}/billing-periods", headers=headers)

    # --- SLAPolicy ---
    def create_sla_policy(self, payload, headers):
        return self._request("POST", "/sla-policies", payload, headers)

    # --- Provider ---
    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    def reinstate_provider(self, provider_id, headers):
        return self._request("POST", f"/providers/{provider_id}/reinstate", headers=headers)

    def list_provider_templates(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}/templates", headers=headers)

    def list_provider_macros(self, provider_id, headers, params=None):
        return self._request("GET", f"/providers/{provider_id}/macros", headers=headers, params=params)

    # --- Editor ---
    def create_editor(self, payload, headers):
        return self._request("POST", "/editors", payload, headers)

    def get_editor(self, editor_id, headers):
        return self._request("GET", f"/editors/{editor_id}", headers=headers)

    def reinstate_editor(self, editor_id, headers):
        return self._request("POST", f"/editors/{editor_id}/reinstate", headers=headers)

    def list_editor_shift_windows(self, editor_id, headers):
        return self._request("GET", f"/editors/{editor_id}/shift-windows", headers=headers)

    def create_editor_shift_window(self, payload, headers):
        return self._request("POST", "/editor-shift-windows", payload, headers)

    # --- DictationJob ---
    def create_dictation_job(self, payload, headers):
        return self._request("POST", "/dictation-jobs", payload, headers)

    def get_dictation_job(self, job_id, headers):
        return self._request("GET", f"/dictation-jobs/{job_id}", headers=headers)

    def list_dictation_jobs(self, headers, params=None):
        return self._request("GET", "/dictation-jobs", headers=headers, params=params)

    def claim_job(self, job_id, payload, headers):
        return self._request("POST", f"/dictation-jobs/{job_id}/claim", payload, headers)

    def release_job(self, job_id, headers):
        return self._request("POST", f"/dictation-jobs/{job_id}/release", headers=headers)

    def submit_job(self, job_id, payload, headers):
        return self._request("POST", f"/dictation-jobs/{job_id}/submit", payload, headers)

    def cancel_job(self, job_id, headers):
        return self._request("POST", f"/dictation-jobs/{job_id}/cancel", headers=headers)

    # --- Transcript ---
    def get_transcript(self, transcript_id, headers):
        return self._request("GET", f"/transcripts/{transcript_id}", headers=headers)

    def list_transcripts(self, headers, params=None):
        return self._request("GET", "/transcripts", headers=headers, params=params)

    def sign_transcript(self, transcript_id, headers):
        return self._request("POST", f"/transcripts/{transcript_id}/sign", headers=headers)

    def return_transcript(self, transcript_id, headers):
        return self._request("POST", f"/transcripts/{transcript_id}/return", headers=headers)

    def addend_transcript(self, transcript_id, payload, headers):
        return self._request("POST", f"/transcripts/{transcript_id}/addend", payload, headers)

    # --- QAReview ---
    def create_qa_review(self, payload, headers):
        return self._request("POST", "/qa-reviews", payload, headers)

    def list_job_qa_reviews(self, job_id, headers):
        return self._request("GET", f"/dictation-jobs/{job_id}/qa-reviews", headers=headers)

    def list_transcript_qa_reviews(self, transcript_id, headers):
        return self._request("GET", f"/transcripts/{transcript_id}/qa-reviews", headers=headers)

    # --- ProviderTemplate ---
    def create_provider_template(self, payload, headers):
        return self._request("POST", "/provider-templates", payload, headers)

    def update_provider_template(self, template_id, payload, headers):
        return self._request("PUT", f"/provider-templates/{template_id}", payload, headers)

    # --- Macro ---
    def create_macro(self, payload, headers):
        return self._request("POST", "/macros", payload, headers)

    def archive_macro(self, macro_id, headers):
        return self._request("POST", f"/macros/{macro_id}/archive", headers=headers)

    # --- BillingPeriod ---
    def create_billing_period(self, payload, headers):
        return self._request("POST", "/billing-periods", payload, headers)

    def get_billing_period(self, period_id, headers):
        return self._request("GET", f"/billing-periods/{period_id}", headers=headers)

    def close_billing_period(self, period_id, headers):
        return self._request("POST", f"/billing-periods/{period_id}/close", headers=headers)

    def finalize_billing_period(self, period_id, headers):
        return self._request("POST", f"/billing-periods/{period_id}/finalize", headers=headers)

    def dispute_billing_period(self, period_id, headers):
        return self._request("POST", f"/billing-periods/{period_id}/dispute", headers=headers)

    def resolve_dispute_billing_period(self, period_id, payload, headers):
        return self._request("POST", f"/billing-periods/{period_id}/resolve-dispute", payload, headers)

    def settle_billing_period(self, period_id, headers):
        return self._request("POST", f"/billing-periods/{period_id}/settle", headers=headers)

    # --- LineItem ---
    def list_billing_period_line_items(self, period_id, headers):
        return self._request("GET", f"/billing-periods/{period_id}/line-items", headers=headers)

    def list_transcript_line_items(self, transcript_id, headers):
        return self._request("GET", f"/transcripts/{transcript_id}/line-items", headers=headers)


api_client = ApiClient()
