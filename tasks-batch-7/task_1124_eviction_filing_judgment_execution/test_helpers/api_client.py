"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Landlords / units / tenancies (PRD 3.1) ---
    def create_landlord(self, payload, headers):
        return self._request("POST", "/api/landlords", payload, headers)

    def get_landlord(self, landlord_id, headers):
        return self._request("GET", f"/api/landlords/{landlord_id}", headers=headers)

    def list_landlords(self, headers, params=None):
        return self._request("GET", "/api/landlords", headers=headers, params=params)

    def create_unit(self, payload, headers):
        return self._request("POST", "/api/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/api/units/{unit_id}", headers=headers)

    def list_landlord_units(self, landlord_id, headers, params=None):
        return self._request(
            "GET", f"/api/landlords/{landlord_id}/units", headers=headers, params=params
        )

    def create_tenancy(self, payload, headers):
        return self._request("POST", "/api/tenancies", payload, headers)

    def get_tenancy(self, tenancy_id, headers):
        return self._request("GET", f"/api/tenancies/{tenancy_id}", headers=headers)

    def list_unit_tenancies(self, unit_id, headers, params=None):
        return self._request(
            "GET", f"/api/units/{unit_id}/tenancies", headers=headers, params=params
        )

    # --- Cases / notices (PRD 3.2) ---
    def create_case(self, payload, headers):
        return self._request("POST", "/api/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/api/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/api/cases", headers=headers, params=params)

    def list_tenancy_cases(self, tenancy_id, headers, params=None):
        return self._request(
            "GET", f"/api/tenancies/{tenancy_id}/cases", headers=headers, params=params
        )

    def dismiss_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/dismiss", payload, headers)

    def create_notice(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/notices", payload, headers)

    def get_notice(self, notice_id, headers):
        return self._request("GET", f"/api/notices/{notice_id}", headers=headers)

    def list_case_notices(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/api/cases/{case_id}/notices", headers=headers, params=params
        )

    def record_cure(self, notice_id, payload, headers):
        return self._request(
            "POST", f"/api/notices/{notice_id}/record-cure", payload, headers
        )

    # --- Filing packages (PRD 3.3) ---
    def create_filing_package(self, case_id, payload, headers):
        return self._request(
            "POST", f"/api/cases/{case_id}/filing-packages", payload, headers
        )

    def get_filing_package(self, package_id, headers):
        return self._request(
            "GET", f"/api/filing-packages/{package_id}", headers=headers
        )

    def list_case_filing_packages(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/api/cases/{case_id}/filing-packages", headers=headers, params=params
        )

    def record_fee_payment(self, package_id, payload, headers):
        return self._request(
            "POST", f"/api/filing-packages/{package_id}/fee-payments", payload, headers
        )

    def review_filing_package(self, package_id, payload, headers):
        return self._request(
            "POST", f"/api/filing-packages/{package_id}/review", payload, headers
        )

    # --- Service of process (PRD 3.4) ---
    def create_service_attempt(self, case_id, payload, headers):
        return self._request(
            "POST", f"/api/cases/{case_id}/service-attempts", payload, headers
        )

    def list_case_service_attempts(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/api/cases/{case_id}/service-attempts", headers=headers, params=params
        )

    # --- Hearings / answers / mediation (PRD 3.5) ---
    def create_hearing(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/hearings", payload, headers)

    def get_hearing(self, hearing_id, headers):
        return self._request("GET", f"/api/hearings/{hearing_id}", headers=headers)

    def list_case_hearings(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/api/cases/{case_id}/hearings", headers=headers, params=params
        )

    def continue_hearing(self, hearing_id, payload, headers):
        return self._request(
            "POST", f"/api/hearings/{hearing_id}/continuance", payload, headers
        )

    def conclude_hearing(self, hearing_id, payload, headers):
        return self._request(
            "POST", f"/api/hearings/{hearing_id}/conclude", payload, headers
        )

    def create_answer(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/answers", payload, headers)

    def get_answer(self, answer_id, headers):
        return self._request("GET", f"/api/answers/{answer_id}", headers=headers)

    def list_case_answers(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/api/cases/{case_id}/answers", headers=headers, params=params
        )

    def create_mediation_referral(self, answer_id, payload, headers):
        return self._request(
            "POST", f"/api/answers/{answer_id}/mediation-referrals", payload, headers
        )

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/api/referrals/{referral_id}", headers=headers)

    def list_answer_referrals(self, answer_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/answers/{answer_id}/mediation-referrals",
            headers=headers,
            params=params,
        )

    def record_referral_outcome(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/api/referrals/{referral_id}/outcome", payload, headers
        )

    # --- Judgment (PRD 3.6) ---
    def enter_judgment(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/judgment", payload, headers)

    def get_judgment(self, judgment_id, headers):
        return self._request("GET", f"/api/judgments/{judgment_id}", headers=headers)

    def get_case_judgment(self, case_id, headers):
        return self._request("GET", f"/api/cases/{case_id}/judgment", headers=headers)

    # --- Writs / lockout / storage (PRD 3.7) ---
    def request_writ(self, judgment_id, payload, headers):
        return self._request(
            "POST", f"/api/judgments/{judgment_id}/writs", payload, headers
        )

    def get_writ(self, writ_id, headers):
        return self._request("GET", f"/api/writs/{writ_id}", headers=headers)

    def list_judgment_writs(self, judgment_id, headers, params=None):
        return self._request(
            "GET", f"/api/judgments/{judgment_id}/writs", headers=headers, params=params
        )

    def issue_writ(self, writ_id, headers):
        return self._request("POST", f"/api/writs/{writ_id}/issue", {}, headers)

    def schedule_lockout(self, writ_id, payload, headers):
        return self._request(
            "POST", f"/api/writs/{writ_id}/schedule-lockout", payload, headers
        )

    def cancel_lockout(self, writ_id, payload, headers):
        return self._request(
            "POST", f"/api/writs/{writ_id}/cancel-lockout", payload, headers
        )

    def execute_writ(self, writ_id, payload, headers):
        return self._request("POST", f"/api/writs/{writ_id}/execute", payload, headers)

    def list_writ_storage_records(self, writ_id, headers, params=None):
        return self._request(
            "GET", f"/api/writs/{writ_id}/storage-records", headers=headers, params=params
        )

    def get_storage_record(self, record_id, headers):
        return self._request(
            "GET", f"/api/storage-records/{record_id}", headers=headers
        )

    def reclaim_storage_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"/api/storage-records/{record_id}/reclaim", payload, headers
        )

    def dispose_storage_record(self, record_id, headers):
        return self._request(
            "POST", f"/api/storage-records/{record_id}/dispose", {}, headers
        )

    # --- Collections (PRD 3.8) ---
    def create_collection_entry(self, judgment_id, payload, headers):
        return self._request(
            "POST", f"/api/judgments/{judgment_id}/collection-entries", payload, headers
        )

    def list_judgment_collection_entries(self, judgment_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/judgments/{judgment_id}/collection-entries",
            headers=headers,
            params=params,
        )

    def get_collection_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/api/collection-entries/{entry_id}", headers=headers
        )

    def list_entry_reversals(self, entry_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/collection-entries/{entry_id}/reversals",
            headers=headers,
            params=params,
        )

    # --- Rental history reports (PRD 3.9) ---
    def create_rental_history_report(self, tenancy_id, payload, headers):
        return self._request(
            "POST",
            f"/api/tenancies/{tenancy_id}/rental-history-reports",
            payload,
            headers,
        )

    def get_rental_history_report(self, report_id, headers):
        return self._request(
            "GET", f"/api/rental-history-reports/{report_id}", headers=headers
        )

    def list_tenancy_rental_history_reports(self, tenancy_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/tenancies/{tenancy_id}/rental-history-reports",
            headers=headers,
            params=params,
        )

    def list_report_corrections(self, report_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/rental-history-reports/{report_id}/corrections",
            headers=headers,
            params=params,
        )

    # --- Ops run / logical clock (PRD 2.5) ---
    def run_ops(self, headers):
        return self._request("POST", "/api/ops/runs", {}, headers)

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
