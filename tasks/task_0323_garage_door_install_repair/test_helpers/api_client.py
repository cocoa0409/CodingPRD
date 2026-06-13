"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Catalog / configuration -----
    def create_door_model(self, payload, headers):
        return self._request("POST", "/door-models", payload, headers)

    def get_door_model(self, door_id, headers):
        return self._request("GET", f"/door-models/{door_id}", headers=headers)

    def create_opener_model(self, payload, headers):
        return self._request("POST", "/opener-models", payload, headers)

    def get_opener_model(self, opener_id, headers):
        return self._request("GET", f"/opener-models/{opener_id}", headers=headers)

    def create_part(self, payload, headers):
        return self._request("POST", "/parts", payload, headers)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/parts/{part_id}", headers=headers)

    def create_equipment_unit(self, payload, headers):
        return self._request("POST", "/equipment-units", payload, headers)

    # ----- Customers -----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ----- Technicians -----
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    def set_technician_leave(self, technician_id, payload, headers):
        return self._request("POST", f"/technicians/{technician_id}/set-leave", payload, headers)

    # ----- Quotes -----
    def create_quote(self, payload, headers):
        return self._request("POST", "/quotes", payload, headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def add_quote_line(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/lines", payload, headers)

    def list_quote_lines(self, quote_id, headers, params=None):
        return self._request("GET", f"/quotes/{quote_id}/lines", headers=headers, params=params)

    def send_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/send", {}, headers)

    def revise_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/revise", payload, headers)

    def accept_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/accept", {}, headers)

    def decline_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/decline", {}, headers)

    # ----- Jobs -----
    def get_job(self, job_id, headers):
        return self._request("GET", f"/jobs/{job_id}", headers=headers)

    def list_jobs(self, headers, params=None):
        return self._request("GET", "/jobs", headers=headers, params=params)

    def schedule_job(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/schedule", payload, headers)

    def depart_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/depart", {}, headers)

    def arrive_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/arrive", {}, headers)

    def safety_check_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/safety-check", {}, headers)

    def complete_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/complete", {}, headers)

    def invoice_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/invoice", {}, headers)

    def pay_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/pay", {}, headers)

    def close_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/close", {}, headers)

    def cancel_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/cancel", {}, headers)

    # ----- Part reservations -----
    def create_part_reservation(self, payload, headers):
        return self._request("POST", "/part-reservations", payload, headers)

    def list_part_reservations(self, headers, params=None):
        return self._request("GET", "/part-reservations", headers=headers, params=params)

    def get_part_reservation(self, reservation_id, headers):
        return self._request("GET", f"/part-reservations/{reservation_id}", headers=headers)

    def consume_part_reservation(self, reservation_id, headers):
        return self._request("POST", f"/part-reservations/{reservation_id}/consume", {}, headers)

    def release_part_reservation(self, reservation_id, headers):
        return self._request("POST", f"/part-reservations/{reservation_id}/release", {}, headers)

    # ----- Warranty plans -----
    def create_warranty_plan(self, payload, headers):
        return self._request("POST", "/warranty-plans", payload, headers)

    def get_warranty_plan(self, plan_id, headers):
        return self._request("GET", f"/warranty-plans/{plan_id}", headers=headers)

    def list_warranty_plans(self, headers, params=None):
        return self._request("GET", "/warranty-plans", headers=headers, params=params)

    def redeem_tune_up(self, plan_id, headers):
        return self._request("POST", f"/warranty-plans/{plan_id}/tune-up", {}, headers)

    def cancel_warranty_plan(self, plan_id, headers):
        return self._request("POST", f"/warranty-plans/{plan_id}/cancel", {}, headers)

    def expire_warranty_plan(self, plan_id, headers):
        return self._request("POST", f"/warranty-plans/{plan_id}/expire", {}, headers)

    # ----- Financing -----
    def create_financing_application(self, payload, headers):
        return self._request("POST", "/financing-applications", payload, headers)

    def get_financing_application(self, app_id, headers):
        return self._request("GET", f"/financing-applications/{app_id}", headers=headers)

    def list_financing_applications(self, headers, params=None):
        return self._request("GET", "/financing-applications", headers=headers, params=params)

    def approve_financing_application(self, app_id, headers):
        return self._request("POST", f"/financing-applications/{app_id}/approve", {}, headers)

    def decline_financing_application(self, app_id, headers):
        return self._request("POST", f"/financing-applications/{app_id}/decline", {}, headers)

    def activate_financing_application(self, app_id, headers):
        return self._request("POST", f"/financing-applications/{app_id}/activate", {}, headers)

    def default_financing_application(self, app_id, headers):
        return self._request("POST", f"/financing-applications/{app_id}/default", {}, headers)

    # ----- Callbacks -----
    def create_callback(self, payload, headers):
        return self._request("POST", "/callbacks", payload, headers)

    def get_callback(self, callback_id, headers):
        return self._request("GET", f"/callbacks/{callback_id}", headers=headers)

    def list_callbacks(self, headers, params=None):
        return self._request("GET", "/callbacks", headers=headers, params=params)

    def schedule_callback(self, callback_id, headers):
        return self._request("POST", f"/callbacks/{callback_id}/schedule", {}, headers)

    def arrive_callback(self, callback_id, headers):
        return self._request("POST", f"/callbacks/{callback_id}/arrive", {}, headers)

    def resolve_callback(self, callback_id, payload, headers):
        return self._request("POST", f"/callbacks/{callback_id}/resolve", payload, headers)

    def reopen_callback(self, callback_id, headers):
        return self._request("POST", f"/callbacks/{callback_id}/reopen", {}, headers)

    # ----- Test-driving clock endpoint -----
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
