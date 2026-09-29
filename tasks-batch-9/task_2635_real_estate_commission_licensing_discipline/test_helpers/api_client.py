"""One typed method per endpoint published in the PRD's endpoint table.

Every path is mounted under the `/commission` prefix.  Methods return the raw
`requests.Response` so the caller decides between `validate_success`,
`validate_error` and `validate_paginated`.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


class CommissionApiClient(GenericApiClient):
    """Thin, explicit wrapper over the commission's HTTP surface."""

    # ---------------------------------------------------------------- clock

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers=headers,
        )

    # ------------------------------------------------------------ licensees

    def create_licensee(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(f"{API_PREFIX}/licensees", payload, headers=headers)

    def get_licensee(self, licensee_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/licensees/{licensee_id}", headers=headers)

    def list_licensees(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self.get(f"{API_PREFIX}/licensees", headers=headers, params=params)

    def record_exam_result(self, licensee_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/licensees/{licensee_id}/exam-results", payload, headers=headers
        )

    def create_affiliation(self, licensee_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/licensees/{licensee_id}/affiliations", payload, headers=headers
        )

    def create_status_change(self, licensee_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/licensees/{licensee_id}/status-changes", payload, headers=headers
        )

    # ----------------------------------------------------------- brokerages

    def create_brokerage(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(f"{API_PREFIX}/brokerages", payload, headers=headers)

    def get_brokerage(self, brokerage_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/brokerages/{brokerage_id}", headers=headers)

    def list_brokerages(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self.get(f"{API_PREFIX}/brokerages", headers=headers, params=params)

    def activate_brokerage(
        self, brokerage_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ):
        return self.post(
            f"{API_PREFIX}/brokerages/{brokerage_id}/activation", payload or {}, headers=headers
        )

    # ------------------------------------------------------- trust accounts

    def create_trust_account(self, brokerage_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/brokerages/{brokerage_id}/trust-accounts", payload, headers=headers
        )

    def get_trust_account(self, account_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/trust-accounts/{account_id}", headers=headers)

    def list_trust_accounts(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self.get(f"{API_PREFIX}/trust-accounts", headers=headers, params=params)

    def create_ledger_entry(self, account_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/trust-accounts/{account_id}/ledger-entries", payload, headers=headers
        )

    def list_ledger_entries(
        self, account_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get(
            f"{API_PREFIX}/trust-accounts/{account_id}/ledger-entries", headers=headers, params=params
        )

    # --------------------------------------------------------- trust audits

    def schedule_audit(self, account_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/trust-accounts/{account_id}/audits", payload, headers=headers
        )

    def get_trust_audit(self, audit_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/trust-audits/{audit_id}", headers=headers)

    def list_trust_audits(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self.get(f"{API_PREFIX}/trust-audits", headers=headers, params=params)

    def open_fieldwork(self, audit_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/trust-audits/{audit_id}/fieldwork", payload, headers=headers
        )

    def audit_disposition(self, audit_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/trust-audits/{audit_id}/disposition", payload, headers=headers
        )

    # ------------------------------------------------------------- sweeps

    def run_compliance_sweep(self, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self.post(f"{API_PREFIX}/compliance-sweeps", payload or {}, headers=headers)

    # ----------------------------------------------------------- complaints

    def create_complaint(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(f"{API_PREFIX}/complaints", payload, headers=headers)

    def get_complaint(self, complaint_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/complaints/{complaint_id}", headers=headers)

    def list_complaints(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self.get(f"{API_PREFIX}/complaints", headers=headers, params=params)

    def complaint_disposition(self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/complaints/{complaint_id}/disposition", payload, headers=headers
        )

    def create_amendment(self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/complaints/{complaint_id}/amendments", payload, headers=headers
        )

    # --------------------------------------------------- consent agreements

    def create_consent_agreement(self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/complaints/{complaint_id}/consent-agreements", payload, headers=headers
        )

    def list_consent_agreements(
        self, complaint_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get(
            f"{API_PREFIX}/complaints/{complaint_id}/consent-agreements",
            headers=headers,
            params=params,
        )

    def get_consent_agreement(self, agreement_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/consent-agreements/{agreement_id}", headers=headers)

    def respondent_response(self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/consent-agreements/{agreement_id}/respondent-response",
            payload,
            headers=headers,
        )

    def commission_action(self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/consent-agreements/{agreement_id}/commission-action",
            payload,
            headers=headers,
        )

    # ------------------------------------------------------------- hearings

    def schedule_hearing(self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/complaints/{complaint_id}/hearings", payload, headers=headers
        )

    def list_hearings(
        self, complaint_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get(
            f"{API_PREFIX}/complaints/{complaint_id}/hearings", headers=headers, params=params
        )

    def get_hearing(self, hearing_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/hearings/{hearing_id}", headers=headers)

    def hearing_disposition(self, hearing_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/hearings/{hearing_id}/disposition", payload, headers=headers
        )

    # ------------------------------------------------------ sanction orders

    def get_sanction_order(self, order_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/sanction-orders/{order_id}", headers=headers)

    def list_sanction_orders(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self.get(f"{API_PREFIX}/sanction-orders", headers=headers, params=params)

    def create_fine_payment(self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/sanction-orders/{order_id}/fine-payments", payload, headers=headers
        )

    def vacate_order(self, order_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self.post(
            f"{API_PREFIX}/sanction-orders/{order_id}/vacatur", payload or {}, headers=headers
        )

    # -------------------------------------------------------- recovery fund

    def create_recovery_claim(self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/sanction-orders/{order_id}/recovery-claims", payload, headers=headers
        )

    def list_recovery_claims(
        self, order_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get(
            f"{API_PREFIX}/sanction-orders/{order_id}/recovery-claims", headers=headers, params=params
        )

    def get_recovery_fund(self, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/recovery-fund", headers=headers)

    def create_appropriation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(f"{API_PREFIX}/recovery-fund/appropriations", payload, headers=headers)

    def run_disbursement(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(f"{API_PREFIX}/recovery-fund/disbursements", payload, headers=headers)

    # --------------------------------------------------- education oversight

    def create_education_provider(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(f"{API_PREFIX}/education-providers", payload, headers=headers)

    def get_education_provider(self, provider_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/education-providers/{provider_id}", headers=headers)

    def list_education_providers(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self.get(f"{API_PREFIX}/education-providers", headers=headers, params=params)

    def approve_education_provider(
        self, provider_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ):
        return self.post(
            f"{API_PREFIX}/education-providers/{provider_id}/approval", payload or {}, headers=headers
        )

    def create_instructor(self, provider_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/education-providers/{provider_id}/instructors", payload, headers=headers
        )

    def get_instructor(self, instructor_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/instructors/{instructor_id}", headers=headers)

    def list_instructors(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self.get(f"{API_PREFIX}/instructors", headers=headers, params=params)

    def approve_instructor(
        self, instructor_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ):
        return self.post(
            f"{API_PREFIX}/instructors/{instructor_id}/approval", payload or {}, headers=headers
        )

    def create_course_completion(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(f"{API_PREFIX}/course-completions", payload, headers=headers)

    def get_course_completion(self, completion_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/course-completions/{completion_id}", headers=headers)

    def list_course_completions(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self.get(f"{API_PREFIX}/course-completions", headers=headers, params=params)

    # ----------------------------------------------------- advertising names

    def create_advertising_name(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(f"{API_PREFIX}/advertising-names", payload, headers=headers)

    def get_advertising_name(self, name_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/advertising-names/{name_id}", headers=headers)

    def list_advertising_names(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self.get(f"{API_PREFIX}/advertising-names", headers=headers, params=params)

    def review_advertising_name(self, name_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/advertising-names/{name_id}/review", payload, headers=headers
        )
