"""Screening applications: two-pass fit score, info-request cycle, approval gates."""
from datetime import timedelta

from test_helpers import (
    ApiErrorId,
    apply_to_study,
    approve_application,
    assert_instant_equals,
    close_study,
    create_nda,
    create_study,
    enroll_participant,
    get_pending_signature,
    get_success_data,
    make_participant_headers,
    parse_instant,
    register_participant,
    set_clock,
    setup_study_with_published_nda,
    start_review,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
RESEARCHER = TEST_USERS["researcher_headers"]
LEGAL = TEST_USERS["legal_headers"]


def _setup_under_review(email="app-p@x.com", age_years=25, region_code="US-W",
                        platform_tags=None, study_overrides=None, publish_nda=True):
    """Participant ACTIVE; study RECRUITING; application UNDER_REVIEW.

    Returns dict(study, nda, participant, application)."""
    study = create_study(**(study_overrides or {}))
    nda = create_nda(study["id"], publish=publish_nda)
    participant = register_participant(email=email, age_years=age_years,
                                       region_code=region_code,
                                       platform_tags=platform_tags)
    app = apply_to_study(study["id"], participant["id"])
    app = start_review(app["id"])
    return {"study": study, "nda": nda, "participant": participant,
            "application": app}


class TestDualVariantFitScore:
    def test_fit_score_variants_diverge_when_verification_narrows_platforms(self, api):
        """PRD §3.2: "The **self-reported** variant, computed at submission, uses
        the participant's self-declared `platform_tags` and lands in
        `fit_score_provisional`. The **verified** variant, computed at approval,
        uses `verified_platform_tags` — empty until operations verifies
        attributes — and lands in `fit_score_final`, which stays null until an
        approval is attempted; identical inputs therefore produce a different
        score whenever verification narrowed the platform set."
        PRD §3.2: "The age component contributes 40 points when the
        participant's `age_years` falls within the study's `min_age`–`max_age`
        band, both bounds inclusive, and 0 otherwise. The region component
        contributes 30 points when the participant's `region_code` appears in
        the study's `allowed_regions`, and 0 otherwise."

        Design: Difficulty/dual_variant_calc/screening_fit_provisional_vs_verified
        """
        set_clock()
        ctx = _setup_under_review(email="dv1-p@x.com", platform_tags=["PC", "PS5"])
        assert ctx["application"]["fit_score_provisional"] == 100, (
            "self-reported variant: 40 age + 30 region + 30 platform (PC in [PC])")
        get_success_data(api.verify_participant_attributes(
            ctx["participant"]["id"], ["PS5"], ADMIN))
        approved = approve_application(ctx["application"]["id"])
        # Verified variant: verified [PS5] against required [PC] -> 0 platform.
        assert approved["fit_score_final"] == 70, (
            "verified variant: 40 age + 30 region + 0 platform")
        assert approved["fit_score_final"] != ctx["application"]["fit_score_provisional"]

    def test_approve_pins_published_nda_on_success(self, api):
        """PRD §3.2: "On success the application moves `UNDER_REVIEW` →
        `APPROVED`, its `pinned_nda_agreement_id` is set to the published
        agreement's `id`, and a `PENDING` NDA signature is created for the
        participant on that agreement with an `expires_at` seven days out."

        Design: Difficulty/dual_variant_calc/screening_fit_provisional_vs_verified
        """
        set_clock()
        ctx = _setup_under_review(email="dv1-p@x.com", platform_tags=["PC", "PS5"])
        get_success_data(api.verify_participant_attributes(
            ctx["participant"]["id"], ["PS5"], ADMIN))
        approved = approve_application(ctx["application"]["id"])
        assert approved["status"] == "APPROVED"
        assert approved["pinned_nda_agreement_id"] == ctx["nda"]["id"]
        sig = get_pending_signature(ctx["participant"]["id"])
        assert sig["agreement_id"] == ctx["nda"]["id"]
        assert sig["application_id"] == ctx["application"]["id"]


class TestInfoRequestCycle:
    def test_info_request_cycle_repeats_without_limit(self, api):
        """PRD §3.2: "Requesting more information moves `UNDER_REVIEW` →
        `INFO_REQUESTED` and records the request's `info_request_note`; the
        owning participant answers through the submit-info action — optionally
        attaching a `supplemental_note` — which returns the application
        `INFO_REQUESTED` → `UNDER_REVIEW`. That cycle may repeat without limit."

        Design: Difficulty/non_linear_state_machine/application_info_request_cycle
        """
        ctx = _setup_under_review(email="nl1-p@x.com")
        pid = ctx["participant"]["id"]
        app_id = ctx["application"]["id"]
        st1 = get_success_data(api.request_app_info(app_id, "Confirm your region",
                                                    RESEARCHER))
        assert st1["status"] == "INFO_REQUESTED"
        assert st1["info_request_note"] == "Confirm your region"
        st2 = get_success_data(api.submit_app_info(
            app_id, make_participant_headers(pid), supplemental_note="Region confirmed US-W"))
        assert st2["status"] == "UNDER_REVIEW", "first loop iteration closed"
        st3 = get_success_data(api.request_app_info(app_id, "Confirm your platform",
                                                    RESEARCHER))
        assert st3["status"] == "INFO_REQUESTED", "the cycle repeats without limit"
        st4 = get_success_data(api.submit_app_info(app_id, make_participant_headers(pid)))
        assert st4["status"] == "UNDER_REVIEW"

    def test_application_still_approves_after_info_cycles(self, api):
        """PRD §3.2: "That cycle may repeat without limit."
        PRD §3.2: "On success the application moves `UNDER_REVIEW` → `APPROVED`"

        Design: Difficulty/non_linear_state_machine/application_info_request_cycle
        """
        ctx = _setup_under_review(email="nl1-p@x.com")
        pid = ctx["participant"]["id"]
        app_id = ctx["application"]["id"]
        for note in ("Confirm your region", "Confirm your platform"):
            get_success_data(api.request_app_info(app_id, note, RESEARCHER))
            get_success_data(api.submit_app_info(app_id, make_participant_headers(pid)))
        approved = approve_application(app_id)
        assert approved["status"] == "APPROVED", (
            "the info cycle does not poison the application")
        # verified_platform_tags still []: 40 age + 30 region + 0 platform.
        assert approved["fit_score_final"] == 70


def test_fit_score_partial_match_blocks_approval(api):
    """PRD §3.2: "The age component contributes 40 points when the
    participant's `age_years` falls within the study's `min_age`–`max_age`
    band, both bounds inclusive, and 0 otherwise. The region component
    contributes 30 points when the participant's `region_code` appears in the
    study's `allowed_regions`, and 0 otherwise."
    PRD §3.2: "and only then is the verified fit score computed, stored as
    `fit_score_final`, and compared against the pass mark of 60 — a score below
    60 is rejected with `ERR_FIT_SCORE_BELOW_THRESHOLD`."

    Design: Corner/calculations/fit_score_partial_match_below_threshold
    """
    ctx = _setup_under_review(email="calc1-p@x.com", age_years=40,
                              region_code="US-E", platform_tags=["PC"])
    # provisional: 0 age (40 out of 18..35) + 0 region (US-E) + 30 platform.
    assert ctx["application"]["fit_score_provisional"] == 30
    resp = api.approve_application(ctx["application"]["id"], RESEARCHER)
    validate_error(resp, ApiErrorId.ERR_FIT_SCORE_BELOW_THRESHOLD)
    current = get_success_data(api.get_application(ctx["application"]["id"], RESEARCHER))
    assert current["status"] == "UNDER_REVIEW", "a rejected approve changes no state"


def test_fit_threshold_exactly_60_approves(api):
    """PRD §3.2: "and only then is the verified fit score computed, stored as
    `fit_score_final`, and compared against the pass mark of 60 — a score below
    60 is rejected with `ERR_FIT_SCORE_BELOW_THRESHOLD`."
    PRD §3.2: "otherwise it contributes 30 points scaled by the fraction of the
    study's required platforms present in the relevant platform-tag set,
    rounded half-up to a whole number."

    Design: Corner/calculations/fit_threshold_exactly_60_approves
    """
    ctx = _setup_under_review(
        email="calc2-p@x.com", age_years=25, region_code="US-E",
        platform_tags=["PC", "PS5"],
        study_overrides={"required_platforms": ["PC", "PS5", "XB"]})
    # 40 age + 0 region + round(30 * 2/3) = 20 platform = 60, both variants.
    assert ctx["application"]["fit_score_provisional"] == 60
    get_success_data(api.verify_participant_attributes(
        ctx["participant"]["id"], ["PC", "PS5"], ADMIN))
    approved = approve_application(ctx["application"]["id"])
    assert approved["fit_score_final"] == 60, "exactly 60 meets the pass mark"
    assert approved["status"] == "APPROVED"


def test_duplicate_application_rejected(api):
    """PRD §3.2: "at most one application per study and participant may exist
    in `SUBMITTED`, `UNDER_REVIEW`, `INFO_REQUESTED`, `APPROVED`, or
    `ENROLLED`, so a prior `REJECTED` or `WITHDRAWN` application never blocks
    a fresh one — violations are `ERR_DUPLICATE_APPLICATION`."

    Design: Corner/validations/duplicate_application_rejected
    """
    study = create_study(code="DUP1")
    participant = register_participant(email="dup1-p@x.com")
    first = apply_to_study(study["id"], participant["id"])
    assert first["status"] == "SUBMITTED"
    resp = api.create_application({"study_id": study["id"]},
                                  make_participant_headers(participant["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPLICATION)


def test_cohort_full_at_capacity_boundary_rejected(api):
    """PRD §3.2: "the cohort must have room, meaning `enrolled_count` is
    strictly below `cohort_capacity` with equality meaning full
    (`ERR_COHORT_FULL`)"

    Design: Corner/validations/cohort_full_at_capacity_boundary_rejected
    """
    study, _nda = setup_study_with_published_nda(code="CAP1", cohort_capacity=1)
    pa = register_participant(email="cap-a@x.com")
    enroll_participant(study["id"], pa)
    assert get_success_data(api.get_study(study["id"], ADMIN))["enrolled_count"] == 1
    pb = register_participant(email="cap-b@x.com", age_years=27)
    app_b = start_review(apply_to_study(study["id"], pb["id"])["id"])
    resp = api.approve_application(app_b["id"], RESEARCHER)
    validate_error(resp, ApiErrorId.ERR_COHORT_FULL)
    current = get_success_data(api.get_application(app_b["id"], RESEARCHER))
    assert current["status"] == "UNDER_REVIEW"


def test_approve_without_published_nda_rejected(api):
    """PRD §3.2: "a `PUBLISHED` NDA agreement must exist for the study — at
    most one can exist at a time by the publish rule of §3.3 — else
    `ERR_NDA_NOT_PUBLISHED`"

    Design: Corner/validations/approve_without_published_nda_rejected
    """
    ctx = _setup_under_review(email="nd0-p@x.com", publish_nda=False)
    assert ctx["nda"]["status"] == "DRAFT"
    resp = api.approve_application(ctx["application"]["id"], RESEARCHER)
    validate_error(resp, ApiErrorId.ERR_NDA_NOT_PUBLISHED)


def test_approve_after_recruitment_close_rejected(api):
    """PRD §3.2: "The application must be `UNDER_REVIEW`; the study must still
    be `RECRUITING` (`ERR_STUDY_NOT_RECRUITING`)"
    PRD §2.9: "`ERR_STUDY_NOT_RECRUITING` for an application create or approve
    against a study that is not `RECRUITING`"

    Design: Corner/validations/approve_after_recruitment_close_rejected
    """
    ctx = _setup_under_review(email="arc-p@x.com")
    close_study(ctx["study"]["id"])
    resp = api.approve_application(ctx["application"]["id"], RESEARCHER)
    validate_error(resp, ApiErrorId.ERR_STUDY_NOT_RECRUITING)


def test_apply_while_registered_rejected(api):
    """PRD §3.2: "The study must be `RECRUITING` (`ERR_STUDY_NOT_RECRUITING`),
    the applicant must be `ACTIVE` (`ERR_PARTICIPANT_NOT_ACTIVE`)"
    PRD §3.1: "only `ACTIVE` participants may apply to studies."

    Design: Corner/validations/apply_while_registered_rejected
    """
    study = create_study(code="REG1")
    participant = register_participant(email="reg-p@x.com", active=False)
    assert participant["status"] == "REGISTERED"
    resp = api.create_application({"study_id": study["id"]},
                                  make_participant_headers(participant["id"]))
    validate_error(resp, ApiErrorId.ERR_PARTICIPANT_NOT_ACTIVE)


def test_approve_withdrawn_application_returns_invalid_state(api):
    """PRD §3.2: "Withdrawal moves an application `SUBMITTED` → `WITHDRAWN` or
    `UNDER_REVIEW` → `WITHDRAWN`; either way it is terminal."
    PRD §3.2: "The application must be `UNDER_REVIEW`"
    PRD §2.9: "The generic rejection is `ERR_INVALID_STATE`"

    Design: Corner/state_machines/approve_withdrawn_application_returns_invalid_state
    """
    study = create_study(code="IV2")
    participant = register_participant(email="iv2-p@x.com")
    app = apply_to_study(study["id"], participant["id"])
    withdrawn = get_success_data(api.withdraw_application(
        app["id"], make_participant_headers(participant["id"])))
    assert withdrawn["status"] == "WITHDRAWN"
    resp = api.approve_application(app["id"], RESEARCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_approve_creates_pending_signature_side_effect(api):
    """PRD §3.2: "On success the application moves `UNDER_REVIEW` → `APPROVED`,
    its `pinned_nda_agreement_id` is set to the published agreement's `id`, and
    a `PENDING` NDA signature is created for the participant on that agreement
    with an `expires_at` seven days out."
    PRD §3.3: "It is created `PENDING` with `expires_at` set to its creation
    instant plus seven days."

    Design: Corner/state_machines/approve_creates_pending_signature_side_effect
    """
    set_clock("2026-08-01T00:00:00Z")
    ctx = _setup_under_review(email="se1-p@x.com")
    approved = approve_application(ctx["application"]["id"])
    assert approved["pinned_nda_agreement_id"] == ctx["nda"]["id"]
    sig = get_pending_signature(ctx["participant"]["id"])
    assert sig["agreement_id"] == ctx["nda"]["id"]
    assert sig["application_id"] == ctx["application"]["id"]
    assert sig["status"] == "PENDING"
    delta = parse_instant(sig["expires_at"]) - parse_instant(sig["created_at"])
    assert delta == timedelta(days=7), "expires_at is the creation instant plus 7 days"
    assert_instant_equals(sig["expires_at"], "2026-08-08T00:00:00Z", "expires_at")
