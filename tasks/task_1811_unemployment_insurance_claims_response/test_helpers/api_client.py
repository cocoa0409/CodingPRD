"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock and agency events (test-driving endpoints)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def claim_adjudication_ack(self, claim_id, headers):
        return self._request("POST", "/_events/claim_adjudication_ack",
                             {"claim_id": claim_id}, headers)

    # ------------------------------------------------------------------
    # State rules
    # ------------------------------------------------------------------
    def create_state_rule(self, payload, headers):
        return self._request("POST", "/ui/state-rules", payload, headers)

    def list_state_rules(self, headers, params=None):
        return self._request("GET", "/ui/state-rules", headers=headers, params=params)

    def get_state_rule(self, rule_id, headers):
        return self._request("GET", f"/ui/state-rules/{rule_id}", headers=headers)

    # ------------------------------------------------------------------
    # Employers
    # ------------------------------------------------------------------
    def create_employer(self, payload, headers):
        return self._request("POST", "/ui/employers", payload, headers)

    def list_employers(self, headers, params=None):
        return self._request("GET", "/ui/employers", headers=headers, params=params)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/ui/employers/{employer_id}", headers=headers)

    def list_employer_claims(self, employer_id, headers, params=None):
        return self._request("GET", f"/ui/employers/{employer_id}/claims",
                             headers=headers, params=params)

    def list_employer_separations(self, employer_id, headers, params=None):
        return self._request("GET", f"/ui/employers/{employer_id}/separations",
                             headers=headers, params=params)

    def list_employer_charge_statements(self, employer_id, headers, params=None):
        return self._request("GET", f"/ui/employers/{employer_id}/charge-statements",
                             headers=headers, params=params)

    def list_employer_models(self, employer_id, headers, params=None):
        return self._request("GET", f"/ui/employers/{employer_id}/experience-rating-models",
                             headers=headers, params=params)

    def list_employer_tpa_engagements(self, employer_id, headers, params=None):
        return self._request("GET", f"/ui/employers/{employer_id}/tpa-engagements",
                             headers=headers, params=params)

    def get_rating_summary(self, employer_id, headers):
        return self._request("GET", f"/ui/employers/{employer_id}/rating-summary",
                             headers=headers)

    # ------------------------------------------------------------------
    # TPA engagements
    # ------------------------------------------------------------------
    def create_tpa_engagement(self, payload, headers):
        return self._request("POST", "/ui/tpa-engagements", payload, headers)

    def get_tpa_engagement(self, engagement_id, headers):
        return self._request("GET", f"/ui/tpa-engagements/{engagement_id}", headers=headers)

    def list_tpa_responses(self, engagement_id, headers, params=None):
        return self._request("GET", f"/ui/tpa-engagements/{engagement_id}/responses",
                             headers=headers, params=params)

    def suspend_tpa_engagement(self, engagement_id, headers):
        return self._request("POST", f"/ui/tpa-engagements/{engagement_id}/suspend",
                             {}, headers)

    def reinstate_tpa_engagement(self, engagement_id, remediation_note, headers):
        return self._request("POST", f"/ui/tpa-engagements/{engagement_id}/reinstate",
                             {"remediation_note": remediation_note}, headers)

    def terminate_tpa_engagement(self, engagement_id, headers):
        return self._request("POST", f"/ui/tpa-engagements/{engagement_id}/terminate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Separations
    # ------------------------------------------------------------------
    def create_separation(self, payload, headers):
        return self._request("POST", "/ui/separations", payload, headers)

    def get_separation(self, separation_id, headers):
        return self._request("GET", f"/ui/separations/{separation_id}", headers=headers)

    def confirm_coding(self, separation_id, headers):
        return self._request("POST", f"/ui/separations/{separation_id}/coding/confirm",
                             {}, headers)

    # ------------------------------------------------------------------
    # Claims
    # ------------------------------------------------------------------
    def create_claim(self, payload, headers):
        return self._request("POST", "/ui/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/ui/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/ui/claims/{claim_id}", headers=headers)

    def list_claim_responses(self, claim_id, headers, params=None):
        return self._request("GET", f"/ui/claims/{claim_id}/responses",
                             headers=headers, params=params)

    def list_claim_evidence(self, claim_id, headers, params=None):
        return self._request("GET", f"/ui/claims/{claim_id}/evidence",
                             headers=headers, params=params)

    def list_claim_determinations(self, claim_id, headers, params=None):
        return self._request("GET", f"/ui/claims/{claim_id}/determinations",
                             headers=headers, params=params)

    def list_claim_hearings(self, claim_id, headers, params=None):
        return self._request("GET", f"/ui/claims/{claim_id}/hearings",
                             headers=headers, params=params)

    def list_claim_line_items(self, claim_id, headers, params=None):
        return self._request("GET", f"/ui/claims/{claim_id}/charge-line-items",
                             headers=headers, params=params)

    def withdraw_claim(self, claim_id, headers):
        return self._request("POST", f"/ui/claims/{claim_id}/withdraw", {}, headers)

    def close_claim(self, claim_id, headers):
        return self._request("POST", f"/ui/claims/{claim_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Responses
    # ------------------------------------------------------------------
    def create_response(self, claim_id, payload, headers):
        return self._request("POST", f"/ui/claims/{claim_id}/responses", payload, headers)

    def get_response(self, response_id, headers):
        return self._request("GET", f"/ui/responses/{response_id}", headers=headers)

    def list_response_amendments(self, response_id, headers, params=None):
        return self._request("GET", f"/ui/responses/{response_id}/amendments",
                             headers=headers, params=params)

    def list_response_evidence(self, response_id, headers, params=None):
        return self._request("GET", f"/ui/responses/{response_id}/evidence",
                             headers=headers, params=params)

    def submit_response(self, claim_id, response_id, expected_claim_version, headers):
        return self._request("POST",
                             f"/ui/claims/{claim_id}/responses/{response_id}/submit",
                             {"expected_claim_version": expected_claim_version}, headers)

    def accept_response(self, claim_id, response_id, headers):
        return self._request("POST",
                             f"/ui/claims/{claim_id}/responses/{response_id}/accept",
                             {}, headers)

    def reject_response(self, claim_id, response_id, headers):
        return self._request("POST",
                             f"/ui/claims/{claim_id}/responses/{response_id}/reject",
                             {}, headers)

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------
    def attach_evidence(self, claim_id, payload, headers):
        return self._request("POST", f"/ui/claims/{claim_id}/evidence", payload, headers)

    def delete_evidence(self, evidence_id, headers):
        return self._request("DELETE", f"/ui/evidence/{evidence_id}", headers=headers)

    # ------------------------------------------------------------------
    # Determinations
    # ------------------------------------------------------------------
    def create_determination(self, claim_id, payload, headers):
        return self._request("POST", f"/ui/claims/{claim_id}/determinations",
                             payload, headers)

    def get_determination(self, determination_id, headers):
        return self._request("GET", f"/ui/determinations/{determination_id}",
                             headers=headers)

    def list_determination_appeals(self, determination_id, headers, params=None):
        return self._request("GET", f"/ui/determinations/{determination_id}/appeals",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Appeals
    # ------------------------------------------------------------------
    def file_appeal(self, determination_id, payload, headers):
        return self._request("POST", f"/ui/determinations/{determination_id}/appeals",
                             payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/ui/appeals/{appeal_id}", headers=headers)

    def list_appeal_hearings(self, appeal_id, headers, params=None):
        return self._request("GET", f"/ui/appeals/{appeal_id}/hearings",
                             headers=headers, params=params)

    def withdraw_appeal(self, appeal_id, headers):
        return self._request("POST", f"/ui/appeals/{appeal_id}/withdraw", {}, headers)

    def decide_appeal(self, appeal_id, decision, headers):
        return self._request("POST", f"/ui/appeals/{appeal_id}/decide",
                             {"decision": decision}, headers)

    # ------------------------------------------------------------------
    # Hearings and witnesses
    # ------------------------------------------------------------------
    def schedule_hearing(self, appeal_id, payload, headers):
        return self._request("POST", f"/ui/appeals/{appeal_id}/hearings",
                             payload, headers)

    def get_hearing(self, hearing_id, headers):
        return self._request("GET", f"/ui/hearings/{hearing_id}", headers=headers)

    def list_hearing_witnesses(self, hearing_id, headers, params=None):
        return self._request("GET", f"/ui/hearings/{hearing_id}/witnesses",
                             headers=headers, params=params)

    def add_witness(self, hearing_id, payload, headers):
        return self._request("POST", f"/ui/hearings/{hearing_id}/witnesses",
                             payload, headers)

    def prep_witness(self, hearing_id, witness_id, headers):
        return self._request(
            "POST", f"/ui/hearings/{hearing_id}/witnesses/{witness_id}/prep",
            {}, headers)

    def continue_hearing(self, hearing_id, scheduled_start, scheduled_end, headers):
        return self._request("POST", f"/ui/hearings/{hearing_id}/continue",
                             {"scheduled_start": scheduled_start,
                              "scheduled_end": scheduled_end}, headers)

    def hold_hearing(self, hearing_id, headers):
        return self._request("POST", f"/ui/hearings/{hearing_id}/hold", {}, headers)

    # ------------------------------------------------------------------
    # Charge statements, line items, protests
    # ------------------------------------------------------------------
    def create_charge_statement(self, payload, headers):
        return self._request("POST", "/ui/charge-statements", payload, headers)

    def get_charge_statement(self, statement_id, headers):
        return self._request("GET", f"/ui/charge-statements/{statement_id}",
                             headers=headers)

    def list_statement_line_items(self, statement_id, headers, params=None):
        return self._request("GET", f"/ui/charge-statements/{statement_id}/line-items",
                             headers=headers, params=params)

    def list_statement_protests(self, statement_id, headers, params=None):
        return self._request("GET", f"/ui/charge-statements/{statement_id}/protests",
                             headers=headers, params=params)

    def post_line_item(self, statement_id, payload, headers):
        return self._request("POST", f"/ui/charge-statements/{statement_id}/line-items",
                             payload, headers)

    def open_audit(self, statement_id, headers):
        return self._request("POST", f"/ui/charge-statements/{statement_id}/audit",
                             {}, headers)

    def complete_audit(self, statement_id, headers):
        return self._request("POST",
                             f"/ui/charge-statements/{statement_id}/audit/complete",
                             {}, headers)

    def reconcile_statement(self, statement_id, headers):
        return self._request("POST", f"/ui/charge-statements/{statement_id}/reconcile",
                             {}, headers)

    def get_line_item(self, line_item_id, headers):
        return self._request("GET", f"/ui/charge-line-items/{line_item_id}",
                             headers=headers)

    def list_line_protests(self, line_item_id, headers, params=None):
        return self._request("GET", f"/ui/charge-line-items/{line_item_id}/protests",
                             headers=headers, params=params)

    def file_protest(self, line_item_id, protest_basis, expected_statement_version,
                     headers):
        return self._request("POST", f"/ui/charge-line-items/{line_item_id}/protests",
                             {"protest_basis": protest_basis,
                              "expected_statement_version": expected_statement_version},
                             headers)

    def waive_line_item(self, line_item_id, headers):
        return self._request("POST", f"/ui/charge-line-items/{line_item_id}/waive",
                             {}, headers)

    def get_protest(self, protest_id, headers):
        return self._request("GET", f"/ui/charge-protests/{protest_id}", headers=headers)

    def review_protest(self, protest_id, headers):
        return self._request("POST", f"/ui/charge-protests/{protest_id}/review",
                             {}, headers)

    def sustain_protest(self, protest_id, headers):
        return self._request("POST", f"/ui/charge-protests/{protest_id}/sustain",
                             {}, headers)

    def deny_protest(self, protest_id, headers):
        return self._request("POST", f"/ui/charge-protests/{protest_id}/deny",
                             {}, headers)

    def withdraw_protest(self, protest_id, headers):
        return self._request("POST", f"/ui/charge-protests/{protest_id}/withdraw",
                             {}, headers)

    # ------------------------------------------------------------------
    # Experience rating models
    # ------------------------------------------------------------------
    def create_model(self, employer_id, payload, headers):
        return self._request("POST",
                             f"/ui/employers/{employer_id}/experience-rating-models",
                             payload, headers)

    def get_model(self, model_id, headers):
        return self._request("GET", f"/ui/experience-rating-models/{model_id}",
                             headers=headers)

    def finalize_model(self, employer_id, model_id, expected_employer_version, headers):
        return self._request(
            "POST",
            f"/ui/employers/{employer_id}/experience-rating-models/{model_id}/finalize",
            {"expected_employer_version": expected_employer_version}, headers)


api_client = ApiClient()
