"""
Composite setup chains for the Employer Tuition Benefit Administration API.

Every precondition is built from scratch through the PRD's own endpoints, since
each test starts against an empty database. `Scenario` bundles the identity
headers and the ids a chain produces, and its methods are the single-hop steps;
the module-level builders below stitch those hops into the named business
situations the tests need.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import TuitionBenefitApiClient
from .factories import (
    academic_outcome_payload,
    approval_decision_payload,
    benefit_policy_payload,
    catalog_listing_payload,
    claim_decision_payload,
    coaching_session_payload,
    employee_payload,
    employer_payload,
    enrollment_payload,
    partner_agreement_payload,
    program_approval_request_payload,
    program_payload,
    reimbursement_claim_payload,
    repayment_payment_payload,
    resubmit_payload,
    school_payload,
    term_close_payload,
)
from .test_users import (
    make_benefit_administrator_headers,
    make_coach_headers,
    make_employee_headers,
    make_platform_admin_headers,
    make_school_partner_headers,
)
from .types import (
    ApprovalDecision,
    ClaimDecision,
    CompletionStatus,
    CredentialType,
    FundingModel,
    JobFamily,
    SkillTrack,
)

Record = Dict[str, Any]


class Scenario:
    """Carrier for the ids, versions and headers one setup chain produces."""

    def __init__(self, api: TuitionBenefitApiClient):
        self.api = api
        self.platform_admin = make_platform_admin_headers()
        self.coach = make_coach_headers()
        self.employer_id: str = ""
        self.school_id: str = ""
        self.program_id: str = ""
        self.employee_id: str = ""
        self.policy_id: str = ""
        self.agreement_id: str = ""
        self.listing_id: str = ""
        self.enrollment_id: str = ""
        self.invoice_id: str = ""
        self.claim_id: str = ""
        self.obligation_id: str = ""
        self.request_id: str = ""
        self.annual_cap_cents: int = 0
        # Second-hop handles for chains that build two enrollments or invoices.
        self.first_enrollment_id: str = ""
        self.second_enrollment_id: str = ""
        self.first_invoice_id: str = ""
        self.second_invoice_id: str = ""
        self.second_listing_id: str = ""
        self.second_program_id: str = ""
        self.second_policy_id: str = ""
        self.second_claim_id: str = ""
        # Third-hop handles for the one chain that curates three programs.
        self.third_enrollment_id: str = ""
        self.third_listing_id: str = ""
        self.third_program_id: str = ""

    # ─── Identity headers (PRD §2.1) ───────────────────────────────────────
    @property
    def benefit_admin(self) -> Dict[str, str]:
        return make_benefit_administrator_headers(self.employer_id)

    @property
    def employee(self) -> Dict[str, str]:
        return make_employee_headers(self.employee_id)

    @property
    def school_partner(self) -> Dict[str, str]:
        return make_school_partner_headers(self.school_id)

    # ─── Reads (used to obtain live versions and derived figures) ─────────
    def read_employee(self, employee_id: Optional[str] = None) -> Record:
        target = employee_id or self.employee_id
        return get_success_data(
            self.api.get_employee(target, make_employee_headers(target))
        )

    def employee_version(self, employee_id: Optional[str] = None) -> int:
        return self.read_employee(employee_id)["version"]

    def read_agreement(self, agreement_id: Optional[str] = None) -> Record:
        return get_success_data(
            self.api.get_partner_agreement(
                agreement_id or self.agreement_id, self.platform_admin
            )
        )

    def agreement_version(self, agreement_id: Optional[str] = None) -> int:
        return self.read_agreement(agreement_id)["version"]

    def read_enrollment(self, enrollment_id: Optional[str] = None) -> Record:
        return get_success_data(
            self.api.get_enrollment(
                enrollment_id or self.enrollment_id, self.employee
            )
        )

    def read_employer(self) -> Record:
        return get_success_data(
            self.api.get_employer(self.employer_id, self.benefit_admin)
        )

    def read_listing(self, listing_id: Optional[str] = None) -> Record:
        return get_success_data(
            self.api.get_catalog_listing(
                listing_id or self.listing_id, self.benefit_admin
            )
        )

    def ledger_entries(self, employee_id: Optional[str] = None) -> List[Record]:
        data = get_success_data(
            self.api.list_tax_ledger_entries(
                self.benefit_admin,
                {"employee_id": employee_id or self.employee_id, "limit": 100},
            )
        )
        return data

    # ─── Single hops ───────────────────────────────────────────────────────
    def set_clock(self, to_iso8601: str) -> Record:
        return get_success_data(self.api.set_clock(to_iso8601, self.platform_admin))

    def onboard_employer(self, **kwargs) -> Record:
        data = get_success_data(
            self.api.create_employer(employer_payload(**kwargs), self.platform_admin)
        )
        self.employer_id = data["id"]
        return data

    def draft_policy(self, primary: bool = True, **kwargs) -> Record:
        data = get_success_data(
            self.api.create_benefit_policy(
                self.employer_id, benefit_policy_payload(**kwargs), self.benefit_admin
            )
        )
        if primary:
            self.policy_id = data["id"]
            self.annual_cap_cents = data["annual_cap_cents"]
        return data

    def activate_policy(self, policy_id: Optional[str] = None) -> Record:
        return get_success_data(
            self.api.activate_benefit_policy(
                policy_id or self.policy_id, self.benefit_admin
            )
        )

    def register_employee(self, primary: bool = True, **kwargs) -> Record:
        data = get_success_data(
            self.api.create_employee(
                self.employer_id, employee_payload(**kwargs), self.benefit_admin
            )
        )
        if primary:
            self.employee_id = data["id"]
        return data

    def register_school(self, primary: bool = True, **kwargs) -> Record:
        data = get_success_data(
            self.api.create_school(school_payload(**kwargs), self.platform_admin)
        )
        if primary:
            self.school_id = data["id"]
        return data

    def publish_program(
        self, primary: bool = True, school_id: Optional[str] = None, **kwargs
    ) -> Record:
        target_school = school_id or self.school_id
        data = get_success_data(
            self.api.create_program(
                target_school,
                program_payload(**kwargs),
                make_school_partner_headers(target_school),
            )
        )
        if primary:
            self.program_id = data["id"]
        return data

    def draft_agreement(
        self, primary: bool = True, school_id: Optional[str] = None, **kwargs
    ) -> Record:
        data = get_success_data(
            self.api.create_partner_agreement(
                partner_agreement_payload(
                    employer_id=self.employer_id,
                    school_id=school_id or self.school_id,
                    **kwargs,
                ),
                self.platform_admin,
            )
        )
        if primary:
            self.agreement_id = data["id"]
        return data

    def activate_agreement(self, agreement_id: Optional[str] = None) -> Record:
        return get_success_data(
            self.api.activate_partner_agreement(
                agreement_id or self.agreement_id, self.benefit_admin
            )
        )

    def curate_listing(
        self,
        primary: bool = True,
        program_id: Optional[str] = None,
        agreement_id: Optional[str] = None,
    ) -> Record:
        target_agreement = agreement_id or self.agreement_id
        data = get_success_data(
            self.api.create_catalog_listing(
                catalog_listing_payload(
                    employer_id=self.employer_id,
                    program_id=program_id or self.program_id,
                    agreement_id=target_agreement,
                    expected_agreement_version=self.agreement_version(
                        target_agreement
                    ),
                ),
                self.benefit_admin,
            )
        )
        if primary:
            self.listing_id = data["id"]
        return data

    def enroll(
        self,
        primary: bool = True,
        employee_id: Optional[str] = None,
        listing_id: Optional[str] = None,
        **kwargs,
    ) -> Record:
        target_employee = employee_id or self.employee_id
        data = get_success_data(
            self.api.create_enrollment(
                enrollment_payload(
                    employee_id=target_employee,
                    catalog_listing_id=listing_id or self.listing_id,
                    expected_employee_version=self.employee_version(target_employee),
                    **kwargs,
                ),
                make_employee_headers(target_employee),
            )
        )
        if primary:
            self.enrollment_id = data["id"]
        return data

    def confirm_registration(self, enrollment_id: Optional[str] = None) -> Record:
        return get_success_data(
            self.api.confirm_registration(
                enrollment_id or self.enrollment_id, self.school_partner
            )
        )

    def withdraw(self, enrollment_id: Optional[str] = None) -> Record:
        target = enrollment_id or self.enrollment_id
        return get_success_data(
            self.api.withdraw_enrollment(target, self.employee)
        )

    def post_outcome(
        self,
        term_code: str,
        completion_status: str,
        credits_earned: int,
        grade_points: Optional[float] = None,
        enrollment_id: Optional[str] = None,
    ) -> Record:
        return get_success_data(
            self.api.create_academic_outcome(
                enrollment_id or self.enrollment_id,
                academic_outcome_payload(
                    term_code, completion_status, credits_earned, grade_points
                ),
                self.school_partner,
            )
        )

    def first_invoice(self, enrollment_id: Optional[str] = None) -> Record:
        data = get_success_data(
            self.api.list_enrollment_invoices(
                enrollment_id or self.enrollment_id, self.benefit_admin
            )
        )
        assert data, "expected the direct-bill confirmation to have raised an invoice"
        self.invoice_id = data[0]["id"]
        return data[0]

    def approve_invoice(self, invoice_id: Optional[str] = None) -> Record:
        return get_success_data(
            self.api.approve_invoice_for_payment(
                invoice_id or self.invoice_id, self.benefit_admin
            )
        )

    def pay_invoice(self, invoice_id: Optional[str] = None) -> Record:
        return get_success_data(
            self.api.pay_invoice(invoice_id or self.invoice_id, self.platform_admin)
        )

    def file_claim(
        self,
        amount_requested_cents: int,
        receipt_reference: str,
        enrollment_id: Optional[str] = None,
    ) -> Record:
        data = get_success_data(
            self.api.create_reimbursement_claim(
                enrollment_id or self.enrollment_id,
                reimbursement_claim_payload(
                    amount_requested_cents, receipt_reference
                ),
                self.employee,
            )
        )
        self.claim_id = data["id"]
        return data

    def decide_claim(
        self,
        decision: str = ClaimDecision.APPROVE,
        decision_note: Optional[str] = None,
        claim_id: Optional[str] = None,
    ) -> Record:
        return get_success_data(
            self.api.decide_reimbursement_claim(
                claim_id or self.claim_id,
                claim_decision_payload(decision, decision_note),
                self.benefit_admin,
            )
        )

    def first_obligation(self, enrollment_id: Optional[str] = None) -> Record:
        data = get_success_data(
            self.api.list_repayment_obligations(
                enrollment_id or self.enrollment_id, self.benefit_admin
            )
        )
        assert data, "expected the clawback chain to have assessed an obligation"
        self.obligation_id = data[0]["id"]
        return data[0]

    def pay_obligation(
        self, amount_cents: int, obligation_id: Optional[str] = None
    ) -> Record:
        return get_success_data(
            self.api.create_repayment_payment(
                obligation_id or self.obligation_id,
                repayment_payment_payload(amount_cents),
                self.employee,
            )
        )

    def waive_obligation(self, obligation_id: Optional[str] = None) -> Record:
        return get_success_data(
            self.api.waive_repayment_obligation(
                obligation_id or self.obligation_id, self.benefit_admin
            )
        )

    def log_session(
        self,
        session_date: str,
        modality: str = "VIDEO",
        risk_flags: Optional[List[str]] = None,
        enrollment_id: Optional[str] = None,
    ) -> Record:
        return get_success_data(
            self.api.create_coaching_session(
                enrollment_id or self.enrollment_id,
                coaching_session_payload(session_date, modality, risk_flags),
                self.coach,
            )
        )

    def open_approval_request(
        self, program_id: Optional[str] = None, **kwargs
    ) -> Record:
        data = get_success_data(
            self.api.create_program_approval_request(
                program_approval_request_payload(
                    employee_id=self.employee_id,
                    program_id=program_id or self.program_id,
                    **kwargs,
                ),
                self.employee,
            )
        )
        self.request_id = data["id"]
        return data

    def review_request(self, request_id: Optional[str] = None) -> Record:
        return get_success_data(
            self.api.review_program_approval_request(
                request_id or self.request_id, self.benefit_admin
            )
        )

    def decide_request(
        self,
        decision: str,
        decision_note: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Record:
        return get_success_data(
            self.api.decide_program_approval_request(
                request_id or self.request_id,
                approval_decision_payload(decision, decision_note),
                self.benefit_admin,
            )
        )

    def close_term(self, term_code: str, **kwargs) -> Record:
        return get_success_data(
            self.api.term_close(
                term_close_payload(term_code, **kwargs), self.platform_admin
            )
        )


# ══════════════════════════════════════════════════════════════════════════
# Vantage Foods Group — hybrid policy, 20% discount, 40,000-cent listing rate
# ══════════════════════════════════════════════════════════════════════════
def build_vantage_base(api: TuitionBenefitApiClient) -> Scenario:
    """Employer, active hybrid policy, eligible learner, active agreement, listing."""
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.onboard_employer(
        legal_name="Vantage Foods Group",
        benefit_admin_contact_email="benefits@vantage-foods.example",
        fiscal_year_start_month=1,
    )
    s.draft_policy(
        effective_from="2026-01-01",
        effective_to="2027-01-01",
        min_tenure_months=6,
        min_weekly_hours=20,
        eligible_job_families=[JobFamily.OPERATIONS],
        annual_cap_cents=1_000_000,
        funding_model=FundingModel.HYBRID,
        reimbursement_pct=0.50,
        max_concurrent_credits=12,
        drop_window_days=14,
        service_commitment_months=12,
    )
    s.activate_policy()
    s.register_employee(
        full_name="Rosa Delgado",
        work_email="rosa.delgado@vantage-foods.example",
        hire_date="2024-01-15",
        weekly_hours=40,
        job_family=JobFamily.OPERATIONS,
    )
    s.register_school(
        legal_name="Cascade Valley College",
        state_code="WA",
        contact_email="partners@cascadevalley.example",
    )
    s.publish_program(
        name="Certificate in Food Safety Analytics",
        credential_type=CredentialType.CERTIFICATE,
        skill_track=SkillTrack.DATA_ANALYTICS,
        list_tuition_per_credit_cents=50_000,
        total_credits=12,
        term_length_weeks=10,
    )
    s.draft_agreement(
        negotiated_discount_pct=0.20,
        direct_bill_enabled=True,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    s.activate_agreement()
    s.curate_listing()
    return s


def build_vantage_reimbursement_enrolled(api: TuitionBenefitApiClient) -> Scenario:
    """Vantage base plus a four-credit REIMBURSEMENT enrollment for 2026-FA."""
    s = build_vantage_base(api)
    s.enroll(
        term_code="2026-FA",
        term_start_date="2026-09-01",
        term_end_date="2026-12-15",
        credits=4,
        funding_model=FundingModel.REIMBURSEMENT,
    )
    return s


def build_vantage_reimbursement_in_progress(api: TuitionBenefitApiClient) -> Scenario:
    """The reimbursement enrollment with its registration confirmed."""
    s = build_vantage_reimbursement_enrolled(api)
    s.confirm_registration()
    return s


def build_vantage_reimbursement_passed(api: TuitionBenefitApiClient) -> Scenario:
    """Term closed at 2026-12-20 with a passing 3.60 outcome on all four credits."""
    s = build_vantage_reimbursement_in_progress(api)
    s.set_clock("2026-12-20T00:00:00Z")
    s.post_outcome("2026-FA", CompletionStatus.PASSED, 4, 3.60)
    return s


def build_vantage_reimbursement_settled(api: TuitionBenefitApiClient) -> Scenario:
    """A filed claim for the full gross tuition, approved by the employer."""
    s = build_vantage_reimbursement_passed(api)
    s.file_claim(160_000, "CVC-2026FA-RDELGADO-01")
    s.decide_claim(ClaimDecision.APPROVE)
    return s


def build_vantage_direct_bill_enrolled(api: TuitionBenefitApiClient) -> Scenario:
    """Vantage base plus a four-credit DIRECT_BILL enrollment for 2026-FA."""
    s = build_vantage_base(api)
    s.enroll(
        term_code="2026-FA",
        term_start_date="2026-09-01",
        term_end_date="2026-12-15",
        credits=4,
        funding_model=FundingModel.DIRECT_BILL,
    )
    return s


def build_vantage_direct_bill_billed(api: TuitionBenefitApiClient) -> Scenario:
    """The direct-bill enrollment confirmed, so its up-front invoice exists."""
    s = build_vantage_direct_bill_enrolled(api)
    s.confirm_registration()
    s.first_invoice()
    return s


def build_vantage_direct_bill_paid(api: TuitionBenefitApiClient) -> Scenario:
    """The up-front invoice approved and disbursed, before any outcome exists."""
    s = build_vantage_direct_bill_billed(api)
    s.approve_invoice()
    s.pay_invoice()
    return s


def build_vantage_direct_bill_clawed_back(api: TuitionBenefitApiClient) -> Scenario:
    """A settled direct-bill term that then fails, so an obligation is assessed."""
    s = build_vantage_direct_bill_paid(api)
    s.set_clock("2026-12-20T00:00:00Z")
    s.post_outcome("2026-FA", CompletionStatus.FAILED, 0, 1.50)
    s.first_obligation()
    return s


def build_vantage_exception_path(api: TuitionBenefitApiClient) -> Scenario:
    """Vantage employer, policy and learner plus an uncurated master's program."""
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.onboard_employer(
        legal_name="Vantage Foods Group",
        benefit_admin_contact_email="benefits@vantage-foods.example",
        fiscal_year_start_month=1,
    )
    s.draft_policy(
        effective_from="2026-01-01",
        effective_to="2027-01-01",
        min_tenure_months=6,
        min_weekly_hours=20,
        eligible_job_families=[JobFamily.OPERATIONS],
        annual_cap_cents=1_000_000,
        funding_model=FundingModel.HYBRID,
        reimbursement_pct=0.50,
        max_concurrent_credits=12,
        drop_window_days=14,
        service_commitment_months=12,
    )
    s.activate_policy()
    s.register_employee(
        full_name="Rosa Delgado",
        work_email="rosa.delgado@vantage-foods.example",
        hire_date="2024-01-15",
        weekly_hours=40,
        job_family=JobFamily.OPERATIONS,
    )
    s.register_school(
        legal_name="Cascade Valley College",
        state_code="WA",
        contact_email="partners@cascadevalley.example",
    )
    s.publish_program(
        name="Master of Science in Food Systems",
        credential_type=CredentialType.MASTER,
        skill_track=SkillTrack.SUPPLY_CHAIN,
        list_tuition_per_credit_cents=75_000,
        total_credits=30,
        term_length_weeks=15,
    )
    return s


# ══════════════════════════════════════════════════════════════════════════
# Northwind Retail Group — reimbursement at 0.60, fiscal year starting in July
# ══════════════════════════════════════════════════════════════════════════
def build_northwind_base(api: TuitionBenefitApiClient) -> Scenario:
    """A 41,002-cent list price discounted 25% into a 30,752-cent listing rate."""
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.onboard_employer(
        legal_name="Northwind Retail Group",
        benefit_admin_contact_email="benefits@northwind-retail.example",
        fiscal_year_start_month=7,
    )
    s.draft_policy(
        effective_from="2026-07-01",
        effective_to="2027-07-01",
        min_tenure_months=6,
        min_weekly_hours=20,
        eligible_job_families=[JobFamily.RETAIL_FRONTLINE, JobFamily.OPERATIONS],
        annual_cap_cents=600_000,
        funding_model=FundingModel.REIMBURSEMENT,
        reimbursement_pct=0.60,
        max_concurrent_credits=9,
        drop_window_days=14,
        service_commitment_months=12,
    )
    s.activate_policy()
    s.register_employee(
        full_name="Dana Okafor",
        work_email="dana.okafor@northwind-retail.example",
        hire_date="2025-01-15",
        weekly_hours=32,
        job_family=JobFamily.RETAIL_FRONTLINE,
    )
    s.register_school(
        legal_name="Cascade State University",
        state_code="WA",
        contact_email="registrar@cascadestate.example",
    )
    s.publish_program(
        name="BS Supply Chain Management",
        credential_type=CredentialType.BACHELOR,
        skill_track=SkillTrack.SUPPLY_CHAIN,
        list_tuition_per_credit_cents=41_002,
        total_credits=120,
        term_length_weeks=15,
    )
    s.draft_agreement(
        negotiated_discount_pct=0.25,
        direct_bill_enabled=True,
        effective_from="2026-07-01",
        effective_to="2027-06-30",
    )
    s.activate_agreement()
    s.curate_listing()
    return s


def build_northwind_three_credit_enrolled(api: TuitionBenefitApiClient) -> Scenario:
    """A three-credit 2026-FA term: 92,256 gross against a 55,354 reservation."""
    s = build_northwind_base(api)
    s.enroll(
        term_code="2026-FA",
        term_start_date="2026-09-01",
        term_end_date="2026-12-15",
        credits=3,
    )
    return s


def build_northwind_three_credit_in_progress(api: TuitionBenefitApiClient) -> Scenario:
    """The three-credit term with its registration confirmed."""
    s = build_northwind_three_credit_enrolled(api)
    s.confirm_registration()
    return s


def build_northwind_six_credit_enrolled(api: TuitionBenefitApiClient) -> Scenario:
    """A six-credit 2026-FA term: 184,512 gross against a 110,707 reservation."""
    s = build_northwind_base(api)
    s.enroll(
        term_code="2026-FA",
        term_start_date="2026-09-01",
        term_end_date="2026-12-15",
        credits=6,
    )
    return s


# ══════════════════════════════════════════════════════════════════════════
# Beacon Analytics Holdings — direct bill at 100%, 52,500-cent listing rate
# ══════════════════════════════════════════════════════════════════════════
def build_beacon_base(api: TuitionBenefitApiClient) -> Scenario:
    """A 70,000-cent list price discounted 25% into a 52,500-cent listing rate."""
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.onboard_employer(
        legal_name="Beacon Analytics Holdings",
        benefit_admin_contact_email="benefits@beacon-analytics.example",
        fiscal_year_start_month=1,
    )
    s.draft_policy(
        effective_from="2026-01-01",
        effective_to="2027-01-01",
        min_tenure_months=3,
        min_weekly_hours=20,
        eligible_job_families=[JobFamily.CORPORATE],
        annual_cap_cents=1_000_000,
        funding_model=FundingModel.DIRECT_BILL,
        reimbursement_pct=1.00,
        max_concurrent_credits=12,
        drop_window_days=7,
        service_commitment_months=12,
    )
    s.activate_policy()
    s.register_employee(
        full_name="Priya Raman",
        work_email="priya.raman@beacon-analytics.example",
        hire_date="2024-06-01",
        weekly_hours=40,
        job_family=JobFamily.CORPORATE,
    )
    s.register_school(
        legal_name="Riverbend Technical Institute",
        state_code="OR",
        contact_email="registrar@riverbendtech.example",
    )
    s.publish_program(
        name="Certificate in Data Analytics",
        credential_type=CredentialType.CERTIFICATE,
        skill_track=SkillTrack.DATA_ANALYTICS,
        list_tuition_per_credit_cents=70_000,
        total_credits=30,
        term_length_weeks=12,
    )
    s.draft_agreement(
        negotiated_discount_pct=0.25,
        direct_bill_enabled=True,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    s.activate_agreement()
    s.curate_listing()
    return s


def build_beacon_ten_credit_paid(api: TuitionBenefitApiClient) -> Scenario:
    """A ten-credit term whose 525,000-cent invoice is paid: the year's whole
    exclusion headroom consumed by one disbursement."""
    s = build_beacon_base(api)
    s.enroll(
        term_code="2026-FA",
        term_start_date="2026-09-01",
        term_end_date="2026-11-30",
        credits=10,
    )
    s.confirm_registration()
    s.first_invoice()
    s.approve_invoice()
    s.pay_invoice()
    s.first_enrollment_id = s.enrollment_id
    s.first_invoice_id = s.invoice_id
    return s


def build_beacon_second_term_billed(api: TuitionBenefitApiClient) -> Scenario:
    """A second one-credit term billed at 52,500 with no exclusion headroom left."""
    s = build_beacon_ten_credit_paid(api)
    s.enroll(
        term_code="2026-WI",
        term_start_date="2026-12-01",
        term_end_date="2027-02-28",
        credits=1,
    )
    s.second_enrollment_id = s.enrollment_id
    s.confirm_registration()
    s.first_invoice()
    s.second_invoice_id = s.invoice_id
    s.approve_invoice()
    return s


def build_beacon_second_term_paid(api: TuitionBenefitApiClient) -> Scenario:
    """Both terms disbursed: 525,000 excluded then 52,500 wholly imputed."""
    s = build_beacon_second_term_billed(api)
    s.pay_invoice(s.second_invoice_id)
    return s


def build_beacon_first_term_failed(api: TuitionBenefitApiClient) -> Scenario:
    """The first, fully excluded term fails after both terms have settled."""
    s = build_beacon_second_term_paid(api)
    s.post_outcome(
        "2026-FA",
        CompletionStatus.FAILED,
        0,
        1.50,
        enrollment_id=s.first_enrollment_id,
    )
    return s


# ══════════════════════════════════════════════════════════════════════════
# Lakeshore Health Partners — reimbursement at 0.55, clock opening in January
# ══════════════════════════════════════════════════════════════════════════
def build_lakeshore_base(api: TuitionBenefitApiClient) -> Scenario:
    """A 40,000-cent list price discounted 20% into a 32,000-cent listing rate."""
    s = Scenario(api)
    s.set_clock("2026-01-05T00:00:00Z")
    s.onboard_employer(
        legal_name="Lakeshore Health Partners",
        benefit_admin_contact_email="benefits@lakeshore-health.example",
        fiscal_year_start_month=1,
    )
    s.draft_policy(
        effective_from="2026-01-01",
        effective_to="2027-01-01",
        min_tenure_months=6,
        min_weekly_hours=20,
        eligible_job_families=[JobFamily.CLINICAL],
        annual_cap_cents=800_000,
        funding_model=FundingModel.REIMBURSEMENT,
        reimbursement_pct=0.55,
        max_concurrent_credits=12,
        drop_window_days=10,
        service_commitment_months=12,
    )
    s.activate_policy()
    s.register_employee(
        full_name="Alina Serrano",
        work_email="alina.serrano@lakeshore-health.example",
        hire_date="2024-03-01",
        weekly_hours=36,
        job_family=JobFamily.CLINICAL,
    )
    s.register_school(
        legal_name="Puget Sound College",
        state_code="WA",
        contact_email="registrar@pugetsound.example",
    )
    s.publish_program(
        name="RN to BSN Completion",
        credential_type=CredentialType.BACHELOR,
        skill_track=SkillTrack.NURSING,
        list_tuition_per_credit_cents=40_000,
        total_credits=60,
        term_length_weeks=15,
    )
    s.draft_agreement(
        negotiated_discount_pct=0.20,
        direct_bill_enabled=False,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    s.activate_agreement()
    s.curate_listing()
    return s


def build_lakeshore_settled(api: TuitionBenefitApiClient) -> Scenario:
    """A five-credit spring term reimbursed at 104,000 with a 5,200-cent fee."""
    s = build_lakeshore_base(api)
    s.enroll(
        term_code="2026-SP",
        term_start_date="2026-01-12",
        term_end_date="2026-04-30",
        credits=5,
    )
    s.confirm_registration()
    s.set_clock("2026-05-05T00:00:00Z")
    s.post_outcome("2026-SP", CompletionStatus.PASSED, 5, 3.60)
    s.file_claim(160_000, "PSC-2026SP-ASERRANO-01")
    s.decide_claim(ClaimDecision.APPROVE)
    return s


def build_lakeshore_early_departure(api: TuitionBenefitApiClient) -> Scenario:
    """The learner resigns on 2026-09-01, four of twelve committed months served."""
    s = build_lakeshore_settled(api)
    s.set_clock("2026-09-01T00:00:00Z")
    get_success_data(
        s.api.patch_employee(
            s.employee_id,
            {"employment_status": "TERMINATED", "termination_date": "2026-09-01"},
            s.benefit_admin,
        )
    )
    s.first_obligation()
    return s


# ══════════════════════════════════════════════════════════════════════════
# Ridgeline Aerospace Systems — hybrid policy, 30,000-cent listing rate
# ══════════════════════════════════════════════════════════════════════════
def build_ridgeline_base(api: TuitionBenefitApiClient) -> Scenario:
    """A 40,000-cent list price discounted 25% into a 30,000-cent listing rate."""
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.onboard_employer(
        legal_name="Ridgeline Aerospace Systems",
        benefit_admin_contact_email="benefits@ridgeline-aero.example",
        fiscal_year_start_month=1,
    )
    s.draft_policy(
        effective_from="2026-01-01",
        effective_to="2028-01-01",
        min_tenure_months=6,
        min_weekly_hours=20,
        eligible_job_families=[JobFamily.ENGINEERING],
        annual_cap_cents=2_000_000,
        funding_model=FundingModel.HYBRID,
        reimbursement_pct=0.50,
        max_concurrent_credits=20,
        drop_window_days=7,
        service_commitment_months=12,
    )
    s.activate_policy()
    s.register_employee(
        full_name="Tomas Weller",
        work_email="tomas.weller@ridgeline-aero.example",
        hire_date="2024-05-01",
        weekly_hours=40,
        job_family=JobFamily.ENGINEERING,
    )
    s.register_school(
        legal_name="Front Range Community College",
        state_code="CO",
        contact_email="registrar@frontrange.example",
    )
    s.publish_program(
        name="Certificate in Industrial Cybersecurity",
        credential_type=CredentialType.CERTIFICATE,
        skill_track=SkillTrack.CYBERSECURITY,
        list_tuition_per_credit_cents=40_000,
        total_credits=16,
        term_length_weeks=12,
    )
    s.draft_agreement(
        negotiated_discount_pct=0.25,
        direct_bill_enabled=True,
        effective_from="2026-01-01",
        effective_to="2027-12-31",
    )
    s.activate_agreement()
    s.curate_listing()
    return s


def build_ridgeline_direct_bill_paid(api: TuitionBenefitApiClient) -> Scenario:
    """A four-credit direct-bill term whose 120,000-cent invoice is already paid."""
    s = build_ridgeline_base(api)
    s.enroll(
        term_code="2026-FA",
        term_start_date="2026-09-01",
        term_end_date="2026-12-15",
        credits=4,
        funding_model=FundingModel.DIRECT_BILL,
    )
    s.first_enrollment_id = s.enrollment_id
    s.confirm_registration()
    s.first_invoice()
    s.first_invoice_id = s.invoice_id
    s.approve_invoice()
    s.pay_invoice()
    return s


def build_northwind_exception_program(api: TuitionBenefitApiClient) -> Scenario:
    """The Northwind catalog plus one uncurated master's programme at the same school."""
    s = build_northwind_base(api)
    second = s.publish_program(
        primary=False,
        name="MS Business Analytics",
        credential_type=CredentialType.MASTER,
        skill_track=SkillTrack.BUSINESS_ADMIN,
        list_tuition_per_credit_cents=90_000,
        total_credits=30,
        term_length_weeks=14,
    )
    s.second_program_id = second["id"]
    return s


def build_northwind_revision_cycle(api: TuitionBenefitApiClient) -> Scenario:
    """A non-catalog request driven twice around the revision cycle."""
    s = build_northwind_exception_program(api)
    s.open_approval_request(
        program_id=s.second_program_id,
        justification="Analytics degree needed for the demand-planning ladder.",
        requested_annual_cost_cents=540_000,
    )
    s.review_request()
    s.decide_request(ApprovalDecision.REQUEST_CHANGES, "Add the manager endorsement.")
    get_success_data(
        s.api.resubmit_program_approval_request(
            s.request_id,
            resubmit_payload(
                justification="Manager endorsement attached; ladder plan revised."
            ),
            s.employee,
        )
    )
    s.review_request()
    s.decide_request(
        ApprovalDecision.REQUEST_CHANGES,
        "Cost estimate still exceeds the annual cap.",
    )
    get_success_data(
        s.api.resubmit_program_approval_request(
            s.request_id,
            resubmit_payload(requested_annual_cost_cents=480_000),
            s.employee,
        )
    )
    s.review_request()
    s.decide_request(
        ApprovalDecision.REQUEST_CHANGES, "Third pass: cost still not funded."
    )
    return s


# ══════════════════════════════════════════════════════════════════════════
# Summit Logistics Cooperative — one agreement, three listings, two fee tiers
# ══════════════════════════════════════════════════════════════════════════
def build_summit_base(api: TuitionBenefitApiClient) -> Scenario:
    """Three programmes at 499,000, 32,802 and 40,000 cents per credit."""
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.onboard_employer(
        legal_name="Summit Logistics Cooperative",
        benefit_admin_contact_email="benefits@summit-logistics.example",
        fiscal_year_start_month=1,
    )
    s.draft_policy(
        effective_from="2026-01-01",
        effective_to="2028-01-01",
        min_tenure_months=0,
        min_weekly_hours=0,
        eligible_job_families=[JobFamily.OPERATIONS],
        annual_cap_cents=6_000_000,
        funding_model=FundingModel.HYBRID,
        reimbursement_pct=0.60,
        max_concurrent_credits=24,
        drop_window_days=7,
        service_commitment_months=12,
    )
    s.activate_policy()
    s.register_employee(
        full_name="Marcus Vela",
        work_email="marcus.vela@summit-logistics.example",
        hire_date="2024-02-01",
        weekly_hours=40,
        job_family=JobFamily.OPERATIONS,
    )
    s.register_school(
        legal_name="Gateway Polytechnic",
        state_code="IL",
        contact_email="partners@gateway-poly.example",
    )
    s.publish_program(
        name="MS Operations Research",
        credential_type=CredentialType.MASTER,
        skill_track=SkillTrack.SUPPLY_CHAIN,
        list_tuition_per_credit_cents=623_750,
        total_credits=30,
        term_length_weeks=14,
    )
    s.second_program_id = s.publish_program(
        primary=False,
        name="BS Supply Chain Management",
        credential_type=CredentialType.BACHELOR,
        skill_track=SkillTrack.SUPPLY_CHAIN,
        list_tuition_per_credit_cents=41_002,
        total_credits=120,
        term_length_weeks=15,
    )["id"]
    s.third_program_id = s.publish_program(
        primary=False,
        name="Certificate in Warehouse Automation",
        credential_type=CredentialType.CERTIFICATE,
        skill_track=SkillTrack.SUPPLY_CHAIN,
        list_tuition_per_credit_cents=50_000,
        total_credits=12,
        term_length_weeks=10,
    )["id"]
    s.draft_agreement(
        negotiated_discount_pct=0.20,
        direct_bill_enabled=True,
        effective_from="2026-01-01",
        effective_to="2027-12-31",
    )
    s.activate_agreement()
    s.curate_listing()
    s.second_listing_id = s.curate_listing(
        primary=False, program_id=s.second_program_id
    )["id"]
    s.third_listing_id = s.curate_listing(
        primary=False, program_id=s.third_program_id
    )["id"]
    return s


def build_summit_direct_bill_paid(api: TuitionBenefitApiClient) -> Scenario:
    """A ten-credit direct-bill term paid at 4,990,000 cents — just inside tier 1."""
    s = build_summit_base(api)
    s.enroll(
        term_code="2026-FA",
        term_start_date="2026-09-01",
        term_end_date="2026-12-10",
        credits=10,
        funding_model=FundingModel.DIRECT_BILL,
    )
    s.first_enrollment_id = s.enrollment_id
    s.confirm_registration()
    s.first_invoice()
    s.first_invoice_id = s.invoice_id
    s.approve_invoice()
    s.pay_invoice()
    return s


def build_summit_second_claim_filed(api: TuitionBenefitApiClient) -> Scenario:
    """A three-credit reimbursement term passed at 3.80 with its claim on file."""
    s = build_summit_direct_bill_paid(api)
    s.enroll(
        listing_id=s.second_listing_id,
        term_code="2026-WI",
        term_start_date="2026-12-15",
        term_end_date="2027-03-20",
        credits=3,
        funding_model=FundingModel.REIMBURSEMENT,
    )
    s.second_enrollment_id = s.enrollment_id
    s.confirm_registration()
    s.set_clock("2027-03-25T00:00:00Z")
    s.post_outcome("2026-WI", CompletionStatus.PASSED, 3, 3.80)
    s.file_claim(98_406, "GP-2026WI-MVELA-01")
    return s


def build_summit_third_claim_filed(api: TuitionBenefitApiClient) -> Scenario:
    """The second settlement is booked and a third, two-credit claim awaits decision."""
    s = build_summit_second_claim_filed(api)
    s.decide_claim(ClaimDecision.APPROVE)
    s.second_claim_id = s.claim_id
    s.enroll(
        listing_id=s.third_listing_id,
        term_code="2027-SP",
        term_start_date="2027-04-01",
        term_end_date="2027-06-10",
        credits=2,
        funding_model=FundingModel.REIMBURSEMENT,
    )
    s.third_enrollment_id = s.enrollment_id
    s.confirm_registration()
    s.set_clock("2027-06-15T00:00:00Z")
    s.post_outcome("2027-SP", CompletionStatus.PASSED, 2, 3.00)
    s.file_claim(80_000, "GP-2027SP-MVELA-01")
    return s


# ══════════════════════════════════════════════════════════════════════════
# Harborview Municipal Services — a 120,000-cent cap exhausted by one term
# ══════════════════════════════════════════════════════════════════════════
def build_harborview_cap_exhausted(api: TuitionBenefitApiClient) -> Scenario:
    """Two curated listings at 30,000 per credit; four credits eat the whole pool."""
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.onboard_employer(
        legal_name="Harborview Municipal Services",
        benefit_admin_contact_email="benefits@harborview-muni.example",
        fiscal_year_start_month=1,
    )
    s.draft_policy(
        effective_from="2026-01-01",
        effective_to="2027-01-01",
        min_tenure_months=0,
        min_weekly_hours=0,
        eligible_job_families=[JobFamily.CORPORATE],
        annual_cap_cents=120_000,
        funding_model=FundingModel.DIRECT_BILL,
        reimbursement_pct=1.00,
        max_concurrent_credits=30,
        drop_window_days=7,
        service_commitment_months=12,
    )
    s.activate_policy()
    s.register_employee(
        full_name="Grace Lindqvist",
        work_email="grace.lindqvist@harborview-muni.example",
        hire_date="2025-06-01",
        weekly_hours=40,
        job_family=JobFamily.CORPORATE,
    )
    s.register_school(
        legal_name="Tidewater State College",
        state_code="VA",
        contact_email="partners@tidewater-state.example",
    )
    s.publish_program(
        name="Certificate in Public Administration",
        credential_type=CredentialType.CERTIFICATE,
        skill_track=SkillTrack.BUSINESS_ADMIN,
        list_tuition_per_credit_cents=40_000,
        total_credits=12,
        term_length_weeks=10,
    )
    s.second_program_id = s.publish_program(
        primary=False,
        name="Certificate in Civic Data Analytics",
        credential_type=CredentialType.CERTIFICATE,
        skill_track=SkillTrack.DATA_ANALYTICS,
        list_tuition_per_credit_cents=40_000,
        total_credits=12,
        term_length_weeks=10,
    )["id"]
    s.draft_agreement(
        negotiated_discount_pct=0.25,
        direct_bill_enabled=True,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    s.activate_agreement()
    s.curate_listing()
    s.second_listing_id = s.curate_listing(
        primary=False, program_id=s.second_program_id
    )["id"]
    s.enroll(
        term_code="2026-FA",
        term_start_date="2026-09-01",
        term_end_date="2026-12-15",
        credits=4,
    )
    s.first_enrollment_id = s.enrollment_id
    return s


# ══════════════════════════════════════════════════════════════════════════
# Cobalt Grocers Alliance — adjacent policy windows raising the tenure floor
# ══════════════════════════════════════════════════════════════════════════
def build_cobalt_successor_policy(api: TuitionBenefitApiClient) -> Scenario:
    """A six-credit term under P1, then a stricter P2 governing from 2026-09-01."""
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.onboard_employer(
        legal_name="Cobalt Grocers Alliance",
        benefit_admin_contact_email="benefits@cobalt-grocers.example",
        fiscal_year_start_month=1,
    )
    s.draft_policy(
        effective_from="2026-07-01",
        effective_to="2026-09-01",
        min_tenure_months=6,
        min_weekly_hours=20,
        eligible_job_families=[JobFamily.RETAIL_FRONTLINE, JobFamily.OPERATIONS],
        annual_cap_cents=2_000_000,
        funding_model=FundingModel.REIMBURSEMENT,
        reimbursement_pct=0.60,
        max_concurrent_credits=9,
        drop_window_days=14,
        service_commitment_months=12,
    )
    s.activate_policy()
    s.register_employee(
        full_name="Dana Okafor",
        work_email="dana.okafor@cobalt-grocers.example",
        hire_date="2025-01-15",
        weekly_hours=32,
        job_family=JobFamily.RETAIL_FRONTLINE,
    )
    s.register_school(
        legal_name="Cascade State University",
        state_code="WA",
        contact_email="registrar@cascadestate.example",
    )
    s.publish_program(
        name="BS Supply Chain Management",
        credential_type=CredentialType.BACHELOR,
        skill_track=SkillTrack.SUPPLY_CHAIN,
        list_tuition_per_credit_cents=41_002,
        total_credits=120,
        term_length_weeks=15,
    )
    s.draft_agreement(
        negotiated_discount_pct=0.25,
        direct_bill_enabled=True,
        effective_from="2026-07-01",
        effective_to="2027-06-30",
    )
    s.activate_agreement()
    s.curate_listing()
    s.enroll(
        term_code="2026-FA",
        term_start_date="2026-09-01",
        term_end_date="2026-12-15",
        credits=6,
    )
    s.first_enrollment_id = s.enrollment_id
    s.second_policy_id = s.draft_policy(
        primary=False,
        effective_from="2026-09-01",
        effective_to="2027-09-01",
        min_tenure_months=36,
        min_weekly_hours=20,
        eligible_job_families=[JobFamily.RETAIL_FRONTLINE, JobFamily.OPERATIONS],
        annual_cap_cents=2_000_000,
        funding_model=FundingModel.REIMBURSEMENT,
        reimbursement_pct=0.60,
        max_concurrent_credits=9,
        drop_window_days=14,
        service_commitment_months=12,
    )["id"]
    s.activate_policy(s.second_policy_id)
    s.set_clock("2026-09-05T00:00:00Z")
    return s


# ══════════════════════════════════════════════════════════════════════════
# Meridian Freight Lines — a curation gated purely by the agreement lifecycle
# ══════════════════════════════════════════════════════════════════════════
def build_meridian_pending_agreement(api: TuitionBenefitApiClient) -> Scenario:
    """Two programmes at one school behind an agreement still sitting in PENDING."""
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.onboard_employer(
        legal_name="Meridian Freight Lines",
        benefit_admin_contact_email="benefits@meridian-freight.example",
        fiscal_year_start_month=1,
    )
    s.register_school(
        legal_name="Great Lakes Institute",
        state_code="MI",
        contact_email="partners@greatlakes-inst.example",
    )
    s.publish_program(
        name="Associate of Logistics Technology",
        credential_type=CredentialType.ASSOCIATE,
        skill_track=SkillTrack.SUPPLY_CHAIN,
        list_tuition_per_credit_cents=36_000,
        total_credits=60,
        term_length_weeks=15,
    )
    s.second_program_id = s.publish_program(
        primary=False,
        name="Certificate in Fleet Data Systems",
        credential_type=CredentialType.CERTIFICATE,
        skill_track=SkillTrack.DATA_ANALYTICS,
        list_tuition_per_credit_cents=36_000,
        total_credits=12,
        term_length_weeks=10,
    )["id"]
    s.draft_agreement(
        negotiated_discount_pct=0.25,
        direct_bill_enabled=True,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    return s
