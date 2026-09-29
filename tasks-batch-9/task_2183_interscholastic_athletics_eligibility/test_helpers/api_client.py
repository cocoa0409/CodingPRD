"""API client: one method per endpoint published by the service."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/athletics"


class ApiClient(GenericApiClient):
    # ---- Logical clock ----------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ---- Schools ----------------------------------------------------------
    def create_school(self, payload, headers):
        return self._request("POST", f"{PREFIX}/schools", payload, headers)

    def get_school(self, school_id, headers):
        return self._request("GET", f"{PREFIX}/schools/{school_id}", headers=headers)

    def list_school_staff_credentials(self, school_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/schools/{school_id}/staff-credentials",
            headers=headers, params=params,
        )

    def list_school_playoff_seeds(self, school_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/schools/{school_id}/playoff-seeds",
            headers=headers, params=params,
        )

    # ---- Students ---------------------------------------------------------
    def create_student(self, payload, headers):
        return self._request("POST", f"{PREFIX}/students", payload, headers)

    def post_academic_record(self, student_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/students/{student_id}/academic-record", payload, headers
        )

    def get_student(self, student_id, headers):
        return self._request("GET", f"{PREFIX}/students/{student_id}", headers=headers)

    def list_students(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/students", headers=headers, params=params)

    # ---- Staff credentials ------------------------------------------------
    def create_staff_credential(self, payload, headers):
        return self._request("POST", f"{PREFIX}/staff-credentials", payload, headers)

    def background_check_credential(self, credential_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/staff-credentials/{credential_id}/background-check",
            payload, headers,
        )

    def revoke_credential(self, credential_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/staff-credentials/{credential_id}/revoke", payload, headers
        )

    # ---- Sport seasons ----------------------------------------------------
    def create_sport_season(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sport-seasons", payload, headers)

    def advance_sport_season(self, season_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sport-seasons/{season_id}/advance", payload, headers
        )

    def seed_sport_season(self, season_id, headers):
        return self._request("POST", f"{PREFIX}/sport-seasons/{season_id}/seed", {}, headers)

    def get_sport_season(self, season_id, headers):
        return self._request("GET", f"{PREFIX}/sport-seasons/{season_id}", headers=headers)

    def list_season_playoff_seeds(self, season_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/sport-seasons/{season_id}/playoff-seeds",
            headers=headers, params=params,
        )

    # ---- Eligibility cases ------------------------------------------------
    def create_eligibility_case(self, payload, headers):
        return self._request("POST", f"{PREFIX}/eligibility-cases", payload, headers)

    def create_clearance_document(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/eligibility-cases/{case_id}/clearance-documents",
            payload, headers,
        )

    def evaluate_case(self, case_id, headers):
        return self._request(
            "POST", f"{PREFIX}/eligibility-cases/{case_id}/evaluate", {}, headers
        )

    def appeal_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/eligibility-cases/{case_id}/appeal", payload, headers
        )

    def activate_case(self, case_id, headers):
        return self._request(
            "POST", f"{PREFIX}/eligibility-cases/{case_id}/activate", {}, headers
        )

    def create_fee_payment(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/eligibility-cases/{case_id}/fee-payments", payload, headers
        )

    def create_fee_waiver_request(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/eligibility-cases/{case_id}/fee-waiver-requests",
            payload, headers,
        )

    def create_fee_waiver_decision(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/eligibility-cases/{case_id}/fee-waiver-decisions",
            payload, headers,
        )

    def create_fee_refund(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/eligibility-cases/{case_id}/fee-refunds", payload, headers
        )

    def get_eligibility_case(self, case_id, headers):
        return self._request(
            "GET", f"{PREFIX}/eligibility-cases/{case_id}", headers=headers
        )

    def list_eligibility_cases(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/eligibility-cases", headers=headers, params=params
        )

    def list_clearance_documents(self, case_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/eligibility-cases/{case_id}/clearance-documents",
            headers=headers, params=params,
        )

    # ---- Contests ---------------------------------------------------------
    def create_contest(self, payload, headers):
        return self._request("POST", f"{PREFIX}/contests", payload, headers)

    def offer_official(self, contest_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/contests/{contest_id}/officials", payload, headers
        )

    def respond_to_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/official-assignments/{assignment_id}/respond",
            payload, headers,
        )

    def confirm_contest(self, contest_id, headers):
        return self._request("POST", f"{PREFIX}/contests/{contest_id}/confirm", {}, headers)

    def postpone_contest(self, contest_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/contests/{contest_id}/postpone", payload, headers
        )

    def record_contest_result(self, contest_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/contests/{contest_id}/result", payload, headers
        )

    def forfeit_contest(self, contest_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/contests/{contest_id}/forfeit", payload, headers
        )

    def get_contest(self, contest_id, headers):
        return self._request("GET", f"{PREFIX}/contests/{contest_id}", headers=headers)

    def list_contests(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/contests", headers=headers, params=params)

    # ---- Officials --------------------------------------------------------
    def create_official(self, payload, headers):
        return self._request("POST", f"{PREFIX}/officials", payload, headers)

    def get_official_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/official-assignments/{assignment_id}", headers=headers
        )

    def list_official_assignments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/official-assignments", headers=headers, params=params
        )

    # ---- Transport --------------------------------------------------------
    def create_transport_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/transport-requests", payload, headers)

    def approve_transport_request(self, transport_request_id, headers):
        return self._request(
            "POST", f"{PREFIX}/transport-requests/{transport_request_id}/approve",
            {}, headers,
        )

    def cancel_transport_request(self, transport_request_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/transport-requests/{transport_request_id}/cancel",
            payload, headers,
        )

    def get_transport_request(self, transport_request_id, headers):
        return self._request(
            "GET", f"{PREFIX}/transport-requests/{transport_request_id}", headers=headers
        )

    def list_transport_requests(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/transport-requests", headers=headers, params=params
        )

    # ---- Injury reports ---------------------------------------------------
    def create_injury_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/injury-reports", payload, headers)

    def advance_injury_stage(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/injury-reports/{report_id}/advance-stage", payload, headers
        )

    def clear_injury_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/injury-reports/{report_id}/clear", payload, headers
        )

    def get_injury_report(self, report_id, headers):
        return self._request(
            "GET", f"{PREFIX}/injury-reports/{report_id}", headers=headers
        )

    def list_injury_reports(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/injury-reports", headers=headers, params=params
        )


api_client = ApiClient()
