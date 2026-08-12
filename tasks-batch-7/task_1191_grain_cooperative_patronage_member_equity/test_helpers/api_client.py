"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (test-driving) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/coop/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/coop/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/coop/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/coop/members", headers=headers, params=params)

    def deactivate_member(self, member_id, headers):
        return self._request(
            "POST", f"/coop/members/{member_id}/deactivate", {}, headers,
        )

    def reactivate_member(self, member_id, headers):
        return self._request(
            "POST", f"/coop/members/{member_id}/reactivate", {}, headers,
        )

    def record_death(self, member_id, payload, headers):
        return self._request(
            "POST", f"/coop/members/{member_id}/record_death", payload, headers,
        )

    def withdraw_member(self, member_id, payload, headers):
        return self._request(
            "POST", f"/coop/members/{member_id}/withdraw", payload, headers,
        )

    def expel_member(self, member_id, headers):
        return self._request(
            "POST", f"/coop/members/{member_id}/expel", {}, headers,
        )

    # --- DelegateDistricts / Delegates ---
    def create_delegate_district(self, payload, headers):
        return self._request("POST", "/coop/delegate_districts", payload, headers)

    def get_delegate_district(self, district_id, headers):
        return self._request(
            "GET", f"/coop/delegate_districts/{district_id}", headers=headers,
        )

    def seat_delegate(self, district_id, payload, headers):
        return self._request(
            "POST", f"/coop/delegate_districts/{district_id}/delegates",
            payload, headers,
        )

    def list_district_delegates(self, district_id, headers):
        return self._request(
            "GET", f"/coop/delegate_districts/{district_id}/delegates",
            headers=headers,
        )

    def get_delegate(self, delegate_id, headers):
        return self._request("GET", f"/coop/delegates/{delegate_id}", headers=headers)

    def list_delegates(self, headers, params=None):
        return self._request("GET", "/coop/delegates", headers=headers, params=params)

    # --- FiscalYears ---
    def create_fiscal_year(self, payload, headers):
        return self._request("POST", "/coop/fiscal_years", payload, headers)

    def get_fiscal_year(self, fy_id, headers):
        return self._request("GET", f"/coop/fiscal_years/{fy_id}", headers=headers)

    def close_provisional(self, fy_id, headers):
        return self._request(
            "POST", f"/coop/fiscal_years/{fy_id}/close_provisional", {}, headers,
        )

    def begin_audit(self, fy_id, headers):
        return self._request(
            "POST", f"/coop/fiscal_years/{fy_id}/begin_audit", {}, headers,
        )

    def finalize_close(self, fy_id, payload, headers):
        return self._request(
            "POST", f"/coop/fiscal_years/{fy_id}/finalize_close", payload, headers,
        )

    def reopen_fiscal_year(self, fy_id, payload, headers):
        return self._request(
            "POST", f"/coop/fiscal_years/{fy_id}/reopen", payload, headers,
        )

    # --- GrainDeliveries ---
    def book_delivery(self, payload, headers):
        return self._request("POST", "/coop/deliveries", payload, headers)

    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"/coop/deliveries/{delivery_id}", headers=headers)

    def list_deliveries(self, headers, params=None):
        return self._request("GET", "/coop/deliveries", headers=headers, params=params)

    def list_member_deliveries(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/coop/members/{member_id}/deliveries",
            headers=headers, params=params,
        )

    def settle_delivery(self, delivery_id, headers):
        return self._request(
            "POST", f"/coop/deliveries/{delivery_id}/settle", {}, headers,
        )

    def cancel_delivery(self, delivery_id, headers):
        return self._request(
            "POST", f"/coop/deliveries/{delivery_id}/cancel", {}, headers,
        )

    # --- PatronageAllocations ---
    def get_allocation(self, alloc_id, headers):
        return self._request("GET", f"/coop/allocations/{alloc_id}", headers=headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/coop/allocations", headers=headers, params=params)

    def list_year_allocations(self, fy_id, headers, params=None):
        return self._request(
            "GET", f"/coop/fiscal_years/{fy_id}/allocations",
            headers=headers, params=params,
        )

    def reverse_allocation(self, alloc_id, payload, headers):
        return self._request(
            "POST", f"/coop/allocations/{alloc_id}/reverse", payload, headers,
        )

    # --- EquityCertificates ---
    def get_certificate(self, cert_id, headers):
        return self._request("GET", f"/coop/certificates/{cert_id}", headers=headers)

    def list_certificates(self, headers, params=None):
        return self._request(
            "GET", "/coop/certificates", headers=headers, params=params,
        )

    def list_member_certificates(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/coop/members/{member_id}/certificates",
            headers=headers, params=params,
        )

    # --- RevolvementCycles ---
    def create_revolvement_cycle(self, payload, headers):
        return self._request("POST", "/coop/revolvement_cycles", payload, headers)

    def get_revolvement_cycle(self, cycle_id, headers):
        return self._request(
            "GET", f"/coop/revolvement_cycles/{cycle_id}", headers=headers,
        )

    def list_revolvement_cycles(self, headers, params=None):
        return self._request(
            "GET", "/coop/revolvement_cycles", headers=headers, params=params,
        )

    def open_cycle(self, cycle_id, headers):
        return self._request(
            "POST", f"/coop/revolvement_cycles/{cycle_id}/open", {}, headers,
        )

    def close_cycle(self, cycle_id, headers):
        return self._request(
            "POST", f"/coop/revolvement_cycles/{cycle_id}/close", {}, headers,
        )

    # --- RedemptionRequests ---
    def create_redemption_request(self, payload, headers):
        return self._request("POST", "/coop/redemption_requests", payload, headers)

    def get_redemption_request(self, req_id, headers):
        return self._request(
            "GET", f"/coop/redemption_requests/{req_id}", headers=headers,
        )

    def list_redemption_requests(self, headers, params=None):
        return self._request(
            "GET", "/coop/redemption_requests", headers=headers, params=params,
        )

    def list_member_redemption_requests(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/coop/members/{member_id}/redemption_requests",
            headers=headers, params=params,
        )

    def submit_for_review(self, req_id, headers):
        return self._request(
            "POST", f"/coop/redemption_requests/{req_id}/submit_for_review",
            {}, headers,
        )

    def decide_redemption(self, req_id, payload, headers):
        return self._request(
            "POST", f"/coop/redemption_requests/{req_id}/decide", payload, headers,
        )

    def appeal_redemption(self, req_id, headers):
        return self._request(
            "POST", f"/coop/redemption_requests/{req_id}/appeal", {}, headers,
        )

    def disburse_redemption(self, req_id, payload, headers):
        return self._request(
            "POST", f"/coop/redemption_requests/{req_id}/disburse", payload, headers,
        )

    def cancel_redemption(self, req_id, headers):
        return self._request(
            "POST", f"/coop/redemption_requests/{req_id}/cancel", {}, headers,
        )

    # --- EstateClaims ---
    def get_estate_claim(self, claim_id, headers):
        return self._request("GET", f"/coop/estate_claims/{claim_id}", headers=headers)

    def list_estate_claims(self, headers, params=None):
        return self._request(
            "GET", "/coop/estate_claims", headers=headers, params=params,
        )

    def list_member_estate_claims(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/coop/members/{member_id}/estate_claims",
            headers=headers, params=params,
        )

    def record_probate(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/coop/estate_claims/{claim_id}/record_probate",
            payload, headers,
        )

    def decide_estate_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/coop/estate_claims/{claim_id}/decide", payload, headers,
        )

    # --- UnclaimedEquityLots ---
    def create_unclaimed_lot(self, payload, headers):
        return self._request("POST", "/coop/unclaimed_lots", payload, headers)

    def get_unclaimed_lot(self, lot_id, headers):
        return self._request("GET", f"/coop/unclaimed_lots/{lot_id}", headers=headers)

    def list_unclaimed_lots(self, headers, params=None):
        return self._request(
            "GET", "/coop/unclaimed_lots", headers=headers, params=params,
        )

    def notify_lot(self, lot_id, headers):
        return self._request(
            "POST", f"/coop/unclaimed_lots/{lot_id}/notify", {}, headers,
        )

    def escheat_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/coop/unclaimed_lots/{lot_id}/escheat", payload, headers,
        )

    def recover_lot(self, lot_id, headers):
        return self._request(
            "POST", f"/coop/unclaimed_lots/{lot_id}/recover", {}, headers,
        )

    # --- BoardResolutions ---
    def create_board_resolution(self, payload, headers):
        return self._request("POST", "/coop/board_resolutions", payload, headers)

    def get_board_resolution(self, res_id, headers):
        return self._request(
            "GET", f"/coop/board_resolutions/{res_id}", headers=headers,
        )

    def open_voting(self, res_id, headers):
        return self._request(
            "POST", f"/coop/board_resolutions/{res_id}/open_voting", {}, headers,
        )

    def record_vote(self, res_id, payload, headers):
        return self._request(
            "POST", f"/coop/board_resolutions/{res_id}/record_vote", payload, headers,
        )

    def table_resolution(self, res_id, headers):
        return self._request(
            "POST", f"/coop/board_resolutions/{res_id}/table", {}, headers,
        )

    # --- PatronTaxForms ---
    def get_tax_form(self, form_id, headers):
        return self._request("GET", f"/coop/tax_forms/{form_id}", headers=headers)

    def list_tax_forms(self, headers, params=None):
        return self._request("GET", "/coop/tax_forms", headers=headers, params=params)

    def list_member_tax_forms(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/coop/members/{member_id}/tax_forms",
            headers=headers, params=params,
        )

    def void_tax_form(self, form_id, payload, headers):
        return self._request(
            "POST", f"/coop/tax_forms/{form_id}/void", payload, headers,
        )


api_client = ApiClient()
