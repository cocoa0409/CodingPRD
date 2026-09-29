"""API client: one method per endpoint defined in the PRD.

Every collection sits directly beneath the ``/tooling`` prefix and a path
carries at most one identifier.
"""

import requests

from prd_bench_local_runner.testing import GenericApiClient

API_PREFIX = "/tooling"


class ApiClient(GenericApiClient):
    """Typed endpoint surface for the Cutting Tool & Carbide Insert API."""

    # ── The logical shop clock ──────────────────────────────────────────
    def set_current_utc(self, current_utc, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )

    def set_current_utc_raw(self, payload, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers
        )

    # ── Carbide grades ──────────────────────────────────────────────────
    def create_carbide_grade(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/carbide-grades", payload, headers)

    def get_carbide_grade(self, grade_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/carbide-grades/{grade_id}", headers=headers
        )

    def list_carbide_grades(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/carbide-grades", headers=headers, params=params
        )

    def start_grade_pilot(self, grade_id, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/carbide-grades/{grade_id}/start-pilot",
            payload,
            headers,
        )

    def revise_carbide_grade(self, grade_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/carbide-grades/{grade_id}/revise", payload, headers
        )

    def retire_carbide_grade(self, grade_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/carbide-grades/{grade_id}/retire", payload, headers
        )

    # ── Powder blend batches ────────────────────────────────────────────
    def create_powder_blend_batch(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/powder-blend-batches", payload, headers
        )

    def get_powder_blend_batch(self, batch_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/powder-blend-batches/{batch_id}", headers=headers
        )

    def list_powder_blend_batches(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/powder-blend-batches", headers=headers, params=params
        )

    def press_powder_blend_batch(self, batch_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/powder-blend-batches/{batch_id}/press",
            payload,
            headers,
        )

    def sinter_powder_blend_batch(self, batch_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/powder-blend-batches/{batch_id}/sinter",
            payload,
            headers,
        )

    def quarantine_powder_blend_batch(self, batch_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/powder-blend-batches/{batch_id}/quarantine",
            payload,
            headers,
        )

    # ── Insert geometries ───────────────────────────────────────────────
    def create_insert_geometry(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/insert-geometries", payload, headers
        )

    def get_insert_geometry(self, geometry_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/insert-geometries/{geometry_id}", headers=headers
        )

    def list_insert_geometries(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/insert-geometries", headers=headers, params=params
        )

    def release_insert_geometry(self, geometry_id, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/insert-geometries/{geometry_id}/release",
            payload,
            headers,
        )

    def revise_insert_geometry(self, geometry_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/insert-geometries/{geometry_id}/revise",
            payload,
            headers,
        )

    # ── Coating recipes ─────────────────────────────────────────────────
    def create_coating_recipe(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/coating-recipes", payload, headers)

    def get_coating_recipe(self, recipe_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/coating-recipes/{recipe_id}", headers=headers
        )

    def list_coating_recipes(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/coating-recipes", headers=headers, params=params
        )

    def revise_coating_recipe(self, recipe_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/coating-recipes/{recipe_id}/revise", payload, headers
        )

    # ── Coating runs ────────────────────────────────────────────────────
    def create_coating_run(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/coating-runs", payload, headers)

    def get_coating_run(self, run_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/coating-runs/{run_id}", headers=headers
        )

    def list_coating_runs(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/coating-runs", headers=headers, params=params
        )

    def complete_coating_run(self, run_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/coating-runs/{run_id}/complete", payload, headers
        )

    # ── Grinding wheels ─────────────────────────────────────────────────
    def create_grinding_wheel(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/grinding-wheels", payload, headers)

    def get_grinding_wheel(self, wheel_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/grinding-wheels/{wheel_id}", headers=headers
        )

    def list_grinding_wheels(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/grinding-wheels", headers=headers, params=params
        )

    def dress_grinding_wheel(self, wheel_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/grinding-wheels/{wheel_id}/dress", payload, headers
        )

    # ── Grinding runs ───────────────────────────────────────────────────
    def create_grinding_run(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/grinding-runs", payload, headers)

    def get_grinding_run(self, run_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/grinding-runs/{run_id}", headers=headers
        )

    def list_grinding_runs(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/grinding-runs", headers=headers, params=params
        )

    def complete_grinding_run(self, run_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/grinding-runs/{run_id}/complete", payload, headers
        )

    def void_grinding_run(self, run_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/grinding-runs/{run_id}/void", payload, headers
        )

    # ── Tool products ───────────────────────────────────────────────────
    def create_tool_product(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/tool-products", payload, headers)

    def get_tool_product(self, product_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/tool-products/{product_id}", headers=headers
        )

    def list_tool_products(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/tool-products", headers=headers, params=params
        )

    def enter_product_qualification(self, product_id, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/tool-products/{product_id}/enter-qualification",
            payload,
            headers,
        )

    def release_tool_product(self, product_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/tool-products/{product_id}/release", payload, headers
        )

    def repin_tool_product(self, product_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/tool-products/{product_id}/repin", payload, headers
        )

    def set_product_supply_status(self, product_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/tool-products/{product_id}/set-supply-status",
            payload,
            headers,
        )

    def withdraw_tool_product(self, product_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/tool-products/{product_id}/withdraw",
            payload,
            headers,
        )

    def get_speeds_feeds(self, product_id, params, headers):
        return self._request(
            "GET",
            f"{API_PREFIX}/tool-products/{product_id}/speeds-feeds",
            headers=headers,
            params=params,
        )

    # ── Qualification dossiers ──────────────────────────────────────────
    def create_qualification_dossier(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/qualification-dossiers", payload, headers
        )

    def get_qualification_dossier(self, dossier_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/qualification-dossiers/{dossier_id}", headers=headers
        )

    def list_qualification_dossiers(self, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/qualification-dossiers",
            headers=headers,
            params=params,
        )

    def submit_qualification_dossier(self, dossier_id, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/qualification-dossiers/{dossier_id}/submit",
            payload,
            headers,
        )

    def approve_qualification_dossier(self, dossier_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/qualification-dossiers/{dossier_id}/approve",
            payload,
            headers,
        )

    def reject_qualification_dossier(self, dossier_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/qualification-dossiers/{dossier_id}/reject",
            payload,
            headers,
        )

    # ── Machining trials ────────────────────────────────────────────────
    def create_machining_trial(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/machining-trials", payload, headers
        )

    def get_machining_trial(self, trial_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/machining-trials/{trial_id}", headers=headers
        )

    def list_machining_trials(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/machining-trials", headers=headers, params=params
        )

    def complete_machining_trial(self, trial_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/machining-trials/{trial_id}/complete",
            payload,
            headers,
        )

    # ── Customers ───────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/customers/{customer_id}", headers=headers
        )

    def list_customers(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/customers", headers=headers, params=params
        )

    def create_credit_adjustment(self, customer_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/customers/{customer_id}/credit-adjustments",
            payload,
            headers,
        )

    def close_customer(self, customer_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/customers/{customer_id}/close", payload, headers
        )

    # ── Tool orders ─────────────────────────────────────────────────────
    def create_tool_order(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/tool-orders", payload, headers)

    def get_tool_order(self, order_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/tool-orders/{order_id}", headers=headers
        )

    def list_tool_orders(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/tool-orders", headers=headers, params=params
        )

    def submit_tool_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/tool-orders/{order_id}/submit", payload, headers
        )

    def confirm_tool_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/tool-orders/{order_id}/confirm", payload, headers
        )

    def ship_tool_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/tool-orders/{order_id}/ship", payload, headers
        )

    def cancel_tool_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/tool-orders/{order_id}/cancel", payload, headers
        )

    # ── Reconditioning jobs ─────────────────────────────────────────────
    def create_recondition_job(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/recondition-jobs", payload, headers
        )

    def get_recondition_job(self, job_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/recondition-jobs/{job_id}", headers=headers
        )

    def list_recondition_jobs(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/recondition-jobs", headers=headers, params=params
        )

    def inspect_recondition_job(self, job_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/recondition-jobs/{job_id}/inspect", payload, headers
        )

    def refurbish_recondition_job(self, job_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/recondition-jobs/{job_id}/refurbish",
            payload,
            headers,
        )

    def return_recondition_job(self, job_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/recondition-jobs/{job_id}/return", payload, headers
        )

    def scrap_recondition_job(self, job_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/recondition-jobs/{job_id}/scrap", payload, headers
        )

    # ── Connection hygiene ──────────────────────────────────────────────
    def reset_session(self):
        """Drop every pooled socket and open a fresh HTTP session.

        The server process is replaced before each test, so a keep-alive
        socket held over from the previous test points at a dead process and
        can surface as ``ConnectionResetError`` on its next use.
        """
        try:
            self.session.close()
        except Exception:  # pragma: no cover - best-effort teardown
            pass
        self.session = requests.Session()


api_client = ApiClient()
