"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Programs ---
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def patch_program(self, program_id, payload, headers):
        return self._request("PATCH", f"/programs/{program_id}", payload, headers)

    def ops_run_program(self, program_id, headers, payload=None):
        return self._request("POST", f"/programs/{program_id}/ops-run",
                             payload or {}, headers)

    def get_diversion_summary(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}/diversion-summary",
                             headers=headers)

    def list_program_notifications(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/notifications",
                             headers=headers, params=params)

    # --- Drop-off sites ---
    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/sites", headers=headers, params=params)

    def patch_site(self, site_id, payload, headers):
        return self._request("PATCH", f"/sites/{site_id}", payload, headers)

    # --- Service zones ---
    def create_zone(self, payload, headers):
        return self._request("POST", "/zones", payload, headers)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/zones/{zone_id}", headers=headers)

    def list_zones(self, headers, params=None):
        return self._request("GET", "/zones", headers=headers, params=params)

    def patch_zone(self, zone_id, payload, headers):
        return self._request("PATCH", f"/zones/{zone_id}", payload, headers)

    # --- Households ---
    def create_household(self, payload, headers):
        return self._request("POST", "/households", payload, headers)

    def get_household(self, household_id, headers):
        return self._request("GET", f"/households/{household_id}", headers=headers)

    def list_households(self, headers, params=None):
        return self._request("GET", "/households", headers=headers, params=params)

    # --- Curbside bookings ---
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def cancel_booking(self, booking_id, headers, payload=None):
        return self._request("POST", f"/bookings/{booking_id}/cancel",
                             payload or {}, headers)

    def reschedule_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/reschedule",
                             payload, headers)

    def record_booking_outcome(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/record-outcome",
                             payload, headers)

    # --- Intake events ---
    def create_intake_event(self, payload, headers):
        return self._request("POST", "/intake-events", payload, headers)

    def get_intake_event(self, intake_id, headers):
        return self._request("GET", f"/intake-events/{intake_id}", headers=headers)

    def list_intake_events(self, headers, params=None):
        return self._request("GET", "/intake-events", headers=headers, params=params)

    def void_intake_event(self, intake_id, payload, headers):
        return self._request("POST", f"/intake-events/{intake_id}/void",
                             payload, headers)

    # --- Contamination tickets ---
    def create_contamination_ticket(self, payload, headers):
        return self._request("POST", "/contamination-tickets", payload, headers)

    def get_contamination_ticket(self, ticket_id, headers):
        return self._request("GET", f"/contamination-tickets/{ticket_id}",
                             headers=headers)

    def list_contamination_tickets(self, headers, params=None):
        return self._request("GET", "/contamination-tickets",
                             headers=headers, params=params)

    def adjudicate_ticket(self, ticket_id, payload, headers):
        return self._request("POST",
                             f"/contamination-tickets/{ticket_id}/adjudicate",
                             payload, headers)

    def appeal_ticket(self, ticket_id, headers, payload=None):
        return self._request("POST", f"/contamination-tickets/{ticket_id}/appeal",
                             payload or {}, headers)

    def resolve_appeal(self, ticket_id, payload, headers):
        return self._request("POST",
                             f"/contamination-tickets/{ticket_id}/resolve-appeal",
                             payload, headers)

    # --- Chipping runs ---
    def create_chipping_run(self, payload, headers):
        return self._request("POST", "/chipping-runs", payload, headers)

    def get_chipping_run(self, run_id, headers):
        return self._request("GET", f"/chipping-runs/{run_id}", headers=headers)

    def list_chipping_runs(self, headers, params=None):
        return self._request("GET", "/chipping-runs", headers=headers, params=params)

    def complete_chipping_run(self, run_id, payload, headers):
        return self._request("POST", f"/chipping-runs/{run_id}/complete",
                             payload, headers)

    def cancel_chipping_run(self, run_id, headers, payload=None):
        return self._request("POST", f"/chipping-runs/{run_id}/cancel",
                             payload or {}, headers)

    # --- Mulch events & claims ---
    def create_mulch_event(self, payload, headers):
        return self._request("POST", "/mulch-events", payload, headers)

    def get_mulch_event(self, event_id, headers):
        return self._request("GET", f"/mulch-events/{event_id}", headers=headers)

    def list_mulch_events(self, headers, params=None):
        return self._request("GET", "/mulch-events", headers=headers, params=params)

    def patch_mulch_event(self, event_id, payload, headers):
        return self._request("PATCH", f"/mulch-events/{event_id}", payload, headers)

    def create_mulch_claim(self, payload, headers):
        return self._request("POST", "/mulch-claims", payload, headers)

    def get_mulch_claim(self, claim_id, headers):
        return self._request("GET", f"/mulch-claims/{claim_id}", headers=headers)

    def list_mulch_claims(self, headers, params=None):
        return self._request("GET", "/mulch-claims", headers=headers, params=params)

    def patch_mulch_claim(self, claim_id, payload, headers):
        return self._request("PATCH", f"/mulch-claims/{claim_id}", payload, headers)

    # --- Volunteers & shifts ---
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/volunteers", payload, headers)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/volunteers/{volunteer_id}", headers=headers)

    def list_volunteers(self, headers, params=None):
        return self._request("GET", "/volunteers", headers=headers, params=params)

    def patch_volunteer(self, volunteer_id, payload, headers):
        return self._request("PATCH", f"/volunteers/{volunteer_id}",
                             payload, headers)

    def create_volunteer_shift(self, payload, headers):
        return self._request("POST", "/volunteer-shifts", payload, headers)

    def get_volunteer_shift(self, shift_id, headers):
        return self._request("GET", f"/volunteer-shifts/{shift_id}",
                             headers=headers)

    def list_volunteer_shifts(self, headers, params=None):
        return self._request("GET", "/volunteer-shifts", headers=headers,
                             params=params)

    def patch_volunteer_shift(self, shift_id, payload, headers):
        return self._request("PATCH", f"/volunteer-shifts/{shift_id}",
                             payload, headers)

    # --- Diversion reports ---
    def create_diversion_report(self, payload, headers):
        return self._request("POST", "/diversion-reports", payload, headers)

    def get_diversion_report(self, report_id, headers):
        return self._request("GET", f"/diversion-reports/{report_id}",
                             headers=headers)

    def list_diversion_reports(self, headers, params=None):
        return self._request("GET", "/diversion-reports", headers=headers,
                             params=params)

    def patch_diversion_report(self, report_id, payload, headers):
        return self._request("PATCH", f"/diversion-reports/{report_id}",
                             payload, headers)

    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
