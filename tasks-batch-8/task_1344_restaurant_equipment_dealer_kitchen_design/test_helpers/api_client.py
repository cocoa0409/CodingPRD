"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_clock(self, to_iso8601: str, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def suspend_customer(self, customer_id, headers):
        return self._request(
            "POST", f"/customers/{customer_id}/suspend", {}, headers
        )

    # --- Projects ---
    def create_project(self, payload, headers):
        return self._request("POST", "/design-build-projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request(
            "GET", "/design-build-projects", headers=headers, params=params
        )

    def get_project(self, project_id, headers):
        return self._request(
            "GET", f"/design-build-projects/{project_id}", headers=headers
        )

    def cancel_project(self, project_id, headers):
        return self._request(
            "POST", f"/design-build-projects/{project_id}/cancel", {}, headers
        )

    def close_punch_list(self, project_id, expected_project_version, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/close-punch-list",
            {"expected_project_version": expected_project_version},
            headers,
        )

    def complete_project(self, project_id, headers):
        return self._request(
            "POST", f"/design-build-projects/{project_id}/complete", {}, headers
        )

    # --- Kitchen layouts ---
    def create_layout(self, project_id, payload, headers):
        return self._request(
            "POST", f"/design-build-projects/{project_id}/layouts", payload, headers
        )

    def list_layouts(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/design-build-projects/{project_id}/layouts",
            headers=headers,
            params=params,
        )

    def get_layout(self, project_id, layout_id, headers):
        return self._request(
            "GET",
            f"/design-build-projects/{project_id}/layouts/{layout_id}",
            headers=headers,
        )

    def submit_layout(self, project_id, layout_id, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/layouts/{layout_id}/submit",
            {},
            headers,
        )

    def approve_layout(self, project_id, layout_id, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/layouts/{layout_id}/approve",
            {},
            headers,
        )

    def return_layout_for_revision(self, project_id, layout_id, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/layouts/{layout_id}/return-for-revision",
            {},
            headers,
        )

    # Top-level layout reads
    def get_layout_toplevel(self, layout_id, headers):
        return self._request("GET", f"/kitchen-layouts/{layout_id}", headers=headers)

    def list_layouts_toplevel(self, headers, params=None):
        return self._request("GET", "/kitchen-layouts", headers=headers, params=params)

    # --- Equipment items ---
    def create_equipment_item(self, project_id, layout_id, payload, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/layouts/{layout_id}/equipment-items",
            payload,
            headers,
        )

    def list_equipment_items_on_layout(self, project_id, layout_id, headers, params=None):
        return self._request(
            "GET",
            f"/design-build-projects/{project_id}/layouts/{layout_id}/equipment-items",
            headers=headers,
            params=params,
        )

    def list_equipment_items_on_project(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/design-build-projects/{project_id}/equipment-items",
            headers=headers,
            params=params,
        )

    def get_equipment_item(self, project_id, item_id, headers):
        return self._request(
            "GET",
            f"/design-build-projects/{project_id}/equipment-items/{item_id}",
            headers=headers,
        )

    def get_equipment_item_toplevel(self, item_id, headers):
        return self._request("GET", f"/equipment-items/{item_id}", headers=headers)

    def list_equipment_items_toplevel(self, headers, params=None):
        return self._request("GET", "/equipment-items", headers=headers, params=params)

    # --- Quotes ---
    def create_quote(self, project_id, layout_id, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/quotes",
            {"layout_id": layout_id},
            headers,
        )

    def list_quotes(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/design-build-projects/{project_id}/quotes",
            headers=headers,
            params=params,
        )

    def get_quote(self, project_id, quote_id, headers):
        return self._request(
            "GET",
            f"/design-build-projects/{project_id}/quotes/{quote_id}",
            headers=headers,
        )

    def present_quote(self, project_id, quote_id, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/quotes/{quote_id}/present",
            {},
            headers,
        )

    def accept_quote(self, project_id, quote_id, expected_project_version, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/quotes/{quote_id}/accept",
            {"expected_project_version": expected_project_version},
            headers,
        )

    def reject_quote(self, project_id, quote_id, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/quotes/{quote_id}/reject",
            {},
            headers,
        )

    def get_quote_toplevel(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def list_quotes_toplevel(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    # --- Fabrication orders ---
    def list_fabrication_orders(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/design-build-projects/{project_id}/fabrication-orders",
            headers=headers,
            params=params,
        )

    def get_fabrication_order(self, project_id, fab_id, headers):
        return self._request(
            "GET",
            f"/design-build-projects/{project_id}/fabrication-orders/{fab_id}",
            headers=headers,
        )

    def approve_shop_drawing(self, project_id, fab_id, headers, shop_drawing_ref=None):
        # PRD 3.4: shop_drawing_ref is "supplied through the approval flow",
        # so the approve call carries it in the request body.
        body = {}
        if shop_drawing_ref is not None:
            body["shop_drawing_ref"] = shop_drawing_ref
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/fabrication-orders/{fab_id}/approve-shop-drawing",
            body,
            headers,
        )

    def start_production(self, project_id, fab_id, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/fabrication-orders/{fab_id}/start-production",
            {},
            headers,
        )

    def complete_fabrication(self, project_id, fab_id, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/fabrication-orders/{fab_id}/complete",
            {},
            headers,
        )

    def get_fabrication_order_toplevel(self, fab_id, headers):
        return self._request("GET", f"/fabrication-orders/{fab_id}", headers=headers)

    def list_fabrication_orders_toplevel(self, headers, params=None):
        return self._request(
            "GET", "/fabrication-orders", headers=headers, params=params
        )

    # --- Permit filings ---
    def create_permit_filing(self, project_id, layout_id, authority, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/permit-filings",
            {"layout_id": layout_id, "authority": authority},
            headers,
        )

    def list_permit_filings(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/design-build-projects/{project_id}/permit-filings",
            headers=headers,
            params=params,
        )

    def get_permit_filing(self, project_id, filing_id, headers):
        return self._request(
            "GET",
            f"/design-build-projects/{project_id}/permit-filings/{filing_id}",
            headers=headers,
        )

    def submit_permit_filing(self, project_id, filing_id, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/permit-filings/{filing_id}/submit",
            {},
            headers,
        )

    def record_permit_decision(self, project_id, filing_id, decision, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/permit-filings/{filing_id}/record-decision",
            {"decision": decision},
            headers,
        )

    def resubmit_permit_filing(self, project_id, filing_id, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/permit-filings/{filing_id}/resubmit",
            {},
            headers,
        )

    def get_permit_filing_toplevel(self, filing_id, headers):
        return self._request("GET", f"/permit-filings/{filing_id}", headers=headers)

    def list_permit_filings_toplevel(self, headers, params=None):
        return self._request("GET", "/permit-filings", headers=headers, params=params)

    # --- Delivery jobs ---
    def create_delivery_job(self, project_id, payload, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/delivery-jobs",
            payload,
            headers,
        )

    def list_delivery_jobs(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/design-build-projects/{project_id}/delivery-jobs",
            headers=headers,
            params=params,
        )

    def get_delivery_job(self, project_id, job_id, headers):
        return self._request(
            "GET",
            f"/design-build-projects/{project_id}/delivery-jobs/{job_id}",
            headers=headers,
        )

    def dispatch_delivery_job(self, project_id, job_id, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/delivery-jobs/{job_id}/dispatch",
            {},
            headers,
        )

    def mark_site_complete(self, project_id, job_id, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/delivery-jobs/{job_id}/mark-site-complete",
            {},
            headers,
        )

    def cancel_delivery_job(self, project_id, job_id, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/delivery-jobs/{job_id}/cancel",
            {},
            headers,
        )

    def get_delivery_job_toplevel(self, job_id, headers):
        return self._request("GET", f"/delivery-jobs/{job_id}", headers=headers)

    def list_delivery_jobs_toplevel(self, headers, params=None):
        return self._request("GET", "/delivery-jobs", headers=headers, params=params)

    # --- Startup sessions ---
    def create_startup_session(self, project_id, payload, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/startup-sessions",
            payload,
            headers,
        )

    def list_startup_sessions(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/design-build-projects/{project_id}/startup-sessions",
            headers=headers,
            params=params,
        )

    def get_startup_session(self, project_id, session_id, headers):
        return self._request(
            "GET",
            f"/design-build-projects/{project_id}/startup-sessions/{session_id}",
            headers=headers,
        )

    def complete_startup_session(self, project_id, session_id, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/startup-sessions/{session_id}/complete",
            {},
            headers,
        )

    def void_startup_session(self, project_id, session_id, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/startup-sessions/{session_id}/void",
            {},
            headers,
        )

    def get_startup_session_toplevel(self, session_id, headers):
        return self._request("GET", f"/startup-sessions/{session_id}", headers=headers)

    def list_startup_sessions_toplevel(self, headers, params=None):
        return self._request(
            "GET", "/startup-sessions", headers=headers, params=params
        )

    # --- Service agencies ---
    def create_service_agency(self, payload, headers):
        return self._request("POST", "/service-agencies", payload, headers)

    def list_service_agencies(self, headers, params=None):
        return self._request("GET", "/service-agencies", headers=headers, params=params)

    def get_service_agency(self, agency_id, headers):
        return self._request("GET", f"/service-agencies/{agency_id}", headers=headers)

    # --- Service assignments ---
    def list_service_assignments(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/design-build-projects/{project_id}/service-assignments",
            headers=headers,
            params=params,
        )

    def get_service_assignment(self, project_id, assignment_id, headers):
        return self._request(
            "GET",
            f"/design-build-projects/{project_id}/service-assignments/{assignment_id}",
            headers=headers,
        )

    def close_service_assignment(self, project_id, assignment_id, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/service-assignments/{assignment_id}/close",
            {},
            headers,
        )

    def transfer_service_assignment(self, project_id, assignment_id, target_agency_id, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/service-assignments/{assignment_id}/transfer",
            {"target_agency_id": target_agency_id},
            headers,
        )

    def get_service_assignment_toplevel(self, assignment_id, headers):
        return self._request(
            "GET", f"/service-assignments/{assignment_id}", headers=headers
        )

    def list_service_assignments_toplevel(self, headers, params=None):
        return self._request(
            "GET", "/service-assignments", headers=headers, params=params
        )

    # --- Punch list items ---
    def create_punch_list_item(self, project_id, payload, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/punch-list-items",
            payload,
            headers,
        )

    def list_punch_list_items(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/design-build-projects/{project_id}/punch-list-items",
            headers=headers,
            params=params,
        )

    def get_punch_list_item(self, project_id, item_id, headers):
        return self._request(
            "GET",
            f"/design-build-projects/{project_id}/punch-list-items/{item_id}",
            headers=headers,
        )

    def verify_punch_list_item(self, project_id, item_id, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/punch-list-items/{item_id}/verify",
            {},
            headers,
        )

    def void_punch_list_item(self, project_id, item_id, headers):
        return self._request(
            "POST",
            f"/design-build-projects/{project_id}/punch-list-items/{item_id}/void",
            {},
            headers,
        )

    def get_punch_list_item_toplevel(self, item_id, headers):
        return self._request("GET", f"/punch-list-items/{item_id}", headers=headers)

    def list_punch_list_items_toplevel(self, headers, params=None):
        return self._request(
            "GET", "/punch-list-items", headers=headers, params=params
        )


api_client = ApiClient()
