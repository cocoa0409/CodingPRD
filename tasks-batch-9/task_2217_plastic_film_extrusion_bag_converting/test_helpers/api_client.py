"""API client: one method per endpoint declared in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Resin grades
    # ------------------------------------------------------------------
    def create_resin_grade(self, payload, headers):
        return self._request("POST", "/resin-grades", payload, headers)

    def get_resin_grade(self, grade_id, headers):
        return self._request("GET", f"/resin-grades/{grade_id}", headers=headers)

    def list_resin_grades(self, headers, params=None):
        return self._request("GET", "/resin-grades", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Blend recipes
    # ------------------------------------------------------------------
    def create_blend_recipe(self, payload, headers):
        return self._request("POST", "/blend-recipes", payload, headers)

    def get_blend_recipe(self, recipe_id, headers):
        return self._request("GET", f"/blend-recipes/{recipe_id}", headers=headers)

    def list_blend_recipes(self, headers, params=None):
        return self._request("GET", "/blend-recipes", headers=headers, params=params)

    def add_recipe_component(self, recipe_id, payload, headers):
        return self._request("POST", f"/blend-recipes/{recipe_id}/components",
                             payload, headers)

    def submit_blend_recipe(self, recipe_id, headers):
        return self._request("POST", f"/blend-recipes/{recipe_id}/submit", {}, headers)

    def approve_blend_recipe(self, recipe_id, headers):
        return self._request("POST", f"/blend-recipes/{recipe_id}/approve", {}, headers)

    def reject_blend_recipe(self, recipe_id, rejection_reason, headers):
        return self._request("POST", f"/blend-recipes/{recipe_id}/reject",
                             {"rejection_reason": rejection_reason}, headers)

    def reopen_blend_recipe(self, recipe_id, headers):
        return self._request("POST", f"/blend-recipes/{recipe_id}/reopen", {}, headers)

    # ------------------------------------------------------------------
    # Extrusion lines
    # ------------------------------------------------------------------
    def create_extrusion_line(self, payload, headers):
        return self._request("POST", "/extrusion-lines", payload, headers)

    def get_extrusion_line(self, line_id, headers):
        return self._request("GET", f"/extrusion-lines/{line_id}", headers=headers)

    def list_extrusion_lines(self, headers, params=None):
        return self._request("GET", "/extrusion-lines", headers=headers, params=params)

    def clear_capability_flags(self, line_id, headers):
        return self._request("POST", f"/extrusion-lines/{line_id}/clear-capability-flags",
                             {}, headers)

    # ------------------------------------------------------------------
    # Extrusion runs
    # ------------------------------------------------------------------
    def create_extrusion_run(self, payload, headers):
        return self._request("POST", "/extrusion-runs", payload, headers)

    def get_extrusion_run(self, run_id, headers):
        return self._request("GET", f"/extrusion-runs/{run_id}", headers=headers)

    def list_extrusion_runs(self, headers, params=None):
        return self._request("GET", "/extrusion-runs", headers=headers, params=params)

    def reschedule_extrusion_run(self, run_id, scheduled_start, scheduled_end, headers):
        return self._request("PATCH", f"/extrusion-runs/{run_id}/reschedule",
                             {"scheduled_start": scheduled_start,
                              "scheduled_end": scheduled_end}, headers)

    def start_extrusion_run(self, run_id, headers):
        return self._request("POST", f"/extrusion-runs/{run_id}/start", {}, headers)

    def add_gauge_reading(self, run_id, payload, headers):
        return self._request("POST", f"/extrusion-runs/{run_id}/gauge-readings",
                             payload, headers)

    def hold_extrusion_run(self, run_id, hold_reason, headers):
        return self._request("POST", f"/extrusion-runs/{run_id}/hold",
                             {"hold_reason": hold_reason}, headers)

    def resume_extrusion_run(self, run_id, headers):
        return self._request("POST", f"/extrusion-runs/{run_id}/resume", {}, headers)

    def create_regrind_reincorporation(self, run_id, payload, headers):
        return self._request("POST", f"/extrusion-runs/{run_id}/regrind-reincorporations",
                             payload, headers)

    def complete_extrusion_run(self, run_id, gross_output_kg, scrap_kg, headers):
        return self._request("POST", f"/extrusion-runs/{run_id}/complete",
                             {"gross_output_kg": gross_output_kg,
                              "scrap_kg": scrap_kg}, headers)

    # ------------------------------------------------------------------
    # Film rolls
    # ------------------------------------------------------------------
    def create_film_roll(self, payload, headers):
        return self._request("POST", "/film-rolls", payload, headers)

    def get_film_roll(self, roll_id, headers):
        return self._request("GET", f"/film-rolls/{roll_id}", headers=headers)

    def list_film_rolls(self, headers, params=None):
        return self._request("GET", "/film-rolls", headers=headers, params=params)

    def release_film_roll(self, roll_id, headers):
        return self._request("POST", f"/film-rolls/{roll_id}/release", {}, headers)

    def scrap_film_roll(self, roll_id, headers, pool_id=None):
        payload = {} if pool_id is None else {"pool_id": pool_id}
        return self._request("POST", f"/film-rolls/{roll_id}/scrap", payload, headers)

    # ------------------------------------------------------------------
    # Regrind pools and ledger
    # ------------------------------------------------------------------
    def create_regrind_pool(self, payload, headers):
        return self._request("POST", "/regrind-pools", payload, headers)

    def get_regrind_pool(self, pool_id, headers):
        return self._request("GET", f"/regrind-pools/{pool_id}", headers=headers)

    def list_regrind_pools(self, headers, params=None):
        return self._request("GET", "/regrind-pools", headers=headers, params=params)

    def get_regrind_pool_balance(self, pool_id, headers):
        return self._request("GET", f"/regrind-pools/{pool_id}/balance", headers=headers)

    def get_regrind_transaction(self, transaction_id, headers):
        return self._request("GET", f"/regrind-transactions/{transaction_id}",
                             headers=headers)

    def list_regrind_transactions(self, headers, params=None):
        return self._request("GET", "/regrind-transactions", headers=headers,
                             params=params)

    def reverse_regrind_transaction(self, transaction_id, reversal_reason, headers):
        return self._request("POST", f"/regrind-transactions/{transaction_id}/reverse",
                             {"reversal_reason": reversal_reason}, headers)

    # ------------------------------------------------------------------
    # Print presses
    # ------------------------------------------------------------------
    def create_print_press(self, payload, headers):
        return self._request("POST", "/print-presses", payload, headers)

    def get_print_press(self, press_id, headers):
        return self._request("GET", f"/print-presses/{press_id}", headers=headers)

    def list_print_presses(self, headers, params=None):
        return self._request("GET", "/print-presses", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Plate sets
    # ------------------------------------------------------------------
    def create_plate_set(self, payload, headers):
        return self._request("POST", "/plate-sets", payload, headers)

    def get_plate_set(self, plate_set_id, headers):
        return self._request("GET", f"/plate-sets/{plate_set_id}", headers=headers)

    def list_plate_sets(self, headers, params=None):
        return self._request("GET", "/plate-sets", headers=headers, params=params)

    def mount_plate_set(self, plate_set_id, press_id, headers):
        return self._request("POST", f"/plate-sets/{plate_set_id}/mount",
                             {"press_id": press_id}, headers)

    # ------------------------------------------------------------------
    # Print jobs
    # ------------------------------------------------------------------
    def create_print_job(self, payload, headers):
        return self._request("POST", "/print-jobs", payload, headers)

    def get_print_job(self, job_id, headers):
        return self._request("GET", f"/print-jobs/{job_id}", headers=headers)

    def list_print_jobs(self, headers, params=None):
        return self._request("GET", "/print-jobs", headers=headers, params=params)

    def registration_check(self, job_id, registration_drift_micron, headers):
        return self._request("POST", f"/print-jobs/{job_id}/registration-check",
                             {"registration_drift_micron": registration_drift_micron},
                             headers)

    def color_proof(self, job_id, delta_e_measured, headers):
        return self._request("POST", f"/print-jobs/{job_id}/color-proof",
                             {"delta_e_measured": delta_e_measured}, headers)

    def start_print(self, job_id, headers):
        return self._request("POST", f"/print-jobs/{job_id}/start-print", {}, headers)

    def complete_print_job(self, job_id, printed_kg, headers):
        return self._request("POST", f"/print-jobs/{job_id}/complete",
                             {"printed_kg": printed_kg}, headers)

    # ------------------------------------------------------------------
    # Bag lots
    # ------------------------------------------------------------------
    def create_bag_lot(self, payload, headers):
        return self._request("POST", "/bag-lots", payload, headers)

    def get_bag_lot(self, lot_id, headers):
        return self._request("GET", f"/bag-lots/{lot_id}", headers=headers)

    def list_bag_lots(self, headers, params=None):
        return self._request("GET", "/bag-lots", headers=headers, params=params)

    def add_seal_test(self, lot_id, payload, headers):
        return self._request("POST", f"/bag-lots/{lot_id}/seal-tests", payload, headers)

    def finalize_seal_tests(self, lot_id, headers):
        return self._request("POST", f"/bag-lots/{lot_id}/finalize-tests", {}, headers)

    def packout_bag_lot(self, lot_id, requested_bags, expected_bag_lot_version, headers):
        return self._request("POST", f"/bag-lots/{lot_id}/packout",
                             {"requested_bags": requested_bags,
                              "expected_bag_lot_version": expected_bag_lot_version},
                             headers)

    def release_bag_lot(self, lot_id, headers):
        return self._request("POST", f"/bag-lots/{lot_id}/release", {}, headers)

    def ship_bag_lot(self, lot_id, headers):
        return self._request("POST", f"/bag-lots/{lot_id}/ship", {}, headers)

    # ------------------------------------------------------------------
    # Compliance dossiers
    # ------------------------------------------------------------------
    def create_compliance_dossier(self, payload, headers):
        return self._request("POST", "/compliance-dossiers", payload, headers)

    def get_compliance_dossier(self, dossier_id, headers):
        return self._request("GET", f"/compliance-dossiers/{dossier_id}", headers=headers)

    def list_compliance_dossiers(self, headers, params=None):
        return self._request("GET", "/compliance-dossiers", headers=headers, params=params)

    def issue_compliance_dossier(self, dossier_id, headers):
        return self._request("POST", f"/compliance-dossiers/{dossier_id}/issue",
                             {}, headers)

    def revoke_compliance_dossier(self, dossier_id, revocation_reason, headers):
        return self._request("POST", f"/compliance-dossiers/{dossier_id}/revoke",
                             {"revocation_reason": revocation_reason}, headers)


api_client = ApiClient()
