"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Parcel ---
    def create_parcel(self, payload, headers):
        return self._request("POST", "/parcels", payload, headers)

    def get_parcel(self, parcel_id, headers):
        return self._request("GET", f"/parcels/{parcel_id}", headers=headers)

    # --- FeeSchedule ---
    def create_fee_schedule(self, payload, headers):
        return self._request("POST", "/fee-schedules", payload, headers)

    def get_fee_schedule(self, fee_schedule_id, headers):
        return self._request("GET", f"/fee-schedules/{fee_schedule_id}", headers=headers)

    # --- Applicant ---
    def create_applicant(self, payload, headers):
        return self._request("POST", "/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    # --- EntitlementApplication ---
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/submit", {}, headers)

    def record_completeness(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/completeness", payload, headers)

    def list_completeness_reviews(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}/completeness-reviews", headers=headers)

    def create_notice(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/notices", payload, headers)

    def list_notices(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}/notices", headers=headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/withdraw", {}, headers)

    def effectuate_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/effectuate", {}, headers)

    def extend_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/extend", {}, headers)

    def list_conditions(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}/conditions", headers=headers)

    def list_findings(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}/findings", headers=headers)

    def list_appeals_for_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}/appeals", headers=headers)

    def list_agenda_items_for_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}/agenda-items", headers=headers)

    # --- Hearing ---
    def create_hearing(self, payload, headers):
        return self._request("POST", "/hearings", payload, headers)

    def get_hearing(self, hearing_id, headers):
        return self._request("GET", f"/hearings/{hearing_id}", headers=headers)

    def place_agenda_item(self, hearing_id, payload, headers):
        return self._request("POST", f"/hearings/{hearing_id}/agenda-items", payload, headers)

    def list_hearing_agenda_items(self, hearing_id, headers):
        return self._request("GET", f"/hearings/{hearing_id}/agenda-items", headers=headers)

    def cancel_hearing(self, hearing_id, headers):
        return self._request("POST", f"/hearings/{hearing_id}/cancel", {}, headers)

    # --- HearingAgendaItem ---
    def get_agenda_item(self, item_id, headers):
        return self._request("GET", f"/agenda-items/{item_id}", headers=headers)

    def decide_agenda_item(self, item_id, payload, headers):
        return self._request("POST", f"/agenda-items/{item_id}/decide", payload, headers)

    # --- Appeal ---
    def create_appeal(self, payload, headers):
        return self._request("POST", "/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def resolve_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/resolve", payload, headers)

    # --- Plat ---
    def create_plat(self, payload, headers):
        return self._request("POST", "/plats", payload, headers)

    def list_plats(self, headers, params=None):
        return self._request("GET", "/plats", headers=headers, params=params)

    def get_plat(self, plat_id, headers):
        return self._request("GET", f"/plats/{plat_id}", headers=headers)

    def record_plat(self, plat_id, payload, headers):
        return self._request("POST", f"/plats/{plat_id}/record", payload, headers)

    def vacate_plat(self, plat_id, headers):
        return self._request("POST", f"/plats/{plat_id}/vacate", {}, headers)

    def list_plat_impact_fee(self, plat_id, headers):
        return self._request("GET", f"/plats/{plat_id}/impact-fee", headers=headers)

    # --- ImpactFeeAssessment ---
    def get_impact_fee(self, fee_id, headers):
        return self._request("GET", f"/impact-fees/{fee_id}", headers=headers)

    def pay_impact_fee(self, fee_id, payload, headers):
        return self._request("POST", f"/impact-fees/{fee_id}/pay", payload, headers)


api_client = ApiClient()
