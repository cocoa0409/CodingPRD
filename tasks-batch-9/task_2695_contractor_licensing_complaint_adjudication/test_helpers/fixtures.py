"""Composite setup helpers.

The harness restarts the API server before every individual test, so each test
begins against an empty database. Everything a test needs is therefore built
here from scratch through the endpoints the PRD declares — no direct database
access and no shared state between tests.

The helpers are layered:

* tier 1 - reference data (clock, trade classifications, the fund appropriation)
* tier 2 - parties (licensees, qualifying individuals with current exams, consumers)
* tier 3 - a licence minted by approving an application
* tier 4 - coverage, designations, complaints
* tier 5 - enforcement and recovery-fund chains built on the tiers above
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import constants as K
from . import factories as F
from .api_client import ApiClient
from .test_users import (
    BOARD_ADMIN_HEADERS,
    FUND_ADJUDICATOR_HEADERS,
    HEARING_OFFICER_USER_ID,
    INVESTIGATOR_USER_ID,
    LICENSING_ANALYST_HEADERS,
    make_consumer_headers,
    make_hearing_officer_headers,
    make_investigator_headers,
    make_licensee_headers,
)
from .types import (
    ApplicationDecision,
    ClaimDecision,
    CoverageType,
    EducationCredential,
    ExamType,
    HearingDecision,
    InvestigationFinding,
    InvestigationOrigin,
    JurisdictionFinding,
    MediationOutcome,
    Severity,
    VerificationOutcome,
)

Json = dict[str, Any]


# =============================================================================
# tier 1 - reference data
# =============================================================================
def set_clock(api: ApiClient, current_utc: str) -> None:
    """Moves the logical clock; every later stamp is read from it."""
    validate_success(api.set_clock(current_utc, BOARD_ADMIN_HEADERS))


def create_classification(api: ApiClient, spec: Json, **overrides: Any) -> Json:
    payload = dict(spec)
    payload.update(overrides)
    return get_success_data(api.create_trade_classification(payload, BOARD_ADMIN_HEADERS))


def create_c10_classification(api: ApiClient, **overrides: Any) -> Json:
    """Tier-3 electrical trade; an accepted complaint is routed to mediation."""
    return create_classification(api, K.C10, **overrides)


def create_c20_classification(api: ApiClient, **overrides: Any) -> Json:
    """Tier-2 trade whose accepted complaints go straight to investigation."""
    return create_classification(api, K.C20, **overrides)


def create_c30_classification(api: ApiClient, **overrides: Any) -> Json:
    """Tier-3 trade whose accepted complaints go straight to investigation."""
    return create_classification(api, K.C30, **overrides)


def open_fund_account(api: ApiClient, **overrides: Any) -> Json:
    return get_success_data(
        api.create_fund_account(F.fund_account_payload(**overrides), BOARD_ADMIN_HEADERS)
    )


def read_fund_account(api: ApiClient, fund_account_id: str) -> Json:
    return validate_success(api.get_fund_account(fund_account_id, FUND_ADJUDICATOR_HEADERS))


# =============================================================================
# tier 2 - parties
# =============================================================================
def register_licensee(api: ApiClient, **overrides: Any) -> Json:
    return get_success_data(
        api.create_licensee(F.licensee_payload(**overrides), LICENSING_ANALYST_HEADERS)
    )


def register_qualifying_individual(api: ApiClient, **overrides: Any) -> Json:
    return get_success_data(
        api.create_qualifying_individual(
            F.qualifying_individual_payload(**overrides), LICENSING_ANALYST_HEADERS
        )
    )


def record_exam(
    api: ApiClient, individual_id: str, exam_type: str, **overrides: Any
) -> Json:
    payload = F.exam_result_payload(exam_type, **overrides)
    return get_success_data(
        api.create_exam_result(individual_id, payload, LICENSING_ANALYST_HEADERS)
    )


def register_exam_qualified_individual(
    api: ApiClient,
    trade_code: str,
    verified_experience_months: int = 60,
    taken_on: str = "2025-03-01",
    law_score: int = 82,
    trade_score: int = 78,
    **overrides: Any,
) -> Json:
    """A qualifying individual holding a current pass in both statutory exams."""
    individual = register_qualifying_individual(
        api, verified_experience_months=verified_experience_months, **overrides
    )
    record_exam(
        api,
        individual["id"],
        ExamType.LAW_AND_BUSINESS,
        score=law_score,
        taken_on=taken_on,
    )
    record_exam(
        api,
        individual["id"],
        ExamType.TRADE,
        trade_code=trade_code,
        score=trade_score,
        taken_on=taken_on,
    )
    return individual


def register_consumer(api: ApiClient, **overrides: Any) -> Json:
    return get_success_data(
        api.create_consumer(F.consumer_payload(**overrides), LICENSING_ANALYST_HEADERS)
    )


# =============================================================================
# tier 3 - a licence minted through the application pipeline
# =============================================================================
@dataclass
class LicenseContext:
    """Everything the approval cascade produced, plus the actors that own it."""

    classification: Json
    licensee: Json
    individual: Json
    application: Json
    license: Json
    assignment: Optional[Json] = None
    extras: Json = field(default_factory=dict)

    @property
    def classification_id(self) -> str:
        return self.classification["id"]

    @property
    def licensee_id(self) -> str:
        return self.licensee["id"]

    @property
    def individual_id(self) -> str:
        return self.individual["id"]

    @property
    def application_id(self) -> str:
        return self.application["id"]

    @property
    def license_id(self) -> str:
        return self.license["id"]

    @property
    def licensee_headers(self) -> dict[str, str]:
        return make_licensee_headers(self.licensee["id"])


def open_application(
    api: ApiClient,
    licensee_id: str,
    classification_id: str,
    individual_id: str,
    **overrides: Any,
) -> Json:
    payload = F.application_payload(
        licensee_id, classification_id, individual_id, **overrides
    )
    return get_success_data(
        api.create_application(payload, make_licensee_headers(licensee_id))
    )


def find_license_for_application(api: ApiClient, application_id: str) -> Json:
    """The approval cascade mints the licence; it is reached by its application."""
    response = api.list_licenses(
        LICENSING_ANALYST_HEADERS, {"application_id": application_id}
    )
    rows = get_success_data(response)
    assert rows, f"no licence was minted for application {application_id}"
    return rows[0]


def find_assignment_for_license(api: ApiClient, license_id: str) -> Optional[Json]:
    rows = get_success_data(
        api.list_qualifier_assignments(
            LICENSING_ANALYST_HEADERS, {"license_id": license_id}
        )
    )
    return rows[0] if rows else None


def mint_active_license(
    api: ApiClient,
    classification: Optional[Json] = None,
    *,
    legal_name: str = "Volt Works LLC",
    contact_email: str = "ops@voltworks.test",
    full_name: str = "Dana Volt",
    verified_experience_months: int = 24,
    education_credential: str = EducationCredential.FOUR_YEAR_DEGREE,
    declared_net_worth_cents: int = 250000,
    individual: Optional[Json] = None,
    taken_on: str = "2025-03-01",
) -> LicenseContext:
    """Registers the parties, submits an application and approves it.

    Approval is the only way a licence comes into existence, so every licence
    used by the suite is minted through this pipeline.
    """
    cls = classification if classification is not None else create_c10_classification(api)
    licensee = register_licensee(
        api, legal_name=legal_name, contact_email=contact_email
    )
    qi = (
        individual
        if individual is not None
        else register_exam_qualified_individual(
            api,
            cls["code"],
            verified_experience_months=verified_experience_months,
            taken_on=taken_on,
            full_name=full_name,
        )
    )
    application = open_application(
        api,
        licensee["id"],
        cls["id"],
        qi["id"],
        declared_net_worth_cents=declared_net_worth_cents,
        education_credential=education_credential,
    )
    licensee_headers = make_licensee_headers(licensee["id"])
    validate_success(api.submit_application(application["id"], licensee_headers))
    validate_success(
        api.decide_application(
            application["id"],
            F.decision_payload(ApplicationDecision.APPROVED),
            LICENSING_ANALYST_HEADERS,
        )
    )
    license_row = find_license_for_application(api, application["id"])
    return LicenseContext(
        classification=cls,
        licensee=licensee,
        individual=qi,
        application=application,
        license=license_row,
        assignment=find_assignment_for_license(api, license_row["id"]),
    )


def read_license(api: ApiClient, license_id: str) -> Json:
    return validate_success(api.get_license(license_id, LICENSING_ANALYST_HEADERS))


# =============================================================================
# tier 4 - coverage, designations and complaints
# =============================================================================
def file_coverage(api: ApiClient, license_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_coverage_record(
            F.coverage_record_payload(license_id, **overrides), LICENSING_ANALYST_HEADERS
        )
    )


def verify_coverage(api: ApiClient, coverage_id: str) -> Json:
    return validate_success(
        api.verify_coverage_record(
            coverage_id,
            F.verification_payload(VerificationOutcome.VERIFY),
            LICENSING_ANALYST_HEADERS,
        )
    )


def verify_bond(
    api: ApiClient,
    license_id: str,
    amount_cents: int = K.C10["required_bond_amount_cents"],
    effective_date: str = "2026-08-01",
    expiration_date: str = "2027-08-01",
    **overrides: Any,
) -> Json:
    """Files a conforming bond and confirms it with the carrier."""
    record = file_coverage(
        api,
        license_id,
        coverage_type=CoverageType.BOND,
        amount_cents=amount_cents,
        effective_date=effective_date,
        expiration_date=expiration_date,
        **overrides,
    )
    return verify_coverage(api, record["id"])


def verify_general_liability(
    api: ApiClient,
    license_id: str,
    amount_cents: int = 100000,
    effective_date: str = "2026-08-01",
    expiration_date: str = "2027-08-01",
    **overrides: Any,
) -> Json:
    record = get_success_data(
        api.create_coverage_record(
            F.general_liability_payload(
                license_id,
                amount_cents=amount_cents,
                effective_date=effective_date,
                expiration_date=expiration_date,
                **overrides,
            ),
            LICENSING_ANALYST_HEADERS,
        )
    )
    return verify_coverage(api, record["id"])


def designate_qualifier(
    api: ApiClient,
    license_id: str,
    individual_id: str,
    expected_license_version: int,
    **overrides: Any,
):
    """Returns the raw response so a test can assert either outcome."""
    return api.create_qualifier_assignment(
        F.qualifier_assignment_payload(
            license_id, individual_id, expected_license_version, **overrides
        ),
        LICENSING_ANALYST_HEADERS,
    )


def file_complaint(
    api: ApiClient, consumer_id: str, license_id: str, **overrides: Any
) -> Json:
    return get_success_data(
        api.create_complaint(
            F.complaint_payload(consumer_id, license_id=license_id, **overrides),
            make_consumer_headers(consumer_id),
        )
    )


def file_unlicensed_complaint(
    api: ApiClient, consumer_id: str, subject_business_name: str, **overrides: Any
) -> Json:
    return get_success_data(
        api.create_complaint(
            F.unlicensed_complaint_payload(
                consumer_id, subject_business_name, **overrides
            ),
            make_consumer_headers(consumer_id),
        )
    )


def screen_accepted(api: ApiClient, complaint_id: str) -> Json:
    return validate_success(
        api.screen_complaint(
            complaint_id,
            F.screening_payload(JurisdictionFinding.ACCEPTED),
            LICENSING_ANALYST_HEADERS,
        )
    )


def fail_mediation(
    api: ApiClient, complaint_id: str, settlement_amount_cents: Optional[int] = None
) -> Json:
    payload = F.mediation_outcome_payload(MediationOutcome.FAILED)
    if settlement_amount_cents is not None:
        payload["settlement_amount_cents"] = settlement_amount_cents
    return validate_success(
        api.record_mediation_outcome(complaint_id, payload, LICENSING_ANALYST_HEADERS)
    )


def complaint_in_investigation(
    api: ApiClient, consumer_id: str, license_id: str, **overrides: Any
) -> Json:
    """Files a complaint and drives it as far as investigation.

    A classification that requires mediation stops at mediation on screening, so
    the mediation attempt is failed out; one that does not is already there.
    """
    complaint = file_complaint(api, consumer_id, license_id, **overrides)
    screened = screen_accepted(api, complaint["id"])
    if screened["status"] == "MEDIATION":
        screened = fail_mediation(api, complaint["id"])
    return screened


# =============================================================================
# tier 5 - enforcement and recovery-fund chains
# =============================================================================
def open_investigation(
    api: ApiClient,
    *,
    complaint_id: Optional[str] = None,
    subject_license_id: Optional[str] = None,
    subject_business_name: Optional[str] = None,
    origin: str = InvestigationOrigin.COMPLAINT,
    investigator_user_id: str = INVESTIGATOR_USER_ID,
) -> Json:
    payload: Json = {"origin": origin}
    if complaint_id is not None:
        payload["complaint_id"] = complaint_id
    if subject_license_id is not None:
        payload["subject_license_id"] = subject_license_id
    if subject_business_name is not None:
        payload["subject_business_name"] = subject_business_name
    return get_success_data(
        api.create_investigation(
            payload, make_investigator_headers(investigator_user_id)
        )
    )


def substantiate(
    api: ApiClient,
    investigation_id: str,
    severity: str = Severity.SERIOUS,
    evidence_summary: str = "Unpermitted service change confirmed on site",
    investigator_user_id: str = INVESTIGATOR_USER_ID,
) -> Json:
    return validate_success(
        api.close_investigation(
            investigation_id,
            F.close_investigation_payload(
                InvestigationFinding.SUBSTANTIATED,
                finding_severity=severity,
                evidence_summary=evidence_summary,
            ),
            make_investigator_headers(investigator_user_id),
        )
    )


def issue_citation(
    api: ApiClient,
    investigation_id: str,
    classification_id: str,
    investigator_user_id: str = INVESTIGATOR_USER_ID,
    **overrides: Any,
) -> Json:
    return get_success_data(
        api.create_citation(
            F.citation_payload(investigation_id, classification_id, **overrides),
            make_investigator_headers(investigator_user_id),
        )
    )


def substantiated_citation(
    api: ApiClient,
    ctx: LicenseContext,
    consumer_id: str,
    *,
    severity: str = Severity.SERIOUS,
    violation_code: str = "B-7109",
    correction_due_date: str = "2026-09-30",
    alleged_loss_cents: int = 800000,
    contract_date: str = "2026-08-10",
    work_completed_on: str = "2026-08-20",
    investigator_user_id: str = INVESTIGATOR_USER_ID,
) -> tuple[Json, Json, Json]:
    """Complaint -> investigation -> substantiated finding -> citation."""
    complaint = complaint_in_investigation(
        api,
        consumer_id,
        ctx.license_id,
        alleged_loss_cents=alleged_loss_cents,
        contract_date=contract_date,
        work_completed_on=work_completed_on,
    )
    investigation = open_investigation(
        api,
        complaint_id=complaint["id"],
        subject_license_id=ctx.license_id,
        investigator_user_id=investigator_user_id,
    )
    substantiate(
        api,
        investigation["id"],
        severity=severity,
        investigator_user_id=investigator_user_id,
    )
    citation = issue_citation(
        api,
        investigation["id"],
        ctx.classification_id,
        investigator_user_id=investigator_user_id,
        violation_code=violation_code,
        correction_due_date=correction_due_date,
    )
    return complaint, investigation, citation


def appeal_citation(api: ApiClient, citation_id: str, licensee_id: str) -> Json:
    return validate_success(
        api.appeal_citation(
            citation_id, F.appeal_payload(), make_licensee_headers(licensee_id)
        )
    )


def calendar_hearing(
    api: ApiClient,
    citation_id: str,
    scheduled_start_utc: str,
    scheduled_end_utc: str,
    presiding_officer_user_id: str = HEARING_OFFICER_USER_ID,
) -> Json:
    return get_success_data(
        api.create_hearing(
            F.hearing_payload(
                citation_id,
                presiding_officer_user_id,
                scheduled_start_utc,
                scheduled_end_utc,
            ),
            BOARD_ADMIN_HEADERS,
        )
    )


def appealed_citation_with_hearing(
    api: ApiClient,
    citation_id: str,
    licensee_id: str,
    scheduled_start_utc: str,
    scheduled_end_utc: str,
    presiding_officer_user_id: str = HEARING_OFFICER_USER_ID,
) -> Json:
    appeal_citation(api, citation_id, licensee_id)
    return calendar_hearing(
        api,
        citation_id,
        scheduled_start_utc,
        scheduled_end_utc,
        presiding_officer_user_id,
    )


def decide_hearing(
    api: ApiClient,
    hearing_id: str,
    decision: str = HearingDecision.AFFIRM,
    presiding_officer_user_id: str = HEARING_OFFICER_USER_ID,
    **overrides: Any,
) -> Json:
    return validate_success(
        api.decide_hearing(
            hearing_id,
            F.hearing_decision_payload(decision, **overrides),
            make_hearing_officer_headers(presiding_officer_user_id),
        )
    )


def file_judgment_claim(
    api: ApiClient,
    fund_account_id: str,
    complaint_id: str,
    consumer_id: str,
    claimed_amount_cents: int,
    judgment_amount_cents: int,
    judgment_docket_number: str,
    judgment_entered_on: str,
) -> Json:
    return get_success_data(
        api.create_claim(
            F.judgment_claim_payload(
                fund_account_id,
                complaint_id,
                claimed_amount_cents,
                judgment_amount_cents,
                judgment_docket_number,
                judgment_entered_on,
            ),
            make_consumer_headers(consumer_id),
        )
    )


def approve_claim(api: ApiClient, claim_id: str) -> Json:
    return validate_success(
        api.adjudicate_claim(
            claim_id,
            F.adjudication_payload(ClaimDecision.APPROVE),
            FUND_ADJUDICATOR_HEADERS,
        )
    )


def pay_claim(api: ApiClient, claim_id: str, fund_account_id: str) -> Json:
    """Disburses using the fund account's current version as the OCC token."""
    account = read_fund_account(api, fund_account_id)
    return validate_success(
        api.pay_claim(
            claim_id, F.payment_payload(account["version"]), FUND_ADJUDICATOR_HEADERS
        )
    )


def approved_court_judgment_claim(
    api: ApiClient,
    ctx: LicenseContext,
    fund_account: Json,
    consumer: Json,
    *,
    alleged_loss_cents: int = 1000000,
    claimed_amount_cents: int = 900000,
    judgment_amount_cents: int = 1000000,
    judgment_docket_number: str = "CV-2026-310",
    judgment_entered_on: str = "2026-09-05",
    contract_date: str = "2026-08-10",
    work_completed_on: str = "2026-08-20",
    adjudication_clock: str = "2026-12-04T00:00:00Z",
) -> tuple[Json, Json]:
    """A screened complaint carrying a ripe judgment claim, already approved."""
    complaint = file_complaint(
        api,
        consumer["id"],
        ctx.license_id,
        alleged_loss_cents=alleged_loss_cents,
        contract_date=contract_date,
        work_completed_on=work_completed_on,
    )
    screen_accepted(api, complaint["id"])
    claim = file_judgment_claim(
        api,
        fund_account["id"],
        complaint["id"],
        consumer["id"],
        claimed_amount_cents,
        judgment_amount_cents,
        judgment_docket_number,
        judgment_entered_on,
    )
    set_clock(api, adjudication_clock)
    approved = approve_claim(api, claim["id"])
    return complaint, approved


def bank_ce_hours(
    api: ApiClient, ctx: LicenseContext, ce_hours: float, completed_on: str
) -> Json:
    return validate_success(
        api.bank_ce_credits(
            ctx.license_id,
            F.ce_credit_payload(ce_hours, completed_on),
            ctx.licensee_headers,
        )
    )
