"""API client: one method per endpoint defined in the PRD endpoint table (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Customer ---
    def create_customer(self, payload, headers=None):
        return self._request("POST", "/label-jobs/customers", payload, headers)

    def list_customers(self, headers=None, params=None):
        return self._request("GET", "/label-jobs/customers", params or {}, headers)

    def get_customer(self, customer_id, headers=None):
        return self._request("GET", f"/label-jobs/customers/{customer_id}",
                             headers=headers)

    def patch_customer(self, customer_id, payload, headers=None):
        return self._request("PATCH", f"/label-jobs/customers/{customer_id}",
                             payload, headers)

    # --- ArtworkVersion ---
    def create_artwork_version(self, customer_id, payload, headers=None):
        return self._request(
            "POST", f"/label-jobs/customers/{customer_id}/artwork-versions",
            payload, headers)

    def list_artwork_versions(self, customer_id, headers=None, params=None):
        return self._request(
            "GET", f"/label-jobs/customers/{customer_id}/artwork-versions",
            params or {}, headers)

    def get_artwork_version(self, customer_id, artwork_id, headers=None):
        return self._request(
            "GET",
            f"/label-jobs/customers/{customer_id}/artwork-versions/{artwork_id}",
            headers=headers)

    def submit_artwork(self, customer_id, artwork_id, headers=None):
        return self._request(
            "POST",
            f"/label-jobs/customers/{customer_id}/artwork-versions/{artwork_id}/submit",
            {}, headers)

    def approve_artwork(self, customer_id, artwork_id, headers=None):
        return self._request(
            "POST",
            f"/label-jobs/customers/{customer_id}/artwork-versions/{artwork_id}/approve",
            {}, headers)

    def return_artwork(self, customer_id, artwork_id, headers=None):
        return self._request(
            "POST",
            f"/label-jobs/customers/{customer_id}/artwork-versions/{artwork_id}/return",
            {}, headers)

    # --- Substrate ---
    def create_substrate(self, payload, headers=None):
        return self._request("POST", "/label-jobs/substrates", payload, headers)

    def list_substrates(self, headers=None, params=None):
        return self._request("GET", "/label-jobs/substrates", params or {},
                             headers)

    def get_substrate(self, substrate_id, headers=None):
        return self._request("GET", f"/label-jobs/substrates/{substrate_id}",
                             headers=headers)

    # --- InkRecipe ---
    def create_ink_recipe(self, payload, headers=None):
        return self._request("POST", "/label-jobs/ink-recipes", payload, headers)

    def list_ink_recipes(self, headers=None, params=None):
        return self._request("GET", "/label-jobs/ink-recipes", params or {},
                             headers)

    # --- Die ---
    def create_die(self, payload, headers=None):
        return self._request("POST", "/label-jobs/dies", payload, headers)

    def purchase_die(self, payload, headers=None):
        return self._request("POST", "/label-jobs/dies/purchase", payload,
                             headers)

    def list_dies(self, headers=None, params=None):
        return self._request("GET", "/label-jobs/dies", params or {}, headers)

    def get_die(self, die_id, headers=None):
        return self._request("GET", f"/label-jobs/dies/{die_id}",
                             headers=headers)

    def retire_die(self, die_id, headers=None):
        return self._request("POST", f"/label-jobs/dies/{die_id}/retire", {},
                             headers)

    # --- Press ---
    def create_press(self, payload, headers=None):
        return self._request("POST", "/label-jobs/presses", payload, headers)

    def list_presses(self, headers=None, params=None):
        return self._request("GET", "/label-jobs/presses", params or {},
                             headers)

    def get_press(self, press_id, headers=None):
        return self._request("GET", f"/label-jobs/presses/{press_id}",
                             headers=headers)

    # --- LabelJob ---
    def create_job(self, customer_id, payload, headers=None):
        return self._request("POST", f"/label-jobs/customers/{customer_id}/jobs",
                             payload, headers)

    def list_customer_jobs(self, customer_id, headers=None, params=None):
        return self._request("GET", f"/label-jobs/customers/{customer_id}/jobs",
                             params or {}, headers)

    def list_jobs(self, headers=None, params=None):
        return self._request("GET", "/label-jobs/jobs", params or {}, headers)

    def get_job(self, job_id, headers=None):
        return self._request("GET", f"/label-jobs/jobs/{job_id}",
                             headers=headers)

    def approve_job(self, job_id, headers=None):
        return self._request("POST", f"/label-jobs/jobs/{job_id}/approve", {},
                             headers)

    def release_job(self, job_id, payload, headers=None):
        return self._request("POST", f"/label-jobs/jobs/{job_id}/release",
                             payload, headers)

    def start_press(self, job_id, headers=None):
        return self._request("POST", f"/label-jobs/jobs/{job_id}/start-press",
                             {}, headers)

    def complete_press(self, job_id, payload, headers=None):
        return self._request("POST", f"/label-jobs/jobs/{job_id}/complete-press",
                             payload, headers)

    def ship_job(self, job_id, payload, headers=None):
        return self._request("POST", f"/label-jobs/jobs/{job_id}/ship", payload,
                             headers)

    def cancel_job(self, job_id, headers=None):
        return self._request("POST", f"/label-jobs/jobs/{job_id}/cancel", {},
                             headers)

    # --- ColorMeasurement ---
    def record_color_measurement(self, job_id, payload, headers=None):
        return self._request("POST",
                             f"/label-jobs/jobs/{job_id}/color-measurements",
                             payload, headers)

    def list_color_measurements(self, job_id, headers=None, params=None):
        return self._request("GET",
                             f"/label-jobs/jobs/{job_id}/color-measurements",
                             params or {}, headers)

    def judge_color_measurement(self, job_id, measurement_id, payload,
                                headers=None):
        return self._request(
            "POST",
            f"/label-jobs/jobs/{job_id}/color-measurements/{measurement_id}/judge",
            payload, headers)

    # --- RewindRoll ---
    def record_rewind_roll(self, job_id, payload, headers=None):
        return self._request("POST", f"/label-jobs/jobs/{job_id}/rewind-rolls",
                             payload, headers)

    def list_rewind_rolls(self, job_id, headers=None, params=None):
        return self._request("GET", f"/label-jobs/jobs/{job_id}/rewind-rolls",
                             params or {}, headers)

    def accept_rewind_roll(self, job_id, roll_id, headers=None):
        return self._request(
            "POST", f"/label-jobs/jobs/{job_id}/rewind-rolls/{roll_id}/accept",
            {}, headers)

    def reject_rewind_roll(self, job_id, roll_id, headers=None):
        return self._request(
            "POST", f"/label-jobs/jobs/{job_id}/rewind-rolls/{roll_id}/reject",
            {}, headers)

    # --- ComplianceLetter ---
    def issue_compliance_letter(self, job_id, payload, headers=None):
        return self._request("POST",
                             f"/label-jobs/jobs/{job_id}/compliance-letters",
                             payload, headers)

    def list_compliance_letters(self, job_id, headers=None, params=None):
        return self._request("GET",
                             f"/label-jobs/jobs/{job_id}/compliance-letters",
                             params or {}, headers)


api_client = ApiClient()
