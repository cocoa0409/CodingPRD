"""API client: one method per endpoint defined in the PRD (PRD section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Logical clock -----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ----- FacilitySite -----
    def create_facility_site(self, payload, headers):
        return self._request("POST", "/facility-sites", payload, headers)

    def get_facility_site(self, site_id, headers):
        return self._request("GET", f"/facility-sites/{site_id}", headers=headers)

    def list_facility_sites(self, headers, params=None):
        return self._request("GET", "/facility-sites", headers=headers, params=params)

    def archive_facility_site(self, site_id, headers):
        return self._request("POST", f"/facility-sites/{site_id}/archive", {}, headers)

    def release_facility_site(self, site_id, headers):
        return self._request("POST", f"/facility-sites/{site_id}/release", {}, headers)

    # ----- Pod -----
    def create_pod(self, payload, headers):
        return self._request("POST", "/pods", payload, headers)

    def get_pod(self, pod_id, headers):
        return self._request("GET", f"/pods/{pod_id}", headers=headers)

    def list_pods(self, headers, params=None):
        return self._request("GET", "/pods", headers=headers, params=params)

    def open_enrollment(self, pod_id, headers):
        return self._request("POST", f"/pods/{pod_id}/open-enrollment", {}, headers)

    def revert_to_draft(self, pod_id, headers):
        return self._request("POST", f"/pods/{pod_id}/revert-to-draft", {}, headers)

    def suspend_pod(self, pod_id, headers):
        return self._request("POST", f"/pods/{pod_id}/suspend", {}, headers)

    def reinstate_pod(self, pod_id, headers):
        return self._request("POST", f"/pods/{pod_id}/reinstate", {}, headers)

    def dissolve_pod(self, pod_id, payload, headers):
        return self._request("POST", f"/pods/{pod_id}/dissolve", payload, headers)

    def finalize_dissolution(self, pod_id, headers):
        return self._request("POST", f"/pods/{pod_id}/finalize-dissolution", {}, headers)

    # ----- SafetyPolicy -----
    def create_safety_policy(self, pod_id, payload, headers):
        return self._request("POST", f"/pods/{pod_id}/safety-policies", payload, headers)

    def list_safety_policies_for_pod(self, pod_id, headers, params=None):
        return self._request("GET", f"/pods/{pod_id}/safety-policies", headers=headers, params=params)

    def get_safety_policy(self, policy_id, headers):
        return self._request("GET", f"/safety-policies/{policy_id}", headers=headers)

    def list_safety_policies(self, headers, params=None):
        return self._request("GET", "/safety-policies", headers=headers, params=params)

    def approve_safety_policy(self, pod_id, policy_id, headers):
        return self._request(
            "POST", f"/pods/{pod_id}/safety-policies/{policy_id}/approve", {}, headers
        )

    # ----- CurriculumPlan -----
    def create_curriculum_plan(self, pod_id, payload, headers):
        return self._request("POST", f"/pods/{pod_id}/curriculum-plans", payload, headers)

    def list_curriculum_plans_for_pod(self, pod_id, headers, params=None):
        return self._request("GET", f"/pods/{pod_id}/curriculum-plans", headers=headers, params=params)

    def get_curriculum_plan(self, plan_id, headers):
        return self._request("GET", f"/curriculum-plans/{plan_id}", headers=headers)

    def list_curriculum_plans(self, headers, params=None):
        return self._request("GET", "/curriculum-plans", headers=headers, params=params)

    def submit_curriculum_plan(self, pod_id, plan_id, headers):
        return self._request(
            "POST", f"/pods/{pod_id}/curriculum-plans/{plan_id}/submit", {}, headers
        )

    def approve_curriculum_plan(self, pod_id, plan_id, headers):
        return self._request(
            "POST", f"/pods/{pod_id}/curriculum-plans/{plan_id}/approve", {}, headers
        )

    def revise_curriculum_plan(self, pod_id, plan_id, headers):
        return self._request(
            "POST", f"/pods/{pod_id}/curriculum-plans/{plan_id}/revise", {}, headers
        )

    # ----- LicensingDetermination -----
    def create_licensing_determination(self, pod_id, payload, headers):
        return self._request("POST", f"/pods/{pod_id}/licensing-determinations", payload, headers)

    def list_licensing_determinations_for_pod(self, pod_id, headers, params=None):
        return self._request(
            "GET", f"/pods/{pod_id}/licensing-determinations", headers=headers, params=params
        )

    def get_licensing_determination(self, det_id, headers):
        return self._request("GET", f"/licensing-determinations/{det_id}", headers=headers)

    def list_licensing_determinations(self, headers, params=None):
        return self._request("GET", "/licensing-determinations", headers=headers, params=params)

    def begin_review_licensing_determination(self, pod_id, det_id, headers):
        return self._request(
            "POST",
            f"/pods/{pod_id}/licensing-determinations/{det_id}/begin-review",
            {},
            headers,
        )

    def decide_licensing_determination(self, pod_id, det_id, payload, headers):
        return self._request(
            "POST",
            f"/pods/{pod_id}/licensing-determinations/{det_id}/decide",
            payload,
            headers,
        )

    def resubmit_licensing_determination(self, pod_id, det_id, payload, headers):
        return self._request(
            "POST",
            f"/pods/{pod_id}/licensing-determinations/{det_id}/resubmit",
            payload,
            headers,
        )

    # ----- Guide -----
    def create_guide(self, payload, headers):
        return self._request("POST", "/guides", payload, headers)

    def get_guide(self, guide_id, headers):
        return self._request("GET", f"/guides/{guide_id}", headers=headers)

    def activate_guide(self, guide_id, headers):
        return self._request("POST", f"/guides/{guide_id}/activate", {}, headers)

    def deactivate_guide(self, guide_id, headers):
        return self._request("POST", f"/guides/{guide_id}/deactivate", {}, headers)

    # ----- GuideAssignment -----
    def create_guide_assignment(self, pod_id, payload, headers):
        return self._request("POST", f"/pods/{pod_id}/guide-assignments", payload, headers)

    def list_guide_assignments_for_pod(self, pod_id, headers, params=None):
        return self._request("GET", f"/pods/{pod_id}/guide-assignments", headers=headers, params=params)

    def get_guide_assignment(self, asg_id, headers):
        return self._request("GET", f"/guide-assignments/{asg_id}", headers=headers)

    def list_guide_assignments(self, headers, params=None):
        return self._request("GET", "/guide-assignments", headers=headers, params=params)

    def terminate_guide_assignment(self, pod_id, asg_id, headers):
        return self._request(
            "POST", f"/pods/{pod_id}/guide-assignments/{asg_id}/terminate", {}, headers
        )

    # ----- Family & Student -----
    def create_family(self, payload, headers):
        return self._request("POST", "/families", payload, headers)

    def get_family(self, family_id, headers):
        return self._request("GET", f"/families/{family_id}", headers=headers)

    def list_students_of_family(self, family_id, headers, params=None):
        return self._request("GET", f"/families/{family_id}/students", headers=headers, params=params)

    def create_student(self, family_id, payload, headers):
        return self._request("POST", f"/families/{family_id}/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/students", headers=headers, params=params)

    # ----- VoucherAccount -----
    def create_voucher_account(self, student_id, payload, headers):
        return self._request("POST", f"/students/{student_id}/voucher-accounts", payload, headers)

    def get_voucher_account(self, va_id, headers):
        return self._request("GET", f"/voucher-accounts/{va_id}", headers=headers)

    def list_voucher_accounts(self, headers, params=None):
        return self._request("GET", "/voucher-accounts", headers=headers, params=params)

    def verify_voucher_account(self, va_id, headers):
        return self._request("POST", f"/voucher-accounts/{va_id}/verify", {}, headers)

    def reject_voucher_account(self, va_id, headers):
        return self._request("POST", f"/voucher-accounts/{va_id}/reject", {}, headers)

    def release_voucher_account(self, va_id, headers):
        return self._request("POST", f"/voucher-accounts/{va_id}/release", {}, headers)

    # ----- Seat -----
    def create_seat(self, pod_id, payload, headers):
        return self._request("POST", f"/pods/{pod_id}/seats", payload, headers)

    def list_seats_for_pod(self, pod_id, headers, params=None):
        return self._request("GET", f"/pods/{pod_id}/seats", headers=headers, params=params)

    def get_seat(self, seat_id, headers):
        return self._request("GET", f"/seats/{seat_id}", headers=headers)

    def list_seats(self, headers, params=None):
        return self._request("GET", "/seats", headers=headers, params=params)

    def enroll_seat(self, pod_id, seat_id, payload, headers):
        return self._request("POST", f"/pods/{pod_id}/seats/{seat_id}/enroll", payload, headers)

    def withdraw_seat(self, pod_id, seat_id, payload, headers):
        return self._request("POST", f"/pods/{pod_id}/seats/{seat_id}/withdraw", payload, headers)

    # ----- TuitionInvoice -----
    def create_invoice(self, pod_id, seat_id, payload, headers):
        return self._request(
            "POST", f"/pods/{pod_id}/seats/{seat_id}/invoices", payload, headers
        )

    def list_invoices_for_seat(self, pod_id, seat_id, headers, params=None):
        return self._request(
            "GET", f"/pods/{pod_id}/seats/{seat_id}/invoices", headers=headers, params=params
        )

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def issue_invoice(self, pod_id, seat_id, invoice_id, headers):
        return self._request(
            "POST",
            f"/pods/{pod_id}/seats/{seat_id}/invoices/{invoice_id}/issue",
            {},
            headers,
        )

    def write_off_invoice(self, pod_id, seat_id, invoice_id, headers):
        return self._request(
            "POST",
            f"/pods/{pod_id}/seats/{seat_id}/invoices/{invoice_id}/write-off",
            {},
            headers,
        )

    # ----- Payment -----
    def create_payment(self, pod_id, seat_id, invoice_id, payload, headers):
        return self._request(
            "POST",
            f"/pods/{pod_id}/seats/{seat_id}/invoices/{invoice_id}/payments",
            payload,
            headers,
        )

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def list_payments_for_invoice(self, pod_id, seat_id, invoice_id, headers, params=None):
        return self._request(
            "GET",
            f"/pods/{pod_id}/seats/{seat_id}/invoices/{invoice_id}/payments",
            headers=headers,
            params=params,
        )

    def clear_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/clear", {}, headers)

    def fail_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/fail", {}, headers)

    def reverse_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/reverse", {}, headers)

    # ----- ProgressConference -----
    def create_progress_conference(self, pod_id, payload, headers):
        return self._request("POST", f"/pods/{pod_id}/progress-conferences", payload, headers)

    def list_progress_conferences_for_pod(self, pod_id, headers, params=None):
        return self._request(
            "GET", f"/pods/{pod_id}/progress-conferences", headers=headers, params=params
        )

    def get_progress_conference(self, conf_id, headers):
        return self._request("GET", f"/progress-conferences/{conf_id}", headers=headers)

    def list_progress_conferences(self, headers, params=None):
        return self._request("GET", "/progress-conferences", headers=headers, params=params)

    def schedule_progress_conference(self, pod_id, conf_id, headers):
        return self._request(
            "POST", f"/pods/{pod_id}/progress-conferences/{conf_id}/schedule", {}, headers
        )

    def complete_progress_conference(self, pod_id, conf_id, payload, headers):
        return self._request(
            "POST", f"/pods/{pod_id}/progress-conferences/{conf_id}/complete", payload, headers
        )

    def mark_no_show_progress_conference(self, pod_id, conf_id, headers):
        return self._request(
            "POST", f"/pods/{pod_id}/progress-conferences/{conf_id}/mark-no-show", {}, headers
        )

    def reschedule_progress_conference(self, pod_id, conf_id, headers):
        return self._request(
            "POST", f"/pods/{pod_id}/progress-conferences/{conf_id}/reschedule", {}, headers
        )

    def cancel_progress_conference(self, pod_id, conf_id, headers):
        return self._request(
            "POST", f"/pods/{pod_id}/progress-conferences/{conf_id}/cancel", {}, headers
        )

    # ----- RefundClaim -----
    def create_refund_claim(self, pod_id, payload, headers):
        return self._request("POST", f"/pods/{pod_id}/refund-claims", payload, headers)

    def list_refund_claims_for_pod(self, pod_id, headers, params=None):
        return self._request("GET", f"/pods/{pod_id}/refund-claims", headers=headers, params=params)

    def get_refund_claim(self, claim_id, headers):
        return self._request("GET", f"/refund-claims/{claim_id}", headers=headers)

    def list_refund_claims(self, headers, params=None):
        return self._request("GET", "/refund-claims", headers=headers, params=params)

    def begin_review_refund_claim(self, pod_id, claim_id, headers):
        return self._request(
            "POST", f"/pods/{pod_id}/refund-claims/{claim_id}/begin-review", {}, headers
        )

    def decide_refund_claim(self, pod_id, claim_id, payload, headers):
        return self._request(
            "POST", f"/pods/{pod_id}/refund-claims/{claim_id}/decide", payload, headers
        )

    def disburse_refund_claim(self, pod_id, claim_id, headers):
        return self._request(
            "POST", f"/pods/{pod_id}/refund-claims/{claim_id}/disburse", {}, headers
        )


api_client = ApiClient()
