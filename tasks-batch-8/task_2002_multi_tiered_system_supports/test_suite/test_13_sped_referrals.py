"""Special-education referrals: the probe-driven auto-creation cascade, the
weeks-unresponsive precondition, and the post-referral lifecycle (PRD §3.6, §3.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_sped_referral,
    committed_minutes,
    get_plan,
    get_student,
    list_referrals,
    probe_until_sped_referral,
    record_consent_payload,
    record_weekly_probes,
    setup_active_plan,
    setup_student_with_ratified_tier,
    validate_error,
    validate_success,
)

LEAD = TEST_USERS["team_lead_headers"]
SPED = TEST_USERS["sped_director_headers"]


def _tier3_plan_ctx(api, sped_referral_min_weeks):
    """Student ratified at TIER_3 (raw 50 bands TIER_3 with cuts 100/70) running
    an ACTIVE TIER_3 plan costing 60 x 5 = 300 weekly minutes."""
    return setup_active_plan(api, tier="TIER_3", raw_score=50,
                             session_minutes=60, sessions_per_week=5,
                             weekly_minute_capacity=1200,
                             sped_referral_min_weeks=sped_referral_min_weeks)


class TestProbeCascadeCreatesReferral:
    def test_probe_cascade_creates_referral_and_exits_plan(self, api):
        """PRD §3.6: "When the plan's `tier_at_start` is `TIER_3` and the new
        decision is `NON_RESPONSIVE`, the student's `weeks_at_tier3_unresponsive`
        increments by one; any `RESPONSIVE` decision resets it to zero."
        PRD §3.6: "When the counter reaches the district's
        `sped_referral_min_weeks` and no open referral exists for the student,
        the system acts on its own: it creates a special-education referral in
        `PENDING_CONSENT` status and cascades the plan to `EXIT_SPED_REFERRAL`,
        releasing the plan's committed minutes."
        PRD §3.9: "Either way, creation records the student's current `ACTIVE`
        plan as the `triggered_plan_id`, cascades that plan to
        `EXIT_SPED_REFERRAL` with its committed minutes released, and sets the
        referral's `status` to `PENDING_CONSENT` with `consent_received_on` still
        null."

        With sped_referral_min_weeks=2, flat probes (score 50 against a rising
        aimline) push the counter to the minimum; the cascade then fires from
        the probe write itself.

        Design: Difficulty/transitive_cascade/probe_non_responsive_cascades_to_sped_referral
        """
        ctx = _tier3_plan_ctx(api, sped_referral_min_weeks=2)
        d_id, s_id = ctx["district"]["id"], ctx["school"]["id"]
        st_id, plan_id = ctx["student"]["id"], ctx["plan"]["id"]
        assert committed_minutes(api, ctx) == 300

        referrals = probe_until_sped_referral(api, ctx, max_probes=3, score=50)
        assert len(referrals) == 1, "the system auto-creates exactly one referral"
        referral = referrals[0]
        assert_sped_referral(referral)
        assert referral["status"] == "PENDING_CONSENT"
        assert referral["triggered_plan_id"] == plan_id
        assert referral["consent_received_on"] is None

        plan = get_plan(api, d_id, s_id, st_id, plan_id)
        assert plan["status"] == "EXIT_SPED_REFERRAL"
        assert committed_minutes(api, ctx) == 0, (
            "the referral cascade releases the plan's 300 committed minutes")

    def test_responsive_probe_resets_unresponsive_counter(self, api):
        """PRD §3.6: "When the plan's `tier_at_start` is `TIER_3` and the new
        decision is `NON_RESPONSIVE`, the student's `weeks_at_tier3_unresponsive`
        increments by one; any `RESPONSIVE` decision resets it to zero."

        Two flat probes build the counter up; a sharply rising third probe
        (score slope 35 against aimline slope 6.5 over the trailing window)
        resets it to zero. The district minimum stays at its default of 12, so
        no referral can fire.

        Design: Difficulty/transitive_cascade/probe_non_responsive_cascades_to_sped_referral
        """
        ctx = _tier3_plan_ctx(api, sped_referral_min_weeks=None)
        d_id, s_id = ctx["district"]["id"], ctx["school"]["id"]
        st_id = ctx["student"]["id"]

        record_weekly_probes(api, ctx, [50, 50], first_date="2026-08-12")
        mid = get_student(api, d_id, s_id, st_id)
        assert mid["weeks_at_tier3_unresponsive"] >= 1, (
            "non-responsive probes at TIER_3 build the counter")

        record_weekly_probes(api, ctx, [120], first_date="2026-08-26")
        after = get_student(api, d_id, s_id, st_id)
        assert after["weeks_at_tier3_unresponsive"] == 0, (
            "a RESPONSIVE decision resets the counter to zero")


class TestReferralPreconditionBoundary:
    def test_referral_below_min_weeks_rejected(self, api):
        """PRD §3.9: "A `TeamLead` or a `SpEdDirector` may open one manually; the
        preconditions are that the student's `current_tier` is `TIER_3`, that
        `weeks_at_tier3_unresponsive` has reached the district's
        `sped_referral_min_weeks`, and that no other open referral — one in
        `PENDING_CONSENT`, `CONSENTED`, or `EVAL_IN_PROGRESS` — exists for the
        student."
        PRD §3.9: "A request failing any of these is rejected with
        `ERR_SPED_REFERRAL_PRECONDITION` (HTTP 422)."

        With the district minimum at 4, three non-responsive probes leave the
        counter below the threshold, so the manual referral is rejected.

        Design: Difficulty/boundary_precision_check/sped_referral_min_weeks_boundary
        """
        ctx = _tier3_plan_ctx(api, sped_referral_min_weeks=4)
        record_weekly_probes(api, ctx, [50, 50, 50], first_date="2026-08-12")
        student = get_student(api, ctx["district"]["id"], ctx["school"]["id"],
                              ctx["student"]["id"])
        assert student["weeks_at_tier3_unresponsive"] < 4
        assert list_referrals(api, ctx) == []

        resp = api.create_sped_referral(ctx["district"]["id"],
                                        ctx["school"]["id"],
                                        ctx["student"]["id"], SPED)
        validate_error(resp, ApiErrorId.ERR_SPED_REFERRAL_PRECONDITION, 422)

    def test_referral_auto_created_when_counter_reaches_minimum(self, api):
        """PRD §3.6: "When the counter reaches the district's
        `sped_referral_min_weeks` and no open referral exists for the student,
        the system acts on its own: it creates a special-education referral in
        `PENDING_CONSENT` status and cascades the plan to `EXIT_SPED_REFERRAL`,
        releasing the plan's committed minutes."
        PRD §3.9: "A `TeamLead` or a `SpEdDirector` may open one manually; the
        preconditions are that the student's `current_tier` is `TIER_3`, that
        `weeks_at_tier3_unresponsive` has reached the district's
        `sped_referral_min_weeks`, and that no other open referral — one in
        `PENDING_CONSENT`, `CONSENTED`, or `EVAL_IN_PROGRESS` — exists for the
        student."

        The boundary is inclusive on the qualifying side: with the district
        minimum at 4, the probe that brings the counter to 4 fires the cascade.

        Design: Difficulty/boundary_precision_check/sped_referral_min_weeks_boundary
        """
        ctx = _tier3_plan_ctx(api, sped_referral_min_weeks=4)
        d_id, s_id = ctx["district"]["id"], ctx["school"]["id"]
        st_id = ctx["student"]["id"]

        referrals = probe_until_sped_referral(api, ctx, max_probes=5, score=50)
        assert len(referrals) == 1
        assert referrals[0]["status"] == "PENDING_CONSENT"
        student = get_student(api, d_id, s_id, st_id)
        assert student["weeks_at_tier3_unresponsive"] >= 4, (
            "the counter has reached the district minimum")
        plan = get_plan(api, d_id, s_id, st_id, ctx["plan"]["id"])
        assert plan["status"] == "EXIT_SPED_REFERRAL"


class TestReferralStudentPreconditions:
    def test_referral_rejected_for_tier2_student(self, api):
        """PRD §3.9: "A `TeamLead` or a `SpEdDirector` may open one manually; the
        preconditions are that the student's `current_tier` is `TIER_3`, that
        `weeks_at_tier3_unresponsive` has reached the district's
        `sped_referral_min_weeks`, and that no other open referral — one in
        `PENDING_CONSENT`, `CONSENTED`, or `EVAL_IN_PROGRESS` — exists for the
        student."
        PRD §3.9: "A request failing any of these is rejected with
        `ERR_SPED_REFERRAL_PRECONDITION` (HTTP 422)."

        The student sits at TIER_2, so the precondition fails regardless of the
        counter.

        Design: Difficulty/cross_entity_state_dependency/sped_referral_requires_plan_active_and_tier3
        """
        ctx = setup_student_with_ratified_tier(api, target_tier="TIER_2",
                                               sped_referral_min_weeks=4)
        resp = api.create_sped_referral(ctx["district"]["id"],
                                        ctx["school"]["id"],
                                        ctx["student"]["id"], SPED)
        validate_error(resp, ApiErrorId.ERR_SPED_REFERRAL_PRECONDITION, 422)

    def test_second_open_referral_rejected(self, api):
        """PRD §3.9: "A `TeamLead` or a `SpEdDirector` may open one manually; the
        preconditions are that the student's `current_tier` is `TIER_3`, that
        `weeks_at_tier3_unresponsive` has reached the district's
        `sped_referral_min_weeks`, and that no other open referral — one in
        `PENDING_CONSENT`, `CONSENTED`, or `EVAL_IN_PROGRESS` — exists for the
        student."
        PRD §3.9: "A request failing any of these is rejected with
        `ERR_SPED_REFERRAL_PRECONDITION` (HTTP 422)."

        An auto-created PENDING_CONSENT referral is already open, so a manual
        open is rejected.

        Design: Difficulty/cross_entity_state_dependency/sped_referral_requires_plan_active_and_tier3
        """
        ctx = _tier3_plan_ctx(api, sped_referral_min_weeks=2)
        referrals = probe_until_sped_referral(api, ctx, max_probes=3, score=50)
        assert len(referrals) == 1 and referrals[0]["status"] == "PENDING_CONSENT"

        resp = api.create_sped_referral(ctx["district"]["id"],
                                        ctx["school"]["id"],
                                        ctx["student"]["id"], LEAD)
        validate_error(resp, ApiErrorId.ERR_SPED_REFERRAL_PRECONDITION, 422)


class TestReferralLifecycle:
    def test_withdraw_from_pending_consent(self, api):
        """PRD §3.9: "A referral may also be withdrawn, transitioning to
        `WITHDRAWN`, from either `PENDING_CONSENT` or `CONSENTED`."
        PRD §3.9: "Either way, creation records the student's current `ACTIVE`
        plan as the `triggered_plan_id`, cascades that plan to
        `EXIT_SPED_REFERRAL` with its committed minutes released, and sets the
        referral's `status` to `PENDING_CONSENT` with `consent_received_on` still
        null."

        Design: Corner/state_machines/sped_referral_withdrawal_from_pending_consent
        """
        ctx = _tier3_plan_ctx(api, sped_referral_min_weeks=2)
        referrals = probe_until_sped_referral(api, ctx, max_probes=3, score=50)
        referral = referrals[0]
        assert referral["status"] == "PENDING_CONSENT"

        withdrawn = validate_success(api.withdraw_referral(
            ctx["district"]["id"], ctx["school"]["id"], ctx["student"]["id"],
            referral["id"], SPED))
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["triggered_plan_id"] == ctx["plan"]["id"], (
            "the triggering plan stays pinned on the historical record")

    def test_record_consent_requires_sped_director(self, api):
        """PRD §2.1: "Access to every operation is restricted by role, and an
        attempt to act outside the caller's designated role is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §3.9: "From there, the `SpEdDirector` drives the lifecycle. Recording
        parent consent with a `consent_received_on` date moves the referral from
        `PENDING_CONSENT` to `CONSENTED` and sets `evaluation_due_on` to sixty
        calendar days after the consent date."
        PRD §4: POST
        `/districts/{districtId}/schools/{schoolId}/students/{studentId}/sped-referrals/{referralId}/record-consent`
        — "Record parent consent | SpEdDirector".

        TeamLead may open a referral but may not record consent.

        Design: Corner/rbac/sped_director_exclusive_record_consent
        """
        ctx = _tier3_plan_ctx(api, sped_referral_min_weeks=2)
        referrals = probe_until_sped_referral(api, ctx, max_probes=3, score=50)
        referral = referrals[0]

        resp = api.record_consent(
            ctx["district"]["id"], ctx["school"]["id"], ctx["student"]["id"],
            referral["id"], record_consent_payload("2026-09-10"), LEAD)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)
