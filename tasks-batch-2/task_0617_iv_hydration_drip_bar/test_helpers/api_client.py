"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ---- InfusionMenuItem ----
    def create_menu_item(self, payload, headers):
        return self._request("POST", "/menu-items", payload, headers)

    def get_menu_item(self, item_id, headers):
        return self._request("GET", f"/menu-items/{item_id}", headers=headers)

    def list_menu_items(self, headers, params=None):
        return self._request("GET", "/menu-items", headers=headers, params=params)

    # ---- AddOn ----
    def create_add_on(self, payload, headers):
        return self._request("POST", "/add-ons", payload, headers)

    def list_add_ons(self, headers, params=None):
        return self._request("GET", "/add-ons", headers=headers, params=params)

    # ---- Patient ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    # ---- Membership ----
    def create_membership(self, payload, headers):
        return self._request("POST", "/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def suspend_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/suspend", {}, headers)

    def reinstate_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/reinstate", {}, headers)

    def list_patient_memberships(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}/memberships", headers=headers)

    # ---- StandingOrder ----
    def create_standing_order(self, payload, headers):
        return self._request("POST", "/standing-orders", payload, headers)

    def get_standing_order(self, order_id, headers):
        return self._request("GET", f"/standing-orders/{order_id}", headers=headers)

    def list_standing_orders(self, headers, params=None):
        return self._request("GET", "/standing-orders", headers=headers, params=params)

    def activate_standing_order(self, order_id, headers):
        return self._request("POST", f"/standing-orders/{order_id}/activate", {}, headers)

    def revoke_standing_order(self, order_id, headers):
        return self._request("POST", f"/standing-orders/{order_id}/revoke", {}, headers)

    # ---- Nurse ----
    def create_nurse(self, payload, headers):
        return self._request("POST", "/nurses", payload, headers)

    def get_nurse(self, nurse_id, headers):
        return self._request("GET", f"/nurses/{nurse_id}", headers=headers)

    def list_lounge_nurses(self, lounge_id, headers):
        return self._request("GET", f"/lounges/{lounge_id}/nurses", headers=headers)

    # ---- Lounge ----
    def create_lounge(self, payload, headers):
        return self._request("POST", "/lounges", payload, headers)

    def get_lounge(self, lounge_id, headers):
        return self._request("GET", f"/lounges/{lounge_id}", headers=headers)

    # ---- SupplyLot ----
    def create_supply_lot(self, payload, headers):
        return self._request("POST", "/supply-lots", payload, headers)

    def get_supply_lot(self, lot_id, headers):
        return self._request("GET", f"/supply-lots/{lot_id}", headers=headers)

    def list_supply_lots(self, headers, params=None):
        return self._request("GET", "/supply-lots", headers=headers, params=params)

    def quarantine_supply_lot(self, lot_id, headers):
        return self._request("POST", f"/supply-lots/{lot_id}/quarantine", {}, headers)

    # ---- DispatchRoute ----
    def create_dispatch_route(self, payload, headers):
        return self._request("POST", "/dispatch-routes", payload, headers)

    def get_dispatch_route(self, route_id, headers):
        return self._request("GET", f"/dispatch-routes/{route_id}", headers=headers)

    def list_nurse_dispatch_routes(self, nurse_id, headers, params=None):
        return self._request("GET", f"/nurses/{nurse_id}/dispatch-routes",
                             headers=headers, params=params)

    def lock_dispatch_route(self, route_id, headers):
        return self._request("POST", f"/dispatch-routes/{route_id}/lock", {}, headers)

    def close_dispatch_route(self, route_id, headers):
        return self._request("POST", f"/dispatch-routes/{route_id}/close", {}, headers)

    # ---- Appointment ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def intake_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/appointments/{appointment_id}/intake", payload, headers)

    def schedule_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/appointments/{appointment_id}/schedule", payload, headers)

    def md_approve_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/appointments/{appointment_id}/md-approve", payload, headers)

    def md_decline_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/md-decline", {}, headers)

    def dispatch_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/appointments/{appointment_id}/dispatch", payload, headers)

    def start_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/start", {}, headers)

    def complete_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/complete", {}, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/cancel", {}, headers)

    # ---- IntakeScreening ----
    def get_intake_screening(self, screening_id, headers):
        return self._request("GET", f"/intake-screenings/{screening_id}", headers=headers)

    def list_appointment_intake_screenings(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}/intake-screenings",
                             headers=headers)

    # ---- Consent ----
    def create_consent(self, payload, headers):
        return self._request("POST", "/consents", payload, headers)

    def get_consent(self, consent_id, headers):
        return self._request("GET", f"/consents/{consent_id}", headers=headers)

    def revoke_consent(self, consent_id, headers):
        return self._request("POST", f"/consents/{consent_id}/revoke", {}, headers)

    def list_appointment_consents(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}/consents", headers=headers)

    # ---- AdverseEvent ----
    def create_adverse_event(self, payload, headers):
        return self._request("POST", "/adverse-events", payload, headers)

    def get_adverse_event(self, event_id, headers):
        return self._request("GET", f"/adverse-events/{event_id}", headers=headers)

    def review_adverse_event(self, event_id, headers):
        return self._request("POST", f"/adverse-events/{event_id}/review", {}, headers)

    def resolve_adverse_event(self, event_id, headers):
        return self._request("POST", f"/adverse-events/{event_id}/resolve", {}, headers)

    def list_appointment_adverse_events(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}/adverse-events",
                             headers=headers)


api_client = ApiClient()
