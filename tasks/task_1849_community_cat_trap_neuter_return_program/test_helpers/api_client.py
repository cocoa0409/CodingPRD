"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- clock -----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ----- caretakers -----
    def create_caretaker(self, payload, headers):
        return self._request("POST", "/tnr/caretakers", payload, headers)

    def get_caretaker(self, caretaker_id, headers):
        return self._request("GET", f"/tnr/caretakers/{caretaker_id}", headers=headers)

    def list_caretaker_vouchers(self, caretaker_id, headers, params=None):
        return self._request("GET", f"/tnr/caretakers/{caretaker_id}/vouchers",
                             headers=headers, params=params)

    # ----- colonies -----
    def create_colony(self, payload, headers):
        return self._request("POST", "/tnr/colonies", payload, headers)

    def get_colony(self, colony_id, headers):
        return self._request("GET", f"/tnr/colonies/{colony_id}", headers=headers)

    def list_colonies(self, headers, params=None):
        return self._request("GET", "/tnr/colonies", headers=headers, params=params)

    def dissolve_colony(self, colony_id, headers):
        return self._request("POST", f"/tnr/colonies/{colony_id}/dissolve", {}, headers)

    # ----- cats -----
    def create_cat(self, colony_id, payload, headers):
        return self._request("POST", f"/tnr/colonies/{colony_id}/cats", payload, headers)

    def list_colony_cats(self, colony_id, headers, params=None):
        return self._request("GET", f"/tnr/colonies/{colony_id}/cats",
                             headers=headers, params=params)

    def get_cat(self, cat_id, headers):
        return self._request("GET", f"/tnr/cats/{cat_id}", headers=headers)

    def decide_pathway(self, cat_id, payload, headers):
        return self._request("POST", f"/tnr/cats/{cat_id}/decide-pathway",
                             payload, headers)

    def finalize_adoption(self, cat_id, headers):
        return self._request("POST", f"/tnr/cats/{cat_id}/finalize-adoption", {}, headers)

    def confirm_long_term(self, cat_id, headers):
        return self._request("POST", f"/tnr/cats/{cat_id}/confirm-long-term", {}, headers)

    # ----- partner clinics & clinic days -----
    def create_partner_clinic(self, payload, headers):
        return self._request("POST", "/tnr/partner-clinics", payload, headers)

    def get_partner_clinic(self, clinic_id, headers):
        return self._request("GET", f"/tnr/partner-clinics/{clinic_id}", headers=headers)

    def list_clinic_days_of_clinic(self, clinic_id, headers, params=None):
        return self._request("GET", f"/tnr/partner-clinics/{clinic_id}/clinic-days",
                             headers=headers, params=params)

    def create_clinic_day(self, payload, headers):
        return self._request("POST", "/tnr/clinic-days", payload, headers)

    def get_clinic_day(self, day_id, headers):
        return self._request("GET", f"/tnr/clinic-days/{day_id}", headers=headers)

    def list_clinic_day_slots(self, day_id, headers, params=None):
        return self._request("GET", f"/tnr/clinic-days/{day_id}/slots",
                             headers=headers, params=params)

    def get_clinic_slot(self, slot_id, headers):
        return self._request("GET", f"/tnr/clinic-slots/{slot_id}", headers=headers)

    def close_clinic_day(self, day_id, headers):
        return self._request("POST", f"/tnr/clinic-days/{day_id}/close", {}, headers)

    def cancel_clinic_day(self, day_id, headers):
        return self._request("POST", f"/tnr/clinic-days/{day_id}/cancel", {}, headers)

    # ----- appointments -----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/tnr/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/tnr/appointments/{appointment_id}", headers=headers)

    def list_cat_appointments(self, cat_id, headers, params=None):
        return self._request("GET", f"/tnr/cats/{cat_id}/appointments",
                             headers=headers, params=params)

    def list_slot_appointments(self, slot_id, headers, params=None):
        return self._request("GET", f"/tnr/clinic-slots/{slot_id}/appointments",
                             headers=headers, params=params)

    def list_voucher_appointments(self, voucher_id, headers, params=None):
        return self._request("GET", f"/tnr/vouchers/{voucher_id}/appointments",
                             headers=headers, params=params)

    def mark_trapped(self, appointment_id, headers):
        return self._request("POST", f"/tnr/appointments/{appointment_id}/mark-trapped",
                             {}, headers)

    def check_in(self, appointment_id, headers):
        return self._request("POST", f"/tnr/appointments/{appointment_id}/check-in",
                             {}, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/tnr/appointments/{appointment_id}/cancel",
                             {}, headers)

    # ----- surgery -----
    def create_surgery_record(self, payload, headers):
        return self._request("POST", "/tnr/surgery-records", payload, headers)

    def list_appointment_surgery_records(self, appointment_id, headers, params=None):
        return self._request("GET",
                             f"/tnr/appointments/{appointment_id}/surgery-records",
                             headers=headers, params=params)

    # ----- vouchers -----
    def create_voucher(self, payload, headers):
        return self._request("POST", "/tnr/vouchers", payload, headers)

    def get_voucher(self, voucher_id, headers):
        return self._request("GET", f"/tnr/vouchers/{voucher_id}", headers=headers)

    def expire_sweep(self, headers):
        return self._request("POST", "/tnr/vouchers/expire-sweep", {}, headers)

    # ----- complaints -----
    def create_complaint(self, colony_id, payload, headers):
        return self._request("POST", f"/tnr/colonies/{colony_id}/complaints",
                             payload, headers)

    def list_colony_complaints(self, colony_id, headers, params=None):
        return self._request("GET", f"/tnr/colonies/{colony_id}/complaints",
                             headers=headers, params=params)

    def start_mediation(self, complaint_id, headers):
        return self._request("POST", f"/tnr/complaints/{complaint_id}/start-mediation",
                             {}, headers)

    def escalate_complaint(self, complaint_id, headers):
        return self._request("POST", f"/tnr/complaints/{complaint_id}/escalate",
                             {}, headers)

    def resolve_complaint(self, complaint_id, headers):
        return self._request("POST", f"/tnr/complaints/{complaint_id}/resolve",
                             {}, headers)

    # ----- foster network -----
    def create_foster_home(self, payload, headers):
        return self._request("POST", "/tnr/foster-homes", payload, headers)

    def get_foster_home(self, home_id, headers):
        return self._request("GET", f"/tnr/foster-homes/{home_id}", headers=headers)

    def list_foster_home_placements(self, home_id, headers, params=None):
        return self._request("GET", f"/tnr/foster-homes/{home_id}/placements",
                             headers=headers, params=params)

    def list_cat_foster_placements(self, cat_id, headers, params=None):
        return self._request("GET", f"/tnr/cats/{cat_id}/foster-placements",
                             headers=headers, params=params)

    def create_foster_placement(self, payload, headers):
        return self._request("POST", "/tnr/foster-placements", payload, headers)

    def graduate_placement(self, placement_id, headers):
        return self._request("POST", f"/tnr/foster-placements/{placement_id}/graduate",
                             {}, headers)

    def return_placement_to_program(self, placement_id, headers):
        return self._request(
            "POST", f"/tnr/foster-placements/{placement_id}/return-to-program",
            {}, headers)

    # ----- population monitoring -----
    def create_population_survey(self, colony_id, payload, headers):
        return self._request("POST", f"/tnr/colonies/{colony_id}/population-surveys",
                             payload, headers)

    def list_population_surveys(self, colony_id, headers, params=None):
        return self._request("GET", f"/tnr/colonies/{colony_id}/population-surveys",
                             headers=headers, params=params)

    def get_population_report(self, colony_id, headers):
        return self._request("GET", f"/tnr/colonies/{colony_id}/population-report",
                             headers=headers)


api_client = ApiClient()
