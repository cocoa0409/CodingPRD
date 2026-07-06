"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers
        )

    # ---- Elections ----
    def create_election(self, payload, headers):
        return self._request("POST", "/elections", payload, headers=headers)

    def get_election(self, election_id, headers):
        return self._request("GET", f"/elections/{election_id}", headers=headers)

    def open_voting(self, election_id, headers):
        return self._request("POST", f"/elections/{election_id}/open-voting", {}, headers=headers)

    def close_voting(self, election_id, headers):
        return self._request("POST", f"/elections/{election_id}/close-voting", {}, headers=headers)

    # ---- Polling places ----
    def create_polling_place(self, payload, headers):
        return self._request("POST", "/polling-places", payload, headers=headers)

    def get_polling_place(self, place_id, headers):
        return self._request("GET", f"/polling-places/{place_id}", headers=headers)

    def list_polling_places(self, headers, params=None):
        return self._request("GET", "/polling-places", headers=headers, params=params)

    def open_place(self, place_id, headers):
        return self._request("POST", f"/polling-places/{place_id}/open", {}, headers=headers)

    def suspend_place(self, place_id, headers, payload=None):
        return self._request(
            "POST", f"/polling-places/{place_id}/suspend", payload or {}, headers=headers
        )

    def resume_place(self, place_id, headers):
        return self._request("POST", f"/polling-places/{place_id}/resume", {}, headers=headers)

    def close_place(self, place_id, headers):
        return self._request("POST", f"/polling-places/{place_id}/close", {}, headers=headers)

    def reconcile_place(self, place_id, payload, headers):
        return self._request(
            "POST", f"/polling-places/{place_id}/reconcile", payload, headers=headers
        )

    # ---- Equipment ----
    def create_equipment(self, payload, headers):
        return self._request("POST", "/equipment", payload, headers=headers)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/equipment/{equipment_id}", headers=headers)

    def list_equipment(self, headers, params=None):
        return self._request("GET", "/equipment", headers=headers, params=params)

    def deploy_equipment(self, equipment_id, payload, headers):
        return self._request(
            "POST", f"/equipment/{equipment_id}/deploy", payload, headers=headers
        )

    # ---- Poll workers ----
    def create_poll_worker(self, payload, headers):
        return self._request("POST", "/poll-workers", payload, headers=headers)

    def get_poll_worker(self, worker_id, headers):
        return self._request("GET", f"/poll-workers/{worker_id}", headers=headers)

    def complete_training(self, worker_id, headers):
        return self._request(
            "POST", f"/poll-workers/{worker_id}/complete-training", {}, headers=headers
        )

    # ---- Assignments ----
    def create_assignment(self, payload, headers):
        return self._request("POST", "/assignments", payload, headers=headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def activate_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/assignments/{assignment_id}/activate", {}, headers=headers
        )

    def withdraw_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/assignments/{assignment_id}/withdraw", {}, headers=headers
        )

    # ---- Shifts ----
    def create_shift(self, payload, headers):
        return self._request("POST", "/shifts", payload, headers=headers)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/shifts/{shift_id}", headers=headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/shifts", headers=headers, params=params)

    def check_in(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/check-in", {}, headers=headers)

    def check_out(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/check-out", {}, headers=headers)

    # ---- Supply kits ----
    def create_supply_kit(self, payload, headers):
        return self._request("POST", "/supply-kits", payload, headers=headers)

    def get_supply_kit(self, kit_id, headers):
        return self._request("GET", f"/supply-kits/{kit_id}", headers=headers)

    def list_supply_kits(self, headers, params=None):
        return self._request("GET", "/supply-kits", headers=headers, params=params)

    def create_custody_event(self, kit_id, payload, headers):
        return self._request(
            "POST", f"/supply-kits/{kit_id}/custody-events", payload, headers=headers
        )

    def list_custody_events(self, kit_id, headers, params=None):
        return self._request(
            "GET", f"/supply-kits/{kit_id}/custody-events", headers=headers, params=params
        )

    # ---- Provisional ballots ----
    def create_provisional_ballot(self, payload, headers):
        return self._request("POST", "/provisional-ballots", payload, headers=headers)

    def get_provisional_ballot(self, ballot_id, headers):
        return self._request("GET", f"/provisional-ballots/{ballot_id}", headers=headers)

    def list_provisional_ballots(self, headers, params=None):
        return self._request("GET", "/provisional-ballots", headers=headers, params=params)

    def adjudicate_provisional(self, ballot_id, payload, headers):
        return self._request(
            "POST", f"/provisional-ballots/{ballot_id}/adjudicate", payload, headers=headers
        )

    # ---- Incidents ----
    def create_incident(self, payload, headers):
        return self._request("POST", "/incidents", payload, headers=headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/incidents/{incident_id}", headers=headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/incidents", headers=headers, params=params)

    def acknowledge_incident(self, incident_id, headers):
        return self._request(
            "POST", f"/incidents/{incident_id}/acknowledge", {}, headers=headers
        )

    def escalate_incident(self, incident_id, headers):
        return self._request(
            "POST", f"/incidents/{incident_id}/escalate", {}, headers=headers
        )

    def resolve_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/incidents/{incident_id}/resolve", payload, headers=headers
        )


api_client = ApiClient()
