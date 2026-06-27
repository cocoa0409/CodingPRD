"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Provider ---------------------------------------------------------
    def create_provider(self, payload, headers):
        return self._request("POST", "/aesthetics/providers", payload, headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/aesthetics/providers", headers=headers, params=params)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/aesthetics/providers/{provider_id}", headers=headers)

    def suspend_provider(self, provider_id, payload, headers):
        return self._request(
            "POST", f"/aesthetics/providers/{provider_id}/suspend", payload, headers
        )

    # ---- MembershipPackage ------------------------------------------------
    def create_membership_package(self, payload, headers):
        return self._request("POST", "/aesthetics/membership-packages", payload, headers)

    def list_membership_packages(self, headers, params=None):
        return self._request(
            "GET", "/aesthetics/membership-packages", headers=headers, params=params
        )

    def get_membership_package(self, membership_id, headers):
        return self._request(
            "GET", f"/aesthetics/membership-packages/{membership_id}", headers=headers
        )

    # ---- InjectableLot ----------------------------------------------------
    def create_injectable_lot(self, payload, headers):
        return self._request("POST", "/aesthetics/injectable-lots", payload, headers)

    def list_injectable_lots(self, headers, params=None):
        return self._request(
            "GET", "/aesthetics/injectable-lots", headers=headers, params=params
        )

    def get_injectable_lot(self, lot_id, headers):
        return self._request("GET", f"/aesthetics/injectable-lots/{lot_id}", headers=headers)

    def quarantine_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/aesthetics/injectable-lots/{lot_id}/quarantine", payload, headers
        )

    # ---- Patient ----------------------------------------------------------
    def create_patient(self, payload, headers):
        return self._request("POST", "/aesthetics/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/aesthetics/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/aesthetics/patients/{patient_id}", headers=headers)

    # ---- LoyaltyAccount ---------------------------------------------------
    def create_loyalty_account(self, payload, headers):
        return self._request("POST", "/aesthetics/loyalty-accounts", payload, headers)

    def list_loyalty_accounts(self, headers, params=None):
        return self._request(
            "GET", "/aesthetics/loyalty-accounts", headers=headers, params=params
        )

    def get_loyalty_account(self, account_id, headers):
        return self._request(
            "GET", f"/aesthetics/loyalty-accounts/{account_id}", headers=headers
        )

    # ---- Consultation -----------------------------------------------------
    def create_consultation(self, payload, headers):
        return self._request("POST", "/aesthetics/consultations", payload, headers)

    def list_consultations(self, headers, params=None):
        return self._request("GET", "/aesthetics/consultations", headers=headers, params=params)

    def get_consultation(self, consultation_id, headers):
        return self._request(
            "GET", f"/aesthetics/consultations/{consultation_id}", headers=headers
        )

    def complete_exam(self, consultation_id, headers, payload=None):
        return self._request(
            "POST", f"/aesthetics/consultations/{consultation_id}/complete-exam",
            payload if payload is not None else {}, headers,
        )

    def void_consultation(self, consultation_id, headers, payload=None):
        return self._request(
            "POST", f"/aesthetics/consultations/{consultation_id}/void",
            payload if payload is not None else {}, headers,
        )

    # ---- StandingOrder ----------------------------------------------------
    def create_standing_order(self, payload, headers):
        return self._request("POST", "/aesthetics/standing-orders", payload, headers)

    def list_standing_orders(self, headers, params=None):
        return self._request("GET", "/aesthetics/standing-orders", headers=headers, params=params)

    def get_standing_order(self, order_id, headers):
        return self._request("GET", f"/aesthetics/standing-orders/{order_id}", headers=headers)

    def revoke_standing_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/aesthetics/standing-orders/{order_id}/revoke", payload, headers
        )

    # ---- ConsentPhoto -----------------------------------------------------
    def create_consent_photo(self, payload, headers):
        return self._request("POST", "/aesthetics/consent-photos", payload, headers)

    def list_consent_photos(self, headers, params=None):
        return self._request("GET", "/aesthetics/consent-photos", headers=headers, params=params)

    def get_consent_photo(self, photo_id, headers):
        return self._request("GET", f"/aesthetics/consent-photos/{photo_id}", headers=headers)

    # ---- TreatmentPlan ----------------------------------------------------
    def create_treatment_plan(self, payload, headers):
        return self._request("POST", "/aesthetics/treatment-plans", payload, headers)

    def list_treatment_plans(self, headers, params=None):
        return self._request("GET", "/aesthetics/treatment-plans", headers=headers, params=params)

    def get_treatment_plan(self, plan_id, headers):
        return self._request("GET", f"/aesthetics/treatment-plans/{plan_id}", headers=headers)

    def activate_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/aesthetics/treatment-plans/{plan_id}/activate", payload, headers
        )

    def complete_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/aesthetics/treatment-plans/{plan_id}/complete", payload, headers
        )

    def cancel_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/aesthetics/treatment-plans/{plan_id}/cancel", payload, headers
        )

    # ---- Deposit ----------------------------------------------------------
    def create_deposit(self, payload, headers):
        return self._request("POST", "/aesthetics/deposits", payload, headers)

    def list_deposits(self, headers, params=None):
        return self._request("GET", "/aesthetics/deposits", headers=headers, params=params)

    def get_deposit(self, deposit_id, headers):
        return self._request("GET", f"/aesthetics/deposits/{deposit_id}", headers=headers)

    # ---- TreatmentSession -------------------------------------------------
    def create_treatment_session(self, payload, headers):
        return self._request("POST", "/aesthetics/treatment-sessions", payload, headers)

    def list_treatment_sessions(self, headers, params=None):
        return self._request(
            "GET", "/aesthetics/treatment-sessions", headers=headers, params=params
        )

    def get_treatment_session(self, session_id, headers):
        return self._request(
            "GET", f"/aesthetics/treatment-sessions/{session_id}", headers=headers
        )

    def commit_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"/aesthetics/treatment-sessions/{session_id}/commit", payload, headers
        )

    def resolve_session(self, session_id, headers, payload=None):
        return self._request(
            "POST", f"/aesthetics/treatment-sessions/{session_id}/resolve",
            payload if payload is not None else {}, headers,
        )

    def cancel_session(self, session_id, headers, payload=None):
        return self._request(
            "POST", f"/aesthetics/treatment-sessions/{session_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    def no_show_session(self, session_id, headers, payload=None):
        return self._request(
            "POST", f"/aesthetics/treatment-sessions/{session_id}/no-show",
            payload if payload is not None else {}, headers,
        )

    # ---- ComplicationCase -------------------------------------------------
    def create_complication_case(self, payload, headers):
        return self._request("POST", "/aesthetics/complication-cases", payload, headers)

    def list_complication_cases(self, headers, params=None):
        return self._request(
            "GET", "/aesthetics/complication-cases", headers=headers, params=params
        )

    def get_complication_case(self, case_id, headers):
        return self._request(
            "GET", f"/aesthetics/complication-cases/{case_id}", headers=headers
        )

    def open_touchup(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"/aesthetics/complication-cases/{case_id}/open-touchup",
            payload if payload is not None else {}, headers,
        )

    def touchup_failed(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"/aesthetics/complication-cases/{case_id}/touchup-failed",
            payload if payload is not None else {}, headers,
        )

    def resolve_complication(self, case_id, payload, headers):
        return self._request(
            "POST", f"/aesthetics/complication-cases/{case_id}/resolve", payload, headers
        )


api_client = ApiClient()
