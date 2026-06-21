"""API client: one method per endpoint defined in the iBuyer Home Offer PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Sellers ---
    def create_seller(self, payload, headers):
        return self._request("POST", "/sellers", payload, headers)

    def get_seller(self, seller_id, headers):
        return self._request("GET", f"/sellers/{seller_id}", headers=headers)

    # --- Properties ---
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def issue_offer(self, property_id, payload, headers):
        return self._request(
            "POST", f"/properties/{property_id}/offers", payload, headers
        )

    def list_property_offers(self, property_id, headers, params=None):
        return self._request(
            "GET", f"/properties/{property_id}/offers", headers=headers, params=params
        )

    def withdraw_property(self, property_id, payload, headers):
        return self._request(
            "POST", f"/properties/{property_id}/withdraw", payload, headers
        )

    # --- Offers ---
    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/offers/{offer_id}", headers=headers)

    def accept_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/offers/{offer_id}/accept", payload, headers)

    def decline_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/offers/{offer_id}/decline", payload, headers)

    def get_offer_assessment(self, offer_id, headers):
        return self._request(
            "GET", f"/offers/{offer_id}/assessment", headers=headers
        )

    # --- Assessments + repair line items ---
    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/assessments/{assessment_id}", headers=headers)

    def create_repair_line_item(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/assessments/{assessment_id}/repair-line-items", payload, headers
        )

    def list_assessment_repair_line_items(self, assessment_id, headers, params=None):
        return self._request(
            "GET",
            f"/assessments/{assessment_id}/repair-line-items",
            headers=headers,
            params=params,
        )

    def list_repair_line_items(self, headers, params=None):
        return self._request(
            "GET", "/repair-line-items", headers=headers, params=params
        )

    def finalize_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/assessments/{assessment_id}/finalize", payload, headers
        )

    # --- Transactions ---
    def list_transactions(self, headers, params=None):
        return self._request("GET", "/transactions", headers=headers, params=params)

    def get_transaction(self, transaction_id, headers):
        return self._request(
            "GET", f"/transactions/{transaction_id}", headers=headers
        )

    def schedule_close(self, transaction_id, payload, headers):
        return self._request(
            "POST", f"/transactions/{transaction_id}/schedule-close", payload, headers
        )

    def start_inspection(self, transaction_id, payload, headers):
        return self._request(
            "POST", f"/transactions/{transaction_id}/start-inspection", payload, headers
        )

    def retrade(self, transaction_id, payload, headers):
        return self._request(
            "POST", f"/transactions/{transaction_id}/retrade", payload, headers
        )

    def close_transaction(self, transaction_id, payload, headers):
        return self._request(
            "POST", f"/transactions/{transaction_id}/close", payload, headers
        )

    def cancel_transaction(self, transaction_id, payload, headers):
        return self._request(
            "POST", f"/transactions/{transaction_id}/cancel", payload, headers
        )

    # --- Resales ---
    def create_resale(self, payload, headers):
        return self._request("POST", "/resales", payload, headers)

    def list_resales(self, headers, params=None):
        return self._request("GET", "/resales", headers=headers, params=params)

    def get_resale(self, resale_id, headers):
        return self._request("GET", f"/resales/{resale_id}", headers=headers)

    def sell_resale(self, resale_id, payload, headers):
        return self._request("POST", f"/resales/{resale_id}/sell", payload, headers)

    def delist_resale(self, resale_id, payload, headers):
        return self._request("POST", f"/resales/{resale_id}/delist", payload, headers)

    # --- Logical clock (auth-exempt control endpoint, PRD §2.7) ---
    def set_clock(self, to_iso8601, headers=None):
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )


api_client = ApiClient()
