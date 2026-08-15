"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/appeals/_clock/set_current_utc", payload, headers)

    # ---- members ----
    def create_member(self, payload, headers):
        return self._request("POST", "/appeals/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/appeals/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/appeals/members", headers=headers, params=params)

    def get_member_ctm_exposure(self, member_id, headers):
        return self._request("GET", f"/appeals/members/{member_id}/ctm-exposure", headers=headers)

    def list_member_cases(self, member_id, headers, params=None):
        return self._request("GET", f"/appeals/members/{member_id}/cases", headers=headers, params=params)

    # ---- providers ----
    def create_provider(self, payload, headers):
        return self._request("POST", "/appeals/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/appeals/providers/{provider_id}", headers=headers)

    def patch_provider(self, provider_id, payload, headers):
        return self._request("PATCH", f"/appeals/providers/{provider_id}", payload, headers)

    # ---- deadline policies ----
    def create_deadline_policy(self, payload, headers):
        return self._request("POST", "/appeals/deadline-policies", payload, headers)

    def list_deadline_policies(self, headers, params=None):
        return self._request("GET", "/appeals/deadline-policies", headers=headers, params=params)

    # ---- cases ----
    def create_case(self, payload, headers):
        return self._request("POST", "/appeals/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/appeals/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/appeals/cases", headers=headers, params=params)

    def triage_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/appeals/cases/{case_id}/triage", payload or {}, headers)

    def begin_review(self, case_id, headers, payload=None):
        return self._request("POST", f"/appeals/cases/{case_id}/begin-review", payload or {}, headers)

    def expedite_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/appeals/cases/{case_id}/expedite", payload or {}, headers)

    def extend_case(self, case_id, payload, headers):
        return self._request("POST", f"/appeals/cases/{case_id}/extensions", payload, headers)

    def decide_case(self, case_id, payload, headers):
        return self._request("POST", f"/appeals/cases/{case_id}/decide", payload, headers)

    def withdraw_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/appeals/cases/{case_id}/withdraw", payload or {}, headers)

    def close_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/appeals/cases/{case_id}/close", payload or {}, headers)

    def list_case_events(self, case_id, headers, params=None):
        return self._request("GET", f"/appeals/cases/{case_id}/events", headers=headers, params=params)

    def list_case_clinical_reviews(self, case_id, headers, params=None):
        return self._request("GET", f"/appeals/cases/{case_id}/clinical-reviews", headers=headers, params=params)

    def list_case_notifications(self, case_id, headers, params=None):
        return self._request("GET", f"/appeals/cases/{case_id}/notifications", headers=headers, params=params)

    def list_case_ire_referrals(self, case_id, headers, params=None):
        return self._request("GET", f"/appeals/cases/{case_id}/ire-referrals", headers=headers, params=params)

    def list_case_effectuations(self, case_id, headers, params=None):
        return self._request("GET", f"/appeals/cases/{case_id}/effectuations", headers=headers, params=params)

    def list_case_reopenings(self, case_id, headers, params=None):
        return self._request("GET", f"/appeals/cases/{case_id}/reopenings", headers=headers, params=params)

    # ---- case events ----
    def append_case_event(self, case_id, payload, headers):
        return self._request("POST", f"/appeals/cases/{case_id}/events", payload, headers)

    # ---- clinical reviews ----
    def request_clinical_review(self, case_id, headers, payload=None):
        return self._request("POST", f"/appeals/cases/{case_id}/clinical-reviews", payload or {}, headers)

    def get_clinical_review(self, review_id, headers):
        return self._request("GET", f"/appeals/clinical-reviews/{review_id}", headers=headers)

    def list_clinical_reviews(self, headers, params=None):
        return self._request("GET", "/appeals/clinical-reviews", headers=headers, params=params)

    def assign_clinical_review(self, review_id, payload, headers):
        return self._request("POST", f"/appeals/clinical-reviews/{review_id}/assign", payload, headers)

    def draft_determination(self, review_id, payload, headers):
        return self._request("POST", f"/appeals/clinical-reviews/{review_id}/draft-determination", payload, headers)

    def finalize_determination(self, review_id, payload, headers):
        return self._request("POST", f"/appeals/clinical-reviews/{review_id}/finalize-determination", payload, headers)

    # ---- notifications ----
    def create_notification(self, case_id, payload, headers):
        return self._request("POST", f"/appeals/cases/{case_id}/notifications", payload, headers)

    def get_notification(self, notification_id, headers):
        return self._request("GET", f"/appeals/notifications/{notification_id}", headers=headers)

    def patch_notification(self, notification_id, payload, headers):
        return self._request("PATCH", f"/appeals/notifications/{notification_id}", payload, headers)

    def mark_notification_sent(self, notification_id, headers, payload=None):
        return self._request("POST", f"/appeals/notifications/{notification_id}/mark-sent", payload or {}, headers)

    def mark_notification_delivered(self, notification_id, headers, payload=None):
        return self._request("POST", f"/appeals/notifications/{notification_id}/mark-delivered", payload or {}, headers)

    def mark_notification_failed(self, notification_id, headers, payload=None):
        return self._request("POST", f"/appeals/notifications/{notification_id}/mark-failed", payload or {}, headers)

    def retry_notification(self, notification_id, headers, payload=None):
        return self._request("POST", f"/appeals/notifications/{notification_id}/retry", payload or {}, headers)

    # ---- IRE referrals ----
    def create_ire_referral(self, case_id, payload, headers):
        return self._request("POST", f"/appeals/cases/{case_id}/ire-referrals", payload, headers)

    def get_ire_referral(self, referral_id, headers):
        return self._request("GET", f"/appeals/ire-referrals/{referral_id}", headers=headers)

    def ire_acknowledge(self, referral_id, headers, payload=None):
        return self._request("POST", f"/appeals/ire-referrals/{referral_id}/ire-acknowledge", payload or {}, headers)

    def ire_record_decision(self, referral_id, payload, headers):
        return self._request("POST", f"/appeals/ire-referrals/{referral_id}/ire-record-decision", payload, headers)

    # ---- effectuations ----
    def get_effectuation(self, effectuation_id, headers):
        return self._request("GET", f"/appeals/effectuations/{effectuation_id}", headers=headers)

    def list_effectuations(self, headers, params=None):
        return self._request("GET", "/appeals/effectuations", headers=headers, params=params)

    def start_effectuation(self, effectuation_id, headers, payload=None):
        return self._request("POST", f"/appeals/effectuations/{effectuation_id}/start", payload or {}, headers)

    def complete_effectuation(self, effectuation_id, payload, headers):
        return self._request("POST", f"/appeals/effectuations/{effectuation_id}/complete", payload, headers)

    def waive_effectuation(self, effectuation_id, headers, payload=None):
        return self._request("POST", f"/appeals/effectuations/{effectuation_id}/waive", payload or {}, headers)

    def escalate_effectuation(self, effectuation_id, headers, payload=None):
        return self._request("POST", f"/appeals/effectuations/{effectuation_id}/escalate", payload or {}, headers)

    # ---- reopenings ----
    def create_reopening(self, payload, headers):
        return self._request("POST", "/appeals/reopenings", payload, headers)

    def get_reopening(self, reopening_id, headers):
        return self._request("GET", f"/appeals/reopenings/{reopening_id}", headers=headers)

    def begin_reopening_review(self, reopening_id, headers, payload=None):
        return self._request("POST", f"/appeals/reopenings/{reopening_id}/begin-review", payload or {}, headers)

    def grant_reopening(self, reopening_id, payload, headers):
        return self._request("POST", f"/appeals/reopenings/{reopening_id}/grant", payload, headers)

    def deny_reopening(self, reopening_id, headers, payload=None):
        return self._request("POST", f"/appeals/reopenings/{reopening_id}/deny", payload or {}, headers)

    # ---- audit universe ----
    def create_audit_snapshot(self, payload, headers):
        return self._request("POST", "/appeals/audit-universe/snapshot", payload, headers)

    def list_audit_universe(self, headers, params=None):
        return self._request("GET", "/appeals/audit-universe", headers=headers, params=params)

    def get_audit_record(self, record_id, headers):
        return self._request("GET", f"/appeals/audit-universe/{record_id}", headers=headers)

    def get_compliance_summary(self, headers, params=None):
        return self._request("GET", "/appeals/audit-universe/compliance-summary", headers=headers, params=params)


api_client = ApiClient()
