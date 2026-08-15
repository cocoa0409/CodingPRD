"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (SystemAdmin-only test-driving capability)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Admission cycles
    # ------------------------------------------------------------------
    def create_cycle(self, payload, headers):
        return self._request("POST", "/enrollment/cycles", payload, headers)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/enrollment/cycles/{cycle_id}",
                             headers=headers)

    def advance_cycle(self, cycle_id, to_status, headers):
        return self._request("POST", f"/enrollment/cycles/{cycle_id}/advance",
                             {"to_status": to_status}, headers)

    def get_cycle_forecast(self, cycle_id, headers, params=None):
        return self._request("GET", f"/enrollment/cycles/{cycle_id}/forecast",
                             headers=headers, params=params)

    def get_cycle_funnel_report(self, cycle_id, headers):
        return self._request("GET",
                             f"/enrollment/cycles/{cycle_id}/funnel-report",
                             headers=headers)

    def melt_sweep_cycle(self, cycle_id, headers):
        return self._request("POST", f"/enrollment/cycles/{cycle_id}/melt-sweep",
                             {}, headers)

    # ------------------------------------------------------------------
    # Programs
    # ------------------------------------------------------------------
    def create_program(self, payload, headers):
        return self._request("POST", "/enrollment/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/enrollment/programs/{program_id}",
                             headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/enrollment/programs",
                             headers=headers, params=params)

    def patch_program(self, program_id, payload, headers):
        return self._request("PATCH", f"/enrollment/programs/{program_id}",
                             payload, headers)

    # ------------------------------------------------------------------
    # Applicants
    # ------------------------------------------------------------------
    def create_applicant(self, payload, headers):
        return self._request("POST", "/enrollment/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/enrollment/applicants/{applicant_id}",
                             headers=headers)

    def list_applicants(self, headers, params=None):
        return self._request("GET", "/enrollment/applicants",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Applications
    # ------------------------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", "/enrollment/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/enrollment/applications/{application_id}",
                             headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/enrollment/applications",
                             headers=headers, params=params)

    def transition_application(self, application_id, to_status, headers):
        return self._request(
            "POST", f"/enrollment/applications/{application_id}/transition",
            {"to_status": to_status}, headers)

    # ------------------------------------------------------------------
    # Committee reviews
    # ------------------------------------------------------------------
    def create_review(self, payload, headers):
        return self._request("POST", "/enrollment/reviews", payload, headers)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/enrollment/reviews/{review_id}",
                             headers=headers)

    def list_reviews(self, headers, params=None):
        return self._request("GET", "/enrollment/reviews",
                             headers=headers, params=params)

    def submit_review(self, review_id, payload, headers):
        return self._request("POST", f"/enrollment/reviews/{review_id}/submit",
                             payload, headers)

    # ------------------------------------------------------------------
    # Aid offers
    # ------------------------------------------------------------------
    def create_aid_offer(self, payload, headers):
        return self._request("POST", "/enrollment/aid-offers", payload, headers)

    def get_aid_offer(self, aid_offer_id, headers):
        return self._request("GET", f"/enrollment/aid-offers/{aid_offer_id}",
                             headers=headers)

    def list_aid_offers(self, headers, params=None):
        return self._request("GET", "/enrollment/aid-offers",
                             headers=headers, params=params)

    def transition_aid_offer(self, aid_offer_id, to_status, headers):
        return self._request(
            "POST", f"/enrollment/aid-offers/{aid_offer_id}/transition",
            {"to_status": to_status}, headers)

    # ------------------------------------------------------------------
    # Deposits
    # ------------------------------------------------------------------
    def create_deposit(self, payload, headers):
        return self._request("POST", "/enrollment/deposits", payload, headers)

    def get_deposit(self, deposit_id, headers):
        return self._request("GET", f"/enrollment/deposits/{deposit_id}",
                             headers=headers)

    def list_deposits(self, headers, params=None):
        return self._request("GET", "/enrollment/deposits",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Waitlist
    # ------------------------------------------------------------------
    def get_waitlist_entry(self, entry_id, headers):
        return self._request("GET",
                             f"/enrollment/waitlist-entries/{entry_id}",
                             headers=headers)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/enrollment/waitlist-entries",
                             headers=headers, params=params)

    def activate_waitlist(self, program_id, headers):
        return self._request("POST", "/enrollment/waitlist-activations",
                             {"program_id": program_id}, headers)

    # ------------------------------------------------------------------
    # Melt interventions
    # ------------------------------------------------------------------
    def create_intervention(self, payload, headers):
        return self._request("POST", "/enrollment/interventions", payload, headers)

    def get_intervention(self, intervention_id, headers):
        return self._request("GET",
                             f"/enrollment/interventions/{intervention_id}",
                             headers=headers)

    def list_interventions(self, headers, params=None):
        return self._request("GET", "/enrollment/interventions",
                             headers=headers, params=params)

    def transition_intervention(self, intervention_id, to_status, headers,
                                outcome=None):
        payload = {"to_status": to_status}
        if outcome is not None:
            payload["outcome"] = outcome
        return self._request(
            "POST", f"/enrollment/interventions/{intervention_id}/transition",
            payload, headers)


api_client = ApiClient()
