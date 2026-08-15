"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint, DistrictAdmin only)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Curriculum frameworks
    # ------------------------------------------------------------------
    def create_framework(self, payload, headers):
        return self._request("POST", "/frameworks", payload, headers)

    def list_frameworks(self, headers, params=None):
        return self._request("GET", "/frameworks", headers=headers, params=params)

    def get_framework(self, framework_id, headers):
        return self._request("GET", f"/frameworks/{framework_id}", headers=headers)

    # ------------------------------------------------------------------
    # Adoption cycles
    # ------------------------------------------------------------------
    def create_cycle(self, payload, headers):
        return self._request("POST", "/adoption-cycles", payload, headers)

    def list_cycles(self, headers, params=None):
        return self._request("GET", "/adoption-cycles", headers=headers, params=params)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/adoption-cycles/{cycle_id}", headers=headers)

    def transition_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/adoption-cycles/{cycle_id}/transitions",
                             payload, headers)

    def board_decision(self, cycle_id, payload, headers):
        return self._request("POST", f"/adoption-cycles/{cycle_id}/board-decision",
                             payload, headers)

    def award(self, cycle_id, payload, headers):
        return self._request("POST", f"/adoption-cycles/{cycle_id}/award",
                             payload, headers)

    def post_appropriation(self, cycle_id, payload, headers):
        return self._request("POST", f"/adoption-cycles/{cycle_id}/budget-appropriation",
                             payload, headers)

    def get_budget_ledger(self, cycle_id, headers):
        return self._request("GET", f"/adoption-cycles/{cycle_id}/budget-ledger",
                             headers=headers)

    def get_budget_forecast(self, cycle_id, headers, variant=None):
        params = {"variant": variant} if variant is not None else None
        return self._request("GET", f"/adoption-cycles/{cycle_id}/budget-forecast",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Instructional materials and alignment mappings
    # ------------------------------------------------------------------
    def create_material(self, cycle_id, payload, headers):
        return self._request("POST", f"/adoption-cycles/{cycle_id}/materials",
                             payload, headers)

    def list_materials(self, headers, params=None):
        return self._request("GET", "/materials", headers=headers, params=params)

    def get_material(self, material_id, headers):
        return self._request("GET", f"/materials/{material_id}", headers=headers)

    def transition_material(self, material_id, payload, headers):
        return self._request("POST", f"/materials/{material_id}/transitions",
                             payload, headers)

    def upsert_alignment(self, material_id, payload, headers):
        return self._request("POST", f"/materials/{material_id}/alignments",
                             payload, headers)

    def list_alignments(self, material_id, headers, params=None):
        return self._request("GET", f"/materials/{material_id}/alignments",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Pilot programs and teacher reviews
    # ------------------------------------------------------------------
    def create_pilot(self, cycle_id, payload, headers):
        return self._request("POST", f"/adoption-cycles/{cycle_id}/pilots",
                             payload, headers)

    def list_pilots(self, headers, params=None):
        return self._request("GET", "/pilots", headers=headers, params=params)

    def get_pilot(self, pilot_id, headers):
        return self._request("GET", f"/pilots/{pilot_id}", headers=headers)

    def transition_pilot(self, pilot_id, payload, headers):
        return self._request("POST", f"/pilots/{pilot_id}/transitions",
                             payload, headers)

    def create_review(self, pilot_id, payload, headers):
        return self._request("POST", f"/pilots/{pilot_id}/reviews", payload, headers)

    def list_reviews(self, pilot_id, headers, params=None):
        return self._request("GET", f"/pilots/{pilot_id}/reviews",
                             headers=headers, params=params)

    def withdraw_review(self, review_id, headers):
        return self._request("POST", f"/reviews/{review_id}/withdraw", {}, headers)

    # ------------------------------------------------------------------
    # Publisher quotes
    # ------------------------------------------------------------------
    def create_quote(self, cycle_id, payload, headers):
        return self._request("POST", f"/adoption-cycles/{cycle_id}/quotes",
                             payload, headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def transition_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/transitions",
                             payload, headers)

    # ------------------------------------------------------------------
    # Purchase orders
    # ------------------------------------------------------------------
    def create_purchase_order(self, cycle_id, payload, headers):
        return self._request("POST", f"/adoption-cycles/{cycle_id}/purchase-orders",
                             payload, headers)

    def list_purchase_orders(self, headers, params=None):
        return self._request("GET", "/purchase-orders", headers=headers, params=params)

    def get_purchase_order(self, po_id, headers):
        return self._request("GET", f"/purchase-orders/{po_id}", headers=headers)

    def issue_purchase_order(self, po_id, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/issue", {}, headers)

    def receive_purchase_order(self, po_id, payload, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/receive",
                             payload, headers)

    def pay_purchase_order(self, po_id, payload, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/pay", payload, headers)

    def cancel_purchase_order(self, po_id, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/cancel", {}, headers)

    def transition_purchase_order(self, po_id, payload, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/transitions",
                             payload, headers)

    # ------------------------------------------------------------------
    # Inventory lots
    # ------------------------------------------------------------------
    def get_inventory_lots(self, material_id, headers):
        return self._request("GET", f"/materials/{material_id}/inventory-lots",
                             headers=headers)

    def list_material_distribution_orders(self, material_id, headers, params=None):
        return self._request("GET", f"/materials/{material_id}/distribution-orders",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Distribution orders
    # ------------------------------------------------------------------
    def create_distribution_order(self, payload, headers):
        return self._request("POST", "/distribution-orders", payload, headers)

    def list_distribution_orders(self, headers, params=None):
        return self._request("GET", "/distribution-orders", headers=headers,
                             params=params)

    def transition_distribution_order(self, do_id, payload, headers):
        return self._request("POST", f"/distribution-orders/{do_id}/transitions",
                             payload, headers)

    # ------------------------------------------------------------------
    # Supplemental requests
    # ------------------------------------------------------------------
    def create_supplemental_request(self, payload, headers):
        return self._request("POST", "/supplemental-requests", payload, headers)

    def list_supplemental_requests(self, headers, params=None):
        return self._request("GET", "/supplemental-requests", headers=headers,
                             params=params)

    def get_supplemental_request(self, sr_id, headers):
        return self._request("GET", f"/supplemental-requests/{sr_id}", headers=headers)

    def transition_supplemental_request(self, sr_id, payload, headers):
        return self._request("POST", f"/supplemental-requests/{sr_id}/transitions",
                             payload, headers)

    # ------------------------------------------------------------------
    # Challenge cases and committee votes
    # ------------------------------------------------------------------
    def create_challenge(self, payload, headers):
        return self._request("POST", "/challenge-cases", payload, headers)

    def list_challenges(self, headers, params=None):
        return self._request("GET", "/challenge-cases", headers=headers, params=params)

    def get_challenge(self, challenge_id, headers):
        return self._request("GET", f"/challenge-cases/{challenge_id}", headers=headers)

    def transition_challenge(self, challenge_id, payload, headers):
        return self._request("POST", f"/challenge-cases/{challenge_id}/transitions",
                             payload, headers)

    def cast_vote(self, challenge_id, payload, headers):
        return self._request("POST", f"/challenge-cases/{challenge_id}/votes",
                             payload, headers)

    def list_votes(self, challenge_id, headers, params=None):
        return self._request("GET", f"/challenge-cases/{challenge_id}/votes",
                             headers=headers, params=params)


api_client = ApiClient()
# The per-test-server isolation restarts the API server before every test;
# "Connection: close" makes every request open a fresh connection to whichever
# server instance is currently bound to the port, so urllib3 never reuses a
# stale pooled socket across a restart (which surfaces as a flaky
# ConnectionError / RemoteDisconnected on the first request after a reboot).
api_client.session.headers["Connection"] = "close"
