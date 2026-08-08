"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- District ----
    def create_district(self, payload, headers):
        return self._request("POST", "/mv/districts", payload, headers)

    def get_district(self, district_id, headers):
        return self._request("GET", f"/mv/districts/{district_id}", headers=headers)

    # ---- Liaison ----
    def create_liaison(self, payload, headers):
        return self._request("POST", "/mv/liaisons", payload, headers)

    def get_liaison(self, liaison_id, headers):
        return self._request("GET", f"/mv/liaisons/{liaison_id}", headers=headers)

    def list_liaisons(self, headers, params=None):
        return self._request("GET", "/mv/liaisons", headers=headers, params=params)

    # ---- Student ----
    def create_student(self, payload, headers):
        return self._request("POST", "/mv/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/mv/students/{student_id}", headers=headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/mv/students", headers=headers, params=params)

    def enroll_student(self, student_id, headers):
        return self._request("POST", f"/mv/students/{student_id}/enroll", {}, headers)

    def withdraw_student(self, student_id, headers):
        return self._request("POST", f"/mv/students/{student_id}/withdraw", {}, headers)

    def assign_liaison(self, student_id, payload, headers):
        return self._request("POST", f"/mv/students/{student_id}/assign-liaison", payload, headers)

    def create_determination(self, student_id, payload, headers):
        return self._request("POST", f"/mv/students/{student_id}/eligibility-determinations", payload, headers)

    # ---- EligibilityDetermination ----
    def get_determination(self, determination_id, headers):
        return self._request("GET", f"/mv/eligibility-determinations/{determination_id}", headers=headers)

    def list_determinations(self, headers, params=None):
        return self._request("GET", "/mv/eligibility-determinations", headers=headers, params=params)

    def finalize_determination(self, determination_id, headers):
        return self._request("POST", f"/mv/eligibility-determinations/{determination_id}/finalize", {}, headers)

    # ---- TransportationPlan ----
    def create_plan(self, payload, headers):
        return self._request("POST", "/mv/transportation-plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/mv/transportation-plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/mv/transportation-plans", headers=headers, params=params)

    def submit_plan(self, plan_id, headers):
        return self._request("POST", f"/mv/transportation-plans/{plan_id}/submit", {}, headers)

    def approve_plan(self, plan_id, headers):
        return self._request("POST", f"/mv/transportation-plans/{plan_id}/approve", {}, headers)

    def deny_plan(self, plan_id, headers):
        return self._request("POST", f"/mv/transportation-plans/{plan_id}/deny", {}, headers)

    def activate_plan(self, plan_id, headers):
        return self._request("POST", f"/mv/transportation-plans/{plan_id}/activate", {}, headers)

    def suspend_plan(self, plan_id, headers):
        return self._request("POST", f"/mv/transportation-plans/{plan_id}/suspend", {}, headers)

    def resume_plan(self, plan_id, headers):
        return self._request("POST", f"/mv/transportation-plans/{plan_id}/resume", {}, headers)

    def terminate_plan(self, plan_id, headers):
        return self._request("POST", f"/mv/transportation-plans/{plan_id}/terminate", {}, headers)

    def plan_cost_summary(self, plan_id, headers):
        return self._request("GET", f"/mv/transportation-plans/{plan_id}/cost-summary", headers=headers)

    # ---- CostShareAgreement ----
    def create_cost_share(self, payload, headers):
        return self._request("POST", "/mv/cost-share-agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/mv/cost-share-agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/mv/cost-share-agreements", headers=headers, params=params)

    def agreement_invoice(self, agreement_id, headers):
        return self._request("GET", f"/mv/cost-share-agreements/{agreement_id}/invoice", headers=headers)

    # ---- Vehicle ----
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/mv/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/mv/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/mv/vehicles", headers=headers, params=params)

    def set_vehicle_status(self, vehicle_id, payload, headers):
        return self._request("POST", f"/mv/vehicles/{vehicle_id}/set-status", payload, headers)

    # ---- TripAssignment ----
    def create_trip(self, payload, headers):
        return self._request("POST", "/mv/trip-assignments", payload, headers)

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"/mv/trip-assignments/{trip_id}", headers=headers)

    def list_trips(self, headers, params=None):
        return self._request("GET", "/mv/trip-assignments", headers=headers, params=params)

    def complete_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/mv/trip-assignments/{trip_id}/complete", payload, headers)

    def cancel_trip(self, trip_id, headers):
        return self._request("POST", f"/mv/trip-assignments/{trip_id}/cancel", {}, headers)

    def void_trip(self, trip_id, headers):
        return self._request("POST", f"/mv/trip-assignments/{trip_id}/void", {}, headers)

    # ---- CostLedgerEntry ----
    def get_ledger_entry(self, ledger_entry_id, headers):
        return self._request("GET", f"/mv/cost-ledger-entries/{ledger_entry_id}", headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/mv/cost-ledger-entries", headers=headers, params=params)

    # ---- BenefitLink ----
    def get_benefit_link(self, benefit_link_id, headers):
        return self._request("GET", f"/mv/benefit-links/{benefit_link_id}", headers=headers)

    def list_benefit_links(self, headers, params=None):
        return self._request("GET", "/mv/benefit-links", headers=headers, params=params)

    def revoke_benefit_link(self, benefit_link_id, headers):
        return self._request("POST", f"/mv/benefit-links/{benefit_link_id}/revoke", {}, headers)

    # ---- Dispute ----
    def create_dispute(self, payload, headers):
        return self._request("POST", "/mv/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/mv/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/mv/disputes", headers=headers, params=params)

    def begin_review(self, dispute_id, headers):
        return self._request("POST", f"/mv/disputes/{dispute_id}/begin-review", {}, headers)

    def request_info(self, dispute_id, headers):
        return self._request("POST", f"/mv/disputes/{dispute_id}/request-info", {}, headers)

    def resubmit_dispute(self, dispute_id, headers):
        return self._request("POST", f"/mv/disputes/{dispute_id}/resubmit", {}, headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/mv/disputes/{dispute_id}/resolve", payload, headers)

    # ---- TutoringReferral ----
    def create_referral(self, payload, headers):
        return self._request("POST", "/mv/tutoring-referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/mv/tutoring-referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/mv/tutoring-referrals", headers=headers, params=params)

    def close_referral(self, referral_id, headers):
        return self._request("POST", f"/mv/tutoring-referrals/{referral_id}/close", {}, headers)

    def cancel_referral(self, referral_id, headers):
        return self._request("POST", f"/mv/tutoring-referrals/{referral_id}/cancel", {}, headers)


api_client = ApiClient()
