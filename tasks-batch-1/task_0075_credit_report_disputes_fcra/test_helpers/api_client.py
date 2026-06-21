"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Consumer ----
    def create_consumer(self, payload, headers=None):
        return self._request("POST", "/consumers", payload, headers)

    def get_consumer(self, consumer_id, headers=None):
        return self._request("GET", f"/consumers/{consumer_id}", headers=headers)

    # ---- Furnisher ----
    def create_furnisher(self, payload, headers=None):
        return self._request("POST", "/furnishers", payload, headers)

    def get_furnisher(self, furnisher_id, headers=None):
        return self._request("GET", f"/furnishers/{furnisher_id}", headers=headers)

    def suspend_furnisher(self, furnisher_id, headers=None):
        return self._request("POST", f"/furnishers/{furnisher_id}/suspend", {}, headers)

    # ---- CreditFile ----
    def create_credit_file(self, payload, headers=None):
        return self._request("POST", "/credit-files", payload, headers)

    def get_credit_file(self, credit_file_id, headers=None):
        return self._request("GET", f"/credit-files/{credit_file_id}", headers=headers)

    def list_credit_files(self, headers=None, params=None):
        return self._request("GET", "/credit-files", headers=headers, params=params)

    def list_file_tradelines(self, credit_file_id, headers=None, params=None):
        return self._request("GET", f"/credit-files/{credit_file_id}/tradelines", headers=headers, params=params)

    def list_file_disputes(self, credit_file_id, headers=None, params=None):
        return self._request("GET", f"/credit-files/{credit_file_id}/disputes", headers=headers, params=params)

    def list_file_security_freezes(self, credit_file_id, headers=None, params=None):
        return self._request("GET", f"/credit-files/{credit_file_id}/security-freezes", headers=headers, params=params)

    def list_file_notifications(self, credit_file_id, headers=None, params=None):
        return self._request("GET", f"/credit-files/{credit_file_id}/notifications", headers=headers, params=params)

    # ---- Tradeline ----
    def create_tradeline(self, payload, headers=None):
        return self._request("POST", "/tradelines", payload, headers)

    def get_tradeline(self, tradeline_id, headers=None):
        return self._request("GET", f"/tradelines/{tradeline_id}", headers=headers)

    def list_tradelines(self, headers=None, params=None):
        return self._request("GET", "/tradelines", headers=headers, params=params)

    def list_tradeline_reage_events(self, tradeline_id, headers=None, params=None):
        return self._request("GET", f"/tradelines/{tradeline_id}/reage-events", headers=headers, params=params)

    def reage_tradeline(self, tradeline_id, payload, headers=None):
        return self._request("POST", f"/tradelines/{tradeline_id}/reage", payload, headers)

    # ---- Dispute ----
    def create_dispute(self, payload, headers=None):
        return self._request("POST", "/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers=None):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers=None, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def open_investigation(self, dispute_id, headers=None):
        return self._request("POST", f"/disputes/{dispute_id}/open-investigation", {}, headers)

    def list_dispute_reage_events(self, dispute_id, headers=None, params=None):
        return self._request("GET", f"/disputes/{dispute_id}/reage-events", headers=headers, params=params)

    def reopen_dispute(self, dispute_id, headers=None):
        return self._request("POST", f"/disputes/{dispute_id}/reopen", {}, headers)

    # ---- ReverificationRequest ----
    def create_reverification(self, payload, headers=None):
        return self._request("POST", "/reverification-requests", payload, headers)

    def get_reverification(self, reverification_id, headers=None):
        return self._request("GET", f"/reverification-requests/{reverification_id}", headers=headers)

    def list_reverifications(self, headers=None, params=None):
        return self._request("GET", "/reverification-requests", headers=headers, params=params)

    def respond_reverification(self, reverification_id, payload, headers=None):
        return self._request("POST", f"/reverification-requests/{reverification_id}/respond", payload, headers)

    # ---- SecurityFreeze ----
    def create_security_freeze(self, payload, headers=None):
        return self._request("POST", "/security-freezes", payload, headers)

    def get_security_freeze(self, freeze_id, headers=None):
        return self._request("GET", f"/security-freezes/{freeze_id}", headers=headers)

    def list_security_freezes(self, headers=None, params=None):
        return self._request("GET", "/security-freezes", headers=headers, params=params)

    def lift_security_freeze(self, freeze_id, headers=None):
        return self._request("POST", f"/security-freezes/{freeze_id}/lift", {}, headers)

    # ---- RegulatoryComplaint ----
    def create_complaint(self, payload, headers=None):
        return self._request("POST", "/regulatory-complaints", payload, headers)

    def get_complaint(self, complaint_id, headers=None):
        return self._request("GET", f"/regulatory-complaints/{complaint_id}", headers=headers)

    def list_complaints(self, headers=None, params=None):
        return self._request("GET", "/regulatory-complaints", headers=headers, params=params)

    def review_complaint(self, complaint_id, headers=None):
        return self._request("POST", f"/regulatory-complaints/{complaint_id}/review", {}, headers)

    def adjudicate_complaint(self, complaint_id, payload, headers=None):
        return self._request("POST", f"/regulatory-complaints/{complaint_id}/adjudicate", payload, headers)

    # ---- Notification (read) ----
    def get_notification(self, notification_id, headers=None):
        return self._request("GET", f"/notifications/{notification_id}", headers=headers)

    def list_notifications(self, headers=None, params=None):
        return self._request("GET", "/notifications", headers=headers, params=params)

    # ---- ReageEvent (read) ----
    def get_reage_event(self, reage_event_id, headers=None):
        return self._request("GET", f"/reage-events/{reage_event_id}", headers=headers)

    def list_reage_events(self, headers=None, params=None):
        return self._request("GET", "/reage-events", headers=headers, params=params)

    # ---- Test-driving clock ----
    def clock_set(self, to_iso8601, headers=None):
        return self._request("POST", "/_clock/set", {"to_iso8601": to_iso8601}, headers)

    def clock_advance(self, to_iso8601, headers=None):
        return self._request("POST", "/_clock/advance", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
