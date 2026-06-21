"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- System clock ---
    def advance_clock(self, by_periods, headers):
        return self._request("POST", "/_clock/advance", {"by_periods": by_periods}, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)

    # --- Driver records ---
    def create_driver_record(self, payload, headers):
        return self._request("POST", "/driver-records", payload, headers)

    def get_driver_record(self, record_id, headers):
        return self._request("GET", f"/driver-records/{record_id}", headers=headers)

    def opt_in(self, record_id, payload, headers):
        return self._request("POST", f"/driver-records/{record_id}/opt-in", payload, headers)

    def real_id_submit(self, record_id, payload, headers):
        return self._request("POST", f"/driver-records/{record_id}/real-id-submit", payload, headers)

    def real_id_adjudicate(self, record_id, payload, headers):
        return self._request("POST", f"/driver-records/{record_id}/real-id-adjudicate", payload, headers)

    def cdl_reinstate(self, record_id, headers):
        return self._request("POST", f"/driver-records/{record_id}/cdl-reinstate", {}, headers)

    def revoke_record(self, record_id, payload, headers):
        return self._request("POST", f"/driver-records/{record_id}/revoke", payload, headers)

    # --- Driver-record sub-resource lists ---
    def list_record_knowledge_tests(self, record_id, headers, params=None):
        return self._request("GET", f"/driver-records/{record_id}/knowledge-tests", headers=headers, params=params)

    def list_record_road_test_appointments(self, record_id, headers, params=None):
        return self._request("GET", f"/driver-records/{record_id}/road-test-appointments", headers=headers, params=params)

    def list_record_licenses(self, record_id, headers, params=None):
        return self._request("GET", f"/driver-records/{record_id}/licenses", headers=headers, params=params)

    def list_record_violations(self, record_id, headers, params=None):
        return self._request("GET", f"/driver-records/{record_id}/violations", headers=headers, params=params)

    def list_record_suspensions(self, record_id, headers, params=None):
        return self._request("GET", f"/driver-records/{record_id}/suspensions", headers=headers, params=params)

    def list_record_cdl_endorsements(self, record_id, headers, params=None):
        return self._request("GET", f"/driver-records/{record_id}/cdl-endorsements", headers=headers, params=params)

    def list_record_medical_cards(self, record_id, headers, params=None):
        return self._request("GET", f"/driver-records/{record_id}/medical-cards", headers=headers, params=params)

    def list_record_fee_payments(self, record_id, headers, params=None):
        return self._request("GET", f"/driver-records/{record_id}/fee-payments", headers=headers, params=params)

    # --- Examiners ---
    def create_examiner(self, payload, headers):
        return self._request("POST", "/examiners", payload, headers)

    def get_examiner(self, examiner_id, headers):
        return self._request("GET", f"/examiners/{examiner_id}", headers=headers)

    def list_examiner_appointments(self, examiner_id, headers, params=None):
        return self._request("GET", f"/examiners/{examiner_id}/road-test-appointments", headers=headers, params=params)

    # --- Knowledge tests ---
    def create_knowledge_test(self, payload, headers):
        return self._request("POST", "/knowledge-tests", payload, headers)

    def grade_knowledge_test(self, test_id, payload, headers):
        return self._request("POST", f"/knowledge-tests/{test_id}/grade", payload, headers)

    def reschedule_knowledge_test(self, test_id, payload, headers):
        return self._request("POST", f"/knowledge-tests/{test_id}/reschedule", payload, headers)

    # --- Road-test appointments ---
    def create_road_test_appointment(self, payload, headers):
        return self._request("POST", "/road-test-appointments", payload, headers)

    def get_road_test_appointment(self, appt_id, headers):
        return self._request("GET", f"/road-test-appointments/{appt_id}", headers=headers)

    def list_appointment_licenses(self, appt_id, headers, params=None):
        return self._request("GET", f"/road-test-appointments/{appt_id}/licenses", headers=headers, params=params)

    def proctor_appointment(self, appt_id, payload, headers):
        return self._request("POST", f"/road-test-appointments/{appt_id}/proctor", payload, headers)

    def score_appointment(self, appt_id, payload, headers):
        return self._request("POST", f"/road-test-appointments/{appt_id}/score", payload, headers)

    def cancel_appointment(self, appt_id, headers):
        return self._request("POST", f"/road-test-appointments/{appt_id}/cancel", {}, headers)

    # --- Licenses ---
    def create_license(self, payload, headers):
        return self._request("POST", "/licenses", payload, headers)

    def renew_license(self, payload, headers):
        return self._request("POST", "/licenses/renew", payload, headers)

    # --- Violations ---
    def create_violation(self, payload, headers):
        return self._request("POST", "/violations", payload, headers)

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/violations/{violation_id}", headers=headers)

    def list_violation_suspensions(self, violation_id, headers, params=None):
        return self._request("GET", f"/violations/{violation_id}/suspensions", headers=headers, params=params)

    def dismiss_violation(self, violation_id, headers):
        return self._request("POST", f"/violations/{violation_id}/dismiss", {}, headers)

    # --- Suspensions ---
    def get_suspension(self, suspension_id, headers):
        return self._request("GET", f"/suspensions/{suspension_id}", headers=headers)

    def dismiss_suspension(self, suspension_id, headers):
        return self._request("POST", f"/suspensions/{suspension_id}/dismiss", {}, headers)

    def reinstate_suspension(self, suspension_id, payload, headers):
        return self._request("POST", f"/suspensions/{suspension_id}/reinstate", payload, headers)

    # --- CDL endorsements ---
    def create_cdl_endorsement(self, payload, headers):
        return self._request("POST", "/cdl-endorsements", payload, headers)

    def withdraw_cdl_endorsement(self, endorsement_id, headers):
        return self._request("POST", f"/cdl-endorsements/{endorsement_id}/withdraw", {}, headers)

    # --- Medical cards ---
    def create_medical_card(self, payload, headers):
        return self._request("POST", "/medical-cards", payload, headers)

    # --- Fee payments ---
    def create_fee_payment(self, payload, headers):
        return self._request("POST", "/fee-payments", payload, headers)


api_client = ApiClient()
