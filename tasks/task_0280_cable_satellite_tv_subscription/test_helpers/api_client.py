"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Test-driving clock ───────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Catalog: channel packages ────────────────────────────────────────
    def create_channel_package(self, payload, headers):
        return self._request("POST", "/channel-packages", payload, headers)

    def list_channel_packages(self, headers, params=None):
        return self._request("GET", "/channel-packages", headers=headers, params=params)

    def get_channel_package(self, package_id, headers):
        return self._request("GET", f"/channel-packages/{package_id}", headers=headers)

    # ─── Catalog: premium channels ────────────────────────────────────────
    def create_premium_channel(self, payload, headers):
        return self._request("POST", "/premium-channels", payload, headers)

    def list_premium_channels(self, headers, params=None):
        return self._request("GET", "/premium-channels", headers=headers, params=params)

    # ─── Catalog: equipment models ────────────────────────────────────────
    def create_equipment_model(self, payload, headers):
        return self._request("POST", "/equipment-models", payload, headers)

    def list_equipment_models(self, headers, params=None):
        return self._request("GET", "/equipment-models", headers=headers, params=params)

    # ─── Catalog: promotion offers ────────────────────────────────────────
    def create_promotion_offer(self, payload, headers):
        return self._request("POST", "/promotion-offers", payload, headers)

    def list_promotion_offers(self, headers, params=None):
        return self._request("GET", "/promotion-offers", headers=headers, params=params)

    # ─── Catalog: regional sports fee rules ───────────────────────────────
    def create_regional_sports_fee_rule(self, payload, headers):
        return self._request("POST", "/regional-sports-fee-rules", payload, headers)

    def list_regional_sports_fee_rules(self, headers, params=None):
        return self._request("GET", "/regional-sports-fee-rules", headers=headers, params=params)

    # ─── Catalog: technicians ─────────────────────────────────────────────
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/technicians", headers=headers, params=params)

    # ─── Cross-aggregate reverse-lookup lists ─────────────────────────────
    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def list_add_ons(self, headers, params=None):
        return self._request("GET", "/add-ons", headers=headers, params=params)

    def get_add_on(self, add_on_id, headers):
        return self._request("GET", f"/add-ons/{add_on_id}", headers=headers)

    def list_equipment_leases(self, headers, params=None):
        return self._request("GET", "/equipment-leases", headers=headers, params=params)

    def get_equipment_lease(self, lease_id, headers):
        return self._request("GET", f"/equipment-leases/{lease_id}", headers=headers)

    def list_service_visits(self, headers, params=None):
        return self._request("GET", "/service-visits", headers=headers, params=params)

    def get_service_visit(self, visit_id, headers):
        return self._request("GET", f"/service-visits/{visit_id}", headers=headers)

    def list_promotion_applications(self, headers, params=None):
        return self._request("GET", "/promotion-applications", headers=headers, params=params)

    def get_promotion_application(self, application_id, headers):
        return self._request("GET", f"/promotion-applications/{application_id}", headers=headers)

    # ─── Account lifecycle ────────────────────────────────────────────────
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/suspend", {}, headers)

    def reactivate_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/reactivate", {}, headers)

    def cancel_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/cancel", {}, headers)

    def advance_cycle(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/advance-cycle", {}, headers)

    # ─── Subscriptions (tier) ─────────────────────────────────────────────
    def create_subscription(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/subscriptions", payload, headers)

    def list_account_subscriptions(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/subscriptions", headers=headers, params=params)

    def downgrade_subscription(self, account_id, subscription_id, payload, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/subscriptions/{subscription_id}/downgrade", payload, headers
        )

    def upgrade_subscription(self, account_id, subscription_id, payload, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/subscriptions/{subscription_id}/upgrade", payload, headers
        )

    # ─── Add-ons ──────────────────────────────────────────────────────────
    def attach_add_on(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/add-ons", payload, headers)

    def list_account_add_ons(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/add-ons", headers=headers, params=params)

    def drop_add_on(self, account_id, add_on_id, headers):
        return self._request("POST", f"/accounts/{account_id}/add-ons/{add_on_id}/drop", {}, headers)

    # ─── Equipment ────────────────────────────────────────────────────────
    def assign_equipment_lease(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/equipment-leases", payload, headers)

    def list_account_equipment_leases(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/equipment-leases", headers=headers, params=params)

    def return_equipment_lease(self, account_id, lease_id, headers):
        return self._request("POST", f"/accounts/{account_id}/equipment-leases/{lease_id}/return", {}, headers)

    # ─── Service visits ───────────────────────────────────────────────────
    def schedule_service_visit(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/service-visits", payload, headers)

    def list_account_service_visits(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/service-visits", headers=headers, params=params)

    def dispatch_service_visit(self, account_id, visit_id, headers):
        return self._request("POST", f"/accounts/{account_id}/service-visits/{visit_id}/dispatch", {}, headers)

    def complete_service_visit(self, account_id, visit_id, payload, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/service-visits/{visit_id}/complete", payload, headers
        )

    def no_show_service_visit(self, account_id, visit_id, headers):
        return self._request("POST", f"/accounts/{account_id}/service-visits/{visit_id}/no-show", {}, headers)

    def cancel_service_visit(self, account_id, visit_id, headers):
        return self._request("POST", f"/accounts/{account_id}/service-visits/{visit_id}/cancel", {}, headers)

    # ─── Promotions ───────────────────────────────────────────────────────
    def apply_promotion(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/promotions", payload, headers)

    def list_account_promotions(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/promotions", headers=headers, params=params)

    # ─── Billing ──────────────────────────────────────────────────────────
    def issue_billing_statement(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/billing-statements", payload, headers)

    def list_account_billing_statements(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/billing-statements", headers=headers, params=params)

    def get_billing_statement(self, account_id, statement_id, headers):
        return self._request(
            "GET", f"/accounts/{account_id}/billing-statements/{statement_id}", headers=headers
        )


api_client = ApiClient()
