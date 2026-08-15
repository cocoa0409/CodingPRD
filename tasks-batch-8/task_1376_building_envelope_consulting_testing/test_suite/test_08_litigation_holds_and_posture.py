"""Litigation holds, FROZEN posture gating, and validation priority."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_litigation_hold,
    create_active_engagement,
    create_anomaly,
    create_assembly,
    create_completed_survey,
    create_design_review,
    create_litigation_hold,
    drive_review_through_cycle,
    get_engagement,
    make_principal_headers,
    make_reviewer_headers,
    setup_field_test_recorded,
    start_review,
    validate_error,
    validate_success,
)

P = TEST_USERS["principal_headers"]
C = TEST_USERS["consultant_headers"]


class TestLitigationHoldThawCascade:

    def _setup_hold_with_submitted_review(self):
        eng = create_active_engagement(name="E8")
        asm = create_assembly(eng["id"], tag="W8", assembly_type="MASONRY",
                              design_u_factor=1.4,
                              required_airtightness_lps_m2=2.0)
        rev = create_design_review(eng["id"], asm["id"], barrier_scope=["AIR"],
                                   drawing_count=4)
        hold = create_litigation_hold(eng["id"], "CASE-2026-001")
        return eng, rev, hold

    def test_release_thaws_posture_and_unlocks_review(self):
        """PRD §3.9: "Releasing the hold, also a `Principal` act, moves it from
        `ACTIVE` to `RELEASED` — any other state is rejected with
        `ERR_HOLD_NOT_ACTIVE` (HTTP 409) — clears `litigation_hold_active` to
        false (assuming no other active hold), re-derives the posture so the
        engagement may thaw to `RESTRICTED` or `OPEN`, and increments the
        engagement's `version` by 1."
        PRD §2.5: "A `FROZEN` posture blocks seven operational mutations, each
        rejected with `ERR_ENGAGEMENT_FROZEN` (HTTP 409): starting a design
        review round, ..."

        Design: Difficulty/transitive_cascade/litigation_hold_release_thaws_posture_unlocks_ops
        """
        eng, rev, hold = self._setup_hold_with_submitted_review()
        frozen = get_engagement(eng["id"])
        assert frozen["posture"] == "FROZEN"
        assert frozen["litigation_hold_active"] is True

        resp = api_client.start_review(eng["id"], rev["id"],
                                       make_reviewer_headers("rev-user-1"))
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_FROZEN)

        resp = api_client.release_litigation_hold(eng["id"], hold["id"], P)
        released = validate_success(resp, 200)
        assert released["hold_status"] == "RELEASED"

        thawed = get_engagement(eng["id"])
        assert thawed["litigation_hold_active"] is False
        assert thawed["posture"] == "OPEN"

        resp = api_client.start_review(eng["id"], rev["id"],
                                       make_reviewer_headers("rev-user-1"))
        data = validate_success(resp, 200)
        assert data["status"] == "UNDER_REVIEW"

    def test_second_active_hold_keeps_engagement_frozen(self):
        """PRD §3.9: "Releasing the hold, also a `Principal` act, moves it from
        `ACTIVE` to `RELEASED` — any other state is rejected with
        `ERR_HOLD_NOT_ACTIVE` (HTTP 409) — clears `litigation_hold_active` to
        false (assuming no other active hold), re-derives the posture so the
        engagement may thaw to `RESTRICTED` or `OPEN`..."
        PRD §2.5: "If the engagement's `litigation_hold_active` flag is true,
        the posture is `FROZEN`."

        Design: Difficulty/transitive_cascade/litigation_hold_release_thaws_posture_unlocks_ops
        """
        eng = create_active_engagement(name="E8B")
        h1 = create_litigation_hold(eng["id"], "CASE-2026-002")
        h2 = create_litigation_hold(eng["id"], "CASE-2026-003")
        resp = api_client.release_litigation_hold(eng["id"], h1["id"], P)
        validate_success(resp, 200)
        mid = get_engagement(eng["id"])
        assert mid["litigation_hold_active"] is True
        assert mid["posture"] == "FROZEN"
        resp = api_client.release_litigation_hold(eng["id"], h2["id"], P)
        validate_success(resp, 200)
        thawed = get_engagement(eng["id"])
        assert thawed["litigation_hold_active"] is False
        assert thawed["posture"] == "OPEN"


class TestValidationPriorityStateBeatsSafety:

    def test_frozen_certify_by_performer_reports_frozen(self):
        """PRD §2.11: "When a request violates more than one rule, the error it
        receives is determined by a fixed evaluation order rather than by
        whichever check happens to run first." — tier 6 covers "The posture
        gates: a `FROZEN` posture blocks the operational mutations enumerated
        in §2.5 with `ERR_ENGAGEMENT_FROZEN`...", ahead of tier 8's
        "Segregation of duties — `ERR_DUTY_SEGREGATION_VIOLATION`."
        PRD §2.5: "A `FROZEN` posture blocks seven operational mutations, each
        rejected with `ERR_ENGAGEMENT_FROZEN` (HTTP 409): ... certifying a
        field test..."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_frozen_certify_by_performer
        """
        # PASS result recorded by tech-user-1, then the engagement freezes.
        eng, asm, ft = setup_field_test_recorded(
            measured=1.0, name="E9", tag="W9",
            test_pressure_pa=75, required_airtightness_lps_m2=2.0,
            tech_user="tech-user-1")
        assert ft["result"] == "PASS"
        create_litigation_hold(eng["id"], "CASE-2026-009")
        assert get_engagement(eng["id"])["posture"] == "FROZEN"
        # The caller is simultaneously the performer (duty violation) — but
        # the posture gate is the earlier tier.
        resp = api_client.certify_field_test(
            eng["id"], ft["id"], make_principal_headers("tech-user-1"))
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_FROZEN)

    def test_restricted_approve_by_comment_issuer_reports_posture(self):
        """PRD §2.11: "A design-review approval attempted by the same reviewer
        who issued the round's comments, on an engagement whose posture is
        `RESTRICTED`, surfaces `ERR_POSTURE_NOT_OPEN` from tier 6 rather than
        the segregation violation from tier 8."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_frozen_certify_by_performer
        """
        eng = create_active_engagement(name="E9B")
        asm = create_assembly(eng["id"], tag="W9B",
                              required_airtightness_lps_m2=2.0)
        rev = create_design_review(eng["id"], asm["id"], barrier_scope=["AIR"],
                                   drawing_count=3)
        start_review(eng["id"], rev["id"], "rev-user-1")
        # One full cycle: revision_round == 1, comment issuer rev-user-1.
        drive_review_through_cycle(eng["id"], rev["id"], "rev-user-1")
        # An OPEN anomaly flips the posture to RESTRICTED.
        srv = create_completed_survey(eng["id"], asm["id"])
        create_anomaly(eng["id"], anomaly_type="MOISTURE_TRAP", severity="LOW",
                       description="open", survey_id=srv["id"])
        assert get_engagement(eng["id"])["posture"] == "RESTRICTED"
        resp = api_client.approve_review(eng["id"], rev["id"],
                                         make_reviewer_headers("rev-user-1"))
        validate_error(resp, ApiErrorId.ERR_POSTURE_NOT_OPEN)


class TestLitigationHoldShape:

    def test_litigation_hold_immutable_no_version_field(self):
        """PRD §2.10: "Two resource types deliberately carry a reduced property
        set: a **LitigationHold** and an **Invoice** each expose only `id` and
        `created_at`. Neither has `updated_at` nor `version` — a released hold
        and a finalized invoice are immutable audit records, and the absence of
        the mutation-tracking fields reflects that."
        PRD §3.9: "The hold is created with its `hold_status` at `ACTIVE`; in
        the same act the engagement's `litigation_hold_active` flag becomes
        true, the posture derivation of §2.5 drives the engagement to
        `FROZEN`..."

        Design: Corner/entities/litigation_hold_immutable_no_version_field
        """
        eng = create_active_engagement(name="EH")
        resp = api_client.create_litigation_hold(
            eng["id"], {"matter_reference": "CASE-X"}, P)
        data = validate_success(resp, 201)
        assert_litigation_hold(data)
        assert data["hold_status"] == "ACTIVE"
        assert "version" not in data
        assert "updated_at" not in data
        assert get_engagement(eng["id"])["posture"] == "FROZEN"
