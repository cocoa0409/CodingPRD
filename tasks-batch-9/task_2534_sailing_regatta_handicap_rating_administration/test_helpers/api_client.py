"""API client: one method per endpoint defined in the PRD.

Every path is rooted at the `/regatta-ops` prefix (PRD section 4).
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/regatta-ops"


class ApiClient(GenericApiClient):
    # ── Logical clock ─────────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    def set_clock_raw(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ── Club members ──────────────────────────────────────────────────────
    def create_club_member(self, payload, headers):
        return self._request("POST", f"{PREFIX}/club-members", payload, headers)

    def patch_club_member(self, member_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/club-members/{member_id}", payload, headers)

    def get_club_member(self, member_id, headers):
        return self._request("GET", f"{PREFIX}/club-members/{member_id}", headers=headers)

    def list_club_members(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/club-members", headers=headers, params=params)

    # ── Boats ─────────────────────────────────────────────────────────────
    def create_boat(self, payload, headers):
        return self._request("POST", f"{PREFIX}/boats", payload, headers)

    def get_boat(self, boat_id, headers):
        return self._request("GET", f"{PREFIX}/boats/{boat_id}", headers=headers)

    def list_boats(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/boats", headers=headers, params=params)

    # ── Rating certificates ───────────────────────────────────────────────
    def create_certificate(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rating-certificates", payload, headers)

    def issue_certificate(self, certificate_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rating-certificates/{certificate_id}/issue", {}, headers
        )

    def suspend_certificate(self, certificate_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/rating-certificates/{certificate_id}/suspend", payload, headers
        )

    def reinstate_certificate(self, certificate_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rating-certificates/{certificate_id}/reinstate", {}, headers
        )

    def get_certificate(self, certificate_id, headers):
        return self._request(
            "GET", f"{PREFIX}/rating-certificates/{certificate_id}", headers=headers
        )

    def list_certificates(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/rating-certificates", headers=headers, params=params
        )

    # ── Regattas ──────────────────────────────────────────────────────────
    def create_regatta(self, payload, headers):
        return self._request("POST", f"{PREFIX}/regattas", payload, headers)

    def open_racing(self, regatta_id, headers):
        return self._request("POST", f"{PREFIX}/regattas/{regatta_id}/open-racing", {}, headers)

    def get_regatta(self, regatta_id, headers):
        return self._request("GET", f"{PREFIX}/regattas/{regatta_id}", headers=headers)

    def list_regattas(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/regattas", headers=headers, params=params)

    # ── Race documents ────────────────────────────────────────────────────
    def create_race_document(self, payload, headers):
        return self._request("POST", f"{PREFIX}/race-documents", payload, headers)

    def get_race_document(self, document_id, headers):
        return self._request("GET", f"{PREFIX}/race-documents/{document_id}", headers=headers)

    def list_race_documents(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/race-documents", headers=headers, params=params)

    # ── Divisions ─────────────────────────────────────────────────────────
    def create_division(self, payload, headers):
        return self._request("POST", f"{PREFIX}/divisions", payload, headers)

    def confirm_division(self, division_id, headers):
        return self._request("POST", f"{PREFIX}/divisions/{division_id}/confirm", {}, headers)

    def merge_division(self, division_id, headers):
        return self._request("POST", f"{PREFIX}/divisions/{division_id}/merge", {}, headers)

    def get_division(self, division_id, headers):
        return self._request("GET", f"{PREFIX}/divisions/{division_id}", headers=headers)

    def list_divisions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/divisions", headers=headers, params=params)

    # ── Entries ───────────────────────────────────────────────────────────
    def create_entry(self, payload, headers):
        return self._request("POST", f"{PREFIX}/entries", payload, headers)

    def add_crew(self, entry_id, payload, headers):
        return self._request("POST", f"{PREFIX}/entries/{entry_id}/crew", payload, headers)

    def remove_crew(self, entry_id, member_id, headers):
        return self._request(
            "DELETE", f"{PREFIX}/entries/{entry_id}/crew/{member_id}", headers=headers
        )

    def assign_division(self, entry_id, headers):
        return self._request(
            "POST", f"{PREFIX}/entries/{entry_id}/assign-division", {}, headers
        )

    def inspect_entry(self, entry_id, payload, headers):
        return self._request("POST", f"{PREFIX}/entries/{entry_id}/inspect", payload, headers)

    def accept_entry(self, entry_id, headers):
        return self._request("POST", f"{PREFIX}/entries/{entry_id}/accept", {}, headers)

    def withdraw_entry(self, entry_id, headers):
        return self._request("POST", f"{PREFIX}/entries/{entry_id}/withdraw", {}, headers)

    def get_entry(self, entry_id, headers):
        return self._request("GET", f"{PREFIX}/entries/{entry_id}", headers=headers)

    def list_entries(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/entries", headers=headers, params=params)

    def get_series_standing(self, entry_id, headers):
        return self._request(
            "GET", f"{PREFIX}/entries/{entry_id}/series-standing", headers=headers
        )

    # ── Mark boats ────────────────────────────────────────────────────────
    def create_mark_boat(self, payload, headers):
        return self._request("POST", f"{PREFIX}/mark-boats", payload, headers)

    def get_mark_boat(self, mark_boat_id, headers):
        return self._request("GET", f"{PREFIX}/mark-boats/{mark_boat_id}", headers=headers)

    def list_mark_boats(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/mark-boats", headers=headers, params=params)

    # ── Duty assignments ──────────────────────────────────────────────────
    def create_duty_assignment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/duty-assignments", payload, headers)

    def confirm_duty_assignment(self, duty_id, headers):
        return self._request(
            "POST", f"{PREFIX}/duty-assignments/{duty_id}/confirm", {}, headers
        )

    def release_duty_assignment(self, duty_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/duty-assignments/{duty_id}/release", payload, headers
        )

    def get_duty_assignment(self, duty_id, headers):
        return self._request("GET", f"{PREFIX}/duty-assignments/{duty_id}", headers=headers)

    def list_duty_assignments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/duty-assignments", headers=headers, params=params
        )

    # ── Races ─────────────────────────────────────────────────────────────
    def create_race(self, payload, headers):
        return self._request("POST", f"{PREFIX}/races", payload, headers)

    def start_sequence(self, race_id, headers):
        return self._request("POST", f"{PREFIX}/races/{race_id}/start-sequence", {}, headers)

    def recall_race(self, race_id, payload, headers):
        return self._request("POST", f"{PREFIX}/races/{race_id}/recall", payload, headers)

    def start_race(self, race_id, payload, headers):
        return self._request("POST", f"{PREFIX}/races/{race_id}/start", payload, headers)

    def abandon_race(self, race_id, payload, headers):
        return self._request("POST", f"{PREFIX}/races/{race_id}/abandon", payload, headers)

    def score_race(self, race_id, headers):
        return self._request("POST", f"{PREFIX}/races/{race_id}/score", {}, headers)

    def get_race(self, race_id, headers):
        return self._request("GET", f"{PREFIX}/races/{race_id}", headers=headers)

    def list_races(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/races", headers=headers, params=params)

    def get_staffing(self, race_id, headers):
        return self._request("GET", f"{PREFIX}/races/{race_id}/staffing", headers=headers)

    # ── Race results ──────────────────────────────────────────────────────
    def create_race_result(self, payload, headers):
        return self._request("POST", f"{PREFIX}/race-results", payload, headers)

    def get_race_result(self, result_id, headers):
        return self._request("GET", f"{PREFIX}/race-results/{result_id}", headers=headers)

    def list_race_results(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/race-results", headers=headers, params=params)

    # ── Recall events ─────────────────────────────────────────────────────
    def get_recall_event(self, recall_event_id, headers):
        return self._request(
            "GET", f"{PREFIX}/recall-events/{recall_event_id}", headers=headers
        )

    def list_recall_events(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/recall-events", headers=headers, params=params)

    # ── Jury panels ───────────────────────────────────────────────────────
    def create_jury_panel(self, payload, headers):
        return self._request("POST", f"{PREFIX}/jury-panels", payload, headers)

    def seat_judge(self, panel_id, payload, headers):
        return self._request("POST", f"{PREFIX}/jury-panels/{panel_id}/seats", payload, headers)

    def recuse_judge(self, panel_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/jury-panels/{panel_id}/recuse", payload, headers
        )

    def get_jury_panel(self, panel_id, headers):
        return self._request("GET", f"{PREFIX}/jury-panels/{panel_id}", headers=headers)

    def list_jury_panels(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/jury-panels", headers=headers, params=params)

    # ── Protests ──────────────────────────────────────────────────────────
    def create_protest(self, payload, headers):
        return self._request("POST", f"{PREFIX}/protests", payload, headers)

    def file_evidence(self, protest_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/protests/{protest_id}/evidence", payload, headers
        )

    def schedule_hearing(self, protest_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/protests/{protest_id}/schedule-hearing", payload, headers
        )

    def hear_protest(self, protest_id, headers):
        return self._request("POST", f"{PREFIX}/protests/{protest_id}/hear", {}, headers)

    def decide_protest(self, protest_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/protests/{protest_id}/decide", payload, headers
        )

    def reopen_protest(self, protest_id, headers):
        return self._request("POST", f"{PREFIX}/protests/{protest_id}/reopen", {}, headers)

    def invalidate_protest(self, protest_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/protests/{protest_id}/invalidate", payload, headers
        )

    def get_protest(self, protest_id, headers):
        return self._request("GET", f"{PREFIX}/protests/{protest_id}", headers=headers)

    def list_protests(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/protests", headers=headers, params=params)


api_client = ApiClient()
