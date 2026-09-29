"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Race editions
    # ------------------------------------------------------------------
    def create_race_edition(self, payload, headers):
        return self._request("POST", "/race-editions", payload, headers)

    def get_race_edition(self, edition_id, headers):
        return self._request("GET", f"/race-editions/{edition_id}", headers=headers)

    def open_field(self, edition_id, headers):
        return self._request(
            "POST", f"/race-editions/{edition_id}/open-field", {}, headers
        )

    def lock_field(self, edition_id, headers):
        return self._request(
            "POST", f"/race-editions/{edition_id}/lock-field", {}, headers
        )

    def mark_raced(self, edition_id, headers):
        return self._request(
            "POST", f"/race-editions/{edition_id}/mark-raced", {}, headers
        )

    def certify_results(self, edition_id, headers):
        return self._request(
            "POST", f"/race-editions/{edition_id}/certify-results", {}, headers
        )

    def compute_awards(self, edition_id, payload, headers):
        return self._request(
            "POST", f"/race-editions/{edition_id}/compute-awards", payload, headers
        )

    def settle_purse(self, edition_id, headers):
        return self._request(
            "POST", f"/race-editions/{edition_id}/settle-purse", {}, headers
        )

    def run_ops(self, edition_id, headers):
        return self._request(
            "POST", f"/race-editions/{edition_id}/run-ops", {}, headers
        )

    def list_purse_lines(self, edition_id, headers, params=None):
        return self._request(
            "GET", f"/race-editions/{edition_id}/purse-lines", headers=headers,
            params=params,
        )

    def list_division_standards(self, edition_id, headers, params=None):
        return self._request(
            "GET", f"/race-editions/{edition_id}/division-standards",
            headers=headers, params=params,
        )

    def list_pacer_assignments(self, edition_id, headers, params=None):
        return self._request(
            "GET", f"/race-editions/{edition_id}/pacer-assignments",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Purse structure
    # ------------------------------------------------------------------
    def create_purse_line(self, payload, headers):
        return self._request("POST", "/purse-lines", payload, headers)

    def create_division_standard(self, payload, headers):
        return self._request("POST", "/division-standards", payload, headers)

    # ------------------------------------------------------------------
    # Athletes and agents
    # ------------------------------------------------------------------
    def create_athlete(self, payload, headers):
        return self._request("POST", "/athletes", payload, headers)

    def get_athlete(self, athlete_id, headers):
        return self._request("GET", f"/athletes/{athlete_id}", headers=headers)

    def update_tax_profile(self, athlete_id, payload, headers):
        return self._request(
            "PATCH", f"/athletes/{athlete_id}/tax-profile", payload, headers
        )

    def list_performance_records(self, athlete_id, headers, params=None):
        return self._request(
            "GET", f"/athletes/{athlete_id}/performance-records",
            headers=headers, params=params,
        )

    def create_rep_agent(self, payload, headers):
        return self._request("POST", "/rep-agents", payload, headers)

    # ------------------------------------------------------------------
    # Performance records
    # ------------------------------------------------------------------
    def create_performance_record(self, payload, headers):
        return self._request("POST", "/performance-records", payload, headers)

    def verify_performance_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"/performance-records/{record_id}/verification", payload, headers
        )

    # ------------------------------------------------------------------
    # Invitations
    # ------------------------------------------------------------------
    def create_invitation(self, payload, headers):
        return self._request("POST", "/invitations", payload, headers)

    def get_invitation(self, invitation_id, headers):
        return self._request("GET", f"/invitations/{invitation_id}", headers=headers)

    def list_invitations(self, headers, params=None):
        return self._request("GET", "/invitations", headers=headers, params=params)

    def send_offer(self, invitation_id, payload, headers):
        return self._request(
            "POST", f"/invitations/{invitation_id}/offer", payload, headers
        )

    def create_negotiation_round(self, invitation_id, payload, headers):
        return self._request(
            "POST", f"/invitations/{invitation_id}/negotiation-rounds", payload, headers
        )

    def list_negotiation_rounds(self, invitation_id, headers, params=None):
        return self._request(
            "GET", f"/invitations/{invitation_id}/negotiation-rounds",
            headers=headers, params=params,
        )

    def respond_to_invitation(self, invitation_id, payload, headers):
        return self._request(
            "POST", f"/invitations/{invitation_id}/respond", payload, headers
        )

    def withdraw_invitation(self, invitation_id, payload, headers):
        return self._request(
            "POST", f"/invitations/{invitation_id}/withdraw", payload, headers
        )

    def assign_bib(self, invitation_id, headers):
        return self._request(
            "POST", f"/invitations/{invitation_id}/assign-bib", {}, headers
        )

    def list_fluid_station_slots(self, invitation_id, headers, params=None):
        return self._request(
            "GET", f"/invitations/{invitation_id}/fluid-station-slots",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Elite services
    # ------------------------------------------------------------------
    def create_fluid_station_slot(self, payload, headers):
        return self._request("POST", "/fluid-station-slots", payload, headers)

    def create_pacer_assignment(self, payload, headers):
        return self._request("POST", "/pacer-assignments", payload, headers)

    # ------------------------------------------------------------------
    # Doping tests
    # ------------------------------------------------------------------
    def create_doping_test(self, payload, headers):
        return self._request("POST", "/doping-tests", payload, headers)

    def get_doping_test(self, test_id, headers):
        return self._request("GET", f"/doping-tests/{test_id}", headers=headers)

    def list_doping_tests(self, headers, params=None):
        return self._request("GET", "/doping-tests", headers=headers, params=params)

    def collect_sample(self, test_id, payload, headers):
        return self._request(
            "POST", f"/doping-tests/{test_id}/collect", payload, headers
        )

    def adjudicate_doping_test(self, test_id, payload, headers):
        return self._request(
            "POST", f"/doping-tests/{test_id}/adjudicate", payload, headers
        )

    # ------------------------------------------------------------------
    # Race results
    # ------------------------------------------------------------------
    def create_race_result(self, payload, headers):
        return self._request("POST", "/race-results", payload, headers)

    def get_race_result(self, result_id, headers):
        return self._request("GET", f"/race-results/{result_id}", headers=headers)

    def list_race_results(self, headers, params=None):
        return self._request("GET", "/race-results", headers=headers, params=params)

    def certify_race_result(self, result_id, headers):
        return self._request(
            "POST", f"/race-results/{result_id}/certify", {}, headers
        )

    def disqualify_race_result(self, result_id, payload, headers):
        return self._request(
            "POST", f"/race-results/{result_id}/disqualify", payload, headers
        )

    def submit_record_package(self, result_id, payload, headers):
        return self._request(
            "POST", f"/race-results/{result_id}/record-submission", payload, headers
        )

    def decide_record_claim(self, result_id, payload, headers):
        return self._request(
            "POST", f"/race-results/{result_id}/record-decision", payload, headers
        )

    # ------------------------------------------------------------------
    # Prize awards
    # ------------------------------------------------------------------
    def get_prize_award(self, award_id, headers):
        return self._request("GET", f"/prize-awards/{award_id}", headers=headers)

    def list_prize_awards(self, headers, params=None):
        return self._request("GET", "/prize-awards", headers=headers, params=params)

    def approve_prize_award(self, award_id, headers):
        return self._request(
            "POST", f"/prize-awards/{award_id}/approve", {}, headers
        )

    def pay_prize_award(self, award_id, payload, headers):
        return self._request("POST", f"/prize-awards/{award_id}/pay", payload, headers)

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
