"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- County ---
    def create_county(self, payload, headers):
        return self._request("POST", "/counties", payload, headers)

    def get_county(self, county_id, headers):
        return self._request("GET", f"/counties/{county_id}", headers=headers)

    # --- Parcel ---
    def create_parcel(self, county_id, payload, headers):
        return self._request(
            "POST", f"/counties/{county_id}/parcels", payload, headers
        )

    def get_parcel(self, county_id, parcel_id, headers):
        return self._request(
            "GET", f"/counties/{county_id}/parcels/{parcel_id}", headers=headers
        )

    def list_parcels(self, county_id, headers, params=None):
        return self._request(
            "GET", f"/counties/{county_id}/parcels", headers=headers, params=params
        )

    # --- Investor ---
    def create_investor(self, payload, headers):
        return self._request("POST", "/investors", payload, headers)

    def get_investor(self, investor_id, headers):
        return self._request("GET", f"/investors/{investor_id}", headers=headers)

    def create_deposit(self, investor_id, payload, headers):
        return self._request(
            "POST", f"/investors/{investor_id}/deposits", payload, headers
        )

    # --- TaxSale ---
    def create_sale(self, county_id, payload, headers):
        return self._request("POST", f"/counties/{county_id}/sales", payload, headers)

    def get_sale(self, county_id, sale_id, headers):
        return self._request(
            "GET", f"/counties/{county_id}/sales/{sale_id}", headers=headers
        )

    def list_sales(self, county_id, headers, params=None):
        return self._request(
            "GET", f"/counties/{county_id}/sales", headers=headers, params=params
        )

    def open_sale(self, county_id, sale_id, headers):
        return self._request(
            "POST", f"/counties/{county_id}/sales/{sale_id}/open", {}, headers
        )

    def close_sale(self, county_id, sale_id, headers):
        return self._request(
            "POST", f"/counties/{county_id}/sales/{sale_id}/close", {}, headers
        )

    def settle_sale(self, county_id, sale_id, headers):
        return self._request(
            "POST", f"/counties/{county_id}/sales/{sale_id}/settle", {}, headers
        )

    # --- SaleListing ---
    def create_listing(self, county_id, sale_id, payload, headers):
        return self._request(
            "POST", f"/counties/{county_id}/sales/{sale_id}/listings", payload, headers
        )

    def get_listing(self, county_id, sale_id, listing_id, headers):
        return self._request(
            "GET",
            f"/counties/{county_id}/sales/{sale_id}/listings/{listing_id}",
            headers=headers,
        )

    def list_listings(self, county_id, sale_id, headers, params=None):
        return self._request(
            "GET",
            f"/counties/{county_id}/sales/{sale_id}/listings",
            headers=headers,
            params=params,
        )

    def withdraw_listing(self, county_id, sale_id, listing_id, headers):
        return self._request(
            "POST",
            f"/counties/{county_id}/sales/{sale_id}/listings/{listing_id}/withdraw",
            {},
            headers,
        )

    # --- Bid ---
    def create_bid(self, county_id, sale_id, listing_id, payload, headers):
        return self._request(
            "POST",
            f"/counties/{county_id}/sales/{sale_id}/listings/{listing_id}/bids",
            payload,
            headers,
        )

    def get_bid(self, county_id, sale_id, listing_id, bid_id, headers):
        return self._request(
            "GET",
            f"/counties/{county_id}/sales/{sale_id}/listings/{listing_id}/bids/{bid_id}",
            headers=headers,
        )

    def list_bids(self, county_id, sale_id, listing_id, headers, params=None):
        return self._request(
            "GET",
            f"/counties/{county_id}/sales/{sale_id}/listings/{listing_id}/bids",
            headers=headers,
            params=params,
        )

    # --- Certificate ---
    def get_certificate(self, county_id, certificate_id, headers):
        return self._request(
            "GET",
            f"/counties/{county_id}/certificates/{certificate_id}",
            headers=headers,
        )

    def list_certificates(self, county_id, headers, params=None):
        return self._request(
            "GET",
            f"/counties/{county_id}/certificates",
            headers=headers,
            params=params,
        )

    def get_payoff_quote(self, county_id, certificate_id, headers):
        return self._request(
            "GET",
            f"/counties/{county_id}/certificates/{certificate_id}/payoff-quote",
            headers=headers,
        )

    def redeem_certificate(self, county_id, certificate_id, headers):
        return self._request(
            "POST",
            f"/counties/{county_id}/certificates/{certificate_id}/redeem",
            {},
            headers,
        )

    # --- SubsequentTax ---
    def create_sub_tax(self, county_id, certificate_id, payload, headers):
        return self._request(
            "POST",
            f"/counties/{county_id}/certificates/{certificate_id}/sub-taxes",
            payload,
            headers,
        )

    def list_sub_taxes(self, county_id, certificate_id, headers, params=None):
        return self._request(
            "GET",
            f"/counties/{county_id}/certificates/{certificate_id}/sub-taxes",
            headers=headers,
            params=params,
        )

    # --- Redemption ---
    def list_redemptions(self, county_id, certificate_id, headers, params=None):
        return self._request(
            "GET",
            f"/counties/{county_id}/certificates/{certificate_id}/redemptions",
            headers=headers,
            params=params,
        )

    # --- Assignment ---
    def create_assignment(self, county_id, certificate_id, payload, headers):
        return self._request(
            "POST",
            f"/counties/{county_id}/certificates/{certificate_id}/assignments",
            payload,
            headers,
        )

    def list_assignments(self, county_id, certificate_id, headers, params=None):
        return self._request(
            "GET",
            f"/counties/{county_id}/certificates/{certificate_id}/assignments",
            headers=headers,
            params=params,
        )

    # --- DeedApplication ---
    def create_deed_application(self, county_id, certificate_id, payload, headers):
        return self._request(
            "POST",
            f"/counties/{county_id}/certificates/{certificate_id}/deed-applications",
            payload,
            headers,
        )

    def get_deed_application(self, county_id, deed_application_id, headers):
        return self._request(
            "GET",
            f"/counties/{county_id}/deed-applications/{deed_application_id}",
            headers=headers,
        )

    def list_deed_applications(self, county_id, certificate_id, headers, params=None):
        return self._request(
            "GET",
            f"/counties/{county_id}/certificates/{certificate_id}/deed-applications",
            headers=headers,
            params=params,
        )

    def award_deed(self, county_id, deed_application_id, payload, headers):
        return self._request(
            "POST",
            f"/counties/{county_id}/deed-applications/{deed_application_id}/award",
            payload,
            headers,
        )

    def cancel_deed(self, county_id, deed_application_id, headers):
        return self._request(
            "POST",
            f"/counties/{county_id}/deed-applications/{deed_application_id}/cancel",
            {},
            headers,
        )

    # --- SurplusDistribution ---
    def list_surplus_by_deed(self, county_id, deed_application_id, headers, params=None):
        return self._request(
            "GET",
            f"/counties/{county_id}/deed-applications/{deed_application_id}/surplus",
            headers=headers,
            params=params,
        )

    def list_surplus_by_certificate(self, county_id, certificate_id, headers, params=None):
        return self._request(
            "GET",
            f"/counties/{county_id}/certificates/{certificate_id}/surplus",
            headers=headers,
            params=params,
        )

    def claim_surplus(self, county_id, deed_application_id, surplus_id, headers):
        return self._request(
            "POST",
            f"/counties/{county_id}/deed-applications/{deed_application_id}/surplus/{surplus_id}/claim",
            {},
            headers,
        )


api_client = ApiClient()
