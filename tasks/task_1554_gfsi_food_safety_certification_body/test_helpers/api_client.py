"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, base_url=None):
        super().__init__(base_url)
        # The runner restarts the API server (SIGKILL + respawn on the same
        # port) before every test under per-test-server isolation. A pooled
        # keep-alive connection to the killed server is intermittently reused
        # by requests/urllib3 and resets mid-setup (ConnectionResetError /
        # RemoteDisconnected — POSTs are never retried by the default
        # adapter). Forcing Connection: close gives every request a fresh TCP
        # connection, so no stale pool entry can ever be drawn.
        self.session.headers["Connection"] = "close"

    # ---- schemes ----
    def create_scheme(self, payload, headers):
        return self._request("POST", "/certification-body/schemes", payload, headers)

    def list_schemes(self, headers, params=None):
        return self._request("GET", "/certification-body/schemes",
                             headers=headers, params=params)

    def get_scheme(self, scheme_id, headers):
        return self._request("GET", f"/certification-body/schemes/{scheme_id}",
                             headers=headers)

    # ---- clients ----
    def create_client(self, payload, headers):
        return self._request("POST", "/certification-body/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/certification-body/clients/{client_id}",
                             headers=headers)

    # ---- auditors ----
    def create_auditor(self, payload, headers):
        return self._request("POST", "/certification-body/auditors", payload, headers)

    def get_auditor(self, auditor_id, headers):
        return self._request("GET", f"/certification-body/auditors/{auditor_id}",
                             headers=headers)

    def list_auditor_audits(self, auditor_id, headers, params=None):
        return self._request("GET", f"/certification-body/auditors/{auditor_id}/audits",
                             headers=headers, params=params)

    def create_witness_audit(self, auditor_id, payload, headers):
        return self._request("POST",
                             f"/certification-body/auditors/{auditor_id}/witness-audits",
                             payload, headers)

    def list_witness_audits(self, auditor_id, headers, params=None):
        return self._request("GET",
                             f"/certification-body/auditors/{auditor_id}/witness-audits",
                             headers=headers, params=params)

    # ---- decision makers ----
    def create_decision_maker(self, payload, headers):
        return self._request("POST", "/certification-body/decision-makers",
                             payload, headers)

    def get_decision_maker(self, decision_maker_id, headers):
        return self._request("GET",
                             f"/certification-body/decision-makers/{decision_maker_id}",
                             headers=headers)

    def list_decision_makers(self, headers, params=None):
        return self._request("GET", "/certification-body/decision-makers",
                             headers=headers, params=params)

    def list_decision_maker_audits(self, decision_maker_id, headers, params=None):
        return self._request("GET",
                             f"/certification-body/decision-makers/{decision_maker_id}/audits",
                             headers=headers, params=params)

    # ---- applications ----
    def create_application(self, payload, headers):
        return self._request("POST", "/certification-body/applications",
                             payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/certification-body/applications",
                             headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET",
                             f"/certification-body/applications/{application_id}",
                             headers=headers)

    def submit_application(self, application_id, headers):
        return self._request("POST",
                             f"/certification-body/applications/{application_id}/submit",
                             headers=headers)

    def review_application(self, application_id, payload, headers):
        return self._request("POST",
                             f"/certification-body/applications/{application_id}/review",
                             payload, headers)

    def list_application_audits(self, application_id, headers, params=None):
        return self._request("GET",
                             f"/certification-body/applications/{application_id}/audits",
                             headers=headers, params=params)

    # ---- audits ----
    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/certification-body/audits/{audit_id}",
                             headers=headers)

    def assign_auditor(self, audit_id, payload, headers):
        return self._request("POST", f"/certification-body/audits/{audit_id}/assign",
                             payload, headers)

    def reschedule_audit(self, audit_id, payload, headers):
        return self._request("POST",
                             f"/certification-body/audits/{audit_id}/reschedule",
                             payload, headers)

    def cancel_audit(self, audit_id, headers):
        return self._request("POST", f"/certification-body/audits/{audit_id}/cancel",
                             headers=headers)

    def start_audit(self, audit_id, headers):
        return self._request("POST", f"/certification-body/audits/{audit_id}/start",
                             headers=headers)

    def create_nonconformity(self, audit_id, payload, headers):
        return self._request("POST",
                             f"/certification-body/audits/{audit_id}/nonconformities",
                             payload, headers)

    def list_nonconformities(self, audit_id, headers, params=None):
        return self._request("GET",
                             f"/certification-body/audits/{audit_id}/nonconformities",
                             headers=headers, params=params)

    def submit_report(self, audit_id, payload, headers):
        return self._request("POST",
                             f"/certification-body/audits/{audit_id}/submit-report",
                             payload, headers)

    def decide_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/certification-body/audits/{audit_id}/decision",
                             payload, headers)

    def get_audit_certificate(self, audit_id, headers, params=None):
        return self._request("GET",
                             f"/certification-body/audits/{audit_id}/certificate",
                             headers=headers, params=params)

    # ---- nonconformities ----
    def get_nonconformity(self, nc_id, headers):
        return self._request("GET",
                             f"/certification-body/nonconformities/{nc_id}",
                             headers=headers)

    def submit_cap(self, nc_id, payload, headers):
        return self._request("POST",
                             f"/certification-body/nonconformities/{nc_id}/submit-cap",
                             payload, headers)

    def review_cap(self, nc_id, payload, headers):
        return self._request("POST",
                             f"/certification-body/nonconformities/{nc_id}/review-cap",
                             payload, headers)

    # ---- certificates ----
    def list_certificates(self, headers, params=None):
        return self._request("GET", "/certification-body/certificates",
                             headers=headers, params=params)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET",
                             f"/certification-body/certificates/{certificate_id}",
                             headers=headers)

    def suspend_certificate(self, certificate_id, payload, headers):
        return self._request("POST",
                             f"/certification-body/certificates/{certificate_id}/suspend",
                             payload, headers)

    def reinstate_certificate(self, certificate_id, headers):
        return self._request("POST",
                             f"/certification-body/certificates/{certificate_id}/reinstate",
                             headers=headers)

    def withdraw_certificate(self, certificate_id, headers):
        return self._request("POST",
                             f"/certification-body/certificates/{certificate_id}/withdraw",
                             headers=headers)

    def create_scope_change(self, certificate_id, payload, headers):
        return self._request("POST",
                             f"/certification-body/certificates/{certificate_id}/scope-changes",
                             payload, headers)

    def list_scope_changes(self, certificate_id, headers, params=None):
        return self._request("GET",
                             f"/certification-body/certificates/{certificate_id}/scope-changes",
                             headers=headers, params=params)

    def list_certificate_appeals(self, certificate_id, headers, params=None):
        return self._request("GET",
                             f"/certification-body/certificates/{certificate_id}/appeals",
                             headers=headers, params=params)

    def get_certificate_listing(self, certificate_id, headers, params=None):
        return self._request("GET",
                             f"/certification-body/certificates/{certificate_id}/directory-listing",
                             headers=headers, params=params)

    # ---- scope changes ----
    def decide_scope_change(self, scope_change_id, payload, headers):
        return self._request("POST",
                             f"/certification-body/scope-changes/{scope_change_id}/decision",
                             payload, headers)

    # ---- appeals ----
    def create_appeal(self, payload, headers):
        return self._request("POST", "/certification-body/appeals", payload, headers)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST",
                             f"/certification-body/appeals/{appeal_id}/decide",
                             payload, headers)

    # ---- public directory ----
    def list_directory(self, headers, params=None):
        return self._request("GET", "/certification-body/directory",
                             headers=headers, params=params)

    # ---- logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/certification-body/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
