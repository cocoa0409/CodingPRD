"""Tiers, viewers, subscriptions, perk fulfillment, and viewer discipline."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equals,
    assert_moderation_action,
    assert_tier_perk_invariant,
    create_active_moderator,
    create_channel,
    create_moderator,
    create_subscription,
    create_subscription_payload,
    create_tier,
    create_viewer,
    get_success_data,
    issue_moderation_action,
    list_perk_grants,
    make_creator_headers,
    make_moderator_headers,
    moderation_action_payload,
    setup_subscription_with_perk,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestTierUniqueness:
    def test_duplicate_active_tier_code_rejected(self, api):
        """PRD §3.4: "A new tier is born `ACTIVE` with
        `perk_inventory_remaining` equal to `perk_inventory_total`, and at
        most one `ACTIVE` tier per `tier_code` may exist per channel: a
        conflicting creation, or a reactivation while a sibling with the same
        code is active, is rejected with `ERR_TIER_CODE_IN_USE`."

        Design: Corner/validations/duplicate_active_tier_code_rejected
        """
        channel_a = create_channel(handle="val_ta", home_platform="TWITCH")
        channel_b = create_channel(handle="val_tb", home_platform="YOUTUBE")
        create_tier(channel_a["id"], tier_code="TIER_1")

        dup = api.create_tier(
            channel_a["id"],
            {"tier_code": "TIER_1", "monthly_price_cents": 6000,
             "revenue_share_bps": 5000, "perk_inventory_total": 1},
            make_creator_headers(channel_a["id"]))
        validate_error(dup, ApiErrorId.ERR_TIER_CODE_IN_USE)

        other = validate_success(api.create_tier(
            channel_b["id"],
            {"tier_code": "TIER_1", "monthly_price_cents": 6000,
             "revenue_share_bps": 5000, "perk_inventory_total": 1},
            make_creator_headers(channel_b["id"])), 201)
        assert other["tier_status"] == "ACTIVE", (
            "the same tier_code on another channel is fine — uniqueness is "
            "scoped per channel")


class TestSubscriptionCreation:
    def test_subscription_cross_channel_fk_rejected(self, api):
        """PRD §2.4: "The same rule applies to body-referenced identifiers —
        a payload naming a `viewer_id`, `tier_id`, `stream_id`, or
        `reverses_event_id` that does not exist, or that belongs to a
        different parent than the path implies, is rejected with
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/subscription_cross_channel_fk_rejected
        """
        channel_a = create_channel(handle="corner_fka", home_platform="TWITCH")
        channel_b = create_channel(handle="corner_fkb", home_platform="YOUTUBE")
        viewer_a = create_viewer(channel_a["id"], handle="v_a")
        tier_b = create_tier(channel_b["id"], tier_code="TIER_1")

        resp = api.create_subscription(
            channel_a["id"],
            create_subscription_payload(viewer_a["id"], tier_b["id"]),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

        _subs, meta = validate_paginated(api.list_subscriptions(
            ADMIN, params={"channel_id": channel_a["id"]}))
        assert meta["total_count"] == 0, "no subscription may be persisted"

    def test_subscription_past_due_recover_cycle(self, api):
        """PRD §3.4: "A `PlatformAdmin` may mark an `ACTIVE` subscription
        `PAST_DUE`, and may later recover a `PAST_DUE` subscription back to
        `ACTIVE` — recovery being the second place the ban gate bites, since
        recovering a subscription for a `BANNED` viewer is rejected with
        `ERR_VIEWER_BANNED`."
        PRD §3.4: "Cancellation voids the subscription's outstanding perks:
        grants in `PENDING` or `FAILED` move to `VOIDED`, while `FULFILLED`
        grants are untouched and no inventory is restored."

        Design: Corner/state_machines/subscription_past_due_recover_cycle
        """
        channel = create_channel(handle="sm_sub", home_platform="TWITCH")
        tier, viewer, subscription, grant = setup_subscription_with_perk(
            channel["id"], perk_inventory_total=5, viewer_handle="v_sub")

        past_due = get_success_data(api.transition_subscription(
            subscription["id"], {"action": "MARK_PAST_DUE"}, ADMIN))
        assert past_due["sub_status"] == "PAST_DUE"

        recovered = get_success_data(api.transition_subscription(
            subscription["id"], {"action": "RECOVER"}, ADMIN))
        assert recovered["sub_status"] == "ACTIVE", "the cycle closes"
        assert recovered["cycles_paid"] == 1, (
            "the PAST_DUE loop does not consume a billing cycle")

        grants = list_perk_grants(subscription["id"], channel["id"])
        assert grants[0]["id"] == grant["id"]
        assert grants[0]["perk_status"] == "PENDING", (
            "no void cascade attaches to PAST_DUE")


class TestPerkInventory:
    def test_perk_fulfill_inventory_exhausted(self, api):
        """PRD §3.4: "Fulfilling a grant requires the tier's
        `perk_inventory_remaining` to be greater than zero — an exhausted tier
        rejects the attempt with `ERR_PERK_INVENTORY_EXHAUSTED` — and on
        success decrements `perk_inventory_remaining` by 1 and stamps
        `fulfilled_at`."

        Design: Corner/validations/perk_fulfill_inventory_exhausted
        """
        channel = create_channel(handle="val_perk", home_platform="TWITCH")
        tier, _viewer, _sub, grant = setup_subscription_with_perk(
            channel["id"], tier_code="TIER_2", monthly_price_cents=10000,
            revenue_share_bps=6000, perk_inventory_total=0,
            viewer_handle="v_perk")
        assert tier["perk_inventory_remaining"] == 0

        resp = api.transition_perk_grant(
            grant["id"], {"action": "FULFILL"},
            make_creator_headers(channel["id"]))
        validate_error(resp, ApiErrorId.ERR_PERK_INVENTORY_EXHAUSTED)

        grants = list_perk_grants(grant["subscription_id"], channel["id"])
        assert grants[0]["perk_status"] == "PENDING"
        tier_after = get_success_data(
            api.get_tier(tier["id"], make_creator_headers(channel["id"])))
        assert tier_after["perk_inventory_remaining"] == 0, (
            "no negative inventory")

    def test_perk_fulfill_decrements_inventory(self, api):
        """PRD §3.4: "Fulfilling a grant requires the tier's
        `perk_inventory_remaining` to be greater than zero — an exhausted tier
        rejects the attempt with `ERR_PERK_INVENTORY_EXHAUSTED` — and on
        success decrements `perk_inventory_remaining` by 1 and stamps
        `fulfilled_at`."
        PRD §3.4: "The invariant `perk_inventory_remaining` plus the count of
        the tier's `FULFILLED` grants equals `perk_inventory_total` holds at
        all times, and a subscription's grant list accepts a `perk_status`
        filter."

        Design: Difficulty/compensating_invariant/perk_inventory_fulfill_void_conservation
        """
        channel = create_channel(handle="ci_perk", home_platform="YOUTUBE")
        tier, _viewer, _sub, grant = setup_subscription_with_perk(
            channel["id"], perk_inventory_total=2)

        fulfilled = validate_success(api.transition_perk_grant(
            grant["id"], {"action": "FULFILL"},
            make_creator_headers(channel["id"])), 200)
        assert fulfilled["perk_status"] == "FULFILLED"
        assert fulfilled["fulfilled_at"] is not None

        tier_after = get_success_data(
            api.get_tier(tier["id"], make_creator_headers(channel["id"])))
        assert tier_after["perk_inventory_remaining"] == 1, "2 - 1 FULFILLED"
        assert_tier_perk_invariant(tier_after, fulfilled_count=1)

    def test_perk_void_restores_inventory_exactly(self, api):
        """PRD §3.4: "Explicit voiding by the owner applies to `FULFILLED`
        grants and is the one compensating move in this lifecycle: it returns
        the unit to stock, incrementing `perk_inventory_remaining` by 1."
        PRD §3.4: "The invariant `perk_inventory_remaining` plus the count of
        the tier's `FULFILLED` grants equals `perk_inventory_total` holds at
        all times, and a subscription's grant list accepts a `perk_status`
        filter."

        Design: Difficulty/compensating_invariant/perk_inventory_fulfill_void_conservation
        """
        channel = create_channel(handle="ci_perk2", home_platform="YOUTUBE")
        tier, _viewer, _sub, grant = setup_subscription_with_perk(
            channel["id"], perk_inventory_total=2)
        get_success_data(api.transition_perk_grant(
            grant["id"], {"action": "FULFILL"},
            make_creator_headers(channel["id"])))

        voided = validate_success(api.transition_perk_grant(
            grant["id"], {"action": "VOID"},
            make_creator_headers(channel["id"])), 200)
        assert voided["perk_status"] == "VOIDED"

        tier_after = get_success_data(
            api.get_tier(tier["id"], make_creator_headers(channel["id"])))
        assert tier_after["perk_inventory_remaining"] == 2, (
            "the FULFILL/VOID compensating pair restores the unit exactly")
        assert_tier_perk_invariant(tier_after, fulfilled_count=0)


class TestModerationActions:
    def test_moderation_action_initial_state_and_standing(self, api):
        """PRD §3.5: "Issuance stamps `issued_at` from the clock; a `TIMEOUT`
        computes `expires_at` as `issued_at` plus its duration, while a `BAN`
        has a null `expires_at` and never auto-expires."
        PRD §3.5: "With at least one `ACTIVE` `BAN`, the viewer is `BANNED`.
        Otherwise, with at least one `ACTIVE` `TIMEOUT`, the viewer is
        `TIMED_OUT`. Otherwise the viewer is `GOOD_STANDING`."
        PRD §2.5: "At startup the clock reads exactly 2026-08-01T00:00:00Z,
        and it never falls back to wall time."

        Design: Corner/state_machines/moderation_action_initial_state_and_standing
        """
        channel = create_channel(handle="sm_mod", home_platform="YOUTUBE")
        viewer = create_viewer(channel["id"], handle="v_mod")

        action = validate_success(api.create_moderation_action(
            channel["id"],
            moderation_action_payload(viewer["id"], action_kind="TIMEOUT",
                                      duration_minutes=600, reason="spam"),
            make_creator_headers(channel["id"])), 201)
        assert_moderation_action(action)
        assert action["action_status"] == "ACTIVE"
        assert_instant_equals(action["issued_at"], "2026-08-01T00:00:00Z",
                              label="issued_at (default logical clock)")
        assert_instant_equals(action["expires_at"], "2026-08-01T10:00:00Z",
                              label="expires_at == issued_at + 600 minutes")

        viewer_after = get_success_data(api.get_viewer(
            viewer["id"], make_creator_headers(channel["id"])))
        assert viewer_after["standing"] == "TIMED_OUT"

    def test_moderation_action_duration_shape_rules(self, api):
        """PRD §2.9: "**Request well-formedness.** The body must parse,
        required fields must be present, enums must be in their declared sets,
        and integer and temporal ranges must hold: a `TIMEOUT` action carries
        `duration_minutes` between 1 and 10,080 minutes (one week) inclusive
        while a `BAN` must omit it, a stream's `scheduled_end` is strictly
        after its `scheduled_start`, a grant's `window_end` is strictly after
        its `window_start`, and a deliverable's `due_at` lies within its
        deal's flight — otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/validations/moderation_action_duration_shape_rules
        """
        channel = create_channel(handle="val_dur", home_platform="TWITCH")
        viewer = create_viewer(channel["id"], handle="v_dur")
        for reason in ("t1", "t2"):
            issue_moderation_action(channel["id"], viewer["id"],
                                    action_kind="TIMEOUT", duration_minutes=10,
                                    reason=reason)

        too_long = api.create_moderation_action(
            channel["id"],
            moderation_action_payload(viewer["id"], action_kind="TIMEOUT",
                                      duration_minutes=10081,
                                      reason="too long"),
            make_creator_headers(channel["id"]))
        validate_error(too_long, ApiErrorId.ERR_INVALID_REQUEST)

        ban_with_duration = api.create_moderation_action(
            channel["id"],
            moderation_action_payload(viewer["id"], action_kind="BAN",
                                      duration_minutes=60,
                                      reason="ban with duration"),
            make_creator_headers(channel["id"]))
        validate_error(ban_with_duration, ApiErrorId.ERR_INVALID_REQUEST)


class TestProgressiveDiscipline:
    def test_ban_requires_progressive_discipline(self, api):
        """PRD §3.5: "Issuing a `BAN` requires at least two prior `TIMEOUT`
        actions on the same channel-and-viewer pair whose status is `ACTIVE`
        or `EXPIRED` — reversed timeouts do not count — and a channel short of
        that history is rejected with `ERR_PROGRESSIVE_DISCIPLINE`."

        Design: Corner/validations/ban_requires_progressive_discipline
        """
        channel = create_channel(handle="val_ban", home_platform="TWITCH")
        viewer = create_viewer(channel["id"], handle="v_ban")

        early = api.create_moderation_action(
            channel["id"],
            moderation_action_payload(viewer["id"], action_kind="BAN",
                                      reason="too early"),
            make_creator_headers(channel["id"]))
        validate_error(early, ApiErrorId.ERR_PROGRESSIVE_DISCIPLINE)

        for reason in ("t1", "t2"):
            issue_moderation_action(channel["id"], viewer["id"],
                                    action_kind="TIMEOUT", duration_minutes=600,
                                    reason=reason)

        ban = validate_success(api.create_moderation_action(
            channel["id"],
            moderation_action_payload(viewer["id"], action_kind="BAN",
                                      reason="now allowed"),
            make_creator_headers(channel["id"])), 201)
        assert ban["action_status"] == "ACTIVE"

        viewer_after = get_success_data(api.get_viewer(
            viewer["id"], make_creator_headers(channel["id"])))
        assert viewer_after["standing"] == "BANNED"

    def test_ban_cascade_voids_subscription_and_blocks_new(self, api):
        """PRD §3.5: "The ban is the punishing cascade: the moment a viewer
        becomes `BANNED`, every subscription of that viewer on the channel in
        `ACTIVE` or `PAST_DUE` moves to `CANCELLED`, and those subscriptions'
        grants in `PENDING` or `FAILED` move to `VOIDED` — exactly the cascade
        §3.4 attaches to owner cancellation."
        PRD §3.4: "Both must belong to the channel in the path (otherwise
        `ERR_NOT_FOUND`), the viewer's standing must not be `BANNED`
        (`ERR_VIEWER_BANNED`), and the tier must currently be `ACTIVE` (a
        `RETIRED` tier fails with `ERR_INVALID_STATE`)."

        Design: Corner/validations/ban_cascade_voids_subscription_and_blocks_new
        """
        channel = create_channel(handle="val_casc", home_platform="YOUTUBE")
        tier, viewer, subscription, grant = setup_subscription_with_perk(
            channel["id"], perk_inventory_total=3, viewer_handle="v_casc")
        for reason in ("t1", "t2"):
            issue_moderation_action(channel["id"], viewer["id"],
                                    action_kind="TIMEOUT", duration_minutes=30,
                                    reason=reason)

        validate_success(api.create_moderation_action(
            channel["id"],
            moderation_action_payload(viewer["id"], action_kind="BAN",
                                      reason="ban"),
            make_creator_headers(channel["id"])), 201)

        sub_after = get_success_data(api.get_subscription(
            subscription["id"], make_creator_headers(channel["id"])))
        assert sub_after["sub_status"] == "CANCELLED", "ban cascade cancels"
        grants = list_perk_grants(subscription["id"], channel["id"])
        assert grants[0]["perk_status"] == "VOIDED", "ban cascade voids perks"
        tier_after = get_success_data(
            api.get_tier(tier["id"], make_creator_headers(channel["id"])))
        assert tier_after["perk_inventory_remaining"] == 3, (
            "the grant was never FULFILLED, so no inventory is restored")

        resp = api.create_subscription(
            channel["id"],
            create_subscription_payload(viewer["id"], tier["id"]),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_VIEWER_BANNED)


class TestModeratorGates:
    def test_moderator_status_and_scope_gates(self, api):
        """PRD §3.5: "When a moderator issues the action, that moderator must
        be `ACTIVE` (`ERR_MODERATOR_NOT_ACTIVE`) and must hold the scope
        matching the action kind — a `BAN` issued without the `BAN` scope is
        rejected with `ERR_MODERATOR_SCOPE_MISSING`; when the owner issues it,
        the action's `moderator_id` stays null."

        Design: Corner/validations/moderator_status_and_scope_gates
        """
        channel = create_channel(handle="val_mod", home_platform="TWITCH")
        moderator = create_active_moderator(channel["id"],
                                            moderator_handle="mod_m",
                                            scopes=["TIMEOUT"])
        viewer = create_viewer(channel["id"], handle="v_scope")
        for reason in ("t1", "t2"):
            issue_moderation_action(channel["id"], viewer["id"],
                                    action_kind="TIMEOUT", duration_minutes=10,
                                    reason=reason)

        no_scope = api.create_moderation_action(
            channel["id"],
            moderation_action_payload(viewer["id"], action_kind="BAN",
                                      reason="no scope"),
            make_moderator_headers(moderator["id"]))
        validate_error(no_scope, ApiErrorId.ERR_MODERATOR_SCOPE_MISSING)

        suspended = get_success_data(api.transition_moderator(
            moderator["id"], {"action": "SUSPEND"},
            make_creator_headers(channel["id"])))
        assert suspended["moderator_status"] == "SUSPENDED"

        not_active = api.create_moderation_action(
            channel["id"],
            moderation_action_payload(viewer["id"], action_kind="TIMEOUT",
                                      duration_minutes=10, reason="suspended"),
            make_moderator_headers(moderator["id"]))
        validate_error(not_active, ApiErrorId.ERR_MODERATOR_NOT_ACTIVE)

    def test_moderator_accept_self_only(self, api):
        """PRD §3.5: "Acceptance is self-service and identity-checked: the
        transition to `ACTIVE` must be performed with an `X-User-ID` equal to
        that moderator's own `id`, otherwise
        `ERR_CHANNEL_OWNERSHIP_MISMATCH`."

        Design: Corner/rbac/moderator_accept_self_only
        """
        channel = create_channel(handle="rb_acc", home_platform="TWITCH")
        mod1 = create_moderator(channel["id"], moderator_handle="m1",
                                scopes=["TIMEOUT"])
        mod2 = create_moderator(channel["id"], moderator_handle="m2",
                                scopes=["TIMEOUT"])

        wrong = api.transition_moderator(mod1["id"], {"action": "ACCEPT"},
                                         make_moderator_headers(mod2["id"]))
        validate_error(wrong, ApiErrorId.ERR_CHANNEL_OWNERSHIP_MISMATCH)

        accepted = validate_success(api.transition_moderator(
            mod1["id"], {"action": "ACCEPT"},
            make_moderator_headers(mod1["id"])), 200)
        assert accepted["moderator_status"] == "ACTIVE"


class TestImmediateConsistency:
    def test_immediate_consistency_after_moderation_action(self, api):
        """PRD §1: "First, money is handled as an immediately consistent
        ledger: every mutation and every cascade it triggers is visible in the
        response of the same request, balances are conserved through
        compensating pairs, and revenue recognition runs in two variants — a
        provisional figure computed at ingestion and a final figure computed
        at month settlement."
        PRD §3.5: "A viewer's `standing` is a derived, compound state
        recomputed on every action issuance, reversal, and expiry."
        PRD §3.5: "The six arcs follow directly: `GOOD_STANDING` to
        `TIMED_OUT` when a timeout becomes active while no ban is active;
        `GOOD_STANDING` or `TIMED_OUT` to `BANNED` when a ban becomes active;
        `TIMED_OUT` back to `GOOD_STANDING` when the last active timeout is
        reversed or expires with no ban active; and `BANNED` to
        `GOOD_STANDING` or to `TIMED_OUT` when all active bans are reversed,
        landing on the latter when a timeout remains active."

        Design: Corner/consistency/immediate_consistency_after_moderation_action
        """
        channel = create_channel(handle="cs_imm", home_platform="YOUTUBE")
        viewer = create_viewer(channel["id"], handle="v_imm")

        action = issue_moderation_action(channel["id"], viewer["id"],
                                         action_kind="TIMEOUT",
                                         duration_minutes=60, reason="spam")
        immediate = get_success_data(api.get_viewer(
            viewer["id"], make_creator_headers(channel["id"])))
        assert immediate["standing"] == "TIMED_OUT", (
            "the derived standing is visible on the very next read")

        get_success_data(api.reverse_moderation_action(
            action["id"], {"reason": "overturned"},
            make_creator_headers(channel["id"])))
        restored = get_success_data(api.get_viewer(
            viewer["id"], make_creator_headers(channel["id"])))
        assert restored["standing"] == "GOOD_STANDING", (
            "reversal flips the derived standing back on the next read")
