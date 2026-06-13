"""API client: one method per endpoint defined in the Blood Donation Center PRD.

Subclasses GenericApiClient; the base _request() handles URL construction,
JSON bodies, query params, and returns the raw requests.Response.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Centers & clock ------------------------------------------------
    def create_center(self, payload, headers):
        return self._request("POST", "/blood-bank/centers", payload, headers)

    def list_centers(self, headers, params=None):
        return self._request("GET", "/blood-bank/centers", headers=headers, params=params)

    def get_center(self, center_id, headers):
        return self._request("GET", f"/blood-bank/centers/{center_id}", headers=headers)

    def advance_clock(self, center_id, payload, headers):
        return self._request("POST", f"/blood-bank/centers/{center_id}/clock/advance", payload, headers)

    # ---- Donors ---------------------------------------------------------
    def create_donor(self, payload, headers):
        return self._request("POST", "/blood-bank/donors", payload, headers)

    def list_donors(self, headers, params=None):
        return self._request("GET", "/blood-bank/donors", headers=headers, params=params)

    def get_donor(self, donor_id, headers):
        return self._request("GET", f"/blood-bank/donors/{donor_id}", headers=headers)

    # ---- Deferrals ------------------------------------------------------
    def create_deferral(self, payload, headers):
        return self._request("POST", "/blood-bank/deferrals", payload, headers)

    def list_deferrals(self, headers, params=None):
        return self._request("GET", "/blood-bank/deferrals", headers=headers, params=params)

    def get_deferral(self, deferral_id, headers):
        return self._request("GET", f"/blood-bank/deferrals/{deferral_id}", headers=headers)

    def lift_deferral(self, deferral_id, headers):
        return self._request("POST", f"/blood-bank/deferrals/{deferral_id}/lift", {}, headers)

    # ---- Slots ----------------------------------------------------------
    def create_slot(self, payload, headers):
        return self._request("POST", "/blood-bank/slots", payload, headers)

    def list_slots(self, headers, params=None):
        return self._request("GET", "/blood-bank/slots", headers=headers, params=params)

    def get_slot(self, slot_id, headers):
        return self._request("GET", f"/blood-bank/slots/{slot_id}", headers=headers)

    def close_slot(self, slot_id, headers):
        return self._request("POST", f"/blood-bank/slots/{slot_id}/close", {}, headers)

    # ---- Appointments ---------------------------------------------------
    def create_appointment(self, payload, headers):
        return self._request("POST", "/blood-bank/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/blood-bank/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/blood-bank/appointments/{appointment_id}", headers=headers)

    def check_in_appointment(self, appointment_id, headers):
        return self._request("POST", f"/blood-bank/appointments/{appointment_id}/check-in", {}, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/blood-bank/appointments/{appointment_id}/cancel", {}, headers)

    def no_show_appointment(self, appointment_id, headers):
        return self._request("POST", f"/blood-bank/appointments/{appointment_id}/no-show", {}, headers)

    def create_donation(self, appointment_id, payload, headers):
        return self._request("POST", f"/blood-bank/appointments/{appointment_id}/donations", payload, headers)

    # ---- Health screenings ----------------------------------------------
    def create_health_screening(self, payload, headers):
        return self._request("POST", "/blood-bank/health-screenings", payload, headers)

    def list_health_screenings(self, headers, params=None):
        return self._request("GET", "/blood-bank/health-screenings", headers=headers, params=params)

    def get_health_screening(self, screening_id, headers):
        return self._request("GET", f"/blood-bank/health-screenings/{screening_id}", headers=headers)

    # ---- Donations (reads + test results) -------------------------------
    def list_donations(self, headers, params=None):
        return self._request("GET", "/blood-bank/donations", headers=headers, params=params)

    def get_donation(self, donation_id, headers):
        return self._request("GET", f"/blood-bank/donations/{donation_id}", headers=headers)

    def create_test_result(self, donation_id, payload, headers):
        return self._request("POST", f"/blood-bank/donations/{donation_id}/test-results", payload, headers)

    # ---- Test results ---------------------------------------------------
    def list_test_results(self, headers, params=None):
        return self._request("GET", "/blood-bank/test-results", headers=headers, params=params)

    def get_test_result(self, test_result_id, headers):
        return self._request("GET", f"/blood-bank/test-results/{test_result_id}", headers=headers)

    # ---- Blood units ----------------------------------------------------
    def create_blood_unit(self, payload, headers):
        return self._request("POST", "/blood-bank/blood-units", payload, headers)

    def list_blood_units(self, headers, params=None):
        return self._request("GET", "/blood-bank/blood-units", headers=headers, params=params)

    def get_blood_unit(self, unit_id, headers):
        return self._request("GET", f"/blood-bank/blood-units/{unit_id}", headers=headers)

    def reserve_blood_unit(self, unit_id, headers):
        return self._request("POST", f"/blood-bank/blood-units/{unit_id}/reserve", {}, headers)

    def unreserve_blood_unit(self, unit_id, headers):
        return self._request("POST", f"/blood-bank/blood-units/{unit_id}/unreserve", {}, headers)

    def issue_blood_unit(self, unit_id, headers):
        return self._request("POST", f"/blood-bank/blood-units/{unit_id}/issue", {}, headers)

    # ---- Adverse reactions ----------------------------------------------
    def create_adverse_reaction(self, payload, headers):
        return self._request("POST", "/blood-bank/adverse-reactions", payload, headers)

    def list_adverse_reactions(self, headers, params=None):
        return self._request("GET", "/blood-bank/adverse-reactions", headers=headers, params=params)

    def get_adverse_reaction(self, reaction_id, headers):
        return self._request("GET", f"/blood-bank/adverse-reactions/{reaction_id}", headers=headers)

    # ---- Recall / lookback ----------------------------------------------
    def create_recall_event(self, payload, headers):
        return self._request("POST", "/blood-bank/recall-events", payload, headers)

    def list_recall_events(self, headers, params=None):
        return self._request("GET", "/blood-bank/recall-events", headers=headers, params=params)

    def get_recall_event(self, recall_event_id, headers):
        return self._request("GET", f"/blood-bank/recall-events/{recall_event_id}", headers=headers)

    # ---- Inventory buckets ----------------------------------------------
    def create_inventory_bucket(self, payload, headers):
        return self._request("POST", "/blood-bank/inventory-buckets", payload, headers)

    def list_inventory_buckets(self, headers, params=None):
        return self._request("GET", "/blood-bank/inventory-buckets", headers=headers, params=params)

    def get_inventory_bucket(self, bucket_id, headers):
        return self._request("GET", f"/blood-bank/inventory-buckets/{bucket_id}", headers=headers)


api_client = ApiClient()
