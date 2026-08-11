"""API client: one method per endpoint defined in the PRD.

Every path is mounted at the server root; there is no version prefix and no
URL nesting beyond the action suffixes the PRD itself declares.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- clinics ----------------
    def create_clinic(self, payload, headers):
        return self._request("POST", "/clinics", payload, headers=headers)

    def get_clinic(self, clinic_id, headers):
        return self._request("GET", f"/clinics/{clinic_id}", headers=headers)

    def set_billing_hold(self, clinic_id, payload, headers):
        return self._request(
            "POST", f"/clinics/{clinic_id}/billing-hold", payload, headers=headers
        )

    # ---------------- contracts ----------------
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers=headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def block_purchase(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/block-purchase", payload, headers=headers
        )

    # ---------------- mobile units ----------------
    def create_mobile_unit(self, payload, headers):
        return self._request("POST", "/mobile-units", payload, headers=headers)

    def get_mobile_unit(self, unit_id, headers):
        return self._request("GET", f"/mobile-units/{unit_id}", headers=headers)

    def set_service_status(self, unit_id, payload, headers):
        return self._request(
            "POST", f"/mobile-units/{unit_id}/service-status", payload, headers=headers
        )

    # ---------------- equipment ----------------
    def create_equipment(self, payload, headers):
        return self._request("POST", "/equipment", payload, headers=headers)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/equipment/{equipment_id}", headers=headers)

    def list_equipment(self, headers, params=None):
        return self._request("GET", "/equipment", headers=headers, params=params)

    def assign_equipment(self, equipment_id, payload, headers):
        return self._request(
            "POST", f"/equipment/{equipment_id}/assign", payload, headers=headers
        )

    def calibrate_equipment(self, equipment_id, payload, headers):
        return self._request(
            "POST", f"/equipment/{equipment_id}/calibrate", payload, headers=headers
        )

    # ---------------- people ----------------
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers=headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    def create_specialist(self, payload, headers):
        return self._request("POST", "/specialists", payload, headers=headers)

    def get_specialist(self, specialist_id, headers):
        return self._request("GET", f"/specialists/{specialist_id}", headers=headers)

    # ---------------- routes ----------------
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers=headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/routes", headers=headers, params=params)

    def add_route_stop(self, route_id, payload, headers):
        return self._request(
            "POST", f"/routes/{route_id}/stops", payload, headers=headers
        )

    def publish_route(self, route_id, headers, payload=None):
        return self._request(
            "POST", f"/routes/{route_id}/publish", payload or {}, headers=headers
        )

    def unpublish_route(self, route_id, headers, payload=None):
        return self._request(
            "POST", f"/routes/{route_id}/unpublish", payload or {}, headers=headers
        )

    def dispatch_route(self, route_id, headers, payload=None):
        return self._request(
            "POST", f"/routes/{route_id}/dispatch", payload or {}, headers=headers
        )

    def complete_route(self, route_id, headers, payload=None):
        return self._request(
            "POST", f"/routes/{route_id}/complete", payload or {}, headers=headers
        )

    # ---------------- route stops ----------------
    def get_route_stop(self, stop_id, headers):
        return self._request("GET", f"/route-stops/{stop_id}", headers=headers)

    def list_route_stops(self, headers, params=None):
        return self._request("GET", "/route-stops", headers=headers, params=params)

    def arrive_stop(self, stop_id, headers, payload=None):
        return self._request(
            "POST", f"/route-stops/{stop_id}/arrive", payload or {}, headers=headers
        )

    def depart_stop(self, stop_id, headers, payload=None):
        return self._request(
            "POST", f"/route-stops/{stop_id}/depart", payload or {}, headers=headers
        )

    def cancel_stop(self, stop_id, payload, headers):
        return self._request(
            "POST", f"/route-stops/{stop_id}/cancel", payload, headers=headers
        )

    # ---------------- referrals ----------------
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers=headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def accept_referral(self, referral_id, headers, payload=None):
        return self._request(
            "POST", f"/referrals/{referral_id}/accept", payload or {}, headers=headers
        )

    def reject_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/referrals/{referral_id}/reject", payload, headers=headers
        )

    def return_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/referrals/{referral_id}/return", payload, headers=headers
        )

    def resubmit_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/referrals/{referral_id}/resubmit", payload, headers=headers
        )

    # ---------------- appointments ----------------
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers=headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def cancel_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/cancel", payload, headers=headers
        )

    def no_show_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/no-show", payload, headers=headers
        )

    # ---------------- studies ----------------
    def create_study(self, payload, headers):
        return self._request("POST", "/studies", payload, headers=headers)

    def get_study(self, study_id, headers):
        return self._request("GET", f"/studies/{study_id}", headers=headers)

    def list_studies(self, headers, params=None):
        return self._request("GET", "/studies", headers=headers, params=params)

    def acquire_study(self, study_id, payload, headers):
        return self._request(
            "POST", f"/studies/{study_id}/acquire", payload, headers=headers
        )

    def upload_study(self, study_id, payload, headers):
        return self._request(
            "POST", f"/studies/{study_id}/upload", payload, headers=headers
        )

    def qc_study(self, study_id, payload, headers):
        return self._request(
            "POST", f"/studies/{study_id}/qc", payload, headers=headers
        )

    def escalate_stat(self, study_id, headers, payload=None):
        return self._request(
            "POST", f"/studies/{study_id}/escalate-stat", payload or {}, headers=headers
        )

    def cancel_study(self, study_id, payload, headers):
        return self._request(
            "POST", f"/studies/{study_id}/cancel", payload, headers=headers
        )

    def not_performed_study(self, study_id, payload, headers):
        return self._request(
            "POST", f"/studies/{study_id}/not-performed", payload, headers=headers
        )

    def hold_study(self, study_id, payload, headers):
        return self._request(
            "POST", f"/studies/{study_id}/hold", payload, headers=headers
        )

    def resume_study(self, study_id, payload, headers):
        return self._request(
            "POST", f"/studies/{study_id}/resume", payload, headers=headers
        )

    def repeat_study(self, study_id, payload, headers):
        return self._request(
            "POST", f"/studies/{study_id}/repeat", payload, headers=headers
        )

    def get_study_pricing(self, study_id, headers):
        return self._request("GET", f"/studies/{study_id}/pricing", headers=headers)

    # ---------------- read assignments ----------------
    def create_read_assignment(self, payload, headers):
        return self._request("POST", "/read-assignments", payload, headers=headers)

    def get_read_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/read-assignments/{assignment_id}", headers=headers
        )

    def list_read_assignments(self, headers, params=None):
        return self._request("GET", "/read-assignments", headers=headers, params=params)

    def accept_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/read-assignments/{assignment_id}/accept",
            payload or {},
            headers=headers,
        )

    def decline_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/read-assignments/{assignment_id}/decline", payload, headers=headers
        )

    def hand_back_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST",
            f"/read-assignments/{assignment_id}/hand-back",
            payload,
            headers=headers,
        )

    # ---------------- reports ----------------
    def create_report(self, payload, headers):
        return self._request("POST", "/reports", payload, headers=headers)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/reports/{report_id}", headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/reports", headers=headers, params=params)

    def publish_report(self, report_id, headers, payload=None):
        return self._request(
            "POST", f"/reports/{report_id}/publish", payload or {}, headers=headers
        )

    def retract_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/reports/{report_id}/retract", payload, headers=headers
        )

    # ---------------- equipment QC checks ----------------
    def create_qc_check(self, payload, headers):
        return self._request("POST", "/qc-checks", payload, headers=headers)

    def get_qc_check(self, qc_check_id, headers):
        return self._request("GET", f"/qc-checks/{qc_check_id}", headers=headers)

    def list_qc_checks(self, headers, params=None):
        return self._request("GET", "/qc-checks", headers=headers, params=params)

    # ---------------- peer reviews ----------------
    def create_peer_review(self, payload, headers):
        return self._request("POST", "/peer-reviews", payload, headers=headers)

    def get_peer_review(self, peer_review_id, headers):
        return self._request("GET", f"/peer-reviews/{peer_review_id}", headers=headers)

    def list_peer_reviews(self, headers, params=None):
        return self._request("GET", "/peer-reviews", headers=headers, params=params)

    def submit_peer_review(self, peer_review_id, payload, headers):
        return self._request(
            "POST", f"/peer-reviews/{peer_review_id}/submit", payload, headers=headers
        )

    # ---------------- invoices, lines, ledger, notifications ----------------
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers=headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def post_study_to_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/invoices/{invoice_id}/post-study", payload, headers=headers
        )

    def finalize_invoice(self, invoice_id, headers, payload=None):
        return self._request(
            "POST", f"/invoices/{invoice_id}/finalize", payload or {}, headers=headers
        )

    def get_charge_line(self, charge_line_id, headers):
        return self._request("GET", f"/charge-lines/{charge_line_id}", headers=headers)

    def list_charge_lines(self, headers, params=None):
        return self._request("GET", "/charge-lines", headers=headers, params=params)

    def get_block_ledger_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/block-ledger-entries/{entry_id}", headers=headers
        )

    def list_block_ledger_entries(self, headers, params=None):
        return self._request(
            "GET", "/block-ledger-entries", headers=headers, params=params
        )

    def get_notification(self, notification_id, headers):
        return self._request(
            "GET", f"/notifications/{notification_id}", headers=headers
        )

    def list_notifications(self, headers, params=None):
        return self._request("GET", "/notifications", headers=headers, params=params)

    # ---------------- logical clock ----------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers=headers,
        )


api_client = ApiClient()
