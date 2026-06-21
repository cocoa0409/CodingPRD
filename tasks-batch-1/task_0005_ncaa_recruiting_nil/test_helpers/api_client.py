"""API client: one method per endpoint defined in the PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Programs (PRD §3.1, §3.4) ──────────────────────
    def create_program(self, payload, headers):
        return self._request("POST", "/ncaa/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/ncaa/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/ncaa/programs", headers=headers, params=params)

    def get_program_utilization(self, program_id, headers, params=None):
        return self._request(
            "GET", f"/ncaa/programs/{program_id}/utilization",
            headers=headers, params=params,
        )

    # ─── Periods (PRD §3.1) ─────────────────────────────
    def create_period(self, program_id, payload, headers):
        return self._request(
            "POST", f"/ncaa/programs/{program_id}/periods", payload, headers,
        )

    def list_periods(self, program_id, headers, params=None):
        return self._request(
            "GET", f"/ncaa/programs/{program_id}/periods",
            headers=headers, params=params,
        )

    def get_period(self, period_id, headers):
        return self._request(
            "GET", f"/ncaa/periods/{period_id}", headers=headers,
        )

    # ─── StudentAthlete (PRD §3.2) ──────────────────────
    def create_student_athlete(self, payload, headers):
        return self._request("POST", "/ncaa/student-athletes", payload, headers)

    def get_student_athlete(self, athlete_id, headers):
        return self._request(
            "GET", f"/ncaa/student-athletes/{athlete_id}", headers=headers,
        )

    def list_student_athletes(self, headers, params=None):
        return self._request(
            "GET", "/ncaa/student-athletes", headers=headers, params=params,
        )

    # ─── EligibilityCertification (PRD §3.2) ────────────
    def create_eligibility_certification(self, payload, headers):
        return self._request(
            "POST", "/ncaa/eligibility-certifications", payload, headers,
        )

    def get_eligibility_certification(self, cert_id, headers):
        return self._request(
            "GET", f"/ncaa/eligibility-certifications/{cert_id}",
            headers=headers,
        )

    def list_eligibility_certifications(self, headers, params=None):
        return self._request(
            "GET", "/ncaa/eligibility-certifications",
            headers=headers, params=params,
        )

    def approve_eligibility_certification(self, cert_id, headers, payload=None):
        return self._request(
            "POST",
            f"/ncaa/eligibility-certifications/{cert_id}/approve",
            payload or {}, headers,
        )

    def deny_eligibility_certification(self, cert_id, payload, headers):
        return self._request(
            "POST",
            f"/ncaa/eligibility-certifications/{cert_id}/deny",
            payload, headers,
        )

    # ─── RecruitingContact (PRD §3.3) ───────────────────
    def create_recruiting_contact(self, payload, headers):
        return self._request(
            "POST", "/ncaa/recruiting-contacts", payload, headers,
        )

    def get_recruiting_contact(self, contact_id, headers):
        return self._request(
            "GET", f"/ncaa/recruiting-contacts/{contact_id}", headers=headers,
        )

    def list_recruiting_contacts(self, headers, params=None):
        return self._request(
            "GET", "/ncaa/recruiting-contacts", headers=headers, params=params,
        )

    # ─── ScholarshipOffer (PRD §3.4) ────────────────────
    def create_scholarship_offer(self, payload, headers):
        return self._request(
            "POST", "/ncaa/scholarship-offers", payload, headers,
        )

    def get_scholarship_offer(self, offer_id, headers):
        return self._request(
            "GET", f"/ncaa/scholarship-offers/{offer_id}", headers=headers,
        )

    def list_scholarship_offers(self, headers, params=None):
        return self._request(
            "GET", "/ncaa/scholarship-offers", headers=headers, params=params,
        )

    def send_scholarship_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/ncaa/scholarship-offers/{offer_id}/send",
            payload, headers,
        )

    def accept_scholarship_offer(self, offer_id, headers, payload=None):
        return self._request(
            "POST", f"/ncaa/scholarship-offers/{offer_id}/accept",
            payload or {}, headers,
        )

    def decline_scholarship_offer(self, offer_id, headers, payload=None):
        return self._request(
            "POST", f"/ncaa/scholarship-offers/{offer_id}/decline",
            payload or {}, headers,
        )

    def withdraw_scholarship_offer(self, offer_id, headers, payload=None):
        return self._request(
            "POST", f"/ncaa/scholarship-offers/{offer_id}/withdraw",
            payload or {}, headers,
        )

    # ─── NILDeal (PRD §3.5) ─────────────────────────────
    def create_nil_deal(self, payload, headers):
        return self._request("POST", "/ncaa/nil-deals", payload, headers)

    def get_nil_deal(self, deal_id, headers):
        return self._request(
            "GET", f"/ncaa/nil-deals/{deal_id}", headers=headers,
        )

    def list_nil_deals(self, headers, params=None):
        return self._request(
            "GET", "/ncaa/nil-deals", headers=headers, params=params,
        )

    def submit_nil_deal_for_review(self, deal_id, headers, payload=None):
        return self._request(
            "POST", f"/ncaa/nil-deals/{deal_id}/submit-for-review",
            payload or {}, headers,
        )

    def request_nil_deal_revision(self, deal_id, headers, payload=None):
        return self._request(
            "POST", f"/ncaa/nil-deals/{deal_id}/request-revision",
            payload or {}, headers,
        )

    def approve_nil_deal(self, deal_id, headers, payload=None):
        return self._request(
            "POST", f"/ncaa/nil-deals/{deal_id}/approve",
            payload or {}, headers,
        )

    def reject_nil_deal(self, deal_id, payload, headers):
        return self._request(
            "POST", f"/ncaa/nil-deals/{deal_id}/reject",
            payload, headers,
        )

    # ─── TransferPortalEntry (PRD §3.6) ─────────────────
    def create_transfer_portal_entry(self, payload, headers):
        return self._request(
            "POST", "/ncaa/transfer-portal-entries", payload, headers,
        )

    def get_transfer_portal_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/ncaa/transfer-portal-entries/{entry_id}",
            headers=headers,
        )

    def list_transfer_portal_entries(self, headers, params=None):
        return self._request(
            "GET", "/ncaa/transfer-portal-entries",
            headers=headers, params=params,
        )

    def match_transfer_portal_entry(self, entry_id, payload, headers):
        return self._request(
            "POST", f"/ncaa/transfer-portal-entries/{entry_id}/match",
            payload, headers,
        )

    def withdraw_transfer_portal_entry(self, entry_id, headers, payload=None):
        return self._request(
            "POST", f"/ncaa/transfer-portal-entries/{entry_id}/withdraw",
            payload or {}, headers,
        )

    # ─── BoosterIncident (PRD §3.7) ─────────────────────
    def create_booster_incident(self, payload, headers):
        return self._request(
            "POST", "/ncaa/booster-incidents", payload, headers,
        )

    def get_booster_incident(self, incident_id, headers):
        return self._request(
            "GET", f"/ncaa/booster-incidents/{incident_id}", headers=headers,
        )

    def list_booster_incidents(self, headers, params=None):
        return self._request(
            "GET", "/ncaa/booster-incidents", headers=headers, params=params,
        )

    def open_investigation(self, incident_id, headers, payload=None):
        return self._request(
            "POST",
            f"/ncaa/booster-incidents/{incident_id}/open-investigation",
            payload or {}, headers,
        )

    def sustain_booster_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/ncaa/booster-incidents/{incident_id}/sustain",
            payload, headers,
        )

    def dismiss_booster_incident(self, incident_id, headers, payload=None):
        return self._request(
            "POST", f"/ncaa/booster-incidents/{incident_id}/dismiss",
            payload or {}, headers,
        )

    # ─── Test-driving (PRD §2.8) ────────────────────────
    def set_clock(self, payload, headers):
        return self._request(
            "POST", "/ncaa/_clock/set_current_utc", payload, headers,
        )

    def sweep_portal_expirations(self, headers, payload=None):
        return self._request(
            "POST", "/ncaa/_jobs/sweep-portal-expirations",
            payload or {}, headers,
        )


api_client = ApiClient()
