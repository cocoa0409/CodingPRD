"""API client: one method per endpoint defined in the Pole-Attachment &
Joint-Use Management PRD (§4). Subclasses the framework's GenericApiClient;
the base _request() handles the HTTP envelope.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock (test-driving) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- PoleOwner ----
    def create_pole_owner(self, payload, headers):
        return self._request("POST", "/joint-use/pole-owners", payload, headers)

    def get_pole_owner(self, owner_id, headers):
        return self._request("GET", f"/joint-use/pole-owners/{owner_id}", headers=headers)

    # ---- MakeReadyCrew ----
    def create_crew(self, payload, headers):
        return self._request("POST", "/joint-use/crews", payload, headers)

    def list_crews(self, headers, params=None):
        return self._request("GET", "/joint-use/crews", headers=headers, params=params)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/joint-use/crews/{crew_id}", headers=headers)

    # ---- Pole ----
    def create_pole(self, payload, headers):
        return self._request("POST", "/joint-use/poles", payload, headers)

    def list_poles(self, headers, params=None):
        return self._request("GET", "/joint-use/poles", headers=headers, params=params)

    def get_pole(self, pole_id, headers):
        return self._request("GET", f"/joint-use/poles/{pole_id}", headers=headers)

    def retire_pole(self, pole_id, headers):
        return self._request("POST", f"/joint-use/poles/{pole_id}/retire", {}, headers)

    # ---- Attacher ----
    def create_attacher(self, payload, headers):
        return self._request("POST", "/joint-use/attachers", payload, headers)

    def get_attacher(self, attacher_id, headers):
        return self._request("GET", f"/joint-use/attachers/{attacher_id}", headers=headers)

    # ---- AttachmentApplication ----
    def create_application(self, payload, headers):
        return self._request("POST", "/joint-use/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/joint-use/applications", headers=headers, params=params)

    def get_application(self, app_id, headers):
        return self._request("GET", f"/joint-use/applications/{app_id}", headers=headers)

    def survey_application(self, app_id, payload, headers):
        return self._request("POST", f"/joint-use/applications/{app_id}/survey", payload, headers)

    def estimate_application(self, app_id, payload, headers):
        return self._request("POST", f"/joint-use/applications/{app_id}/estimate", payload, headers)

    def estimate_decision_application(self, app_id, payload, headers):
        return self._request(
            "POST", f"/joint-use/applications/{app_id}/estimate-decision", payload, headers
        )

    def permit_application(self, app_id, payload, headers):
        return self._request("POST", f"/joint-use/applications/{app_id}/permit", payload, headers)

    def withdraw_application(self, app_id, headers):
        return self._request("POST", f"/joint-use/applications/{app_id}/withdraw", {}, headers)

    # ---- MakeReadySurvey ----
    def list_surveys(self, headers, params=None):
        return self._request("GET", "/joint-use/surveys", headers=headers, params=params)

    def get_survey(self, survey_id, headers):
        return self._request("GET", f"/joint-use/surveys/{survey_id}", headers=headers)

    # ---- Attachment ----
    def list_attachments(self, headers, params=None):
        return self._request("GET", "/joint-use/attachments", headers=headers, params=params)

    def get_attachment(self, att_id, headers):
        return self._request("GET", f"/joint-use/attachments/{att_id}", headers=headers)

    def transfer_attachment(self, att_id, payload, headers):
        return self._request("POST", f"/joint-use/attachments/{att_id}/transfer", payload, headers)

    def abandon_attachment(self, att_id, headers):
        return self._request("POST", f"/joint-use/attachments/{att_id}/abandon", {}, headers)

    # ---- UnauthorizedAttachmentFinding ----
    def create_finding(self, payload, headers):
        return self._request("POST", "/joint-use/findings", payload, headers)

    def list_findings(self, headers, params=None):
        return self._request("GET", "/joint-use/findings", headers=headers, params=params)

    def get_finding(self, finding_id, headers):
        return self._request("GET", f"/joint-use/findings/{finding_id}", headers=headers)

    def resolve_finding(self, finding_id, payload, headers):
        return self._request("POST", f"/joint-use/findings/{finding_id}/resolve", payload, headers)

    # ---- Invoice ----
    def create_invoice(self, payload, headers):
        return self._request("POST", "/joint-use/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/joint-use/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/joint-use/invoices/{invoice_id}", headers=headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/joint-use/invoices/{invoice_id}/pay", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/joint-use/invoices/{invoice_id}/void", {}, headers)

    # ---- Dispute ----
    def create_dispute(self, payload, headers):
        return self._request("POST", "/joint-use/disputes", payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/joint-use/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/joint-use/disputes/{dispute_id}", headers=headers)

    def transition_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/joint-use/disputes/{dispute_id}/transition", payload, headers
        )


api_client = ApiClient()
