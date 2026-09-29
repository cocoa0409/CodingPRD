"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Institutions ─────────────────────────────────────────────────────────
    def create_institution(self, payload, headers):
        return self._request("POST", "/hmda/institutions", payload, headers)

    def patch_institution(self, institution_id, payload, headers):
        return self._request(
            "PATCH", f"/hmda/institutions/{institution_id}", payload, headers
        )

    def get_institution(self, institution_id, headers):
        return self._request(
            "GET", f"/hmda/institutions/{institution_id}", headers=headers
        )

    def list_institution_applications(self, institution_id, headers, params=None):
        return self._request(
            "GET", f"/hmda/institutions/{institution_id}/applications",
            headers=headers, params=params,
        )

    def list_institution_edit_runs(self, institution_id, headers, params=None):
        return self._request(
            "GET", f"/hmda/institutions/{institution_id}/edit-runs",
            headers=headers, params=params,
        )

    def list_institution_submissions(self, institution_id, headers, params=None):
        return self._request(
            "GET", f"/hmda/institutions/{institution_id}/submissions",
            headers=headers, params=params,
        )

    def list_institution_audit_samples(self, institution_id, headers, params=None):
        return self._request(
            "GET", f"/hmda/institutions/{institution_id}/audit-samples",
            headers=headers, params=params,
        )

    def list_institution_fair_lending_analyses(self, institution_id, headers, params=None):
        return self._request(
            "GET", f"/hmda/institutions/{institution_id}/fair-lending-analyses",
            headers=headers, params=params,
        )

    # ── Census tracts ────────────────────────────────────────────────────────
    def create_census_tract(self, payload, headers):
        return self._request("POST", "/hmda/census-tracts", payload, headers)

    def get_census_tract(self, tract_id, headers):
        return self._request("GET", f"/hmda/census-tracts/{tract_id}", headers=headers)

    def list_tract_geocode_assignments(self, tract_id, headers, params=None):
        return self._request(
            "GET", f"/hmda/census-tracts/{tract_id}/geocode-assignments",
            headers=headers, params=params,
        )

    # ── Register records ─────────────────────────────────────────────────────
    def create_application(self, payload, headers):
        return self._request("POST", "/hmda/applications", payload, headers)

    def patch_application(self, application_id, payload, headers):
        return self._request(
            "PATCH", f"/hmda/applications/{application_id}", payload, headers
        )

    def get_application(self, application_id, headers):
        return self._request(
            "GET", f"/hmda/applications/{application_id}", headers=headers
        )

    def advance_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/hmda/applications/{application_id}/advance", payload, headers
        )

    def record_action_taken(self, application_id, payload, headers):
        return self._request(
            "POST", f"/hmda/applications/{application_id}/action-taken", payload, headers
        )

    def reopen_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/hmda/applications/{application_id}/reopen", payload, headers
        )

    def list_application_corrections(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/hmda/applications/{application_id}/corrections",
            headers=headers, params=params,
        )

    def list_application_demographic_entries(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/hmda/applications/{application_id}/demographic-entries",
            headers=headers, params=params,
        )

    def list_application_geocode_assignments(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/hmda/applications/{application_id}/geocode-assignments",
            headers=headers, params=params,
        )

    def list_application_edit_exceptions(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/hmda/applications/{application_id}/edit-exceptions",
            headers=headers, params=params,
        )

    def list_application_audit_findings(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/hmda/applications/{application_id}/audit-findings",
            headers=headers, params=params,
        )

    # ── Applicant demographics ───────────────────────────────────────────────
    def create_demographic_entry(self, payload, headers):
        return self._request("POST", "/hmda/demographic-entries", payload, headers)

    def patch_demographic_entry(self, entry_id, payload, headers):
        return self._request(
            "PATCH", f"/hmda/demographic-entries/{entry_id}", payload, headers
        )

    # ── Geocoding ────────────────────────────────────────────────────────────
    def create_geocode_assignment(self, payload, headers):
        return self._request("POST", "/hmda/geocode-assignments", payload, headers)

    def manual_override_geocode(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/hmda/geocode-assignments/{assignment_id}/manual-override",
            payload, headers,
        )

    # ── Edit battery ─────────────────────────────────────────────────────────
    def create_edit_run(self, payload, headers):
        return self._request("POST", "/hmda/edit-runs", payload, headers)

    def get_edit_run(self, run_id, headers):
        return self._request("GET", f"/hmda/edit-runs/{run_id}", headers=headers)

    def list_edit_run_exceptions(self, run_id, headers, params=None):
        return self._request(
            "GET", f"/hmda/edit-runs/{run_id}/exceptions", headers=headers, params=params
        )

    def list_edit_run_submissions(self, run_id, headers, params=None):
        return self._request(
            "GET", f"/hmda/edit-runs/{run_id}/submissions", headers=headers, params=params
        )

    def verify_edit_exception(self, exception_id, payload, headers):
        return self._request(
            "POST", f"/hmda/edit-exceptions/{exception_id}/verify", payload, headers
        )

    # ── Filing submissions ───────────────────────────────────────────────────
    def create_submission(self, payload, headers):
        return self._request("POST", "/hmda/submissions", payload, headers)

    def get_submission(self, submission_id, headers):
        return self._request("GET", f"/hmda/submissions/{submission_id}", headers=headers)

    def attach_edit_run(self, submission_id, payload, headers):
        return self._request(
            "POST", f"/hmda/submissions/{submission_id}/attach-edit-run", payload, headers
        )

    def certify_submission(self, submission_id, payload, headers):
        return self._request(
            "POST", f"/hmda/submissions/{submission_id}/certify", payload, headers
        )

    def file_submission(self, submission_id, headers, payload=None):
        return self._request(
            "POST", f"/hmda/submissions/{submission_id}/file", payload or {}, headers
        )

    def review_submission(self, submission_id, payload, headers):
        return self._request(
            "POST", f"/hmda/submissions/{submission_id}/review", payload, headers
        )

    def resubmit_submission(self, submission_id, payload, headers):
        return self._request(
            "POST", f"/hmda/submissions/{submission_id}/resubmit", payload, headers
        )

    def list_submission_disclosure_statements(self, submission_id, headers, params=None):
        return self._request(
            "GET", f"/hmda/submissions/{submission_id}/disclosure-statements",
            headers=headers, params=params,
        )

    # ── Audit scrub ──────────────────────────────────────────────────────────
    def create_audit_sample(self, payload, headers):
        return self._request("POST", "/hmda/audit-samples", payload, headers)

    def get_audit_sample(self, sample_id, headers):
        return self._request("GET", f"/hmda/audit-samples/{sample_id}", headers=headers)

    def list_audit_sample_findings(self, sample_id, headers, params=None):
        return self._request(
            "GET", f"/hmda/audit-samples/{sample_id}/findings",
            headers=headers, params=params,
        )

    def create_audit_finding(self, payload, headers):
        return self._request("POST", "/hmda/audit-findings", payload, headers)

    def close_audit_sample(self, sample_id, payload, headers):
        return self._request(
            "POST", f"/hmda/audit-samples/{sample_id}/close", payload, headers
        )

    # ── Fair lending ─────────────────────────────────────────────────────────
    def create_fair_lending_analysis(self, payload, headers):
        return self._request("POST", "/hmda/fair-lending-analyses", payload, headers)

    # ── Logical clock ────────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
