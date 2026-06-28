"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() handles
the HTTP envelope and base URL.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Logical clock (test-driving) ──────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ─── Practitioner ──────────────────────────────────────────────────
    def create_practitioner(self, payload, headers):
        return self._request("POST", "/practitioners", payload, headers)

    def list_practitioners(self, headers, params=None):
        return self._request("GET", "/practitioners", headers=headers, params=params)

    def get_practitioner(self, practitioner_id, headers):
        return self._request("GET", f"/practitioners/{practitioner_id}", headers=headers)

    # ─── TreatmentRoom ─────────────────────────────────────────────────
    def create_room(self, payload, headers):
        return self._request("POST", "/rooms", payload, headers)

    def list_rooms(self, headers, params=None):
        return self._request("GET", "/rooms", headers=headers, params=params)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/rooms/{room_id}", headers=headers)

    # ─── HerbItem (inventory) ──────────────────────────────────────────
    def create_herb_item(self, payload, headers):
        return self._request("POST", "/herb-items", payload, headers)

    def list_herb_items(self, headers, params=None):
        return self._request("GET", "/herb-items", headers=headers, params=params)

    def get_herb_item(self, herb_item_id, headers):
        return self._request("GET", f"/herb-items/{herb_item_id}", headers=headers)

    # ─── HerbalFormula ─────────────────────────────────────────────────
    def create_formula(self, payload, headers):
        return self._request("POST", "/formulas", payload, headers)

    def list_formulas(self, headers, params=None):
        return self._request("GET", "/formulas", headers=headers, params=params)

    def get_formula(self, formula_id, headers):
        return self._request("GET", f"/formulas/{formula_id}", headers=headers)

    # ─── Patient ───────────────────────────────────────────────────────
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def set_membership(self, patient_id, payload, headers):
        return self._request("POST", f"/patients/{patient_id}/membership", payload, headers)

    # ─── Intake ────────────────────────────────────────────────────────
    def create_intake(self, payload, headers):
        return self._request("POST", "/intakes", payload, headers)

    def list_intakes(self, headers, params=None):
        return self._request("GET", "/intakes", headers=headers, params=params)

    def get_intake(self, intake_id, headers):
        return self._request("GET", f"/intakes/{intake_id}", headers=headers)

    def finalize_intake(self, intake_id, headers):
        return self._request("POST", f"/intakes/{intake_id}/finalize", {}, headers)

    # ─── TreatmentPlan ─────────────────────────────────────────────────
    def create_treatment_plan(self, payload, headers):
        return self._request("POST", "/treatment-plans", payload, headers)

    def list_treatment_plans(self, headers, params=None):
        return self._request("GET", "/treatment-plans", headers=headers, params=params)

    def get_treatment_plan(self, plan_id, headers):
        return self._request("GET", f"/treatment-plans/{plan_id}", headers=headers)

    def hold_plan(self, plan_id, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/hold", {}, headers)

    def resume_plan(self, plan_id, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/resume", {}, headers)

    def complete_plan(self, plan_id, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/complete", {}, headers)

    def cancel_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/cancel", payload, headers)

    # ─── PackageSeries ─────────────────────────────────────────────────
    def create_package_series(self, payload, headers):
        return self._request("POST", "/package-series", payload, headers)

    def list_package_series(self, headers, params=None):
        return self._request("GET", "/package-series", headers=headers, params=params)

    def get_package_series(self, series_id, headers):
        return self._request("GET", f"/package-series/{series_id}", headers=headers)

    def cancel_package_series(self, series_id, headers):
        return self._request("POST", f"/package-series/{series_id}/cancel", {}, headers)

    # ─── Appointment ───────────────────────────────────────────────────
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def get_appointment(self, appt_id, headers):
        return self._request("GET", f"/appointments/{appt_id}", headers=headers)

    def add_addon(self, appt_id, payload, headers):
        return self._request("POST", f"/appointments/{appt_id}/addons", payload, headers)

    def check_in(self, appt_id, headers):
        return self._request("POST", f"/appointments/{appt_id}/check-in", {}, headers)

    def complete_appointment(self, appt_id, headers):
        return self._request("POST", f"/appointments/{appt_id}/complete", {}, headers)

    def no_show(self, appt_id, headers):
        return self._request("POST", f"/appointments/{appt_id}/no-show", {}, headers)

    def cancel_appointment(self, appt_id, headers):
        return self._request("POST", f"/appointments/{appt_id}/cancel", {}, headers)

    # ─── AddOn (read) ──────────────────────────────────────────────────
    def list_addons(self, headers, params=None):
        return self._request("GET", "/addons", headers=headers, params=params)

    def get_addon(self, addon_id, headers):
        return self._request("GET", f"/addons/{addon_id}", headers=headers)

    # ─── Charge (read) ─────────────────────────────────────────────────
    def list_charges(self, headers, params=None):
        return self._request("GET", "/charges", headers=headers, params=params)

    def get_charge(self, charge_id, headers):
        return self._request("GET", f"/charges/{charge_id}", headers=headers)

    # ─── Superbill (read) ──────────────────────────────────────────────
    def list_superbills(self, headers, params=None):
        return self._request("GET", "/superbills", headers=headers, params=params)

    def get_superbill(self, superbill_id, headers):
        return self._request("GET", f"/superbills/{superbill_id}", headers=headers)

    # ─── FormulaDispense ───────────────────────────────────────────────
    def create_dispense(self, payload, headers):
        return self._request("POST", "/dispenses", payload, headers)

    def list_dispenses(self, headers, params=None):
        return self._request("GET", "/dispenses", headers=headers, params=params)

    def get_dispense(self, dispense_id, headers):
        return self._request("GET", f"/dispenses/{dispense_id}", headers=headers)

    def fill_dispense(self, dispense_id, headers):
        return self._request("POST", f"/dispenses/{dispense_id}/fill", {}, headers)

    def reverse_dispense(self, dispense_id, payload, headers):
        return self._request("POST", f"/dispenses/{dispense_id}/reverse", payload, headers)


api_client = ApiClient()
