"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Applicant ---
    def create_applicant(self, payload, headers):
        return self._request("POST", "/licensure/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/licensure/applicants/{applicant_id}",
                             headers=headers)

    def list_applicants(self, headers, params=None):
        return self._request("GET", "/licensure/applicants",
                             headers=headers, params=params)

    # --- EducatorPrepProgram ---
    def create_program(self, payload, headers):
        return self._request("POST", "/licensure/educator-prep-programs",
                             payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET",
                             f"/licensure/educator-prep-programs/{program_id}",
                             headers=headers)

    def transition_program(self, program_id, payload, headers):
        return self._request(
            "POST", f"/licensure/educator-prep-programs/{program_id}/state",
            payload, headers)

    # --- CredentialApplication ---
    def create_application(self, payload, headers):
        return self._request("POST", "/licensure/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/licensure/applications/{application_id}",
                             headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/licensure/applications",
                             headers=headers, params=params)

    def pay_application_fee(self, application_id, payload, headers):
        return self._request(
            "POST", f"/licensure/applications/{application_id}/fee-payment",
            payload, headers)

    def transition_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/licensure/applications/{application_id}/state",
            payload, headers)

    # --- Transcript ---
    def create_transcript(self, application_id, payload, headers):
        return self._request(
            "POST", f"/licensure/applications/{application_id}/transcripts",
            payload, headers)

    def list_transcripts(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/licensure/applications/{application_id}/transcripts",
            headers=headers, params=params)

    def get_transcript(self, transcript_id, headers):
        return self._request("GET", f"/licensure/transcripts/{transcript_id}",
                             headers=headers)

    def verify_transcript(self, transcript_id, payload, headers):
        return self._request("POST",
                             f"/licensure/transcripts/{transcript_id}/verify",
                             payload, headers)

    # --- TestScore ---
    def create_test_score(self, application_id, payload, headers):
        return self._request(
            "POST", f"/licensure/applications/{application_id}/test-scores",
            payload, headers)

    def list_test_scores(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/licensure/applications/{application_id}/test-scores",
            headers=headers, params=params)

    def get_test_score(self, test_score_id, headers):
        return self._request("GET", f"/licensure/test-scores/{test_score_id}",
                             headers=headers)

    def verify_test_score(self, test_score_id, payload, headers):
        return self._request("POST",
                             f"/licensure/test-scores/{test_score_id}/verify",
                             payload, headers)

    # --- BackgroundCheck ---
    def create_background_check(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/licensure/applications/{application_id}/background-checks",
            payload, headers)

    def list_background_checks(self, application_id, headers, params=None):
        return self._request(
            "GET",
            f"/licensure/applications/{application_id}/background-checks",
            headers=headers, params=params)

    def get_background_check(self, check_id, headers):
        return self._request("GET", f"/licensure/background-checks/{check_id}",
                             headers=headers)

    def transition_background_check(self, check_id, payload, headers):
        return self._request(
            "POST", f"/licensure/background-checks/{check_id}/state",
            payload, headers)

    # --- ReciprocityEvaluation ---
    def create_reciprocity_evaluation(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/licensure/applications/{application_id}/reciprocity-evaluations",
            payload, headers)

    def list_reciprocity_evaluations(self, application_id, headers, params=None):
        return self._request(
            "GET",
            f"/licensure/applications/{application_id}/reciprocity-evaluations",
            headers=headers, params=params)

    def get_reciprocity_evaluation(self, evaluation_id, headers):
        return self._request(
            "GET", f"/licensure/reciprocity-evaluations/{evaluation_id}",
            headers=headers)

    def finalize_reciprocity_evaluation(self, evaluation_id, payload, headers):
        return self._request(
            "POST",
            f"/licensure/reciprocity-evaluations/{evaluation_id}/finalize",
            payload, headers)

    # --- DeficiencyPlan ---
    def create_deficiency_plan(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/licensure/applications/{application_id}/deficiency-plans",
            payload, headers)

    def list_deficiency_plans(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/licensure/applications/{application_id}/deficiency-plans",
            headers=headers, params=params)

    def get_deficiency_plan(self, plan_id, headers):
        return self._request("GET", f"/licensure/deficiency-plans/{plan_id}",
                             headers=headers)

    def transition_deficiency_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/licensure/deficiency-plans/{plan_id}/state",
            payload, headers)

    def post_plan_evidence(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/licensure/deficiency-plans/{plan_id}/evidence",
            payload, headers)

    # --- License ---
    def get_license(self, license_id, headers):
        return self._request("GET", f"/licensure/licenses/{license_id}",
                             headers=headers)

    def list_licenses(self, headers, params=None):
        return self._request("GET", "/licensure/licenses",
                             headers=headers, params=params)

    def renew_license(self, license_id, payload, headers):
        return self._request("POST", f"/licensure/licenses/{license_id}/renew",
                             payload, headers)

    def reinstate_license(self, license_id, payload, headers):
        return self._request("POST",
                             f"/licensure/licenses/{license_id}/reinstate",
                             payload, headers)

    def surrender_license(self, license_id, headers):
        return self._request("POST",
                             f"/licensure/licenses/{license_id}/surrender",
                             None, headers)

    # --- Endorsement ---
    def create_endorsement(self, license_id, payload, headers):
        return self._request(
            "POST", f"/licensure/licenses/{license_id}/endorsements",
            payload, headers)

    def list_endorsements(self, license_id, headers, params=None):
        return self._request(
            "GET", f"/licensure/licenses/{license_id}/endorsements",
            headers=headers, params=params)

    def get_endorsement(self, endorsement_id, headers):
        return self._request("GET", f"/licensure/endorsements/{endorsement_id}",
                             headers=headers)

    def transition_endorsement(self, endorsement_id, payload, headers):
        return self._request(
            "POST", f"/licensure/endorsements/{endorsement_id}/state",
            payload, headers)

    # --- EmergencyPermit ---
    def create_emergency_permit(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/licensure/applications/{application_id}/emergency-permits",
            payload, headers)

    def get_emergency_permit(self, permit_id, headers):
        return self._request("GET", f"/licensure/emergency-permits/{permit_id}",
                             headers=headers)

    def list_emergency_permits(self, headers, params=None):
        return self._request("GET", "/licensure/emergency-permits",
                             headers=headers, params=params)

    def transition_emergency_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/licensure/emergency-permits/{permit_id}/state",
            payload, headers)

    # --- CECredit ---
    def create_ce_credit(self, license_id, payload, headers):
        return self._request("POST", f"/licensure/licenses/{license_id}/ce-credits",
                             payload, headers)

    def list_ce_credits(self, license_id, headers, params=None):
        return self._request("GET",
                             f"/licensure/licenses/{license_id}/ce-credits",
                             headers=headers, params=params)

    def get_ce_credit(self, credit_id, headers):
        return self._request("GET", f"/licensure/ce-credits/{credit_id}",
                             headers=headers)

    def transition_ce_credit(self, credit_id, payload, headers):
        return self._request("POST", f"/licensure/ce-credits/{credit_id}/state",
                             payload, headers)

    # --- CEAudit ---
    def create_ce_audit(self, license_id, payload, headers):
        return self._request("POST", f"/licensure/licenses/{license_id}/ce-audits",
                             payload, headers)

    def list_ce_audits(self, license_id, headers, params=None):
        return self._request("GET", f"/licensure/licenses/{license_id}/ce-audits",
                             headers=headers, params=params)

    def get_ce_audit(self, audit_id, headers):
        return self._request("GET", f"/licensure/ce-audits/{audit_id}",
                             headers=headers)

    def transition_ce_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/licensure/ce-audits/{audit_id}/state",
                             payload, headers)

    def post_audit_determination(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/licensure/ce-audits/{audit_id}/determinations",
            payload, headers)

    # --- MisconductCase ---
    def create_misconduct_case(self, license_id, payload, headers):
        return self._request(
            "POST", f"/licensure/licenses/{license_id}/misconduct-cases",
            payload, headers)

    def list_misconduct_cases(self, license_id, headers, params=None):
        return self._request(
            "GET", f"/licensure/licenses/{license_id}/misconduct-cases",
            headers=headers, params=params)

    def get_misconduct_case(self, case_id, headers):
        return self._request("GET", f"/licensure/misconduct-cases/{case_id}",
                             headers=headers)

    def transition_misconduct_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/licensure/misconduct-cases/{case_id}/state",
            payload, headers)

    # --- DisciplinaryAction ---
    def create_disciplinary_action(self, case_id, payload, headers):
        return self._request(
            "POST",
            f"/licensure/misconduct-cases/{case_id}/disciplinary-actions",
            payload, headers)

    def get_disciplinary_action(self, action_id, headers):
        return self._request("GET", f"/licensure/disciplinary-actions/{action_id}",
                             headers=headers)

    def list_disciplinary_actions(self, headers, params=None):
        return self._request("GET", "/licensure/disciplinary-actions",
                             headers=headers, params=params)

    def transition_disciplinary_action(self, action_id, payload, headers):
        return self._request(
            "POST", f"/licensure/disciplinary-actions/{action_id}/state",
            payload, headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
