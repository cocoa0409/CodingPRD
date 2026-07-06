"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Representatives ---
    def create_representative(self, payload, headers):
        return self._request("POST", "/representatives", payload, headers)

    def get_representative(self, rep_id, headers):
        return self._request("GET", f"/representatives/{rep_id}", headers=headers)

    # --- Constituents ---
    def create_constituent(self, payload, headers):
        return self._request("POST", "/constituents", payload, headers)

    def get_constituent(self, con_id, headers):
        return self._request("GET", f"/constituents/{con_id}", headers=headers)

    def list_constituents(self, headers, params=None):
        return self._request("GET", "/constituents", headers=headers, params=params)

    def update_constituent(self, con_id, payload, headers):
        return self._request("PATCH", f"/constituents/{con_id}", payload, headers)

    def purge_constituent(self, con_id, headers):
        return self._request("POST", f"/constituents/{con_id}/purge", {}, headers)

    # --- Agencies ---
    def create_agency(self, payload, headers):
        return self._request("POST", "/agencies", payload, headers)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/agencies/{agency_id}", headers=headers)

    # --- Response templates ---
    def create_template(self, payload, headers):
        return self._request("POST", "/response-templates", payload, headers)

    def get_template(self, tmpl_id, headers):
        return self._request("GET", f"/response-templates/{tmpl_id}", headers=headers)

    # --- Cases ---
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def triage_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/triage", payload, headers)

    def request_info(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/request-info", payload, headers)

    def constituent_reply(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/constituent-reply", payload, headers)

    def respond_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/respond", payload, headers)

    def close_case(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/close", {}, headers)

    def withdraw_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/withdraw", payload, headers)

    def create_referral(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/referrals", payload, headers)

    def list_case_referrals(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/referrals", headers=headers, params=params)

    # --- Agency referrals ---
    def get_referral(self, ref_id, headers):
        return self._request("GET", f"/agency-referrals/{ref_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/agency-referrals", headers=headers, params=params)

    def send_referral(self, ref_id, headers):
        return self._request("POST", f"/agency-referrals/{ref_id}/send", {}, headers)

    def resolve_referral(self, ref_id, payload, headers):
        return self._request("POST", f"/agency-referrals/{ref_id}/resolve", payload, headers)

    def reject_referral(self, ref_id, payload, headers):
        return self._request("POST", f"/agency-referrals/{ref_id}/reject", payload, headers)

    # --- Analytics ---
    def get_recurring_issues(self, headers, params=None):
        return self._request("GET", "/analytics/recurring-issues", headers=headers, params=params)

    # --- Venues ---
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    # --- Events ---
    def create_event(self, payload, headers):
        return self._request("POST", "/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/events", headers=headers, params=params)

    def reschedule_event(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/reschedule", payload, headers)

    def open_registration(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/open-registration", {}, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/cancel", {}, headers)

    def create_registration(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/registrations", payload, headers)

    def list_event_registrations(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/registrations", headers=headers, params=params)

    # --- Event registrations ---
    def get_registration(self, reg_id, headers):
        return self._request("GET", f"/event-registrations/{reg_id}", headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/event-registrations", headers=headers, params=params)

    def cancel_registration(self, reg_id, headers):
        return self._request("POST", f"/event-registrations/{reg_id}/cancel", {}, headers)

    # --- Newsletters ---
    def create_newsletter(self, rep_id, payload, headers):
        return self._request("POST", f"/representatives/{rep_id}/newsletters", payload, headers)

    def list_newsletters(self, rep_id, headers, params=None):
        return self._request("GET", f"/representatives/{rep_id}/newsletters", headers=headers, params=params)

    def get_newsletter(self, camp_id, headers):
        return self._request("GET", f"/newsletters/{camp_id}", headers=headers)


api_client = ApiClient()
