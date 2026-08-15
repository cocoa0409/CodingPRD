"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- clock -----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/siu/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ----- adjusters -----
    def create_adjuster(self, payload, headers):
        return self._request("POST", "/siu/adjusters", payload, headers)

    def get_adjuster(self, adjuster_id, headers):
        return self._request("GET", f"/siu/adjusters/{adjuster_id}", headers=headers)

    # ----- claims -----
    def create_claim(self, payload, headers):
        return self._request("POST", "/siu/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/siu/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/siu/claims", headers=headers, params=params)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/siu/claims/{claim_id}/pay", {}, headers)

    def close_claim(self, claim_id, headers):
        return self._request("POST", f"/siu/claims/{claim_id}/close-claim", {}, headers)

    def delay_payment(self, claim_id, payload, headers):
        return self._request("POST", f"/siu/claims/{claim_id}/delay-payment", payload, headers)

    def release_delay(self, claim_id, headers):
        return self._request("POST", f"/siu/claims/{claim_id}/release-delay", {}, headers)

    def list_claim_cases(self, claim_id, headers):
        return self._request("GET", f"/siu/claims/{claim_id}/cases", headers=headers)

    def list_claim_referrals(self, claim_id, headers):
        return self._request("GET", f"/siu/claims/{claim_id}/referrals", headers=headers)

    # ----- referrals -----
    def create_referral(self, payload, headers):
        return self._request("POST", "/siu/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/siu/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/siu/referrals", headers=headers, params=params)

    def triage_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/siu/referrals/{referral_id}/triage", payload, headers)

    def accept_referral(self, referral_id, headers):
        return self._request("POST", f"/siu/referrals/{referral_id}/accept", {}, headers)

    def decline_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/siu/referrals/{referral_id}/decline", payload, headers)

    def link_duplicate_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/siu/referrals/{referral_id}/link-duplicate", payload, headers)

    # ----- cases -----
    def get_case(self, case_id, headers):
        return self._request("GET", f"/siu/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/siu/cases", headers=headers, params=params)

    def open_case(self, case_id, headers):
        return self._request("POST", f"/siu/cases/{case_id}/open", {}, headers)

    def submit_case_for_decision(self, case_id, headers):
        return self._request("POST", f"/siu/cases/{case_id}/submit-for-decision", {}, headers)

    def close_case(self, case_id, payload, headers):
        return self._request("POST", f"/siu/cases/{case_id}/close", payload, headers)

    # ----- investigators -----
    def create_investigator(self, payload, headers):
        return self._request("POST", "/siu/investigators", payload, headers)

    def get_investigator(self, investigator_id, headers):
        return self._request("GET", f"/siu/investigators/{investigator_id}", headers=headers)

    def list_investigators(self, headers, params=None):
        return self._request("GET", "/siu/investigators", headers=headers, params=params)

    def list_investigator_assignments(self, investigator_id, headers):
        return self._request("GET", f"/siu/investigators/{investigator_id}/assignments", headers=headers)

    def list_investigator_training_records(self, investigator_id, headers):
        return self._request("GET", f"/siu/investigators/{investigator_id}/training-records", headers=headers)

    def list_training_records(self, headers, params=None):
        return self._request("GET", "/siu/training-records", headers=headers, params=params)

    def get_training_record(self, record_id, headers):
        return self._request("GET", f"/siu/training-records/{record_id}", headers=headers)

    def create_training_record(self, investigator_id, payload, headers):
        return self._request("POST", f"/siu/investigators/{investigator_id}/training-records",
                             payload, headers)

    def suspend_investigator(self, investigator_id, payload, headers):
        return self._request("POST", f"/siu/investigators/{investigator_id}/suspend",
                             payload, headers)

    def reinstate_investigator(self, investigator_id, headers):
        return self._request("POST", f"/siu/investigators/{investigator_id}/reinstate",
                             {}, headers)

    # ----- assignments -----
    def create_assignment(self, case_id, payload, headers):
        return self._request("POST", f"/siu/cases/{case_id}/assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/siu/assignments/{assignment_id}", headers=headers)

    def list_case_assignments(self, case_id, headers):
        return self._request("GET", f"/siu/cases/{case_id}/assignments", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/siu/assignments", headers=headers, params=params)

    def terminate_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/siu/assignments/{assignment_id}/terminate",
                             payload, headers)

    # ----- evidence -----
    def create_evidence(self, case_id, payload, headers):
        return self._request("POST", f"/siu/cases/{case_id}/evidence", payload, headers)

    def get_case_evidence(self, case_id, evidence_id, headers):
        return self._request("GET", f"/siu/cases/{case_id}/evidence/{evidence_id}", headers=headers)

    def list_case_evidence(self, case_id, headers, params=None):
        return self._request("GET", f"/siu/cases/{case_id}/evidence", headers=headers, params=params)

    def list_evidence(self, headers, params=None):
        return self._request("GET", "/siu/evidence", headers=headers, params=params)

    def get_evidence(self, evidence_id, headers):
        return self._request("GET", f"/siu/evidence/{evidence_id}", headers=headers)

    def submit_evidence_review(self, case_id, evidence_id, headers):
        return self._request("POST", f"/siu/cases/{case_id}/evidence/{evidence_id}/submit-review",
                             {}, headers)

    def admit_evidence(self, case_id, evidence_id, payload, headers):
        return self._request("POST", f"/siu/cases/{case_id}/evidence/{evidence_id}/admit",
                             payload, headers)

    def exclude_evidence(self, case_id, evidence_id, payload, headers):
        return self._request("POST", f"/siu/cases/{case_id}/evidence/{evidence_id}/exclude",
                             payload, headers)

    def return_evidence_for_more_work(self, case_id, evidence_id, payload, headers):
        return self._request("POST",
                             f"/siu/cases/{case_id}/evidence/{evidence_id}/return-for-more-work",
                             payload, headers)

    def seal_evidence(self, case_id, evidence_id, headers):
        return self._request("POST", f"/siu/cases/{case_id}/evidence/{evidence_id}/seal",
                             {}, headers)

    # ----- EUO sessions -----
    def create_euo_session(self, case_id, payload, headers):
        return self._request("POST", f"/siu/cases/{case_id}/euo-sessions", payload, headers)

    def list_case_euo_sessions(self, case_id, headers, params=None):
        return self._request("GET", f"/siu/cases/{case_id}/euo-sessions", headers=headers, params=params)

    def list_euo_sessions(self, headers, params=None):
        return self._request("GET", "/siu/euo-sessions", headers=headers, params=params)

    def get_euo_session(self, euo_id, headers):
        return self._request("GET", f"/siu/euo-sessions/{euo_id}", headers=headers)

    def get_case_euo_session(self, case_id, euo_id, headers):
        return self._request("GET", f"/siu/cases/{case_id}/euo-sessions/{euo_id}", headers=headers)

    def send_euo_notice(self, case_id, euo_id, headers):
        return self._request("POST", f"/siu/cases/{case_id}/euo-sessions/{euo_id}/send-notice",
                             {}, headers)

    def conduct_euo(self, case_id, euo_id, headers):
        return self._request("POST", f"/siu/cases/{case_id}/euo-sessions/{euo_id}/conduct",
                             {}, headers)

    def no_show_euo(self, case_id, euo_id, headers):
        return self._request("POST", f"/siu/cases/{case_id}/euo-sessions/{euo_id}/no-show",
                             {}, headers)

    def reschedule_euo(self, case_id, euo_id, payload, headers):
        return self._request("POST", f"/siu/cases/{case_id}/euo-sessions/{euo_id}/reschedule",
                             payload, headers)

    def cancel_euo(self, case_id, euo_id, payload, headers):
        return self._request("POST", f"/siu/cases/{case_id}/euo-sessions/{euo_id}/cancel",
                             payload, headers)

    # ----- bureau referrals -----
    def list_case_bureau_referrals(self, case_id, headers):
        return self._request("GET", f"/siu/cases/{case_id}/bureau-referrals", headers=headers)

    def list_bureau_referrals(self, headers, params=None):
        return self._request("GET", "/siu/bureau-referrals", headers=headers, params=params)

    def get_bureau_referral(self, referral_id, headers):
        return self._request("GET", f"/siu/bureau-referrals/{referral_id}", headers=headers)

    def get_case_bureau_referral(self, case_id, referral_id, headers):
        return self._request("GET", f"/siu/cases/{case_id}/bureau-referrals/{referral_id}",
                             headers=headers)

    def file_bureau_referral(self, case_id, referral_id, payload, headers):
        return self._request("POST", f"/siu/cases/{case_id}/bureau-referrals/{referral_id}/file",
                             payload, headers)

    def acknowledge_bureau_referral(self, case_id, referral_id, headers):
        return self._request("POST",
                             f"/siu/cases/{case_id}/bureau-referrals/{referral_id}/acknowledge",
                             {}, headers)

    def reject_bureau_referral(self, case_id, referral_id, payload, headers):
        return self._request("POST",
                             f"/siu/cases/{case_id}/bureau-referrals/{referral_id}/reject",
                             payload, headers)

    # ----- provider patterns -----
    def create_provider_pattern(self, payload, headers):
        return self._request("POST", "/siu/provider-patterns", payload, headers)

    def get_provider_pattern(self, pattern_id, headers):
        return self._request("GET", f"/siu/provider-patterns/{pattern_id}", headers=headers)

    def list_provider_patterns(self, headers, params=None):
        return self._request("GET", "/siu/provider-patterns", headers=headers, params=params)

    def escalate_provider_pattern(self, pattern_id, headers):
        return self._request("POST", f"/siu/provider-patterns/{pattern_id}/escalate", {}, headers)

    def clear_provider_pattern(self, pattern_id, headers):
        return self._request("POST", f"/siu/provider-patterns/{pattern_id}/clear", {}, headers)

    def merge_provider_pattern(self, pattern_id, payload, headers):
        return self._request("POST", f"/siu/provider-patterns/{pattern_id}/merge", payload, headers)

    # ----- restitution ledgers / payments -----
    def create_restitution_ledger(self, case_id, payload, headers):
        return self._request("POST", f"/siu/cases/{case_id}/restitution-ledgers", payload, headers)

    def list_case_ledgers(self, case_id, headers):
        return self._request("GET", f"/siu/cases/{case_id}/restitution-ledgers", headers=headers)

    def list_ledgers(self, headers, params=None):
        return self._request("GET", "/siu/ledgers", headers=headers, params=params)

    def get_ledger(self, ledger_id, headers):
        return self._request("GET", f"/siu/ledgers/{ledger_id}", headers=headers)

    def list_ledger_payments(self, ledger_id, headers):
        return self._request("GET", f"/siu/ledgers/{ledger_id}/payments", headers=headers)

    def list_recovery_payments(self, headers, params=None):
        return self._request("GET", "/siu/recovery-payments", headers=headers, params=params)

    def get_recovery_payment(self, payment_id, headers):
        return self._request("GET", f"/siu/recovery-payments/{payment_id}", headers=headers)

    def create_recovery_payment(self, ledger_id, payload, headers):
        return self._request("POST", f"/siu/ledgers/{ledger_id}/payments", payload, headers)

    def clear_recovery_payment(self, ledger_id, payment_id, payload, headers):
        return self._request("POST", f"/siu/ledgers/{ledger_id}/payments/{payment_id}/clear",
                             payload, headers)

    def return_recovery_payment(self, ledger_id, payment_id, payload, headers):
        return self._request("POST", f"/siu/ledgers/{ledger_id}/payments/{payment_id}/return",
                             payload, headers)

    def reverse_recovery_payment(self, ledger_id, payment_id, payload, headers):
        return self._request("POST", f"/siu/ledgers/{ledger_id}/payments/{payment_id}/reverse",
                             payload, headers)

    def write_off_ledger(self, case_id, ledger_id, payload, headers):
        return self._request("POST",
                             f"/siu/cases/{case_id}/restitution-ledgers/{ledger_id}/write-off",
                             payload, headers)

    # ----- reports -----
    def create_report(self, payload, headers):
        return self._request("POST", "/siu/reports", payload, headers)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/siu/reports/{report_id}", headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/siu/reports", headers=headers, params=params)

    def compute_report(self, report_id, headers):
        return self._request("POST", f"/siu/reports/{report_id}/compute", {}, headers)

    def submit_report(self, report_id, headers):
        return self._request("POST", f"/siu/reports/{report_id}/submit", {}, headers)

    def accept_report(self, report_id, headers):
        return self._request("POST", f"/siu/reports/{report_id}/accept", {}, headers)

    def reject_report(self, report_id, payload, headers):
        return self._request("POST", f"/siu/reports/{report_id}/reject", payload, headers)


api_client = ApiClient()
