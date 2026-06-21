"""API client: one method per endpoint defined in the Privacy DSAR PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Controllers -----
    def create_controller(self, payload, headers):
        return self._request("POST", "/controllers", payload, headers)

    def get_controller(self, controller_id, headers):
        return self._request("GET", f"/controllers/{controller_id}", headers=headers)

    # ----- Data subjects -----
    def create_data_subject(self, payload, headers):
        return self._request("POST", "/data-subjects", payload, headers)

    def get_data_subject(self, subject_id, headers):
        return self._request("GET", f"/data-subjects/{subject_id}", headers=headers)

    def list_data_subjects(self, headers, params=None):
        return self._request("GET", "/data-subjects", headers=headers, params=params)

    # ----- Processors -----
    def create_processor(self, payload, headers):
        return self._request("POST", "/processors", payload, headers)

    def get_processor(self, processor_id, headers):
        return self._request("GET", f"/processors/{processor_id}", headers=headers)

    def list_processors(self, headers, params=None):
        return self._request("GET", "/processors", headers=headers, params=params)

    def suspend_processor(self, processor_id, headers):
        return self._request("POST", f"/processors/{processor_id}/suspend", headers=headers)

    # ----- Consent records -----
    def create_consent_record(self, payload, headers):
        return self._request("POST", "/consent-records", payload, headers)

    def get_consent_record(self, consent_id, headers):
        return self._request("GET", f"/consent-records/{consent_id}", headers=headers)

    def list_consent_records(self, headers, params=None):
        return self._request("GET", "/consent-records", headers=headers, params=params)

    def withdraw_consent_record(self, consent_id, headers):
        return self._request("POST", f"/consent-records/{consent_id}/withdraw", headers=headers)

    # ----- Legal holds -----
    def create_legal_hold(self, payload, headers):
        return self._request("POST", "/legal-holds", payload, headers)

    def get_legal_hold(self, hold_id, headers):
        return self._request("GET", f"/legal-holds/{hold_id}", headers=headers)

    def list_legal_holds(self, headers, params=None):
        return self._request("GET", "/legal-holds", headers=headers, params=params)

    def lift_legal_hold(self, hold_id, headers):
        return self._request("POST", f"/legal-holds/{hold_id}/lift", headers=headers)

    # ----- DSAR requests -----
    def create_dsar_request(self, payload, headers):
        return self._request("POST", "/dsar-requests", payload, headers)

    def get_dsar_request(self, request_id, headers):
        return self._request("GET", f"/dsar-requests/{request_id}", headers=headers)

    def list_dsar_requests(self, headers, params=None):
        return self._request("GET", "/dsar-requests", headers=headers, params=params)

    def get_dsar_risk(self, request_id, headers):
        return self._request("GET", f"/dsar-requests/{request_id}/risk", headers=headers)

    def verify_identity(self, request_id, payload, headers):
        return self._request("POST", f"/dsar-requests/{request_id}/verify-identity", payload, headers)

    def reject_identity(self, request_id, payload, headers):
        return self._request("POST", f"/dsar-requests/{request_id}/reject-identity", payload, headers)

    def resubmit_identity(self, request_id, headers):
        return self._request("POST", f"/dsar-requests/{request_id}/resubmit-identity", headers=headers)

    def complete_discovery(self, request_id, headers):
        return self._request("POST", f"/dsar-requests/{request_id}/complete-discovery", headers=headers)

    def extend_deadline(self, request_id, payload, headers):
        return self._request("POST", f"/dsar-requests/{request_id}/extend-deadline", payload, headers)

    def dispatch_fulfillment(self, request_id, payload, headers):
        return self._request("POST", f"/dsar-requests/{request_id}/dispatch-fulfillment", payload, headers)

    def close_request(self, request_id, payload, headers):
        return self._request("POST", f"/dsar-requests/{request_id}/close", payload, headers)

    # ----- Discovery findings -----
    def create_finding(self, request_id, payload, headers):
        return self._request("POST", f"/dsar-requests/{request_id}/findings", payload, headers)

    def list_request_findings(self, request_id, headers, params=None):
        return self._request("GET", f"/dsar-requests/{request_id}/findings", headers=headers, params=params)

    def get_finding(self, finding_id, headers):
        return self._request("GET", f"/findings/{finding_id}", headers=headers)

    def list_findings(self, headers, params=None):
        return self._request("GET", "/findings", headers=headers, params=params)

    def confirm_finding(self, finding_id, headers):
        return self._request("POST", f"/findings/{finding_id}/confirm", headers=headers)

    def dismiss_finding(self, finding_id, headers):
        return self._request("POST", f"/findings/{finding_id}/dismiss", headers=headers)

    # ----- Exemption claims -----
    def create_exemption(self, request_id, payload, headers):
        return self._request("POST", f"/dsar-requests/{request_id}/exemptions", payload, headers)

    def list_request_exemptions(self, request_id, headers, params=None):
        return self._request("GET", f"/dsar-requests/{request_id}/exemptions", headers=headers, params=params)

    def get_exemption(self, exemption_id, headers):
        return self._request("GET", f"/exemptions/{exemption_id}", headers=headers)

    def decide_exemption(self, exemption_id, payload, headers):
        return self._request("POST", f"/exemptions/{exemption_id}/decide", payload, headers)

    # ----- Fulfillment items -----
    def list_request_fulfillment_items(self, request_id, headers, params=None):
        return self._request("GET", f"/dsar-requests/{request_id}/fulfillment-items", headers=headers, params=params)

    def get_fulfillment_item(self, item_id, headers):
        return self._request("GET", f"/fulfillment-items/{item_id}", headers=headers)

    def list_fulfillment_items(self, headers, params=None):
        return self._request("GET", "/fulfillment-items", headers=headers, params=params)

    def dispatch_item(self, item_id, payload, headers):
        return self._request("POST", f"/fulfillment-items/{item_id}/dispatch", payload, headers)

    def complete_item(self, item_id, headers):
        return self._request("POST", f"/fulfillment-items/{item_id}/complete", headers=headers)

    def unblock_item(self, item_id, headers):
        return self._request("POST", f"/fulfillment-items/{item_id}/unblock", headers=headers)

    def list_item_notifications(self, item_id, headers, params=None):
        return self._request("GET", f"/fulfillment-items/{item_id}/notifications", headers=headers, params=params)

    # ----- Processor notifications -----
    def get_notification(self, notification_id, headers):
        return self._request("GET", f"/processor-notifications/{notification_id}", headers=headers)

    def list_notifications(self, headers, params=None):
        return self._request("GET", "/processor-notifications", headers=headers, params=params)

    def acknowledge_notification(self, notification_id, headers):
        return self._request("POST", f"/processor-notifications/{notification_id}/acknowledge", headers=headers)

    # ----- Audit events -----
    def list_audit_events(self, request_id, headers, params=None):
        return self._request("GET", f"/dsar-requests/{request_id}/audit-events", headers=headers, params=params)

    # ----- System clock (test-driving) -----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
