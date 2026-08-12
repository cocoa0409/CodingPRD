"""API client: one method per endpoint defined in the PRD (§4 index)."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock (test-driving) ──────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Customers ─────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/coatings/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/coatings/customers/{customer_id}", headers=headers)

    # ─── Tint bases ────────────────────────────────────
    def create_tint_base(self, payload, headers):
        return self._request("POST", "/coatings/tint-bases", payload, headers)

    def get_tint_base(self, base_id, headers):
        return self._request("GET", f"/coatings/tint-bases/{base_id}", headers=headers)

    # ─── Colorants ─────────────────────────────────────
    def create_colorant(self, payload, headers):
        return self._request("POST", "/coatings/colorants", payload, headers)

    def get_colorant(self, colorant_id, headers):
        return self._request("GET", f"/coatings/colorants/{colorant_id}", headers=headers)

    def list_colorant_formula_lines(self, colorant_id, headers, params=None):
        return self._request(
            "GET", f"/coatings/colorants/{colorant_id}/formula-lines",
            headers=headers, params=params,
        )

    def list_colorant_batch_adjustments(self, colorant_id, headers, params=None):
        return self._request(
            "GET", f"/coatings/colorants/{colorant_id}/batch-adjustments",
            headers=headers, params=params,
        )

    # ─── Formulas ──────────────────────────────────────
    def create_formula(self, payload, headers):
        return self._request("POST", "/coatings/formulas", payload, headers)

    def get_formula(self, formula_id, headers):
        return self._request("GET", f"/coatings/formulas/{formula_id}", headers=headers)

    def list_formulas(self, headers, params=None):
        return self._request("GET", "/coatings/formulas", headers=headers, params=params)

    def list_formula_lines(self, formula_id, headers, params=None):
        return self._request(
            "GET", f"/coatings/formulas/{formula_id}/lines",
            headers=headers, params=params,
        )

    def supersede_formula(self, formula_id, payload, headers):
        return self._request(
            "POST", f"/coatings/formulas/{formula_id}/supersede", payload, headers
        )

    def activate_formula(self, formula_id, headers):
        return self._request(
            "POST", f"/coatings/formulas/{formula_id}/activate", {}, headers
        )

    def deprecate_formula(self, formula_id, headers):
        return self._request(
            "POST", f"/coatings/formulas/{formula_id}/deprecate", {}, headers
        )

    # ─── VOC rules ─────────────────────────────────────
    def create_voc_rule(self, payload, headers):
        return self._request("POST", "/coatings/voc-rules", payload, headers)

    def get_voc_rule(self, rule_id, headers):
        return self._request("GET", f"/coatings/voc-rules/{rule_id}", headers=headers)

    def list_voc_rules(self, headers, params=None):
        return self._request("GET", "/coatings/voc-rules", headers=headers, params=params)

    def activate_voc_rule(self, rule_id, headers):
        return self._request(
            "POST", f"/coatings/voc-rules/{rule_id}/activate", {}, headers
        )

    def retire_voc_rule(self, rule_id, headers):
        return self._request(
            "POST", f"/coatings/voc-rules/{rule_id}/retire", {}, headers
        )

    # ─── Mills ─────────────────────────────────────────
    def create_mill(self, payload, headers):
        return self._request("POST", "/coatings/mills", payload, headers)

    def get_mill(self, mill_id, headers):
        return self._request("GET", f"/coatings/mills/{mill_id}", headers=headers)

    def enter_mill_maintenance(self, mill_id, headers):
        return self._request(
            "POST", f"/coatings/mills/{mill_id}/enter-maintenance", {}, headers
        )

    def return_mill_to_service(self, mill_id, headers):
        return self._request(
            "POST", f"/coatings/mills/{mill_id}/return-to-service", {}, headers
        )

    def list_mill_batches(self, mill_id, headers, params=None):
        return self._request(
            "GET", f"/coatings/mills/{mill_id}/batches", headers=headers, params=params
        )

    # ─── Batches ───────────────────────────────────────
    def create_batch(self, payload, headers):
        return self._request("POST", "/coatings/batches", payload, headers)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/coatings/batches/{batch_id}", headers=headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/coatings/batches", headers=headers, params=params)

    def start_mill(self, batch_id, headers):
        return self._request(
            "POST", f"/coatings/batches/{batch_id}/start-mill", {}, headers
        )

    def dispersion_check(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/coatings/batches/{batch_id}/dispersion-check", payload, headers
        )

    def record_adjustment(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/coatings/batches/{batch_id}/adjustments", payload, headers
        )

    def list_adjustments(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"/coatings/batches/{batch_id}/adjustments",
            headers=headers, params=params,
        )

    def submit_qc(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/coatings/batches/{batch_id}/submit-qc", payload, headers
        )

    def rework_batch(self, batch_id, headers):
        return self._request("POST", f"/coatings/batches/{batch_id}/rework", {}, headers)

    def resume_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/coatings/batches/{batch_id}/resume", payload, headers
        )

    def record_fill(self, batch_id, payload, headers):
        return self._request("POST", f"/coatings/batches/{batch_id}/fills", payload, headers)

    def complete_filling(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/coatings/batches/{batch_id}/complete-filling", payload, headers
        )

    def close_batch(self, batch_id, headers):
        return self._request("POST", f"/coatings/batches/{batch_id}/close", {}, headers)

    def cancel_batch(self, batch_id, headers):
        return self._request("POST", f"/coatings/batches/{batch_id}/cancel", {}, headers)

    def dispose_batch(self, batch_id, headers):
        return self._request("POST", f"/coatings/batches/{batch_id}/dispose", {}, headers)

    # ─── Color matches ─────────────────────────────────
    def create_color_match(self, payload, headers):
        return self._request("POST", "/coatings/color-matches", payload, headers)

    def get_color_match(self, match_id, headers):
        return self._request(
            "GET", f"/coatings/color-matches/{match_id}", headers=headers
        )

    def list_color_matches(self, headers, params=None):
        return self._request(
            "GET", "/coatings/color-matches", headers=headers, params=params
        )

    def approve_color_match(self, match_id, headers):
        return self._request(
            "POST", f"/coatings/color-matches/{match_id}/approve", {}, headers
        )

    def reject_color_match(self, match_id, headers):
        return self._request(
            "POST", f"/coatings/color-matches/{match_id}/reject", {}, headers
        )

    # ─── Containers ────────────────────────────────────
    def get_container(self, container_id, headers):
        return self._request(
            "GET", f"/coatings/containers/{container_id}", headers=headers
        )

    def list_containers(self, headers, params=None):
        return self._request(
            "GET", "/coatings/containers", headers=headers, params=params
        )

    def reweigh_container(self, container_id, payload, headers):
        return self._request(
            "POST", f"/coatings/containers/{container_id}/reweigh", payload, headers
        )

    def ship_container(self, container_id, payload, headers):
        return self._request(
            "POST", f"/coatings/containers/{container_id}/ship", payload, headers
        )

    def mark_freeze_exposure(self, container_id, headers):
        return self._request(
            "POST", f"/coatings/containers/{container_id}/mark-freeze-exposure",
            {}, headers,
        )

    def customer_return(self, container_id, headers):
        return self._request(
            "POST", f"/coatings/containers/{container_id}/customer-return", {}, headers
        )

    # ─── Sales orders ──────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/coatings/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/coatings/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/coatings/orders", headers=headers, params=params)

    def rush_approve_order(self, order_id, headers):
        return self._request(
            "POST", f"/coatings/orders/{order_id}/rush-approve", {}, headers
        )

    def rush_reject_order(self, order_id, headers):
        return self._request(
            "POST", f"/coatings/orders/{order_id}/rush-reject", {}, headers
        )

    def schedule_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/coatings/orders/{order_id}/schedule", payload, headers
        )

    def cancel_order(self, order_id, headers):
        return self._request(
            "POST", f"/coatings/orders/{order_id}/cancel", {}, headers
        )

    # ─── Credit claims ─────────────────────────────────
    def create_credit_claim(self, payload, headers):
        return self._request("POST", "/coatings/credit-claims", payload, headers)

    def get_credit_claim(self, claim_id, headers):
        return self._request(
            "GET", f"/coatings/credit-claims/{claim_id}", headers=headers
        )

    def list_credit_claims(self, headers, params=None):
        return self._request(
            "GET", "/coatings/credit-claims", headers=headers, params=params
        )

    def review_credit_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/coatings/credit-claims/{claim_id}/review", {}, headers
        )

    def approve_credit_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/coatings/credit-claims/{claim_id}/approve", {}, headers
        )

    def reject_credit_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/coatings/credit-claims/{claim_id}/reject", {}, headers
        )

    def settle_credit_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/coatings/credit-claims/{claim_id}/settle", {}, headers
        )

    def void_credit_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/coatings/credit-claims/{claim_id}/void", {}, headers
        )

    # ─── Disposal requests ─────────────────────────────
    def create_disposal_request(self, payload, headers):
        return self._request("POST", "/coatings/disposal-requests", payload, headers)

    def get_disposal_request(self, request_id, headers):
        return self._request(
            "GET", f"/coatings/disposal-requests/{request_id}", headers=headers
        )

    def manifest_disposal_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/coatings/disposal-requests/{request_id}/manifest",
            payload, headers,
        )

    def complete_disposal_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/coatings/disposal-requests/{request_id}/complete",
            payload, headers,
        )

    def cancel_disposal_request(self, request_id, headers):
        return self._request(
            "POST", f"/coatings/disposal-requests/{request_id}/cancel", {}, headers
        )

    # ─── Operations ────────────────────────────────────
    def run_daily_sweep(self, headers):
        return self._request("POST", "/coatings/ops/run-daily-sweep", {}, headers)


api_client = ApiClient()
