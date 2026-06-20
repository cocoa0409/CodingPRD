"""API client: one method per endpoint defined in the PRD.

All endpoints are mounted under the root path `/ccrc` (PRD §4). The base
`_request()` method is inherited from GenericApiClient.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Communities ─────────────────────────────────────────────────
    def create_community(self, payload, headers):
        return self._request("POST", "/ccrc/communities", payload, headers)

    def list_communities(self, headers, params=None):
        return self._request(
            "GET", "/ccrc/communities", headers=headers, params=params,
        )

    def get_community(self, community_id, headers):
        return self._request(
            "GET", f"/ccrc/communities/{community_id}", headers=headers,
        )

    def advance_clock(self, community_id, payload, headers):
        return self._request(
            "POST", f"/ccrc/communities/{community_id}/clock/advance",
            payload, headers,
        )

    def create_reserve_report(self, community_id, payload, headers):
        return self._request(
            "POST", f"/ccrc/communities/{community_id}/reserve-reports",
            payload, headers,
        )

    # ── Contract Plans ──────────────────────────────────────────────
    def create_contract_plan(self, payload, headers):
        return self._request("POST", "/ccrc/contract-plans", payload, headers)

    def list_contract_plans(self, headers, params=None):
        return self._request(
            "GET", "/ccrc/contract-plans", headers=headers, params=params,
        )

    def get_contract_plan(self, plan_id, headers):
        return self._request(
            "GET", f"/ccrc/contract-plans/{plan_id}", headers=headers,
        )

    # ── Units ───────────────────────────────────────────────────────
    def create_unit(self, payload, headers):
        return self._request("POST", "/ccrc/units", payload, headers)

    def list_units(self, headers, params=None):
        return self._request(
            "GET", "/ccrc/units", headers=headers, params=params,
        )

    def get_unit(self, unit_id, headers):
        return self._request(
            "GET", f"/ccrc/units/{unit_id}", headers=headers,
        )

    # ── Residents ───────────────────────────────────────────────────
    def create_resident(self, payload, headers):
        return self._request("POST", "/ccrc/residents", payload, headers)

    def list_residents(self, headers, params=None):
        return self._request(
            "GET", "/ccrc/residents", headers=headers, params=params,
        )

    def get_resident(self, resident_id, headers):
        return self._request(
            "GET", f"/ccrc/residents/{resident_id}", headers=headers,
        )

    # ── Residencies ─────────────────────────────────────────────────
    def create_residency(self, payload, headers):
        return self._request("POST", "/ccrc/residencies", payload, headers)

    def list_residencies(self, headers, params=None):
        return self._request(
            "GET", "/ccrc/residencies", headers=headers, params=params,
        )

    def get_residency(self, residency_id, headers):
        return self._request(
            "GET", f"/ccrc/residencies/{residency_id}", headers=headers,
        )

    def assign_unit(self, residency_id, payload, headers):
        return self._request(
            "POST", f"/ccrc/residencies/{residency_id}/assign-unit",
            payload, headers,
        )

    def activate_residency(self, residency_id, payload, headers):
        return self._request(
            "POST", f"/ccrc/residencies/{residency_id}/activate",
            payload, headers,
        )

    def terminate_residency(self, residency_id, payload, headers):
        return self._request(
            "POST", f"/ccrc/residencies/{residency_id}/terminate",
            payload, headers,
        )

    def issue_invoice(self, residency_id, payload, headers):
        return self._request(
            "POST", f"/ccrc/residencies/{residency_id}/invoices",
            payload, headers,
        )

    # ── Second Persons ──────────────────────────────────────────────
    def add_second_person(self, residency_id, payload, headers):
        return self._request(
            "POST", f"/ccrc/residencies/{residency_id}/second-persons",
            payload, headers,
        )

    def list_second_persons(self, headers, params=None):
        return self._request(
            "GET", "/ccrc/second-persons", headers=headers, params=params,
        )

    def get_second_person(self, sp_id, headers):
        return self._request(
            "GET", f"/ccrc/second-persons/{sp_id}", headers=headers,
        )

    def remove_second_person(self, sp_id, headers):
        return self._request(
            "POST", f"/ccrc/second-persons/{sp_id}/remove", {}, headers,
        )

    # ── Waitlist ────────────────────────────────────────────────────
    def create_waitlist_entry(self, payload, headers):
        return self._request(
            "POST", "/ccrc/waitlist-entries", payload, headers,
        )

    def list_waitlist_entries(self, headers, params=None):
        return self._request(
            "GET", "/ccrc/waitlist-entries", headers=headers, params=params,
        )

    def get_waitlist_entry(self, wid, headers):
        return self._request(
            "GET", f"/ccrc/waitlist-entries/{wid}", headers=headers,
        )

    def offer_waitlist_entry(self, wid, headers):
        return self._request(
            "POST", f"/ccrc/waitlist-entries/{wid}/offer", {}, headers,
        )

    def place_waitlist_entry(self, wid, payload, headers):
        return self._request(
            "POST", f"/ccrc/waitlist-entries/{wid}/place", payload, headers,
        )

    def withdraw_waitlist_entry(self, wid, headers):
        return self._request(
            "POST", f"/ccrc/waitlist-entries/{wid}/withdraw", {}, headers,
        )

    # ── Care Transitions ────────────────────────────────────────────
    def create_care_transition(self, payload, headers):
        return self._request(
            "POST", "/ccrc/care-transitions", payload, headers,
        )

    def list_care_transitions(self, headers, params=None):
        return self._request(
            "GET", "/ccrc/care-transitions", headers=headers, params=params,
        )

    def get_care_transition(self, ctid, headers):
        return self._request(
            "GET", f"/ccrc/care-transitions/{ctid}", headers=headers,
        )

    def apply_care_transition(self, ctid, headers):
        return self._request(
            "POST", f"/ccrc/care-transitions/{ctid}/apply", {}, headers,
        )

    def revert_care_transition(self, ctid, headers):
        return self._request(
            "POST", f"/ccrc/care-transitions/{ctid}/revert", {}, headers,
        )

    # ── Bed Reservations ────────────────────────────────────────────
    def create_bed_reservation(self, payload, headers):
        return self._request(
            "POST", "/ccrc/bed-reservations", payload, headers,
        )

    def list_bed_reservations(self, headers, params=None):
        return self._request(
            "GET", "/ccrc/bed-reservations", headers=headers, params=params,
        )

    def get_bed_reservation(self, brid, headers):
        return self._request(
            "GET", f"/ccrc/bed-reservations/{brid}", headers=headers,
        )

    def occupy_bed_reservation(self, brid, headers):
        return self._request(
            "POST", f"/ccrc/bed-reservations/{brid}/occupy", {}, headers,
        )

    def release_bed_reservation(self, brid, headers):
        return self._request(
            "POST", f"/ccrc/bed-reservations/{brid}/release", {}, headers,
        )

    # ── Monthly Invoices ────────────────────────────────────────────
    def list_invoices(self, headers, params=None):
        return self._request(
            "GET", "/ccrc/invoices", headers=headers, params=params,
        )

    def get_invoice(self, invid, headers):
        return self._request(
            "GET", f"/ccrc/invoices/{invid}", headers=headers,
        )

    # ── Refund Disbursements ────────────────────────────────────────
    def list_refund_disbursements(self, headers, params=None):
        return self._request(
            "GET", "/ccrc/refund-disbursements", headers=headers, params=params,
        )

    def get_refund_disbursement(self, dsbid, headers):
        return self._request(
            "GET", f"/ccrc/refund-disbursements/{dsbid}", headers=headers,
        )

    def settle_refund(self, dsbid, headers):
        return self._request(
            "POST", f"/ccrc/refund-disbursements/{dsbid}/settle", {}, headers,
        )

    # ── Councils ────────────────────────────────────────────────────
    def create_council(self, payload, headers):
        return self._request("POST", "/ccrc/councils", payload, headers)

    def list_councils(self, headers, params=None):
        return self._request(
            "GET", "/ccrc/councils", headers=headers, params=params,
        )

    def get_council(self, coid, headers):
        return self._request(
            "GET", f"/ccrc/councils/{coid}", headers=headers,
        )

    # ── Council Resolutions ─────────────────────────────────────────
    def create_resolution(self, payload, headers):
        return self._request(
            "POST", "/ccrc/council-resolutions", payload, headers,
        )

    def list_resolutions(self, headers, params=None):
        return self._request(
            "GET", "/ccrc/council-resolutions", headers=headers, params=params,
        )

    def get_resolution(self, resid, headers):
        return self._request(
            "GET", f"/ccrc/council-resolutions/{resid}", headers=headers,
        )

    def open_resolution(self, resid, headers):
        return self._request(
            "POST", f"/ccrc/council-resolutions/{resid}/open", {}, headers,
        )

    def cast_vote(self, resid, payload, headers):
        return self._request(
            "POST", f"/ccrc/council-resolutions/{resid}/votes", payload, headers,
        )

    def close_resolution(self, resid, headers):
        return self._request(
            "POST", f"/ccrc/council-resolutions/{resid}/close", {}, headers,
        )


api_client = ApiClient()
