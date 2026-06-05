"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Configuration: Breed / ServiceTier / AddOn / Van ----
    def create_breed(self, payload, headers):
        return self._request("POST", "/breeds", payload, headers)

    def get_breed(self, breed_id, headers):
        return self._request("GET", f"/breeds/{breed_id}", headers=headers)

    def create_service_tier(self, payload, headers):
        return self._request("POST", "/service-tiers", payload, headers)

    def create_add_on(self, payload, headers):
        return self._request("POST", "/add-ons", payload, headers)

    def create_van(self, payload, headers):
        return self._request("POST", "/vans", payload, headers)

    # ---- Customer / Pet / Vaccination ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customer_pets(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/pets", headers=headers, params=params)

    def list_customer_fee_charges(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/fee-charges", headers=headers, params=params)

    def create_pet(self, payload, headers):
        return self._request("POST", "/pets", payload, headers)

    def get_pet(self, pet_id, headers):
        return self._request("GET", f"/pets/{pet_id}", headers=headers)

    def list_pets(self, headers, params=None):
        return self._request("GET", "/pets", headers=headers, params=params)

    def patch_pet(self, pet_id, payload, headers):
        return self._request("PATCH", f"/pets/{pet_id}", payload, headers)

    def list_pet_vaccinations(self, pet_id, headers, params=None):
        return self._request("GET", f"/pets/{pet_id}/vaccinations", headers=headers, params=params)

    def create_vaccination(self, pet_id, payload, headers):
        return self._request("POST", f"/pets/{pet_id}/vaccinations", payload, headers)

    # ---- Groomer ----
    def create_groomer(self, payload, headers):
        return self._request("POST", "/groomers", payload, headers)

    def get_groomer(self, groomer_id, headers):
        return self._request("GET", f"/groomers/{groomer_id}", headers=headers)

    # ---- RouteDay / RouteStop ----
    def create_route_day(self, payload, headers):
        return self._request("POST", "/route-days", payload, headers)

    def get_route_day(self, route_day_id, headers):
        return self._request("GET", f"/route-days/{route_day_id}", headers=headers)

    def list_route_day_stops(self, route_day_id, headers, params=None):
        return self._request("GET", f"/route-days/{route_day_id}/stops", headers=headers, params=params)

    def dispatch_route_day(self, route_day_id, headers):
        return self._request("POST", f"/route-days/{route_day_id}/dispatch", {}, headers)

    def list_route_days(self, headers, params=None):
        return self._request("GET", "/route-days", headers=headers, params=params)

    def get_route_stop(self, route_stop_id, headers):
        return self._request("GET", f"/route-stops/{route_stop_id}", headers=headers)

    def list_route_stops(self, headers, params=None):
        return self._request("GET", "/route-stops", headers=headers, params=params)

    # ---- Appointment lifecycle ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def attach_add_on(self, appointment_id, payload, headers):
        return self._request("POST", f"/appointments/{appointment_id}/add-ons", payload, headers)

    def list_appointment_add_ons(self, appointment_id, headers, params=None):
        return self._request("GET", f"/appointments/{appointment_id}/add-ons", headers=headers, params=params)

    def get_add_on_link(self, link_id, headers):
        return self._request("GET", f"/add-on-links/{link_id}", headers=headers)

    def list_add_on_links(self, headers, params=None):
        return self._request("GET", "/add-on-links", headers=headers, params=params)

    def quote_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/quote", {}, headers)

    def schedule_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/appointments/{appointment_id}/schedule", payload, headers)

    def complete_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/appointments/{appointment_id}/complete", payload, headers)

    def no_show_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/no-show", {}, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/cancel", {}, headers)

    # ---- RecurringPlan ----
    def create_recurring_plan(self, payload, headers):
        return self._request("POST", "/recurring-plans", payload, headers)

    def get_recurring_plan(self, plan_id, headers):
        return self._request("GET", f"/recurring-plans/{plan_id}", headers=headers)

    def list_recurring_plans(self, headers, params=None):
        return self._request("GET", "/recurring-plans", headers=headers, params=params)

    def pause_recurring_plan(self, plan_id, headers):
        return self._request("POST", f"/recurring-plans/{plan_id}/pause", {}, headers)

    def resume_recurring_plan(self, plan_id, headers):
        return self._request("POST", f"/recurring-plans/{plan_id}/resume", {}, headers)

    def cancel_recurring_plan(self, plan_id, headers):
        return self._request("POST", f"/recurring-plans/{plan_id}/cancel", {}, headers)

    def generate_appointment(self, plan_id, headers):
        return self._request("POST", f"/recurring-plans/{plan_id}/generate-appointment", {}, headers)

    # ---- FeeCharge ----
    def get_fee_charge(self, fee_id, headers):
        return self._request("GET", f"/fee-charges/{fee_id}", headers=headers)

    def list_fee_charges(self, headers, params=None):
        return self._request("GET", "/fee-charges", headers=headers, params=params)

    def settle_fee_charge(self, fee_id, headers):
        return self._request("POST", f"/fee-charges/{fee_id}/settle", {}, headers)

    def waive_fee_charge(self, fee_id, headers):
        return self._request("POST", f"/fee-charges/{fee_id}/waive", {}, headers)

    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # Raw request escape hatch (for auth/role negative tests with custom headers).
    def raw(self, method, path, payload=None, headers=None, params=None):
        return self._request(method, path, payload, headers, params)


api_client = ApiClient()
