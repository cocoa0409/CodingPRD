"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ---- MobileUnit ----
    def create_mobile_unit(self, payload, headers):
        return self._request("POST", "/mobile-units", payload, headers)

    def list_mobile_units(self, headers, params=None):
        return self._request("GET", "/mobile-units", headers=headers, params=params)

    def get_mobile_unit(self, unit_id, headers):
        return self._request("GET", f"/mobile-units/{unit_id}", headers=headers)

    def retire_mobile_unit(self, unit_id, headers):
        return self._request("POST", f"/mobile-units/{unit_id}/retire", {}, headers)

    # ---- StaffMember ----
    def create_staff(self, payload, headers):
        return self._request("POST", "/staff", payload, headers)

    def list_staff(self, headers, params=None):
        return self._request("GET", "/staff", headers=headers, params=params)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/staff/{staff_id}", headers=headers)

    def deactivate_staff(self, staff_id, headers):
        return self._request("POST", f"/staff/{staff_id}/deactivate", {}, headers)

    # ---- Sponsor ----
    def create_sponsor(self, payload, headers):
        return self._request("POST", "/sponsors", payload, headers)

    def list_sponsors(self, headers, params=None):
        return self._request("GET", "/sponsors", headers=headers, params=params)

    def get_sponsor(self, sponsor_id, headers):
        return self._request("GET", f"/sponsors/{sponsor_id}", headers=headers)

    def get_sponsor_report(self, sponsor_id, headers):
        return self._request("GET", f"/sponsors/{sponsor_id}/report", headers=headers)

    # ---- Grant ----
    def create_grant(self, payload, headers):
        return self._request("POST", "/grants", payload, headers)

    def list_grants(self, headers, params=None):
        return self._request("GET", "/grants", headers=headers, params=params)

    def get_grant(self, grant_id, headers):
        return self._request("GET", f"/grants/{grant_id}", headers=headers)

    # ---- ScreeningEvent ----
    def create_event(self, payload, headers):
        return self._request("POST", "/screening-events", payload, headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/screening-events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/screening-events/{event_id}", headers=headers)

    def get_event_summary(self, event_id, headers):
        return self._request("GET", f"/screening-events/{event_id}/summary", headers=headers)

    def publish_event(self, event_id, payload, headers):
        return self._request("POST", f"/screening-events/{event_id}/publish", payload, headers)

    def close_event(self, event_id, headers):
        return self._request("POST", f"/screening-events/{event_id}/close", {}, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/screening-events/{event_id}/cancel", {}, headers)

    # ---- Participant ----
    def create_participant(self, payload, headers):
        return self._request("POST", "/participants", payload, headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/participants", headers=headers, params=params)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}", headers=headers)

    def reinstate_participant(self, participant_id, headers):
        return self._request("POST", f"/participants/{participant_id}/reinstate", {}, headers)

    # ---- Appointment ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def consent_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/consent", {}, headers)

    def checkin_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/check-in", {}, headers)

    def screen_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/screen", {}, headers)

    def deliver_result(self, appointment_id, payload, headers):
        return self._request("POST", f"/appointments/{appointment_id}/deliver-result", payload, headers)

    def close_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/close", {}, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/cancel", {}, headers)

    def mark_no_show(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/mark-no-show", {}, headers)

    # ---- Referral ----
    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def contact_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/contact", {}, headers)

    def schedule_followup_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/schedule-followup", {}, headers)

    def resolve_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/resolve", {}, headers)

    def mark_lost_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/mark-lost", {}, headers)

    # ---- Charge ----
    def list_charges(self, headers, params=None):
        return self._request("GET", "/charges", headers=headers, params=params)

    def get_charge(self, charge_id, headers):
        return self._request("GET", f"/charges/{charge_id}", headers=headers)

    def adjudicate_charge(self, charge_id, payload, headers):
        return self._request("POST", f"/charges/{charge_id}/adjudicate", payload, headers)

    def settle_charge(self, charge_id, payload, headers):
        return self._request("POST", f"/charges/{charge_id}/settle", payload, headers)

    def void_charge(self, charge_id, headers):
        return self._request("POST", f"/charges/{charge_id}/void", {}, headers)

    # ---- Reminder ----
    def create_reminder(self, payload, headers):
        return self._request("POST", "/reminders", payload, headers)

    def list_reminders(self, headers, params=None):
        return self._request("GET", "/reminders", headers=headers, params=params)

    def get_reminder(self, reminder_id, headers):
        return self._request("GET", f"/reminders/{reminder_id}", headers=headers)

    def send_reminder(self, reminder_id, headers):
        return self._request("POST", f"/reminders/{reminder_id}/send", {}, headers)

    def cancel_reminder(self, reminder_id, headers):
        return self._request("POST", f"/reminders/{reminder_id}/cancel", {}, headers)


api_client = ApiClient()
