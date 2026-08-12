"""API client: one method per endpoint defined in the PRD (Section 4).

All endpoints are mounted under /api. List methods accept a params dict for
the PRD's documented filters plus limit/offset; None values are dropped.
"""
from prd_bench_local_runner.testing import GenericApiClient


def _clean(params):
    if not params:
        return None
    return {k: v for k, v in params.items() if v is not None}


class ApiClient(GenericApiClient):
    # --- logical clock (test-driving) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- catalog products ---
    def create_catalog_product(self, payload, headers):
        return self._request("POST", "/api/catalog/products", payload, headers)

    def get_catalog_product(self, product_id, headers):
        return self._request(
            "GET", f"/api/catalog/products/{product_id}", headers=headers
        )

    def list_catalog_products(self, headers, params=None):
        return self._request(
            "GET", "/api/catalog/products", headers=headers, params=_clean(params)
        )

    # --- customers ---
    def register_customer(self, payload, headers=None):
        # Registration is the one unauthenticated endpoint (PRD 2.1).
        return self._request("POST", "/api/customers/register", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    def set_customer_status(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/api/customers/{customer_id}/status", payload, headers
        )

    # --- lawns ---
    def create_lawn(self, payload, headers):
        return self._request("POST", "/api/lawns", payload, headers)

    def get_lawn(self, lawn_id, headers):
        return self._request("GET", f"/api/lawns/{lawn_id}", headers=headers)

    def list_lawns(self, headers, params=None):
        return self._request("GET", "/api/lawns", headers=headers, params=_clean(params))

    def patch_lawn(self, lawn_id, payload, headers):
        return self._request("PATCH", f"/api/lawns/{lawn_id}", payload, headers)

    # --- soil test kits ---
    def create_soil_test(self, payload, headers):
        return self._request("POST", "/api/soil-tests", payload, headers)

    def get_soil_test(self, soil_test_id, headers):
        return self._request("GET", f"/api/soil-tests/{soil_test_id}", headers=headers)

    def list_soil_tests(self, headers, params=None):
        return self._request(
            "GET", "/api/soil-tests", headers=headers, params=_clean(params)
        )

    def return_sample(self, soil_test_id, headers):
        return self._request(
            "POST", f"/api/soil-tests/{soil_test_id}/return-sample", None, headers
        )

    def post_lab_result(self, soil_test_id, payload, headers):
        return self._request(
            "POST", f"/api/soil-tests/{soil_test_id}/lab-result", payload, headers
        )

    # --- plan versions ---
    def create_plan(self, payload, headers):
        return self._request("POST", "/api/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/api/plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/api/plans", headers=headers, params=_clean(params))

    def submit_plan_review(self, plan_id, headers):
        return self._request(
            "POST", f"/api/plans/{plan_id}/submit-review", None, headers
        )

    def patch_plan(self, plan_id, payload, headers):
        return self._request("PATCH", f"/api/plans/{plan_id}", payload, headers)

    def activate_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/api/plans/{plan_id}/activate", payload, headers)

    # --- subscriptions ---
    def create_subscription(self, payload, headers):
        return self._request("POST", "/api/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request(
            "GET", f"/api/subscriptions/{subscription_id}", headers=headers
        )

    def list_subscriptions(self, headers, params=None):
        return self._request(
            "GET", "/api/subscriptions", headers=headers, params=_clean(params)
        )

    def patch_subscription(self, subscription_id, payload, headers):
        return self._request(
            "PATCH", f"/api/subscriptions/{subscription_id}", payload, headers
        )

    def set_subscription_status(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/api/subscriptions/{subscription_id}/status", payload, headers
        )

    def skip_next_shipment(self, subscription_id, headers):
        return self._request(
            "POST", f"/api/subscriptions/{subscription_id}/skip-next-shipment", None, headers
        )

    def cancel_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/api/subscriptions/{subscription_id}/cancel", None, headers
        )

    # --- shipment boxes ---
    def create_shipment(self, payload, headers):
        return self._request("POST", "/api/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/api/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request(
            "GET", "/api/shipments", headers=headers, params=_clean(params)
        )

    def advance_fulfillment(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/api/shipments/{shipment_id}/advance-fulfillment", payload, headers
        )

    # --- application tasks ---
    def create_application(self, payload, headers):
        return self._request("POST", "/api/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request(
            "GET", f"/api/applications/{application_id}", headers=headers
        )

    def list_applications(self, headers, params=None):
        return self._request(
            "GET", "/api/applications", headers=headers, params=_clean(params)
        )

    def reschedule_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/api/applications/{application_id}/reschedule", payload, headers
        )

    def mark_applied(self, application_id, headers):
        return self._request(
            "POST", f"/api/applications/{application_id}/mark-applied", None, headers
        )

    def get_application_reminder(self, application_id, headers):
        return self._request(
            "GET", f"/api/applications/{application_id}/reminder", headers=headers
        )

    # --- weather advisories ---
    def create_weather_advisory(self, payload, headers):
        return self._request("POST", "/api/weather-advisories", payload, headers)

    def list_weather_advisories(self, headers, params=None):
        return self._request(
            "GET", "/api/weather-advisories", headers=headers, params=_clean(params)
        )

    # --- add-on orders ---
    def create_add_on(self, payload, headers):
        return self._request("POST", "/api/add-ons", payload, headers)

    def get_add_on(self, add_on_id, headers):
        return self._request("GET", f"/api/add-ons/{add_on_id}", headers=headers)

    def list_add_ons(self, headers, params=None):
        return self._request("GET", "/api/add-ons", headers=headers, params=_clean(params))

    def confirm_add_on(self, add_on_id, headers):
        return self._request("POST", f"/api/add-ons/{add_on_id}/confirm", None, headers)

    def cancel_add_on(self, add_on_id, headers):
        return self._request("POST", f"/api/add-ons/{add_on_id}/cancel", None, headers)

    # --- invoices ---
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/api/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request(
            "GET", "/api/invoices", headers=headers, params=_clean(params)
        )

    def record_payment(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/api/invoices/{invoice_id}/record-payment", payload, headers
        )

    # --- satisfaction claims ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/api/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/api/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/api/claims", headers=headers, params=_clean(params))

    def resolve_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/api/claims/{claim_id}/resolve", payload, headers)

    # --- referrals ---
    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/api/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request(
            "GET", "/api/referrals", headers=headers, params=_clean(params)
        )

    def revoke_referral(self, referral_id, headers):
        return self._request(
            "POST", f"/api/referrals/{referral_id}/revoke", None, headers
        )

    # --- credit ledger ---
    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/api/credit-ledger/{entry_id}", headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request(
            "GET", "/api/credit-ledger", headers=headers, params=_clean(params)
        )

    def create_ledger_adjustment(self, payload, headers):
        return self._request("POST", "/api/credit-ledger/adjustments", payload, headers)


api_client = ApiClient()
