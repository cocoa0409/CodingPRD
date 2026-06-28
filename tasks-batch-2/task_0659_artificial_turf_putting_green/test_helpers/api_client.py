"""API client: one method per endpoint defined in the PRD (§4).

Subclasses the framework's GenericApiClient; only PRD-specific endpoint methods
are defined here. The base _request() handles envelope plumbing.

Routing note: per the PRD endpoint catalog, every resource that lives under a
project is addressed by a path that names the project first and the child
second (e.g. POST /projects/{project_id}/design-layouts). The payment, clock,
and settlement drivers are addressed flatly (/_payments/settle, /_payments/fail,
/_clock/set_current_utc).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock (driver) ──────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Customers ───────────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ─── Catalog: TurfProduct ────────────────────────────────────────────────
    def create_turf_product(self, payload, headers):
        return self._request("POST", "/turf-products", payload, headers)

    def list_turf_products(self, headers, params=None):
        return self._request("GET", "/turf-products", headers=headers, params=params)

    def get_turf_product(self, turf_product_id, headers):
        return self._request("GET", f"/turf-products/{turf_product_id}", headers=headers)

    # ─── Catalog: InfillProduct ──────────────────────────────────────────────
    def create_infill_product(self, payload, headers):
        return self._request("POST", "/infill-products", payload, headers)

    def list_infill_products(self, headers, params=None):
        return self._request("GET", "/infill-products", headers=headers, params=params)

    def get_infill_product(self, infill_product_id, headers):
        return self._request("GET", f"/infill-products/{infill_product_id}", headers=headers)

    # ─── Crews ───────────────────────────────────────────────────────────────
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    def list_crew_install_jobs(self, crew_id, headers, params=None):
        return self._request(
            "GET", f"/crews/{crew_id}/install-jobs", headers=headers, params=params
        )

    # ─── Projects ────────────────────────────────────────────────────────────
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def get_ledger(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/projects/{project_id}/ledger", headers=headers, params=params
        )

    def close_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/close", headers=headers)

    def cancel_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/cancel", headers=headers)

    # ─── Site Measures (under project) ───────────────────────────────────────
    def create_site_measure(self, project_id, payload, headers):
        return self._request(
            "POST", f"/projects/{project_id}/site-measures", payload, headers
        )

    def list_site_measures(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/projects/{project_id}/site-measures", headers=headers, params=params
        )

    # ─── Design Layouts (under project) ──────────────────────────────────────
    def create_design_layout(self, project_id, payload, headers):
        return self._request(
            "POST", f"/projects/{project_id}/design-layouts", payload, headers
        )

    def list_design_layouts(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/projects/{project_id}/design-layouts", headers=headers, params=params
        )

    def get_design_layout(self, project_id, design_layout_id, headers):
        return self._request(
            "GET", f"/projects/{project_id}/design-layouts/{design_layout_id}", headers=headers
        )

    def accept_design_layout(self, project_id, design_layout_id, headers):
        return self._request(
            "POST",
            f"/projects/{project_id}/design-layouts/{design_layout_id}/accept",
            headers=headers,
        )

    def reject_design_layout(self, project_id, design_layout_id, headers):
        return self._request(
            "POST",
            f"/projects/{project_id}/design-layouts/{design_layout_id}/reject",
            headers=headers,
        )

    # ─── Base Prep Scopes (under project) ────────────────────────────────────
    def create_base_prep_scope(self, project_id, payload, headers):
        return self._request(
            "POST", f"/projects/{project_id}/base-prep-scopes", payload, headers
        )

    def list_base_prep_scopes(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/projects/{project_id}/base-prep-scopes", headers=headers, params=params
        )

    def finalize_base_prep_scope(self, project_id, base_prep_scope_id, headers):
        return self._request(
            "POST",
            f"/projects/{project_id}/base-prep-scopes/{base_prep_scope_id}/finalize",
            headers=headers,
        )

    # ─── Quotes (under project) ──────────────────────────────────────────────
    def create_quote(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/quotes", payload, headers)

    def list_quotes(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/projects/{project_id}/quotes", headers=headers, params=params
        )

    def get_quote(self, project_id, quote_id, headers):
        return self._request(
            "GET", f"/projects/{project_id}/quotes/{quote_id}", headers=headers
        )

    def send_quote(self, project_id, quote_id, headers):
        return self._request(
            "POST", f"/projects/{project_id}/quotes/{quote_id}/send", headers=headers
        )

    def revise_quote(self, project_id, quote_id, payload, headers):
        return self._request(
            "POST", f"/projects/{project_id}/quotes/{quote_id}/revise", payload, headers
        )

    def accept_quote(self, project_id, quote_id, payload, headers):
        return self._request(
            "POST", f"/projects/{project_id}/quotes/{quote_id}/accept", payload, headers
        )

    # ─── Payments (under project) + drivers ──────────────────────────────────
    def create_payment(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/payments", payload, headers)

    def list_payments(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/projects/{project_id}/payments", headers=headers, params=params
        )

    def settle_payment(self, payload, headers):
        return self._request("POST", "/_payments/settle", payload, headers)

    def fail_payment(self, payload, headers):
        return self._request("POST", "/_payments/fail", payload, headers)

    # ─── Install Jobs (under project) ────────────────────────────────────────
    def create_install_job(self, project_id, payload, headers):
        return self._request(
            "POST", f"/projects/{project_id}/install-jobs", payload, headers
        )

    def list_install_jobs(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/projects/{project_id}/install-jobs", headers=headers, params=params
        )

    def start_install_job(self, project_id, install_job_id, headers):
        return self._request(
            "POST",
            f"/projects/{project_id}/install-jobs/{install_job_id}/start",
            headers=headers,
        )

    def complete_install_job(self, project_id, install_job_id, headers):
        return self._request(
            "POST",
            f"/projects/{project_id}/install-jobs/{install_job_id}/complete",
            headers=headers,
        )

    def abort_install_job(self, project_id, install_job_id, headers):
        return self._request(
            "POST",
            f"/projects/{project_id}/install-jobs/{install_job_id}/abort",
            headers=headers,
        )

    # ─── Warranty Plans (under project) ──────────────────────────────────────
    def create_warranty_plan(self, project_id, payload, headers):
        return self._request(
            "POST", f"/projects/{project_id}/warranty-plans", payload, headers
        )

    def list_warranty_plans(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/projects/{project_id}/warranty-plans", headers=headers, params=params
        )

    # ─── Callbacks (under project) ───────────────────────────────────────────
    def create_callback(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/callbacks", payload, headers)

    def list_callbacks(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/projects/{project_id}/callbacks", headers=headers, params=params
        )

    def start_callback(self, project_id, callback_id, headers):
        return self._request(
            "POST", f"/projects/{project_id}/callbacks/{callback_id}/start", headers=headers
        )

    def resolve_callback(self, project_id, callback_id, headers):
        return self._request(
            "POST", f"/projects/{project_id}/callbacks/{callback_id}/resolve", headers=headers
        )

    def cancel_callback(self, project_id, callback_id, headers):
        return self._request(
            "POST", f"/projects/{project_id}/callbacks/{callback_id}/cancel", headers=headers
        )


api_client = ApiClient()
