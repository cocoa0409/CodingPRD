"""API client: one method per endpoint defined in the PRD (Roadside Assistance Dispatch)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Test-driving clock -----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ----- MembershipPlan -----
    def create_membership_plan(self, payload, headers):
        return self._request("POST", "/membership-plans", payload, headers)

    def get_membership_plan(self, plan_id, headers):
        return self._request("GET", f"/membership-plans/{plan_id}", headers=headers)

    def list_membership_plans(self, headers, params=None):
        return self._request("GET", "/membership-plans", headers=headers, params=params)

    # ----- Member -----
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def suspend_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/suspend", {}, headers)

    def reinstate_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/reinstate", {}, headers)

    # ----- ServiceProvider -----
    def create_service_provider(self, payload, headers):
        return self._request("POST", "/service-providers", payload, headers)

    def get_service_provider(self, provider_id, headers):
        return self._request("GET", f"/service-providers/{provider_id}", headers=headers)

    def list_service_providers(self, headers, params=None):
        return self._request("GET", "/service-providers", headers=headers, params=params)

    def provider_go_offline(self, provider_id, headers):
        return self._request("POST", f"/service-providers/{provider_id}/go-offline", {}, headers)

    def provider_go_online(self, provider_id, headers):
        return self._request("POST", f"/service-providers/{provider_id}/go-online", {}, headers)

    def list_provider_offers(self, provider_id, headers, params=None):
        return self._request("GET", f"/service-providers/{provider_id}/offers", headers=headers, params=params)

    # ----- ProviderShift -----
    def create_shift(self, provider_id, payload, headers):
        return self._request("POST", f"/service-providers/{provider_id}/shifts", payload, headers)

    def list_shifts(self, provider_id, headers, params=None):
        return self._request("GET", f"/service-providers/{provider_id}/shifts", headers=headers, params=params)

    def cancel_shift(self, provider_id, shift_id, headers):
        return self._request("POST", f"/service-providers/{provider_id}/shifts/{shift_id}/cancel", {}, headers)

    # ----- Depot -----
    def create_depot(self, payload, headers):
        return self._request("POST", "/depots", payload, headers)

    def get_depot(self, depot_id, headers):
        return self._request("GET", f"/depots/{depot_id}", headers=headers)

    def list_depots(self, headers, params=None):
        return self._request("GET", "/depots", headers=headers, params=params)

    # ----- BayReservation -----
    def create_bay_reservation(self, depot_id, payload, headers):
        return self._request("POST", f"/depots/{depot_id}/bay-reservations", payload, headers)

    def list_depot_bay_reservations(self, depot_id, headers, params=None):
        return self._request("GET", f"/depots/{depot_id}/bay-reservations", headers=headers, params=params)

    def release_bay_reservation(self, depot_id, reservation_id, headers):
        return self._request("POST", f"/depots/{depot_id}/bay-reservations/{reservation_id}/release", {}, headers)

    # ----- ServiceCall -----
    def create_service_call(self, payload, headers):
        return self._request("POST", "/service-calls", payload, headers)

    def get_service_call(self, call_id, headers):
        return self._request("GET", f"/service-calls/{call_id}", headers=headers)

    def list_service_calls(self, headers, params=None):
        return self._request("GET", "/service-calls", headers=headers, params=params)

    def get_dispatch_candidates(self, call_id, headers, params=None):
        return self._request("GET", f"/service-calls/{call_id}/dispatch-candidates", headers=headers, params=params)

    def create_offer(self, call_id, payload, headers):
        return self._request("POST", f"/service-calls/{call_id}/offers", payload, headers)

    def list_call_offers(self, call_id, headers, params=None):
        return self._request("GET", f"/service-calls/{call_id}/offers", headers=headers, params=params)

    def list_call_bay_reservations(self, call_id, headers, params=None):
        return self._request("GET", f"/service-calls/{call_id}/bay-reservations", headers=headers, params=params)

    def accept_offer(self, call_id, offer_id, headers):
        return self._request("POST", f"/service-calls/{call_id}/offers/{offer_id}/accept", {}, headers)

    def decline_offer(self, call_id, offer_id, headers):
        return self._request("POST", f"/service-calls/{call_id}/offers/{offer_id}/decline", {}, headers)

    def expire_offer(self, call_id, offer_id, headers):
        return self._request("POST", f"/service-calls/{call_id}/offers/{offer_id}/expire", {}, headers)

    def start_call(self, call_id, headers):
        return self._request("POST", f"/service-calls/{call_id}/start", {}, headers)

    def complete_call(self, call_id, payload, headers):
        return self._request("POST", f"/service-calls/{call_id}/complete", payload, headers)

    def abandon_call(self, call_id, headers):
        return self._request("POST", f"/service-calls/{call_id}/abandon", {}, headers)

    def cancel_call(self, call_id, headers):
        return self._request("POST", f"/service-calls/{call_id}/cancel", {}, headers)

    # ----- ReimbursementClaim -----
    def create_claim(self, payload, headers):
        return self._request("POST", "/reimbursement-claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/reimbursement-claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/reimbursement-claims", headers=headers, params=params)

    def begin_review_claim(self, claim_id, headers):
        return self._request("POST", f"/reimbursement-claims/{claim_id}/begin-review", {}, headers)

    def request_info_claim(self, claim_id, headers):
        return self._request("POST", f"/reimbursement-claims/{claim_id}/request-info", {}, headers)

    def resubmit_claim(self, claim_id, headers):
        return self._request("POST", f"/reimbursement-claims/{claim_id}/resubmit", {}, headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/reimbursement-claims/{claim_id}/approve", {}, headers)

    def reject_claim(self, claim_id, headers):
        return self._request("POST", f"/reimbursement-claims/{claim_id}/reject", {}, headers)


api_client = ApiClient()
