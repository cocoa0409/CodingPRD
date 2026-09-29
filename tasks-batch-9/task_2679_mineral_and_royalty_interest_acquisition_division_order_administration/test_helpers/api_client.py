"""Typed API client: one method per declared endpoint."""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """One method per route in the endpoint table."""

    # ------------------------------------------------------------------ tracts
    def create_tract(self, payload: dict, headers: dict):
        return self._request("POST", "/tracts", payload, headers)

    def get_tract(self, tract_id: str, headers: dict):
        return self._request("GET", f"/tracts/{tract_id}", None, headers)

    def list_tracts(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/tracts", params, headers)

    def create_title_chain_entry(self, tract_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/tracts/{tract_id}/title-chain-entries", payload, headers
        )

    def list_title_chain_entries(
        self, tract_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/tracts/{tract_id}/title-chain-entries", params, headers
        )

    def certify_title(self, tract_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/tracts/{tract_id}/certify-title", payload or {}, headers
        )

    def list_tract_unit_allocations(
        self, tract_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/tracts/{tract_id}/unit-allocations", params, headers
        )

    # ---------------------------------------------------------- royalty owners
    def create_royalty_owner(self, payload: dict, headers: dict):
        return self._request("POST", "/royalty-owners", payload, headers)

    def get_royalty_owner(self, owner_id: str, headers: dict):
        return self._request("GET", f"/royalty-owners/{owner_id}", None, headers)

    def list_royalty_owners(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/royalty-owners", params, headers)

    def update_royalty_owner(self, owner_id: str, payload: dict, headers: dict):
        return self._request("PATCH", f"/royalty-owners/{owner_id}", payload, headers)

    def get_tax_statement(self, owner_id: str, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"/royalty-owners/{owner_id}/tax-statement", params, headers
        )

    # -------------------------------------------------------- mineral interests
    def create_mineral_interest(self, payload: dict, headers: dict):
        return self._request("POST", "/mineral-interests", payload, headers)

    def get_mineral_interest(self, interest_id: str, headers: dict):
        return self._request("GET", f"/mineral-interests/{interest_id}", None, headers)

    def list_mineral_interests(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/mineral-interests", params, headers)

    # ------------------------------------------------------------- valuations
    def create_valuation(self, interest_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/mineral-interests/{interest_id}/valuations", payload, headers
        )

    def list_valuations(
        self, interest_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/mineral-interests/{interest_id}/valuations", params, headers
        )

    def get_valuation(self, valuation_id: str, headers: dict):
        return self._request("GET", f"/valuations/{valuation_id}", None, headers)

    # ----------------------------------------------------------- offer letters
    def create_offer_letter(self, interest_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/mineral-interests/{interest_id}/offer-letters", payload, headers
        )

    def list_offer_letters(
        self, interest_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/mineral-interests/{interest_id}/offer-letters", params, headers
        )

    def get_offer_letter(self, offer_id: str, headers: dict):
        return self._request("GET", f"/offer-letters/{offer_id}", None, headers)

    def counter_offer_letter(self, offer_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/offer-letters/{offer_id}/counter", payload, headers
        )

    def revise_offer_letter(self, offer_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/offer-letters/{offer_id}/revise", payload, headers
        )

    def accept_offer_letter(self, offer_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/offer-letters/{offer_id}/accept", payload or {}, headers
        )

    def reject_offer_letter(self, offer_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/offer-letters/{offer_id}/reject", payload or {}, headers
        )

    # -------------------------------------------------------------------- psas
    def create_psa(self, payload: dict, headers: dict):
        return self._request("POST", "/psas", payload, headers)

    def get_psa(self, psa_id: str, headers: dict):
        return self._request("GET", f"/psas/{psa_id}", None, headers)

    def list_psas(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/psas", params, headers)

    def create_title_defect(self, psa_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/psas/{psa_id}/title-defects", payload, headers)

    def list_title_defects(self, psa_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/psas/{psa_id}/title-defects", params, headers)

    def close_curative(self, psa_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/psas/{psa_id}/close-curative", payload or {}, headers
        )

    def fund_psa(self, psa_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/psas/{psa_id}/fund", payload, headers)

    def record_deed(self, psa_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/psas/{psa_id}/record-deed", payload, headers)

    # ----------------------------------------------------------- title defects
    def get_title_defect(self, defect_id: str, headers: dict):
        return self._request("GET", f"/title-defects/{defect_id}", None, headers)

    def submit_cure(self, defect_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/title-defects/{defect_id}/submit-cure", payload, headers
        )

    def cure_decision(self, defect_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/title-defects/{defect_id}/cure-decision", payload, headers
        )

    def waive_defect(self, defect_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/title-defects/{defect_id}/waive", payload or {}, headers
        )

    # ------------------------------------------------------------------- units
    def create_unit(self, payload: dict, headers: dict):
        return self._request("POST", "/units", payload, headers)

    def get_unit(self, unit_id: str, headers: dict):
        return self._request("GET", f"/units/{unit_id}", None, headers)

    def list_units(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/units", params, headers)

    def update_unit(self, unit_id: str, payload: dict, headers: dict):
        return self._request("PATCH", f"/units/{unit_id}", payload, headers)

    # ------------------------------------------------------- unit allocations
    def create_allocation(self, payload: dict, headers: dict):
        return self._request("POST", "/unit-tract-allocations", payload, headers)

    def get_allocation(self, allocation_id: str, headers: dict):
        return self._request(
            "GET", f"/unit-tract-allocations/{allocation_id}", None, headers
        )

    def list_unit_tract_allocations(
        self, unit_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request("GET", f"/units/{unit_id}/tract-allocations", params, headers)

    def pugh_release(self, allocation_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"/unit-tract-allocations/{allocation_id}/pugh-release",
            payload or {},
            headers,
        )

    def terminate_allocation(self, allocation_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/unit-tract-allocations/{allocation_id}/terminate", payload, headers
        )

    # ---------------------------------------------------------- division orders
    def create_division_order(self, payload: dict, headers: dict):
        return self._request("POST", "/division-orders", payload, headers)

    def get_division_order(self, order_id: str, headers: dict):
        return self._request("GET", f"/division-orders/{order_id}", None, headers)

    def list_division_orders(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/division-orders", params, headers)

    def operator_response(self, order_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/division-orders/{order_id}/operator-response", payload, headers
        )

    def correct_division_order(self, order_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/division-orders/{order_id}/correct", payload, headers
        )

    # --------------------------------------------------- revenue check details
    def create_revenue_check_detail(self, order_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/division-orders/{order_id}/revenue-check-details", payload, headers
        )

    def list_revenue_check_details(
        self, order_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/division-orders/{order_id}/revenue-check-details", params, headers
        )

    def get_revenue_check_detail(self, detail_id: str, headers: dict):
        return self._request("GET", f"/revenue-check-details/{detail_id}", None, headers)

    # ------------------------------------------------------- suspense accounts
    def get_suspense_account(self, suspense_id: str, headers: dict):
        return self._request("GET", f"/suspense-accounts/{suspense_id}", None, headers)

    def list_suspense_accounts(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/suspense-accounts", params, headers)

    def release_suspense(self, suspense_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/suspense-accounts/{suspense_id}/release", payload or {}, headers
        )

    def escheat_suspense(self, suspense_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/suspense-accounts/{suspense_id}/escheat", payload, headers
        )

    # ------------------------------------------------------------------- clock
    def set_clock(self, payload: dict, headers: dict):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)
