"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Owners ------------------------------------------------------------
    def create_owner(self, payload, headers=None):
        return self._request("POST", "/owners", payload, headers=headers)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/owners/{owner_id}", headers=headers)

    # --- Tax rolls ---------------------------------------------------------
    def create_tax_roll(self, payload, headers):
        return self._request("POST", "/tax-rolls", payload, headers=headers)

    def list_tax_rolls(self, headers, params=None):
        return self._request("GET", "/tax-rolls", headers=headers, params=params)

    def get_tax_roll(self, roll_id, headers):
        return self._request("GET", f"/tax-rolls/{roll_id}", headers=headers)

    def open_tax_roll(self, roll_id, headers):
        return self._request("POST", f"/tax-rolls/{roll_id}/open", {}, headers=headers)

    def certify_tax_roll(self, roll_id, headers):
        return self._request("POST", f"/tax-rolls/{roll_id}/certify", {}, headers=headers)

    def close_tax_roll(self, roll_id, headers):
        return self._request("POST", f"/tax-rolls/{roll_id}/close", {}, headers=headers)

    # --- Parcels -----------------------------------------------------------
    def create_parcel(self, payload, headers):
        return self._request("POST", "/parcels", payload, headers=headers)

    def list_parcels(self, headers, params=None):
        return self._request("GET", "/parcels", headers=headers, params=params)

    def get_parcel(self, parcel_id, headers):
        return self._request("GET", f"/parcels/{parcel_id}", headers=headers)

    def record_sale(self, parcel_id, payload, headers):
        return self._request("POST", f"/parcels/{parcel_id}/record-sale", payload, headers=headers)

    def list_parcel_assessments(self, parcel_id, headers, params=None):
        return self._request("GET", f"/parcels/{parcel_id}/assessments", headers=headers, params=params)

    def list_parcel_deferrals(self, parcel_id, headers, params=None):
        return self._request("GET", f"/parcels/{parcel_id}/deferrals", headers=headers, params=params)

    # --- Assessments -------------------------------------------------------
    def create_assessment(self, payload, headers):
        return self._request("POST", "/assessments", payload, headers=headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/assessments", headers=headers, params=params)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/assessments/{assessment_id}", headers=headers)

    def notice_assessment(self, assessment_id, headers):
        return self._request("POST", f"/assessments/{assessment_id}/notice", {}, headers=headers)

    def finalize_assessment(self, assessment_id, headers):
        return self._request("POST", f"/assessments/{assessment_id}/finalize", {}, headers=headers)

    def issue_bill(self, assessment_id, headers):
        return self._request("POST", f"/assessments/{assessment_id}/issue-bill", {}, headers=headers)

    def list_assessment_exemptions(self, assessment_id, headers, params=None):
        return self._request("GET", f"/assessments/{assessment_id}/exemptions", headers=headers, params=params)

    def list_assessment_appeals(self, assessment_id, headers, params=None):
        return self._request("GET", f"/assessments/{assessment_id}/appeals", headers=headers, params=params)

    def list_assessment_bills(self, assessment_id, headers, params=None):
        return self._request("GET", f"/assessments/{assessment_id}/bills", headers=headers, params=params)

    # --- Tax bills ---------------------------------------------------------
    def get_tax_bill(self, bill_id, headers):
        return self._request("GET", f"/tax-bills/{bill_id}", headers=headers)

    def pay_tax_bill(self, bill_id, headers):
        return self._request("POST", f"/tax-bills/{bill_id}/pay", {}, headers=headers)

    # --- Exemptions --------------------------------------------------------
    def create_exemption(self, payload, headers):
        return self._request("POST", "/exemptions", payload, headers=headers)

    def get_exemption(self, exemption_id, headers):
        return self._request("GET", f"/exemptions/{exemption_id}", headers=headers)

    def approve_exemption(self, exemption_id, headers):
        return self._request("POST", f"/exemptions/{exemption_id}/approve", {}, headers=headers)

    def deny_exemption(self, exemption_id, headers):
        return self._request("POST", f"/exemptions/{exemption_id}/deny", {}, headers=headers)

    # --- Appeals -----------------------------------------------------------
    def create_appeal(self, payload, headers):
        return self._request("POST", "/appeals", payload, headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/appeals", headers=headers, params=params)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def accept_appeal(self, appeal_id, headers):
        return self._request("POST", f"/appeals/{appeal_id}/accept", {}, headers=headers)

    def request_evidence(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/request-evidence", payload, headers=headers)

    def submit_evidence(self, appeal_id, headers):
        return self._request("POST", f"/appeals/{appeal_id}/submit-evidence", {}, headers=headers)

    def settle_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/settle", payload, headers=headers)

    def grant_appeal(self, appeal_id, headers):
        return self._request("POST", f"/appeals/{appeal_id}/grant", {}, headers=headers)

    def deny_appeal(self, appeal_id, headers):
        return self._request("POST", f"/appeals/{appeal_id}/deny", {}, headers=headers)

    def withdraw_appeal(self, appeal_id, headers):
        return self._request("POST", f"/appeals/{appeal_id}/withdraw", {}, headers=headers)

    def list_appeal_hearings(self, appeal_id, headers, params=None):
        return self._request("GET", f"/appeals/{appeal_id}/hearings", headers=headers, params=params)

    # --- Board panels & hearings ------------------------------------------
    def create_board_panel(self, payload, headers):
        return self._request("POST", "/board-panels", payload, headers=headers)

    def get_board_panel(self, panel_id, headers):
        return self._request("GET", f"/board-panels/{panel_id}", headers=headers)

    def list_panel_hearings(self, panel_id, headers, params=None):
        return self._request("GET", f"/board-panels/{panel_id}/hearings", headers=headers, params=params)

    def create_hearing(self, payload, headers):
        return self._request("POST", "/hearings", payload, headers=headers)

    def get_hearing(self, hearing_id, headers):
        return self._request("GET", f"/hearings/{hearing_id}", headers=headers)

    def hold_hearing(self, hearing_id, headers):
        return self._request("POST", f"/hearings/{hearing_id}/hold", {}, headers=headers)

    def cancel_hearing(self, hearing_id, headers):
        return self._request("POST", f"/hearings/{hearing_id}/cancel", {}, headers=headers)

    # --- Deferrals ---------------------------------------------------------
    def create_deferral(self, payload, headers):
        return self._request("POST", "/deferrals", payload, headers=headers)

    def list_deferrals(self, headers, params=None):
        return self._request("GET", "/deferrals", headers=headers, params=params)

    def get_deferral(self, deferral_id, headers):
        return self._request("GET", f"/deferrals/{deferral_id}", headers=headers)

    def enroll_bill(self, deferral_id, payload, headers):
        return self._request("POST", f"/deferrals/{deferral_id}/enroll-bill", payload, headers=headers)

    def accrue_interest(self, deferral_id, headers):
        return self._request("POST", f"/deferrals/{deferral_id}/accrue-interest", {}, headers=headers)

    def create_payment(self, deferral_id, payload, headers):
        return self._request("POST", f"/deferrals/{deferral_id}/payments", payload, headers=headers)

    def default_deferral(self, deferral_id, headers):
        return self._request("POST", f"/deferrals/{deferral_id}/default", {}, headers=headers)

    def list_deferral_payments(self, deferral_id, headers, params=None):
        return self._request("GET", f"/deferrals/{deferral_id}/payments", headers=headers, params=params)


api_client = ApiClient()
