"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # --- DistrictProgram ---
    def create_program(self, payload, headers):
        return self._request("POST", "/api/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/api/programs", headers=headers, params=params)

    def get_program(self, prog_id, headers):
        return self._request("GET", f"/api/programs/{prog_id}", headers=headers)

    def activate_program(self, prog_id, headers):
        return self._request("POST", f"/api/programs/{prog_id}/activate", {}, headers)

    def begin_summer_collection(self, prog_id, headers):
        return self._request(
            "POST", f"/api/programs/{prog_id}/begin-summer-collection", {}, headers
        )

    def close_program(self, prog_id, headers):
        return self._request("POST", f"/api/programs/{prog_id}/close", {}, headers)

    # --- AssetFleet ---
    def create_fleet(self, prog_id, payload, headers):
        return self._request("POST", f"/api/programs/{prog_id}/fleets", payload, headers)

    def list_fleets(self, prog_id, headers, params=None):
        return self._request(
            "GET", f"/api/programs/{prog_id}/fleets", headers=headers, params=params
        )

    def get_fleet(self, prog_id, fleet_id, headers):
        return self._request(
            "GET", f"/api/programs/{prog_id}/fleets/{fleet_id}", headers=headers
        )

    # --- AssetUnit ---
    def create_asset_unit(self, prog_id, fleet_id, payload, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/fleets/{fleet_id}/asset-units",
            payload,
            headers,
        )

    def list_asset_units(self, prog_id, fleet_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/programs/{prog_id}/fleets/{fleet_id}/asset-units",
            headers=headers,
            params=params,
        )

    def get_asset_unit(self, prog_id, asset_id, headers):
        return self._request(
            "GET", f"/api/programs/{prog_id}/asset-units/{asset_id}", headers=headers
        )

    def designate_loaner(self, prog_id, asset_id, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/asset-units/{asset_id}/designate-loaner",
            {},
            headers,
        )

    def return_loaner_to_pool(self, prog_id, asset_id, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/asset-units/{asset_id}/return-loaner-to-pool",
            {},
            headers,
        )

    def complete_repair(self, prog_id, asset_id, payload, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/asset-units/{asset_id}/complete-repair",
            payload,
            headers,
        )

    def begin_reimage(self, prog_id, asset_id, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/asset-units/{asset_id}/begin-reimage",
            {},
            headers,
        )

    def complete_reimage(self, prog_id, asset_id, payload, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/asset-units/{asset_id}/complete-reimage",
            payload,
            headers,
        )

    def retire_asset_unit(self, prog_id, asset_id, payload, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/asset-units/{asset_id}/retire",
            payload,
            headers,
        )

    def dispose_asset_unit(self, prog_id, asset_id, headers):
        return self._request(
            "POST", f"/api/programs/{prog_id}/asset-units/{asset_id}/dispose", {}, headers
        )

    def donate_asset_unit(self, prog_id, asset_id, headers):
        return self._request(
            "POST", f"/api/programs/{prog_id}/asset-units/{asset_id}/donate", {}, headers
        )

    def write_off_asset_unit(self, prog_id, asset_id, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/asset-units/{asset_id}/write-off",
            {},
            headers,
        )

    # --- StudentAccount ---
    def create_student(self, prog_id, payload, headers):
        return self._request("POST", f"/api/programs/{prog_id}/students", payload, headers)

    def list_students(self, prog_id, headers, params=None):
        return self._request(
            "GET", f"/api/programs/{prog_id}/students", headers=headers, params=params
        )

    def get_student(self, prog_id, student_id, headers):
        return self._request(
            "GET", f"/api/programs/{prog_id}/students/{student_id}", headers=headers
        )

    def withdraw_student(self, prog_id, student_id, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/students/{student_id}/withdraw",
            {},
            headers,
        )

    def graduate_student(self, prog_id, student_id, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/students/{student_id}/graduate",
            {},
            headers,
        )

    # --- FamilyAgreement ---
    def get_family_agreement(self, prog_id, student_id, headers):
        return self._request(
            "GET",
            f"/api/programs/{prog_id}/students/{student_id}/family-agreement",
            headers=headers,
        )

    def sign_family_agreement(self, prog_id, student_id, payload, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/students/{student_id}/family-agreement/sign",
            payload,
            headers,
        )

    def decline_family_agreement(self, prog_id, student_id, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/students/{student_id}/family-agreement/decline",
            {},
            headers,
        )

    # --- InsurancePolicy ---
    def create_insurance_policy(self, prog_id, student_id, payload, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/students/{student_id}/insurance-policies",
            payload,
            headers,
        )

    def list_insurance_policies(self, prog_id, student_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/programs/{prog_id}/students/{student_id}/insurance-policies",
            headers=headers,
            params=params,
        )

    def get_insurance_policy(self, prog_id, student_id, policy_id, headers):
        return self._request(
            "GET",
            f"/api/programs/{prog_id}/students/{student_id}/insurance-policies/{policy_id}",
            headers=headers,
        )

    def activate_insurance_policy(self, prog_id, student_id, policy_id, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/students/{student_id}/insurance-policies/{policy_id}/activate",
            {},
            headers,
        )

    def cancel_insurance_policy(self, prog_id, student_id, policy_id, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/students/{student_id}/insurance-policies/{policy_id}/cancel",
            {},
            headers,
        )

    def expire_insurance_policies(self, prog_id, headers):
        return self._request(
            "POST", f"/api/programs/{prog_id}/expire-insurance-policies", {}, headers
        )

    # --- Assignment ---
    def create_assignment(self, prog_id, student_id, payload, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/students/{student_id}/assignments",
            payload,
            headers,
        )

    def list_assignments(self, prog_id, student_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/programs/{prog_id}/students/{student_id}/assignments",
            headers=headers,
            params=params,
        )

    def get_assignment(self, prog_id, student_id, assignment_id, headers):
        return self._request(
            "GET",
            f"/api/programs/{prog_id}/students/{student_id}/assignments/{assignment_id}",
            headers=headers,
        )

    def return_assignment(self, prog_id, student_id, assignment_id, payload, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/students/{student_id}/assignments/{assignment_id}/return",
            payload,
            headers,
        )

    def declare_lost(self, prog_id, student_id, assignment_id, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/students/{student_id}/assignments/{assignment_id}/declare-lost",
            {},
            headers,
        )

    # --- DamageReport ---
    def create_damage_report(self, prog_id, student_id, assignment_id, payload, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/students/{student_id}/assignments/{assignment_id}/damage-reports",
            payload,
            headers,
        )

    def list_damage_reports(self, prog_id, student_id, assignment_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/programs/{prog_id}/students/{student_id}/assignments/{assignment_id}/damage-reports",
            headers=headers,
            params=params,
        )

    def get_damage_report(self, prog_id, student_id, assignment_id, report_id, headers):
        return self._request(
            "GET",
            f"/api/programs/{prog_id}/students/{student_id}/assignments/{assignment_id}/damage-reports/{report_id}",
            headers=headers,
        )

    def submit_damage_report(self, prog_id, student_id, assignment_id, report_id, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/students/{student_id}/assignments/{assignment_id}/damage-reports/{report_id}/submit",
            {},
            headers,
        )

    def confirm_damage_report(self, prog_id, student_id, assignment_id, report_id, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/students/{student_id}/assignments/{assignment_id}/damage-reports/{report_id}/confirm",
            {},
            headers,
        )

    def dismiss_damage_report(self, prog_id, student_id, assignment_id, report_id, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/students/{student_id}/assignments/{assignment_id}/damage-reports/{report_id}/dismiss",
            {},
            headers,
        )

    # --- FeeAssessment ---
    def list_fees(self, prog_id, student_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/programs/{prog_id}/students/{student_id}/fees",
            headers=headers,
            params=params,
        )

    def get_fee(self, prog_id, student_id, fee_id, headers):
        return self._request(
            "GET",
            f"/api/programs/{prog_id}/students/{student_id}/fees/{fee_id}",
            headers=headers,
        )

    def appeal_fee(self, prog_id, student_id, fee_id, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/students/{student_id}/fees/{fee_id}/appeal",
            {},
            headers,
        )

    def appeal_grant_fee(self, prog_id, student_id, fee_id, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/students/{student_id}/fees/{fee_id}/appeal-grant",
            {},
            headers,
        )

    def appeal_deny_fee(self, prog_id, student_id, fee_id, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/students/{student_id}/fees/{fee_id}/appeal-deny",
            {},
            headers,
        )

    def waive_fee(self, prog_id, student_id, fee_id, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/students/{student_id}/fees/{fee_id}/waive",
            {},
            headers,
        )

    def settle_fee(self, prog_id, student_id, fee_id, payload, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/students/{student_id}/fees/{fee_id}/settle",
            payload,
            headers,
        )

    def write_off_fee(self, prog_id, student_id, fee_id, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/students/{student_id}/fees/{fee_id}/write-off",
            {},
            headers,
        )

    # --- LoanerCheckout ---
    def create_loaner_checkout(self, prog_id, student_id, payload, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/students/{student_id}/loaner-checkouts",
            payload,
            headers,
        )

    def list_loaner_checkouts(self, prog_id, student_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/programs/{prog_id}/students/{student_id}/loaner-checkouts",
            headers=headers,
            params=params,
        )

    def get_loaner_checkout(self, prog_id, student_id, checkout_id, headers):
        return self._request(
            "GET",
            f"/api/programs/{prog_id}/students/{student_id}/loaner-checkouts/{checkout_id}",
            headers=headers,
        )

    def return_loaner_checkout(self, prog_id, student_id, checkout_id, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/students/{student_id}/loaner-checkouts/{checkout_id}/return",
            {},
            headers,
        )

    def escalate_loaner_checkout(self, prog_id, student_id, checkout_id, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/students/{student_id}/loaner-checkouts/{checkout_id}/escalate",
            {},
            headers,
        )

    # --- AuditSweep ---
    def create_audit_sweep(self, prog_id, payload, headers):
        return self._request(
            "POST", f"/api/programs/{prog_id}/audit-sweeps", payload, headers
        )

    def list_audit_sweeps(self, prog_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/programs/{prog_id}/audit-sweeps",
            headers=headers,
            params=params,
        )

    def get_audit_sweep(self, prog_id, sweep_id, headers):
        return self._request(
            "GET", f"/api/programs/{prog_id}/audit-sweeps/{sweep_id}", headers=headers
        )

    def begin_audit_sweep(self, prog_id, sweep_id, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/audit-sweeps/{sweep_id}/begin",
            {},
            headers,
        )

    def scan_audit_sweep(self, prog_id, sweep_id, payload, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/audit-sweeps/{sweep_id}/scan",
            payload,
            headers,
        )

    def finish_scan_audit_sweep(self, prog_id, sweep_id, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/audit-sweeps/{sweep_id}/finish-scan",
            {},
            headers,
        )

    def close_audit_sweep(self, prog_id, sweep_id, headers):
        return self._request(
            "POST",
            f"/api/programs/{prog_id}/audit-sweeps/{sweep_id}/close",
            {},
            headers,
        )

    # --- AssetLifecycleEvent (read-only) ---
    def list_lifecycle_events(self, prog_id, asset_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/programs/{prog_id}/asset-units/{asset_id}/lifecycle-events",
            headers=headers,
            params=params,
        )

    # --- Sub-resources ---
    def list_student_asset_units(self, prog_id, student_id, headers):
        return self._request(
            "GET",
            f"/api/programs/{prog_id}/students/{student_id}/asset-units",
            headers=headers,
        )

    def list_asset_unit_assignments(self, prog_id, asset_id, headers):
        return self._request(
            "GET",
            f"/api/programs/{prog_id}/asset-units/{asset_id}/assignments",
            headers=headers,
        )

    def list_asset_unit_loaner_checkouts(self, prog_id, asset_id, headers):
        return self._request(
            "GET",
            f"/api/programs/{prog_id}/asset-units/{asset_id}/loaner-checkouts",
            headers=headers,
        )

    # --- Flat collection routes ---
    def flat_list_students(self, headers, params=None):
        return self._request("GET", "/api/students", headers=headers, params=params)

    def flat_list_fleets(self, headers, params=None):
        return self._request("GET", "/api/fleets", headers=headers, params=params)

    def flat_list_asset_units(self, headers, params=None):
        return self._request("GET", "/api/asset-units", headers=headers, params=params)

    def flat_list_assignments(self, headers, params=None):
        return self._request("GET", "/api/assignments", headers=headers, params=params)

    def flat_list_damage_reports(self, headers, params=None):
        return self._request("GET", "/api/damage-reports", headers=headers, params=params)

    def flat_list_fees(self, headers, params=None):
        return self._request("GET", "/api/fees", headers=headers, params=params)

    def flat_list_loaner_checkouts(self, headers, params=None):
        return self._request("GET", "/api/loaner-checkouts", headers=headers, params=params)

    def flat_list_insurance_policies(self, headers, params=None):
        return self._request(
            "GET", "/api/insurance-policies", headers=headers, params=params
        )

    def flat_list_family_agreements(self, headers, params=None):
        return self._request(
            "GET", "/api/family-agreements", headers=headers, params=params
        )

    def flat_list_lifecycle_events(self, headers, params=None):
        return self._request("GET", "/api/lifecycle-events", headers=headers, params=params)

    def flat_list_audit_sweeps(self, headers, params=None):
        return self._request("GET", "/api/audit-sweeps", headers=headers, params=params)

    # --- Flat alias single-read routes ---
    def flat_get_student(self, student_id, headers):
        return self._request("GET", f"/api/students/{student_id}", headers=headers)

    def flat_get_fleet(self, fleet_id, headers):
        return self._request("GET", f"/api/fleets/{fleet_id}", headers=headers)

    def flat_get_asset_unit(self, asset_id, headers):
        return self._request("GET", f"/api/asset-units/{asset_id}", headers=headers)

    def flat_get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/api/assignments/{assignment_id}", headers=headers)

    def flat_get_damage_report(self, report_id, headers):
        return self._request("GET", f"/api/damage-reports/{report_id}", headers=headers)

    def flat_get_fee(self, fee_id, headers):
        return self._request("GET", f"/api/fees/{fee_id}", headers=headers)

    def flat_get_loaner_checkout(self, checkout_id, headers):
        return self._request(
            "GET", f"/api/loaner-checkouts/{checkout_id}", headers=headers
        )

    def flat_get_insurance_policy(self, policy_id, headers):
        return self._request(
            "GET", f"/api/insurance-policies/{policy_id}", headers=headers
        )

    def flat_get_family_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/api/family-agreements/{agreement_id}", headers=headers
        )

    def flat_get_lifecycle_event(self, event_id, headers):
        return self._request("GET", f"/api/lifecycle-events/{event_id}", headers=headers)

    def flat_get_audit_sweep(self, sweep_id, headers):
        return self._request("GET", f"/api/audit-sweeps/{sweep_id}", headers=headers)

    # --- Logical clock (test-driving capability, PRD §2.8) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
