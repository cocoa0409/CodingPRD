"""API client: one method per endpoint the PRD declares.

Every path is mounted under the ``/water-service`` prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/water-service"


class ApiClient(GenericApiClient):
    # --- 4.1 Logical clock ---------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", f"{BASE}/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", f"{BASE}/_clock", headers=headers)

    # --- 4.2 Accounts --------------------------------------------------------
    def create_account(self, payload, headers):
        return self._request("POST", f"{BASE}/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"{BASE}/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", f"{BASE}/accounts", headers=headers, params=params)

    def patch_account(self, account_id, payload, headers):
        return self._request("PATCH", f"{BASE}/accounts/{account_id}", payload, headers)

    def list_account_invoices(self, account_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/accounts/{account_id}/invoices", headers=headers, params=params
        )

    # --- 4.3 Properties ------------------------------------------------------
    def create_property(self, payload, headers):
        return self._request("POST", f"{BASE}/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"{BASE}/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", f"{BASE}/properties", headers=headers, params=params)

    def list_property_well_profiles(self, property_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/properties/{property_id}/well-profiles",
            headers=headers,
            params=params,
        )

    # --- 4.4 Well profiles ---------------------------------------------------
    def create_well_profile(self, payload, headers):
        return self._request("POST", f"{BASE}/well-profiles", payload, headers)

    def get_well_profile(self, well_profile_id, headers):
        return self._request(
            "GET", f"{BASE}/well-profiles/{well_profile_id}", headers=headers
        )

    def list_well_profiles(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/well-profiles", headers=headers, params=params
        )

    def replace_pressure_tank(self, well_profile_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/well-profiles/{well_profile_id}/pressure-tank-replacement",
            payload,
            headers,
        )

    def list_well_maintenance_plans(self, well_profile_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/well-profiles/{well_profile_id}/maintenance-plans",
            headers=headers,
            params=params,
        )

    def create_treatment_recommendation(self, well_profile_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/well-profiles/{well_profile_id}/treatment-recommendations",
            payload,
            headers,
        )

    # --- 4.5 Shared-well agreements -----------------------------------------
    def create_shared_well_agreement(self, payload, headers):
        return self._request("POST", f"{BASE}/shared-well-agreements", payload, headers)

    def get_shared_well_agreement(self, shared_well_agreement_id, headers):
        return self._request(
            "GET",
            f"{BASE}/shared-well-agreements/{shared_well_agreement_id}",
            headers=headers,
        )

    def list_shared_well_agreements(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/shared-well-agreements", headers=headers, params=params
        )

    def terminate_shared_well_agreement(self, shared_well_agreement_id, headers):
        return self._request(
            "POST",
            f"{BASE}/shared-well-agreements/{shared_well_agreement_id}/terminate",
            {},
            headers,
        )

    # --- 4.6 Technicians -----------------------------------------------------
    def create_technician(self, payload, headers):
        return self._request("POST", f"{BASE}/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request(
            "GET", f"{BASE}/technicians/{technician_id}", headers=headers
        )

    def list_technicians(self, headers, params=None):
        return self._request("GET", f"{BASE}/technicians", headers=headers, params=params)

    def patch_technician(self, technician_id, payload, headers):
        return self._request(
            "PATCH", f"{BASE}/technicians/{technician_id}", payload, headers
        )

    # --- 4.7 Part catalog ----------------------------------------------------
    def create_part_catalog_item(self, payload, headers):
        return self._request("POST", f"{BASE}/part-catalog-items", payload, headers)

    def get_part_catalog_item(self, part_catalog_item_id, headers):
        return self._request(
            "GET", f"{BASE}/part-catalog-items/{part_catalog_item_id}", headers=headers
        )

    def list_part_catalog_items(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/part-catalog-items", headers=headers, params=params
        )

    def patch_part_catalog_item(self, part_catalog_item_id, payload, headers):
        return self._request(
            "PATCH", f"{BASE}/part-catalog-items/{part_catalog_item_id}", payload, headers
        )

    # --- 4.8 Inspections -----------------------------------------------------
    def create_inspection(self, payload, headers):
        return self._request("POST", f"{BASE}/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"{BASE}/inspections/{inspection_id}", headers=headers
        )

    def list_inspections(self, headers, params=None):
        return self._request("GET", f"{BASE}/inspections", headers=headers, params=params)

    def start_inspection(self, inspection_id, headers):
        return self._request(
            "POST", f"{BASE}/inspections/{inspection_id}/start", {}, headers
        )

    def complete_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/inspections/{inspection_id}/complete", payload, headers
        )

    def cancel_inspection(self, inspection_id, headers):
        return self._request(
            "POST", f"{BASE}/inspections/{inspection_id}/cancel", {}, headers
        )

    # --- 4.9 Water tests -----------------------------------------------------
    def create_water_test(self, payload, headers):
        return self._request("POST", f"{BASE}/water-tests", payload, headers)

    def get_water_test(self, water_test_id, headers):
        return self._request(
            "GET", f"{BASE}/water-tests/{water_test_id}", headers=headers
        )

    def list_water_tests(self, headers, params=None):
        return self._request("GET", f"{BASE}/water-tests", headers=headers, params=params)

    def record_lab_result(self, water_test_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/water-tests/{water_test_id}/lab-result", payload, headers
        )

    def record_confirmatory_result(self, water_test_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/water-tests/{water_test_id}/confirmatory-result",
            payload,
            headers,
        )

    def lapse_retest_window(self, water_test_id, headers):
        return self._request(
            "POST", f"{BASE}/water-tests/{water_test_id}/lapse-retest-window", {}, headers
        )

    def list_water_test_recommendations(self, water_test_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/water-tests/{water_test_id}/treatment-recommendations",
            headers=headers,
            params=params,
        )

    # --- 4.10 Treatment recommendations -------------------------------------
    def get_treatment_recommendation(self, treatment_recommendation_id, headers):
        return self._request(
            "GET",
            f"{BASE}/treatment-recommendations/{treatment_recommendation_id}",
            headers=headers,
        )

    def list_treatment_recommendations(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/treatment-recommendations", headers=headers, params=params
        )

    def accept_treatment_recommendation(self, treatment_recommendation_id, headers):
        return self._request(
            "POST",
            f"{BASE}/treatment-recommendations/{treatment_recommendation_id}/accept",
            {},
            headers,
        )

    # --- 4.11 Quotes ---------------------------------------------------------
    def create_quote(self, payload, headers):
        return self._request("POST", f"{BASE}/quotes", payload, headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"{BASE}/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", f"{BASE}/quotes", headers=headers, params=params)

    def add_quote_line(self, quote_id, payload, headers):
        return self._request("POST", f"{BASE}/quotes/{quote_id}/lines", payload, headers)

    def list_quote_lines_of(self, quote_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/quotes/{quote_id}/lines", headers=headers, params=params
        )

    def price_quote(self, quote_id, headers):
        return self._request("POST", f"{BASE}/quotes/{quote_id}/price", {}, headers)

    def send_quote(self, quote_id, headers):
        return self._request("POST", f"{BASE}/quotes/{quote_id}/send", {}, headers)

    def approve_quote(self, quote_id, headers):
        return self._request("POST", f"{BASE}/quotes/{quote_id}/approve", {}, headers)

    def decline_quote(self, quote_id, headers):
        return self._request("POST", f"{BASE}/quotes/{quote_id}/decline", {}, headers)

    def expire_quote(self, quote_id, headers):
        return self._request("POST", f"{BASE}/quotes/{quote_id}/expire", {}, headers)

    # --- 4.12 Quote lines ----------------------------------------------------
    def get_quote_line(self, quote_line_id, headers):
        return self._request(
            "GET", f"{BASE}/quote-lines/{quote_line_id}", headers=headers
        )

    def list_quote_lines(self, headers, params=None):
        return self._request("GET", f"{BASE}/quote-lines", headers=headers, params=params)

    def delete_quote_line(self, quote_line_id, headers):
        return self._request(
            "DELETE", f"{BASE}/quote-lines/{quote_line_id}", headers=headers
        )

    # --- 4.13 Emergency tickets ---------------------------------------------
    def create_emergency_ticket(self, payload, headers):
        return self._request("POST", f"{BASE}/emergency-tickets", payload, headers)

    def get_emergency_ticket(self, emergency_ticket_id, headers):
        return self._request(
            "GET", f"{BASE}/emergency-tickets/{emergency_ticket_id}", headers=headers
        )

    def list_emergency_tickets(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/emergency-tickets", headers=headers, params=params
        )

    def triage_ticket(self, emergency_ticket_id, headers):
        return self._request(
            "POST", f"{BASE}/emergency-tickets/{emergency_ticket_id}/triage", {}, headers
        )

    def dispatch_ticket(self, emergency_ticket_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/emergency-tickets/{emergency_ticket_id}/dispatch",
            payload,
            headers,
        )

    def arrive_ticket(self, emergency_ticket_id, headers):
        return self._request(
            "POST", f"{BASE}/emergency-tickets/{emergency_ticket_id}/arrive", {}, headers
        )

    def diagnose_ticket(self, emergency_ticket_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/emergency-tickets/{emergency_ticket_id}/diagnosis",
            payload,
            headers,
        )

    def authorize_ticket(self, emergency_ticket_id, headers):
        return self._request(
            "POST",
            f"{BASE}/emergency-tickets/{emergency_ticket_id}/authorize",
            {},
            headers,
        )

    def decline_ticket_authorization(self, emergency_ticket_id, headers):
        return self._request(
            "POST",
            f"{BASE}/emergency-tickets/{emergency_ticket_id}/decline-authorization",
            {},
            headers,
        )

    def cancel_ticket(self, emergency_ticket_id, headers):
        return self._request(
            "POST", f"{BASE}/emergency-tickets/{emergency_ticket_id}/cancel", {}, headers
        )

    def list_ticket_work_orders(self, emergency_ticket_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/emergency-tickets/{emergency_ticket_id}/work-orders",
            headers=headers,
            params=params,
        )

    # --- 4.14 Work orders ----------------------------------------------------
    def create_work_order(self, payload, headers):
        return self._request("POST", f"{BASE}/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request(
            "GET", f"{BASE}/work-orders/{work_order_id}", headers=headers
        )

    def list_work_orders(self, headers, params=None):
        return self._request("GET", f"{BASE}/work-orders", headers=headers, params=params)

    def schedule_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/work-orders/{work_order_id}/schedule", payload, headers
        )

    def start_work_order(self, work_order_id, headers):
        return self._request(
            "POST", f"{BASE}/work-orders/{work_order_id}/start", {}, headers
        )

    def post_parts_consumption(self, work_order_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/work-orders/{work_order_id}/parts-consumption",
            payload,
            headers,
        )

    def list_work_order_parts_consumption(self, work_order_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/work-orders/{work_order_id}/parts-consumption",
            headers=headers,
            params=params,
        )

    def complete_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/work-orders/{work_order_id}/complete", payload, headers
        )

    def cancel_work_order(self, work_order_id, headers):
        return self._request(
            "POST", f"{BASE}/work-orders/{work_order_id}/cancel", {}, headers
        )

    def write_off_work_order(self, work_order_id, headers):
        return self._request(
            "POST", f"{BASE}/work-orders/{work_order_id}/write-off", {}, headers
        )

    def list_work_order_warranty_coverages(self, work_order_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/work-orders/{work_order_id}/warranty-coverages",
            headers=headers,
            params=params,
        )

    def create_callback_claim(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/work-orders/{work_order_id}/callback-claims", payload, headers
        )

    def list_work_order_callback_claims(self, work_order_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/work-orders/{work_order_id}/callback-claims",
            headers=headers,
            params=params,
        )

    def list_work_order_invoices(self, work_order_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/work-orders/{work_order_id}/invoices",
            headers=headers,
            params=params,
        )

    def list_work_order_maintenance_visits(self, work_order_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/work-orders/{work_order_id}/maintenance-visits",
            headers=headers,
            params=params,
        )

    # --- 4.15 Parts consumption entries --------------------------------------
    def get_parts_consumption_entry(self, parts_consumption_entry_id, headers):
        return self._request(
            "GET",
            f"{BASE}/parts-consumption-entries/{parts_consumption_entry_id}",
            headers=headers,
        )

    def list_parts_consumption_entries(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/parts-consumption-entries", headers=headers, params=params
        )

    # --- 4.16 Warranty coverages ---------------------------------------------
    def get_warranty_coverage(self, warranty_coverage_id, headers):
        return self._request(
            "GET", f"{BASE}/warranty-coverages/{warranty_coverage_id}", headers=headers
        )

    def list_warranty_coverages(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/warranty-coverages", headers=headers, params=params
        )

    def void_warranty_coverage(self, warranty_coverage_id, headers):
        return self._request(
            "POST", f"{BASE}/warranty-coverages/{warranty_coverage_id}/void", {}, headers
        )

    # --- 4.17 Callback claims -------------------------------------------------
    def get_callback_claim(self, callback_claim_id, headers):
        return self._request(
            "GET", f"{BASE}/callback-claims/{callback_claim_id}", headers=headers
        )

    def list_callback_claims(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/callback-claims", headers=headers, params=params
        )

    def adjudicate_callback_claim(self, callback_claim_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/callback-claims/{callback_claim_id}/adjudicate",
            payload,
            headers,
        )

    def create_remedy_work_order(self, callback_claim_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/callback-claims/{callback_claim_id}/remedy-work-order",
            payload,
            headers,
        )

    # --- 4.18 Permits ---------------------------------------------------------
    def create_permit(self, payload, headers):
        return self._request("POST", f"{BASE}/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"{BASE}/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", f"{BASE}/permits", headers=headers, params=params)

    def file_permit(self, permit_id, headers):
        return self._request("POST", f"{BASE}/permits/{permit_id}/file", {}, headers)

    def approve_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/permits/{permit_id}/approve", payload, headers
        )

    def reject_permit(self, permit_id, headers):
        return self._request("POST", f"{BASE}/permits/{permit_id}/reject", {}, headers)

    def refile_permit_draft(self, permit_id, headers):
        return self._request(
            "POST", f"{BASE}/permits/{permit_id}/refile-draft", {}, headers
        )

    def withdraw_permit(self, permit_id, headers):
        return self._request("POST", f"{BASE}/permits/{permit_id}/withdraw", {}, headers)

    # --- 4.19 Maintenance plans ----------------------------------------------
    def create_maintenance_plan(self, payload, headers):
        return self._request("POST", f"{BASE}/maintenance-plans", payload, headers)

    def get_maintenance_plan(self, maintenance_plan_id, headers):
        return self._request(
            "GET", f"{BASE}/maintenance-plans/{maintenance_plan_id}", headers=headers
        )

    def list_maintenance_plans(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/maintenance-plans", headers=headers, params=params
        )

    def record_salt_delivery(self, maintenance_plan_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/maintenance-plans/{maintenance_plan_id}/salt-deliveries",
            payload,
            headers,
        )

    def record_filter_change(self, maintenance_plan_id, headers):
        return self._request(
            "POST",
            f"{BASE}/maintenance-plans/{maintenance_plan_id}/filter-change",
            {},
            headers,
        )

    def evaluate_plan_compliance(self, maintenance_plan_id, headers):
        return self._request(
            "POST",
            f"{BASE}/maintenance-plans/{maintenance_plan_id}/evaluate-compliance",
            {},
            headers,
        )

    def suspend_maintenance_plan(self, maintenance_plan_id, headers):
        return self._request(
            "POST",
            f"{BASE}/maintenance-plans/{maintenance_plan_id}/suspend",
            {},
            headers,
        )

    def resume_maintenance_plan(self, maintenance_plan_id, headers):
        return self._request(
            "POST", f"{BASE}/maintenance-plans/{maintenance_plan_id}/resume", {}, headers
        )

    def terminate_maintenance_plan(self, maintenance_plan_id, headers):
        return self._request(
            "POST",
            f"{BASE}/maintenance-plans/{maintenance_plan_id}/terminate",
            {},
            headers,
        )

    def list_plan_visits(self, maintenance_plan_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/maintenance-plans/{maintenance_plan_id}/visits",
            headers=headers,
            params=params,
        )

    # --- 4.20 Maintenance visits ---------------------------------------------
    def get_maintenance_visit(self, maintenance_visit_id, headers):
        return self._request(
            "GET", f"{BASE}/maintenance-visits/{maintenance_visit_id}", headers=headers
        )

    def list_maintenance_visits(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/maintenance-visits", headers=headers, params=params
        )

    # --- 4.21 Invoices --------------------------------------------------------
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"{BASE}/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", f"{BASE}/invoices", headers=headers, params=params)

    def list_invoice_lines_of(self, invoice_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/invoices/{invoice_id}/lines", headers=headers, params=params
        )

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"{BASE}/invoices/{invoice_id}/issue", {}, headers)

    def record_payment(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/invoices/{invoice_id}/payments", payload, headers
        )

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"{BASE}/invoices/{invoice_id}/void", {}, headers)

    # --- 4.22 Invoice lines ---------------------------------------------------
    def get_invoice_line(self, invoice_line_id, headers):
        return self._request(
            "GET", f"{BASE}/invoice-lines/{invoice_line_id}", headers=headers
        )

    def list_invoice_lines(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/invoice-lines", headers=headers, params=params
        )


api_client = ApiClient()
