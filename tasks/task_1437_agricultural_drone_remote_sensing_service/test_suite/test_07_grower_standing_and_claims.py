"""Grower account-standing cascades and the insurance-claim liability cap
(PRD sections 3.8 and 2.9)."""
from test_helpers import (
    ADMIN,
    ADJUSTER,
    ApiErrorId,
    api_client,
    approve_claim,
    assert_claim,
    create_claim,
    create_field,
    create_mission,
    create_mission_authorized,
    create_mission_in_flight,
    deny_claim,
    get_mission,
    open_claim_review,
    setup_completed_mission_scenario,
    setup_ops,
    validate_error,
    validate_success,
)


class TestSuspensionCascade:

    def test_suspend_cancels_planned_and_authorized_missions(self):
        """PRD section 3.8: "Suspending a grower requires the grower to be
        `ACTIVE` (else `ERR_GROWER_NOT_ACTIVE`); the grower drops to
        `SUSPENDED`, every `PLANNED` or `AUTHORIZED` mission on that grower's
        fields is cancelled in the same transaction, and the grower's
        `version` increments."

        Design: Difficulty/transitive_cascade/grower_suspend_cascades_to_missions
        """
        ctx = setup_ops()
        field2 = create_field(ctx["grower"]["id"], field_name="F2")
        m1 = create_mission(
            ctx["field"]["id"], ctx["pilot"]["id"],
            scheduled_start="2026-06-05T08:00:00Z",
            scheduled_end="2026-06-05T10:00:00Z", acres_planned=50)
        m2 = create_mission_authorized(
            field2["id"], ctx["pilot"]["id"],
            scheduled_start="2026-06-06T08:00:00Z",
            scheduled_end="2026-06-06T10:00:00Z", acres_planned=50)
        resp = api_client.suspend_grower(ctx["grower"]["id"], ADMIN)
        suspended = validate_success(resp, expected_status=200)
        assert suspended["status"] == "SUSPENDED"
        assert get_mission(m1["id"])["status"] == "CANCELLED", \
            "PLANNED mission must be cancelled by suspension"
        assert get_mission(m2["id"])["status"] == "CANCELLED", \
            "AUTHORIZED mission must be cancelled by suspension"

    def test_suspend_does_not_cancel_in_flight_mission(self):
        """PRD section 3.8: "Suspending a grower requires the grower to be
        `ACTIVE` (else `ERR_GROWER_NOT_ACTIVE`); the grower drops to
        `SUSPENDED`, every `PLANNED` or `AUTHORIZED` mission on that grower's
        fields is cancelled in the same transaction, and the grower's
        `version` increments."
        PRD section 3.8: "Termination is final and also requires `SUSPENDED`
        (else `ERR_GROWER_NOT_SUSPENDED`), with one additional hard gate: no
        mission on any of the grower's fields may currently be `IN_FLIGHT`".

        Design: Difficulty/transitive_cascade/grower_suspend_cascades_to_missions
        """
        ctx = setup_ops()
        m3 = create_mission_in_flight(
            ctx["field"]["id"], ctx["pilot"]["id"],
            start="2026-06-02T08:00:00Z", end="2026-06-02T10:00:00Z",
            launch_time="2026-06-02T08:30:00Z", acres_planned=50)
        validate_success(api_client.suspend_grower(ctx["grower"]["id"], ADMIN))
        after = get_mission(m3["id"])
        assert after["status"] == "IN_FLIGHT", \
            f"IN_FLIGHT missions are not cancelled by suspension, got {after['status']}"


class TestTerminationGate:

    def test_grower_terminate_with_in_flight_mission_blocked(self):
        """PRD section 3.8: "Termination is final and also requires
        `SUSPENDED` (else `ERR_GROWER_NOT_SUSPENDED`), with one additional
        hard gate: no mission on any of the grower's fields may currently be
        `IN_FLIGHT`, or the termination is blocked with
        `ERR_MISSION_IN_FLIGHT`."

        Design: Corner/state_machines/grower_terminate_with_in_flight_mission_blocked
        """
        ctx = setup_ops()
        create_mission_in_flight(
            ctx["field"]["id"], ctx["pilot"]["id"],
            start="2026-06-02T08:00:00Z", end="2026-06-02T10:00:00Z",
            launch_time="2026-06-02T08:30:00Z", acres_planned=10)
        validate_success(api_client.suspend_grower(ctx["grower"]["id"], ADMIN))
        resp = api_client.terminate_grower(ctx["grower"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_MISSION_IN_FLIGHT)


class TestClaimLifecycle:

    def test_grower_can_submit_claim_for_own_mission(self):
        """PRD section 3.8: "A `Grower` submits a claim against their own
        record, naming the `mission_id` on which the loss occurred and the
        `claim_amount_cents` sought — a positive integer, or the submission
        fails as `ERR_INVALID_REQUEST`. The claim is born `SUBMITTED` with
        `approved_amount_cents` at zero."

        Design: Corner/roles/grower_can_submit_claim_for_own_mission
        """
        ctx, mission = setup_completed_mission_scenario(
            acres_planned=10, acres_flown=10)
        claim = create_claim(ctx["grower"]["id"], mission["id"], 5000)
        assert_claim(claim)
        assert claim["status"] == "SUBMITTED"
        assert claim["approved_amount_cents"] == 0
        assert claim["grower_id"] == ctx["grower"]["id"]
        assert claim["mission_id"] == mission["id"]

    def test_terminal_claim_cannot_be_reopened(self):
        """PRD section 3.8: "Denial, likewise from `UNDER_REVIEW`, moves the
        claim to `DENIED` with `approved_amount_cents` zeroed."
        PRD section 3.8: "A `ClaimsAdjuster` then opens review — only on a
        `SUBMITTED` claim, else `ERR_CLAIM_NOT_SUBMITTED`".

        Design: Corner/state_machines/terminal_claim_cannot_be_reopened
        """
        ctx, mission = setup_completed_mission_scenario(
            acres_planned=10, acres_flown=10)
        claim = create_claim(ctx["grower"]["id"], mission["id"], 1000)
        open_claim_review(claim["id"])
        deny_claim(claim["id"])
        resp = api_client.open_claim_review(claim["id"], ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_SUBMITTED)


class TestLiabilityCapInvariant:

    def test_approve_beyond_remaining_cap_rejected(self):
        """PRD section 3.8: "Approval, from `UNDER_REVIEW` (else
        `ERR_CLAIM_NOT_UNDER_REVIEW`), requires the referenced mission to be
        final — `COMPLETED` or `WEATHER_ABORTED`, anything earlier drawing
        `ERR_CLAIM_MISSION_NOT_FINAL` — and takes an `amount_cents` that must
        be positive and, added to the running total of already approved or
        paid amounts across all claims on the same mission, must not exceed
        the grower's `liability_coverage_cents`; a request that breaches the
        cap is `ERR_CLAIM_EXCEEDS_COVERAGE`."

        Design: Difficulty/compensating_invariant/claim_approve_pay_conserves_liability_cap
        """
        ctx, mission = setup_completed_mission_scenario(
            acres_planned=50, acres_flown=50)
        # Grower liability cap is the factory default 50,000,000 cents.
        c1 = create_claim(ctx["grower"]["id"], mission["id"], 40_000_000)
        open_claim_review(c1["id"])
        approve_claim(c1["id"], 40_000_000)
        c2 = create_claim(ctx["grower"]["id"], mission["id"], 20_000_000)
        open_claim_review(c2["id"])
        # 40,000,000 already approved; +20,000,000 would breach the cap.
        resp = api_client.approve_claim(
            c2["id"], {"amount_cents": 20_000_000}, ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_CLAIM_EXCEEDS_COVERAGE)
        # No state drift: both claims unchanged.
        c2_after = validate_success(api_client.get_claim(c2["id"], ADJUSTER))
        assert c2_after["status"] == "UNDER_REVIEW"
        assert c2_after["approved_amount_cents"] == 0
        c1_after = validate_success(api_client.get_claim(c1["id"], ADJUSTER))
        assert c1_after["status"] == "APPROVED"
        assert c1_after["approved_amount_cents"] == 40_000_000

    def test_approve_exactly_at_remaining_cap_succeeds(self):
        """PRD section 3.8: "Approval, from `UNDER_REVIEW` (else
        `ERR_CLAIM_NOT_UNDER_REVIEW`), requires the referenced mission to be
        final — `COMPLETED` or `WEATHER_ABORTED`, anything earlier drawing
        `ERR_CLAIM_MISSION_NOT_FINAL` — and takes an `amount_cents` that must
        be positive and, added to the running total of already approved or
        paid amounts across all claims on the same mission, must not exceed
        the grower's `liability_coverage_cents`; a request that breaches the
        cap is `ERR_CLAIM_EXCEEDS_COVERAGE`."

        Design: Difficulty/compensating_invariant/claim_approve_pay_conserves_liability_cap
        """
        ctx, mission = setup_completed_mission_scenario(
            acres_planned=50, acres_flown=50)
        c1 = create_claim(ctx["grower"]["id"], mission["id"], 40_000_000)
        open_claim_review(c1["id"])
        approve_claim(c1["id"], 40_000_000)
        c2 = create_claim(ctx["grower"]["id"], mission["id"], 10_000_000)
        open_claim_review(c2["id"])
        # 40,000,000 + 10,000,000 == 50,000,000 cap exactly: does not exceed.
        approved = approve_claim(c2["id"], 10_000_000)
        assert approved["status"] == "APPROVED"
        assert approved["approved_amount_cents"] == 10_000_000
