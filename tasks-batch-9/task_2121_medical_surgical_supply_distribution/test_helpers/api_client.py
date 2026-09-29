"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Supply rooms ─────────────────────────────────────────────────

    def create_supply_room(self, payload, headers):
        return self._request("POST", "/supply-rooms", payload, headers)

    def get_supply_room(self, supply_room_id, headers):
        return self._request("GET", f"/supply-rooms/{supply_room_id}", headers=headers)

    # ─── Item master ──────────────────────────────────────────────────

    def create_item(self, payload, headers):
        return self._request("POST", "/items", payload, headers)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/items/{item_id}", headers=headers)

    def list_items(self, headers, params=None):
        return self._request("GET", "/items", headers=headers, params=params)

    # ─── GPO contracts ────────────────────────────────────────────────

    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def transition_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/transition", payload, headers
        )

    # ─── Contract lines ───────────────────────────────────────────────

    def create_contract_line(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/lines", payload, headers)

    def get_contract_line(self, contract_line_id, headers):
        return self._request(
            "GET", f"/contract-lines/{contract_line_id}", headers=headers
        )

    def list_contract_lines(self, headers, params=None):
        return self._request("GET", "/contract-lines", headers=headers, params=params)

    # ─── Formulary items ──────────────────────────────────────────────

    def create_formulary_item(self, supply_room_id, payload, headers):
        return self._request(
            "POST", f"/supply-rooms/{supply_room_id}/formulary-items", payload, headers
        )

    def get_formulary_item(self, formulary_item_id, headers):
        return self._request(
            "GET", f"/formulary-items/{formulary_item_id}", headers=headers
        )

    def list_formulary_items(self, headers, params=None):
        return self._request("GET", "/formulary-items", headers=headers, params=params)

    def decide_formulary_item(self, formulary_item_id, payload, headers):
        return self._request(
            "POST", f"/formulary-items/{formulary_item_id}/decision", payload, headers
        )

    def adjust_on_hand(self, formulary_item_id, payload, headers):
        return self._request(
            "POST",
            f"/formulary-items/{formulary_item_id}/adjust-on-hand",
            payload,
            headers,
        )

    def get_replenishment_suggestion(self, formulary_item_id, headers, params=None):
        return self._request(
            "GET",
            f"/formulary-items/{formulary_item_id}/replenishment-suggestion",
            headers=headers,
            params=params,
        )

    # ─── Lots ─────────────────────────────────────────────────────────

    def create_lot(self, payload, headers):
        return self._request("POST", "/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/lots", headers=headers, params=params)

    def lot_excursion(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/excursion", payload, headers)

    # ─── Replenishment orders ─────────────────────────────────────────

    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def create_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/submit", {}, headers)

    def allocate_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/allocate", {}, headers)

    def deliver_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/deliver", {}, headers)

    # ─── Order lines ──────────────────────────────────────────────────

    def get_order_line(self, order_line_id, headers):
        return self._request("GET", f"/order-lines/{order_line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    # ─── Substitution requests ────────────────────────────────────────

    def create_substitution_request(self, order_line_id, payload, headers):
        return self._request(
            "POST", f"/order-lines/{order_line_id}/substitution-requests", payload, headers
        )

    def get_substitution_request(self, substitution_request_id, headers):
        return self._request(
            "GET", f"/substitution-requests/{substitution_request_id}", headers=headers
        )

    def list_substitution_requests(self, headers, params=None):
        return self._request(
            "GET", "/substitution-requests", headers=headers, params=params
        )

    def clinician_action(self, substitution_request_id, payload, headers):
        return self._request(
            "POST",
            f"/substitution-requests/{substitution_request_id}/clinician-action",
            payload,
            headers,
        )

    def respond_substitution_request(self, substitution_request_id, payload, headers):
        return self._request(
            "POST",
            f"/substitution-requests/{substitution_request_id}/respond",
            payload,
            headers,
        )

    # ─── Recall notices ───────────────────────────────────────────────

    def create_recall_notice(self, payload, headers):
        return self._request("POST", "/recall-notices", payload, headers)

    def get_recall_notice(self, recall_notice_id, headers):
        return self._request(
            "GET", f"/recall-notices/{recall_notice_id}", headers=headers
        )

    def list_recall_notices(self, headers, params=None):
        return self._request("GET", "/recall-notices", headers=headers, params=params)

    def cascade_recall_notice(self, recall_notice_id, payload, headers):
        return self._request(
            "POST", f"/recall-notices/{recall_notice_id}/cascade", payload, headers
        )

    # ─── Delivery routes ──────────────────────────────────────────────

    def create_delivery_route(self, payload, headers):
        return self._request("POST", "/delivery-routes", payload, headers)

    def get_delivery_route(self, route_id, headers):
        return self._request("GET", f"/delivery-routes/{route_id}", headers=headers)

    def list_delivery_routes(self, headers, params=None):
        return self._request("GET", "/delivery-routes", headers=headers, params=params)

    def create_route_stop(self, route_id, payload, headers):
        return self._request(
            "POST", f"/delivery-routes/{route_id}/stops", payload, headers
        )

    def dispatch_route(self, route_id, headers):
        return self._request(
            "POST", f"/delivery-routes/{route_id}/dispatch", {}, headers
        )

    # ─── Chargeback claims ────────────────────────────────────────────

    def create_chargeback_claim(self, payload, headers):
        return self._request("POST", "/chargeback-claims", payload, headers)

    def get_chargeback_claim(self, chargeback_claim_id, headers):
        return self._request(
            "GET", f"/chargeback-claims/{chargeback_claim_id}", headers=headers
        )

    def list_chargeback_claims(self, headers, params=None):
        return self._request("GET", "/chargeback-claims", headers=headers, params=params)

    def respond_chargeback_claim(self, chargeback_claim_id, payload, headers):
        return self._request(
            "POST", f"/chargeback-claims/{chargeback_claim_id}/response", payload, headers
        )

    def settle_chargeback_claim(self, chargeback_claim_id, payload, headers):
        return self._request(
            "POST", f"/chargeback-claims/{chargeback_claim_id}/settle", payload, headers
        )

    # ─── Logical clock ────────────────────────────────────────────────

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
