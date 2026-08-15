"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving clock ---
    def set_current_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/api/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    # --- Property ---
    def create_property(self, payload, headers):
        return self._request("POST", "/api/properties", payload, headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/api/properties", headers=headers, params=params)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/api/properties/{property_id}", headers=headers)

    # --- SiteAssessment ---
    def create_assessment(self, payload, headers):
        return self._request("POST", "/api/assessments", payload, headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/api/assessments", headers=headers, params=params)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/api/assessments/{assessment_id}", headers=headers)

    def submit_assessment(self, assessment_id, headers):
        return self._request(
            "POST", f"/api/assessments/{assessment_id}/submit", {}, headers
        )

    # --- Material ---
    def create_material(self, payload, headers):
        return self._request("POST", "/api/materials", payload, headers)

    def list_materials(self, headers, params=None):
        return self._request("GET", "/api/materials", headers=headers, params=params)

    def get_material(self, material_id, headers):
        return self._request("GET", f"/api/materials/{material_id}", headers=headers)

    # --- MaterialLot ---
    def create_material_lot(self, payload, headers):
        return self._request("POST", "/api/material-lots", payload, headers)

    def list_material_lots(self, headers, params=None):
        return self._request("GET", "/api/material-lots", headers=headers, params=params)

    def get_material_lot(self, lot_id, headers):
        return self._request("GET", f"/api/material-lots/{lot_id}", headers=headers)

    def quarantine_material_lot(self, lot_id, headers):
        return self._request(
            "POST", f"/api/material-lots/{lot_id}/quarantine", {}, headers
        )

    def record_waste(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/api/material-lots/{lot_id}/record-waste", payload, headers
        )

    # --- Crew ---
    def create_crew(self, payload, headers):
        return self._request("POST", "/api/crews", payload, headers)

    def list_crews(self, headers, params=None):
        return self._request("GET", "/api/crews", headers=headers, params=params)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/api/crews/{crew_id}", headers=headers)

    def get_crew_utilization(self, crew_id, month, headers):
        return self._request(
            "GET",
            f"/api/crews/{crew_id}/utilization",
            headers=headers,
            params={"month": month},
        )

    # --- RouteSheet ---
    def create_route_sheet(self, payload, headers):
        return self._request("POST", "/api/route-sheets", payload, headers)

    def list_route_sheets(self, headers, params=None):
        return self._request("GET", "/api/route-sheets", headers=headers, params=params)

    def get_route_sheet(self, route_sheet_id, headers):
        return self._request(
            "GET", f"/api/route-sheets/{route_sheet_id}", headers=headers
        )

    def publish_route_sheet(self, route_sheet_id, headers):
        return self._request(
            "POST", f"/api/route-sheets/{route_sheet_id}/publish", {}, headers
        )

    def cancel_route_sheet(self, route_sheet_id, headers):
        return self._request(
            "POST", f"/api/route-sheets/{route_sheet_id}/cancel", {}, headers
        )

    # --- Quote ---
    def create_quote(self, payload, headers):
        return self._request("POST", "/api/quotes", payload, headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/api/quotes", headers=headers, params=params)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/api/quotes/{quote_id}", headers=headers)

    def patch_quote(self, quote_id, payload, headers):
        return self._request("PATCH", f"/api/quotes/{quote_id}", payload, headers)

    def send_quote(self, quote_id, headers):
        return self._request("POST", f"/api/quotes/{quote_id}/send", {}, headers)

    def accept_quote(self, quote_id, headers):
        return self._request("POST", f"/api/quotes/{quote_id}/accept", {}, headers)

    def decline_quote(self, quote_id, headers):
        return self._request("POST", f"/api/quotes/{quote_id}/decline", {}, headers)

    def request_quote_revision(self, quote_id, headers):
        return self._request(
            "POST", f"/api/quotes/{quote_id}/request-revision", {}, headers
        )

    # --- WorkOrder ---
    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/api/work-orders", headers=headers, params=params)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/api/work-orders/{work_order_id}", headers=headers)

    def schedule_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/api/work-orders/{work_order_id}/schedule", payload, headers
        )

    def reschedule_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/api/work-orders/{work_order_id}/reschedule", payload, headers
        )

    def start_work_order(self, work_order_id, headers):
        return self._request(
            "POST", f"/api/work-orders/{work_order_id}/start", {}, headers
        )

    def finish_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST",
            f"/api/work-orders/{work_order_id}/finish-application",
            payload,
            headers,
        )

    def complete_work_order(self, work_order_id, headers):
        return self._request(
            "POST", f"/api/work-orders/{work_order_id}/complete", {}, headers
        )

    def cancel_work_order(self, work_order_id, headers):
        return self._request(
            "POST", f"/api/work-orders/{work_order_id}/cancel", {}, headers
        )

    # --- DisplacementPlan ---
    def list_displacement_plans(self, headers, params=None):
        return self._request(
            "GET", "/api/displacement-plans", headers=headers, params=params
        )

    def get_displacement_plan(self, plan_id, headers):
        return self._request(
            "GET", f"/api/displacement-plans/{plan_id}", headers=headers
        )

    def send_displacement_notice(self, plan_id, headers):
        return self._request(
            "POST", f"/api/displacement-plans/{plan_id}/send-notice", {}, headers
        )

    def confirm_displacement_cleared(self, plan_id, headers):
        return self._request(
            "POST", f"/api/displacement-plans/{plan_id}/confirm-cleared", {}, headers
        )

    # --- Striping (parallel dimension on WorkOrder) ---
    def plan_striping(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/api/work-orders/{work_order_id}/striping/plan", payload, headers
        )

    def approve_striping(self, work_order_id, headers):
        return self._request(
            "POST", f"/api/work-orders/{work_order_id}/striping/approve", {}, headers
        )

    def mark_striping_applied(self, work_order_id, headers):
        return self._request(
            "POST",
            f"/api/work-orders/{work_order_id}/striping/mark-applied",
            {},
            headers,
        )

    def verify_striping(self, work_order_id, headers):
        return self._request(
            "POST", f"/api/work-orders/{work_order_id}/striping/verify", {}, headers
        )

    # --- Invoice ---
    def list_invoices(self, headers, params=None):
        return self._request("GET", "/api/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/api/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/issue", {}, headers)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/pay", payload, headers)

    # --- Warranty ---
    def list_warranty_records(self, headers, params=None):
        return self._request(
            "GET", "/api/warranty-records", headers=headers, params=params
        )

    def get_warranty_record(self, record_id, headers):
        return self._request("GET", f"/api/warranty-records/{record_id}", headers=headers)

    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/api/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/api/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/api/warranty-claims/{claim_id}", headers=headers)

    def investigate_warranty_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/api/warranty-claims/{claim_id}/investigate", {}, headers
        )

    def approve_warranty_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/api/warranty-claims/{claim_id}/approve", {}, headers
        )

    def deny_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/api/warranty-claims/{claim_id}/deny", {}, headers)

    # --- Weather ---
    def create_weather_snapshot(self, payload, headers):
        return self._request("POST", "/api/weather-snapshots", payload, headers)

    def list_weather_snapshots(self, headers, params=None):
        return self._request(
            "GET", "/api/weather-snapshots", headers=headers, params=params
        )


api_client = ApiClient()
