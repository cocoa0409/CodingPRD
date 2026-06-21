"""Composite setup helpers for multi-step test prerequisites.

Each fixture builds preconditions from an EMPTY database — the runner restarts
the API server (via start.sh) before every individual pytest test, so nothing
carries over between tests. All setup helpers use get_success_data() (lenient
validator) so setup-step failures surface as clear "Setup failed" messages
rather than confusing assertion failures.

Identity threading (PRD §2.1): the Applicant role is entity_backed — its
X-User-ID equals the acting Applicant.id. Every ownership-gated call as
Applicant in a fixture below uses make_applicant_headers(applicant_id), never
the shared TEST_USERS fallback.
"""
from typing import Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_jurisdiction_payload,
    create_applicant_payload,
    create_application_payload,
    create_consent_payload,
    create_order_payload,
    create_verification_payload,
    report_verification_payload,
    dispute_verification_payload,
    resolve_verification_payload,
)
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_recruiter_headers,
    make_compliance_officer_headers,
)


# ─── Convenience header aliases ────────────────────────────────────────

PA = TEST_USERS["platform_admin_headers"]
REC = TEST_USERS["recruiter_headers"]
REC_B = TEST_USERS["recruiter_b_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CO_B = TEST_USERS["compliance_officer_b_headers"]
VP = TEST_USERS["verification_provider_headers"]


# ─── Tier 0: Clock + primitive helpers ─────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the SystemClock singleton (PRD §3.8). PlatformAdmin only."""
    return get_success_data(api_client.set_clock(to_iso8601, PA))


def create_jurisdiction(
    state_code: str,
    ban_the_box_enabled: Optional[bool] = None,
    salary_history_ban_enabled: Optional[bool] = None,
    pre_adverse_waiting_days: Optional[int] = None,
):
    """Create a Jurisdiction (PRD §3.1)."""
    return get_success_data(api_client.create_jurisdiction(
        create_jurisdiction_payload(
            state_code=state_code,
            ban_the_box_enabled=ban_the_box_enabled,
            salary_history_ban_enabled=salary_history_ban_enabled,
            pre_adverse_waiting_days=pre_adverse_waiting_days,
        ),
        PA,
    ))


def create_applicant(full_name="Test Applicant",
                     email="test@example.com",
                     date_of_birth="1990-01-01T00:00:00.000Z"):
    """Register an Applicant (PRD §3.1). Returns the Applicant dict."""
    return get_success_data(api_client.create_applicant(
        create_applicant_payload(full_name=full_name, email=email,
                                 date_of_birth=date_of_birth),
        TEST_USERS["applicant_headers"],
    ))


def create_application(applicant_id: str, jurisdiction_id: str,
                       position_title: str = "Engineer",
                       salary_history_disclosed=None):
    """Create an Application in DRAFT (PRD §3.1).
    The Applicant role threads applicant_id as X-User-ID (entity_backed)."""
    return get_success_data(api_client.create_application(
        create_application_payload(
            applicant_id=applicant_id,
            jurisdiction_id=jurisdiction_id,
            position_title=position_title,
            salary_history_disclosed=salary_history_disclosed,
        ),
        make_applicant_headers(applicant_id),
    ))


def create_consent(application_id: str, applicant_id: str,
                   signed_at="2026-06-01T10:00:00.000Z",
                   disclosure_text_version="v2024-01",
                   ip_address="1.2.3.4"):
    """Open a ConsentDisclosure in PENDING (PRD §3.2)."""
    return get_success_data(api_client.create_consent(
        create_consent_payload(
            application_id=application_id,
            disclosure_text_version=disclosure_text_version,
            signed_at=signed_at,
            ip_address=ip_address,
        ),
        make_applicant_headers(applicant_id),
    ))


def grant_consent(consent_id: str, expected_version: int, applicant_id: str):
    """Grant a PENDING consent (PRD §3.2)."""
    return get_success_data(api_client.grant_consent(
        consent_id,
        {"expected_consent_disclosure_version": expected_version},
        make_applicant_headers(applicant_id),
    ))


def submit_application(application_id: str, expected_version: int,
                       applicant_id: str):
    """Submit DRAFT -> SUBMITTED (PRD §3.2)."""
    return get_success_data(api_client.submit_application(
        application_id,
        {"expected_application_version": expected_version},
        make_applicant_headers(applicant_id),
    ))


def conditional_offer(application_id: str, expected_version: int,
                      recruiter_id: str = "rec-001"):
    """Recruiter extends conditional offer SUBMITTED -> CONDITIONAL_OFFER
    (PRD §3.3). recruiter_id is captured on the audit row used later by the
    segregation-of-duties check (PRD §2.7)."""
    return get_success_data(api_client.conditional_offer(
        application_id,
        {"expected_application_version": expected_version},
        make_recruiter_headers(recruiter_id),
    ))


def create_order(application_id: str, consent_id: str,
                 expected_application_version: int,
                 recruiter_id: str = "rec-001"):
    """Recruiter creates BackgroundCheckOrder (PRD §3.3)."""
    return get_success_data(api_client.create_order(
        create_order_payload(
            application_id=application_id,
            consent_id=consent_id,
            expected_application_version=expected_application_version,
        ),
        make_recruiter_headers(recruiter_id),
    ))


def create_verification(order_id: str, verification_type: str,
                        recruiter_id: str = "rec-001"):
    """Create one Verification (PRD §3.4)."""
    return get_success_data(api_client.create_verification(
        order_id,
        create_verification_payload(verification_type=verification_type),
        make_recruiter_headers(recruiter_id),
    ))


def report_verification(verification_id: str, result: str,
                        expected_version: int, report_payload=None):
    """Provider reports a verification (PRD §3.4)."""
    return get_success_data(api_client.report_verification(
        verification_id,
        report_verification_payload(
            result=result,
            expected_verification_version=expected_version,
            report_payload=report_payload,
        ),
        VP,
    ))


def dispute_verification(verification_id: str, dispute_reason: str,
                         expected_version: int, applicant_id: str):
    """Applicant disputes a REPORTED verification (PRD §3.5)."""
    return get_success_data(api_client.dispute_verification(
        verification_id,
        dispute_verification_payload(
            dispute_reason=dispute_reason,
            expected_verification_version=expected_version,
        ),
        make_applicant_headers(applicant_id),
    ))


def resolve_verification(verification_id: str, new_result: str,
                         expected_version: int):
    """Provider resolves a DISPUTED verification (PRD §3.5)."""
    return get_success_data(api_client.resolve_verification(
        verification_id,
        resolve_verification_payload(
            new_result=new_result,
            expected_verification_version=expected_version,
        ),
        VP,
    ))


# ─── Tier 1: Application progression ───────────────────────────────────

def create_applicant_and_application(
    state_code: str,
    ban_the_box_enabled: Optional[bool] = None,
    salary_history_ban_enabled: Optional[bool] = None,
    pre_adverse_waiting_days: Optional[int] = None,
    clock_iso: str = "2026-06-01T10:00:00.000Z",
    full_name: str = "Test Applicant",
    email_seed: str = "test",
    position_title: str = "Engineer",
    salary_history_disclosed=None,
) -> Tuple[dict, dict, dict]:
    """Bootstrap: set clock, create jurisdiction, applicant, and Application
    (DRAFT). Returns (jurisdiction, applicant, application).

    Each call uses a unique email so multiple bootstraps inside the same
    fixture do not collide on the unique-email constraint (PRD §3.1).
    """
    set_clock(clock_iso)
    jur = create_jurisdiction(
        state_code=state_code,
        ban_the_box_enabled=ban_the_box_enabled,
        salary_history_ban_enabled=salary_history_ban_enabled,
        pre_adverse_waiting_days=pre_adverse_waiting_days,
    )
    applicant = create_applicant(
        full_name=full_name,
        email=f"{email_seed}+{state_code.lower()}@example.com",
        date_of_birth="1990-01-01T00:00:00.000Z",
    )
    application = create_application(
        applicant_id=applicant["id"],
        jurisdiction_id=jur["id"],
        position_title=position_title,
        salary_history_disclosed=salary_history_disclosed,
    )
    return jur, applicant, application


def application_in_submitted(
    state_code: str = "OR",
    ban_the_box_enabled: Optional[bool] = None,
    salary_history_ban_enabled: Optional[bool] = None,
    pre_adverse_waiting_days: Optional[int] = None,
    clock_iso: str = "2026-06-01T10:00:00.000Z",
    salary_history_disclosed=None,
) -> Tuple[dict, dict, dict, dict]:
    """Walk DRAFT application all the way to SUBMITTED with a GRANTED consent.
    Returns (jurisdiction, applicant, application, consent) where the
    application carries its current SUBMITTED version."""
    jur, applicant, app = create_applicant_and_application(
        state_code=state_code,
        ban_the_box_enabled=ban_the_box_enabled,
        salary_history_ban_enabled=salary_history_ban_enabled,
        pre_adverse_waiting_days=pre_adverse_waiting_days,
        clock_iso=clock_iso,
        salary_history_disclosed=salary_history_disclosed,
    )
    consent = create_consent(app["id"], applicant["id"])
    consent = grant_consent(consent["id"], consent["version"], applicant["id"])
    app = submit_application(app["id"], app["version"], applicant["id"])
    return jur, applicant, app, consent


def application_in_conditional_offer(
    state_code: str = "OR",
    ban_the_box_enabled: Optional[bool] = None,
    salary_history_ban_enabled: Optional[bool] = None,
    pre_adverse_waiting_days: Optional[int] = None,
    clock_iso: str = "2026-06-01T10:00:00.000Z",
    recruiter_id: str = "rec-001",
    salary_history_disclosed=None,
) -> Tuple[dict, dict, dict, dict]:
    """Walk to CONDITIONAL_OFFER. recruiter_id is the Recruiter's X-User-ID
    captured on the conditional-offer audit row (used later by §2.7 SoD)."""
    jur, applicant, app, consent = application_in_submitted(
        state_code=state_code,
        ban_the_box_enabled=ban_the_box_enabled,
        salary_history_ban_enabled=salary_history_ban_enabled,
        pre_adverse_waiting_days=pre_adverse_waiting_days,
        clock_iso=clock_iso,
        salary_history_disclosed=salary_history_disclosed,
    )
    app = conditional_offer(app["id"], app["version"], recruiter_id=recruiter_id)
    return jur, applicant, app, consent


# ─── Tier 2: Order + verifications ─────────────────────────────────────

def order_with_three_pending_verifications(
    state_code: str = "OR",
    ban_the_box_enabled: Optional[bool] = None,
    salary_history_ban_enabled: Optional[bool] = None,
    pre_adverse_waiting_days: Optional[int] = None,
    clock_iso: str = "2026-06-01T10:00:00.000Z",
    recruiter_id: str = "rec-001",
    salary_history_disclosed=None,
) -> Tuple[dict, dict, dict, dict, dict, dict, dict]:
    """Walk to a PENDING order with all three Verifications (CRIMINAL, MVR,
    EDUCATION) created in PENDING. Returns
    (jurisdiction, applicant, application, consent, order, crim, mvr, edu)
    is the full set, but we return tuple (jur, applicant, app, consent, order,
    crim, mvr, edu)."""
    jur, applicant, app, consent = application_in_conditional_offer(
        state_code=state_code,
        ban_the_box_enabled=ban_the_box_enabled,
        salary_history_ban_enabled=salary_history_ban_enabled,
        pre_adverse_waiting_days=pre_adverse_waiting_days,
        clock_iso=clock_iso,
        recruiter_id=recruiter_id,
        salary_history_disclosed=salary_history_disclosed,
    )
    order = create_order(app["id"], consent["id"], app["version"],
                         recruiter_id=recruiter_id)
    crim = create_verification(order["id"], "CRIMINAL", recruiter_id=recruiter_id)
    mvr = create_verification(order["id"], "MVR", recruiter_id=recruiter_id)
    edu = create_verification(order["id"], "EDUCATION", recruiter_id=recruiter_id)
    return (jur, applicant, app, consent, order, crim, mvr, edu)


def order_complete_with_results(
    crim_result: str,
    mvr_result: str,
    edu_result: str,
    state_code: str = "OR",
    ban_the_box_enabled: Optional[bool] = None,
    salary_history_ban_enabled: Optional[bool] = None,
    pre_adverse_waiting_days: Optional[int] = None,
    clock_iso: str = "2026-06-01T10:00:00.000Z",
    recruiter_id: str = "rec-001",
    crim_payload=None,
    salary_history_disclosed=None,
):
    """Walk to a COMPLETE order with the three given results. The CRIMINAL
    verification is reported LAST so that, if any result is FAIL, the
    transition is IN_REVIEW -> COMPLETE (PRD §3.4) and the AdverseAction
    auto-create cascade (PRD §3.4 final paragraph) fires at that moment.

    Returns (jur, applicant, app, consent, order, crim, mvr, edu)
    where each verification dict carries the version it has *after* report.
    """
    (jur, applicant, app, consent, order, crim, mvr, edu) = (
        order_with_three_pending_verifications(
            state_code=state_code,
            ban_the_box_enabled=ban_the_box_enabled,
            salary_history_ban_enabled=salary_history_ban_enabled,
            pre_adverse_waiting_days=pre_adverse_waiting_days,
            clock_iso=clock_iso,
            recruiter_id=recruiter_id,
            salary_history_disclosed=salary_history_disclosed,
        )
    )
    mvr = report_verification(mvr["id"], mvr_result, mvr["version"])
    edu = report_verification(edu["id"], edu_result, edu["version"])
    crim = report_verification(crim["id"], crim_result, crim["version"],
                               report_payload=crim_payload)
    return (jur, applicant, app, consent, order, crim, mvr, edu)


def order_complete_consider_with_adverse_action(
    state_code: str = "OR",
    ban_the_box_enabled: Optional[bool] = None,
    pre_adverse_waiting_days: Optional[int] = None,
    clock_iso: str = "2026-06-01T10:00:00.000Z",
    recruiter_id: str = "rec-001",
    crim_payload=None,
):
    """Walk to COMPLETE+CONSIDER (CRIMINAL=FAIL, MVR=PASS, EDUCATION=PASS).
    PRD §3.4 guarantees a single AdverseAction in PRE_ADVERSE_SENT is
    auto-created in the same logical step. Returns
    (jur, applicant, app, consent, order, crim, mvr, edu, adverse_action).
    """
    (jur, applicant, app, consent, order, crim, mvr, edu) = (
        order_complete_with_results(
            crim_result="FAIL", mvr_result="PASS", edu_result="PASS",
            state_code=state_code,
            ban_the_box_enabled=ban_the_box_enabled,
            salary_history_ban_enabled=False,
            pre_adverse_waiting_days=pre_adverse_waiting_days,
            clock_iso=clock_iso,
            recruiter_id=recruiter_id,
            crim_payload=crim_payload,
        )
    )
    # PRD §3.4: AdverseAction auto-created when status reaches COMPLETE +
    # overall_result CONSIDER. PRD §4 exposes the row via the sub-resource list.
    aa_list_resp = api_client.list_order_adverse_action(order["id"], CO)
    aa_list = get_success_data(aa_list_resp)
    assert isinstance(aa_list, list) and len(aa_list) == 1, \
        f"PRD §3.4 expects exactly one auto-created AdverseAction after CONSIDER, got {aa_list!r}"
    adverse_action = aa_list[0]
    return (jur, applicant, app, consent, order, crim, mvr, edu, adverse_action)
