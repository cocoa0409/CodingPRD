"""Composite setup helpers for multi-step test prerequisites.

The University Application Platform requires many tests to reach an
ADMITTED, ENROLLED, or WAITLISTED state — each of which takes 8-15 API
calls (register → invite recommender → accept → create app → essay →
letter → start → submit letter → submit app → start-review → decide).
These helpers encapsulate that walk so test bodies stay focused on the
single assertion they validate.

Every helper uses get_success_data() (lenient — accepts any 2xx) so
setup failures surface as 'Setup failed' rather than confusing assertion
errors deep inside a test.
"""
from typing import Optional, Tuple, List

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_applicant_payload, create_recommender_payload, create_school_payload,
    create_application_payload, create_essay_payload, create_letter_payload,
    create_fa_profile_payload, create_aid_offer_payload, decide_payload,
    submit_letter_payload, LONG_LETTER_BODY,
    DEFAULT_TEST_CLOCK, DEFAULT_ED_DEADLINE, DEFAULT_EA_DEADLINE,
    DEFAULT_RD_DEADLINE,
)
from .test_users import (
    admin_headers, admissions_headers, fa_officer_headers,
    make_applicant_headers, make_recommender_headers,
)


# --- Tier 0: Primitives --------------------------------------------------

def advance_clock_to(iso8601: str) -> None:
    """Move the test clock. PRD §2.10 / §3 / §4."""
    get_success_data(api_client.advance_clock(iso8601, admin_headers()))


def register_applicant(**overrides) -> dict:
    """Create an Applicant via public registration (PRD §3.1)."""
    return get_success_data(api_client.register_applicant(
        create_applicant_payload(**overrides)))


def create_school(**overrides) -> dict:
    """Create a School (PRD §3.3). Requires PlatformAdmin role."""
    return get_success_data(api_client.create_school(
        create_school_payload(**overrides), admin_headers()))


def setup_clock_and_school(clock_iso: str = DEFAULT_TEST_CLOCK,
                           **school_overrides) -> dict:
    """Initialize the test clock and create one school.

    The clock is advanced AFTER school creation so the school's
    ed/ea/rd deadlines (default 2030/2031) lie in the future of the
    new clock value (2030-10-01).
    """
    school = create_school(**school_overrides)
    advance_clock_to(clock_iso)
    return school


def invite_and_accept_recommender(applicant_id: str,
                                  **overrides) -> dict:
    """Create a Recommender for an Applicant and accept the invitation.

    PRD §3.2: invitation transition INVITED → ACCEPTED via the public
    accept endpoint.
    """
    rec = get_success_data(api_client.create_recommender(
        create_recommender_payload(applicant_id, **overrides),
        make_applicant_headers(applicant_id)))
    get_success_data(api_client.accept_recommender(rec["id"]))
    return rec


def create_recommender_invited(applicant_id: str,
                               **overrides) -> dict:
    """Create a Recommender without accepting — stays in INVITED."""
    return get_success_data(api_client.create_recommender(
        create_recommender_payload(applicant_id, **overrides),
        make_applicant_headers(applicant_id)))


# --- Tier 1: Applicant in READY state ------------------------------------

def setup_applicant_ready(school: Optional[dict] = None) -> Tuple[dict, dict]:
    """Create an Applicant with a full profile and an ACCEPTED Recommender.

    Returns (applicant, recommender). PRD §3.1: profile_status flips to
    READY when full_name and gpa are set AND >= 1 Recommender row exists.
    """
    applicant = register_applicant(full_name="Ready Test", gpa=3.5, sat_total=1400)
    recommender = invite_and_accept_recommender(applicant["id"])
    return applicant, recommender


# --- Tier 2: Application lifecycle progression ---------------------------

def create_application(applicant_id: str, school_id: str,
                       plan: str = "REGULAR") -> dict:
    """Create a DRAFT Application (PRD §3.4)."""
    return get_success_data(api_client.create_application(
        create_application_payload(applicant_id, school_id, plan),
        make_applicant_headers(applicant_id)))


def create_essay(application_id: str, applicant_id: str,
                 body: str = "this is an essay body for the application") -> dict:
    """Create an essay (PRD §3.5). Default body is 9 words within [1..650]."""
    return get_success_data(api_client.create_essay(
        create_essay_payload(application_id, body=body),
        make_applicant_headers(applicant_id)))


def create_and_submit_letter(application_id: str, applicant_id: str,
                             recommender_id: str,
                             body: str = LONG_LETTER_BODY) -> dict:
    """Create a letter, walk REQUESTED → IN_PROGRESS → SUBMITTED.

    Assumes the recommender is already in ACCEPTED state and the
    application is in DRAFT (PRD §3.2 preconditions).
    """
    letter = get_success_data(api_client.create_letter(
        create_letter_payload(application_id, recommender_id),
        make_applicant_headers(applicant_id)))
    get_success_data(api_client.start_letter(
        letter["id"], make_recommender_headers(recommender_id)))
    get_success_data(api_client.submit_letter(
        letter["id"], submit_letter_payload(body=body),
        make_recommender_headers(recommender_id)))
    return letter


def create_requested_letter(application_id: str, applicant_id: str,
                            recommender_id: str) -> dict:
    """Create a letter and leave it in REQUESTED."""
    return get_success_data(api_client.create_letter(
        create_letter_payload(application_id, recommender_id),
        make_applicant_headers(applicant_id)))


def submit_application(application_id: str, applicant_id: str) -> dict:
    return get_success_data(api_client.submit_application(
        application_id, make_applicant_headers(applicant_id)))


def start_review(application_id: str) -> dict:
    return get_success_data(api_client.start_review_application(
        application_id, admissions_headers()))


def decide(application_id: str, decision: str,
           expected_application_version: int) -> dict:
    return get_success_data(api_client.decide_application(
        application_id,
        decide_payload(decision, expected_application_version),
        admissions_headers()))


# --- Tier 3: Composite — full path to ADMITTED ---------------------------

def setup_admitted_application(
    plan: str = "REGULAR",
    school_overrides: Optional[dict] = None,
    *,
    include_letter: bool = True,
) -> Tuple[dict, dict, dict]:
    """Drive an Application all the way to ADMITTED.

    Pipeline:
      register applicant + recommender(ACCEPTED) → create app → essay →
      letter REQUESTED → IN_PROGRESS → SUBMITTED → submit app → start-review
      → decide(ADMIT).

    Returns (applicant, school, application_admitted). The returned
    application has fresh version captured for OCC.
    """
    school = setup_clock_and_school(**(school_overrides or {}))
    applicant, recommender = setup_applicant_ready()

    app = create_application(applicant["id"], school["id"], plan)
    create_essay(app["id"], applicant["id"])
    if include_letter:
        create_and_submit_letter(app["id"], applicant["id"], recommender["id"])
    submit_application(app["id"], applicant["id"])
    reviewed = start_review(app["id"])
    admitted = decide(app["id"], "ADMIT", reviewed["version"])
    return applicant, school, admitted


def setup_under_review_application(
    plan: str = "REGULAR",
    school_overrides: Optional[dict] = None,
) -> Tuple[dict, dict, dict, dict]:
    """Drive an Application to UNDER_REVIEW.

    Returns (applicant, recommender, school, application_under_review).
    """
    school = setup_clock_and_school(**(school_overrides or {}))
    applicant, recommender = setup_applicant_ready()
    app = create_application(applicant["id"], school["id"], plan)
    create_essay(app["id"], applicant["id"])
    create_and_submit_letter(app["id"], applicant["id"], recommender["id"])
    submit_application(app["id"], applicant["id"])
    reviewed = start_review(app["id"])
    return applicant, recommender, school, reviewed


def setup_draft_application(plan: str = "REGULAR",
                            school_overrides: Optional[dict] = None,
                            *,
                            ready_profile: bool = True
                            ) -> Tuple[dict, Optional[dict], dict, dict]:
    """Build an Applicant + Application in DRAFT state.

    When ``ready_profile`` is true, the applicant has an accepted
    Recommender (profile_status=READY). Returns (applicant, recommender_or_None,
    school, application_draft).
    """
    school = setup_clock_and_school(**(school_overrides or {}))
    if ready_profile:
        applicant, recommender = setup_applicant_ready()
    else:
        applicant = register_applicant()
        recommender = None
    app = create_application(applicant["id"], school["id"], plan)
    return applicant, recommender, school, app


# --- Tier 4: Waitlist / yield scenarios ---------------------------------

def setup_waitlisted_application(
    school_overrides: Optional[dict] = None,
) -> Tuple[dict, dict, dict]:
    """Drive an Application to WAITLISTED.

    Returns (applicant, school, waitlisted_application).
    """
    school = setup_clock_and_school(**(school_overrides or {}))
    applicant, recommender = setup_applicant_ready()
    app = create_application(applicant["id"], school["id"], "REGULAR")
    create_essay(app["id"], applicant["id"])
    create_and_submit_letter(app["id"], applicant["id"], recommender["id"])
    submit_application(app["id"], applicant["id"])
    reviewed = start_review(app["id"])
    waitlisted = decide(app["id"], "WAITLIST", reviewed["version"])
    return applicant, school, waitlisted


def setup_enrolled_application(
    school_overrides: Optional[dict] = None,
    plan: str = "REGULAR",
) -> Tuple[dict, dict, dict]:
    """Drive an Application all the way to ENROLLED.

    Returns (applicant, school, enrolled_application).
    """
    applicant, school, admitted = setup_admitted_application(
        plan=plan, school_overrides=school_overrides)
    enrolled = get_success_data(api_client.accept_offer(
        admitted["id"], make_applicant_headers(applicant["id"])))
    return applicant, school, enrolled


# --- Tier 5: Aid offer scenarios ----------------------------------------

def setup_admitted_with_fa_profile(
    fafsa_efc_cents: int = 1_500_000,
    css_efc_cents: Optional[int] = None,
    family_income_cents: int = 6_000_000,
    school_overrides: Optional[dict] = None,
) -> Tuple[dict, dict, dict, dict]:
    """ADMITTED Application + SUBMITTED FinancialAidProfile.

    Returns (applicant, school, application_admitted, fa_profile).
    """
    applicant, school, admitted = setup_admitted_application(
        plan="REGULAR", school_overrides=school_overrides)

    fa_payload = create_fa_profile_payload(
        applicant["id"],
        fafsa_efc_cents=fafsa_efc_cents,
        family_income_cents=family_income_cents,
    )
    if css_efc_cents is not None:
        fa_payload["css_efc_cents"] = css_efc_cents

    fa = get_success_data(api_client.create_financial_aid_profile(
        fa_payload, make_applicant_headers(applicant["id"])))
    submitted_fa = get_success_data(api_client.submit_financial_aid_profile(
        fa["id"], make_applicant_headers(applicant["id"])))
    return applicant, school, admitted, submitted_fa


# --- Word-count helpers for essay boundary tests -------------------------

def make_body_with_word_count(n: int) -> str:
    """Build an essay body that splits into exactly ``n`` whitespace tokens.

    PRD §3.5: word_count is computed as the number of whitespace-separated
    tokens.
    """
    assert n >= 0
    if n == 0:
        return ""
    return " ".join(["word"] * n)
