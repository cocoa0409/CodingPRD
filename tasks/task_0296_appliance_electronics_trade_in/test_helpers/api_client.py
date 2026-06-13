"""API client: one method per endpoint defined in the PRD (Appliance & Electronics Trade-In API)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Catalog & config ─────────────────────────────
    def create_catalog(self, payload, headers):
        return self._request("POST", "/catalogs", payload, headers)

    def get_catalog(self, catalog_id, headers):
        return self._request("GET", f"/catalogs/{catalog_id}", headers=headers)

    def create_device_model(self, catalog_id, payload, headers):
        return self._request("POST", f"/catalogs/{catalog_id}/device-models", payload, headers)

    def list_device_models(self, catalog_id, headers, params=None):
        return self._request("GET", f"/catalogs/{catalog_id}/device-models", headers=headers, params=params)

    def get_device_model(self, model_id, headers):
        return self._request("GET", f"/device-models/{model_id}", headers=headers)

    def retire_device_model(self, model_id, headers):
        return self._request("POST", f"/device-models/{model_id}/retire", {}, headers)

    def create_promotion_campaign(self, catalog_id, payload, headers):
        return self._request("POST", f"/catalogs/{catalog_id}/promotion-campaigns", payload, headers)

    def list_promotion_campaigns(self, catalog_id, headers, params=None):
        return self._request("GET", f"/catalogs/{catalog_id}/promotion-campaigns", headers=headers, params=params)

    def expire_promotion_campaign(self, campaign_id, headers):
        return self._request("POST", f"/promotion-campaigns/{campaign_id}/expire", {}, headers)

    def create_inspection_slot(self, catalog_id, payload, headers):
        return self._request("POST", f"/catalogs/{catalog_id}/inspection-slots", payload, headers)

    def list_inspection_slots(self, catalog_id, headers, params=None):
        return self._request("GET", f"/catalogs/{catalog_id}/inspection-slots", headers=headers, params=params)

    def release_inspection_slot(self, slot_id, headers):
        return self._request("POST", f"/inspection-slots/{slot_id}/release", {}, headers)

    # ─── Customers ────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customer_trade_ins(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/trade-ins", headers=headers, params=params)

    # ─── Trade-in lifecycle ───────────────────────────
    def create_trade_in(self, payload, headers):
        return self._request("POST", "/trade-ins", payload, headers)

    def get_trade_in(self, trade_in_id, headers):
        return self._request("GET", f"/trade-ins/{trade_in_id}", headers=headers)

    def list_trade_ins(self, headers, params=None):
        return self._request("GET", "/trade-ins", headers=headers, params=params)

    def quote_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/quote", {}, headers)

    def ship_kit(self, trade_in_id, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/ship-kit", {}, headers)

    def receive_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/receive", {}, headers)

    def inspect_trade_in(self, trade_in_id, payload, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/inspect", payload, headers)

    def reinspect_trade_in(self, trade_in_id, payload, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/reinspect", payload, headers)

    def accept_requote(self, trade_in_id, payload, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/accept-requote", payload, headers)

    def decline_requote(self, trade_in_id, payload, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/decline-requote", payload, headers)

    def cancel_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/cancel", {}, headers)

    def sweep_expiry(self, trade_in_id, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/sweep-expiry", {}, headers)

    # ─── Child resources & reads ──────────────────────
    def list_quotes(self, trade_in_id, headers, params=None):
        return self._request("GET", f"/trade-ins/{trade_in_id}/quotes", headers=headers, params=params)

    def list_shipping_kits(self, trade_in_id, headers, params=None):
        return self._request("GET", f"/trade-ins/{trade_in_id}/shipping-kits", headers=headers, params=params)

    def list_inspections(self, trade_in_id, headers, params=None):
        return self._request("GET", f"/trade-ins/{trade_in_id}/inspections", headers=headers, params=params)

    def create_data_wipe(self, trade_in_id, payload, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/data-wipe", payload, headers)

    def list_data_wipe_certificates(self, trade_in_id, headers, params=None):
        return self._request("GET", f"/trade-ins/{trade_in_id}/data-wipe-certificates", headers=headers, params=params)

    def create_payout(self, trade_in_id, payload, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/payouts", payload, headers)

    def list_payouts(self, trade_in_id, headers, params=None):
        return self._request("GET", f"/trade-ins/{trade_in_id}/payouts", headers=headers, params=params)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/payouts/{payout_id}", headers=headers)

    def reverse_payout(self, trade_in_id, payout_id, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/payouts/{payout_id}/reverse", {}, headers)

    def list_disposition_records(self, trade_in_id, headers, params=None):
        return self._request("GET", f"/trade-ins/{trade_in_id}/disposition-records", headers=headers, params=params)

    # ─── Test-driving clock ───────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
