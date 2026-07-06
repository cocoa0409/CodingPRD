"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----------------------------------------------------------- logical clock
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------ members
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member_summary(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/summary", headers=headers, params=params
        )

    def activate_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/activate", {}, headers)

    def leave_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/leave", {}, headers)

    def return_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/return", {}, headers)

    def retire_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/retire", {}, headers)

    def expel_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/expel", {}, headers)

    def create_dues_payment(self, member_id, payload, headers):
        return self._request(
            "POST", f"/members/{member_id}/dues-payments", payload, headers
        )

    # ----------------------------------------------------------- certifications
    def create_certification(self, member_id, payload, headers):
        return self._request(
            "POST", f"/members/{member_id}/certifications", payload, headers
        )

    def get_certification(self, cert_id, headers):
        return self._request("GET", f"/certifications/{cert_id}", headers=headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/certifications", headers=headers, params=params)

    def issue_certification(self, cert_id, headers):
        return self._request("POST", f"/certifications/{cert_id}/issue", {}, headers)

    def renew_certification(self, cert_id, headers):
        return self._request("POST", f"/certifications/{cert_id}/renew", {}, headers)

    def suspend_certification(self, cert_id, headers):
        return self._request("POST", f"/certifications/{cert_id}/suspend", {}, headers)

    def reinstate_certification(self, cert_id, headers):
        return self._request("POST", f"/certifications/{cert_id}/reinstate", {}, headers)

    def revoke_certification(self, cert_id, headers):
        return self._request("POST", f"/certifications/{cert_id}/revoke", {}, headers)

    def sweep_certifications(self, headers):
        return self._request("POST", "/certifications/sweep", {}, headers)

    # ---------------------------------------------------------- training records
    def create_training_record(self, member_id, payload, headers):
        return self._request(
            "POST", f"/members/{member_id}/training-records", payload, headers
        )

    def get_training_record(self, record_id, headers):
        return self._request("GET", f"/training-records/{record_id}", headers=headers)

    def list_training_records(self, headers, params=None):
        return self._request("GET", "/training-records", headers=headers, params=params)

    # ---------------------------------------------------------- point adjustments
    def create_point_adjustment(self, member_id, payload, headers):
        return self._request(
            "POST", f"/members/{member_id}/point-adjustments", payload, headers
        )

    def get_point_adjustment(self, adjustment_id, headers):
        return self._request(
            "GET", f"/point-adjustments/{adjustment_id}", headers=headers
        )

    def list_point_adjustments(self, headers, params=None):
        return self._request(
            "GET", "/point-adjustments", headers=headers, params=params
        )

    # ------------------------------------------------------------------ stations
    def create_station(self, payload, headers):
        return self._request("POST", "/stations", payload, headers)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/stations/{station_id}", headers=headers)

    # ---------------------------------------------------------------- apparatus
    def create_apparatus(self, station_id, payload, headers):
        return self._request(
            "POST", f"/stations/{station_id}/apparatus", payload, headers
        )

    def get_apparatus(self, apparatus_id, headers):
        return self._request("GET", f"/apparatus/{apparatus_id}", headers=headers)

    def list_apparatus(self, headers, params=None):
        return self._request("GET", "/apparatus", headers=headers, params=params)

    # ---------------------------------------------------------------- equipment
    def create_equipment(self, apparatus_id, payload, headers):
        return self._request(
            "POST", f"/apparatus/{apparatus_id}/equipment", payload, headers
        )

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/equipment/{equipment_id}", headers=headers)

    def list_equipment(self, headers, params=None):
        return self._request("GET", "/equipment", headers=headers, params=params)

    def equipment_out_of_service(self, equipment_id, headers):
        return self._request(
            "POST", f"/equipment/{equipment_id}/out-of-service", {}, headers
        )

    def equipment_return_to_service(self, equipment_id, headers):
        return self._request(
            "POST", f"/equipment/{equipment_id}/return-to-service", {}, headers
        )

    # ------------------------------------------------------- maintenance windows
    def create_maintenance_window(self, apparatus_id, payload, headers):
        return self._request(
            "POST", f"/apparatus/{apparatus_id}/maintenance-windows", payload, headers
        )

    def get_maintenance_window(self, window_id, headers):
        return self._request(
            "GET", f"/maintenance-windows/{window_id}", headers=headers
        )

    def list_maintenance_windows(self, headers, params=None):
        return self._request(
            "GET", "/maintenance-windows", headers=headers, params=params
        )

    def start_maintenance_window(self, window_id, headers):
        return self._request(
            "POST", f"/maintenance-windows/{window_id}/start", {}, headers
        )

    def complete_maintenance_window(self, window_id, headers):
        return self._request(
            "POST", f"/maintenance-windows/{window_id}/complete", {}, headers
        )

    def cancel_maintenance_window(self, window_id, headers):
        return self._request(
            "POST", f"/maintenance-windows/{window_id}/cancel", {}, headers
        )

    # --------------------------------------------------------------- duty shifts
    def create_duty_shift(self, payload, headers):
        return self._request("POST", "/duty-shifts", payload, headers)

    def get_duty_shift(self, shift_id, headers):
        return self._request("GET", f"/duty-shifts/{shift_id}", headers=headers)

    def list_duty_shifts(self, headers, params=None):
        return self._request("GET", "/duty-shifts", headers=headers, params=params)

    def publish_duty_shift(self, shift_id, headers):
        return self._request("POST", f"/duty-shifts/{shift_id}/publish", {}, headers)

    def cancel_duty_shift(self, shift_id, headers):
        return self._request("POST", f"/duty-shifts/{shift_id}/cancel", {}, headers)

    def sweep_duty_shifts(self, headers):
        return self._request("POST", "/duty-shifts/sweep", {}, headers)

    def create_assignment(self, shift_id, payload, headers):
        return self._request(
            "POST", f"/duty-shifts/{shift_id}/assignments", payload, headers
        )

    # ----------------------------------------------------------- duty assignments
    def get_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/duty-assignments/{assignment_id}", headers=headers
        )

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/duty-assignments", headers=headers, params=params)

    def check_in_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/duty-assignments/{assignment_id}/check-in", {}, headers
        )

    def cancel_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/duty-assignments/{assignment_id}/cancel", {}, headers
        )

    # ------------------------------------------------------------------ incidents
    def create_incident(self, payload, headers):
        return self._request("POST", "/incidents", payload, headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/incidents/{incident_id}", headers=headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/incidents", headers=headers, params=params)

    def incident_enroute(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/enroute", {}, headers)

    def incident_arrive(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/arrive", {}, headers)

    def incident_clear(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/clear", {}, headers)

    def incident_report(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/incidents/{incident_id}/report", payload, headers
        )

    def incident_report_lock(self, incident_id, headers):
        return self._request(
            "POST", f"/incidents/{incident_id}/report/lock", {}, headers
        )

    def incident_report_amend(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/incidents/{incident_id}/report/amend", payload, headers
        )

    # ------------------------------------------------------------------ turnouts
    def create_turnout(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/incidents/{incident_id}/turnouts", payload, headers
        )

    def get_turnout(self, turnout_id, headers):
        return self._request("GET", f"/turnouts/{turnout_id}", headers=headers)

    def list_turnouts(self, headers, params=None):
        return self._request("GET", "/turnouts", headers=headers, params=params)

    def void_turnout(self, turnout_id, headers):
        return self._request("POST", f"/turnouts/{turnout_id}/void", {}, headers)

    # ----------------------------------------------------------------- campaigns
    def create_campaign(self, payload, headers):
        return self._request("POST", "/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/campaigns/{campaign_id}", headers=headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/campaigns", headers=headers, params=params)

    def open_campaign(self, campaign_id, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/open", {}, headers)

    def close_campaign(self, campaign_id, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/close", {}, headers)

    def create_donation(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"/campaigns/{campaign_id}/donations", payload, headers
        )

    # ----------------------------------------------------------------- donations
    def get_donation(self, donation_id, headers):
        return self._request("GET", f"/donations/{donation_id}", headers=headers)

    def list_donations(self, headers, params=None):
        return self._request("GET", "/donations", headers=headers, params=params)

    def refund_donation(self, donation_id, headers):
        return self._request("POST", f"/donations/{donation_id}/refund", {}, headers)


api_client = ApiClient()
