"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Tugs ─────────────────────────────────────────
    def create_tug(self, payload, headers):
        return self._request("POST", "/api/tugs", payload, headers)

    def list_tugs(self, headers, params=None):
        return self._request("GET", "/api/tugs", headers=headers, params=params)

    def get_tug(self, tug_id, headers):
        return self._request("GET", f"/api/tugs/{tug_id}", headers=headers)

    # ─── Vessels ──────────────────────────────────────
    def create_vessel(self, payload, headers):
        return self._request("POST", "/api/vessels", payload, headers)

    def get_vessel(self, vessel_id, headers):
        return self._request("GET", f"/api/vessels/{vessel_id}", headers=headers)

    # ─── Pilots ───────────────────────────────────────
    def create_pilot(self, payload, headers):
        return self._request("POST", "/api/pilots", payload, headers)

    def get_pilot(self, pilot_id, headers):
        return self._request("GET", f"/api/pilots/{pilot_id}", headers=headers)

    # ─── Crew Members ─────────────────────────────────
    def create_crew_member(self, payload, headers):
        return self._request("POST", "/api/crew-members", payload, headers)

    def get_crew_member(self, crew_member_id, headers):
        return self._request("GET", f"/api/crew-members/{crew_member_id}", headers=headers)

    # ─── Tariff Rates ─────────────────────────────────
    def create_tariff_rate(self, payload, headers):
        return self._request("POST", "/api/tariff-rates", payload, headers)

    def get_tariff_rate(self, tariff_rate_id, headers):
        return self._request("GET", f"/api/tariff-rates/{tariff_rate_id}", headers=headers)

    # ─── Job Orders ───────────────────────────────────
    def create_job_order(self, payload, headers):
        return self._request("POST", "/api/job-orders", payload, headers)

    def list_job_orders(self, headers, params=None):
        return self._request("GET", "/api/job-orders", headers=headers, params=params)

    def get_job_order(self, job_order_id, headers):
        return self._request("GET", f"/api/job-orders/{job_order_id}", headers=headers)

    def amend_job_order(self, job_order_id, payload, headers):
        return self._request("POST", f"/api/job-orders/{job_order_id}/amend", payload, headers)

    def confirm_job_order(self, job_order_id, headers):
        return self._request("POST", f"/api/job-orders/{job_order_id}/confirm", headers=headers)

    def dispatch_job_order(self, job_order_id, headers):
        return self._request("POST", f"/api/job-orders/{job_order_id}/dispatch", headers=headers)

    def start_job_order(self, job_order_id, headers):
        return self._request("POST", f"/api/job-orders/{job_order_id}/start", headers=headers)

    def complete_job_order(self, job_order_id, headers):
        return self._request("POST", f"/api/job-orders/{job_order_id}/complete", headers=headers)

    def cancel_job_order(self, job_order_id, payload, headers):
        return self._request("POST", f"/api/job-orders/{job_order_id}/cancel", payload, headers)

    # ─── Tug Assignments ──────────────────────────────
    def create_tug_assignment(self, payload, headers):
        return self._request("POST", "/api/tug-assignments", payload, headers)

    def list_tug_assignments(self, headers, params=None):
        return self._request("GET", "/api/tug-assignments", headers=headers, params=params)

    def get_tug_assignment(self, assignment_id, headers):
        return self._request("GET", f"/api/tug-assignments/{assignment_id}", headers=headers)

    def confirm_tug_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/api/tug-assignments/{assignment_id}/confirm", headers=headers
        )

    def release_tug_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/api/tug-assignments/{assignment_id}/release", headers=headers
        )

    # ─── Pilot Bookings ───────────────────────────────
    def create_pilot_booking(self, payload, headers):
        return self._request("POST", "/api/pilot-bookings", payload, headers)

    def list_pilot_bookings(self, headers, params=None):
        return self._request("GET", "/api/pilot-bookings", headers=headers, params=params)

    def get_pilot_booking(self, booking_id, headers):
        return self._request("GET", f"/api/pilot-bookings/{booking_id}", headers=headers)

    def confirm_pilot_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/api/pilot-bookings/{booking_id}/confirm", headers=headers
        )

    def board_pilot_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/api/pilot-bookings/{booking_id}/board", headers=headers
        )

    # ─── Watch Rotations ──────────────────────────────
    def create_watch_rotation(self, payload, headers):
        return self._request("POST", "/api/watch-rotations", payload, headers)

    def list_watch_rotations(self, headers, params=None):
        return self._request("GET", "/api/watch-rotations", headers=headers, params=params)

    def get_watch_rotation(self, watch_id, headers):
        return self._request("GET", f"/api/watch-rotations/{watch_id}", headers=headers)

    # ─── Gear Inspections ─────────────────────────────
    def create_gear_inspection(self, payload, headers):
        return self._request("POST", "/api/gear-inspections", payload, headers)

    def list_gear_inspections(self, headers, params=None):
        return self._request("GET", "/api/gear-inspections", headers=headers, params=params)

    def get_gear_inspection(self, inspection_id, headers):
        return self._request("GET", f"/api/gear-inspections/{inspection_id}", headers=headers)

    # ─── Incidents ────────────────────────────────────
    def create_incident(self, payload, headers):
        return self._request("POST", "/api/incidents", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/api/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/api/incidents/{incident_id}", headers=headers)

    def resolve_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/api/incidents/{incident_id}/resolve", payload, headers
        )

    # ─── Weather Restrictions ─────────────────────────
    def create_weather_restriction(self, payload, headers):
        return self._request("POST", "/api/weather-restrictions", payload, headers)

    def list_weather_restrictions(self, headers, params=None):
        return self._request("GET", "/api/weather-restrictions", headers=headers, params=params)

    def lift_weather_restriction(self, restriction_id, headers):
        return self._request(
            "POST", f"/api/weather-restrictions/{restriction_id}/lift", headers=headers
        )

    # ─── Invoices ─────────────────────────────────────
    def list_invoices(self, headers, params=None):
        return self._request("GET", "/api/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/api/invoices/{invoice_id}", headers=headers)

    def finalize_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/api/invoices/{invoice_id}/finalize", payload, headers
        )

    def void_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/void", payload, headers)

    # ─── Damage Claims ────────────────────────────────
    def create_damage_claim(self, payload, headers):
        return self._request("POST", "/api/damage-claims", payload, headers)

    def list_damage_claims(self, headers, params=None):
        return self._request("GET", "/api/damage-claims", headers=headers, params=params)

    def get_damage_claim(self, claim_id, headers):
        return self._request("GET", f"/api/damage-claims/{claim_id}", headers=headers)

    def review_damage_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/api/damage-claims/{claim_id}/review", payload, headers
        )

    def settle_damage_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/api/damage-claims/{claim_id}/settle", headers=headers
        )

    # ─── Logical Clock ────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
