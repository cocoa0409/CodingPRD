"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test offerings ----
    def create_test_offering(self, payload, headers):
        return self._request("POST", "/catalog/test-offerings", payload, headers)

    def list_test_offerings(self, headers, params=None):
        return self._request("GET", "/catalog/test-offerings", headers=headers, params=params)

    def get_test_offering(self, offering_id, headers):
        return self._request("GET", f"/catalog/test-offerings/{offering_id}", headers=headers)

    def archive_test_offering(self, offering_id, headers):
        return self._request("POST", f"/catalog/test-offerings/{offering_id}/archive", headers=headers)

    # ---- Panel bundles ----
    def create_panel_bundle(self, payload, headers):
        return self._request("POST", "/catalog/panel-bundles", payload, headers)

    def list_panel_bundles(self, headers, params=None):
        return self._request("GET", "/catalog/panel-bundles", headers=headers, params=params)

    def get_panel_bundle(self, bundle_id, headers):
        return self._request("GET", f"/catalog/panel-bundles/{bundle_id}", headers=headers)

    # ---- Patients ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/catalog/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/catalog/patients/{patient_id}", headers=headers)

    def update_patient(self, patient_id, payload, headers):
        return self._request("PATCH", f"/catalog/patients/{patient_id}", payload, headers)

    # ---- Carts & cart lines ----
    def create_cart(self, payload, headers):
        return self._request("POST", "/catalog/carts", payload, headers)

    def list_carts(self, headers, params=None):
        return self._request("GET", "/catalog/carts", headers=headers, params=params)

    def get_cart(self, cart_id, headers):
        return self._request("GET", f"/catalog/carts/{cart_id}", headers=headers)

    def update_cart(self, cart_id, payload, headers):
        return self._request("PATCH", f"/catalog/carts/{cart_id}", payload, headers)

    def create_cart_line(self, payload, headers):
        return self._request("POST", "/catalog/cart-lines", payload, headers)

    def list_cart_lines(self, headers, params=None):
        return self._request("GET", "/catalog/cart-lines", headers=headers, params=params)

    def get_cart_line(self, cart_line_id, headers):
        return self._request("GET", f"/catalog/cart-lines/{cart_line_id}", headers=headers)

    def delete_cart_line(self, cart_line_id, headers):
        return self._request("DELETE", f"/catalog/cart-lines/{cart_line_id}", headers=headers)

    # ---- Orders ----
    def create_order(self, payload, headers):
        return self._request("POST", "/catalog/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/catalog/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/catalog/orders", headers=headers, params=params)

    def capture_payment(self, order_id, payload, headers):
        return self._request("POST", f"/catalog/orders/{order_id}/capture-payment", payload, headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/catalog/orders/{order_id}/cancel", payload, headers)

    # ---- Order lines ----
    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/catalog/order-lines", headers=headers, params=params)

    def get_order_line(self, order_line_id, headers):
        return self._request("GET", f"/catalog/order-lines/{order_line_id}", headers=headers)

    def collect_order_line(self, order_line_id, headers):
        return self._request("POST", f"/catalog/order-lines/{order_line_id}/collect", headers=headers)

    # ---- Physician orders ----
    def list_physician_orders(self, headers, params=None):
        return self._request("GET", "/catalog/physician-orders", headers=headers, params=params)

    def get_physician_order(self, physician_order_id, headers):
        return self._request("GET", f"/catalog/physician-orders/{physician_order_id}", headers=headers)

    def decide_physician_order(self, physician_order_id, payload, headers):
        return self._request("POST", f"/catalog/physician-orders/{physician_order_id}/decision", payload, headers)

    def resubmit_physician_order(self, physician_order_id, payload, headers):
        return self._request("POST", f"/catalog/physician-orders/{physician_order_id}/resubmit", payload, headers)

    # ---- Appointments ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/catalog/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/catalog/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/catalog/appointments/{appointment_id}", headers=headers)

    def check_in_appointment(self, appointment_id, headers):
        return self._request("POST", f"/catalog/appointments/{appointment_id}/check-in", headers=headers)

    # ---- Home kits ----
    def create_home_kit(self, payload, headers):
        return self._request("POST", "/catalog/home-kits", payload, headers)

    def list_home_kits(self, headers, params=None):
        return self._request("GET", "/catalog/home-kits", headers=headers, params=params)

    def get_home_kit(self, home_kit_id, headers):
        return self._request("GET", f"/catalog/home-kits/{home_kit_id}", headers=headers)

    # ---- Specimens ----
    def list_specimens(self, headers, params=None):
        return self._request("GET", "/catalog/specimens", headers=headers, params=params)

    def get_specimen(self, specimen_id, headers):
        return self._request("GET", f"/catalog/specimens/{specimen_id}", headers=headers)

    def process_specimen(self, specimen_id, payload, headers):
        return self._request("POST", f"/catalog/specimens/{specimen_id}/process", payload, headers)

    def reject_specimen(self, specimen_id, headers):
        return self._request("POST", f"/catalog/specimens/{specimen_id}/reject", headers=headers)

    # ---- Lab results ----
    def list_lab_results(self, headers, params=None):
        return self._request("GET", "/catalog/lab-results", headers=headers, params=params)

    def get_lab_result(self, lab_result_id, headers):
        return self._request("GET", f"/catalog/lab-results/{lab_result_id}", headers=headers)

    def acknowledge_critical(self, lab_result_id, headers):
        return self._request("POST", f"/catalog/lab-results/{lab_result_id}/acknowledge-critical", headers=headers)

    def release_lab_result(self, lab_result_id, headers):
        return self._request("POST", f"/catalog/lab-results/{lab_result_id}/release", headers=headers)

    def amend_lab_result(self, lab_result_id, payload, headers):
        return self._request("POST", f"/catalog/lab-results/{lab_result_id}/amend", payload, headers)

    # ---- Telehealth referrals ----
    def create_telehealth_referral(self, payload, headers):
        return self._request("POST", "/catalog/telehealth-referrals", payload, headers)

    def list_telehealth_referrals(self, headers, params=None):
        return self._request("GET", "/catalog/telehealth-referrals", headers=headers, params=params)

    def get_telehealth_referral(self, referral_id, headers):
        return self._request("GET", f"/catalog/telehealth-referrals/{referral_id}", headers=headers)

    def schedule_telehealth_referral(self, referral_id, headers):
        return self._request("POST", f"/catalog/telehealth-referrals/{referral_id}/schedule", headers=headers)

    # ---- Analyzer runs ----
    def create_analyzer_run(self, payload, headers):
        return self._request("POST", "/catalog/analyzer-runs", payload, headers)

    def list_analyzer_runs(self, headers, params=None):
        return self._request("GET", "/catalog/analyzer-runs", headers=headers, params=params)

    def release_analyzer_run(self, analyzer_run_id, headers):
        return self._request("POST", f"/catalog/analyzer-runs/{analyzer_run_id}/release", headers=headers)

    # ---- Payments ----
    def list_payments(self, headers, params=None):
        return self._request("GET", "/catalog/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/catalog/payments/{payment_id}", headers=headers)

    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/catalog/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
