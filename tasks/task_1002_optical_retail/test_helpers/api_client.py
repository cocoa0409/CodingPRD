"""API client: one method per endpoint defined in the PRD (§4). Mounted under /optical."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/optical"


class ApiClient(GenericApiClient):
    # ─── Catalog & configuration ─────────────────────────────────────────────

    def create_insurance_policy(self, payload, headers):
        return self._request("POST", f"{PREFIX}/insurance-policies", payload, headers)

    def get_insurance_policy(self, policy_id, headers):
        return self._request(
            "GET", f"{PREFIX}/insurance-policies/{policy_id}", headers=headers
        )

    def create_store(self, payload, headers):
        return self._request("POST", f"{PREFIX}/stores", payload, headers)

    def create_frame(self, payload, headers):
        return self._request("POST", f"{PREFIX}/frames", payload, headers)

    def get_frame(self, frame_id, headers):
        return self._request("GET", f"{PREFIX}/frames/{frame_id}", headers=headers)

    def list_frame_try_on_kit_items(self, frame_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/frames/{frame_id}/try-on-kit-items",
            headers=headers,
            params=params,
        )

    def create_lens_option(self, payload, headers):
        return self._request("POST", f"{PREFIX}/lens-options", payload, headers)

    def create_customer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"{PREFIX}/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/customers", headers=headers, params=params)

    def set_clock(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers
        )

    # ─── Prescriptions ───────────────────────────────────────────────────────

    def create_prescription(self, payload, headers):
        return self._request("POST", f"{PREFIX}/prescriptions", payload, headers)

    def get_prescription(self, prescription_id, headers):
        return self._request(
            "GET", f"{PREFIX}/prescriptions/{prescription_id}", headers=headers
        )

    def list_customer_prescriptions(self, customer_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/customers/{customer_id}/prescriptions",
            headers=headers,
            params=params,
        )

    def verify_prescription(self, prescription_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/prescriptions/{prescription_id}/verify", payload, headers
        )

    def resubmit_prescription(self, prescription_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/prescriptions/{prescription_id}/resubmit",
            payload,
            headers,
        )

    # ─── Home try-on ─────────────────────────────────────────────────────────

    def create_home_try_on_kit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/home-try-on-kits", payload, headers)

    def get_home_try_on_kit(self, kit_id, headers):
        return self._request(
            "GET", f"{PREFIX}/home-try-on-kits/{kit_id}", headers=headers
        )

    def list_customer_home_try_on_kits(self, customer_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/customers/{customer_id}/home-try-on-kits",
            headers=headers,
            params=params,
        )

    def list_kit_items(self, kit_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/home-try-on-kits/{kit_id}/items",
            headers=headers,
            params=params,
        )

    def ship_home_try_on_kit(self, kit_id, headers):
        return self._request(
            "POST", f"{PREFIX}/home-try-on-kits/{kit_id}/ship", {}, headers
        )

    def return_home_try_on_kit(self, kit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/home-try-on-kits/{kit_id}/return", payload, headers
        )

    # ─── Orders ──────────────────────────────────────────────────────────────

    def create_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/orders", headers=headers, params=params)

    def confirm_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/orders/{order_id}/confirm", payload, headers
        )

    def cancel_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/orders/{order_id}/cancel", payload, headers
        )

    # ─── Lab ─────────────────────────────────────────────────────────────────

    def get_lab_order(self, lab_order_id, headers):
        return self._request(
            "GET", f"{PREFIX}/lab-orders/{lab_order_id}", headers=headers
        )

    def list_lab_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/lab-orders", headers=headers, params=params
        )

    def start_lab_order(self, lab_order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/lab-orders/{lab_order_id}/start", {}, headers
        )

    def qc_lab_order(self, lab_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/lab-orders/{lab_order_id}/qc", payload, headers
        )

    def ship_lab_order(self, lab_order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/lab-orders/{lab_order_id}/ship", {}, headers
        )

    def deliver_lab_order(self, lab_order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/lab-orders/{lab_order_id}/deliver", {}, headers
        )

    # ─── Insurance ───────────────────────────────────────────────────────────

    def create_insurance_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/insurance-claims", payload, headers)

    def get_insurance_claim(self, claim_id, headers):
        return self._request(
            "GET", f"{PREFIX}/insurance-claims/{claim_id}", headers=headers
        )

    def list_insurance_claims(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/insurance-claims", headers=headers, params=params
        )

    def adjudicate_insurance_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/insurance-claims/{claim_id}/adjudicate", payload, headers
        )

    def reimburse_insurance_claim(self, claim_id, headers):
        return self._request(
            "POST", f"{PREFIX}/insurance-claims/{claim_id}/reimburse", {}, headers
        )

    # ─── Warranty ────────────────────────────────────────────────────────────

    def create_warranty_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/warranty-claims", payload, headers)

    def get_warranty_claim(self, warranty_claim_id, headers):
        return self._request(
            "GET", f"{PREFIX}/warranty-claims/{warranty_claim_id}", headers=headers
        )

    def list_warranty_claims(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/warranty-claims", headers=headers, params=params
        )

    def decide_warranty_claim(self, warranty_claim_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/warranty-claims/{warranty_claim_id}/decide",
            payload,
            headers,
        )

    # ─── Exams ───────────────────────────────────────────────────────────────

    def create_exam_appointment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/exam-appointments", payload, headers)

    def get_exam_appointment(self, appointment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/exam-appointments/{appointment_id}", headers=headers
        )

    def list_exam_appointments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/exam-appointments", headers=headers, params=params
        )

    def complete_exam_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/exam-appointments/{appointment_id}/complete",
            payload,
            headers,
        )


api_client = ApiClient()
