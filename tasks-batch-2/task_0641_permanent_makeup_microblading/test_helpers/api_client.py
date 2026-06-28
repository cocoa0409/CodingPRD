"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; only PRD-specific endpoint methods
are defined here. The base _request() method handles envelope plumbing.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- logical clock -----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ----- Studio -----
    def create_studio(self, payload, headers):
        return self._request("POST", "/studios", payload, headers)

    def get_studio(self, studio_id, headers):
        return self._request("GET", f"/studios/{studio_id}", headers=headers)

    # ----- Technician -----
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/technicians", headers=headers, params=params)

    def suspend_license(self, technician_id, payload, headers):
        return self._request(
            "POST", f"/technicians/{technician_id}/suspend-license", payload, headers
        )

    def reinstate_license(self, technician_id, headers):
        return self._request(
            "POST", f"/technicians/{technician_id}/reinstate-license", headers=headers
        )

    # ----- Client -----
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def medical_clearance(self, client_id, headers):
        return self._request(
            "POST", f"/clients/{client_id}/medical-clearance", headers=headers
        )

    # ----- ConsentRecord -----
    def create_consent_record(self, payload, headers):
        return self._request("POST", "/consent-records", payload, headers)

    def get_consent_record(self, consent_id, headers):
        return self._request("GET", f"/consent-records/{consent_id}", headers=headers)

    def list_consent_records(self, headers, params=None):
        return self._request("GET", "/consent-records", headers=headers, params=params)

    # ----- PatchTest -----
    def create_patch_test(self, payload, headers):
        return self._request("POST", "/patch-tests", payload, headers)

    def get_patch_test(self, patch_test_id, headers):
        return self._request("GET", f"/patch-tests/{patch_test_id}", headers=headers)

    def list_patch_tests(self, headers, params=None):
        return self._request("GET", "/patch-tests", headers=headers, params=params)

    def read_patch_test(self, patch_test_id, payload, headers):
        return self._request(
            "POST", f"/patch-tests/{patch_test_id}/read", payload, headers
        )

    def void_patch_test(self, patch_test_id, headers):
        return self._request(
            "POST", f"/patch-tests/{patch_test_id}/void", headers=headers
        )

    # ----- ColorFormula -----
    def create_color_formula(self, payload, headers):
        return self._request("POST", "/color-formulas", payload, headers)

    def get_color_formula(self, formula_id, headers):
        return self._request("GET", f"/color-formulas/{formula_id}", headers=headers)

    def list_color_formulas(self, headers, params=None):
        return self._request("GET", "/color-formulas", headers=headers, params=params)

    # ----- Appointment -----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def deposit(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/deposit", payload, headers
        )

    def start_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/start", headers=headers
        )

    def finish_procedure(self, appointment_id, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/finish-procedure", headers=headers
        )

    def pay_balance(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/pay-balance", payload, headers
        )

    def complete_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/complete", headers=headers
        )

    def cancel_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/cancel", headers=headers
        )

    def no_show(self, appointment_id, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/no-show", headers=headers
        )

    def void_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/void", headers=headers
        )

    def book_touch_up(self, payload, headers):
        return self._request("POST", "/appointments/touch-up", payload, headers)

    def book_annual_refresh(self, payload, headers):
        return self._request("POST", "/appointments/annual-refresh", payload, headers)

    # ----- PackageOrder -----
    def create_package(self, payload, headers):
        return self._request("POST", "/packages", payload, headers)

    def get_package(self, package_id, headers):
        return self._request("GET", f"/packages/{package_id}", headers=headers)

    def list_packages(self, headers, params=None):
        return self._request("GET", "/packages", headers=headers, params=params)

    # ----- DepositTransaction -----
    def get_deposit_transaction(self, txn_id, headers):
        return self._request("GET", f"/deposit-transactions/{txn_id}", headers=headers)

    def list_deposit_transactions(self, headers, params=None):
        return self._request(
            "GET", "/deposit-transactions", headers=headers, params=params
        )

    # ----- HealingLog -----
    def create_healing_log(self, payload, headers):
        return self._request("POST", "/healing-logs", payload, headers)

    def get_healing_log(self, log_id, headers):
        return self._request("GET", f"/healing-logs/{log_id}", headers=headers)

    def list_healing_logs(self, headers, params=None):
        return self._request("GET", "/healing-logs", headers=headers, params=params)

    # ----- RedoRequest -----
    def create_redo_request(self, payload, headers):
        return self._request("POST", "/redo-requests", payload, headers)

    def get_redo_request(self, redo_id, headers):
        return self._request("GET", f"/redo-requests/{redo_id}", headers=headers)

    def list_redo_requests(self, headers, params=None):
        return self._request("GET", "/redo-requests", headers=headers, params=params)

    def approve_redo(self, redo_id, headers):
        return self._request(
            "POST", f"/redo-requests/{redo_id}/approve", headers=headers
        )

    def deny_redo(self, redo_id, headers):
        return self._request("POST", f"/redo-requests/{redo_id}/deny", headers=headers)

    def schedule_redo(self, redo_id, payload, headers):
        return self._request(
            "POST", f"/redo-requests/{redo_id}/schedule", payload, headers
        )


api_client = ApiClient()
