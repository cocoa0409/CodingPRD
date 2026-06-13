"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Jurisdiction ---
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/jurisdictions", payload, headers)

    def get_jurisdiction(self, jid, headers):
        return self._request("GET", f"/jurisdictions/{jid}", headers=headers)

    # --- Driver ---
    def create_driver(self, payload, headers):
        return self._request("POST", "/drivers", payload, headers)

    def get_driver(self, did, headers):
        return self._request("GET", f"/drivers/{did}", headers=headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/drivers", headers=headers, params=params)

    # --- Citation ---
    def create_citation(self, payload, headers):
        return self._request("POST", "/citations", payload, headers)

    def get_citation(self, cid, headers):
        return self._request("GET", f"/citations/{cid}", headers=headers)

    def list_citations(self, headers, params=None):
        return self._request("GET", "/citations", headers=headers, params=params)

    def assess_citation(self, cid, headers):
        return self._request("POST", f"/citations/{cid}/assess", {}, headers)

    def void_citation(self, cid, headers):
        return self._request("POST", f"/citations/{cid}/void", {}, headers)

    def apply_late_penalty(self, cid, headers):
        return self._request(
            "POST", f"/citations/{cid}/apply-late-penalty", {}, headers
        )

    # --- CitationCharge ---
    def create_charge(self, payload, headers):
        return self._request("POST", "/charges", payload, headers)

    def get_charge(self, chid, headers):
        return self._request("GET", f"/charges/{chid}", headers=headers)

    def list_charges(self, headers, params=None):
        return self._request("GET", "/charges", headers=headers, params=params)

    # --- Payment ---
    def create_payment(self, cid, payload, headers):
        return self._request("POST", f"/citations/{cid}/payments", payload, headers)

    def get_payment(self, pid, headers):
        return self._request("GET", f"/payments/{pid}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    # --- Installment plan ---
    def create_installment_plan(self, cid, payload, headers):
        return self._request(
            "POST", f"/citations/{cid}/installment-plans", payload, headers
        )

    def get_installment_plan(self, pid, headers):
        return self._request("GET", f"/installment-plans/{pid}", headers=headers)

    def list_installment_plans(self, headers, params=None):
        return self._request(
            "GET", "/installment-plans", headers=headers, params=params
        )

    def mark_default(self, pid, headers):
        return self._request(
            "POST", f"/installment-plans/{pid}/mark-default", {}, headers
        )

    def cancel_plan(self, pid, headers):
        return self._request(
            "POST", f"/installment-plans/{pid}/cancel", {}, headers
        )

    # --- Installment ---
    def get_installment(self, iid, headers):
        return self._request("GET", f"/installments/{iid}", headers=headers)

    def list_installments(self, headers, params=None):
        return self._request("GET", "/installments", headers=headers, params=params)

    # --- Contest / hearing ---
    def create_contest_request(self, cid, payload, headers):
        return self._request(
            "POST", f"/citations/{cid}/contest-requests", payload, headers
        )

    def get_contest_request(self, rid, headers):
        return self._request("GET", f"/contest-requests/{rid}", headers=headers)

    def list_contest_requests(self, headers, params=None):
        return self._request(
            "GET", "/contest-requests", headers=headers, params=params
        )

    def schedule_hearing(self, rid, payload, headers):
        return self._request(
            "POST", f"/contest-requests/{rid}/schedule", payload, headers
        )

    def continue_hearing(self, rid, headers):
        return self._request(
            "POST", f"/contest-requests/{rid}/continue", {}, headers
        )

    def decide_contest(self, rid, payload, headers):
        return self._request(
            "POST", f"/contest-requests/{rid}/decide", payload, headers
        )

    def fail_to_appear(self, rid, headers):
        return self._request(
            "POST", f"/contest-requests/{rid}/fail-to-appear", {}, headers
        )

    # --- Traffic school ---
    def create_enrollment(self, cid, payload, headers):
        return self._request(
            "POST", f"/citations/{cid}/enrollments", payload, headers
        )

    def get_enrollment(self, eid, headers):
        return self._request("GET", f"/enrollments/{eid}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def complete_enrollment(self, eid, headers):
        return self._request(
            "POST", f"/enrollments/{eid}/complete", {}, headers
        )

    def fail_enrollment(self, eid, headers):
        return self._request("POST", f"/enrollments/{eid}/fail", {}, headers)

    # --- Collections ---
    def create_collections_referral(self, cid, headers):
        return self._request(
            "POST", f"/citations/{cid}/collections-referrals", {}, headers
        )

    def get_collections_referral(self, crid, headers):
        return self._request(
            "GET", f"/collections-referrals/{crid}", headers=headers
        )

    def list_collections_referrals(self, headers, params=None):
        return self._request(
            "GET", "/collections-referrals", headers=headers, params=params
        )

    # --- License holds (DMV) ---
    def get_license_hold(self, hid, headers):
        return self._request("GET", f"/license-holds/{hid}", headers=headers)

    def list_license_holds(self, headers, params=None):
        return self._request(
            "GET", "/license-holds", headers=headers, params=params
        )

    def release_license_hold(self, hid, headers):
        return self._request(
            "POST", f"/license-holds/{hid}/release", {}, headers
        )

    # --- Warrants ---
    def get_warrant(self, wid, headers):
        return self._request("GET", f"/warrants/{wid}", headers=headers)

    def list_warrants(self, headers, params=None):
        return self._request("GET", "/warrants", headers=headers, params=params)

    def quash_warrant(self, wid, headers):
        return self._request("POST", f"/warrants/{wid}/quash", {}, headers)

    # --- Point ledger (DMV) ---
    def get_point_ledger_entry(self, pleid, headers):
        return self._request("GET", f"/point-ledger/{pleid}", headers=headers)

    def list_point_ledger(self, headers, params=None):
        return self._request("GET", "/point-ledger", headers=headers, params=params)


api_client = ApiClient()
