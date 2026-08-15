"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Campuses
    # ------------------------------------------------------------------
    def create_campus(self, payload, headers):
        return self._request("POST", "/campuses", payload, headers)

    def get_campus(self, campus_id, headers):
        return self._request("GET", f"/campuses/{campus_id}", headers=headers)

    # ------------------------------------------------------------------
    # Volunteers
    # ------------------------------------------------------------------
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/volunteers", payload, headers)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/volunteers/{volunteer_id}", headers=headers)

    def list_volunteers(self, headers, params=None):
        return self._request("GET", "/volunteers", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Background checks
    # ------------------------------------------------------------------
    def create_background_check(self, payload, headers):
        return self._request("POST", "/background-checks", payload, headers)

    def get_background_check(self, check_id, headers):
        return self._request("GET", f"/background-checks/{check_id}", headers=headers)

    def list_background_checks(self, headers, params=None):
        return self._request("GET", "/background-checks", headers=headers, params=params)

    def adjudicate_background_check(self, check_id, payload, headers):
        return self._request("POST", f"/background-checks/{check_id}/adjudicate",
                             payload, headers)

    # ------------------------------------------------------------------
    # Training modules and records
    # ------------------------------------------------------------------
    def create_training_module(self, payload, headers):
        return self._request("POST", "/training-modules", payload, headers)

    def list_training_modules(self, headers, params=None):
        return self._request("GET", "/training-modules", headers=headers, params=params)

    def create_training_record(self, payload, headers):
        return self._request("POST", "/training-records", payload, headers)

    def get_training_record(self, record_id, headers):
        return self._request("GET", f"/training-records/{record_id}", headers=headers)

    def list_training_records(self, headers, params=None):
        return self._request("GET", "/training-records", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Opportunities
    # ------------------------------------------------------------------
    def create_opportunity(self, payload, headers):
        return self._request("POST", "/opportunities", payload, headers)

    def get_opportunity(self, opportunity_id, headers):
        return self._request("GET", f"/opportunities/{opportunity_id}", headers=headers)

    def list_opportunities(self, headers, params=None):
        return self._request("GET", "/opportunities", headers=headers, params=params)

    def publish_opportunity(self, opportunity_id, headers):
        return self._request("POST", f"/opportunities/{opportunity_id}/publish",
                             {}, headers)

    def cancel_opportunity(self, opportunity_id, headers):
        return self._request("POST", f"/opportunities/{opportunity_id}/cancel",
                             {}, headers)

    def match_opportunity(self, opportunity_id, payload, headers):
        return self._request("POST", f"/opportunities/{opportunity_id}/match",
                             payload, headers)

    # ------------------------------------------------------------------
    # Placements
    # ------------------------------------------------------------------
    def create_placement(self, payload, headers):
        return self._request("POST", "/placements", payload, headers)

    def get_placement(self, placement_id, headers):
        return self._request("GET", f"/placements/{placement_id}", headers=headers)

    def list_placements(self, headers, params=None):
        return self._request("GET", "/placements", headers=headers, params=params)

    def confirm_placement(self, placement_id, headers):
        return self._request("POST", f"/placements/{placement_id}/confirm",
                             {}, headers)

    def cancel_placement(self, placement_id, headers):
        return self._request("POST", f"/placements/{placement_id}/cancel",
                             {}, headers)

    def complete_placement(self, placement_id, headers):
        return self._request("POST", f"/placements/{placement_id}/complete",
                             {}, headers)

    # ------------------------------------------------------------------
    # Hour entries
    # ------------------------------------------------------------------
    def create_hour_entry(self, payload, headers):
        return self._request("POST", "/hour-entries", payload, headers)

    def get_hour_entry(self, entry_id, headers):
        return self._request("GET", f"/hour-entries/{entry_id}", headers=headers)

    def list_hour_entries(self, headers, params=None):
        return self._request("GET", "/hour-entries", headers=headers, params=params)

    def verify_hour_entry(self, entry_id, headers):
        return self._request("POST", f"/hour-entries/{entry_id}/verify", {}, headers)

    def reject_hour_entry(self, entry_id, headers):
        return self._request("POST", f"/hour-entries/{entry_id}/reject", {}, headers)

    def revoke_hour_entry(self, entry_id, headers):
        return self._request("POST", f"/hour-entries/{entry_id}/revoke", {}, headers)

    # ------------------------------------------------------------------
    # Campus check-ins
    # ------------------------------------------------------------------
    def create_check_in(self, payload, headers):
        return self._request("POST", "/check-ins", payload, headers)

    def get_check_in(self, checkin_id, headers):
        return self._request("GET", f"/check-ins/{checkin_id}", headers=headers)

    def list_check_ins(self, headers, params=None):
        return self._request("GET", "/check-ins", headers=headers, params=params)

    def check_out(self, checkin_id, headers):
        return self._request("POST", f"/check-ins/{checkin_id}/check-out",
                             {}, headers)

    # ------------------------------------------------------------------
    # Incident reports
    # ------------------------------------------------------------------
    def create_incident_report(self, payload, headers):
        return self._request("POST", "/incident-reports", payload, headers)

    def get_incident_report(self, incident_id, headers):
        return self._request("GET", f"/incident-reports/{incident_id}", headers=headers)

    def list_incident_reports(self, headers, params=None):
        return self._request("GET", "/incident-reports", headers=headers, params=params)

    def adjudicate_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/incident-reports/{incident_id}/adjudicate",
                             payload, headers)

    # ------------------------------------------------------------------
    # Recognition awards
    # ------------------------------------------------------------------
    def create_recognition_award(self, payload, headers):
        return self._request("POST", "/recognition-awards", payload, headers)

    def get_recognition_award(self, award_id, headers):
        return self._request("GET", f"/recognition-awards/{award_id}", headers=headers)

    def list_recognition_awards(self, headers, params=None):
        return self._request("GET", "/recognition-awards", headers=headers, params=params)


api_client = ApiClient()
