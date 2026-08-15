"""API client: one method per endpoint defined in PRD §4 (all under /etax)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/etax/_clock/set_current_utc", payload, headers)

    # --- Employer ---
    def create_employer(self, payload, headers):
        return self._request("POST", "/etax/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/etax/employers/{employer_id}", headers=headers)

    # --- TaxAgency catalog ---
    def create_tax_agency(self, payload, headers):
        return self._request("POST", "/etax/tax-agencies", payload, headers)

    def list_tax_agencies(self, headers, params=None):
        return self._request("GET", "/etax/tax-agencies", headers=headers, params=params)

    def get_tax_agency(self, agency_id, headers):
        return self._request("GET", f"/etax/tax-agencies/{agency_id}", headers=headers)

    # --- ReciprocityAgreement catalog ---
    def create_reciprocity_agreement(self, payload, headers):
        return self._request("POST", "/etax/reciprocity-agreements", payload, headers)

    def list_reciprocity_agreements(self, headers, params=None):
        return self._request("GET", "/etax/reciprocity-agreements", headers=headers, params=params)

    def get_reciprocity_agreement(self, agreement_id, headers):
        return self._request("GET", f"/etax/reciprocity-agreements/{agreement_id}", headers=headers)

    # --- WorkLocation ---
    def create_work_location(self, payload, headers):
        return self._request("POST", "/etax/work-locations", payload, headers)

    def list_work_locations(self, headers, params=None):
        return self._request("GET", "/etax/work-locations", headers=headers, params=params)

    def get_work_location(self, location_id, headers):
        return self._request("GET", f"/etax/work-locations/{location_id}", headers=headers)

    # --- Employee ---
    def create_employee(self, payload, headers):
        return self._request("POST", "/etax/employees", payload, headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/etax/employees", headers=headers, params=params)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/etax/employees/{employee_id}", headers=headers)

    def terminate_employee(self, employee_id, payload, headers):
        return self._request("POST", f"/etax/employees/{employee_id}/terminate", payload, headers)

    # --- NexusCase ---
    def create_nexus_case(self, payload, headers):
        return self._request("POST", "/etax/nexus-cases", payload, headers)

    def list_nexus_cases(self, headers, params=None):
        return self._request("GET", "/etax/nexus-cases", headers=headers, params=params)

    def get_nexus_case(self, case_id, headers):
        return self._request("GET", f"/etax/nexus-cases/{case_id}", headers=headers)

    def recompute_nexus_case(self, case_id, headers):
        return self._request("POST", f"/etax/nexus-cases/{case_id}/recompute", {}, headers)

    def confirm_nexus_case(self, case_id, headers):
        return self._request("POST", f"/etax/nexus-cases/{case_id}/confirm", {}, headers)

    def exempt_nexus_case(self, case_id, payload, headers):
        return self._request("POST", f"/etax/nexus-cases/{case_id}/exempt", payload, headers)

    # --- Registration ---
    def create_registration(self, payload, headers):
        return self._request("POST", "/etax/registrations", payload, headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/etax/registrations", headers=headers, params=params)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/etax/registrations/{registration_id}", headers=headers)

    def submit_registration(self, registration_id, headers):
        return self._request("POST", f"/etax/registrations/{registration_id}/submit", {}, headers)

    def reject_registration(self, registration_id, payload, headers):
        return self._request("POST", f"/etax/registrations/{registration_id}/reject", payload, headers)

    def activate_registration(self, registration_id, payload, headers):
        return self._request("POST", f"/etax/registrations/{registration_id}/activate", payload, headers)

    def close_registration(self, registration_id, headers):
        return self._request("POST", f"/etax/registrations/{registration_id}/close", {}, headers)

    def recompute_registration_schedule(self, registration_id, headers):
        return self._request(
            "POST", f"/etax/registrations/{registration_id}/recompute_schedule", {}, headers
        )

    # --- WithholdingElection ---
    def create_withholding_election(self, payload, headers):
        return self._request("POST", "/etax/withholding-elections", payload, headers)

    def list_withholding_elections(self, headers, params=None):
        return self._request("GET", "/etax/withholding-elections", headers=headers, params=params)

    def get_withholding_election(self, election_id, headers):
        return self._request("GET", f"/etax/withholding-elections/{election_id}", headers=headers)

    def validate_election(self, election_id, headers):
        return self._request("POST", f"/etax/withholding-elections/{election_id}/validate", {}, headers)

    def reject_election(self, election_id, payload, headers):
        return self._request("POST", f"/etax/withholding-elections/{election_id}/reject", payload, headers)

    def revoke_election(self, election_id, headers):
        return self._request("POST", f"/etax/withholding-elections/{election_id}/revoke", {}, headers)

    # --- LocalAssignment ---
    def resolve_local_assignment(self, payload, headers):
        return self._request("POST", "/etax/local-assignments/resolve", payload, headers)

    def override_local_assignment(self, payload, headers):
        return self._request("POST", "/etax/local-assignments/override", payload, headers)

    def list_local_assignments(self, headers, params=None):
        return self._request("GET", "/etax/local-assignments", headers=headers, params=params)

    def get_local_assignment(self, assignment_id, headers):
        return self._request("GET", f"/etax/local-assignments/{assignment_id}", headers=headers)

    # --- UIRate ---
    def create_ui_rate(self, payload, headers):
        return self._request("POST", "/etax/ui-rates", payload, headers)

    def list_ui_rates(self, headers, params=None):
        return self._request("GET", "/etax/ui-rates", headers=headers, params=params)

    def get_ui_rate(self, rate_id, headers):
        return self._request("GET", f"/etax/ui-rates/{rate_id}", headers=headers)

    def review_ui_rate(self, rate_id, headers):
        return self._request("POST", f"/etax/ui-rates/{rate_id}/review", {}, headers)

    def contest_ui_rate(self, rate_id, payload, headers):
        return self._request("POST", f"/etax/ui-rates/{rate_id}/contest", payload, headers)

    def make_ui_rate_effective(self, rate_id, headers):
        return self._request("POST", f"/etax/ui-rates/{rate_id}/make_effective", {}, headers)

    # --- VoluntaryContribution ---
    def create_voluntary_contribution(self, payload, headers):
        return self._request("POST", "/etax/voluntary-contributions", payload, headers)

    def list_voluntary_contributions(self, headers, params=None):
        return self._request("GET", "/etax/voluntary-contributions", headers=headers, params=params)

    def get_voluntary_contribution(self, vc_id, headers):
        return self._request("GET", f"/etax/voluntary-contributions/{vc_id}", headers=headers)

    def approve_voluntary_contribution(self, vc_id, headers):
        return self._request("POST", f"/etax/voluntary-contributions/{vc_id}/approve", {}, headers)

    def decline_voluntary_contribution(self, vc_id, headers):
        return self._request("POST", f"/etax/voluntary-contributions/{vc_id}/decline", {}, headers)

    def remit_voluntary_contribution(self, vc_id, headers):
        return self._request("POST", f"/etax/voluntary-contributions/{vc_id}/remit", {}, headers)

    def apply_voluntary_contribution(self, vc_id, headers):
        return self._request("POST", f"/etax/voluntary-contributions/{vc_id}/apply", {}, headers)

    # --- LocationChange ---
    def create_location_change(self, payload, headers):
        return self._request("POST", "/etax/location-changes", payload, headers)

    def list_location_changes(self, headers, params=None):
        return self._request("GET", "/etax/location-changes", headers=headers, params=params)

    def get_location_change(self, change_id, headers):
        return self._request("GET", f"/etax/location-changes/{change_id}", headers=headers)

    def patch_location_change(self, change_id, payload, headers):
        return self._request("PATCH", f"/etax/location-changes/{change_id}", payload, headers)

    def approve_location_change(self, change_id, headers):
        return self._request("POST", f"/etax/location-changes/{change_id}/approve", {}, headers)

    def reject_location_change(self, change_id, payload, headers):
        return self._request("POST", f"/etax/location-changes/{change_id}/reject", payload, headers)

    def cancel_location_change(self, change_id, headers):
        return self._request("POST", f"/etax/location-changes/{change_id}/cancel", {}, headers)

    def reverse_location_change(self, change_id, headers):
        return self._request("POST", f"/etax/location-changes/{change_id}/reverse", {}, headers)

    # --- FilingObligation ---
    def list_filing_obligations(self, headers, params=None):
        return self._request("GET", "/etax/filing-obligations", headers=headers, params=params)

    def get_filing_obligation(self, obligation_id, headers):
        return self._request("GET", f"/etax/filing-obligations/{obligation_id}", headers=headers)

    def file_obligation(self, obligation_id, payload, headers):
        return self._request("POST", f"/etax/filing-obligations/{obligation_id}/file", payload, headers)

    def confirm_obligation(self, obligation_id, headers):
        return self._request("POST", f"/etax/filing-obligations/{obligation_id}/confirm", {}, headers)

    # --- AgencyNotice ---
    def create_agency_notice(self, payload, headers):
        return self._request("POST", "/etax/agency-notices", payload, headers)

    def list_agency_notices(self, headers, params=None):
        return self._request("GET", "/etax/agency-notices", headers=headers, params=params)

    def get_agency_notice(self, notice_id, headers):
        return self._request("GET", f"/etax/agency-notices/{notice_id}", headers=headers)

    def triage_notice(self, notice_id, headers):
        return self._request("POST", f"/etax/agency-notices/{notice_id}/triage", {}, headers)

    def escalate_notice(self, notice_id, headers):
        return self._request("POST", f"/etax/agency-notices/{notice_id}/escalate", {}, headers)

    def resolve_notice(self, notice_id, payload, headers):
        return self._request("POST", f"/etax/agency-notices/{notice_id}/resolve", payload, headers)

    def close_notice(self, notice_id, headers):
        return self._request("POST", f"/etax/agency-notices/{notice_id}/close", {}, headers)

    # --- AbatementRequest ---
    def create_abatement_request(self, payload, headers):
        return self._request("POST", "/etax/abatement-requests", payload, headers)

    def list_abatement_requests(self, headers, params=None):
        return self._request("GET", "/etax/abatement-requests", headers=headers, params=params)

    def get_abatement_request(self, request_id, headers):
        return self._request("GET", f"/etax/abatement-requests/{request_id}", headers=headers)

    def submit_abatement_request(self, request_id, headers):
        return self._request("POST", f"/etax/abatement-requests/{request_id}/submit", {}, headers)

    def review_abatement_request(self, request_id, headers):
        return self._request("POST", f"/etax/abatement-requests/{request_id}/review", {}, headers)

    def decide_abatement_request(self, request_id, payload, headers):
        return self._request("POST", f"/etax/abatement-requests/{request_id}/decide", payload, headers)

    def withdraw_abatement_request(self, request_id, headers):
        return self._request("POST", f"/etax/abatement-requests/{request_id}/withdraw", {}, headers)


api_client = ApiClient()
