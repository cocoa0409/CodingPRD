"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Employer ──────────────────────────────────────────────────────────
    def create_employer(self, payload, headers):
        return self._request("POST", "/ui/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/ui/employers/{employer_id}", headers=headers)

    def list_employers(self, headers, params=None):
        return self._request("GET", "/ui/employers", headers=headers, params=params)

    def list_employer_charges(self, employer_id, headers, params=None):
        return self._request("GET", f"/ui/employers/{employer_id}/charges",
                             headers=headers, params=params)

    def list_employer_wage_records(self, employer_id, headers, params=None):
        return self._request("GET", f"/ui/employers/{employer_id}/wage-records",
                             headers=headers, params=params)

    def list_employer_work_search_contacts(self, employer_id, headers, params=None):
        return self._request("GET", f"/ui/employers/{employer_id}/work-search-contacts",
                             headers=headers, params=params)

    # ─── Claimant ──────────────────────────────────────────────────────────
    def create_claimant(self, payload, headers):
        return self._request("POST", "/ui/claimants", payload, headers)

    def get_claimant(self, claimant_id, headers):
        return self._request("GET", f"/ui/claimants/{claimant_id}", headers=headers)

    def list_claimant_wage_records(self, claimant_id, headers, params=None):
        return self._request("GET", f"/ui/claimants/{claimant_id}/wage-records",
                             headers=headers, params=params)

    def update_claimant(self, claimant_id, payload, headers):
        return self._request("PATCH", f"/ui/claimants/{claimant_id}", payload, headers)

    # ─── WageRecord ────────────────────────────────────────────────────────
    def create_wage_record(self, payload, headers):
        return self._request("POST", "/ui/wage-records", payload, headers)

    def list_wage_records(self, headers, params=None):
        return self._request("GET", "/ui/wage-records", headers=headers, params=params)

    def update_wage_record(self, wage_record_id, payload, headers):
        return self._request("PATCH", f"/ui/wage-records/{wage_record_id}", payload, headers)

    # ─── Claim ─────────────────────────────────────────────────────────────
    def create_claim(self, payload, headers):
        return self._request("POST", "/ui/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/ui/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/ui/claims", headers=headers, params=params)

    def submit_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/ui/claims/{claim_id}/submit", payload, headers)

    def apply_extension(self, claim_id, payload, headers):
        return self._request("POST", f"/ui/claims/{claim_id}/apply-extension", payload, headers)

    def close_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/ui/claims/{claim_id}/close", payload, headers)

    def list_claim_determinations(self, claim_id, headers, params=None):
        return self._request("GET", f"/ui/claims/{claim_id}/determinations",
                             headers=headers, params=params)

    def list_claim_weekly_certifications(self, claim_id, headers, params=None):
        return self._request("GET", f"/ui/claims/{claim_id}/weekly-certifications",
                             headers=headers, params=params)

    def list_claim_overpayments(self, claim_id, headers, params=None):
        return self._request("GET", f"/ui/claims/{claim_id}/overpayments",
                             headers=headers, params=params)

    # ─── Determination ─────────────────────────────────────────────────────
    def create_determination(self, payload, headers):
        return self._request("POST", "/ui/determinations", payload, headers)

    def get_determination(self, determination_id, headers):
        return self._request("GET", f"/ui/determinations/{determination_id}", headers=headers)

    def list_determination_appeals(self, determination_id, headers, params=None):
        return self._request("GET", f"/ui/determinations/{determination_id}/appeals",
                             headers=headers, params=params)

    # ─── WeeklyCertification ───────────────────────────────────────────────
    def create_weekly_certification(self, payload, headers):
        return self._request("POST", "/ui/weekly-certifications", payload, headers)

    def get_weekly_certification(self, wc_id, headers):
        return self._request("GET", f"/ui/weekly-certifications/{wc_id}", headers=headers)

    def create_work_search_contact(self, wc_id, payload, headers):
        return self._request("POST", f"/ui/weekly-certifications/{wc_id}/work-search-contacts",
                             payload, headers)

    def list_work_search_contacts(self, wc_id, headers, params=None):
        return self._request("GET", f"/ui/weekly-certifications/{wc_id}/work-search-contacts",
                             headers=headers, params=params)

    def adjudicate_weekly_certification(self, wc_id, payload, headers):
        return self._request("POST", f"/ui/weekly-certifications/{wc_id}/adjudicate",
                             payload, headers)

    def hold_weekly_certification(self, wc_id, payload, headers):
        return self._request("POST", f"/ui/weekly-certifications/{wc_id}/hold", payload, headers)

    def pay_weekly_certification(self, wc_id, payload, headers):
        return self._request("POST", f"/ui/weekly-certifications/{wc_id}/pay", payload, headers)

    def list_weekly_certification_employer_charges(self, wc_id, headers, params=None):
        return self._request("GET", f"/ui/weekly-certifications/{wc_id}/employer-charges",
                             headers=headers, params=params)

    def list_weekly_certification_recoveries(self, wc_id, headers, params=None):
        return self._request("GET", f"/ui/weekly-certifications/{wc_id}/recoveries",
                             headers=headers, params=params)

    # ─── EmployerCharge ────────────────────────────────────────────────────
    def get_employer_charge(self, charge_id, headers):
        return self._request("GET", f"/ui/employer-charges/{charge_id}", headers=headers)

    def protest_employer_charge(self, charge_id, payload, headers):
        return self._request("POST", f"/ui/employer-charges/{charge_id}/protest", payload, headers)

    def relieve_employer_charge(self, charge_id, payload, headers):
        return self._request("POST", f"/ui/employer-charges/{charge_id}/relieve", payload, headers)

    # ─── Overpayment ───────────────────────────────────────────────────────
    def create_overpayment(self, payload, headers):
        return self._request("POST", "/ui/overpayments", payload, headers)

    def get_overpayment(self, overpayment_id, headers):
        return self._request("GET", f"/ui/overpayments/{overpayment_id}", headers=headers)

    def create_recovery(self, overpayment_id, payload, headers):
        return self._request("POST", f"/ui/overpayments/{overpayment_id}/recoveries",
                             payload, headers)

    def list_overpayment_recoveries(self, overpayment_id, headers, params=None):
        return self._request("GET", f"/ui/overpayments/{overpayment_id}/recoveries",
                             headers=headers, params=params)

    def waive_overpayment(self, overpayment_id, payload, headers):
        return self._request("POST", f"/ui/overpayments/{overpayment_id}/waive", payload, headers)

    # ─── Appeal ────────────────────────────────────────────────────────────
    def create_appeal(self, payload, headers):
        return self._request("POST", "/ui/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/ui/appeals/{appeal_id}", headers=headers)

    def assign_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/ui/appeals/{appeal_id}/assign", payload, headers)

    def dismiss_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/ui/appeals/{appeal_id}/dismiss", payload, headers)

    def remand_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/ui/appeals/{appeal_id}/remand", payload, headers)

    def withdraw_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/ui/appeals/{appeal_id}/withdraw", payload, headers)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/ui/appeals/{appeal_id}/decide", payload, headers)

    # ─── EmergencyExtensionProgram ─────────────────────────────────────────
    def create_extension_program(self, payload, headers):
        return self._request("POST", "/ui/extension-programs", payload, headers)

    def get_extension_program(self, program_id, headers):
        return self._request("GET", f"/ui/extension-programs/{program_id}", headers=headers)

    def update_extension_program(self, program_id, payload, headers):
        return self._request("PATCH", f"/ui/extension-programs/{program_id}", payload, headers)

    # ─── Test-driving hooks ────────────────────────────────────────────────
    def set_claim_balance(self, payload, headers):
        return self._request("POST", "/_ledger/set_claim_balance", payload, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
