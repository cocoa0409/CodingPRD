"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock / sweep ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_docket_sweep(self, headers):
        return self._request("POST", "/docket-sweeps", {}, headers)

    # --- JurisdictionRule ---
    def create_jurisdiction_rule(self, payload, headers):
        return self._request("POST", "/jurisdiction-rules", payload, headers)

    def list_jurisdiction_rules(self, headers, params=None):
        return self._request("GET", "/jurisdiction-rules", headers=headers, params=params)

    def get_jurisdiction_rule(self, rule_id, headers):
        return self._request("GET", f"/jurisdiction-rules/{rule_id}", headers=headers)

    def update_jurisdiction_rule(self, rule_id, payload, headers):
        return self._request("PATCH", f"/jurisdiction-rules/{rule_id}", payload, headers)

    # --- Client ---
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def suspend_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/suspend", {}, headers)

    def reactivate_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/reactivate", {}, headers)

    def get_client_risk_score(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/risk-score", headers=headers, params=params)

    # --- ClientContact ---
    def create_contact(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/contacts", payload, headers)

    def list_contacts_of_client(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/contacts", headers=headers, params=params)

    def get_contact(self, contact_id, headers):
        return self._request("GET", f"/contacts/{contact_id}", headers=headers)

    def list_contacts(self, headers, params=None):
        return self._request("GET", "/contacts", headers=headers, params=params)

    # --- CounselFirm ---
    def create_counsel_firm(self, payload, headers):
        return self._request("POST", "/counsel-firms", payload, headers)

    def get_counsel_firm(self, firm_id, headers):
        return self._request("GET", f"/counsel-firms/{firm_id}", headers=headers)

    def list_instructions_of_firm(self, firm_id, headers, params=None):
        return self._request("GET", f"/counsel-firms/{firm_id}/instructions", headers=headers, params=params)

    # --- Inventor ---
    def create_inventor(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/inventors", payload, headers)

    def list_inventors_of_client(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/inventors", headers=headers, params=params)

    def get_inventor(self, inventor_id, headers):
        return self._request("GET", f"/inventors/{inventor_id}", headers=headers)

    def list_assignments_of_inventor(self, inventor_id, headers, params=None):
        return self._request("GET", f"/inventors/{inventor_id}/assignments", headers=headers, params=params)

    def list_inventors(self, headers, params=None):
        return self._request("GET", "/inventors", headers=headers, params=params)

    # --- PatentFamily ---
    def create_family(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/families", payload, headers)

    def list_families_of_client(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/families", headers=headers, params=params)

    def get_family(self, family_id, headers):
        return self._request("GET", f"/families/{family_id}", headers=headers)

    def enter_pruning_review(self, family_id, headers):
        return self._request("POST", f"/families/{family_id}/enter-pruning-review", {}, headers)

    def exit_pruning_review(self, family_id, headers):
        return self._request("POST", f"/families/{family_id}/exit-pruning-review", {}, headers)

    def close_family(self, family_id, headers):
        return self._request("POST", f"/families/{family_id}/close", {}, headers)

    def get_budget_forecast(self, family_id, headers, params=None):
        return self._request("GET", f"/families/{family_id}/budget-forecast", headers=headers, params=params)

    def list_families(self, headers, params=None):
        return self._request("GET", "/families", headers=headers, params=params)

    # --- Application ---
    def create_application(self, family_id, payload, headers):
        return self._request("POST", f"/families/{family_id}/applications", payload, headers)

    def list_applications_of_family(self, family_id, headers, params=None):
        return self._request("GET", f"/families/{family_id}/applications", headers=headers, params=params)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def patch_application(self, application_id, payload, headers):
        return self._request("PATCH", f"/applications/{application_id}", payload, headers)

    def file_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/file", {}, headers)

    def grant_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/grant", payload, headers)

    def record_lapse_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/record-lapse", {}, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/withdraw", {}, headers)

    # --- DocketEntry ---
    def create_docket_entry(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/docket-entries", payload, headers)

    def list_docket_entries_of_application(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/docket-entries", headers=headers, params=params)

    def get_docket_entry(self, entry_id, headers):
        return self._request("GET", f"/docket-entries/{entry_id}", headers=headers)

    def start_docket_entry(self, entry_id, headers):
        return self._request("POST", f"/docket-entries/{entry_id}/start", {}, headers)

    def request_extension(self, entry_id, headers):
        return self._request("POST", f"/docket-entries/{entry_id}/request-extension", {}, headers)

    def record_response(self, entry_id, payload, headers):
        return self._request("POST", f"/docket-entries/{entry_id}/record-response", payload, headers)

    def record_rejection(self, entry_id, payload, headers):
        return self._request("POST", f"/docket-entries/{entry_id}/record-rejection", payload, headers)

    def complete_docket_entry(self, entry_id, headers):
        return self._request("POST", f"/docket-entries/{entry_id}/complete", {}, headers)

    def cancel_docket_entry(self, entry_id, headers):
        return self._request("POST", f"/docket-entries/{entry_id}/cancel", {}, headers)

    def list_office_actions_of_entry(self, entry_id, headers):
        return self._request("GET", f"/docket-entries/{entry_id}/office-actions", headers=headers)

    def list_instructions_of_entry(self, entry_id, headers):
        return self._request("GET", f"/docket-entries/{entry_id}/instructions", headers=headers)

    def list_docket_entries(self, headers, params=None):
        return self._request("GET", "/docket-entries", headers=headers, params=params)

    # --- OfficeAction ---
    def create_office_action(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/office-actions", payload, headers)

    def list_office_actions_of_application(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/office-actions", headers=headers, params=params)

    def get_office_action(self, office_action_id, headers):
        return self._request("GET", f"/office-actions/{office_action_id}", headers=headers)

    def close_informational_office_action(self, office_action_id, headers):
        return self._request("POST", f"/office-actions/{office_action_id}/close-informational", {}, headers)

    def list_office_actions(self, headers, params=None):
        return self._request("GET", "/office-actions", headers=headers, params=params)

    # --- AnnuityObligation / PaymentAuthorization ---
    def list_annuity_obligations_of_application(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/annuity-obligations", headers=headers, params=params)

    def get_annuity_obligation(self, obligation_id, headers):
        return self._request("GET", f"/annuity-obligations/{obligation_id}", headers=headers)

    def create_authorization(self, obligation_id, payload, headers):
        return self._request("POST", f"/annuity-obligations/{obligation_id}/authorizations", payload, headers)

    def list_authorizations_of_obligation(self, obligation_id, headers, params=None):
        return self._request("GET", f"/annuity-obligations/{obligation_id}/authorizations", headers=headers, params=params)

    def get_authorization(self, authorization_id, headers):
        return self._request("GET", f"/authorizations/{authorization_id}", headers=headers)

    def approve_authorization(self, authorization_id, headers):
        return self._request("POST", f"/authorizations/{authorization_id}/approve", {}, headers)

    def reject_authorization(self, authorization_id, headers):
        return self._request("POST", f"/authorizations/{authorization_id}/reject", {}, headers)

    def release_authorization(self, authorization_id, headers):
        return self._request("POST", f"/authorizations/{authorization_id}/release", {}, headers)

    def deauthorize_obligation(self, obligation_id, headers):
        return self._request("POST", f"/annuity-obligations/{obligation_id}/deauthorize", {}, headers)

    def instruct_payment(self, obligation_id, headers):
        return self._request("POST", f"/annuity-obligations/{obligation_id}/instruct-payment", {}, headers)

    def raise_confirmation_query(self, obligation_id, headers):
        return self._request("POST", f"/annuity-obligations/{obligation_id}/raise-confirmation-query", {}, headers)

    def reinstruct_payment(self, obligation_id, headers):
        return self._request("POST", f"/annuity-obligations/{obligation_id}/reinstruct", {}, headers)

    def confirm_payment(self, obligation_id, payload, headers):
        return self._request("POST", f"/annuity-obligations/{obligation_id}/confirm-payment", payload, headers)

    def list_annuity_obligations(self, headers, params=None):
        return self._request("GET", "/annuity-obligations", headers=headers, params=params)

    def list_authorizations(self, headers, params=None):
        return self._request("GET", "/authorizations", headers=headers, params=params)

    # --- OutsideCounselInstruction ---
    def create_instruction(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/instructions", payload, headers)

    def list_instructions_of_application(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/instructions", headers=headers, params=params)

    def get_instruction(self, instruction_id, headers):
        return self._request("GET", f"/instructions/{instruction_id}", headers=headers)

    def send_instruction(self, instruction_id, headers):
        return self._request("POST", f"/instructions/{instruction_id}/send", {}, headers)

    def acknowledge_instruction(self, instruction_id, headers):
        return self._request("POST", f"/instructions/{instruction_id}/acknowledge", {}, headers)

    def confirm_instruction(self, instruction_id, headers):
        return self._request("POST", f"/instructions/{instruction_id}/confirm", {}, headers)

    def decline_instruction(self, instruction_id, headers):
        return self._request("POST", f"/instructions/{instruction_id}/decline", {}, headers)

    def complete_instruction(self, instruction_id, headers):
        return self._request("POST", f"/instructions/{instruction_id}/complete", {}, headers)

    def cancel_instruction(self, instruction_id, headers):
        return self._request("POST", f"/instructions/{instruction_id}/cancel", {}, headers)

    def list_instructions(self, headers, params=None):
        return self._request("GET", "/instructions", headers=headers, params=params)

    # --- AbandonmentReview ---
    def create_abandonment_review(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/abandonment-reviews", payload, headers)

    def list_abandonment_reviews_of_application(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/abandonment-reviews", headers=headers, params=params)

    def get_abandonment_review(self, review_id, headers):
        return self._request("GET", f"/abandonment-reviews/{review_id}", headers=headers)

    def submit_abandonment_review(self, review_id, headers):
        return self._request("POST", f"/abandonment-reviews/{review_id}/submit", {}, headers)

    def approve_abandonment_review(self, review_id, headers):
        return self._request("POST", f"/abandonment-reviews/{review_id}/approve", {}, headers)

    def reject_abandonment_review(self, review_id, headers):
        return self._request("POST", f"/abandonment-reviews/{review_id}/reject", {}, headers)

    def execute_abandonment_review(self, review_id, headers):
        return self._request("POST", f"/abandonment-reviews/{review_id}/execute", {}, headers)

    def list_abandonment_reviews(self, headers, params=None):
        return self._request("GET", "/abandonment-reviews", headers=headers, params=params)

    # --- AssignmentRecord ---
    def create_assignment(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/assignments", payload, headers)

    def list_assignments_of_application(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def execute_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/execute", {}, headers)

    def record_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/record", payload, headers)

    def record_assignment_rejection(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/record-rejection", {}, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    # --- DocketAudit ---
    def create_audit(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/audits", payload, headers)

    def list_audits_of_application(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/audits", headers=headers, params=params)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/audits/{audit_id}", headers=headers)

    def resolve_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/audits/{audit_id}/resolve", payload, headers)

    def close_audit(self, audit_id, headers):
        return self._request("POST", f"/audits/{audit_id}/close", {}, headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/audits", headers=headers, params=params)


api_client = ApiClient()
