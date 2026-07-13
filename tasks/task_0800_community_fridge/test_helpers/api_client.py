"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Fridge ----
    def create_fridge(self, payload, headers):
        return self._request("POST", "/fridges", payload, headers)

    def get_fridge(self, fridge_id, headers):
        return self._request("GET", f"/fridges/{fridge_id}", headers=headers)

    def record_temperature(self, fridge_id, payload, headers):
        return self._request(
            "POST", f"/fridges/{fridge_id}/temperature", payload, headers
        )

    def run_ops(self, fridge_id, headers):
        return self._request("POST", f"/fridges/{fridge_id}/run-ops", {}, headers)

    # ---- Steward ----
    def create_steward(self, payload, headers):
        return self._request("POST", "/stewards", payload, headers)

    def get_steward(self, steward_id, headers):
        return self._request("GET", f"/stewards/{steward_id}", headers=headers)

    def suspend_steward(self, steward_id, headers):
        return self._request("POST", f"/stewards/{steward_id}/suspend", {}, headers)

    # ---- Donor ----
    def create_donor(self, payload, headers):
        return self._request("POST", "/donors", payload, headers)

    def get_donor(self, donor_id, headers):
        return self._request("GET", f"/donors/{donor_id}", headers=headers)

    # ---- SponsorGrant ----
    def create_grant(self, fridge_id, payload, headers):
        return self._request("POST", f"/fridges/{fridge_id}/grants", payload, headers)

    def get_grant(self, grant_id, headers):
        return self._request("GET", f"/grants/{grant_id}", headers=headers)

    def list_grants(self, headers, params=None):
        return self._request("GET", "/grants", headers=headers, params=params)

    def cancel_grant(self, grant_id, headers):
        return self._request("POST", f"/grants/{grant_id}/cancel", {}, headers)

    # ---- StewardShift ----
    def create_shift(self, fridge_id, payload, headers):
        return self._request("POST", f"/fridges/{fridge_id}/shifts", payload, headers)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/shifts/{shift_id}", headers=headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/shifts", headers=headers, params=params)

    def complete_shift(self, shift_id, payload, headers):
        return self._request("POST", f"/shifts/{shift_id}/complete", payload, headers)

    def fail_inspection(self, shift_id, headers):
        return self._request(
            "POST", f"/shifts/{shift_id}/fail-inspection", {}, headers
        )

    # ---- SurplusOffer ----
    def create_offer(self, donor_id, payload, headers):
        return self._request("POST", f"/donors/{donor_id}/offers", payload, headers)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/offers", headers=headers, params=params)

    def accept_offer(self, offer_id, headers):
        return self._request("POST", f"/offers/{offer_id}/accept", {}, headers)

    # ---- DonationBatch ----
    def create_batch(self, fridge_id, payload, headers):
        return self._request(
            "POST", f"/fridges/{fridge_id}/donation-batches", payload, headers
        )

    def get_batch(self, batch_id, headers):
        return self._request(
            "GET", f"/donation-batches/{batch_id}", headers=headers
        )

    def list_batches(self, headers, params=None):
        return self._request(
            "GET", "/donation-batches", headers=headers, params=params
        )

    def recall_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/donation-batches/{batch_id}/recall", {}, headers
        )

    def discard_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/donation-batches/{batch_id}/discard", {}, headers
        )

    # ---- Claim ----
    def create_claim(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/donation-batches/{batch_id}/claims", payload, headers
        )

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    # ---- NeedPosting ----
    def create_need(self, fridge_id, payload, headers):
        return self._request("POST", f"/fridges/{fridge_id}/needs", payload, headers)

    def get_need(self, need_id, headers):
        return self._request("GET", f"/needs/{need_id}", headers=headers)

    def list_needs(self, headers, params=None):
        return self._request("GET", "/needs", headers=headers, params=params)


api_client = ApiClient()
