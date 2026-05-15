"""Composite setup helpers — multi-step preambles tests can reuse.

The university-application pipeline is long: applicant create →
university create → program create → application create → essay attach
→ recommendations create → recommendation accept → recommendation
submit-letter (×N) → submit application → admissions begin-review →
admissions decide → financial aid request → financial aid issue-offer
→ financial aid accept → enroll. Many test claims need the system in a
late-pipeline state; these helpers reach it.

IDENTITY THREADING — PRD §2.1:

- Applicant is ENTITY-BACKED. X-User-ID == Applicant.id. Every call
  whose success requires ownership (submit/withdraw/enroll an
  application, attach essay, request recommendation, accept/decline
  aid, accept waitlist offer) MUST mint headers via
  make_applicant_headers(applicant["id"]) — never via the shared
  APPLICANT_FALLBACK_ID. Fixtures below thread the real Applicant.id
  through every Applicant-role call.

- Recommender is OPAQUE-BUT-EMAIL-MATCHED. PRD §2.1: "A recommender
  may read or act on a RecommendationRequest only when the value of
  X-User-ID matches the recommender_email recorded on the request."
  Every Recommender-role call (accept, decline, submit-letter) MUST
  use make_recommender_headers(recommender_email) with the same email
  passed in the create-recommendation payload. Fixtures here preserve
  the email mapping and mint matching headers automatically.

- PlatformAdmin, AdmissionsOfficer, FinancialAidOfficer are OPAQUE —
  shared TEST_USERS constants are canonical. AdmissionsOfficer has a
  per-university scope check at the validation layer (PRD §2.1 / §3.7);
  it is enforced via the AdmissionsOfficer's university_id matching
  the program's university_id, NOT via entity identity.

Setup calls use get_success_data (a lenient 2xx validator), so a failed
setup surfaces as 'Setup failed' rather than a confusing test assertion
failure.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    INVITATION_VALIDITY_DAYS,
    NON_ED_ENROLLMENT_WINDOW_DAYS,
    TEST_DEFAULTS,
)
from .factories import (
    advance_clock_payload,
    attach_essay_payload,
    craft_essay_body,
    create_applicant_payload,
    create_application_payload,
    create_financial_aid_payload,
    create_program_payload,
    create_recommendation_payload,
    create_university_payload,
    decide_application_payload,
    iso_offset,
    random_suffix,
    submit_letter_payload,
)
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_recommender_headers,
)


# ===========================================================================
# Clock (PRD §3.11 — PlatformAdmin only)
# ===========================================================================
def advance_clock(seconds: int,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["platform_admin_headers"]
    res = api_client.advance_clock(seconds, headers)
    return get_success_data(res)


# ===========================================================================
# Applicant primitives (PRD §3.1)
# ===========================================================================
def create_applicant(**overrides: Any) -> Dict[str, Any]:
    """Create an applicant. Returns the Applicant resource.

    Per PRD §3.1, /applicants is open to Applicant and PlatformAdmin
    roles. We use PlatformAdmin to bootstrap so that no caller needs to
    know the applicant id before it exists.
    """
    res = api_client.create_applicant(
        create_applicant_payload(**overrides),
        TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(res)


def get_applicant(applicant_id: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["platform_admin_headers"]
    res = api_client.get_applicant(applicant_id, headers)
    return get_success_data(res)


def patch_applicant(applicant_id: str,
                    payload: Dict[str, Any],
                    headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Update Applicant fields. Defaults to using make_applicant_headers
    so ownership-gated updates use the right identity."""
    headers = headers or make_applicant_headers(applicant_id)
    res = api_client.patch_applicant(applicant_id, payload, headers)
    return get_success_data(res)


# ===========================================================================
# University & Program primitives (PRD §3.2)
# ===========================================================================
def create_university(**overrides: Any) -> Dict[str, Any]:
    """Register a university. Only PlatformAdmin per PRD §3.2."""
    res = api_client.create_university(
        create_university_payload(**overrides),
        TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(res)


def get_university(university_id: str,
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["platform_admin_headers"]
    res = api_client.get_university(university_id, headers)
    return get_success_data(res)


def create_program(university_id: str, **overrides: Any) -> Dict[str, Any]:
    """Add a program to a university. AdmissionsOfficer or PlatformAdmin.
    Defaults to PlatformAdmin to sidestep officer-university scope."""
    res = api_client.create_program(
        university_id,
        create_program_payload(**overrides),
        TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(res)


def get_program(program_id: str,
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["platform_admin_headers"]
    res = api_client.get_program(program_id, headers)
    return get_success_data(res)


# ===========================================================================
# Application primitives (PRD §3.3)
# ===========================================================================
def create_application(applicant_id: str,
                       program_id: str,
                       **overrides: Any) -> Dict[str, Any]:
    """Create an Application in DRAFT. Applicant-only per PRD §3.3.
    Uses make_applicant_headers(applicant_id) for ownership."""
    res = api_client.create_application(
        create_application_payload(applicant_id, program_id, **overrides),
        make_applicant_headers(applicant_id),
    )
    return get_success_data(res)


def get_application(application_id: str,
                    headers: Optional[Dict[str, str]] = None
                    ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["platform_admin_headers"]
    res = api_client.get_application(application_id, headers)
    return get_success_data(res)


# ===========================================================================
# Essay primitives (PRD §3.4)
# ===========================================================================
def attach_strong_essay(applicant_id: str,
                        application_id: str,
                        *,
                        university_name: str,
                        program_name: str,
                        prompt_code: str = "ESSAY-DEFAULT",
                        token_count: int = 500,
                        uni_mentions: int = 2,
                        prog_mentions: int = 2) -> Dict[str, Any]:
    """Attach an essay crafted to clear the >= 0.30 customization
    threshold under both DRAFT and SUBMITTED variants (PRD §3.4).

    Default token_count=500 + 2 uni mentions + 2 program mentions gives
    high length factor and high mention factors → score well above 0.30.
    """
    body = craft_essay_body(
        university_name=university_name,
        program_name=program_name,
        uni_mentions=uni_mentions,
        prog_mentions=prog_mentions,
        token_count=token_count,
    )
    res = api_client.attach_essay(
        application_id,
        attach_essay_payload(prompt_code=prompt_code, body=body),
        make_applicant_headers(applicant_id),
    )
    return get_success_data(res)


def patch_essay(applicant_id: str, essay_id: str,
                **fields: Any) -> Dict[str, Any]:
    res = api_client.patch_essay(
        essay_id, fields, make_applicant_headers(applicant_id),
    )
    return get_success_data(res)


def get_essay(essay_id: str,
              headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["platform_admin_headers"]
    res = api_client.get_essay(essay_id, headers)
    return get_success_data(res)


# ===========================================================================
# Recommendation primitives (PRD §3.5)
# ===========================================================================
def create_recommendation(applicant_id: str,
                          application_id: str,
                          *,
                          recommender_email: Optional[str] = None
                          ) -> Dict[str, Any]:
    """Create a RecommendationRequest. Returns the request with its
    recommender_email — caller should keep this to mint matching
    Recommender headers later."""
    payload = create_recommendation_payload()
    if recommender_email is not None:
        payload["recommender_email"] = recommender_email
    res = api_client.create_recommendation(
        application_id, payload, make_applicant_headers(applicant_id),
    )
    return get_success_data(res)


def accept_recommendation(recommendation: Dict[str, Any]) -> Dict[str, Any]:
    """Recommender accepts. Uses make_recommender_headers with the
    recommendation's own recommender_email so PRD §2.1's identity match
    succeeds."""
    res = api_client.accept_recommendation(
        recommendation["id"],
        make_recommender_headers(recommendation["recommender_email"]),
    )
    return get_success_data(res)


def decline_recommendation(recommendation: Dict[str, Any]) -> Dict[str, Any]:
    res = api_client.decline_recommendation(
        recommendation["id"],
        make_recommender_headers(recommendation["recommender_email"]),
    )
    return get_success_data(res)


def submit_letter(recommendation: Dict[str, Any],
                  *,
                  letter_body: Optional[str] = None,
                  word_count: int = 220) -> Dict[str, Any]:
    """Recommender submits letter. Default body has 220 whitespace tokens
    (above PRD §3.5's 200-word weak-letter threshold)."""
    if letter_body is None:
        letter_body = "word " * word_count
    res = api_client.submit_letter(
        recommendation["id"],
        {"letter_body": letter_body.strip()},
        make_recommender_headers(recommendation["recommender_email"]),
    )
    return get_success_data(res)


def setup_strong_recommendations(
    applicant_id: str,
    application_id: str,
    *,
    count: int = 2,
    word_count: int = 220,
) -> List[Dict[str, Any]]:
    """Create `count` recommendations, all of them accepted and with
    letters submitted at word_count >= 200 (PRD §3.5).
    Returns the list of final RecommendationRequest dicts.
    """
    final_recs: List[Dict[str, Any]] = []
    for _ in range(count):
        rec = create_recommendation(applicant_id, application_id)
        rec = accept_recommendation(rec)
        rec = submit_letter(rec, word_count=word_count)
        final_recs.append(rec)
    return final_recs


# ===========================================================================
# Application workflow shortcuts (PRD §3.6, §3.7, §3.10)
# ===========================================================================
def submit_application(applicant_id: str,
                       application_id: str,
                       *,
                       version: Optional[int] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    res = api_client.submit_application(
        application_id, make_applicant_headers(applicant_id), payload,
    )
    return get_success_data(res)


def withdraw_submission(applicant_id: str,
                        application_id: str,
                        *,
                        version: Optional[int] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    res = api_client.withdraw_submission(
        application_id, make_applicant_headers(applicant_id), payload,
    )
    return get_success_data(res)


def withdraw_application(applicant_id: str,
                         application_id: str,
                         *,
                         version: Optional[int] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    res = api_client.withdraw_application(
        application_id, make_applicant_headers(applicant_id), payload,
    )
    return get_success_data(res)


def begin_review(application_id: str,
                 headers: Optional[Dict[str, str]] = None
                 ) -> Dict[str, Any]:
    """AdmissionsOfficer-only per PRD §3.7. PRD §3.7 requires the
    officer's university_id to equal the target program's university_id
    (else ERR_FORBIDDEN). The default opaque officer is treated as
    universally scoped by tests that bootstrap with PlatformAdmin."""
    headers = headers or TEST_USERS["admissions_officer_headers"]
    res = api_client.begin_review(application_id, headers)
    return get_success_data(res)


def decide_application(application_id: str,
                       decision: str = "ADMIT",
                       headers: Optional[Dict[str, str]] = None
                       ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["admissions_officer_headers"]
    res = api_client.decide_application(
        application_id, decide_application_payload(decision), headers,
    )
    return get_success_data(res)


def enroll_application(applicant_id: str,
                       application_id: str,
                       *,
                       version: Optional[int] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    res = api_client.enroll_application(
        application_id, make_applicant_headers(applicant_id), payload,
    )
    return get_success_data(res)


# ===========================================================================
# Financial aid primitives (PRD §3.8)
# ===========================================================================
def create_financial_aid(applicant_id: str,
                         application_id: str,
                         *,
                         aid_method: str = "FEDERAL_METHODOLOGY",
                         cost_of_attendance_cents: int = 8_000_000
                         ) -> Dict[str, Any]:
    res = api_client.create_financial_aid(
        application_id,
        create_financial_aid_payload(
            aid_method=aid_method,
            cost_of_attendance_cents=cost_of_attendance_cents,
        ),
        make_applicant_headers(applicant_id),
    )
    return get_success_data(res)


def issue_aid_offer(package_id: str,
                    headers: Optional[Dict[str, str]] = None
                    ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["financial_aid_officer_headers"]
    res = api_client.issue_aid_offer(package_id, headers)
    return get_success_data(res)


def accept_aid_offer(applicant_id: str, package_id: str,
                     *, version: Optional[int] = None
                     ) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    res = api_client.accept_aid_offer(
        package_id, make_applicant_headers(applicant_id), payload,
    )
    return get_success_data(res)


def decline_aid_offer(applicant_id: str, package_id: str,
                      *, version: Optional[int] = None
                      ) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    res = api_client.decline_aid_offer(
        package_id, make_applicant_headers(applicant_id), payload,
    )
    return get_success_data(res)


# ===========================================================================
# Waitlist & yield primitives (PRD §3.9)
# ===========================================================================
def accept_waitlist_offer(applicant_id: str, entry_id: str,
                          *, version: Optional[int] = None
                          ) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    res = api_client.accept_waitlist_offer(
        entry_id, make_applicant_headers(applicant_id), payload,
    )
    return get_success_data(res)


def run_yield_sweep(university_id: str,
                    headers: Optional[Dict[str, str]] = None
                    ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["platform_admin_headers"]
    res = api_client.run_yield_sweep(university_id, headers)
    return get_success_data(res)


# ===========================================================================
# Tier 1: minimal scaffolding
# ===========================================================================
def setup_university_with_program(*,
                                  university_overrides: Optional[Dict[str, Any]] = None,
                                  program_overrides: Optional[Dict[str, Any]] = None
                                  ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create one University + one Program under it. Returns (university, program).

    Default deadlines are far in the future so no transition trips on
    them. Default program capacity is 10."""
    uni = create_university(**(university_overrides or {}))
    prog = create_program(uni["id"], **(program_overrides or {}))
    return uni, prog


def setup_applicant_with_application(
    *,
    applicant_overrides: Optional[Dict[str, Any]] = None,
    application_overrides: Optional[Dict[str, Any]] = None,
    university_overrides: Optional[Dict[str, Any]] = None,
    program_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create University, Program, Applicant, Application(DRAFT).
    Returns (applicant, university, program, application)."""
    uni, prog = setup_university_with_program(
        university_overrides=university_overrides,
        program_overrides=program_overrides,
    )
    applicant = create_applicant(**(applicant_overrides or {}))
    application = create_application(
        applicant["id"], prog["id"], **(application_overrides or {}),
    )
    return applicant, uni, prog, application


# ===========================================================================
# Tier 2: ready-to-submit applications
# ===========================================================================
def setup_application_ready_to_submit(
    *,
    round_: str = "REGULAR_DECISION",
    required_recommendation_count: int = 2,
    university_overrides: Optional[Dict[str, Any]] = None,
    program_overrides: Optional[Dict[str, Any]] = None,
    applicant_overrides: Optional[Dict[str, Any]] = None,
    prompt_code: Optional[str] = None,
    essay_token_count: int = 500,
    essay_uni_mentions: int = 2,
    essay_prog_mentions: int = 2,
) -> Dict[str, Any]:
    """Build an application that satisfies every submission precondition
    PRD §3.6 requires EXCEPT the actual /submit call.

    - University with deadlines well in the future.
    - Rolling admission enabled (so round=ROLLING applications also pass).
    - Applicant with valid GPA/income/EFCs.
    - Application in DRAFT with round=`round_`.
    - Essay attached with customization_score >= 0.30 (PRD §3.4).
    - `required_recommendation_count` recommendations, all SUBMITTED
      with letter_word_count >= 200 (PRD §3.5).

    Returns dict: applicant, university, program, application, essay,
    recommendations. Caller invokes submit_application(...) to fire
    the transition.
    """
    uni_overrides = dict(university_overrides or {})
    uni_overrides.setdefault("rolling_admission_enabled", True)
    uni_overrides.setdefault("regular_decision_deadline", iso_offset(days=180))
    uni_overrides.setdefault("early_decision_deadline", iso_offset(days=90))
    applicant_overrides = dict(applicant_overrides or {})
    program_overrides = dict(program_overrides or {})

    applicant, uni, prog, application = setup_applicant_with_application(
        applicant_overrides=applicant_overrides,
        application_overrides={
            "round": round_,
            "required_recommendation_count": required_recommendation_count,
        },
        university_overrides=uni_overrides,
        program_overrides=program_overrides,
    )

    # Compose a prompt_code that mentions the university id-prefix
    # so PRD §3.4's prompt_match factor can fire. Per PRD §3.4 the
    # match condition is that prompt_code begins with the target
    # university's id-prefix code; the implementation defines the
    # exact prefix length, so we use the full university id as a
    # safe prefix (a faithful PRD implementer will accept either
    # 'starts with the id' or 'starts with some derived prefix' —
    # but starts-with-id should match any reasonable derivation).
    if prompt_code is None:
        prompt_code = f"{uni['id']}-prompt-{random_suffix(4)}"

    essay = attach_strong_essay(
        applicant["id"], application["id"],
        university_name=uni["name"],
        program_name=prog["name"],
        prompt_code=prompt_code,
        token_count=essay_token_count,
        uni_mentions=essay_uni_mentions,
        prog_mentions=essay_prog_mentions,
    )

    recommendations = setup_strong_recommendations(
        applicant["id"], application["id"],
        count=required_recommendation_count,
    )

    # Refresh application: attaching the essay writes essay_id back onto
    # the application (PRD §3.4 — "writes the new submission's id back
    # onto the application's essay_id"), which per PRD §2.4 increments
    # the application's version. Callers asserting +1 from the next
    # mutation must see the post-setup state.
    application = get_application(application["id"])

    return {
        "applicant": applicant,
        "university": uni,
        "program": prog,
        "application": application,
        "essay": essay,
        "recommendations": recommendations,
    }


def setup_submitted_application(**kwargs: Any) -> Dict[str, Any]:
    """As setup_application_ready_to_submit but also fires the submit
    transition. The returned dict's `application` is in SUBMITTED state."""
    ctx = setup_application_ready_to_submit(**kwargs)
    submitted = submit_application(
        ctx["applicant"]["id"], ctx["application"]["id"],
    )
    ctx["application"] = submitted
    return ctx


def setup_under_review_application(**kwargs: Any) -> Dict[str, Any]:
    """Submitted application moved into UNDER_REVIEW by begin-review."""
    ctx = setup_submitted_application(**kwargs)
    reviewed = begin_review(ctx["application"]["id"])
    ctx["application"] = reviewed
    return ctx


def setup_admitted_application(**kwargs: Any) -> Dict[str, Any]:
    """Application driven through to ADMITTED state."""
    ctx = setup_under_review_application(**kwargs)
    admitted = decide_application(ctx["application"]["id"], decision="ADMIT")
    ctx["application"] = admitted
    return ctx


def setup_waitlisted_application(**kwargs: Any) -> Dict[str, Any]:
    """Application driven through to WAITLISTED state."""
    ctx = setup_under_review_application(**kwargs)
    waitlisted = decide_application(ctx["application"]["id"], decision="WAITLIST")
    ctx["application"] = waitlisted
    return ctx


def setup_rejected_application(**kwargs: Any) -> Dict[str, Any]:
    """Application driven through to REJECTED state."""
    ctx = setup_under_review_application(**kwargs)
    rejected = decide_application(ctx["application"]["id"], decision="REJECT")
    ctx["application"] = rejected
    return ctx


# ===========================================================================
# Tier 3: financial-aid lifecycle shortcuts (PRD §3.8)
# ===========================================================================
def setup_admitted_with_aid_requested(
    *,
    aid_method: str = "FEDERAL_METHODOLOGY",
    cost_of_attendance_cents: int = 8_000_000,
    fafsa_efc_cents: Optional[int] = 2_000_000,
    css_profile_efc_cents: Optional[int] = 2_000_000,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Admitted application + FinancialAidPackage in REQUESTED.
    Applicant has both EFCs populated by default so either methodology
    can be issued without ERR_MISSING_EFC."""
    applicant_overrides = dict(kwargs.pop("applicant_overrides", {}) or {})
    if fafsa_efc_cents is not None:
        applicant_overrides.setdefault("fafsa_efc_cents", fafsa_efc_cents)
    if css_profile_efc_cents is not None:
        applicant_overrides.setdefault(
            "css_profile_efc_cents", css_profile_efc_cents,
        )
    ctx = setup_admitted_application(
        applicant_overrides=applicant_overrides, **kwargs,
    )
    pkg = create_financial_aid(
        ctx["applicant"]["id"], ctx["application"]["id"],
        aid_method=aid_method,
        cost_of_attendance_cents=cost_of_attendance_cents,
    )
    ctx["financial_aid"] = pkg
    return ctx


def setup_admitted_with_aid_offered(**kwargs: Any) -> Dict[str, Any]:
    """Admitted application + FinancialAidPackage in OFFERED (computed)."""
    ctx = setup_admitted_with_aid_requested(**kwargs)
    offered = issue_aid_offer(ctx["financial_aid"]["id"])
    ctx["financial_aid"] = offered
    return ctx


def setup_admitted_with_aid_accepted(**kwargs: Any) -> Dict[str, Any]:
    """Admitted application + FinancialAidPackage in ACCEPTED."""
    ctx = setup_admitted_with_aid_offered(**kwargs)
    accepted = accept_aid_offer(
        ctx["applicant"]["id"], ctx["financial_aid"]["id"],
    )
    ctx["financial_aid"] = accepted
    return ctx


# ===========================================================================
# Tier 4: ED-binding scenarios (PRD §3.6, §2.10)
# ===========================================================================
def setup_ed_bound_applicant(
    *,
    program_overrides: Optional[Dict[str, Any]] = None,
    university_overrides: Optional[Dict[str, Any]] = None,
    applicant_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Applicant who has SUBMITTED an Early Decision application (so
    Applicant.ed_commitment_application_id is set). Returns the same
    dict shape as setup_submitted_application plus 'ed_application'."""
    ctx = setup_submitted_application(
        round_="EARLY_DECISION",
        program_overrides=program_overrides,
        university_overrides=university_overrides,
        applicant_overrides=applicant_overrides,
    )
    ctx["ed_application"] = ctx["application"]
    return ctx


# ===========================================================================
# Tier 5: cascade / multi-application fixtures (PRD §3.10)
# ===========================================================================
def setup_applicant_with_two_admitted_applications(
    *,
    applicant_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One applicant with TWO admitted applications across two
    different universities/programs. Used for the enroll cascade test
    (PRD §3.10): enrolling APP1 cascades-withdraw on APP2."""
    applicant = create_applicant(**(applicant_overrides or {}))

    # First univ/program/app — admit APP1
    uni1, prog1 = setup_university_with_program()
    ctx1 = _drive_app_to_admitted(
        applicant_id=applicant["id"],
        program_id=prog1["id"],
        university_name=uni1["name"],
        program_name=prog1["name"],
        round_="REGULAR_DECISION",
    )

    # Second univ/program/app — admit APP2
    uni2, prog2 = setup_university_with_program()
    ctx2 = _drive_app_to_admitted(
        applicant_id=applicant["id"],
        program_id=prog2["id"],
        university_name=uni2["name"],
        program_name=prog2["name"],
        round_="REGULAR_DECISION",
    )

    return {
        "applicant": applicant,
        "university_1": uni1,
        "program_1": prog1,
        "application_1": ctx1["application"],
        "university_2": uni2,
        "program_2": prog2,
        "application_2": ctx2["application"],
    }


def _drive_app_to_admitted(*,
                           applicant_id: str,
                           program_id: str,
                           university_name: str,
                           program_name: str,
                           round_: str,
                           required_recommendation_count: int = 2,
                           ) -> Dict[str, Any]:
    """Internal: build an application for an existing applicant on the
    given program and drive it to ADMITTED. Returns {application}."""
    app = create_application(
        applicant_id, program_id,
        round=round_,
        required_recommendation_count=required_recommendation_count,
    )
    # Essay strong enough to clear 0.30
    essay = attach_strong_essay(
        applicant_id, app["id"],
        university_name=university_name,
        program_name=program_name,
    )
    setup_strong_recommendations(
        applicant_id, app["id"],
        count=required_recommendation_count,
    )
    submitted = submit_application(applicant_id, app["id"])
    reviewed = begin_review(submitted["id"])
    admitted = decide_application(reviewed["id"], decision="ADMIT")
    return {"application": admitted, "essay": essay}


def setup_enroll_cascade_scenario() -> Dict[str, Any]:
    """Build the depth-3 enroll cascade fixture from PRD §3.10.

    Applicant A with:
      - APP1 on Program P1 of University U1, status=ADMITTED
      - APP2 on Program P2 of University U2, status=ADMITTED, with
        FinancialAidPackage F2 in OFFERED
      - APP3 on Program P3 of University U3, status=WAITLISTED, with
        WaitlistEntry W3 in ACTIVE

    Caller enrolls APP1 and asserts the depth-3 cascade.
    """
    applicant = create_applicant()

    uni1, prog1 = setup_university_with_program()
    uni2, prog2 = setup_university_with_program()
    uni3, prog3 = setup_university_with_program()

    # APP1 → ADMITTED
    ctx1 = _drive_app_to_admitted(
        applicant_id=applicant["id"], program_id=prog1["id"],
        university_name=uni1["name"], program_name=prog1["name"],
        round_="REGULAR_DECISION",
    )

    # APP2 → ADMITTED + aid OFFERED
    ctx2 = _drive_app_to_admitted(
        applicant_id=applicant["id"], program_id=prog2["id"],
        university_name=uni2["name"], program_name=prog2["name"],
        round_="REGULAR_DECISION",
    )
    # Need EFCs for aid offer — patch applicant.
    patch_applicant(applicant["id"], {
        "fafsa_efc_cents": 2_000_000,
    })
    pkg2 = create_financial_aid(
        applicant["id"], ctx2["application"]["id"],
        aid_method="FEDERAL_METHODOLOGY",
        cost_of_attendance_cents=8_000_000,
    )
    pkg2 = issue_aid_offer(pkg2["id"])

    # APP3 → WAITLISTED (creates WaitlistEntry W3 in ACTIVE)
    app3 = create_application(
        applicant["id"], prog3["id"], round="REGULAR_DECISION",
    )
    attach_strong_essay(
        applicant["id"], app3["id"],
        university_name=uni3["name"], program_name=prog3["name"],
    )
    setup_strong_recommendations(applicant["id"], app3["id"])
    submit_application(applicant["id"], app3["id"])
    begin_review(app3["id"])
    app3_waitlisted = decide_application(app3["id"], decision="WAITLIST")

    return {
        "applicant": applicant,
        "university_1": uni1, "program_1": prog1,
        "application_1": ctx1["application"],
        "university_2": uni2, "program_2": prog2,
        "application_2": ctx2["application"],
        "financial_aid_2": pkg2,
        "university_3": uni3, "program_3": prog3,
        "application_3": app3_waitlisted,
    }


# ===========================================================================
# Tier 6: waitlist & yield-sweep fixtures (PRD §3.9)
# ===========================================================================
def setup_waitlist_entry_in_active(**kwargs: Any) -> Dict[str, Any]:
    """Build an application in WAITLISTED state. The /decide=WAITLIST
    transition side-effect (PRD §3.7) creates the WaitlistEntry; we
    fetch it via the application's waitlist linkage. Returns ctx with
    a 'waitlist_entry' key (the ACTIVE entry).

    The PRD does not expose a 'list waitlist entries for application'
    endpoint, so the caller obtains the entry id either by:
      (a) reading the decision response (if the implementation includes
          waitlist_entry_id in the returned Application — note: this is
          not a PRD-stated guarantee), or
      (b) reading via GET /waitlist/{id} with a known id from the
          response or the run-yield-sweep audit log.

    For test purposes we return the application; tests that need the
    entry id should obtain it through one of those documented paths.
    """
    ctx = setup_waitlisted_application(**kwargs)
    return ctx


def setup_waitlist_offer_pending(
    *,
    university_yield_target: int = 100,
    program_capacity: int = 10,
    additional_applicants_admitted: int = 0,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Build a single waitlisted application, then run a yield sweep
    so that its WaitlistEntry is OFFERED. Returns the ctx with
    'yield_sweep' included.

    The waitlist promotion requires Program.admitted_count < capacity
    (PRD §3.9 stage 4). We optionally admit `additional_applicants_admitted`
    other applicants to consume capacity precisely.
    """
    ctx = setup_waitlisted_application(
        university_overrides={
            "yield_target_count": university_yield_target,
        },
        program_overrides={"capacity": program_capacity},
        **kwargs,
    )
    # Optionally fill admitted slots with throwaway applicants.
    for _ in range(additional_applicants_admitted):
        extra_applicant = create_applicant()
        _drive_app_to_admitted(
            applicant_id=extra_applicant["id"],
            program_id=ctx["program"]["id"],
            university_name=ctx["university"]["name"],
            program_name=ctx["program"]["name"],
            round_="REGULAR_DECISION",
        )
    sweep = run_yield_sweep(ctx["university"]["id"])
    ctx["yield_sweep"] = sweep
    return ctx


# ===========================================================================
# Tier 7: applicant-with-known-EFCs for financial-aid calc boundary tests
# ===========================================================================
def setup_admitted_applicant_with_known_efcs(
    *,
    fafsa_efc_cents: int = 2_000_000,
    css_profile_efc_cents: int = 2_000_000,
    cost_of_attendance_cents: int = 8_000_000,
    aid_method: str = "FEDERAL_METHODOLOGY",
) -> Dict[str, Any]:
    """Build a single ADMITTED Application whose Applicant has both
    EFCs populated, with a FinancialAidPackage in REQUESTED ready for
    issue-offer. Used for PRD §3.8 calc boundary tests."""
    return setup_admitted_with_aid_requested(
        aid_method=aid_method,
        cost_of_attendance_cents=cost_of_attendance_cents,
        fafsa_efc_cents=fafsa_efc_cents,
        css_profile_efc_cents=css_profile_efc_cents,
    )


__all__ = [
    # Primitives
    "advance_clock",
    "create_applicant",
    "get_applicant",
    "patch_applicant",
    "create_university",
    "get_university",
    "create_program",
    "get_program",
    "create_application",
    "get_application",
    "attach_strong_essay",
    "patch_essay",
    "get_essay",
    "create_recommendation",
    "accept_recommendation",
    "decline_recommendation",
    "submit_letter",
    "setup_strong_recommendations",
    "submit_application",
    "withdraw_submission",
    "withdraw_application",
    "begin_review",
    "decide_application",
    "enroll_application",
    "create_financial_aid",
    "issue_aid_offer",
    "accept_aid_offer",
    "decline_aid_offer",
    "accept_waitlist_offer",
    "run_yield_sweep",
    # Composite fixtures
    "setup_university_with_program",
    "setup_applicant_with_application",
    "setup_application_ready_to_submit",
    "setup_submitted_application",
    "setup_under_review_application",
    "setup_admitted_application",
    "setup_waitlisted_application",
    "setup_rejected_application",
    "setup_admitted_with_aid_requested",
    "setup_admitted_with_aid_offered",
    "setup_admitted_with_aid_accepted",
    "setup_ed_bound_applicant",
    "setup_applicant_with_two_admitted_applications",
    "setup_enroll_cascade_scenario",
    "setup_waitlist_entry_in_active",
    "setup_waitlist_offer_pending",
    "setup_admitted_applicant_with_known_efcs",
]
