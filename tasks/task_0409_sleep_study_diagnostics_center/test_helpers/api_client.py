"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Patient ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    # ---- Referral ----
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def request_auth(self, referral_id, headers):
        return self._request(
            "POST", f"/referrals/{referral_id}/request-auth", {}, headers
        )

    def approve_auth(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/referrals/{referral_id}/approve-auth", payload, headers
        )

    def deny_auth(self, referral_id, headers):
        return self._request(
            "POST", f"/referrals/{referral_id}/deny-auth", {}, headers
        )

    def cancel_referral(self, referral_id, headers):
        return self._request(
            "POST", f"/referrals/{referral_id}/cancel", {}, headers
        )

    # ---- SleepBed ----
    def create_bed(self, payload, headers):
        return self._request("POST", "/beds", payload, headers)

    def list_beds(self, headers, params=None):
        return self._request("GET", "/beds", headers=headers, params=params)

    def get_bed(self, bed_id, headers):
        return self._request("GET", f"/beds/{bed_id}", headers=headers)

    def set_bed_out_of_service(self, bed_id, headers):
        return self._request(
            "POST", f"/beds/{bed_id}/set-out-of-service", {}, headers
        )

    # ---- StudyOrder ----
    def create_study_order(self, payload, headers):
        return self._request("POST", "/study-orders", payload, headers)

    def list_study_orders(self, headers, params=None):
        return self._request("GET", "/study-orders", headers=headers, params=params)

    def get_study_order(self, study_order_id, headers):
        return self._request("GET", f"/study-orders/{study_order_id}", headers=headers)

    def schedule_study(self, study_order_id, payload, headers):
        return self._request(
            "POST", f"/study-orders/{study_order_id}/schedule", payload, headers
        )

    def start_study(self, study_order_id, headers):
        return self._request(
            "POST", f"/study-orders/{study_order_id}/start", {}, headers
        )

    def score_study(self, study_order_id, payload, headers):
        return self._request(
            "POST", f"/study-orders/{study_order_id}/score", payload, headers
        )

    def cancel_study(self, study_order_id, headers):
        return self._request(
            "POST", f"/study-orders/{study_order_id}/cancel", {}, headers
        )

    def list_scoring_reports_for_study(self, study_order_id, headers, params=None):
        return self._request(
            "GET",
            f"/study-orders/{study_order_id}/scoring-reports",
            headers=headers,
            params=params,
        )

    def list_follow_ups_for_study(self, study_order_id, headers, params=None):
        return self._request(
            "GET",
            f"/study-orders/{study_order_id}/follow-ups",
            headers=headers,
            params=params,
        )

    # ---- ScoringReport ----
    def get_scoring_report(self, scoring_report_id, headers):
        return self._request(
            "GET", f"/scoring-reports/{scoring_report_id}", headers=headers
        )

    def interpret_scoring_report(self, scoring_report_id, payload, headers):
        return self._request(
            "POST", f"/scoring-reports/{scoring_report_id}/interpret", payload, headers
        )

    def return_scoring_report(self, scoring_report_id, headers):
        return self._request(
            "POST", f"/scoring-reports/{scoring_report_id}/return", {}, headers
        )

    # ---- DMEOrder ----
    def create_dme_order(self, payload, headers):
        return self._request("POST", "/dme-orders", payload, headers)

    def list_dme_orders(self, headers, params=None):
        return self._request("GET", "/dme-orders", headers=headers, params=params)

    def get_dme_order(self, dme_order_id, headers):
        return self._request("GET", f"/dme-orders/{dme_order_id}", headers=headers)

    def submit_dme_order(self, dme_order_id, headers):
        return self._request(
            "POST", f"/dme-orders/{dme_order_id}/submit", {}, headers
        )

    def fulfill_dme_order(self, dme_order_id, headers):
        return self._request(
            "POST", f"/dme-orders/{dme_order_id}/fulfill", {}, headers
        )

    def cancel_dme_order(self, dme_order_id, headers):
        return self._request(
            "POST", f"/dme-orders/{dme_order_id}/cancel", {}, headers
        )

    def list_compliance_records_for_dme(self, dme_order_id, headers, params=None):
        return self._request(
            "GET",
            f"/dme-orders/{dme_order_id}/compliance-records",
            headers=headers,
            params=params,
        )

    # ---- ComplianceRecord ----
    def create_compliance_record(self, payload, headers):
        return self._request("POST", "/compliance-records", payload, headers)

    def get_compliance_record(self, compliance_record_id, headers):
        return self._request(
            "GET", f"/compliance-records/{compliance_record_id}", headers=headers
        )

    # ---- FollowUp ----
    def create_follow_up(self, payload, headers):
        return self._request("POST", "/follow-ups", payload, headers)

    def get_follow_up(self, follow_up_id, headers):
        return self._request("GET", f"/follow-ups/{follow_up_id}", headers=headers)

    def complete_follow_up(self, follow_up_id, payload, headers):
        return self._request(
            "POST", f"/follow-ups/{follow_up_id}/complete", payload, headers
        )

    def no_show_follow_up(self, follow_up_id, headers):
        return self._request(
            "POST", f"/follow-ups/{follow_up_id}/no-show", {}, headers
        )

    def cancel_follow_up(self, follow_up_id, headers):
        return self._request(
            "POST", f"/follow-ups/{follow_up_id}/cancel", {}, headers
        )


api_client = ApiClient()
