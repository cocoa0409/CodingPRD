"""Panel governance and outside counsel engagements."""
from test_helpers import (
    create_approved_firm,
    create_counsel_firm_payload,
    create_engagement_payload,
    get_success_data,
    setup_active_matter,
    setup_staffing_matter,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId, EngagementStatus, PanelStatus


class TestEngagementLetterGate:
    def test_engagement_activate_requires_executed_letter(self, api):
        """PRD §3.3: "Activating the engagement (`APPROVED` → `ACTIVE`) then requires
        the letter to be executed — activation without it fails with
        `ERR_ENGAGEMENT_LETTER_REQUIRED` — and a linked matter in `STAFFING`, `ACTIVE`,
        or `REOPENED`."
        PRD §3.3: "While the engagement is `PROPOSED` or `APPROVED`, the owning counsel
        may update `engagement_letter_executed` to record the countersigned letter; the
        update outside those states is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/engagement_activate_requires_executed_letter
        """
        ctx = setup_staffing_matter()
        firm = create_approved_firm(ctx["gc_id"])
        engagement = get_success_data(api.create_engagement(
            ctx["matter_id"],
            create_engagement_payload(firm_id=firm["id"], role_type="SPECIALIST",
                                      engagement_letter_executed=False),
            ctx["counsel"]))
        get_success_data(api.approve_engagement(engagement["id"], ctx["dgc"]))

        resp = api.activate_engagement(engagement["id"], ctx["counsel"])
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_LETTER_REQUIRED)

        get_success_data(api.patch_engagement(
            engagement["id"], {"engagement_letter_executed": True}, ctx["counsel"]))
        activated = validate_success(
            api.activate_engagement(engagement["id"], ctx["counsel"]))
        assert activated["status"] == EngagementStatus.ACTIVE.value


class TestEngagementApproveFirmGate:
    def test_engagement_approve_blocked_while_firm_pending(self, api):
        """PRD §3.3: "Approval belongs to the `DeputyGeneralCounsel` and checks, beyond
        the firm's panel and conflict state and the rate cap, that the linked matter is
        in `STAFFING`, `ACTIVE`, or `REOPENED`."
        PRD §2.11: "(16) referenced-entity state (`ERR_REFERENCE_STATE_INVALID`)".

        Design: Difficulty/cross_entity_state_dependency/engagement_approve_requires_firm_panel_approved
        """
        ctx = setup_staffing_matter()
        firm = get_success_data(api.create_counsel_firm(
            create_counsel_firm_payload(), ctx["ops"]))
        get_success_data(api.conflict_check_firm(firm["id"], "CLEARED", ctx["ops"]))
        engagement = get_success_data(api.create_engagement(
            ctx["matter_id"],
            create_engagement_payload(firm_id=firm["id"], role_type="LEAD_COUNSEL"),
            ctx["counsel"]))

        resp = api.approve_engagement(engagement["id"], ctx["dgc"])
        validate_error(resp, ApiErrorId.ERR_REFERENCE_STATE_INVALID)
        current = get_success_data(api.get_engagement(engagement["id"], ctx["counsel"]))
        assert current["status"] == EngagementStatus.PROPOSED.value

    def test_engagement_approve_succeeds_after_panel_approval(self, api):
        """PRD §3.3: "Only the `GeneralCounsel` may then approve the firm onto the
        panel, and only when the firm is `PENDING` with a conflict result of `CLEARED`
        or `WAIVED`"
        PRD §3.3: "Approval belongs to the `DeputyGeneralCounsel` and checks, beyond
        the firm's panel and conflict state and the rate cap, that the linked matter is
        in `STAFFING`, `ACTIVE`, or `REOPENED`."

        Design: Difficulty/cross_entity_state_dependency/engagement_approve_requires_firm_panel_approved
        """
        ctx = setup_staffing_matter()
        firm = get_success_data(api.create_counsel_firm(
            create_counsel_firm_payload(), ctx["ops"]))
        get_success_data(api.conflict_check_firm(firm["id"], "CLEARED", ctx["ops"]))
        engagement = get_success_data(api.create_engagement(
            ctx["matter_id"],
            create_engagement_payload(firm_id=firm["id"], role_type="LEAD_COUNSEL"),
            ctx["counsel"]))

        get_success_data(api.approve_panel_firm(firm["id"], ctx["gc"]))
        approved = validate_success(
            api.approve_engagement(engagement["id"], ctx["dgc"]))
        assert approved["status"] == EngagementStatus.APPROVED.value
        assert approved["approved_by_user_id"] == ctx["dgc_id"]


class TestFirmSuspendCycle:
    def test_firm_suspend_cascades_engagement_suspension(self, api):
        """PRD §3.3: "The `GeneralCounsel` may suspend an `APPROVED` firm, which moves
        it to `SUSPENDED` and cascades: every engagement referencing that firm in
        `ACTIVE` status moves to `SUSPENDED`, each such engagement incrementing its
        own `version`."

        Design: Difficulty/non_linear_state_machine/counsel_firm_suspend_cycle_cascades_engagements
        """
        ctx = setup_active_matter()
        suspended_firm = validate_success(api.suspend_firm(ctx["firm_id"], ctx["gc"]))
        assert suspended_firm["panel_status"] == PanelStatus.SUSPENDED.value
        engagement = get_success_data(
            api.get_engagement(ctx["engagement_id"], ctx["counsel"]))
        assert engagement["status"] == EngagementStatus.SUSPENDED.value, \
            "firm suspension must cascade ACTIVE engagements to SUSPENDED"

    def test_firm_reinstate_does_not_restore_engagements(self, api):
        """PRD §3.3: "Reinstating the firm moves `SUSPENDED` → `APPROVED`, but
        engagements suspended by the cascade do not ride back automatically — each
        must be reinstated individually."

        Design: Difficulty/non_linear_state_machine/counsel_firm_suspend_cycle_cascades_engagements
        """
        ctx = setup_active_matter()
        get_success_data(api.suspend_firm(ctx["firm_id"], ctx["gc"]))
        reinstated = validate_success(api.reinstate_firm(ctx["firm_id"], ctx["gc"]))
        assert reinstated["panel_status"] == PanelStatus.APPROVED.value
        engagement = get_success_data(
            api.get_engagement(ctx["engagement_id"], ctx["counsel"]))
        assert engagement["status"] == EngagementStatus.SUSPENDED.value, \
            "the reinstate leg must not auto-restore cascade-suspended engagements"


class TestFirmTermination:
    def test_firm_terminate_blocked_by_active_engagement(self, api):
        """PRD §3.3: "Termination, from `APPROVED` or `SUSPENDED`, is final and is
        refused with `ERR_REFERENCE_STATE_INVALID` while any engagement of the firm
        remains `ACTIVE` or `APPROVED`; engagements must be wound down first."

        Design: Corner/state_machines/firm_terminate_blocked_by_active_engagement
        """
        ctx = setup_active_matter()
        resp = api.terminate_firm(ctx["firm_id"], ctx["gc"])
        validate_error(resp, ApiErrorId.ERR_REFERENCE_STATE_INVALID)

        get_success_data(api.terminate_engagement(ctx["engagement_id"], ctx["dgc"]))
        terminated = validate_success(api.terminate_firm(ctx["firm_id"], ctx["gc"]))
        assert terminated["panel_status"] == PanelStatus.TERMINATED.value


class TestEngagementSupersession:
    def test_engagement_supersede_terminates_prior(self, api):
        """PRD §3.3: "Approval stamps `approved_by_user_id` for audit, increments the
        engagement's `version`, and performs the supersession compensation — when
        `supersedes_engagement_id` is set, the superseded engagement moves from
        `ACTIVE` or `SUSPENDED` to `TERMINATED`."

        Design: Corner/state_machines/engagement_supersede_terminates_prior
        """
        ctx = setup_active_matter()
        prior_id = ctx["engagement_id"]
        replacement = get_success_data(api.create_engagement(
            ctx["matter_id"],
            create_engagement_payload(
                firm_id=ctx["firm_id"], role_type="LEAD_COUNSEL",
                proposed_rate_cents=75_000, engagement_letter_executed=True,
                supersedes_engagement_id=prior_id),
            ctx["counsel"]))

        approved = validate_success(
            api.approve_engagement(replacement["id"], ctx["dgc"]))
        assert approved["status"] == EngagementStatus.APPROVED.value
        prior = get_success_data(api.get_engagement(prior_id, ctx["counsel"]))
        assert prior["status"] == EngagementStatus.TERMINATED.value, \
            "the superseded engagement must be terminated by the approval cascade"


class TestRateCap:
    def test_error_rate_cap_exceeded_on_engagement_create(self, api):
        """PRD §3.3: "For `HOURLY` or `HYBRID` arrangements a `proposed_rate_cents` is
        required and must not exceed the firm's `blended_rate_cap_cents`, an overage
        rejected with `ERR_RATE_CAP_EXCEEDED`"

        Design: Corner/errors/error_rate_cap_exceeded_on_engagement_create
        """
        ctx = setup_staffing_matter()
        firm = create_approved_firm(ctx["gc_id"], rate_cap_cents=90_000)
        resp = api.create_engagement(
            ctx["matter_id"],
            create_engagement_payload(firm_id=firm["id"], role_type="SPECIALIST",
                                      proposed_rate_cents=90_001),
            ctx["counsel"])
        validate_error(resp, ApiErrorId.ERR_RATE_CAP_EXCEEDED)


class TestFirmReverseReachability:
    def test_counsel_firm_filtered_engagements_reverse_reachability(self, api):
        """PRD §3.3: "A firm's engagements can be listed directly from the firm for
        reverse reachability."

        Design: Corner/endpoints/counsel_firm_filtered_engagements_reverse_reachability
        """
        ctx = setup_staffing_matter()
        firm = get_success_data(api.create_counsel_firm(
            create_counsel_firm_payload(), ctx["ops"]))
        engagement = get_success_data(api.create_engagement(
            ctx["matter_id"],
            create_engagement_payload(firm_id=firm["id"], role_type="SPECIALIST"),
            ctx["counsel"]))

        data, _meta = validate_paginated(
            api.list_firm_engagements(firm["id"], ctx["counsel"]))
        assert len(data) == 1
        assert data[0]["id"] == engagement["id"]
