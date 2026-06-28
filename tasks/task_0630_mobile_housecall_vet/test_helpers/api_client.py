"""API client: one method per endpoint defined in the PRD.

Subclasses the framework GenericApiClient; the base _request() does envelope
handling, base-url resolution and JSON serialization.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- ServiceArea ----
    def create_service_area(self, payload, headers):
        return self._request("POST", "/service-areas", payload, headers)

    def list_service_areas(self, headers, params=None):
        return self._request("GET", "/service-areas", headers=headers, params=params)

    def get_service_area(self, area_id, headers):
        return self._request("GET", f"/service-areas/{area_id}", headers=headers)

    def suspend_service_area(self, area_id, headers):
        return self._request("POST", f"/service-areas/{area_id}/suspend", {}, headers)

    # ---- Clinician ----
    def create_clinician(self, payload, headers):
        return self._request("POST", "/clinicians", payload, headers)

    def list_clinicians(self, headers, params=None):
        return self._request("GET", "/clinicians", headers=headers, params=params)

    def get_clinician(self, clinician_id, headers):
        return self._request("GET", f"/clinicians/{clinician_id}", headers=headers)

    def list_clinician_controlled_logs(self, clinician_id, headers, params=None):
        return self._request(
            "GET", f"/clinicians/{clinician_id}/controlled-logs", headers=headers, params=params
        )

    # ---- RollingClinic ----
    def create_rolling_clinic(self, payload, headers):
        return self._request("POST", "/rolling-clinics", payload, headers)

    def list_rolling_clinics(self, headers, params=None):
        return self._request("GET", "/rolling-clinics", headers=headers, params=params)

    def get_rolling_clinic(self, clinic_id, headers):
        return self._request("GET", f"/rolling-clinics/{clinic_id}", headers=headers)

    def patch_rolling_clinic(self, clinic_id, payload, headers):
        return self._request("PATCH", f"/rolling-clinics/{clinic_id}", payload, headers)

    def list_vehicle_controlled_logs(self, clinic_id, headers, params=None):
        return self._request(
            "GET", f"/rolling-clinics/{clinic_id}/controlled-logs", headers=headers, params=params
        )

    # ---- Patient ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    # ---- Appointment ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def arrive_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/arrive", {}, headers)

    def complete_visit(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/complete-visit", {}, headers)

    def refer_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/appointments/{appointment_id}/refer", payload, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/cancel", {}, headers)

    def create_euthanasia_log(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/euthanasia-log", payload, headers
        )

    def list_euthanasia_log(self, appointment_id, headers, params=None):
        return self._request(
            "GET", f"/appointments/{appointment_id}/euthanasia-log", headers=headers, params=params
        )

    # ---- RouteDay / RouteStop ----
    def create_route_day(self, payload, headers):
        return self._request("POST", "/route-days", payload, headers)

    def list_route_days(self, headers, params=None):
        return self._request("GET", "/route-days", headers=headers, params=params)

    def get_route_day(self, route_day_id, headers):
        return self._request("GET", f"/route-days/{route_day_id}", headers=headers)

    def create_stop(self, route_day_id, payload, headers):
        return self._request("POST", f"/route-days/{route_day_id}/stops", payload, headers)

    def list_stops_on_route(self, route_day_id, headers, params=None):
        return self._request(
            "GET", f"/route-days/{route_day_id}/stops", headers=headers, params=params
        )

    def list_route_stops(self, headers, params=None):
        return self._request("GET", "/route-stops", headers=headers, params=params)

    def get_route_stop(self, stop_id, headers):
        return self._request("GET", f"/route-stops/{stop_id}", headers=headers)

    def lock_route_day(self, route_day_id, headers):
        return self._request("POST", f"/route-days/{route_day_id}/lock", {}, headers)

    def reconcile_route_day(self, route_day_id, headers):
        return self._request("POST", f"/route-days/{route_day_id}/reconcile", {}, headers)

    # ---- Estimate / Payment ----
    def create_estimate(self, payload, headers):
        return self._request("POST", "/estimates", payload, headers)

    def get_estimate(self, estimate_id, headers):
        return self._request("GET", f"/estimates/{estimate_id}", headers=headers)

    def list_estimates(self, headers, params=None):
        return self._request("GET", "/estimates", headers=headers, params=params)

    def revise_estimate(self, estimate_id, payload, headers):
        return self._request("PUT", f"/estimates/{estimate_id}", payload, headers)

    def approve_estimate(self, estimate_id, headers):
        return self._request("POST", f"/estimates/{estimate_id}/approve", {}, headers)

    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    # ---- SpecimenPickup ----
    def create_specimen_pickup(self, payload, headers):
        return self._request("POST", "/specimen-pickups", payload, headers)

    def list_specimen_pickups(self, headers, params=None):
        return self._request("GET", "/specimen-pickups", headers=headers, params=params)

    def get_specimen_pickup(self, spec_id, headers):
        return self._request("GET", f"/specimen-pickups/{spec_id}", headers=headers)

    def transit_specimen(self, spec_id, headers):
        return self._request("POST", f"/specimen-pickups/{spec_id}/transit", {}, headers)

    def deliver_specimen(self, spec_id, headers):
        return self._request("POST", f"/specimen-pickups/{spec_id}/deliver", {}, headers)

    # ---- WellnessPlan ----
    def create_wellness_plan(self, payload, headers):
        return self._request("POST", "/wellness-plans", payload, headers)

    def list_wellness_plans(self, headers, params=None):
        return self._request("GET", "/wellness-plans", headers=headers, params=params)

    def get_wellness_plan(self, plan_id, headers):
        return self._request("GET", f"/wellness-plans/{plan_id}", headers=headers)

    def pause_wellness_plan(self, plan_id, headers):
        return self._request("POST", f"/wellness-plans/{plan_id}/pause", {}, headers)

    def resume_wellness_plan(self, plan_id, headers):
        return self._request("POST", f"/wellness-plans/{plan_id}/resume", {}, headers)

    def end_wellness_plan(self, plan_id, headers):
        return self._request("POST", f"/wellness-plans/{plan_id}/end", {}, headers)

    # ---- Referral ----
    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def acknowledge_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/acknowledge", {}, headers)

    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
