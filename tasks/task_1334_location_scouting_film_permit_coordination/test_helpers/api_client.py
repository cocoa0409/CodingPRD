"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock and ops sweep ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def ops_sweep(self, headers):
        return self._request("POST", "/_ops/sweep", {}, headers)

    # --- Jurisdictions ---
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/jurisdictions/{jurisdiction_id}", headers=headers)

    def list_jurisdictions(self, headers, params=None):
        return self._request("GET", "/jurisdictions", headers=headers, params=params)

    def suspend_jurisdiction(self, jurisdiction_id, headers):
        return self._request("POST", f"/jurisdictions/{jurisdiction_id}/suspend", {}, headers)

    # --- Owners ---
    def create_owner(self, payload, headers):
        return self._request("POST", "/owners", payload, headers)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/owners/{owner_id}", headers=headers)

    def list_owners(self, headers, params=None):
        return self._request("GET", "/owners", headers=headers, params=params)

    # --- Locations ---
    def create_location(self, payload, headers):
        return self._request("POST", "/locations", payload, headers)

    def get_location(self, location_id, headers):
        return self._request("GET", f"/locations/{location_id}", headers=headers)

    def list_locations(self, headers, params=None):
        return self._request("GET", "/locations", headers=headers, params=params)

    def retire_location(self, location_id, headers):
        return self._request("POST", f"/locations/{location_id}/retire", {}, headers)

    # --- Cross-scope read aliases ---
    def get_permit_application_alias(self, application_id, headers):
        return self._request("GET", f"/permit-applications/{application_id}", headers=headers)

    def get_shoot_day_alias(self, shoot_day_id, headers):
        return self._request("GET", f"/shoot-days/{shoot_day_id}", headers=headers)

    def list_location_bookings_at_location(self, location_id, headers, params=None):
        return self._request("GET", f"/locations/{location_id}/location-bookings", headers=headers, params=params)

    def list_scout_packages_at_location(self, location_id, headers, params=None):
        return self._request("GET", f"/locations/{location_id}/scout-packages", headers=headers, params=params)

    def list_owner_agreements_at_location(self, location_id, headers, params=None):
        return self._request("GET", f"/locations/{location_id}/owner-agreements", headers=headers, params=params)

    def list_permit_applications_at_location(self, location_id, headers, params=None):
        return self._request("GET", f"/locations/{location_id}/permit-applications", headers=headers, params=params)

    def list_permit_applications_at_jurisdiction(self, jurisdiction_id, headers, params=None):
        return self._request("GET", f"/jurisdictions/{jurisdiction_id}/permit-applications", headers=headers, params=params)

    def list_amendments_of(self, application_id, headers, params=None):
        return self._request("GET", f"/permit-applications/{application_id}/amendments", headers=headers, params=params)

    def list_street_closures_of_permit(self, application_id, headers, params=None):
        return self._request("GET", f"/permit-applications/{application_id}/street-closures", headers=headers, params=params)

    def list_notifications_of_permit(self, application_id, headers, params=None):
        return self._request("GET", f"/permit-applications/{application_id}/notifications", headers=headers, params=params)

    def list_insurance_certificates_at_jurisdiction(self, jurisdiction_id, headers, params=None):
        return self._request("GET", f"/jurisdictions/{jurisdiction_id}/insurance-certificates", headers=headers, params=params)

    def list_deposit_accounts_at_location(self, location_id, headers, params=None):
        return self._request("GET", f"/locations/{location_id}/deposit-accounts", headers=headers, params=params)

    def list_walkthrough_reports_at_location(self, location_id, headers, params=None):
        return self._request("GET", f"/locations/{location_id}/walkthrough-reports", headers=headers, params=params)

    def list_monitor_assignments_of_day(self, shoot_day_id, headers, params=None):
        return self._request("GET", f"/shoot-days/{shoot_day_id}/monitor-assignments", headers=headers, params=params)

    def list_shoot_days_of_permit(self, application_id, headers, params=None):
        return self._request("GET", f"/permit-applications/{application_id}/shoot-days", headers=headers, params=params)

    def list_shoot_days_at_location(self, location_id, headers, params=None):
        return self._request("GET", f"/locations/{location_id}/shoot-days", headers=headers, params=params)

    def list_complaints_of_day(self, shoot_day_id, headers, params=None):
        return self._request("GET", f"/shoot-days/{shoot_day_id}/complaints", headers=headers, params=params)

    # --- Productions ---
    def create_production(self, payload, headers):
        return self._request("POST", "/productions", payload, headers)

    def get_production(self, production_id, headers):
        return self._request("GET", f"/productions/{production_id}", headers=headers)

    def wrap_production(self, production_id, headers):
        return self._request("POST", f"/productions/{production_id}/wrap", {}, headers)

    def cancel_production(self, production_id, headers):
        return self._request("POST", f"/productions/{production_id}/cancel", {}, headers)

    # --- Location bookings ---
    def create_location_booking(self, production_id, payload, headers):
        return self._request("POST", f"/productions/{production_id}/location-bookings", payload, headers)

    def list_location_bookings(self, production_id, headers, params=None):
        return self._request("GET", f"/productions/{production_id}/location-bookings", headers=headers, params=params)

    def release_location_booking(self, production_id, booking_id, headers):
        return self._request("POST", f"/productions/{production_id}/location-bookings/{booking_id}/release", {}, headers)

    # --- Scout packages ---
    def create_scout_package(self, production_id, payload, headers):
        return self._request("POST", f"/productions/{production_id}/scout-packages", payload, headers)

    def list_scout_packages(self, production_id, headers, params=None):
        return self._request("GET", f"/productions/{production_id}/scout-packages", headers=headers, params=params)

    def get_scout_package(self, production_id, package_id, headers):
        return self._request("GET", f"/productions/{production_id}/scout-packages/{package_id}", headers=headers)

    def submit_scout_package(self, production_id, package_id, headers):
        return self._request("POST", f"/productions/{production_id}/scout-packages/{package_id}/submit", {}, headers)

    def review_scout_package(self, production_id, package_id, decision, headers):
        return self._request("POST", f"/productions/{production_id}/scout-packages/{package_id}/review", {"decision": decision}, headers)

    # --- Owner agreements ---
    def create_owner_agreement(self, production_id, payload, headers):
        return self._request("POST", f"/productions/{production_id}/owner-agreements", payload, headers)

    def list_owner_agreements(self, production_id, headers, params=None):
        return self._request("GET", f"/productions/{production_id}/owner-agreements", headers=headers, params=params)

    def get_owner_agreement(self, production_id, agreement_id, headers):
        return self._request("GET", f"/productions/{production_id}/owner-agreements/{agreement_id}", headers=headers)

    def propose_owner_agreement(self, production_id, agreement_id, proposed_day_rate_cents, headers):
        return self._request("POST", f"/productions/{production_id}/owner-agreements/{agreement_id}/propose",
                             {"proposed_day_rate_cents": proposed_day_rate_cents}, headers)

    def counter_owner_agreement(self, production_id, agreement_id, proposed_day_rate_cents, headers):
        return self._request("POST", f"/productions/{production_id}/owner-agreements/{agreement_id}/counter",
                             {"proposed_day_rate_cents": proposed_day_rate_cents}, headers)

    def accept_owner_agreement(self, production_id, agreement_id, headers):
        return self._request("POST", f"/productions/{production_id}/owner-agreements/{agreement_id}/accept", {}, headers)

    def walk_away_owner_agreement(self, production_id, agreement_id, headers):
        return self._request("POST", f"/productions/{production_id}/owner-agreements/{agreement_id}/walk-away", {}, headers)

    # --- Permit applications ---
    def create_permit_application(self, production_id, payload, headers):
        return self._request("POST", f"/productions/{production_id}/permit-applications", payload, headers)

    def list_permit_applications(self, production_id, headers, params=None):
        return self._request("GET", f"/productions/{production_id}/permit-applications", headers=headers, params=params)

    def get_permit_application(self, production_id, application_id, headers):
        return self._request("GET", f"/productions/{production_id}/permit-applications/{application_id}", headers=headers)

    def submit_permit_application(self, production_id, application_id, headers):
        return self._request("POST", f"/productions/{production_id}/permit-applications/{application_id}/submit", {}, headers)

    def start_review_permit_application(self, production_id, application_id, headers):
        return self._request("POST", f"/productions/{production_id}/permit-applications/{application_id}/start-review", {}, headers)

    def decide_permit_application(self, production_id, application_id, decision, headers):
        return self._request("POST", f"/productions/{production_id}/permit-applications/{application_id}/decide",
                             {"decision": decision}, headers)

    def withdraw_permit_application(self, production_id, application_id, headers):
        return self._request("POST", f"/productions/{production_id}/permit-applications/{application_id}/withdraw", {}, headers)

    # --- Street closures ---
    def create_street_closure(self, production_id, payload, headers):
        return self._request("POST", f"/productions/{production_id}/street-closures", payload, headers)

    def list_street_closures(self, production_id, headers, params=None):
        return self._request("GET", f"/productions/{production_id}/street-closures", headers=headers, params=params)

    def approve_street_closure(self, production_id, closure_id, headers):
        return self._request("POST", f"/productions/{production_id}/street-closures/{closure_id}/approve", {}, headers)

    def cancel_street_closure(self, production_id, closure_id, headers):
        return self._request("POST", f"/productions/{production_id}/street-closures/{closure_id}/cancel", {}, headers)

    # --- Notifications ---
    def create_notification(self, production_id, payload, headers):
        return self._request("POST", f"/productions/{production_id}/notifications", payload, headers)

    def list_notifications(self, production_id, headers, params=None):
        return self._request("GET", f"/productions/{production_id}/notifications", headers=headers, params=params)

    def acknowledge_notification(self, production_id, notification_id, headers):
        return self._request("POST", f"/productions/{production_id}/notifications/{notification_id}/acknowledge", {}, headers)

    # --- Insurance certificates ---
    def create_insurance_certificate(self, production_id, payload, headers):
        return self._request("POST", f"/productions/{production_id}/insurance-certificates", payload, headers)

    def list_insurance_certificates(self, production_id, headers, params=None):
        return self._request("GET", f"/productions/{production_id}/insurance-certificates", headers=headers, params=params)

    def verify_insurance_certificate(self, production_id, certificate_id, headers):
        return self._request("POST", f"/productions/{production_id}/insurance-certificates/{certificate_id}/verify", {}, headers)

    def reject_insurance_certificate(self, production_id, certificate_id, headers):
        return self._request("POST", f"/productions/{production_id}/insurance-certificates/{certificate_id}/reject", {}, headers)

    # --- Deposit accounts ---
    def create_deposit_account(self, production_id, payload, headers):
        return self._request("POST", f"/productions/{production_id}/deposit-accounts", payload, headers)

    def list_deposit_accounts(self, production_id, headers, params=None):
        return self._request("GET", f"/productions/{production_id}/deposit-accounts", headers=headers, params=params)

    def get_deposit_account(self, production_id, account_id, headers):
        return self._request("GET", f"/productions/{production_id}/deposit-accounts/{account_id}", headers=headers)

    def deposit_into_account(self, production_id, account_id, amount_cents, headers):
        return self._request("POST", f"/productions/{production_id}/deposit-accounts/{account_id}/deposit",
                             {"amount_cents": amount_cents}, headers)

    def settle_deposit_account(self, production_id, account_id, awarded_claim_cents, headers):
        return self._request("POST", f"/productions/{production_id}/deposit-accounts/{account_id}/settle",
                             {"awarded_claim_cents": awarded_claim_cents}, headers)

    # --- Walkthrough reports ---
    def create_walkthrough_report(self, production_id, payload, headers):
        return self._request("POST", f"/productions/{production_id}/walkthrough-reports", payload, headers)

    def list_walkthrough_reports(self, production_id, headers, params=None):
        return self._request("GET", f"/productions/{production_id}/walkthrough-reports", headers=headers, params=params)

    def sign_walkthrough_report(self, production_id, report_id, headers):
        return self._request("POST", f"/productions/{production_id}/walkthrough-reports/{report_id}/sign", {}, headers)

    def dispute_walkthrough_report(self, production_id, report_id, headers):
        return self._request("POST", f"/productions/{production_id}/walkthrough-reports/{report_id}/dispute", {}, headers)

    # --- Monitor assignments ---
    def create_monitor_assignment(self, production_id, payload, headers):
        return self._request("POST", f"/productions/{production_id}/monitor-assignments", payload, headers)

    def list_monitor_assignments(self, production_id, headers, params=None):
        return self._request("GET", f"/productions/{production_id}/monitor-assignments", headers=headers, params=params)

    def confirm_monitor_assignment(self, production_id, assignment_id, headers):
        return self._request("POST", f"/productions/{production_id}/monitor-assignments/{assignment_id}/confirm", {}, headers)

    def release_monitor_assignment(self, production_id, assignment_id, headers):
        return self._request("POST", f"/productions/{production_id}/monitor-assignments/{assignment_id}/release", {}, headers)

    def mark_no_show_monitor_assignment(self, production_id, assignment_id, headers):
        return self._request("POST", f"/productions/{production_id}/monitor-assignments/{assignment_id}/mark-no-show", {}, headers)

    def check_in_monitor_assignment(self, production_id, assignment_id, headers):
        return self._request("POST", f"/productions/{production_id}/monitor-assignments/{assignment_id}/check-in", {}, headers)

    # --- Shoot days ---
    def create_shoot_day(self, production_id, payload, headers):
        return self._request("POST", f"/productions/{production_id}/shoot-days", payload, headers)

    def list_shoot_days(self, production_id, headers, params=None):
        return self._request("GET", f"/productions/{production_id}/shoot-days", headers=headers, params=params)

    def get_shoot_day(self, production_id, day_id, headers):
        return self._request("GET", f"/productions/{production_id}/shoot-days/{day_id}", headers=headers)

    def mark_shoot_day_ready(self, production_id, day_id, expected_shoot_day_version, headers):
        return self._request("POST", f"/productions/{production_id}/shoot-days/{day_id}/mark-ready",
                             {"expected_shoot_day_version": expected_shoot_day_version}, headers)

    def complete_shoot_day(self, production_id, day_id, actual_hours, headers):
        return self._request("POST", f"/productions/{production_id}/shoot-days/{day_id}/complete",
                             {"actual_hours": actual_hours}, headers)

    def cancel_shoot_day(self, production_id, day_id, headers):
        return self._request("POST", f"/productions/{production_id}/shoot-days/{day_id}/cancel", {}, headers)

    def shut_down_shoot_day(self, production_id, day_id, headers):
        return self._request("POST", f"/productions/{production_id}/shoot-days/{day_id}/shut-down", {}, headers)

    # --- Complaints ---
    def create_complaint(self, production_id, payload, headers):
        return self._request("POST", f"/productions/{production_id}/complaints", payload, headers)

    def list_complaints(self, production_id, headers, params=None):
        return self._request("GET", f"/productions/{production_id}/complaints", headers=headers, params=params)

    def acknowledge_complaint(self, production_id, complaint_id, headers):
        return self._request("POST", f"/productions/{production_id}/complaints/{complaint_id}/acknowledge", {}, headers)

    def resolve_complaint(self, production_id, complaint_id, resolution_note, headers):
        return self._request("POST", f"/productions/{production_id}/complaints/{complaint_id}/resolve",
                             {"resolution_note": resolution_note}, headers)


api_client = ApiClient()
