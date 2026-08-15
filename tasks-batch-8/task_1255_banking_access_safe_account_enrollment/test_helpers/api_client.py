"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, base_url=None):
        super().__init__(base_url)
        # The runner restarts the server before every test (per-test-server
        # isolation). A keep-alive pool would hold dead connections across
        # reboots and surface as ECONNRESET mid-test; close per request so
        # every request opens a fresh socket.
        self.session.headers["Connection"] = "close"

    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- ops epoch ---
    def ops_evaluate_due(self, headers):
        return self._request("POST", "/api/ops/evaluate-due", {}, headers)

    # --- AccountStandard ---
    def create_account_standard(self, payload, headers):
        return self._request("POST", "/api/account-standards", payload, headers)

    def get_account_standard(self, standard_id, headers):
        return self._request("GET", f"/api/account-standards/{standard_id}", headers=headers)

    def activate_account_standard(self, standard_id, headers):
        return self._request("POST", f"/api/account-standards/{standard_id}/activate", {}, headers)

    # --- PartnerInstitution ---
    def create_partner_institution(self, payload, headers):
        return self._request("POST", "/api/partner-institutions", payload, headers)

    def list_partner_institutions(self, headers, params=None):
        return self._request("GET", "/api/partner-institutions", headers=headers, params=params)

    def get_partner_institution(self, institution_id, headers):
        return self._request("GET", f"/api/partner-institutions/{institution_id}", headers=headers)

    def suspend_partner_institution(self, institution_id, headers):
        return self._request("POST", f"/api/partner-institutions/{institution_id}/suspend", {}, headers)

    def reinstate_partner_institution(self, institution_id, headers):
        return self._request("POST", f"/api/partner-institutions/{institution_id}/reinstate", {}, headers)

    # --- CertificationReview ---
    def create_certification_review(self, payload, headers):
        return self._request("POST", "/api/certification-reviews", payload, headers)

    def list_certification_reviews(self, headers, params=None):
        return self._request("GET", "/api/certification-reviews", headers=headers, params=params)

    def get_certification_review(self, review_id, headers):
        return self._request("GET", f"/api/certification-reviews/{review_id}", headers=headers)

    def score_certification_review(self, review_id, payload, headers):
        return self._request("POST", f"/api/certification-reviews/{review_id}/score", payload, headers)

    def finalize_certification_review(self, review_id, headers):
        return self._request("POST", f"/api/certification-reviews/{review_id}/finalize", {}, headers)

    # --- Participant ---
    def create_participant(self, payload, headers):
        return self._request("POST", "/api/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/api/participants/{participant_id}", headers=headers)

    def update_participant_documents(self, participant_id, payload, headers):
        return self._request("PATCH", f"/api/participants/{participant_id}/documents", payload, headers)

    # --- Referral ---
    def create_referral(self, payload, headers):
        return self._request("POST", "/api/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/api/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/api/referrals/{referral_id}", headers=headers)

    def referral_docs_complete(self, referral_id, headers):
        return self._request("POST", f"/api/referrals/{referral_id}/docs-complete", {}, headers)

    def book_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/api/referrals/{referral_id}/book", payload, headers)

    def unbook_referral(self, referral_id, headers):
        return self._request("POST", f"/api/referrals/{referral_id}/unbook", {}, headers)

    # --- AccountOpeningEvent ---
    def create_account_opening_event(self, payload, headers):
        return self._request("POST", "/api/account-opening-events", payload, headers)

    def list_account_opening_events(self, headers, params=None):
        return self._request("GET", "/api/account-opening-events", headers=headers, params=params)

    def get_account_opening_event(self, event_id, headers):
        return self._request("GET", f"/api/account-opening-events/{event_id}", headers=headers)

    def list_event_referrals(self, event_id, headers, params=None):
        return self._request("GET", f"/api/account-opening-events/{event_id}/referrals", headers=headers, params=params)

    def cancel_account_opening_event(self, event_id, headers):
        return self._request("POST", f"/api/account-opening-events/{event_id}/cancel", {}, headers)

    # --- AccountApplication ---
    def create_account_application(self, payload, headers):
        return self._request("POST", "/api/account-applications", payload, headers)

    def list_account_applications(self, headers, params=None):
        return self._request("GET", "/api/account-applications", headers=headers, params=params)

    def get_account_application(self, application_id, headers):
        return self._request("GET", f"/api/account-applications/{application_id}", headers=headers)

    def decide_account_application(self, application_id, payload, headers):
        return self._request("POST", f"/api/account-applications/{application_id}/decision", payload, headers)

    def report_application_closure(self, application_id, payload, headers):
        return self._request("POST", f"/api/account-applications/{application_id}/report-closure", payload, headers)

    # --- BarrierCase ---
    def list_barrier_cases(self, headers, params=None):
        return self._request("GET", "/api/barrier-cases", headers=headers, params=params)

    def get_barrier_case(self, case_id, headers):
        return self._request("GET", f"/api/barrier-cases/{case_id}", headers=headers)

    def propose_barrier_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/barrier-cases/{case_id}/propose", payload, headers)

    def counter_barrier_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/barrier-cases/{case_id}/counter", payload, headers)

    def accept_barrier_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/barrier-cases/{case_id}/accept", payload, headers)

    def escalate_barrier_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/barrier-cases/{case_id}/escalate", payload, headers)

    # --- EducationPairing ---
    def create_education_pairing(self, payload, headers):
        return self._request("POST", "/api/education-pairings", payload, headers)

    def list_education_pairings(self, headers, params=None):
        return self._request("GET", "/api/education-pairings", headers=headers, params=params)

    def get_education_pairing(self, pairing_id, headers):
        return self._request("GET", f"/api/education-pairings/{pairing_id}", headers=headers)

    def complete_education_pairing(self, pairing_id, headers):
        return self._request("POST", f"/api/education-pairings/{pairing_id}/complete", {}, headers)

    def log_follow_up(self, pairing_id, headers):
        return self._request("POST", f"/api/education-pairings/{pairing_id}/log-follow-up", {}, headers)

    # --- RetentionCheckpoint ---
    def list_retention_checkpoints(self, headers, params=None):
        return self._request("GET", "/api/retention-checkpoints", headers=headers, params=params)

    def get_retention_checkpoint(self, checkpoint_id, headers):
        return self._request("GET", f"/api/retention-checkpoints/{checkpoint_id}", headers=headers)

    # --- FundingGrant ---
    def create_funding_grant(self, payload, headers):
        return self._request("POST", "/api/funding-grants", payload, headers)

    def get_funding_grant(self, grant_id, headers):
        return self._request("GET", f"/api/funding-grants/{grant_id}", headers=headers)

    def activate_funding_grant(self, grant_id, headers):
        return self._request("POST", f"/api/funding-grants/{grant_id}/activate", {}, headers)

    def suspend_funding_grant(self, grant_id, headers):
        return self._request("POST", f"/api/funding-grants/{grant_id}/suspend", {}, headers)

    def close_funding_grant(self, grant_id, headers):
        return self._request("POST", f"/api/funding-grants/{grant_id}/close", {}, headers)

    # --- PartnerReport ---
    def create_partner_report(self, payload, headers):
        return self._request("POST", "/api/partner-reports", payload, headers)

    def list_partner_reports(self, headers, params=None):
        return self._request("GET", "/api/partner-reports", headers=headers, params=params)

    def get_partner_report(self, report_id, headers):
        return self._request("GET", f"/api/partner-reports/{report_id}", headers=headers)

    def submit_partner_report(self, report_id, headers):
        return self._request("POST", f"/api/partner-reports/{report_id}/submit", {}, headers)

    def review_partner_report(self, report_id, payload, headers):
        return self._request("POST", f"/api/partner-reports/{report_id}/review", payload, headers)

    # --- OutreachCampaign ---
    def create_outreach_campaign(self, payload, headers):
        return self._request("POST", "/api/outreach-campaigns", payload, headers)

    def get_outreach_campaign(self, campaign_id, headers):
        return self._request("GET", f"/api/outreach-campaigns/{campaign_id}", headers=headers)

    def close_outreach_campaign(self, campaign_id, headers):
        return self._request("POST", f"/api/outreach-campaigns/{campaign_id}/close", {}, headers)


api_client = ApiClient()
