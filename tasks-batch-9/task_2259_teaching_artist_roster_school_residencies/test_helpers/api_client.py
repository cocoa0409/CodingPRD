"""API client: one method per endpoint defined in the PRD (§4)."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- School partners ----------------
    def create_school_partner(self, payload: dict, headers: dict):
        return self._request("POST", "/school-partners", payload, headers)

    def get_school_partner(self, school_partner_id: str, headers: dict):
        return self._request(
            "GET", f"/school-partners/{school_partner_id}", headers=headers
        )

    def create_calendar_blackout(
        self, school_partner_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST",
            f"/school-partners/{school_partner_id}/calendar-blackouts",
            payload,
            headers,
        )

    def list_calendar_blackouts(
        self, school_partner_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"/school-partners/{school_partner_id}/calendar-blackouts",
            headers=headers,
            params=params,
        )

    # ---------------- Teaching artists ----------------
    def create_teaching_artist(self, payload: dict, headers: dict):
        return self._request("POST", "/teaching-artists", payload, headers)

    def get_teaching_artist(self, artist_id: str, headers: dict):
        return self._request("GET", f"/teaching-artists/{artist_id}", headers=headers)

    def list_teaching_artists(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/teaching-artists", headers=headers, params=params)

    def advance_vetting(self, artist_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/teaching-artists/{artist_id}/vetting", payload, headers
        )

    def set_roster_status(self, artist_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/teaching-artists/{artist_id}/roster-status", payload, headers
        )

    def create_portfolio_review(self, artist_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/teaching-artists/{artist_id}/portfolio-reviews", payload, headers
        )

    def list_portfolio_reviews(
        self, artist_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"/teaching-artists/{artist_id}/portfolio-reviews",
            headers=headers,
            params=params,
        )

    def create_screening(self, artist_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/teaching-artists/{artist_id}/screenings", payload, headers
        )

    def list_screenings(
        self, artist_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"/teaching-artists/{artist_id}/screenings",
            headers=headers,
            params=params,
        )

    # ---------------- Arts standards ----------------
    def create_arts_standard(self, payload: dict, headers: dict):
        return self._request("POST", "/arts-standards", payload, headers)

    def list_arts_standards(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/arts-standards", headers=headers, params=params)

    # ---------------- Residencies ----------------
    def create_residency(self, payload: dict, headers: dict):
        return self._request("POST", "/residencies", payload, headers)

    def get_residency(self, residency_id: str, headers: dict):
        return self._request("GET", f"/residencies/{residency_id}", headers=headers)

    def list_residencies(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/residencies", headers=headers, params=params)

    def assign_lead_artist(self, residency_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/residencies/{residency_id}/lead-artist", payload, headers
        )

    def set_residency_status(self, residency_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/residencies/{residency_id}/status", payload, headers
        )

    # ---------------- Lesson plans ----------------
    def create_lesson_plan(self, payload: dict, headers: dict):
        return self._request("POST", "/lesson-plans", payload, headers)

    def get_lesson_plan(self, lesson_plan_id: str, headers: dict):
        return self._request("GET", f"/lesson-plans/{lesson_plan_id}", headers=headers)

    def list_lesson_plans(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/lesson-plans", headers=headers, params=params)

    def review_lesson_plan(self, lesson_plan_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/lesson-plans/{lesson_plan_id}/review", payload, headers
        )

    def revise_lesson_plan(self, lesson_plan_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/lesson-plans/{lesson_plan_id}/revisions", payload, headers
        )

    # ---------------- Sessions ----------------
    def create_session(self, payload: dict, headers: dict):
        return self._request("POST", "/sessions", payload, headers)

    def get_session(self, session_id: str, headers: dict):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/sessions", headers=headers, params=params)

    def confirm_session(self, session_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/sessions/{session_id}/confirm", payload, headers
        )

    def reassign_session(self, session_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/sessions/{session_id}/reassign", payload, headers
        )

    def cancel_session(self, session_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/sessions/{session_id}/cancel", payload, headers)

    def deliver_session(self, session_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/sessions/{session_id}/deliver", payload, headers
        )

    def create_evaluation(self, session_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/sessions/{session_id}/evaluations", payload, headers
        )

    def list_evaluations(
        self, session_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"/sessions/{session_id}/evaluations",
            headers=headers,
            params=params,
        )

    # ---------------- Payment vouchers ----------------
    def create_payment_voucher(self, payload: dict, headers: dict):
        return self._request("POST", "/payment-vouchers", payload, headers)

    def get_payment_voucher(self, voucher_id: str, headers: dict):
        return self._request("GET", f"/payment-vouchers/{voucher_id}", headers=headers)

    def list_payment_vouchers(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/payment-vouchers", headers=headers, params=params)

    def submit_payment_voucher(
        self, voucher_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST", f"/payment-vouchers/{voucher_id}/submit", payload or {}, headers
        )

    def review_payment_voucher(self, voucher_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/payment-vouchers/{voucher_id}/review", payload, headers
        )

    def void_payment_voucher(self, voucher_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/payment-vouchers/{voucher_id}/void", payload, headers
        )

    # ---------------- Funder reports ----------------
    def create_funder_report(self, payload: dict, headers: dict):
        return self._request("POST", "/funder-reports", payload, headers)

    def get_funder_report(self, report_id: str, headers: dict):
        return self._request("GET", f"/funder-reports/{report_id}", headers=headers)

    def list_funder_reports(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/funder-reports", headers=headers, params=params)

    def compile_funder_report(
        self, report_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST", f"/funder-reports/{report_id}/compile", payload or {}, headers
        )

    def certify_funder_report(self, report_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/funder-reports/{report_id}/certify", payload, headers
        )

    # ---------------- Logical clock ----------------
    def set_clock(self, to_iso8601: str, headers: dict):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
