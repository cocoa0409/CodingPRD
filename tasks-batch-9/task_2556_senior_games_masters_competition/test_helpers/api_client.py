"""API client: one method per endpoint described in the PRD.

Every route is mounted beneath the /senior-games prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/senior-games"


class ApiClient(GenericApiClient):
    # ---------------- logical clock ----------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    def set_clock_raw(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ---------------- games editions ----------------
    def create_games_edition(self, payload, headers):
        return self._request("POST", f"{PREFIX}/games-editions", payload, headers)

    def get_games_edition(self, games_edition_id, headers):
        return self._request("GET", f"{PREFIX}/games-editions/{games_edition_id}", headers=headers)

    def list_games_editions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/games-editions", headers=headers, params=params)

    def open_registration(self, games_edition_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/games-editions/{games_edition_id}/open-registration",
            payload if payload is not None else {}, headers,
        )

    def ops_run(self, games_edition_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/games-editions/{games_edition_id}/ops-run",
            payload if payload is not None else {}, headers,
        )

    def finalize_impact(self, games_edition_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/games-editions/{games_edition_id}/finalize-impact",
            payload if payload is not None else {}, headers,
        )

    def get_economic_impact(self, games_edition_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/games-editions/{games_edition_id}/economic-impact",
            headers=headers, params=params,
        )

    # ---------------- sports ----------------
    def create_sport(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sports", payload, headers)

    def get_sport(self, sport_id, headers):
        return self._request("GET", f"{PREFIX}/sports/{sport_id}", headers=headers)

    def list_sports(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sports", headers=headers, params=params)

    # ---------------- sport events ----------------
    def create_sport_event(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sport-events", payload, headers)

    def get_sport_event(self, sport_event_id, headers):
        return self._request("GET", f"{PREFIX}/sport-events/{sport_event_id}", headers=headers)

    def list_sport_events(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sport-events", headers=headers, params=params)

    def seed_sport_event(self, sport_event_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/sport-events/{sport_event_id}/seed",
            payload if payload is not None else {}, headers,
        )

    def cancel_sport_event(self, sport_event_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sport-events/{sport_event_id}/cancel", payload, headers,
        )

    # ---------------- venues ----------------
    def create_venue(self, payload, headers):
        return self._request("POST", f"{PREFIX}/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"{PREFIX}/venues/{venue_id}", headers=headers)

    def list_venues(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/venues", headers=headers, params=params)

    def close_venue(self, venue_id, payload, headers):
        return self._request("POST", f"{PREFIX}/venues/{venue_id}/close", payload, headers)

    # ---------------- session slots ----------------
    def create_session_slot(self, payload, headers):
        return self._request("POST", f"{PREFIX}/session-slots", payload, headers)

    def get_session_slot(self, session_slot_id, headers):
        return self._request("GET", f"{PREFIX}/session-slots/{session_slot_id}", headers=headers)

    def list_session_slots(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/session-slots", headers=headers, params=params)

    def reschedule_session_slot(self, session_slot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/session-slots/{session_slot_id}/reschedule", payload, headers,
        )

    def advance_session_slot(self, session_slot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/session-slots/{session_slot_id}/advance", payload, headers,
        )

    # ---------------- athletes ----------------
    def create_athlete(self, payload, headers):
        return self._request("POST", f"{PREFIX}/athletes", payload, headers)

    def get_athlete(self, athlete_id, headers):
        return self._request("GET", f"{PREFIX}/athletes/{athlete_id}", headers=headers)

    def list_athletes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/athletes", headers=headers, params=params)

    def pay_fees(self, athlete_id, payload, headers):
        return self._request("POST", f"{PREFIX}/athletes/{athlete_id}/pay-fees", payload, headers)

    def check_in_athlete(self, athlete_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/athletes/{athlete_id}/check-in",
            payload if payload is not None else {}, headers,
        )

    def withdraw_athlete(self, athlete_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/athletes/{athlete_id}/withdraw",
            payload if payload is not None else {}, headers,
        )

    def medical_appeal(self, athlete_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/athletes/{athlete_id}/medical-appeal", payload, headers,
        )

    # ---------------- qualifying results ----------------
    def create_qualifying_result(self, payload, headers):
        return self._request("POST", f"{PREFIX}/qualifying-results", payload, headers)

    def get_qualifying_result(self, qualifying_result_id, headers):
        return self._request(
            "GET", f"{PREFIX}/qualifying-results/{qualifying_result_id}", headers=headers,
        )

    def list_qualifying_results(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/qualifying-results", headers=headers, params=params)

    # ---------------- sport entries ----------------
    def create_sport_entry(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sport-entries", payload, headers)

    def get_sport_entry(self, sport_entry_id, headers):
        return self._request("GET", f"{PREFIX}/sport-entries/{sport_entry_id}", headers=headers)

    def list_sport_entries(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sport-entries", headers=headers, params=params)

    def review_sport_entry(self, sport_entry_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sport-entries/{sport_entry_id}/review", payload, headers,
        )

    def resubmit_sport_entry(self, sport_entry_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sport-entries/{sport_entry_id}/resubmit", payload, headers,
        )

    def withdraw_sport_entry(self, sport_entry_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/sport-entries/{sport_entry_id}/withdraw",
            payload if payload is not None else {}, headers,
        )

    # ---------------- medical screenings ----------------
    def create_medical_screening(self, payload, headers):
        return self._request("POST", f"{PREFIX}/medical-screenings", payload, headers)

    def get_medical_screening(self, medical_screening_id, headers):
        return self._request(
            "GET", f"{PREFIX}/medical-screenings/{medical_screening_id}", headers=headers,
        )

    def list_medical_screenings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/medical-screenings", headers=headers, params=params)

    # ---------------- personnel ----------------
    def create_personnel(self, payload, headers):
        return self._request("POST", f"{PREFIX}/personnel", payload, headers)

    def get_personnel(self, personnel_id, headers):
        return self._request("GET", f"{PREFIX}/personnel/{personnel_id}", headers=headers)

    def list_personnel(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/personnel", headers=headers, params=params)

    # ---------------- personnel assignments ----------------
    def create_personnel_assignment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/personnel-assignments", payload, headers)

    def get_personnel_assignment(self, personnel_assignment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/personnel-assignments/{personnel_assignment_id}", headers=headers,
        )

    def list_personnel_assignments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/personnel-assignments", headers=headers, params=params,
        )

    def confirm_personnel_assignment(self, personnel_assignment_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/personnel-assignments/{personnel_assignment_id}/confirm",
            payload if payload is not None else {}, headers,
        )

    def release_personnel_assignment(self, personnel_assignment_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/personnel-assignments/{personnel_assignment_id}/release",
            payload if payload is not None else {}, headers,
        )

    # ---------------- competition results ----------------
    def create_competition_result(self, payload, headers):
        return self._request("POST", f"{PREFIX}/competition-results", payload, headers)

    def get_competition_result(self, competition_result_id, headers):
        return self._request(
            "GET", f"{PREFIX}/competition-results/{competition_result_id}", headers=headers,
        )

    def list_competition_results(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/competition-results", headers=headers, params=params)

    def verify_competition_result(self, competition_result_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/competition-results/{competition_result_id}/verify",
            payload if payload is not None else {}, headers,
        )

    def publish_competition_result(self, competition_result_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/competition-results/{competition_result_id}/publish",
            payload if payload is not None else {}, headers,
        )

    def protest_competition_result(self, competition_result_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/competition-results/{competition_result_id}/protest",
            payload, headers,
        )

    def resolve_protest(self, competition_result_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/competition-results/{competition_result_id}/resolve-protest",
            payload, headers,
        )

    # ---------------- age group records ----------------
    def create_age_group_record(self, payload, headers):
        return self._request("POST", f"{PREFIX}/age-group-records", payload, headers)

    def get_age_group_record(self, age_group_record_id, headers):
        return self._request(
            "GET", f"{PREFIX}/age-group-records/{age_group_record_id}", headers=headers,
        )

    def list_age_group_records(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/age-group-records", headers=headers, params=params)

    def ratify_age_group_record(self, age_group_record_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/age-group-records/{age_group_record_id}/ratify", payload, headers,
        )

    # ---------------- accommodation blocks ----------------
    def create_accommodation_block(self, payload, headers):
        return self._request("POST", f"{PREFIX}/accommodation-blocks", payload, headers)

    def get_accommodation_block(self, accommodation_block_id, headers):
        return self._request(
            "GET", f"{PREFIX}/accommodation-blocks/{accommodation_block_id}", headers=headers,
        )

    def list_accommodation_blocks(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/accommodation-blocks", headers=headers, params=params,
        )

    # ---------------- village stays ----------------
    def create_village_stay(self, payload, headers):
        return self._request("POST", f"{PREFIX}/village-stays", payload, headers)

    def get_village_stay(self, village_stay_id, headers):
        return self._request("GET", f"{PREFIX}/village-stays/{village_stay_id}", headers=headers)

    def list_village_stays(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/village-stays", headers=headers, params=params)

    def cancel_village_stay(self, village_stay_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/village-stays/{village_stay_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    # ---------------- sponsorship commitments ----------------
    def create_sponsorship_commitment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sponsorship-commitments", payload, headers)

    def get_sponsorship_commitment(self, sponsorship_commitment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/sponsorship-commitments/{sponsorship_commitment_id}", headers=headers,
        )

    def list_sponsorship_commitments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/sponsorship-commitments", headers=headers, params=params,
        )

    def allocate_sponsorship_commitment(self, sponsorship_commitment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sponsorship-commitments/{sponsorship_commitment_id}/allocate",
            payload, headers,
        )

    def withdraw_sponsorship_commitment(self, sponsorship_commitment_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/sponsorship-commitments/{sponsorship_commitment_id}/withdraw",
            payload if payload is not None else {}, headers,
        )


api_client = ApiClient()
