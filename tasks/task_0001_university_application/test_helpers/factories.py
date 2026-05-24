"""Payload factories — one per entity, input fields only.

Each factory takes a minimal set of required fields plus **overrides to
let callers tune the payload. Defaults pick safe values that pass all
type/range constraints from PRD §3.
"""
import itertools
import uuid


# A pool of deadline triplets that satisfy strict ED < EA < RD ordering
# (PRD §3.3: "the Early-Decision deadline is earlier than the Early-Action
# deadline, which is earlier than the Regular-Decision deadline").
DEFAULT_ED_DEADLINE = "2030-11-01T00:00:00Z"
DEFAULT_EA_DEADLINE = "2030-11-15T00:00:00Z"
DEFAULT_RD_DEADLINE = "2031-01-01T00:00:00Z"
DEFAULT_COOLDOWN_MS = 86_400_000
DEFAULT_TEST_CLOCK = "2030-10-01T00:00:00Z"

_SCHOOL_NAME_COUNTER = itertools.count(1)
_EMAIL_COUNTER = itertools.count(1)


def unique_school_name(prefix: str = "TestU") -> str:
    return f"{prefix}-{next(_SCHOOL_NAME_COUNTER)}-{uuid.uuid4().hex[:6]}"


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}{next(_EMAIL_COUNTER)}-{uuid.uuid4().hex[:6]}@example.com"


def create_applicant_payload(**overrides) -> dict:
    defaults = {
        "email": unique_email("app"),
        "full_name": "Test Applicant",
        "gpa": 3.5,
        "sat_total": 1300,
    }
    defaults.update(overrides)
    return defaults


def create_recommender_payload(applicant_id: str, **overrides) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "email": unique_email("rec"),
        "full_name": "Test Recommender",
        "relationship": "TEACHER",
    }
    defaults.update(overrides)
    return defaults


def create_school_payload(**overrides) -> dict:
    defaults = {
        "name": unique_school_name(),
        "target_class_size": 5,
        "ed_deadline_iso": DEFAULT_ED_DEADLINE,
        "ea_deadline_iso": DEFAULT_EA_DEADLINE,
        "rd_deadline_iso": DEFAULT_RD_DEADLINE,
        "rolling_open": False,
        "requires_css_profile": False,
        "cooldown_ms": DEFAULT_COOLDOWN_MS,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(applicant_id: str, school_id: str,
                               plan: str = "REGULAR", **overrides) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "school_id": school_id,
        "plan": plan,
    }
    defaults.update(overrides)
    return defaults


def create_essay_payload(application_id: str, body: str = "Test essay body content.",
                         prompt_code: str = "P1", **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "prompt_code": prompt_code,
        "body": body,
    }
    defaults.update(overrides)
    return defaults


def create_letter_payload(application_id: str, recommender_id: str,
                          **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "recommender_id": recommender_id,
    }
    defaults.update(overrides)
    return defaults


# PRD §3.2: "the supplied body be non-null with length of at least 200 characters"
LONG_LETTER_BODY = (
    "Recommendation letter content for the applicant. "
    "This applicant has demonstrated exceptional intellectual curiosity, "
    "diligence, and growth over the period of instruction. "
    "Their academic record, classroom contributions, and personal qualities "
    "all merit the strongest possible support for admission."
)
assert len(LONG_LETTER_BODY) >= 200, "fixture body must be >= 200 chars per PRD §3.2"


def submit_letter_payload(body: str = LONG_LETTER_BODY, **overrides) -> dict:
    defaults = {"body": body}
    defaults.update(overrides)
    return defaults


def create_fa_profile_payload(applicant_id: str,
                              fafsa_efc_cents: int = 1_500_000,
                              family_income_cents: int = 6_000_000,
                              **overrides) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "fafsa_efc_cents": fafsa_efc_cents,
        "family_income_cents": family_income_cents,
    }
    defaults.update(overrides)
    return defaults


def create_aid_offer_payload(application_id: str,
                             expected_application_version: int,
                             cost_of_attendance_cents: int = 7_000_000,
                             variant: str = "FEDERAL",
                             grant_cents: int = 0,
                             loan_cents: int = 0,
                             work_study_cents: int = 0,
                             **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "cost_of_attendance_cents": cost_of_attendance_cents,
        "variant": variant,
        "grant_cents": grant_cents,
        "loan_cents": loan_cents,
        "work_study_cents": work_study_cents,
        "expected_application_version": expected_application_version,
    }
    defaults.update(overrides)
    return defaults


def decide_payload(decision: str, expected_application_version: int) -> dict:
    return {
        "decision": decision,
        "expected_application_version": expected_application_version,
    }
