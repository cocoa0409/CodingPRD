"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Property ---
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    # --- Unit ---
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/units", headers=headers, params=params)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def unit_service(self, unit_id, payload, headers):
        return self._request("POST", f"/units/{unit_id}/service", payload, headers)

    # --- OccupancyStandard ---
    def create_occupancy_standard(self, payload, headers):
        return self._request("POST", "/occupancy-standards", payload, headers)

    def list_occupancy_standards(self, headers, params=None):
        return self._request("GET", "/occupancy-standards", headers=headers,
                             params=params)

    def get_occupancy_standard(self, standard_id, headers):
        return self._request("GET", f"/occupancy-standards/{standard_id}",
                             headers=headers)

    # --- AmiLimit ---
    def create_ami_limit(self, payload, headers):
        return self._request("POST", "/ami-limits", payload, headers)

    def list_ami_limits(self, headers, params=None):
        return self._request("GET", "/ami-limits", headers=headers, params=params)

    def get_ami_limit(self, limit_id, headers):
        return self._request("GET", f"/ami-limits/{limit_id}", headers=headers)

    # --- ApplicationCampaign ---
    def create_campaign(self, payload, headers):
        return self._request("POST", "/campaigns", payload, headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/campaigns", headers=headers, params=params)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/campaigns/{campaign_id}", headers=headers)

    def transition_campaign(self, campaign_id, payload, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/transition",
                             payload, headers)

    # --- Applicant ---
    def create_applicant(self, payload, headers):
        return self._request("POST", "/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    # --- Application ---
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}",
                             headers=headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/withdraw",
                             {}, headers)

    def review_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/review",
                             payload, headers)

    # --- PreferenceClaim ---
    def create_preference_claim(self, payload, headers):
        return self._request("POST", "/preference-claims", payload, headers)

    def list_preference_claims(self, headers, params=None):
        return self._request("GET", "/preference-claims", headers=headers,
                             params=params)

    def get_preference_claim(self, claim_id, headers):
        return self._request("GET", f"/preference-claims/{claim_id}",
                             headers=headers)

    def transition_preference_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/preference-claims/{claim_id}/transition",
                             payload, headers)

    # --- IncomeCertification ---
    def create_income_certification(self, payload, headers):
        return self._request("POST", "/income-certifications", payload, headers)

    def list_income_certifications(self, headers, params=None):
        return self._request("GET", "/income-certifications", headers=headers,
                             params=params)

    def get_income_certification(self, cert_id, headers):
        return self._request("GET", f"/income-certifications/{cert_id}",
                             headers=headers)

    def advance_income_certification(self, cert_id, payload, headers):
        return self._request("POST", f"/income-certifications/{cert_id}/advance",
                             payload, headers)

    # --- LotteryRun ---
    def create_lottery_run(self, payload, headers):
        return self._request("POST", "/lottery-runs", payload, headers)

    def list_lottery_runs(self, headers, params=None):
        return self._request("GET", "/lottery-runs", headers=headers, params=params)

    def get_lottery_run(self, run_id, headers):
        return self._request("GET", f"/lottery-runs/{run_id}", headers=headers)

    def transition_lottery_run(self, run_id, payload, headers):
        return self._request("POST", f"/lottery-runs/{run_id}/transition",
                             payload, headers)

    # --- WaitlistEntry ---
    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/waitlist-entries", headers=headers,
                             params=params)

    def get_waitlist_entry(self, entry_id, headers):
        return self._request("GET", f"/waitlist-entries/{entry_id}",
                             headers=headers)

    def confirm_interest(self, entry_id, headers):
        return self._request("POST",
                             f"/waitlist-entries/{entry_id}/confirm-interest",
                             {}, headers)

    def remove_waitlist_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/waitlist-entries/{entry_id}/remove",
                             payload, headers)

    # --- UnitOffer ---
    def generate_offers(self, payload, headers):
        return self._request("POST", "/offers/generate", payload, headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/offers", headers=headers, params=params)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/offers/{offer_id}", headers=headers)

    def respond_to_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/offers/{offer_id}/respond", payload,
                             headers)

    def expire_due_offers(self, headers):
        return self._request("POST", "/offers/expire-due", {}, headers)

    # --- PurgeRun ---
    def create_purge_run(self, payload, headers):
        return self._request("POST", "/purge-runs", payload, headers)

    def list_purge_runs(self, headers, params=None):
        return self._request("GET", "/purge-runs", headers=headers, params=params)

    def get_purge_run(self, purge_id, headers):
        return self._request("GET", f"/purge-runs/{purge_id}", headers=headers)

    def advance_purge_run(self, purge_id, payload, headers):
        return self._request("POST", f"/purge-runs/{purge_id}/advance", payload,
                             headers)

    # --- ComplianceReport ---
    def create_compliance_report(self, payload, headers):
        return self._request("POST", "/compliance-reports", payload, headers)

    def list_compliance_reports(self, headers, params=None):
        return self._request("GET", "/compliance-reports", headers=headers,
                             params=params)

    def get_compliance_report(self, report_id, headers):
        return self._request("GET", f"/compliance-reports/{report_id}",
                             headers=headers)

    def transition_compliance_report(self, report_id, payload, headers):
        return self._request("POST",
                             f"/compliance-reports/{report_id}/transition",
                             payload, headers)


api_client = ApiClient()
