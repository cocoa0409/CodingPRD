"""API client: one method per endpoint declared in the PRD.

Every route is mounted under the `/chw` prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/chw"


class ApiClient(GenericApiClient):
    """One method per endpoint. All methods return the raw response."""

    # ─── Logical clock ────────────────────────────────────────────────────

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ─── Community health workers ─────────────────────────────────────────

    def create_worker(self, payload, headers):
        return self._request("POST", f"{PREFIX}/workers", payload, headers)

    def get_worker(self, worker_id, headers):
        return self._request("GET", f"{PREFIX}/workers/{worker_id}", headers=headers)

    # ─── Patients ─────────────────────────────────────────────────────────

    def create_patient(self, payload, headers):
        return self._request("POST", f"{PREFIX}/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"{PREFIX}/patients/{patient_id}", headers=headers)

    def update_patient(self, patient_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/patients/{patient_id}", payload, headers
        )

    def records_hold(self, patient_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/patients/{patient_id}/records-hold", payload, headers
        )

    # ─── Screening instruments ────────────────────────────────────────────

    def create_instrument(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/screening-instruments", payload, headers
        )

    def get_instrument(self, instrument_id, headers):
        return self._request(
            "GET", f"{PREFIX}/screening-instruments/{instrument_id}", headers=headers
        )

    def publish_instrument(self, instrument_id, headers):
        return self._request(
            "POST", f"{PREFIX}/screening-instruments/{instrument_id}/publish",
            {}, headers,
        )

    def retire_instrument(self, instrument_id, headers):
        return self._request(
            "POST", f"{PREFIX}/screening-instruments/{instrument_id}/retire",
            {}, headers,
        )

    # ─── Screenings ───────────────────────────────────────────────────────

    def administer_screening(self, payload, headers):
        return self._request("POST", f"{PREFIX}/screenings", payload, headers)

    def get_screening(self, screening_id, headers):
        return self._request(
            "GET", f"{PREFIX}/screenings/{screening_id}", headers=headers
        )

    def list_screenings(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/screenings", headers=headers, params=params
        )

    # ─── Resource organizations ───────────────────────────────────────────

    def create_resource_org(self, payload, headers):
        return self._request("POST", f"{PREFIX}/resource-orgs", payload, headers)

    def get_resource_org(self, org_id, headers):
        return self._request(
            "GET", f"{PREFIX}/resource-orgs/{org_id}", headers=headers
        )

    def suspend_resource_org(self, org_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/resource-orgs/{org_id}/suspend", payload, headers
        )

    # ─── Offerings and eligibility ────────────────────────────────────────

    def create_offering(self, payload, headers):
        return self._request("POST", f"{PREFIX}/offerings", payload, headers)

    def get_offering(self, offering_id, headers):
        return self._request(
            "GET", f"{PREFIX}/offerings/{offering_id}", headers=headers
        )

    def list_offerings(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/offerings", headers=headers, params=params
        )

    def create_criterion(self, offering_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/offerings/{offering_id}/criteria", payload, headers
        )

    def list_criteria(self, offering_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/offerings/{offering_id}/criteria",
            headers=headers, params=params,
        )

    def eligibility_check(self, offering_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/offerings/{offering_id}/eligibility-check",
            payload, headers,
        )

    # ─── Referrals ────────────────────────────────────────────────────────

    def create_referral(self, payload, headers):
        return self._request("POST", f"{PREFIX}/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request(
            "GET", f"{PREFIX}/referrals/{referral_id}", headers=headers
        )

    def list_referrals(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/referrals", headers=headers, params=params
        )

    def respond_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/referrals/{referral_id}/respond", payload, headers
        )

    def deliver_referral(self, referral_id, headers):
        return self._request(
            "POST", f"{PREFIX}/referrals/{referral_id}/deliver", {}, headers
        )

    def close_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/referrals/{referral_id}/close", payload, headers
        )

    def reroute_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/referrals/{referral_id}/reroute", payload, headers
        )

    # ─── Home visits ──────────────────────────────────────────────────────

    def create_home_visit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/home-visits", payload, headers)

    def get_home_visit(self, visit_id, headers):
        return self._request(
            "GET", f"{PREFIX}/home-visits/{visit_id}", headers=headers
        )

    def list_home_visits(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/home-visits", headers=headers, params=params
        )

    def en_route_home_visit(self, visit_id, headers):
        return self._request(
            "POST", f"{PREFIX}/home-visits/{visit_id}/en-route", {}, headers
        )

    def complete_home_visit(self, visit_id, headers):
        return self._request(
            "POST", f"{PREFIX}/home-visits/{visit_id}/complete", {}, headers
        )

    def no_show_home_visit(self, visit_id, headers):
        return self._request(
            "POST", f"{PREFIX}/home-visits/{visit_id}/no-show", {}, headers
        )

    def cancel_home_visit(self, visit_id, headers):
        return self._request(
            "POST", f"{PREFIX}/home-visits/{visit_id}/cancel", {}, headers
        )

    def attest_home_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/home-visits/{visit_id}/attest", payload, headers
        )

    def revise_documentation(self, visit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/home-visits/{visit_id}/documentation-revision",
            payload, headers,
        )

    # ─── Care-plan goals ──────────────────────────────────────────────────

    def create_goal(self, payload, headers):
        return self._request("POST", f"{PREFIX}/goals", payload, headers)

    def get_goal(self, goal_id, headers):
        return self._request("GET", f"{PREFIX}/goals/{goal_id}", headers=headers)

    def list_goals(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/goals", headers=headers, params=params)

    def record_goal_progress(self, goal_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/goals/{goal_id}/progress", payload, headers
        )

    def close_goal(self, goal_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/goals/{goal_id}/close", payload, headers
        )

    def reopen_goal(self, goal_id, headers):
        return self._request("POST", f"{PREFIX}/goals/{goal_id}/reopen", {}, headers)

    # ─── Encounters ───────────────────────────────────────────────────────

    def create_encounter(self, payload, headers):
        return self._request("POST", f"{PREFIX}/encounters", payload, headers)

    def get_encounter(self, encounter_id, headers):
        return self._request(
            "GET", f"{PREFIX}/encounters/{encounter_id}", headers=headers
        )

    def list_encounters(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/encounters", headers=headers, params=params
        )

    def submit_encounter(self, encounter_id, headers):
        return self._request(
            "POST", f"{PREFIX}/encounters/{encounter_id}/submit", {}, headers
        )

    def void_encounter(self, encounter_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/encounters/{encounter_id}/void", payload, headers
        )

    # ─── Payer claims ─────────────────────────────────────────────────────

    def create_payer_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/payer-claims", payload, headers)

    def get_payer_claim(self, claim_id, headers):
        return self._request(
            "GET", f"{PREFIX}/payer-claims/{claim_id}", headers=headers
        )

    def list_payer_claims(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/payer-claims", headers=headers, params=params
        )

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/payer-claims/{claim_id}/adjudicate", payload, headers
        )

    def appeal_claim(self, claim_id, headers):
        return self._request(
            "POST", f"{PREFIX}/payer-claims/{claim_id}/appeal", {}, headers
        )

    def decide_appeal(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/payer-claims/{claim_id}/appeal-decision",
            payload, headers,
        )

    # ─── Grant awards and charge lines ────────────────────────────────────

    def create_grant_award(self, payload, headers):
        return self._request("POST", f"{PREFIX}/grant-awards", payload, headers)

    def get_grant_award(self, award_id, headers):
        return self._request(
            "GET", f"{PREFIX}/grant-awards/{award_id}", headers=headers
        )

    def close_grant_award(self, award_id, headers):
        return self._request(
            "POST", f"{PREFIX}/grant-awards/{award_id}/close", {}, headers
        )

    def create_charge_line(self, payload, headers):
        return self._request("POST", f"{PREFIX}/grant-charge-lines", payload, headers)

    def get_charge_line(self, line_id, headers):
        return self._request(
            "GET", f"{PREFIX}/grant-charge-lines/{line_id}", headers=headers
        )

    def list_charge_lines(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/grant-charge-lines", headers=headers, params=params
        )

    def reverse_charge_line(self, line_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/grant-charge-lines/{line_id}/reverse", payload, headers
        )

    # ─── Escalations ──────────────────────────────────────────────────────

    def create_escalation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/escalations", payload, headers)

    def get_escalation(self, escalation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/escalations/{escalation_id}", headers=headers
        )

    def list_escalations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/escalations", headers=headers, params=params
        )

    def acknowledge_escalation(self, escalation_id, headers):
        return self._request(
            "POST", f"{PREFIX}/escalations/{escalation_id}/acknowledge", {}, headers
        )

    def resolve_escalation(self, escalation_id, headers):
        return self._request(
            "POST", f"{PREFIX}/escalations/{escalation_id}/resolve", {}, headers
        )

    # ─── Sweeps and reporting ─────────────────────────────────────────────

    def run_sweep(self, sweep_type, headers):
        return self._request(
            "POST", f"{PREFIX}/ops/run-sweep", {"sweep_type": sweep_type}, headers
        )

    def program_summary(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/reports/program-summary", headers=headers, params=params
        )


api_client = ApiClient()
