"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Credit unions & CUSOs ---
    def create_credit_union(self, payload, headers):
        return self._request("POST", "/network/credit-unions", payload, headers)

    def get_credit_union(self, credit_union_id, headers):
        return self._request("GET", f"/network/credit-unions/{credit_union_id}", headers=headers)

    def suspend_credit_union(self, credit_union_id, headers):
        return self._request("POST", f"/network/credit-unions/{credit_union_id}/suspend", headers=headers)

    def reinstate_credit_union(self, credit_union_id, headers):
        return self._request("POST", f"/network/credit-unions/{credit_union_id}/reinstate", headers=headers)

    def create_cuso(self, payload, headers):
        return self._request("POST", "/network/cusos", payload, headers)

    def get_cuso(self, cuso_id, headers):
        return self._request("GET", f"/network/cusos/{cuso_id}", headers=headers)

    # --- CUSO investments ---
    def create_cuso_investment(self, payload, headers):
        return self._request("POST", "/network/cuso-investments", payload, headers)

    def get_cuso_investment(self, investment_id, headers):
        return self._request("GET", f"/network/cuso-investments/{investment_id}", headers=headers)

    def list_cuso_investments(self, headers, params=None):
        return self._request("GET", "/network/cuso-investments", headers=headers, params=params)

    def approve_cuso_investment(self, investment_id, headers):
        return self._request("POST", f"/network/cuso-investments/{investment_id}/approve", headers=headers)

    def reject_cuso_investment(self, investment_id, headers):
        return self._request("POST", f"/network/cuso-investments/{investment_id}/reject", headers=headers)

    def rescind_cuso_investment(self, investment_id, headers):
        return self._request("POST", f"/network/cuso-investments/{investment_id}/rescind", headers=headers)

    # --- Servicing agreements ---
    def create_servicing_agreement(self, payload, headers):
        return self._request("POST", "/network/servicing-agreements", payload, headers)

    def get_servicing_agreement(self, agreement_id, headers):
        return self._request("GET", f"/network/servicing-agreements/{agreement_id}", headers=headers)

    def list_servicing_agreements(self, headers, params=None):
        return self._request("GET", "/network/servicing-agreements", headers=headers, params=params)

    def activate_servicing_agreement(self, agreement_id, headers):
        return self._request("POST", f"/network/servicing-agreements/{agreement_id}/activate", headers=headers)

    def terminate_servicing_agreement(self, agreement_id, headers):
        return self._request("POST", f"/network/servicing-agreements/{agreement_id}/terminate", headers=headers)

    # --- Participation offerings ---
    def create_offering(self, payload, headers):
        return self._request("POST", "/network/offerings", payload, headers)

    def get_offering(self, offering_id, headers):
        return self._request("GET", f"/network/offerings/{offering_id}", headers=headers)

    def list_offerings(self, headers, params=None):
        return self._request("GET", "/network/offerings", headers=headers, params=params)

    def open_offering(self, offering_id, headers):
        return self._request("POST", f"/network/offerings/{offering_id}/open", headers=headers)

    def close_offering(self, offering_id, headers):
        return self._request("POST", f"/network/offerings/{offering_id}/close", headers=headers)

    # --- Participation certificates (commitments) ---
    def create_commitment(self, payload, headers):
        return self._request("POST", "/network/commitments", payload, headers)

    def get_commitment(self, certificate_id, headers):
        return self._request("GET", f"/network/commitments/{certificate_id}", headers=headers)

    def list_commitments(self, headers, params=None):
        return self._request("GET", "/network/commitments", headers=headers, params=params)

    def approve_diligence(self, certificate_id, headers):
        return self._request("POST", f"/network/commitments/{certificate_id}/approve-diligence", headers=headers)

    def decline_commitment(self, certificate_id, headers):
        return self._request("POST", f"/network/commitments/{certificate_id}/decline", headers=headers)

    def fund_commitment(self, certificate_id, headers):
        return self._request("POST", f"/network/commitments/{certificate_id}/fund", headers=headers)

    def rescind_commitment(self, certificate_id, headers):
        return self._request("POST", f"/network/commitments/{certificate_id}/rescind", headers=headers)

    # --- Documentation exceptions ---
    def create_exception(self, payload, headers):
        return self._request("POST", "/network/exceptions", payload, headers)

    def get_exception(self, exception_id, headers):
        return self._request("GET", f"/network/exceptions/{exception_id}", headers=headers)

    def list_exceptions(self, headers, params=None):
        return self._request("GET", "/network/exceptions", headers=headers, params=params)

    def submit_cure(self, exception_id, payload, headers):
        return self._request("POST", f"/network/exceptions/{exception_id}/submit-cure", payload, headers)

    def verify_cure(self, exception_id, payload, headers):
        return self._request("POST", f"/network/exceptions/{exception_id}/verify-cure", payload, headers)

    # --- Remittances ---
    def create_remittance(self, payload, headers):
        return self._request("POST", "/network/remittances", payload, headers)

    def get_remittance(self, remittance_id, headers):
        return self._request("GET", f"/network/remittances/{remittance_id}", headers=headers)

    def list_remittances(self, headers, params=None):
        return self._request("GET", "/network/remittances", headers=headers, params=params)

    def pay_remittance(self, remittance_id, headers):
        return self._request("POST", f"/network/remittances/{remittance_id}/pay", headers=headers)

    def reverse_remittance(self, remittance_id, headers):
        return self._request("POST", f"/network/remittances/{remittance_id}/reverse", headers=headers)

    # --- Surveillance reports ---
    def create_surveillance_report(self, payload, headers):
        return self._request("POST", "/network/surveillance-reports", payload, headers)

    def get_surveillance_report(self, report_id, headers):
        return self._request("GET", f"/network/surveillance-reports/{report_id}", headers=headers)

    def list_surveillance_reports(self, headers, params=None):
        return self._request("GET", "/network/surveillance-reports", headers=headers, params=params)

    # --- Regulatory exams & findings ---
    def create_exam(self, payload, headers):
        return self._request("POST", "/network/exams", payload, headers)

    def get_exam(self, exam_id, headers):
        return self._request("GET", f"/network/exams/{exam_id}", headers=headers)

    def list_exams(self, headers, params=None):
        return self._request("GET", "/network/exams", headers=headers, params=params)

    def finalize_exam(self, exam_id, headers):
        return self._request("POST", f"/network/exams/{exam_id}/finalize", headers=headers)

    def create_finding(self, payload, headers):
        return self._request("POST", "/network/findings", payload, headers)

    def get_finding(self, finding_id, headers):
        return self._request("GET", f"/network/findings/{finding_id}", headers=headers)

    def list_findings(self, headers, params=None):
        return self._request("GET", "/network/findings", headers=headers, params=params)

    def submit_remediation(self, finding_id, payload, headers):
        return self._request("POST", f"/network/findings/{finding_id}/submit-remediation", payload, headers)

    def verify_finding(self, finding_id, payload, headers):
        return self._request("POST", f"/network/findings/{finding_id}/verify", payload, headers)

    # --- Loss events ---
    def create_loss_event(self, payload, headers):
        return self._request("POST", "/network/loss-events", payload, headers)

    def get_loss_event(self, loss_event_id, headers):
        return self._request("GET", f"/network/loss-events/{loss_event_id}", headers=headers)

    def list_loss_events(self, headers, params=None):
        return self._request("GET", "/network/loss-events", headers=headers, params=params)

    def allocate_loss_event(self, loss_event_id, headers):
        return self._request("POST", f"/network/loss-events/{loss_event_id}/allocate", headers=headers)

    # --- Repurchase cases ---
    def create_repurchase_case(self, payload, headers):
        return self._request("POST", "/network/repurchase-cases", payload, headers)

    def get_repurchase_case(self, case_id, headers):
        return self._request("GET", f"/network/repurchase-cases/{case_id}", headers=headers)

    def list_repurchase_cases(self, headers, params=None):
        return self._request("GET", "/network/repurchase-cases", headers=headers, params=params)

    def complete_repurchase_case(self, case_id, headers):
        return self._request("POST", f"/network/repurchase-cases/{case_id}/complete", headers=headers)

    def dispute_repurchase_case(self, case_id, headers):
        return self._request("POST", f"/network/repurchase-cases/{case_id}/dispute", headers=headers)

    def withdraw_repurchase_case(self, case_id, headers):
        return self._request("POST", f"/network/repurchase-cases/{case_id}/withdraw", headers=headers)

    # --- Ops-run checkpoint & logical clock ---
    def run_sweep(self, headers):
        return self._request("POST", "/network/sweeps/run", headers=headers)

    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/network/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
