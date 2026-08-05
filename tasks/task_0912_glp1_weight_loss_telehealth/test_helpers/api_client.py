"""API client: one method per endpoint defined in the PRD.

Every resource lives directly under the ``/glp1`` prefix; relationships are
carried by identifier fields on the resources rather than by nested paths.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/glp1"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_current_utc(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Patients
    # ------------------------------------------------------------------
    def create_patient(self, payload, headers):
        return self._request("POST", f"{PREFIX}/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"{PREFIX}/patients/{patient_id}", headers=headers)

    def update_patient_vitals(self, patient_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/patients/{patient_id}/vitals", payload, headers
        )

    # ------------------------------------------------------------------
    # Providers and pharmacies
    # ------------------------------------------------------------------
    def create_provider(self, payload, headers):
        return self._request("POST", f"{PREFIX}/providers", payload, headers)

    def create_pharmacy(self, payload, headers):
        return self._request("POST", f"{PREFIX}/pharmacies", payload, headers)

    # ------------------------------------------------------------------
    # Supply lots
    # ------------------------------------------------------------------
    def create_supply_lot(self, payload, headers):
        return self._request("POST", f"{PREFIX}/supply-lots", payload, headers)

    def get_supply_lot(self, supply_lot_id, headers):
        return self._request("GET", f"{PREFIX}/supply-lots/{supply_lot_id}", headers=headers)

    def list_supply_lots(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/supply-lots", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Eligibility screenings
    # ------------------------------------------------------------------
    def create_screening(self, payload, headers):
        return self._request("POST", f"{PREFIX}/screenings", payload, headers)

    def get_screening(self, screening_id, headers):
        return self._request("GET", f"{PREFIX}/screenings/{screening_id}", headers=headers)

    def list_screenings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/screenings", headers=headers, params=params)

    def submit_screening(self, screening_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/screenings/{screening_id}/submit", payload, headers
        )

    # ------------------------------------------------------------------
    # Consults
    # ------------------------------------------------------------------
    def create_consult(self, payload, headers):
        return self._request("POST", f"{PREFIX}/consults", payload, headers)

    def get_consult(self, consult_id, headers):
        return self._request("GET", f"{PREFIX}/consults/{consult_id}", headers=headers)

    def list_consults(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/consults", headers=headers, params=params)

    def complete_consult(self, consult_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/consults/{consult_id}/complete", payload, headers
        )

    def reschedule_consult(self, consult_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/consults/{consult_id}/reschedule", payload, headers
        )

    # ------------------------------------------------------------------
    # Prescriptions
    # ------------------------------------------------------------------
    def create_prescription(self, payload, headers):
        return self._request("POST", f"{PREFIX}/prescriptions", payload, headers)

    def get_prescription(self, prescription_id, headers):
        return self._request(
            "GET", f"{PREFIX}/prescriptions/{prescription_id}", headers=headers
        )

    def list_prescriptions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/prescriptions", headers=headers, params=params)

    def discontinue_prescription(self, prescription_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/prescriptions/{prescription_id}/discontinue", payload, headers
        )

    def request_refill(self, prescription_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/prescriptions/{prescription_id}/request-refill",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Titration steps
    # ------------------------------------------------------------------
    def get_titration_step(self, titration_step_id, headers):
        return self._request(
            "GET", f"{PREFIX}/titration-steps/{titration_step_id}", headers=headers
        )

    def list_titration_steps(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/titration-steps", headers=headers, params=params
        )

    def escalate_titration_step(self, titration_step_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/titration-steps/{titration_step_id}/escalate", payload, headers
        )

    def hold_titration_step(self, titration_step_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/titration-steps/{titration_step_id}/hold", payload, headers
        )

    def reduce_titration_step(self, titration_step_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/titration-steps/{titration_step_id}/reduce", payload, headers
        )

    # ------------------------------------------------------------------
    # Prior authorizations
    # ------------------------------------------------------------------
    def create_prior_authorization(self, payload, headers):
        return self._request("POST", f"{PREFIX}/prior-authorizations", payload, headers)

    def get_prior_authorization(self, prior_authorization_id, headers):
        return self._request(
            "GET", f"{PREFIX}/prior-authorizations/{prior_authorization_id}", headers=headers
        )

    def list_prior_authorizations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/prior-authorizations", headers=headers, params=params
        )

    def decide_prior_authorization(self, prior_authorization_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/prior-authorizations/{prior_authorization_id}/decide",
            payload,
            headers,
        )

    def appeal_prior_authorization(self, prior_authorization_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/prior-authorizations/{prior_authorization_id}/appeal",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Pharmacy orders
    # ------------------------------------------------------------------
    def create_pharmacy_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/pharmacy-orders", payload, headers)

    def get_pharmacy_order(self, pharmacy_order_id, headers):
        return self._request(
            "GET", f"{PREFIX}/pharmacy-orders/{pharmacy_order_id}", headers=headers
        )

    def list_pharmacy_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/pharmacy-orders", headers=headers, params=params
        )

    def reserve_pharmacy_order(self, pharmacy_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/pharmacy-orders/{pharmacy_order_id}/reserve", payload, headers
        )

    def ship_pharmacy_order(self, pharmacy_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/pharmacy-orders/{pharmacy_order_id}/ship", payload, headers
        )

    def cancel_pharmacy_order(self, pharmacy_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/pharmacy-orders/{pharmacy_order_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------
    def create_subscription(self, payload, headers):
        return self._request("POST", f"{PREFIX}/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request(
            "GET", f"{PREFIX}/subscriptions/{subscription_id}", headers=headers
        )

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/subscriptions", headers=headers, params=params)

    def pause_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/subscriptions/{subscription_id}/pause", payload, headers
        )

    def resume_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/subscriptions/{subscription_id}/resume", payload, headers
        )

    def cancel_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/subscriptions/{subscription_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------
    # Billing cycles
    # ------------------------------------------------------------------
    def get_billing_cycle(self, billing_cycle_id, headers):
        return self._request(
            "GET", f"{PREFIX}/billing-cycles/{billing_cycle_id}", headers=headers
        )

    def list_billing_cycles(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/billing-cycles", headers=headers, params=params)

    def invoice_billing_cycle(self, billing_cycle_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/billing-cycles/{billing_cycle_id}/invoice", payload, headers
        )

    def settle_billing_cycle(self, billing_cycle_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/billing-cycles/{billing_cycle_id}/settle", payload, headers
        )

    def void_billing_cycle(self, billing_cycle_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/billing-cycles/{billing_cycle_id}/void", payload, headers
        )

    # ------------------------------------------------------------------
    # Check-ins
    # ------------------------------------------------------------------
    def create_check_in(self, payload, headers):
        return self._request("POST", f"{PREFIX}/check-ins", payload, headers)

    def get_check_in(self, check_in_id, headers):
        return self._request("GET", f"{PREFIX}/check-ins/{check_in_id}", headers=headers)

    def list_check_ins(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/check-ins", headers=headers, params=params)

    def triage_check_in(self, check_in_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/check-ins/{check_in_id}/triage", payload, headers
        )

    def resolve_check_in(self, check_in_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/check-ins/{check_in_id}/resolve", payload, headers
        )

    # ------------------------------------------------------------------
    # Coaching sessions
    # ------------------------------------------------------------------
    def create_coaching_session(self, payload, headers):
        return self._request("POST", f"{PREFIX}/coaching-sessions", payload, headers)

    def get_coaching_session(self, coaching_session_id, headers):
        return self._request(
            "GET", f"{PREFIX}/coaching-sessions/{coaching_session_id}", headers=headers
        )

    def list_coaching_sessions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/coaching-sessions", headers=headers, params=params
        )

    def complete_coaching_session(self, coaching_session_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/coaching-sessions/{coaching_session_id}/complete",
            payload,
            headers,
        )

    def cancel_coaching_session(self, coaching_session_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/coaching-sessions/{coaching_session_id}/cancel",
            payload,
            headers,
        )


api_client = ApiClient()
