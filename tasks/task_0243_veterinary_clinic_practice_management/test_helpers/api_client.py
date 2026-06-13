"""API client: one method per endpoint defined in the PRD.

Subclasses GenericApiClient; the base _request() is inherited. Every path is
mounted under the /clinic prefix per the endpoint surface in Section 4.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Operatory ----
    def create_operatory(self, payload, headers):
        return self._request("POST", "/clinic/operatories", payload, headers)

    def list_operatories(self, headers, params=None):
        return self._request("GET", "/clinic/operatories", headers=headers, params=params)

    def get_operatory(self, oid, headers):
        return self._request("GET", f"/clinic/operatories/{oid}", headers=headers)

    # ---- Kennel ----
    def create_kennel(self, payload, headers):
        return self._request("POST", "/clinic/kennels", payload, headers)

    def list_kennels(self, headers, params=None):
        return self._request("GET", "/clinic/kennels", headers=headers, params=params)

    def get_kennel(self, kid, headers):
        return self._request("GET", f"/clinic/kennels/{kid}", headers=headers)

    # ---- Household ----
    def create_household(self, payload, headers):
        return self._request("POST", "/clinic/households", payload, headers)

    def list_households(self, headers, params=None):
        return self._request("GET", "/clinic/households", headers=headers, params=params)

    def get_household(self, hid, headers):
        return self._request("GET", f"/clinic/households/{hid}", headers=headers)

    # ---- Deposit ----
    def create_deposit(self, payload, headers):
        return self._request("POST", "/clinic/deposits", payload, headers)

    # ---- Owner ----
    def create_owner(self, payload, headers):
        return self._request("POST", "/clinic/owners", payload, headers)

    def list_owners(self, headers, params=None):
        return self._request("GET", "/clinic/owners", headers=headers, params=params)

    def get_owner(self, ownerid, headers):
        return self._request("GET", f"/clinic/owners/{ownerid}", headers=headers)

    # ---- Patient ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/clinic/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/clinic/patients", headers=headers, params=params)

    def get_patient(self, pid, headers):
        return self._request("GET", f"/clinic/patients/{pid}", headers=headers)

    def deactivate_patient(self, pid, headers):
        return self._request("POST", f"/clinic/patients/{pid}/deactivate", headers=headers)

    def mark_patient_deceased(self, pid, headers):
        return self._request("POST", f"/clinic/patients/{pid}/mark-deceased", headers=headers)

    # ---- WellnessPlan ----
    def create_wellness_plan(self, payload, headers):
        return self._request("POST", "/clinic/wellness-plans", payload, headers)

    def list_wellness_plans(self, headers, params=None):
        return self._request("GET", "/clinic/wellness-plans", headers=headers, params=params)

    def get_wellness_plan(self, wpid, headers):
        return self._request("GET", f"/clinic/wellness-plans/{wpid}", headers=headers)

    # ---- Appointment ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/clinic/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/clinic/appointments", headers=headers, params=params)

    def get_appointment(self, aid, headers):
        return self._request("GET", f"/clinic/appointments/{aid}", headers=headers)

    def transition_appointment(self, aid, payload, headers):
        return self._request("POST", f"/clinic/appointments/{aid}/transition", payload, headers)

    # ---- Vaccination ----
    def create_vaccination(self, payload, headers):
        return self._request("POST", "/clinic/vaccinations", payload, headers)

    def list_vaccinations(self, headers, params=None):
        return self._request("GET", "/clinic/vaccinations", headers=headers, params=params)

    def get_vaccination(self, vid, headers):
        return self._request("GET", f"/clinic/vaccinations/{vid}", headers=headers)

    # ---- Prescription ----
    def create_prescription(self, payload, headers):
        return self._request("POST", "/clinic/prescriptions", payload, headers)

    def list_prescriptions(self, headers, params=None):
        return self._request("GET", "/clinic/prescriptions", headers=headers, params=params)

    def get_prescription(self, rxid, headers):
        return self._request("GET", f"/clinic/prescriptions/{rxid}", headers=headers)

    def refill_prescription(self, rxid, headers):
        return self._request("POST", f"/clinic/prescriptions/{rxid}/refill", headers=headers)

    # ---- Estimate ----
    def create_estimate(self, payload, headers):
        return self._request("POST", "/clinic/estimates", payload, headers)

    def list_estimates(self, headers, params=None):
        return self._request("GET", "/clinic/estimates", headers=headers, params=params)

    def get_estimate(self, eid, headers):
        return self._request("GET", f"/clinic/estimates/{eid}", headers=headers)

    def transition_estimate(self, eid, payload, headers):
        return self._request("POST", f"/clinic/estimates/{eid}/transition", payload, headers)

    # ---- Surgery ----
    def create_surgery(self, payload, headers):
        return self._request("POST", "/clinic/surgeries", payload, headers)

    def list_surgeries(self, headers, params=None):
        return self._request("GET", "/clinic/surgeries", headers=headers, params=params)

    def get_surgery(self, sid, headers):
        return self._request("GET", f"/clinic/surgeries/{sid}", headers=headers)

    def transition_surgery(self, sid, payload, headers):
        return self._request("POST", f"/clinic/surgeries/{sid}/transition", payload, headers)

    # ---- BoardingStay ----
    def create_boarding_stay(self, payload, headers):
        return self._request("POST", "/clinic/boarding-stays", payload, headers)

    def list_boarding_stays(self, headers, params=None):
        return self._request("GET", "/clinic/boarding-stays", headers=headers, params=params)

    def get_boarding_stay(self, bid, headers):
        return self._request("GET", f"/clinic/boarding-stays/{bid}", headers=headers)

    def transition_boarding_stay(self, bid, payload, headers):
        return self._request("POST", f"/clinic/boarding-stays/{bid}/transition", payload, headers)

    # ---- LabOrder ----
    def create_lab_order(self, payload, headers):
        return self._request("POST", "/clinic/lab-orders", payload, headers)

    def list_lab_orders(self, headers, params=None):
        return self._request("GET", "/clinic/lab-orders", headers=headers, params=params)

    def get_lab_order(self, loid, headers):
        return self._request("GET", f"/clinic/lab-orders/{loid}", headers=headers)

    def transition_lab_order(self, loid, payload, headers):
        return self._request("POST", f"/clinic/lab-orders/{loid}/transition", payload, headers)

    # ---- Invoice ----
    def create_invoice(self, payload, headers):
        return self._request("POST", "/clinic/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/clinic/invoices", headers=headers, params=params)

    def get_invoice(self, invid, headers):
        return self._request("GET", f"/clinic/invoices/{invid}", headers=headers)


api_client = ApiClient()
