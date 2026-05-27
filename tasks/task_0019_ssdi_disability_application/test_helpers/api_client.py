"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------- Claimant ----------
    def create_claimant(self, payload, headers):
        return self._request("POST", "/ssdi/claimants", payload, headers)

    def get_claimant(self, claimant_id, headers):
        return self._request("GET", f"/ssdi/claimants/{claimant_id}", headers=headers)

    def list_claimants(self, headers, params=None):
        return self._request("GET", "/ssdi/claimants", headers=headers, params=params)

    # ---------- WorkCreditRecord ----------
    def create_work_credit(self, payload, headers):
        return self._request("POST", "/ssdi/work-credits", payload, headers)

    def get_work_credit(self, wc_id, headers):
        return self._request("GET", f"/ssdi/work-credits/{wc_id}", headers=headers)

    def list_work_credits(self, headers, params=None):
        return self._request("GET", "/ssdi/work-credits", headers=headers, params=params)

    # ---------- Application ----------
    def create_application(self, payload, headers):
        return self._request("POST", "/ssdi/applications", payload, headers)

    def get_application(self, app_id, headers):
        return self._request("GET", f"/ssdi/applications/{app_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/ssdi/applications", headers=headers, params=params)

    def submit_application(self, app_id, headers, payload=None):
        return self._request("POST", f"/ssdi/applications/{app_id}/submit",
                             payload if payload is not None else {}, headers)

    def medical_decision(self, app_id, payload, headers):
        return self._request("POST", f"/ssdi/applications/{app_id}/medical-decision",
                             payload, headers)

    def request_reconsideration(self, app_id, headers, payload=None):
        return self._request("POST", f"/ssdi/applications/{app_id}/request-reconsideration",
                             payload if payload is not None else {}, headers)

    def request_hearing(self, app_id, headers, payload=None):
        return self._request("POST", f"/ssdi/applications/{app_id}/request-hearing",
                             payload if payload is not None else {}, headers)

    # ---------- MedicalEvidence ----------
    def create_evidence(self, app_id, payload, headers):
        return self._request("POST", f"/ssdi/applications/{app_id}/evidence",
                             payload, headers)

    def list_evidence(self, app_id, headers, params=None):
        return self._request("GET", f"/ssdi/applications/{app_id}/evidence",
                             headers=headers, params=params)

    def list_decisions(self, app_id, headers, params=None):
        return self._request("GET", f"/ssdi/applications/{app_id}/decisions",
                             headers=headers, params=params)

    # ---------- HearingRequest ----------
    def get_hearing(self, hearing_id, headers):
        return self._request("GET", f"/ssdi/hearings/{hearing_id}", headers=headers)

    def list_hearings(self, headers, params=None):
        return self._request("GET", "/ssdi/hearings", headers=headers, params=params)

    def schedule_hearing(self, hearing_id, payload, headers):
        return self._request("POST", f"/ssdi/hearings/{hearing_id}/schedule",
                             payload, headers)

    def record_held_hearing(self, hearing_id, headers, payload=None):
        return self._request("POST", f"/ssdi/hearings/{hearing_id}/record-held",
                             payload if payload is not None else {}, headers)

    def hearing_decision(self, hearing_id, payload, headers):
        return self._request("POST", f"/ssdi/hearings/{hearing_id}/decision",
                             payload, headers)

    def cancel_hearing(self, hearing_id, headers, payload=None):
        return self._request("POST", f"/ssdi/hearings/{hearing_id}/cancel",
                             payload if payload is not None else {}, headers)

    # ---------- BenefitAward ----------
    def get_award(self, award_id, headers):
        return self._request("GET", f"/ssdi/awards/{award_id}", headers=headers)

    def list_awards(self, headers, params=None):
        return self._request("GET", "/ssdi/awards", headers=headers, params=params)

    def suspend_award(self, award_id, headers, payload=None):
        return self._request("POST", f"/ssdi/awards/{award_id}/suspend",
                             payload if payload is not None else {}, headers)

    def reinstate_award(self, award_id, headers, payload=None):
        return self._request("POST", f"/ssdi/awards/{award_id}/reinstate",
                             payload if payload is not None else {}, headers)

    # ---------- ChildAuxiliaryBenefit ----------
    def create_child_auxiliary(self, award_id, payload, headers):
        return self._request("POST", f"/ssdi/awards/{award_id}/child-auxiliaries",
                             payload, headers)

    def list_child_auxiliaries(self, award_id, headers, params=None):
        return self._request("GET", f"/ssdi/awards/{award_id}/child-auxiliaries",
                             headers=headers, params=params)

    # ---------- SSISupplement ----------
    def get_ssi_supplement(self, sup_id, headers):
        return self._request("GET", f"/ssdi/ssi-supplements/{sup_id}", headers=headers)

    def list_ssi_supplements(self, headers, params=None):
        return self._request("GET", "/ssdi/ssi-supplements", headers=headers, params=params)

    # ---------- CDRReview ----------
    def get_cdr_review(self, cdr_id, headers):
        return self._request("GET", f"/ssdi/cdr-reviews/{cdr_id}", headers=headers)

    def list_cdr_reviews(self, headers, params=None):
        return self._request("GET", "/ssdi/cdr-reviews", headers=headers, params=params)

    def start_cdr(self, cdr_id, headers, payload=None):
        return self._request("POST", f"/ssdi/cdr-reviews/{cdr_id}/start",
                             payload if payload is not None else {}, headers)

    def complete_cdr(self, cdr_id, payload, headers):
        return self._request("POST", f"/ssdi/cdr-reviews/{cdr_id}/complete",
                             payload, headers)

    # ---------- Test-driving clock (PRD §2.10) ----------
    def set_clock(self, payload, headers):
        return self._request("POST", "/ssdi/_clock/set_current_utc", payload, headers)

    def advance_clock(self, payload, headers):
        return self._request("POST", "/ssdi/_clock/advance", payload, headers)


api_client = ApiClient()
