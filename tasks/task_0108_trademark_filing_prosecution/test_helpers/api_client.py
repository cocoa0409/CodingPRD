"""API client: one method per endpoint defined in the PRD.

Subclasses GenericApiClient; the base _request() handles HTTP plumbing.
GET helpers pass query params; POST helpers pass JSON bodies.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Clock control (test-driving) ─────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ─── Applicant ────────────────────────────────────────────────────────
    def create_applicant(self, payload, headers):
        return self._request("POST", "/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    def get_risk_score(self, applicant_id, headers, params=None):
        return self._request("GET", f"/applicants/{applicant_id}/risk-score",
                             headers=headers, params=params)

    # ─── Attorney ─────────────────────────────────────────────────────────
    def create_attorney(self, payload, headers):
        return self._request("POST", "/attorneys", payload, headers)

    def get_attorney(self, attorney_id, headers):
        return self._request("GET", f"/attorneys/{attorney_id}", headers=headers)

    def suspend_attorney(self, attorney_id, headers):
        return self._request("POST", f"/attorneys/{attorney_id}/suspend", {}, headers)

    # ─── Nice classes ─────────────────────────────────────────────────────
    def create_nice_class(self, payload, headers):
        return self._request("POST", "/nice-classes", payload, headers)

    def get_nice_class(self, nice_class_id, headers):
        return self._request("GET", f"/nice-classes/{nice_class_id}", headers=headers)

    def list_nice_class_goods_services(self, nice_class_id, headers, params=None):
        return self._request("GET", f"/nice-classes/{nice_class_id}/goods-services",
                             headers=headers, params=params)

    # ─── Application core ─────────────────────────────────────────────────
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def add_goods_services(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/goods-services",
                             payload, headers)

    def list_application_goods_services(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/goods-services",
                             headers=headers, params=params)

    def file_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/file", {}, headers)

    def assign_examination(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/assign-examination",
                             {}, headers)

    def approve_publication(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/approve-publication",
                             {}, headers)

    def issue_allowance(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/issue-allowance",
                             {}, headers)

    def register_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/register", {}, headers)

    def abandon_sou_lapsed(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/abandon-sou-lapsed",
                             {}, headers)

    def list_application_docket_deadlines(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/docket-deadlines",
                             headers=headers, params=params)

    # ─── Office actions ───────────────────────────────────────────────────
    def create_office_action(self, payload, headers):
        return self._request("POST", "/office-actions", payload, headers)

    def get_office_action(self, office_action_id, headers):
        return self._request("GET", f"/office-actions/{office_action_id}", headers=headers)

    def list_application_office_actions(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/office-actions",
                             headers=headers, params=params)

    def expire_office_action(self, office_action_id, headers):
        return self._request("POST", f"/office-actions/{office_action_id}/expire", {}, headers)

    def create_office_action_response(self, payload, headers):
        return self._request("POST", "/office-action-responses", payload, headers)

    def list_office_action_responses(self, office_action_id, headers, params=None):
        return self._request("GET", f"/office-actions/{office_action_id}/responses",
                             headers=headers, params=params)

    # ─── Statements of use ────────────────────────────────────────────────
    def create_statement_of_use(self, payload, headers):
        return self._request("POST", "/statements-of-use", payload, headers)

    def accept_statement_of_use(self, sou_id, headers):
        return self._request("POST", f"/statements-of-use/{sou_id}/accept", {}, headers)

    def list_application_statements_of_use(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/statements-of-use",
                             headers=headers, params=params)

    # ─── TTAB proceedings ─────────────────────────────────────────────────
    def create_ttab_proceeding(self, payload, headers):
        return self._request("POST", "/ttab-proceedings", payload, headers)

    def get_ttab_proceeding(self, proceeding_id, headers):
        return self._request("GET", f"/ttab-proceedings/{proceeding_id}", headers=headers)

    def list_ttab_proceedings(self, headers, params=None):
        return self._request("GET", "/ttab-proceedings", headers=headers, params=params)

    def answer_ttab_proceeding(self, proceeding_id, headers):
        return self._request("POST", f"/ttab-proceedings/{proceeding_id}/answer", {}, headers)

    def enter_default_ttab_proceeding(self, proceeding_id, headers):
        return self._request("POST", f"/ttab-proceedings/{proceeding_id}/enter-default",
                             {}, headers)

    def set_for_trial_ttab_proceeding(self, proceeding_id, headers):
        return self._request("POST", f"/ttab-proceedings/{proceeding_id}/set-for-trial",
                             {}, headers)

    def decide_ttab_proceeding(self, proceeding_id, payload, headers):
        return self._request("POST", f"/ttab-proceedings/{proceeding_id}/decide",
                             payload, headers)

    def withdraw_ttab_proceeding(self, proceeding_id, headers):
        return self._request("POST", f"/ttab-proceedings/{proceeding_id}/withdraw", {}, headers)

    # ─── Registration & maintenance ───────────────────────────────────────
    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/registrations/{registration_id}", headers=headers)

    def get_application_registration(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}/registration",
                             headers=headers)

    def enter_grace_registration(self, registration_id, headers):
        return self._request("POST", f"/registrations/{registration_id}/enter-grace",
                             {}, headers)

    def expire_registration(self, registration_id, headers):
        return self._request("POST", f"/registrations/{registration_id}/expire", {}, headers)

    def create_maintenance_filing(self, payload, headers):
        return self._request("POST", "/maintenance-filings", payload, headers)

    def accept_maintenance_filing(self, filing_id, headers):
        return self._request("POST", f"/maintenance-filings/{filing_id}/accept", {}, headers)

    def list_registration_maintenance_filings(self, registration_id, headers, params=None):
        return self._request("GET", f"/registrations/{registration_id}/maintenance-filings",
                             headers=headers, params=params)

    # ─── Madrid ───────────────────────────────────────────────────────────
    def create_madrid_application(self, payload, headers):
        return self._request("POST", "/madrid-applications", payload, headers)

    def get_madrid_application(self, madrid_id, headers):
        return self._request("GET", f"/madrid-applications/{madrid_id}", headers=headers)

    def certify_madrid_application(self, madrid_id, headers):
        return self._request("POST", f"/madrid-applications/{madrid_id}/certify", {}, headers)

    def forward_madrid_application(self, madrid_id, headers):
        return self._request("POST", f"/madrid-applications/{madrid_id}/forward", {}, headers)

    def list_application_madrid_applications(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/madrid-applications",
                             headers=headers, params=params)


api_client = ApiClient()
