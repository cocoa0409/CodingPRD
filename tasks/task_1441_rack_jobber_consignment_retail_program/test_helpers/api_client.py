"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Program ---
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def archive_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/archive",
                             headers=headers)

    # --- Store ---
    def create_store(self, payload, headers):
        return self._request("POST", "/stores", payload, headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", "/stores", headers=headers, params=params)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    def close_store(self, store_id, headers):
        return self._request("POST", f"/stores/{store_id}/close", headers=headers)

    # --- StoreAgreement ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/agreements/{agreement_id}", headers=headers)

    def patch_agreement(self, agreement_id, payload, headers):
        return self._request("PATCH", f"/agreements/{agreement_id}",
                             payload, headers)

    def submit_agreement(self, agreement_id, headers):
        return self._request("POST", f"/agreements/{agreement_id}/submit",
                             headers=headers)

    def accept_agreement(self, agreement_id, headers):
        return self._request("POST", f"/agreements/{agreement_id}/accept",
                             headers=headers)

    def reject_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/agreements/{agreement_id}/reject",
                             payload, headers)

    def suspend_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/agreements/{agreement_id}/suspend",
                             payload, headers)

    def resume_agreement(self, agreement_id, headers):
        return self._request("POST", f"/agreements/{agreement_id}/resume",
                             headers=headers)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/agreements/{agreement_id}/terminate",
                             headers=headers)

    # --- Product ---
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def patch_product(self, product_id, payload, headers):
        return self._request("PATCH", f"/products/{product_id}", payload, headers)

    # --- SpaceAllocation ---
    def create_space_allocation(self, payload, headers):
        return self._request("POST", "/space-allocations", payload, headers)

    def list_space_allocations(self, headers, params=None):
        return self._request("GET", "/space-allocations",
                             headers=headers, params=params)

    def get_space_allocation(self, allocation_id, headers):
        return self._request("GET", f"/space-allocations/{allocation_id}",
                             headers=headers)

    def close_space_allocation(self, allocation_id, headers):
        return self._request("POST", f"/space-allocations/{allocation_id}/close",
                             headers=headers)

    # --- PriceDirective ---
    def create_price_directive(self, payload, headers):
        return self._request("POST", "/price-directives", payload, headers)

    def list_price_directives(self, headers, params=None):
        return self._request("GET", "/price-directives",
                             headers=headers, params=params)

    def get_price_directive(self, directive_id, headers):
        return self._request("GET", f"/price-directives/{directive_id}",
                             headers=headers)

    # --- Promotion ---
    def create_promotion(self, payload, headers):
        return self._request("POST", "/promotions", payload, headers)

    def list_promotions(self, headers, params=None):
        return self._request("GET", "/promotions", headers=headers, params=params)

    def get_promotion(self, promotion_id, headers):
        return self._request("GET", f"/promotions/{promotion_id}", headers=headers)

    def schedule_promotion(self, promotion_id, headers):
        return self._request("POST", f"/promotions/{promotion_id}/schedule",
                             headers=headers)

    def suspend_promotion(self, promotion_id, headers):
        return self._request("POST", f"/promotions/{promotion_id}/suspend",
                             headers=headers)

    def resume_promotion(self, promotion_id, headers):
        return self._request("POST", f"/promotions/{promotion_id}/resume",
                             headers=headers)

    def cancel_promotion(self, promotion_id, headers):
        return self._request("POST", f"/promotions/{promotion_id}/cancel",
                             headers=headers)

    def end_promotion(self, promotion_id, headers):
        return self._request("POST", f"/promotions/{promotion_id}/end",
                             headers=headers)

    # --- InventoryBalance (read-only) ---
    def list_inventory_balances(self, headers, params=None):
        return self._request("GET", "/inventory-balances",
                             headers=headers, params=params)

    def get_inventory_balance(self, balance_id, headers):
        return self._request("GET", f"/inventory-balances/{balance_id}",
                             headers=headers)

    # --- Route ---
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/routes", headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def patch_route(self, route_id, payload, headers):
        return self._request("PATCH", f"/routes/{route_id}", payload, headers)

    # --- ServiceVisit ---
    def create_service_visit(self, payload, headers):
        return self._request("POST", "/service-visits", payload, headers)

    def list_service_visits(self, headers, params=None):
        return self._request("GET", "/service-visits",
                             headers=headers, params=params)

    def get_service_visit(self, visit_id, headers):
        return self._request("GET", f"/service-visits/{visit_id}",
                             headers=headers)

    def check_in_service_visit(self, visit_id, headers):
        return self._request("POST", f"/service-visits/{visit_id}/check-in",
                             headers=headers)

    def submit_visit_counts(self, visit_id, payload, headers):
        return self._request("POST", f"/service-visits/{visit_id}/submit-counts",
                             payload, headers)

    def confirm_service_visit(self, visit_id, headers):
        return self._request("POST", f"/service-visits/{visit_id}/confirm",
                             headers=headers)

    def dispute_service_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/service-visits/{visit_id}/dispute",
                             payload, headers)

    def recount_service_visit(self, visit_id, headers):
        return self._request("POST", f"/service-visits/{visit_id}/recount",
                             headers=headers)

    def cancel_service_visit(self, visit_id, headers):
        return self._request("POST", f"/service-visits/{visit_id}/cancel",
                             headers=headers)

    # --- ScanEvent (append-only) ---
    def create_scan_event(self, payload, headers):
        return self._request("POST", "/scan-events", payload, headers)

    def list_scan_events(self, headers, params=None):
        return self._request("GET", "/scan-events", headers=headers, params=params)

    def get_scan_event(self, scan_id, headers):
        return self._request("GET", f"/scan-events/{scan_id}", headers=headers)

    def resolve_scan_event(self, scan_id, headers):
        return self._request("POST", f"/scan-events/{scan_id}/resolve",
                             headers=headers)

    # --- AuditCount ---
    def create_audit_count(self, payload, headers):
        return self._request("POST", "/audit-counts", payload, headers)

    def list_audit_counts(self, headers, params=None):
        return self._request("GET", "/audit-counts", headers=headers, params=params)

    def get_audit_count(self, audit_id, headers):
        return self._request("GET", f"/audit-counts/{audit_id}", headers=headers)

    def start_audit_count(self, audit_id, headers):
        return self._request("POST", f"/audit-counts/{audit_id}/start",
                             headers=headers)

    def submit_audit_count(self, audit_id, payload, headers):
        return self._request("POST", f"/audit-counts/{audit_id}/submit",
                             payload, headers)

    def dispute_audit_count(self, audit_id, payload, headers):
        return self._request("POST", f"/audit-counts/{audit_id}/dispute",
                             payload, headers)

    def order_recount_audit_count(self, audit_id, headers):
        return self._request("POST", f"/audit-counts/{audit_id}/order-recount",
                             headers=headers)

    def certify_audit_count(self, audit_id, payload, headers):
        return self._request("POST", f"/audit-counts/{audit_id}/certify",
                             payload, headers)

    def lock_audit_count(self, audit_id, headers):
        return self._request("POST", f"/audit-counts/{audit_id}/lock",
                             headers=headers)

    # --- MarkdownAuthorization ---
    def create_markdown_authorization(self, payload, headers):
        return self._request("POST", "/markdown-authorizations", payload, headers)

    def list_markdown_authorizations(self, headers, params=None):
        return self._request("GET", "/markdown-authorizations",
                             headers=headers, params=params)

    def get_markdown_authorization(self, markdown_id, headers):
        return self._request("GET", f"/markdown-authorizations/{markdown_id}",
                             headers=headers)

    def approve_markdown_authorization(self, markdown_id, headers):
        return self._request("POST",
                             f"/markdown-authorizations/{markdown_id}/approve",
                             headers=headers)

    def reject_markdown_authorization(self, markdown_id, payload, headers):
        return self._request("POST",
                             f"/markdown-authorizations/{markdown_id}/reject",
                             payload, headers)

    def apply_markdown_authorization(self, markdown_id, headers):
        return self._request("POST",
                             f"/markdown-authorizations/{markdown_id}/apply",
                             headers=headers)

    # --- SettlementStatement ---
    def create_settlement_statement(self, payload, headers):
        return self._request("POST", "/settlement-statements", payload, headers)

    def list_settlement_statements(self, headers, params=None):
        return self._request("GET", "/settlement-statements",
                             headers=headers, params=params)

    def get_settlement_statement(self, statement_id, headers):
        return self._request("GET", f"/settlement-statements/{statement_id}",
                             headers=headers)

    def finalize_settlement_statement(self, statement_id, payload, headers):
        return self._request("POST",
                             f"/settlement-statements/{statement_id}/finalize",
                             payload, headers)

    def dispute_settlement_statement(self, statement_id, payload, headers):
        return self._request("POST",
                             f"/settlement-statements/{statement_id}/dispute",
                             payload, headers)

    def revise_settlement_statement(self, statement_id, headers):
        return self._request("POST",
                             f"/settlement-statements/{statement_id}/revise",
                             headers=headers)

    def approve_settlement_statement(self, statement_id, headers):
        return self._request("POST",
                             f"/settlement-statements/{statement_id}/approve",
                             headers=headers)

    def pay_settlement_statement(self, statement_id, headers):
        return self._request("POST",
                             f"/settlement-statements/{statement_id}/pay",
                             headers=headers)

    # --- SeasonalSet ---
    def create_seasonal_set(self, payload, headers):
        return self._request("POST", "/seasonal-sets", payload, headers)

    def list_seasonal_sets(self, headers, params=None):
        return self._request("GET", "/seasonal-sets", headers=headers, params=params)

    def get_seasonal_set(self, set_id, headers):
        return self._request("GET", f"/seasonal-sets/{set_id}", headers=headers)

    def begin_setup_seasonal_set(self, set_id, headers):
        return self._request("POST", f"/seasonal-sets/{set_id}/begin-setup",
                             headers=headers)

    def complete_setup_seasonal_set(self, set_id, headers):
        return self._request("POST", f"/seasonal-sets/{set_id}/complete-setup",
                             headers=headers)

    def activate_seasonal_set(self, set_id, headers):
        return self._request("POST", f"/seasonal-sets/{set_id}/activate",
                             headers=headers)

    def teardown_seasonal_set(self, set_id, headers):
        return self._request("POST", f"/seasonal-sets/{set_id}/teardown",
                             headers=headers)

    def reconcile_seasonal_set(self, set_id, headers):
        return self._request("POST", f"/seasonal-sets/{set_id}/reconcile",
                             headers=headers)


api_client = ApiClient()
