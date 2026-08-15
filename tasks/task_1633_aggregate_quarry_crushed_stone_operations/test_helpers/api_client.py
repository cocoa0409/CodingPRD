"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving capability, QuarryAdmin only)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Quarry sites
    # ------------------------------------------------------------------
    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/sites", headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    def recompute_posture(self, site_id, headers):
        return self._request("POST", f"/sites/{site_id}/recompute-posture",
                             {}, headers)

    # ------------------------------------------------------------------
    # Benches
    # ------------------------------------------------------------------
    def create_bench(self, payload, headers):
        return self._request("POST", "/benches", payload, headers)

    def list_benches(self, headers, params=None):
        return self._request("GET", "/benches", headers=headers, params=params)

    def get_bench(self, bench_id, headers):
        return self._request("GET", f"/benches/{bench_id}", headers=headers)

    def release_bench(self, bench_id, headers):
        return self._request("POST", f"/benches/{bench_id}/release", {}, headers)

    def hold_bench(self, bench_id, payload, headers):
        return self._request("POST", f"/benches/{bench_id}/hold", payload, headers)

    def resume_bench(self, bench_id, headers):
        return self._request("POST", f"/benches/{bench_id}/resume", {}, headers)

    def mark_bench_mined_out(self, bench_id, headers):
        return self._request("POST", f"/benches/{bench_id}/mark-mined-out",
                             {}, headers)

    def start_reclamation(self, bench_id, headers):
        return self._request("POST", f"/benches/{bench_id}/start-reclamation",
                             {}, headers)

    def complete_reclamation(self, bench_id, headers):
        return self._request("POST", f"/benches/{bench_id}/complete-reclamation",
                             {}, headers)

    # ------------------------------------------------------------------
    # Shot plans
    # ------------------------------------------------------------------
    def create_shot_plan(self, payload, headers):
        return self._request("POST", "/shot-plans", payload, headers)

    def list_shot_plans(self, headers, params=None):
        return self._request("GET", "/shot-plans", headers=headers, params=params)

    def get_shot_plan(self, plan_id, headers):
        return self._request("GET", f"/shot-plans/{plan_id}", headers=headers)

    def submit_shot_plan(self, plan_id, headers):
        return self._request("POST", f"/shot-plans/{plan_id}/submit", {}, headers)

    def approve_shot_plan(self, plan_id, headers):
        return self._request("POST", f"/shot-plans/{plan_id}/approve", {}, headers)

    def start_drilling(self, plan_id, headers):
        return self._request("POST", f"/shot-plans/{plan_id}/start-drilling",
                             {}, headers)

    def complete_drilling(self, plan_id, payload, headers):
        return self._request("POST", f"/shot-plans/{plan_id}/complete-drilling",
                             payload, headers)

    def redrill_shot_plan(self, plan_id, headers):
        return self._request("POST", f"/shot-plans/{plan_id}/redrill", {}, headers)

    def load_shot_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/shot-plans/{plan_id}/load", payload, headers)

    def fire_shot_plan(self, plan_id, headers):
        return self._request("POST", f"/shot-plans/{plan_id}/fire", {}, headers)

    def cancel_shot_plan(self, plan_id, headers):
        return self._request("POST", f"/shot-plans/{plan_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Muckpiles
    # ------------------------------------------------------------------
    def list_muckpiles(self, headers, params=None):
        return self._request("GET", "/muckpiles", headers=headers, params=params)

    def get_muckpile(self, muckpile_id, headers):
        return self._request("GET", f"/muckpiles/{muckpile_id}", headers=headers)

    # ------------------------------------------------------------------
    # Product specs
    # ------------------------------------------------------------------
    def create_product_spec(self, payload, headers):
        return self._request("POST", "/product-specs", payload, headers)

    def list_product_specs(self, headers, params=None):
        return self._request("GET", "/product-specs", headers=headers,
                             params=params)

    def get_product_spec(self, spec_id, headers):
        return self._request("GET", f"/product-specs/{spec_id}", headers=headers)

    def retire_product_spec(self, spec_id, headers):
        return self._request("POST", f"/product-specs/{spec_id}/retire",
                             {}, headers)

    # ------------------------------------------------------------------
    # Stockpiles
    # ------------------------------------------------------------------
    def create_stockpile(self, payload, headers):
        return self._request("POST", "/stockpiles", payload, headers)

    def list_stockpiles(self, headers, params=None):
        return self._request("GET", "/stockpiles", headers=headers, params=params)

    def get_stockpile(self, stockpile_id, headers):
        return self._request("GET", f"/stockpiles/{stockpile_id}",
                             headers=headers)

    def adjust_stockpile(self, stockpile_id, payload, headers):
        return self._request("POST", f"/stockpiles/{stockpile_id}/adjustments",
                             payload, headers)

    def close_stockpile(self, stockpile_id, headers):
        return self._request("POST", f"/stockpiles/{stockpile_id}/close",
                             {}, headers)

    # ------------------------------------------------------------------
    # Gradation tests
    # ------------------------------------------------------------------
    def create_gradation_test(self, payload, headers):
        return self._request("POST", "/gradation-tests", payload, headers)

    def list_gradation_tests(self, headers, params=None):
        return self._request("GET", "/gradation-tests", headers=headers,
                             params=params)

    def get_gradation_test(self, test_id, headers):
        return self._request("GET", f"/gradation-tests/{test_id}",
                             headers=headers)

    def confirm_gradation_test(self, test_id, headers):
        return self._request("POST", f"/gradation-tests/{test_id}/confirm",
                             {}, headers)

    def void_gradation_test(self, test_id, headers):
        return self._request("POST", f"/gradation-tests/{test_id}/void",
                             {}, headers)

    # ------------------------------------------------------------------
    # Scales and calibrations
    # ------------------------------------------------------------------
    def create_scale(self, payload, headers):
        return self._request("POST", "/scales", payload, headers)

    def list_scales(self, headers, params=None):
        return self._request("GET", "/scales", headers=headers, params=params)

    def get_scale(self, scale_id, headers):
        return self._request("GET", f"/scales/{scale_id}", headers=headers)

    def create_scale_calibration(self, payload, headers):
        return self._request("POST", "/scale-calibrations", payload, headers)

    def list_scale_calibrations(self, headers, params=None):
        return self._request("GET", "/scale-calibrations", headers=headers,
                             params=params)

    def get_scale_calibration(self, calibration_id, headers):
        return self._request("GET", f"/scale-calibrations/{calibration_id}",
                             headers=headers)

    def void_scale_calibration(self, calibration_id, headers):
        return self._request("POST", f"/scale-calibrations/{calibration_id}/void",
                             {}, headers)

    # ------------------------------------------------------------------
    # Plant runs
    # ------------------------------------------------------------------
    def create_plant_run(self, payload, headers):
        return self._request("POST", "/plant-runs", payload, headers)

    def list_plant_runs(self, headers, params=None):
        return self._request("GET", "/plant-runs", headers=headers, params=params)

    def get_plant_run(self, run_id, headers):
        return self._request("GET", f"/plant-runs/{run_id}", headers=headers)

    def start_plant_run(self, run_id, headers):
        return self._request("POST", f"/plant-runs/{run_id}/start", {}, headers)

    def complete_plant_run(self, run_id, payload, headers):
        return self._request("POST", f"/plant-runs/{run_id}/complete",
                             payload, headers)

    def reconcile_plant_run(self, run_id, payload, headers):
        return self._request("POST", f"/plant-runs/{run_id}/reconcile",
                             payload, headers)

    def void_plant_run(self, run_id, headers):
        return self._request("POST", f"/plant-runs/{run_id}/void", {}, headers)

    def cancel_plant_run(self, run_id, headers):
        return self._request("POST", f"/plant-runs/{run_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Freight zones
    # ------------------------------------------------------------------
    def create_freight_zone(self, payload, headers):
        return self._request("POST", "/freight-zones", payload, headers)

    def list_freight_zones(self, headers, params=None):
        return self._request("GET", "/freight-zones", headers=headers,
                             params=params)

    def get_freight_zone(self, zone_id, headers):
        return self._request("GET", f"/freight-zones/{zone_id}", headers=headers)

    def deactivate_freight_zone(self, zone_id, headers):
        return self._request("POST", f"/freight-zones/{zone_id}/deactivate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Sales orders
    # ------------------------------------------------------------------
    def create_sales_order(self, payload, headers):
        return self._request("POST", "/sales-orders", payload, headers)

    def list_sales_orders(self, headers, params=None):
        return self._request("GET", "/sales-orders", headers=headers,
                             params=params)

    def get_sales_order(self, order_id, headers):
        return self._request("GET", f"/sales-orders/{order_id}", headers=headers)

    def confirm_sales_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/confirm",
                             {}, headers)

    def cancel_sales_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/cancel",
                             {}, headers)

    def reprice_sales_order(self, order_id, payload, headers):
        return self._request("POST", f"/sales-orders/{order_id}/reprice",
                             payload, headers)

    # ------------------------------------------------------------------
    # Scale tickets
    # ------------------------------------------------------------------
    def create_scale_ticket(self, payload, headers):
        return self._request("POST", "/scale-tickets", payload, headers)

    def list_scale_tickets(self, headers, params=None):
        return self._request("GET", "/scale-tickets", headers=headers,
                             params=params)

    def get_scale_ticket(self, ticket_id, headers):
        return self._request("GET", f"/scale-tickets/{ticket_id}",
                             headers=headers)

    def weigh_out_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/scale-tickets/{ticket_id}/weigh-out",
                             payload, headers)

    def void_scale_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/scale-tickets/{ticket_id}/void",
                             payload, headers)

    # ------------------------------------------------------------------
    # Royalty agreements
    # ------------------------------------------------------------------
    def create_royalty_agreement(self, payload, headers):
        return self._request("POST", "/royalty-agreements", payload, headers)

    def list_royalty_agreements(self, headers, params=None):
        return self._request("GET", "/royalty-agreements", headers=headers,
                             params=params)

    def get_royalty_agreement(self, agreement_id, headers):
        return self._request("GET", f"/royalty-agreements/{agreement_id}",
                             headers=headers)

    def amend_royalty_agreement(self, agreement_id, payload, headers):
        return self._request("POST",
                             f"/royalty-agreements/{agreement_id}/amendments",
                             payload, headers)

    def terminate_royalty_agreement(self, agreement_id, headers):
        return self._request("POST",
                             f"/royalty-agreements/{agreement_id}/terminate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Royalty statements
    # ------------------------------------------------------------------
    def create_royalty_statement(self, payload, headers):
        return self._request("POST", "/royalty-statements", payload, headers)

    def list_royalty_statements(self, headers, params=None):
        return self._request("GET", "/royalty-statements", headers=headers,
                             params=params)

    def get_royalty_statement(self, statement_id, headers):
        return self._request("GET", f"/royalty-statements/{statement_id}",
                             headers=headers)

    def issue_royalty_statement(self, statement_id, headers):
        return self._request("POST", f"/royalty-statements/{statement_id}/issue",
                             {}, headers)

    def pay_royalty_statement(self, statement_id, payload, headers):
        return self._request("POST", f"/royalty-statements/{statement_id}/pay",
                             payload, headers)

    def void_royalty_statement(self, statement_id, headers):
        return self._request("POST", f"/royalty-statements/{statement_id}/void",
                             {}, headers)

    # ------------------------------------------------------------------
    # MSHA inspections and citations
    # ------------------------------------------------------------------
    def create_msha_inspection(self, payload, headers):
        return self._request("POST", "/msha-inspections", payload, headers)

    def list_msha_inspections(self, headers, params=None):
        return self._request("GET", "/msha-inspections", headers=headers,
                             params=params)

    def get_msha_inspection(self, inspection_id, headers):
        return self._request("GET", f"/msha-inspections/{inspection_id}",
                             headers=headers)

    def close_msha_inspection(self, inspection_id, headers):
        return self._request("POST", f"/msha-inspections/{inspection_id}/close",
                             {}, headers)

    def create_msha_citation(self, payload, headers):
        return self._request("POST", "/msha-citations", payload, headers)

    def list_msha_citations(self, headers, params=None):
        return self._request("GET", "/msha-citations", headers=headers,
                             params=params)

    def get_msha_citation(self, citation_id, headers):
        return self._request("GET", f"/msha-citations/{citation_id}",
                             headers=headers)

    def abate_msha_citation(self, citation_id, payload, headers):
        return self._request("POST", f"/msha-citations/{citation_id}/abate",
                             payload, headers)

    def vacate_msha_citation(self, citation_id, headers):
        return self._request("POST", f"/msha-citations/{citation_id}/vacate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Training records
    # ------------------------------------------------------------------
    def create_training_record(self, payload, headers):
        return self._request("POST", "/training-records", payload, headers)

    def list_training_records(self, headers, params=None):
        return self._request("GET", "/training-records", headers=headers,
                             params=params)

    def get_training_record(self, record_id, headers):
        return self._request("GET", f"/training-records/{record_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Reclamation bonds
    # ------------------------------------------------------------------
    def create_reclamation_bond(self, payload, headers):
        return self._request("POST", "/reclamation-bonds", payload, headers)

    def list_reclamation_bonds(self, headers, params=None):
        return self._request("GET", "/reclamation-bonds", headers=headers,
                             params=params)

    def get_reclamation_bond(self, bond_id, headers):
        return self._request("GET", f"/reclamation-bonds/{bond_id}",
                             headers=headers)

    def release_reclamation_bond(self, bond_id, payload, headers):
        return self._request("POST", f"/reclamation-bonds/{bond_id}/release",
                             payload, headers)

    # ------------------------------------------------------------------
    # Truck queue entries
    # ------------------------------------------------------------------
    def create_queue_entry(self, payload, headers):
        return self._request("POST", "/queue-entries", payload, headers)

    def list_queue_entries(self, headers, params=None):
        return self._request("GET", "/queue-entries", headers=headers,
                             params=params)

    def get_queue_entry(self, entry_id, headers):
        return self._request("GET", f"/queue-entries/{entry_id}",
                             headers=headers)

    def call_next_queue_entry(self, payload, headers):
        return self._request("POST", "/queue-entries/call-next", payload,
                             headers)

    def begin_scale_out(self, entry_id, headers):
        return self._request("POST", f"/queue-entries/{entry_id}/begin-scale-out",
                             {}, headers)

    def mark_no_show(self, entry_id, headers):
        return self._request("POST", f"/queue-entries/{entry_id}/mark-no-show",
                             {}, headers)


api_client = ApiClient()
