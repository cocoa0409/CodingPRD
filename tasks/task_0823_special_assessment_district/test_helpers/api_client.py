"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Districts ----
    def create_district(self, payload, headers):
        return self._request("POST", "/districts", payload, headers)

    def get_district(self, district_id, headers):
        return self._request("GET", f"/districts/{district_id}", headers=headers)

    def open_protest(self, district_id, headers):
        return self._request("POST", f"/districts/{district_id}/open-protest", {}, headers)

    def close_hearing(self, district_id, headers):
        return self._request("POST", f"/districts/{district_id}/close-hearing", {}, headers)

    # ---- Parcels ----
    def create_parcel(self, district_id, payload, headers):
        return self._request("POST", f"/districts/{district_id}/parcels", payload, headers)

    def list_district_parcels(self, district_id, headers, params=None):
        return self._request("GET", f"/districts/{district_id}/parcels", headers=headers, params=params)

    def get_parcel(self, parcel_id, headers):
        return self._request("GET", f"/parcels/{parcel_id}", headers=headers)

    def list_parcels(self, headers, params=None):
        return self._request("GET", "/parcels", headers=headers, params=params)

    def subdivide_parcel(self, parcel_id, payload, headers):
        return self._request("POST", f"/parcels/{parcel_id}/subdivide", payload, headers)

    def consolidate_parcel(self, parcel_id, headers):
        return self._request("POST", f"/parcels/{parcel_id}/consolidate", {}, headers)

    def create_protest(self, parcel_id, payload, headers):
        return self._request("POST", f"/parcels/{parcel_id}/protests", payload, headers)

    def list_protests(self, parcel_id, headers, params=None):
        return self._request("GET", f"/parcels/{parcel_id}/protests", headers=headers, params=params)

    # ---- Rolls ----
    def create_roll(self, district_id, payload, headers):
        return self._request("POST", f"/districts/{district_id}/rolls", payload, headers)

    def list_rolls(self, district_id, headers, params=None):
        return self._request("GET", f"/districts/{district_id}/rolls", headers=headers, params=params)

    def confirm_roll(self, roll_id, headers):
        return self._request("POST", f"/rolls/{roll_id}/confirm", {}, headers)

    # ---- Bonds ----
    def create_bond(self, district_id, payload, headers):
        return self._request("POST", f"/districts/{district_id}/bonds", payload, headers)

    def list_bonds(self, district_id, headers, params=None):
        return self._request("GET", f"/districts/{district_id}/bonds", headers=headers, params=params)

    def issue_bond(self, bond_id, headers):
        return self._request("POST", f"/bonds/{bond_id}/issue", {}, headers)

    # ---- Installments ----
    def create_installment(self, parcel_id, payload, headers):
        return self._request("POST", f"/parcels/{parcel_id}/installments", payload, headers)

    def get_installment(self, installment_id, headers):
        return self._request("GET", f"/installments/{installment_id}", headers=headers)

    def list_installments(self, headers, params=None):
        return self._request("GET", "/installments", headers=headers, params=params)

    def create_payment(self, installment_id, payload, headers):
        return self._request("POST", f"/installments/{installment_id}/payments", payload, headers)

    def list_payments(self, installment_id, headers, params=None):
        return self._request("GET", f"/installments/{installment_id}/payments", headers=headers, params=params)

    def reverse_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/reverse", {}, headers)

    def mark_delinquent(self, installment_id, headers):
        return self._request("POST", f"/installments/{installment_id}/mark-delinquent", {}, headers)

    # ---- Payoff quotes ----
    def create_payoff_quote(self, parcel_id, payload, headers):
        return self._request("POST", f"/parcels/{parcel_id}/payoff-quotes", payload, headers)

    def list_payoff_quotes(self, parcel_id, headers, params=None):
        return self._request("GET", f"/parcels/{parcel_id}/payoff-quotes", headers=headers, params=params)

    def honor_payoff_quote(self, quote_id, headers):
        return self._request("POST", f"/payoff-quotes/{quote_id}/honor", {}, headers)

    # ---- Foreclosures ----
    def create_foreclosure(self, parcel_id, headers):
        return self._request("POST", f"/parcels/{parcel_id}/foreclosures", {}, headers)

    def list_foreclosures(self, parcel_id, headers, params=None):
        return self._request("GET", f"/parcels/{parcel_id}/foreclosures", headers=headers, params=params)

    def advance_foreclosure(self, foreclosure_id, payload, headers):
        return self._request("POST", f"/foreclosures/{foreclosure_id}/advance", payload, headers)

    # ---- Liens & disclosure ----
    def list_liens(self, parcel_id, headers, params=None):
        return self._request("GET", f"/parcels/{parcel_id}/liens", headers=headers, params=params)

    def get_disclosure(self, parcel_id, headers):
        return self._request("GET", f"/parcels/{parcel_id}/disclosure", headers=headers)

    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
