"""
Endpoint client for the Individual Artist Fellowship Grants API.

One method per endpoint declared in the PRD. Every method returns the raw
`requests.Response` so tests can assert on status codes themselves.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/grants"


class ApiClient(GenericApiClient):
    """Typed wrapper over the fellowship-grants HTTP surface."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # FellowshipCycle
    # ------------------------------------------------------------------
    def create_cycle(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/cycles", payload, headers)

    def list_cycles(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/cycles", params or {}, headers)

    def get_cycle(self, cycle_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/cycles/{cycle_id}", None, headers)

    def set_cycle_status(self, cycle_id: str, to_status: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/cycles/{cycle_id}/status", {"to_status": to_status}, headers
        )

    def set_cycle_status_raw(
        self, cycle_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/cycles/{cycle_id}/status", payload, headers
        )

    def get_cycle_evaluation(self, cycle_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/cycles/{cycle_id}/evaluation", None, headers
        )

    # ------------------------------------------------------------------
    # DisciplineCategory
    # ------------------------------------------------------------------
    def create_discipline(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/discipline-categories", payload, headers)

    def list_disciplines(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/discipline-categories", params or {}, headers
        )

    def get_discipline(self, discipline_category_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"{PREFIX}/discipline-categories/{discipline_category_id}",
            None,
            headers,
        )

    # ------------------------------------------------------------------
    # Artist
    # ------------------------------------------------------------------
    def create_artist(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/artists", payload, headers)

    def list_artists(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/artists", params or {}, headers)

    def get_artist(self, artist_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/artists/{artist_id}", None, headers)

    def patch_artist(
        self, artist_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PATCH", f"{PREFIX}/artists/{artist_id}", payload, headers)

    def add_award_history(
        self, artist_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/artists/{artist_id}/award-history", payload, headers
        )

    def debar_artist(
        self, artist_id: str, debar_reason_code: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/artists/{artist_id}/debar",
            {"debar_reason_code": debar_reason_code},
            headers,
        )

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    def create_application(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/applications", payload, headers)

    def list_applications(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/applications", params or {}, headers)

    def get_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/applications/{application_id}", None, headers
        )

    def submit_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/applications/{application_id}/submit", {}, headers
        )

    def determine_eligibility(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/applications/{application_id}/eligibility",
            payload,
            headers,
        )

    def withdraw_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/applications/{application_id}/withdraw", {}, headers
        )

    # ------------------------------------------------------------------
    # WorkSample
    # ------------------------------------------------------------------
    def create_work_sample(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/work-samples", payload, headers)

    def list_work_samples(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/work-samples", params or {}, headers)

    def get_work_sample(self, work_sample_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/work-samples/{work_sample_id}", None, headers
        )

    def screen_work_sample(
        self, work_sample_id: str, disposition: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/work-samples/{work_sample_id}/screen",
            {"disposition": disposition},
            headers,
        )

    def redact_work_sample(self, work_sample_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/work-samples/{work_sample_id}/redact", {}, headers
        )

    # ------------------------------------------------------------------
    # Panel
    # ------------------------------------------------------------------
    def create_panel(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/panels", payload, headers)

    def list_panels(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/panels", params or {}, headers)

    def get_panel(self, panel_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/panels/{panel_id}", None, headers)

    def charter_panel(self, panel_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/panels/{panel_id}/charter", {}, headers)

    def open_round(self, panel_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/panels/{panel_id}/open-round", {}, headers
        )

    def close_round(self, panel_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/panels/{panel_id}/close-round", {}, headers
        )

    def submit_slate(
        self, panel_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"{PREFIX}/panels/{panel_id}/slate", payload, headers)

    # ------------------------------------------------------------------
    # Panelist
    # ------------------------------------------------------------------
    def create_panelist(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/panelists", payload, headers)

    def list_panelists(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/panelists", params or {}, headers)

    def get_panelist(self, panelist_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/panelists/{panelist_id}", None, headers)

    def seat_panelist(self, panelist_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/panelists/{panelist_id}/seat", {}, headers
        )

    def resign_panelist(self, panelist_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/panelists/{panelist_id}/resign", {}, headers
        )

    # ------------------------------------------------------------------
    # ConflictDeclaration
    # ------------------------------------------------------------------
    def create_conflict(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/conflicts", payload, headers)

    def list_conflicts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/conflicts", params or {}, headers)

    def get_conflict(self, conflict_declaration_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/conflicts/{conflict_declaration_id}", None, headers
        )

    def screen_conflict(
        self,
        conflict_declaration_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"{PREFIX}/conflicts/{conflict_declaration_id}/screen",
            payload,
            headers,
        )

    def waive_override_conflict(
        self,
        conflict_declaration_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"{PREFIX}/conflicts/{conflict_declaration_id}/waive-override",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Review
    # ------------------------------------------------------------------
    def create_review(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/reviews", payload, headers)

    def list_reviews(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/reviews", params or {}, headers)

    def get_review(self, review_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/reviews/{review_id}", None, headers)

    def submit_review(self, review_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/reviews/{review_id}/submit", {}, headers
        )

    # ------------------------------------------------------------------
    # RecommendationSlot
    # ------------------------------------------------------------------
    def list_slots(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/recommendation-slots", params or {}, headers
        )

    def get_slot(self, recommendation_slot_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"{PREFIX}/recommendation-slots/{recommendation_slot_id}",
            None,
            headers,
        )

    def board_action(
        self,
        recommendation_slot_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"{PREFIX}/recommendation-slots/{recommendation_slot_id}/board-action",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Award
    # ------------------------------------------------------------------
    def list_awards(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/awards", params or {}, headers)

    def get_award(self, award_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/awards/{award_id}", None, headers)

    def accept_award(
        self, award_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/awards/{award_id}/accept", payload, headers
        )

    def decline_award(self, award_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/awards/{award_id}/decline", {}, headers)

    def rescind_award(
        self, award_id: str, rescind_reason_code: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/awards/{award_id}/rescind",
            {"rescind_reason_code": rescind_reason_code},
            headers,
        )

    def get_tax_report(
        self, award_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/awards/{award_id}/tax-report", params or {}, headers
        )

    # ------------------------------------------------------------------
    # PaymentInstallment
    # ------------------------------------------------------------------
    def list_installments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/payment-installments", params or {}, headers
        )

    def get_installment(self, payment_installment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/payment-installments/{payment_installment_id}", None, headers
        )

    def release_installment(self, payment_installment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/payment-installments/{payment_installment_id}/release",
            {},
            headers,
        )

    def pay_installment(self, payment_installment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/payment-installments/{payment_installment_id}/pay",
            {},
            headers,
        )

    def reverse_installment(
        self,
        payment_installment_id: str,
        reversal_reason_code: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"{PREFIX}/payment-installments/{payment_installment_id}/reverse",
            {"reversal_reason_code": reversal_reason_code},
            headers,
        )

    # ------------------------------------------------------------------
    # FinalReport
    # ------------------------------------------------------------------
    def create_final_report(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/final-reports", payload, headers)

    def list_final_reports(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/final-reports", params or {}, headers)

    def get_final_report(self, final_report_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/final-reports/{final_report_id}", None, headers
        )

    def review_final_report(
        self, final_report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/final-reports/{final_report_id}/review", payload, headers
        )

    def resubmit_final_report(
        self, final_report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/final-reports/{final_report_id}/resubmit",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Appeal
    # ------------------------------------------------------------------
    def create_appeal(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/appeals", payload, headers)

    def list_appeals(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/appeals", params or {}, headers)

    def get_appeal(self, appeal_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/appeals/{appeal_id}", None, headers)

    def screen_appeal(self, appeal_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/appeals/{appeal_id}/screen", {}, headers
        )

    def decide_appeal(
        self, appeal_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/appeals/{appeal_id}/decide", payload, headers
        )


api_client = ApiClient()
