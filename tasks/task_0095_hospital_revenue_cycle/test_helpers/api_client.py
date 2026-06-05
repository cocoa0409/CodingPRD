"""API client: one method per endpoint defined in the Hospital Revenue Cycle PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Payer ----
    def create_payer(self, payload, headers):
        return self._request("POST", "/payers", payload, headers)

    def get_payer(self, payer_id, headers):
        return self._request("GET", f"/payers/{payer_id}", headers=headers)

    # ---- Patient ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    # ---- InsurancePolicy ----
    def create_policy(self, payload, headers):
        return self._request("POST", "/insurance-policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/insurance-policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/insurance-policies", headers=headers, params=params)

    def verify_policy(self, policy_id, headers):
        return self._request("POST", f"/insurance-policies/{policy_id}/verify", {}, headers)

    def terminate_policy(self, policy_id, headers):
        return self._request("POST", f"/insurance-policies/{policy_id}/terminate", {}, headers)

    # ---- BenefitAccumulator ----
    def get_benefit_accumulator(self, accumulator_id, headers):
        return self._request("GET", f"/benefit-accumulators/{accumulator_id}", headers=headers)

    def list_benefit_accumulators(self, headers, params=None):
        return self._request("GET", "/benefit-accumulators", headers=headers, params=params)

    # ---- Encounter ----
    def create_encounter(self, payload, headers):
        return self._request("POST", "/encounters", payload, headers)

    def get_encounter(self, encounter_id, headers):
        return self._request("GET", f"/encounters/{encounter_id}", headers=headers)

    def list_encounters(self, headers, params=None):
        return self._request("GET", "/encounters", headers=headers, params=params)

    def discharge_encounter(self, encounter_id, headers):
        return self._request("POST", f"/encounters/{encounter_id}/discharge", {}, headers)

    # ---- EligibilityCheck ----
    def create_eligibility_check(self, encounter_id, headers):
        return self._request("POST", f"/encounters/{encounter_id}/eligibility-checks", {}, headers)

    def list_eligibility_checks_for_encounter(self, encounter_id, headers, params=None):
        return self._request(
            "GET", f"/encounters/{encounter_id}/eligibility-checks", headers=headers, params=params
        )

    def get_eligibility_check(self, check_id, headers):
        return self._request("GET", f"/eligibility-checks/{check_id}", headers=headers)

    def list_eligibility_checks(self, headers, params=None):
        return self._request("GET", "/eligibility-checks", headers=headers, params=params)

    # ---- Charge ----
    def create_charge(self, encounter_id, payload, headers):
        return self._request("POST", f"/encounters/{encounter_id}/charges", payload, headers)

    def list_charges_for_encounter(self, encounter_id, headers, params=None):
        return self._request(
            "GET", f"/encounters/{encounter_id}/charges", headers=headers, params=params
        )

    def get_charge(self, charge_id, headers):
        return self._request("GET", f"/charges/{charge_id}", headers=headers)

    def void_charge(self, charge_id, headers):
        return self._request("POST", f"/charges/{charge_id}/void", {}, headers)

    # ---- CodingAssignment ----
    def create_coding_assignment(self, encounter_id, payload, headers):
        return self._request(
            "POST", f"/encounters/{encounter_id}/coding-assignment", payload, headers
        )

    def list_coding_for_encounter(self, encounter_id, headers, params=None):
        return self._request(
            "GET", f"/encounters/{encounter_id}/coding-assignment", headers=headers, params=params
        )

    def get_coding_assignment(self, coding_id, headers):
        return self._request("GET", f"/coding-assignments/{coding_id}", headers=headers)

    def finalize_coding(self, coding_id, headers):
        return self._request("POST", f"/coding-assignments/{coding_id}/finalize", {}, headers)

    def return_coding_for_recode(self, coding_id, headers):
        return self._request(
            "POST", f"/coding-assignments/{coding_id}/return-for-recode", {}, headers
        )

    def clear_coding(self, coding_id, headers):
        return self._request("POST", f"/coding-assignments/{coding_id}/clear", {}, headers)

    # ---- Claim ----
    def submit_claim(self, encounter_id, payload, headers):
        return self._request("POST", f"/encounters/{encounter_id}/claims", payload, headers)

    def list_claims_for_encounter(self, encounter_id, headers, params=None):
        return self._request(
            "GET", f"/encounters/{encounter_id}/claims", headers=headers, params=params
        )

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/adjudicate", payload, headers)

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/deny", payload, headers)

    def correct_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/correct", {}, headers)

    def appeal_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/appeal", {}, headers)

    def void_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/void", {}, headers)

    # ---- ClaimLine ----
    def list_claim_lines(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/lines", headers=headers, params=params)

    # ---- PatientStatement ----
    def list_statements_for_encounter(self, encounter_id, headers, params=None):
        return self._request(
            "GET", f"/encounters/{encounter_id}/patient-statements", headers=headers, params=params
        )

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/patient-statements/{statement_id}", headers=headers)

    def post_payment(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/patient-statements/{statement_id}/payments", payload, headers
        )

    def send_statement_to_collections(self, statement_id, headers):
        return self._request(
            "POST", f"/patient-statements/{statement_id}/send-to-collections", {}, headers
        )

    def write_off_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/patient-statements/{statement_id}/write-off", payload, headers
        )

    def list_payments(self, statement_id, headers, params=None):
        return self._request(
            "GET", f"/patient-statements/{statement_id}/payments", headers=headers, params=params
        )

    def list_write_offs(self, statement_id, headers, params=None):
        return self._request(
            "GET", f"/patient-statements/{statement_id}/write-offs", headers=headers, params=params
        )

    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
