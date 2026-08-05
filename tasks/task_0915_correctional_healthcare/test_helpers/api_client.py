"""API client: one method per endpoint defined in the PRD (§4)."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def set_clock_raw(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Inmate ───────────────────────────────────────
    def create_inmate(self, payload, headers):
        return self._request("POST", "/inmates", payload, headers)

    def get_inmate(self, inmate_id, headers):
        return self._request("GET", f"/inmates/{inmate_id}", headers=headers)

    def release_inmate(self, inmate_id, headers):
        return self._request("POST", f"/inmates/{inmate_id}/release", {}, headers)

    def record_death_event(self, inmate_id, payload, headers):
        return self._request("POST", f"/inmates/{inmate_id}/death-event", payload, headers)

    def freeze_records(self, inmate_id, headers):
        return self._request("POST", f"/inmates/{inmate_id}/records-freeze", {}, headers)

    def unfreeze_records(self, inmate_id, headers):
        return self._request("POST", f"/inmates/{inmate_id}/records-unfreeze", {}, headers)

    # ─── Intake screening ─────────────────────────────
    def create_intake_screening(self, inmate_id, payload, headers):
        return self._request(
            "POST", f"/inmates/{inmate_id}/intake-screenings", payload, headers
        )

    def list_intake_screenings(self, inmate_id, headers, params=None):
        return self._request(
            "GET", f"/inmates/{inmate_id}/intake-screenings", headers=headers, params=params
        )

    def dispose_intake_screening(self, screening_id, payload, headers):
        return self._request(
            "POST", f"/intake-screenings/{screening_id}/disposition", payload, headers
        )

    # ─── Chronic care ─────────────────────────────────
    def create_chronic_enrollment(self, inmate_id, payload, headers):
        return self._request(
            "POST", f"/inmates/{inmate_id}/chronic-care-enrollments", payload, headers
        )

    def list_chronic_enrollments(self, inmate_id, headers, params=None):
        return self._request(
            "GET",
            f"/inmates/{inmate_id}/chronic-care-enrollments",
            headers=headers,
            params=params,
        )

    def get_chronic_enrollment(self, enrollment_id, headers):
        return self._request(
            "GET", f"/chronic-care-enrollments/{enrollment_id}", headers=headers
        )

    def re_enroll_chronic(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/chronic-care-enrollments/{enrollment_id}/re-enroll", payload, headers
        )

    def create_chronic_visit(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/chronic-care-enrollments/{enrollment_id}/visits", payload, headers
        )

    def list_chronic_visits(self, enrollment_id, headers, params=None):
        return self._request(
            "GET",
            f"/chronic-care-enrollments/{enrollment_id}/visits",
            headers=headers,
            params=params,
        )

    # ─── Sick call ────────────────────────────────────
    def create_sick_call_request(self, payload, headers):
        return self._request("POST", "/sick-call-requests", payload, headers)

    def list_sick_call_requests(self, headers, params=None):
        return self._request("GET", "/sick-call-requests", headers=headers, params=params)

    def get_sick_call_request(self, request_id, headers):
        return self._request("GET", f"/sick-call-requests/{request_id}", headers=headers)

    def triage_sick_call_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/sick-call-requests/{request_id}/triage", payload, headers
        )

    def schedule_sick_call_request(self, request_id, headers):
        return self._request(
            "POST", f"/sick-call-requests/{request_id}/schedule", {}, headers
        )

    def see_sick_call_request(self, request_id, headers):
        return self._request("POST", f"/sick-call-requests/{request_id}/see", {}, headers)

    def close_sick_call_request(self, request_id, headers):
        return self._request("POST", f"/sick-call-requests/{request_id}/close", {}, headers)

    # ─── Medication orders ────────────────────────────
    def create_medication_order(self, payload, headers):
        return self._request("POST", "/medication-orders", payload, headers)

    def list_medication_orders(self, headers, params=None):
        return self._request("GET", "/medication-orders", headers=headers, params=params)

    def get_medication_order(self, order_id, headers):
        return self._request("GET", f"/medication-orders/{order_id}", headers=headers)

    def set_medication_order_hold(self, order_id, payload, headers):
        return self._request(
            "POST", f"/medication-orders/{order_id}/hold-status", payload, headers
        )

    def discontinue_medication_order(self, order_id, headers):
        return self._request(
            "POST", f"/medication-orders/{order_id}/discontinue", {}, headers
        )

    def record_pill_count(self, order_id, payload, headers):
        return self._request(
            "POST", f"/medication-orders/{order_id}/pill-count", payload, headers
        )

    def create_administration(self, order_id, payload, headers):
        return self._request(
            "POST", f"/medication-orders/{order_id}/administrations", payload, headers
        )

    def list_administrations(self, order_id, headers, params=None):
        return self._request(
            "GET",
            f"/medication-orders/{order_id}/administrations",
            headers=headers,
            params=params,
        )

    def record_administration(self, administration_id, payload, headers):
        return self._request(
            "POST", f"/medication-administrations/{administration_id}/record", payload, headers
        )

    # ─── Specialty referral / utilization review ──────
    def create_specialty_referral(self, payload, headers):
        return self._request("POST", "/specialty-referrals", payload, headers)

    def list_specialty_referrals(self, headers, params=None):
        return self._request("GET", "/specialty-referrals", headers=headers, params=params)

    def get_specialty_referral(self, referral_id, headers):
        return self._request("GET", f"/specialty-referrals/{referral_id}", headers=headers)

    def submit_referral_for_review(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/specialty-referrals/{referral_id}/submit-for-review", payload, headers
        )

    def list_utilization_reviews(self, referral_id, headers, params=None):
        return self._request(
            "GET",
            f"/specialty-referrals/{referral_id}/utilization-reviews",
            headers=headers,
            params=params,
        )

    def decide_utilization_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/utilization-reviews/{review_id}/decide", payload, headers
        )

    def supply_review_information(self, review_id, payload, headers):
        return self._request(
            "POST", f"/utilization-reviews/{review_id}/supply-information", payload, headers
        )

    def escalate_peer_review(self, review_id, headers):
        return self._request(
            "POST", f"/utilization-reviews/{review_id}/escalate-peer-review", {}, headers
        )

    def peer_decide_utilization_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/utilization-reviews/{review_id}/peer-decide", payload, headers
        )

    # ─── Transport ────────────────────────────────────
    def create_transport_order(self, payload, headers):
        return self._request("POST", "/transport-orders", payload, headers)

    def list_transport_orders(self, referral_id, headers, params=None):
        return self._request(
            "GET",
            f"/specialty-referrals/{referral_id}/transport-orders",
            headers=headers,
            params=params,
        )

    def assign_escort(self, transport_id, payload, headers):
        return self._request(
            "POST", f"/transport-orders/{transport_id}/assign-escort", payload, headers
        )

    def dispatch_transport(self, transport_id, headers):
        return self._request(
            "POST", f"/transport-orders/{transport_id}/dispatch", {}, headers
        )

    def record_transport_outcome(self, transport_id, payload, headers):
        return self._request(
            "POST", f"/transport-orders/{transport_id}/outcome", payload, headers
        )

    def cancel_transport(self, transport_id, payload, headers):
        return self._request(
            "POST", f"/transport-orders/{transport_id}/cancel", payload, headers
        )

    # ─── Trust account ────────────────────────────────
    def create_copay_charge(self, inmate_id, payload, headers):
        return self._request(
            "POST", f"/inmates/{inmate_id}/copay-charges", payload, headers
        )

    def list_copay_charges(self, headers, params=None):
        return self._request("GET", "/copay-charges", headers=headers, params=params)

    def get_copay_charge(self, charge_id, headers):
        return self._request("GET", f"/copay-charges/{charge_id}", headers=headers)

    def create_ledger_entry(self, inmate_id, payload, headers):
        return self._request(
            "POST", f"/inmates/{inmate_id}/ledger-entries", payload, headers
        )

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/ledger-entries/{entry_id}", headers=headers)

    # ─── Grievances ───────────────────────────────────
    def create_grievance(self, inmate_id, payload, headers):
        return self._request("POST", f"/inmates/{inmate_id}/grievances", payload, headers)

    def list_grievances(self, headers, params=None):
        return self._request("GET", "/grievances", headers=headers, params=params)

    def get_grievance(self, grievance_id, headers):
        return self._request("GET", f"/grievances/{grievance_id}", headers=headers)

    def accept_grievance(self, grievance_id, headers):
        return self._request("POST", f"/grievances/{grievance_id}/accept", {}, headers)

    def decide_grievance(self, grievance_id, payload, headers):
        return self._request("POST", f"/grievances/{grievance_id}/decide", payload, headers)

    def escalate_grievance(self, grievance_id, headers):
        return self._request("POST", f"/grievances/{grievance_id}/escalate", {}, headers)

    def remand_grievance(self, grievance_id, headers):
        return self._request("POST", f"/grievances/{grievance_id}/remand", {}, headers)

    def close_grievance(self, grievance_id, headers):
        return self._request("POST", f"/grievances/{grievance_id}/close", {}, headers)

    def withdraw_grievance(self, grievance_id, headers):
        return self._request("POST", f"/grievances/{grievance_id}/withdraw", {}, headers)

    # ─── Release planning & mortality review ──────────
    def create_release_plan(self, inmate_id, payload, headers):
        return self._request(
            "POST", f"/inmates/{inmate_id}/release-plans", payload, headers
        )

    def list_release_plans(self, inmate_id, headers, params=None):
        return self._request(
            "GET", f"/inmates/{inmate_id}/release-plans", headers=headers, params=params
        )

    def finalize_release_plan(self, plan_id, headers):
        return self._request("POST", f"/release-plans/{plan_id}/finalize", {}, headers)

    def list_mortality_reviews(self, inmate_id, headers, params=None):
        return self._request(
            "GET", f"/inmates/{inmate_id}/mortality-reviews", headers=headers, params=params
        )

    def add_corrective_action(self, review_id, payload, headers):
        return self._request(
            "POST", f"/mortality-reviews/{review_id}/corrective-actions", payload, headers
        )

    def close_mortality_review(self, review_id, headers):
        return self._request("POST", f"/mortality-reviews/{review_id}/close", {}, headers)

    # ─── Reporting ────────────────────────────────────
    def get_facility_adherence(self, facility_code, headers):
        return self._request(
            "GET",
            "/reports/facility-adherence",
            headers=headers,
            params={"facility_code": facility_code},
        )


api_client = ApiClient()
