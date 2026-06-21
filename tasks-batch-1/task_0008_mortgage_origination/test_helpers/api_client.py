"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Applicants ----
    def create_applicant(self, payload, headers):
        return self._request("POST", "/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    def list_applicants(self, headers, params=None):
        return self._request("GET", "/applicants", headers=headers, params=params)

    # ---- LoanApplications ----
    def create_loan_application(self, payload, headers):
        return self._request("POST", "/loan-applications", payload, headers)

    def get_loan_application(self, app_id, headers):
        return self._request("GET", f"/loan-applications/{app_id}", headers=headers)

    def list_loan_applications(self, headers, params=None):
        return self._request("GET", "/loan-applications", headers=headers, params=params)

    def prequalify_loan_application(self, app_id, headers):
        return self._request(
            "POST", f"/loan-applications/{app_id}/prequalify", {}, headers
        )

    def submit_for_review_loan_application(self, app_id, headers):
        return self._request(
            "POST", f"/loan-applications/{app_id}/submit-for-review", {}, headers
        )

    def approve_loan_application(self, app_id, headers):
        return self._request(
            "POST", f"/loan-applications/{app_id}/approve", {}, headers
        )

    def deny_loan_application(self, app_id, payload, headers):
        return self._request(
            "POST", f"/loan-applications/{app_id}/deny", payload, headers
        )

    def clear_to_close_loan_application(self, app_id, headers):
        return self._request(
            "POST", f"/loan-applications/{app_id}/clear-to-close", {}, headers
        )

    def close_loan_application(self, app_id, headers):
        return self._request(
            "POST", f"/loan-applications/{app_id}/close", {}, headers
        )

    def withdraw_loan_application(self, app_id, headers):
        return self._request(
            "POST", f"/loan-applications/{app_id}/withdraw", {}, headers
        )

    # ---- IncomeVerifications ----
    def create_income_verification(self, payload, headers):
        return self._request("POST", "/income-verifications", payload, headers)

    def get_income_verification(self, iv_id, headers):
        return self._request(
            "GET", f"/income-verifications/{iv_id}", headers=headers
        )

    def list_income_verifications(self, headers, params=None):
        return self._request(
            "GET", "/income-verifications", headers=headers, params=params
        )

    def accept_income_verification(self, iv_id, headers):
        return self._request(
            "POST", f"/income-verifications/{iv_id}/accept", {}, headers
        )

    def reject_income_verification(self, iv_id, payload, headers):
        return self._request(
            "POST", f"/income-verifications/{iv_id}/reject", payload, headers
        )

    # ---- AssetVerifications ----
    def create_asset_verification(self, payload, headers):
        return self._request("POST", "/asset-verifications", payload, headers)

    def get_asset_verification(self, av_id, headers):
        return self._request(
            "GET", f"/asset-verifications/{av_id}", headers=headers
        )

    def list_asset_verifications(self, headers, params=None):
        return self._request(
            "GET", "/asset-verifications", headers=headers, params=params
        )

    def accept_asset_verification(self, av_id, headers):
        return self._request(
            "POST", f"/asset-verifications/{av_id}/accept", {}, headers
        )

    def reject_asset_verification(self, av_id, payload, headers):
        return self._request(
            "POST", f"/asset-verifications/{av_id}/reject", payload, headers
        )

    # ---- Appraisals ----
    def create_appraisal(self, payload, headers):
        return self._request("POST", "/appraisals", payload, headers)

    def get_appraisal(self, appr_id, headers):
        return self._request("GET", f"/appraisals/{appr_id}", headers=headers)

    def list_appraisals(self, headers, params=None):
        return self._request("GET", "/appraisals", headers=headers, params=params)

    def complete_appraisal(self, appr_id, payload, headers):
        return self._request(
            "POST", f"/appraisals/{appr_id}/complete", payload, headers
        )

    def reconsider_appraisal(self, appr_id, payload, headers):
        return self._request(
            "POST", f"/appraisals/{appr_id}/reconsider", payload, headers
        )

    def confirm_reconsideration_appraisal(self, appr_id, headers):
        return self._request(
            "POST", f"/appraisals/{appr_id}/confirm-reconsideration", {}, headers
        )

    # ---- TitleSearches ----
    def create_title_search(self, payload, headers):
        return self._request("POST", "/title-searches", payload, headers)

    def get_title_search(self, ts_id, headers):
        return self._request("GET", f"/title-searches/{ts_id}", headers=headers)

    def list_title_searches(self, headers, params=None):
        return self._request("GET", "/title-searches", headers=headers, params=params)

    def mark_clear_title_search(self, ts_id, headers):
        return self._request(
            "POST", f"/title-searches/{ts_id}/mark-clear", {}, headers
        )

    def raise_exception_title_search(self, ts_id, payload, headers):
        return self._request(
            "POST", f"/title-searches/{ts_id}/raise-exception", payload, headers
        )

    def cure_title_search(self, ts_id, headers):
        return self._request(
            "POST", f"/title-searches/{ts_id}/cure", {}, headers
        )

    # ---- RateLocks ----
    def create_rate_lock(self, payload, headers):
        return self._request("POST", "/rate-locks", payload, headers)

    def get_rate_lock(self, lock_id, headers):
        return self._request("GET", f"/rate-locks/{lock_id}", headers=headers)

    def list_rate_locks(self, headers, params=None):
        return self._request("GET", "/rate-locks", headers=headers, params=params)

    def extend_rate_lock(self, lock_id, payload, headers):
        return self._request(
            "POST", f"/rate-locks/{lock_id}/extend", payload, headers
        )

    # ---- Disclosures ----
    def create_disclosure(self, payload, headers):
        return self._request("POST", "/disclosures", payload, headers)

    def get_disclosure(self, disc_id, headers):
        return self._request("GET", f"/disclosures/{disc_id}", headers=headers)

    def list_disclosures(self, headers, params=None):
        return self._request("GET", "/disclosures", headers=headers, params=params)

    def deliver_disclosure(self, disc_id, headers):
        return self._request(
            "POST", f"/disclosures/{disc_id}/deliver", {}, headers
        )

    def acknowledge_disclosure(self, disc_id, headers):
        return self._request(
            "POST", f"/disclosures/{disc_id}/acknowledge", {}, headers
        )

    # ---- UDAAPChecks ----
    def create_udaap_check(self, payload, headers):
        return self._request("POST", "/udaap-checks", payload, headers)

    def get_udaap_check(self, check_id, headers):
        return self._request("GET", f"/udaap-checks/{check_id}", headers=headers)

    def list_udaap_checks(self, headers, params=None):
        return self._request("GET", "/udaap-checks", headers=headers, params=params)

    # ---- Test-driving clock (PRD §2.10) ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
