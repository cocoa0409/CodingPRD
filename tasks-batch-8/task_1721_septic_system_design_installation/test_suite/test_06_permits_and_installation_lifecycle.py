"""Permit lifecycle, installation legs, expiry/suspension cascades, revocation."""
from test_helpers import (
    ApiErrorId,
    add_design,
    add_installation,
    add_permit,
    advance,
    advance_clock,
    api_client,
    approve_design,
    freeze_site,
    get_design,
    get_installation,
    get_permit,
    reinstate_permit_payload,
    revoke_permit_payload,
    schedule_inspection,
    setup_installation,
    setup_site_with_science,
    submit_design,
    validate_error,
    validate_success,
)


class TestPermitSuspendReinstateCycle:
    def test_suspend_cascades_installation_to_failed_hold(self, api):
        """PRD section 3.5: "A health officer may suspend it manually, and approval
        of a competing design suspends it automatically per §3.4; either path
        moves the permit from `ISSUED` to `SUSPENDED` and forces every
        installation it authorizes that sits in a non-terminal state — anywhere
        from `NOT_STARTED` through `READY_FOR_FINAL` — into `FAILED_HOLD`."

        Design: Difficulty/non_linear_state_machine/permit_suspend_reinstate_cycle_restores_installation_path
        """
        ctx = setup_installation(bedroom_count=3)
        advance(ctx)  # ROUGH_IN_PROGRESS
        suspended = validate_success(api_client.suspend_permit(
            ctx.cid, ctx.cu, ctx.s, ctx.p0, ctx.officer))
        assert suspended["status"] == "SUSPENDED"
        assert get_installation(ctx)["status"] == "FAILED_HOLD"

    def test_reinstate_restores_permit_but_not_installation(self, api):
        """PRD section 3.5: "A successful reinstatement bumps the permit's
        `version` by one."
        PRD section 3.5: "installations forced to `FAILED_HOLD` by the suspension
        are not restored; each one needs an explicit remediation action under
        §3.6."
        PRD section 3.6: "a `ProjectManager` may remediate — returning the
        installation to `READY_FOR_FINAL` for re-inspection under the standing
        permit-and-site guards above — or abandon it."

        Design: Difficulty/non_linear_state_machine/permit_suspend_reinstate_cycle_restores_installation_path
        """
        ctx = setup_installation(bedroom_count=3)
        advance(ctx)
        suspended = validate_success(api_client.suspend_permit(
            ctx.cid, ctx.cu, ctx.s, ctx.p0, ctx.officer))
        reinstated = validate_success(api_client.reinstate_permit(
            ctx.cid, ctx.cu, ctx.s, ctx.p0,
            reinstate_permit_payload(suspended["version"]), ctx.officer))
        assert reinstated["status"] == "ISSUED"
        assert reinstated["version"] == suspended["version"] + 1

        assert get_installation(ctx)["status"] == "FAILED_HOLD", (
            "the permit cycle does not auto-restore the installation")
        remediated = validate_success(api_client.remediate_installation(
            ctx.cid, ctx.cu, ctx.s, ctx.i0, ctx.manager))
        assert remediated["status"] == "READY_FOR_FINAL", (
            "the installation's own cycle edge completes the recovery")


class TestApprovalSupersessionCascade:
    def test_second_design_approval_suspends_permit(self, api):
        """PRD section 2.8: "Approving a design when the site already holds
        another `APPROVED` design supersedes the older design, which in turn
        suspends any permit pinning it, which in turn forces any non-terminal
        installation under such a permit into `FAILED_HOLD`."

        Design: Difficulty/transitive_cascade/approval_supersession_cascades_permit_to_installation
        """
        ctx = setup_installation(bedroom_count=3)
        advance(ctx)
        db = add_design(ctx, bedroom_count=4)
        submit_design(ctx, db["id"])
        approved = approve_design(ctx, db["id"])
        assert approved["status"] == "APPROVED"
        assert get_design(ctx, ctx.d0)["status"] == "SUPERSEDED"
        assert get_permit(ctx)["status"] == "SUSPENDED", (
            "hop 2: caused by the pinned design's supersession")

    def test_approval_cascade_forces_installation_failed_hold(self, api):
        """PRD section 2.8: "Approving a design when the site already holds
        another `APPROVED` design supersedes the older design, which in turn
        suspends any permit pinning it, which in turn forces any non-terminal
        installation under such a permit into `FAILED_HOLD`."

        Design: Difficulty/transitive_cascade/approval_supersession_cascades_permit_to_installation
        """
        ctx = setup_installation(bedroom_count=3)
        advance(ctx)  # ROUGH_IN_PROGRESS is non-terminal
        db = add_design(ctx, bedroom_count=4)
        submit_design(ctx, db["id"])
        approve_design(ctx, db["id"])
        assert get_installation(ctx)["status"] == "FAILED_HOLD", (
            "hop 3: caused by the permit's suspension")


class TestPermitExpiryBoundary:
    def test_clock_advance_expires_permit_past_window(self, api):
        """PRD section 3.5: "records the `issued_period` as the site's current
        period index, and computes the `expires_period` as the issued period plus
        6 minus 1 — a validity window of six periods inclusive on both ends, so a
        permit issued at period 0 covers periods 0 through 5 and is expired once
        the site clock reaches period 6."
        PRD section 3.5: "The clock can expire it: when the site's
        `current_period_index` advances beyond `expires_period`, the permit moves
        to `EXPIRED` and its non-terminal installations are likewise forced to
        `FAILED_HOLD`."

        Design: Difficulty/transitive_cascade/clock_advance_cascades_permit_expiry_to_installation
        """
        ctx = setup_installation(bedroom_count=4)
        advance(ctx)
        permit = get_permit(ctx)
        assert permit["expires_period"] == 5, "issued 0 + 6 - 1; window covers 0..5"
        site = advance_clock(ctx, 6)
        assert site["current_period_index"] == 6
        assert get_permit(ctx)["status"] == "EXPIRED", "hop 1: 6 > expires_period 5"

    def test_expiry_cascade_forces_installation_failed_hold(self, api):
        """PRD section 3.5: "The clock can expire it: when the site's
        `current_period_index` advances beyond `expires_period`, the permit moves
        to `EXPIRED` and its non-terminal installations are likewise forced to
        `FAILED_HOLD`."

        Design: Difficulty/transitive_cascade/clock_advance_cascades_permit_expiry_to_installation
        """
        ctx = setup_installation(bedroom_count=4)
        advance(ctx)
        advance_clock(ctx, 6)
        assert get_permit(ctx)["status"] == "EXPIRED"
        assert get_installation(ctx)["status"] == "FAILED_HOLD", (
            "hop 2: expiry cascade, not a direct clock side effect")

    def test_installation_start_at_expiry_period_succeeds(self, api):
        """PRD section 3.6: "The first leg, breaking ground into
        `ROUGH_IN_PROGRESS`, additionally requires the permit to be within its
        validity window — the site's `current_period_index` must not exceed the
        permit's `expires_period`, else `ERR_PERMIT_EXPIRED` — and records the
        current period as the installation's `started_period`."

        Design: Difficulty/boundary_precision_check/permit_expiry_inclusive_window_boundary
        """
        ctx = setup_installation(bedroom_count=4)
        advance_clock(ctx, 5)  # == expires_period: inside the inclusive window
        started = advance(ctx)
        assert started["status"] == "ROUGH_IN_PROGRESS"
        assert started["started_period"] == 5

    def test_reinstate_after_expiry_window_rejected(self, api):
        """PRD section 3.5: "the site's clock must not have moved past
        `expires_period`, else `ERR_PERMIT_EXPIRED`".

        Design: Difficulty/boundary_precision_check/permit_expiry_inclusive_window_boundary
        """
        ctx = setup_installation(bedroom_count=4)
        suspended = validate_success(api_client.suspend_permit(
            ctx.cid, ctx.cu, ctx.s, ctx.p0, ctx.officer))
        advance_clock(ctx, 6)  # SUSPENDED permits do not auto-expire; window passed
        resp = api_client.reinstate_permit(
            ctx.cid, ctx.cu, ctx.s, ctx.p0,
            reinstate_permit_payload(suspended["version"]), ctx.officer)
        validate_error(resp, ApiErrorId.ERR_PERMIT_EXPIRED)


class TestInstallationDependsOnPermitState:
    def test_suspend_forces_not_started_installation_to_failed_hold(self, api):
        """PRD section 3.5: "either path moves the permit from `ISSUED` to
        `SUSPENDED` and forces every installation it authorizes that sits in a
        non-terminal state — anywhere from `NOT_STARTED` through `READY_FOR_FINAL`
        — into `FAILED_HOLD`."

        Design: Difficulty/cross_entity_state_dependency/installation_advance_depends_on_permit_state
        """
        ctx = setup_installation(bedroom_count=4)
        suspended = validate_success(api_client.suspend_permit(
            ctx.cid, ctx.cu, ctx.s, ctx.p0, ctx.officer))
        assert suspended["status"] == "SUSPENDED"
        assert get_installation(ctx)["status"] == "FAILED_HOLD", (
            "NOT_STARTED is in the cascade's non-terminal range")

    def test_remediate_with_suspended_permit_fails(self, api):
        """PRD section 3.6: "Two standing guards apply to every advance and every
        remediation: the authorizing permit must be `ISSUED`, else
        `ERR_PERMIT_NOT_ISSUED`, and the site must be `OPEN`, else
        `ERR_SITE_FROZEN`."

        Design: Difficulty/cross_entity_state_dependency/installation_advance_depends_on_permit_state
        """
        ctx = setup_installation(bedroom_count=4)
        api_client.suspend_permit(ctx.cid, ctx.cu, ctx.s, ctx.p0, ctx.officer)
        assert get_installation(ctx)["status"] == "FAILED_HOLD", (
            "a valid from-state for remediate does not rescue the call")
        resp = api_client.remediate_installation(ctx.cid, ctx.cu, ctx.s, ctx.i0, ctx.manager)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ISSUED)


class TestFrozenAndRevokedPermitEffects:
    def test_error_site_frozen_blocks_installation_advance(self, api):
        """PRD section 3.7: "While frozen, four operations are refused with
        `ERR_SITE_FROZEN`: design submission, installation advance, installation
        remediation, and repair-case remediation start."

        Design: Corner/validations/error_site_frozen_blocks_installation_advance
        """
        ctx = setup_installation(bedroom_count=3)
        freeze_site(ctx, 3)
        resp = api_client.advance_installation(ctx.cid, ctx.cu, ctx.s, ctx.i0, ctx.manager)
        validate_error(resp, ApiErrorId.ERR_SITE_FROZEN)
        assert get_installation(ctx)["status"] == "NOT_STARTED"

    def test_cascading_side_effects_permit_revoke_abandons_installation(self, api):
        """PRD section 3.5: "a health officer may revoke it outright from either
        `ISSUED` or `SUSPENDED` — any other status is `ERR_INVALID_STATE` —
        supplying a `revoke_note` of at least 20 characters
        (`ERR_INSUFFICIENT_NOTE`); revocation moves the permit to `REVOKED` and
        forces its non-terminal installations to `ABANDONED`."

        Design: Corner/cross_cutting_layers/cascading_side_effects_permit_revoke_abandons_installation
        """
        ctx = setup_installation(bedroom_count=3)
        short = api_client.revoke_permit(
            ctx.cid, ctx.cu, ctx.s, ctx.p0, revoke_permit_payload("short"), ctx.officer)
        validate_error(short, ApiErrorId.ERR_INSUFFICIENT_NOTE)
        assert get_permit(ctx)["status"] == "ISSUED", "atomic rejection: no partial cascade"
        assert get_installation(ctx)["status"] == "NOT_STARTED"

        revoked = validate_success(api_client.revoke_permit(
            ctx.cid, ctx.cu, ctx.s, ctx.p0, revoke_permit_payload(), ctx.officer))
        assert revoked["status"] == "REVOKED"
        assert get_installation(ctx)["status"] == "ABANDONED"


class TestInitialStates:
    def test_initial_states_on_creation(self, api):
        """PRD section 3.2: "both records enter life in `RECORDED` status."
        PRD section 3.3: "The design is born in `DRAFT` status with a
        `design_version` of 1".
        PRD section 3.5: "The permit is born `ISSUED`."
        PRD section 3.6: "The installation is born `NOT_STARTED`".
        PRD section 3.6: "A scheduled inspection's `result` starts as `PENDING`."

        Design: Corner/state_machines/initial_states_on_creation
        """
        ctx = setup_site_with_science(inspector=True)
        evaluation = validate_success(api_client.get_soil_evaluation(
            ctx.cid, ctx.cu, ctx.s, ctx.e1, ctx.manager))
        assert evaluation["status"] == "RECORDED"

        design = add_design(ctx, bedroom_count=3)
        assert design["status"] == "DRAFT"
        assert design["design_version"] == 1

        submit_design(ctx, design["id"])
        approve_design(ctx, design["id"])
        ctx.d0 = design["id"]
        permit = add_permit(ctx)
        assert permit["status"] == "ISSUED"
        assert permit["issued_period"] == 0
        assert permit["expires_period"] == 5

        installation = add_installation(ctx)
        assert installation["status"] == "NOT_STARTED"

        inspection = schedule_inspection(ctx, hold_point="TANK_SET", scheduled_period=0)
        assert inspection["result"] == "PENDING"
