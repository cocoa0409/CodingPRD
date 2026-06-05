"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Community ----
    def create_community(self, payload, headers):
        return self._request("POST", "/communities", payload, headers)

    def get_community(self, community_id, headers):
        return self._request("GET", f"/communities/{community_id}", headers=headers)

    # ---- Lot ----
    def create_lot(self, payload, headers):
        return self._request("POST", "/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/lots", headers=headers, params=params)

    # ---- Resident ----
    def create_resident(self, payload, headers):
        return self._request("POST", "/residents", payload, headers)

    def get_resident(self, resident_id, headers):
        return self._request("GET", f"/residents/{resident_id}", headers=headers)

    def list_residents(self, headers, params=None):
        return self._request("GET", "/residents", headers=headers, params=params)

    # ---- LotLease ----
    def create_lease(self, payload, headers):
        return self._request("POST", "/lot-leases", payload, headers)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/lot-leases/{lease_id}", headers=headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/lot-leases", headers=headers, params=params)

    def activate_lease(self, lease_id, headers, payload=None):
        return self._request(
            "POST", f"/lot-leases/{lease_id}/activate", payload or {}, headers
        )

    def post_payment(self, lease_id, amount_cents, headers):
        return self._request(
            "POST",
            f"/lot-leases/{lease_id}/payments",
            {"amount_cents": amount_cents},
            headers,
        )

    # ---- RentSchedule ----
    def create_rent_schedule(self, payload, headers):
        return self._request("POST", "/rent-schedules", payload, headers)

    def get_rent_schedule(self, sched_id, headers):
        return self._request("GET", f"/rent-schedules/{sched_id}", headers=headers)

    def list_rent_schedules(self, headers, params=None):
        return self._request("GET", "/rent-schedules", headers=headers, params=params)

    def accept_rent_schedule(self, sched_id, headers):
        return self._request(
            "POST", f"/rent-schedules/{sched_id}/accept", {}, headers
        )

    def contest_rent_schedule(self, sched_id, headers):
        return self._request(
            "POST", f"/rent-schedules/{sched_id}/contest", {}, headers
        )

    def revise_rent_schedule(self, sched_id, proposed_rent_cents, headers):
        return self._request(
            "POST",
            f"/rent-schedules/{sched_id}/revise",
            {"proposed_rent_cents": proposed_rent_cents},
            headers,
        )

    def apply_rent_schedule(self, sched_id, headers):
        return self._request(
            "POST", f"/rent-schedules/{sched_id}/apply", {}, headers
        )

    def withdraw_rent_schedule(self, sched_id, headers):
        return self._request(
            "POST", f"/rent-schedules/{sched_id}/withdraw", {}, headers
        )

    # ---- UtilityBill / readings / charges ----
    def create_utility_bill(self, payload, headers):
        return self._request("POST", "/utility-bills", payload, headers)

    def get_utility_bill(self, bill_id, headers):
        return self._request("GET", f"/utility-bills/{bill_id}", headers=headers)

    def list_utility_bills(self, headers, params=None):
        return self._request("GET", "/utility-bills", headers=headers, params=params)

    def create_reading(self, bill_id, payload, headers):
        return self._request(
            "POST", f"/utility-bills/{bill_id}/readings", payload, headers
        )

    def get_reading(self, reading_id, headers):
        return self._request(
            "GET", f"/utility-readings/{reading_id}", headers=headers
        )

    def list_readings(self, headers, params=None):
        return self._request(
            "GET", "/utility-readings", headers=headers, params=params
        )

    def apportion_bill(self, bill_id, headers):
        return self._request(
            "POST", f"/utility-bills/{bill_id}/apportion", {}, headers
        )

    def get_utility_charge(self, charge_id, headers):
        return self._request(
            "GET", f"/utility-charges/{charge_id}", headers=headers
        )

    def list_utility_charges(self, headers, params=None):
        return self._request(
            "GET", "/utility-charges", headers=headers, params=params
        )

    # ---- Ledger ----
    def get_ledger_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/lot-ledger-entries/{entry_id}", headers=headers
        )

    def list_ledger_entries(self, headers, params=None):
        return self._request(
            "GET", "/lot-ledger-entries", headers=headers, params=params
        )

    # ---- EvictionCase ----
    def create_eviction_case(self, payload, headers):
        return self._request("POST", "/eviction-cases", payload, headers)

    def get_eviction_case(self, case_id, headers):
        return self._request("GET", f"/eviction-cases/{case_id}", headers=headers)

    def list_eviction_cases(self, headers, params=None):
        return self._request("GET", "/eviction-cases", headers=headers, params=params)

    def cure_eviction(self, case_id, headers):
        return self._request(
            "POST", f"/eviction-cases/{case_id}/cure", {}, headers
        )

    def adjudicate_eviction(self, case_id, headers):
        return self._request(
            "POST", f"/eviction-cases/{case_id}/adjudicate", {}, headers
        )

    def dismiss_eviction(self, case_id, headers):
        return self._request(
            "POST", f"/eviction-cases/{case_id}/dismiss", {}, headers
        )

    # ---- ConversionVote / ballots ----
    def create_conversion_vote(self, payload, headers):
        return self._request("POST", "/conversion-votes", payload, headers)

    def get_conversion_vote(self, vote_id, headers):
        return self._request(
            "GET", f"/conversion-votes/{vote_id}", headers=headers
        )

    def list_conversion_votes(self, headers, params=None):
        return self._request(
            "GET", "/conversion-votes", headers=headers, params=params
        )

    def open_conversion_vote(self, vote_id, headers):
        return self._request(
            "POST", f"/conversion-votes/{vote_id}/open", {}, headers
        )

    def cast_ballot(self, vote_id, payload, headers):
        return self._request(
            "POST", f"/conversion-votes/{vote_id}/ballots", payload, headers
        )

    def list_vote_ballots(self, vote_id, headers, params=None):
        return self._request(
            "GET", f"/conversion-votes/{vote_id}/ballots", headers=headers, params=params
        )

    def get_ballot(self, ballot_id, headers):
        return self._request(
            "GET", f"/conversion-ballots/{ballot_id}", headers=headers
        )

    def list_ballots(self, headers, params=None):
        return self._request(
            "GET", "/conversion-ballots", headers=headers, params=params
        )

    def tally_conversion_vote(self, vote_id, headers):
        return self._request(
            "POST", f"/conversion-votes/{vote_id}/tally", {}, headers
        )

    # ---- Generic raw helpers (header-omission / malformed tests) ----
    def raw_get(self, path, headers):
        return self._request("GET", path, headers=headers)

    def raw_post(self, path, payload, headers):
        return self._request("POST", path, payload, headers)


api_client = ApiClient()
