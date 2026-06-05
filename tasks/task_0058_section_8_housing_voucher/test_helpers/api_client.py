"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # --- Regions ---
    def create_region(self, payload, headers):
        return self._request("POST", "/regions", payload, headers)

    def get_region(self, region_id, headers):
        return self._request("GET", f"/regions/{region_id}", headers=headers)

    def list_regions(self, headers, params=None):
        return self._request("GET", "/regions", headers=headers, params=params)

    # --- Payment standards ---
    def create_payment_standard(self, payload, headers):
        return self._request("POST", "/payment-standards", payload, headers)

    def get_payment_standard(self, ps_id, headers):
        return self._request("GET", f"/payment-standards/{ps_id}", headers=headers)

    def list_payment_standards(self, headers, params=None):
        return self._request("GET", "/payment-standards", headers=headers, params=params)

    # --- Households ---
    def create_household(self, payload, headers):
        return self._request("POST", "/households", payload, headers)

    def get_household(self, household_id, headers):
        return self._request("GET", f"/households/{household_id}", headers=headers)

    def list_households(self, headers, params=None):
        return self._request("GET", "/households", headers=headers, params=params)

    def determine_eligibility(self, household_id, headers, payload=None):
        return self._request(
            "POST", f"/households/{household_id}/determine-eligibility",
            payload or {}, headers,
        )

    # --- Vouchers ---
    def create_voucher(self, payload, headers):
        return self._request("POST", "/vouchers", payload, headers)

    def get_voucher(self, voucher_id, headers):
        return self._request("GET", f"/vouchers/{voucher_id}", headers=headers)

    def list_vouchers(self, headers, params=None):
        return self._request("GET", "/vouchers", headers=headers, params=params)

    def expire_voucher(self, voucher_id, headers, payload=None):
        return self._request(
            "POST", f"/vouchers/{voucher_id}/expire", payload or {}, headers,
        )

    # --- Landlords ---
    def create_landlord(self, payload, headers):
        return self._request("POST", "/landlords", payload, headers)

    def get_landlord(self, landlord_id, headers):
        return self._request("GET", f"/landlords/{landlord_id}", headers=headers)

    # --- Units ---
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/units", headers=headers, params=params)

    # --- Rent reasonableness ---
    def create_rent_reasonableness(self, payload, headers):
        return self._request("POST", "/rent-reasonableness", payload, headers)

    def get_rent_reasonableness(self, det_id, headers):
        return self._request("GET", f"/rent-reasonableness/{det_id}", headers=headers)

    def list_rent_reasonableness(self, headers, params=None):
        return self._request("GET", "/rent-reasonableness", headers=headers, params=params)

    # --- Inspections ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def pass_inspection(self, inspection_id, headers, payload=None):
        return self._request(
            "POST", f"/inspections/{inspection_id}/pass", payload or {}, headers,
        )

    def fail_inspection(self, inspection_id, headers, payload=None):
        return self._request(
            "POST", f"/inspections/{inspection_id}/fail", payload or {}, headers,
        )

    def cure_inspection(self, inspection_id, headers, payload=None):
        return self._request(
            "POST", f"/inspections/{inspection_id}/cure", payload or {}, headers,
        )

    def fail_cure_inspection(self, inspection_id, headers, payload=None):
        return self._request(
            "POST", f"/inspections/{inspection_id}/fail-cure", payload or {}, headers,
        )

    # --- HAP contracts ---
    def create_hap_contract(self, payload, headers):
        return self._request("POST", "/hap-contracts", payload, headers)

    def get_hap_contract(self, contract_id, headers):
        return self._request("GET", f"/hap-contracts/{contract_id}", headers=headers)

    def list_hap_contracts(self, headers, params=None):
        return self._request("GET", "/hap-contracts", headers=headers, params=params)

    def terminate_hap_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST", f"/hap-contracts/{contract_id}/terminate", payload or {}, headers,
        )

    # --- Portability moves ---
    def create_portability_move(self, payload, headers):
        return self._request("POST", "/portability-moves", payload, headers)

    def get_portability_move(self, move_id, headers):
        return self._request("GET", f"/portability-moves/{move_id}", headers=headers)

    def list_portability_moves(self, headers, params=None):
        return self._request("GET", "/portability-moves", headers=headers, params=params)

    def approve_portability_move(self, move_id, headers, payload=None):
        return self._request(
            "POST", f"/portability-moves/{move_id}/approve", payload or {}, headers,
        )

    def deny_portability_move(self, move_id, headers, payload=None):
        return self._request(
            "POST", f"/portability-moves/{move_id}/deny", payload or {}, headers,
        )

    # --- Annual reviews ---
    def create_annual_review(self, payload, headers):
        return self._request("POST", "/annual-reviews", payload, headers)

    def get_annual_review(self, review_id, headers):
        return self._request("GET", f"/annual-reviews/{review_id}", headers=headers)

    def list_annual_reviews(self, headers, params=None):
        return self._request("GET", "/annual-reviews", headers=headers, params=params)

    def finalize_annual_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/annual-reviews/{review_id}/finalize", payload, headers,
        )

    # --- Special mobility grants ---
    def create_special_mobility_grant(self, payload, headers):
        return self._request("POST", "/special-mobility-grants", payload, headers)

    def get_special_mobility_grant(self, grant_id, headers):
        return self._request(
            "GET", f"/special-mobility-grants/{grant_id}", headers=headers,
        )

    def list_special_mobility_grants(self, headers, params=None):
        return self._request(
            "GET", "/special-mobility-grants", headers=headers, params=params,
        )

    def revoke_special_mobility_grant(self, grant_id, headers, payload=None):
        return self._request(
            "POST", f"/special-mobility-grants/{grant_id}/revoke",
            payload or {}, headers,
        )

    # --- Test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
