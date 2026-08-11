"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Student Health Center API client (all paths under /shc)."""

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/shc/_clock/set_current_utc", payload, headers)

    # --- Students ---
    def create_student(self, payload, headers):
        return self._request("POST", "/shc/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/shc/students/{student_id}", headers=headers)

    # --- Insurance ---
    def create_insurance_policy(self, payload, headers):
        return self._request("POST", "/shc/insurance-policies", payload, headers)

    def verify_insurance_policy(self, policy_id, headers):
        return self._request(
            "POST", f"/shc/insurance-policies/{policy_id}/verify", headers=headers
        )

    def list_student_policies(self, student_id, headers):
        return self._request(
            "GET", f"/shc/students/{student_id}/insurance-policies", headers=headers
        )

    # --- Immunization configuration & records ---
    def create_immunization_requirement(self, payload, headers):
        return self._request("POST", "/shc/immunization-requirements", payload, headers)

    def create_immunization_record(self, payload, headers):
        return self._request("POST", "/shc/immunization-records", payload, headers)

    def list_immunization_records(self, headers, params=None):
        return self._request(
            "GET", "/shc/immunization-records", headers=headers, params=params
        )

    def get_immunization_record(self, record_id, headers):
        return self._request(
            "GET", f"/shc/immunization-records/{record_id}", headers=headers
        )

    def record_dose(self, record_id, payload, headers):
        return self._request(
            "POST", f"/shc/immunization-records/{record_id}/doses", payload, headers
        )

    def exempt_immunization_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"/shc/immunization-records/{record_id}/exempt", payload, headers
        )

    # --- Providers & on-call ---
    def create_provider(self, payload, headers):
        return self._request("POST", "/shc/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/shc/providers/{provider_id}", headers=headers)

    def create_on_call_shift(self, payload, headers):
        return self._request("POST", "/shc/on-call-shifts", payload, headers)

    def list_provider_on_call_shifts(self, provider_id, headers):
        return self._request(
            "GET", f"/shc/providers/{provider_id}/on-call-shifts", headers=headers
        )

    # --- Appointments ---
    def create_appointment(self, payload, headers):
        return self._request("POST", "/shc/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/shc/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request(
            "GET", f"/shc/appointments/{appointment_id}", headers=headers
        )

    def check_in_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/shc/appointments/{appointment_id}/check-in", headers=headers
        )

    def cancel_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/shc/appointments/{appointment_id}/cancel", headers=headers
        )

    # --- Encounters ---
    def list_encounters(self, headers, params=None):
        return self._request("GET", "/shc/encounters", headers=headers, params=params)

    def get_encounter(self, encounter_id, headers):
        return self._request("GET", f"/shc/encounters/{encounter_id}", headers=headers)

    def close_encounter(self, encounter_id, payload, headers):
        return self._request(
            "POST", f"/shc/encounters/{encounter_id}/close", payload, headers
        )

    # --- Pharmacy ---
    def create_prescription(self, encounter_id, payload, headers):
        return self._request(
            "POST", f"/shc/encounters/{encounter_id}/prescriptions", payload, headers
        )

    def list_prescriptions(self, headers, params=None):
        return self._request(
            "GET", "/shc/prescriptions", headers=headers, params=params
        )

    def get_prescription(self, prescription_id, headers):
        return self._request(
            "GET", f"/shc/prescriptions/{prescription_id}", headers=headers
        )

    def dispense_prescription(self, prescription_id, payload, headers):
        return self._request(
            "POST", f"/shc/prescriptions/{prescription_id}/dispense", payload, headers
        )

    def cancel_prescription(self, prescription_id, headers):
        return self._request(
            "POST", f"/shc/prescriptions/{prescription_id}/cancel", headers=headers
        )

    def create_medication_stock(self, payload, headers):
        return self._request("POST", "/shc/medication-stocks", payload, headers)

    def list_medication_stocks(self, headers, params=None):
        return self._request(
            "GET", "/shc/medication-stocks", headers=headers, params=params
        )

    def restock_medication_stock(self, stock_id, payload, headers):
        return self._request(
            "POST", f"/shc/medication-stocks/{stock_id}/restock", payload, headers
        )

    # --- Lab services ---
    def create_lab_order(self, encounter_id, payload, headers):
        return self._request(
            "POST", f"/shc/encounters/{encounter_id}/lab-orders", payload, headers
        )

    def list_encounter_lab_orders(self, encounter_id, headers):
        return self._request(
            "GET", f"/shc/encounters/{encounter_id}/lab-orders", headers=headers
        )

    def get_lab_order(self, lab_order_id, headers):
        return self._request("GET", f"/shc/lab-orders/{lab_order_id}", headers=headers)

    def collect_lab_order(self, lab_order_id, headers):
        return self._request(
            "POST", f"/shc/lab-orders/{lab_order_id}/collect", headers=headers
        )

    def result_lab_order(self, lab_order_id, payload, headers):
        return self._request(
            "POST", f"/shc/lab-orders/{lab_order_id}/result", payload, headers
        )

    def review_lab_order(self, lab_order_id, headers):
        return self._request(
            "POST", f"/shc/lab-orders/{lab_order_id}/review", headers=headers
        )

    # --- Communicable disease & outbreak ---
    def list_disease_cases(self, headers, params=None):
        return self._request("GET", "/shc/disease-cases", headers=headers, params=params)

    def get_disease_case(self, case_id, headers):
        return self._request("GET", f"/shc/disease-cases/{case_id}", headers=headers)

    def list_lab_order_disease_cases(self, lab_order_id, headers):
        return self._request(
            "GET", f"/shc/lab-orders/{lab_order_id}/disease-cases", headers=headers
        )

    def confirm_disease_case(self, case_id, headers):
        return self._request(
            "POST", f"/shc/disease-cases/{case_id}/confirm", headers=headers
        )

    def report_disease_case(self, case_id, headers):
        return self._request(
            "POST", f"/shc/disease-cases/{case_id}/report", headers=headers
        )

    def resolve_disease_case(self, case_id, headers):
        return self._request(
            "POST", f"/shc/disease-cases/{case_id}/resolve", headers=headers
        )

    def list_outbreak_investigations(self, headers, params=None):
        return self._request(
            "GET", "/shc/outbreak-investigations", headers=headers, params=params
        )

    def contain_outbreak(self, investigation_id, headers):
        return self._request(
            "POST",
            f"/shc/outbreak-investigations/{investigation_id}/contain",
            headers=headers,
        )

    def reopen_outbreak(self, investigation_id, headers):
        return self._request(
            "POST",
            f"/shc/outbreak-investigations/{investigation_id}/reopen",
            headers=headers,
        )

    def close_outbreak(self, investigation_id, headers):
        return self._request(
            "POST",
            f"/shc/outbreak-investigations/{investigation_id}/close",
            headers=headers,
        )

    # --- Billing ---
    def create_invoice(self, encounter_id, payload, headers):
        return self._request(
            "POST", f"/shc/encounters/{encounter_id}/invoice", payload, headers
        )

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/shc/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/shc/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/shc/invoices/{invoice_id}/issue", headers=headers
        )

    def create_payment(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/shc/invoices/{invoice_id}/payments", payload, headers
        )

    def void_payment(self, payment_id, headers):
        return self._request("POST", f"/shc/payments/{payment_id}/void", headers=headers)

    def list_invoice_payments(self, invoice_id, headers):
        return self._request(
            "GET", f"/shc/invoices/{invoice_id}/payments", headers=headers
        )

    # --- After-hours referral ---
    def create_referral(self, encounter_id, payload, headers):
        return self._request(
            "POST", f"/shc/encounters/{encounter_id}/referrals", payload, headers
        )

    def accept_referral(self, referral_id, headers):
        return self._request(
            "POST", f"/shc/referrals/{referral_id}/accept", headers=headers
        )

    def list_encounter_referrals(self, encounter_id, headers):
        return self._request(
            "GET", f"/shc/encounters/{encounter_id}/referrals", headers=headers
        )

    # --- Health fee funding ---
    def create_health_fee_pool(self, payload, headers):
        return self._request("POST", "/shc/health-fee-pools", payload, headers)

    def list_health_fee_pools(self, headers, params=None):
        return self._request(
            "GET", "/shc/health-fee-pools", headers=headers, params=params
        )


api_client = ApiClient()
