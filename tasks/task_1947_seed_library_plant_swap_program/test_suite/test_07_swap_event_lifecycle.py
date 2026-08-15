"""Swap event lifecycle: buffered overlap, publish/intake corridor, cancel and
complete cascades, credit revocation/expiry, and event OCC."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_credit_conservation,
    create_member,
    create_site,
    create_swap_event,
    create_variety,
    get_credit_summary,
    publish_event,
    redeem,
    setup_intake_open_event,
    submit_and_accept,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestBufferedOverlap:
    def test_event_starting_inside_buffer_rejected_at_creation(self):
        """PRD §3.6: "each event claims an interval from thirty minutes before
        its start until thirty minutes after its end, and that buffered
        interval must not intersect any other non-`CANCELLED` event's buffered
        interval at the same site. The check is half-open — one event's
        buffered end landing exactly on another's buffered start is permitted —
        and violations are rejected with `ERR_EVENT_WINDOW_OVERLAP`. The check
        runs at creation, again at publish, and again on any reschedule that
        moves the times."

        Existing event 10:00-12:00 occupies [09:30, 12:30); a new event
        starting 12:20 intersects it.

        Design: Difficulty/resource_temporal_overlap/swap_event_buffered_interval_overlap
        """
        site = create_site()
        e1 = create_swap_event(
            site["id"],
            start_at="2026-10-10T10:00:00Z", end_at="2026-10-10T12:00:00Z",
        )
        publish_event(e1["id"])
        resp = api_client.create_swap_event(
            {
                "site_id": site["id"],
                "title": "overlap",
                "start_at": "2026-10-10T12:20:00Z",
                "end_at": "2026-10-10T13:00:00Z",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_EVENT_WINDOW_OVERLAP)

    def test_event_starting_exactly_at_buffer_end_allowed(self):
        """PRD §3.6: "The check is half-open — one event's buffered end landing
        exactly on another's buffered start is permitted — and violations are
        rejected with `ERR_EVENT_WINDOW_OVERLAP`."

        Existing event 10:00-12:00 occupies [09:30, 12:30); a new event
        starting 13:00 has buffered start exactly 12:30 — adjacent, not
        intersecting — and publishes to SCHEDULED.

        Design: Difficulty/resource_temporal_overlap/swap_event_buffered_interval_overlap
        """
        site = create_site()
        e1 = create_swap_event(
            site["id"],
            start_at="2026-10-10T10:00:00Z", end_at="2026-10-10T12:00:00Z",
        )
        publish_event(e1["id"])
        e3 = create_swap_event(
            site["id"],
            start_at="2026-10-10T13:00:00Z", end_at="2026-10-10T14:00:00Z",
        )
        published = publish_event(e3["id"])
        assert published["status"] == "SCHEDULED", (
            "buffered end == buffered start is permitted (half-open)"
        )


class TestCancelCascade:
    def _setup_event_with_two_accepted_items(self):
        ctx = setup_intake_open_event(
            start_at="2026-09-12T10:00:00Z", end_at="2026-09-12T12:00:00Z"
        )
        rare = create_variety(
            variety_name="VR", category="NATIVE", approved_zones=["ZONE_5A"],
            rarity_flag=True,
        )
        plain = create_variety(
            variety_name="VN", category="FLOWER", approved_zones=["ZONE_5A"]
        )
        member = create_member(ctx["site"]["id"])
        # rare PLANT_START/GOOD: round_half_up(5*1.0) + 2 = 7
        item1 = submit_and_accept(
            ctx["event"]["id"], member["id"], rare["id"], "PLANT_START", "GOOD"
        )
        # plain SEED_PACKET/EXCELLENT: round_half_up(2*1.5) = 3
        item2 = submit_and_accept(
            ctx["event"]["id"], member["id"], plain["id"], "SEED_PACKET",
            "EXCELLENT",
        )
        return ctx, member, item1, item2

    def test_cancel_returns_items_to_owners(self):
        """PRD §3.6: "The cancel cascade then runs in two hops: hop one moves
        every `SUBMITTED` or `ACCEPTED` item to `RETURNED_TO_OWNER`, and hop
        two, caused by each accepted item's return, appends a `REVOKED` entry
        for each member equal to everything they earned at the event,
        recomputing `credits_revoked_total` and `credits_balance`."

        Design: Difficulty/transitive_cascade/event_cancel_credit_revocation_cascade_depth2
        """
        ctx, member, item1, item2 = self._setup_event_with_two_accepted_items()
        resp = api_client.cancel_swap_event(ctx["event"]["id"], ADMIN)
        event = validate_success(resp, 200)
        assert event["status"] == "CANCELLED"
        for item in (item1, item2):
            after = validate_success(
                api_client.get_intake_item(item["id"], ADMIN), 200
            )
            assert after["status"] == "RETURNED_TO_OWNER", (
                f"hop 1: item must move to RETURNED_TO_OWNER, "
                f"got {after['status']}"
            )

    def test_cancel_revokes_earned_credits_and_preserves_earned_history(self):
        """PRD §3.6: "The cancel cascade then runs in two hops: hop one moves
        every `SUBMITTED` or `ACCEPTED` item to `RETURNED_TO_OWNER`, and hop
        two, caused by each accepted item's return, appends a `REVOKED` entry
        for each member equal to everything they earned at the event,
        recomputing `credits_revoked_total` and `credits_balance`."

        Earned history stays 10 while balance drops to 0 and revoked rises to
        10 (7 + 3).

        Design: Difficulty/transitive_cascade/event_cancel_credit_revocation_cascade_depth2
        """
        ctx, member, _, _ = self._setup_event_with_two_accepted_items()
        resp = api_client.cancel_swap_event(ctx["event"]["id"], ADMIN)
        validate_success(resp, 200)
        summary = get_credit_summary(member["id"])
        assert summary["credits_earned_total"] == 10, (
            "earned history is preserved by the cascade"
        )
        assert summary["credits_revoked_total"] == 10
        assert summary["credits_balance"] == 0
        assert_credit_conservation(summary)


class TestCreditUnitsConservation:
    def test_earn_phase_totals(self):
        """PRD §3.6: "Acceptance moves the item to `ACCEPTED` and immediately
        pays for it: a `CreditEntry` of type `EARNED` for the item's
        `credit_value` is appended against the member and scoped to the event,
        with a system-generated provenance `note`, and the member's earned
        total and balance are recomputed."

        Rare PLANT_START/GOOD (7) + plain SEED_PACKET/EXCELLENT (3) = 10.

        Design: Difficulty/compensating_invariant/credit_units_conservation_earn_then_revoke_on_cancel
        """
        ctx = setup_intake_open_event(
            start_at="2026-11-07T10:00:00Z", end_at="2026-11-07T12:00:00Z"
        )
        rare = create_variety(
            variety_name="VR", category="NATIVE", approved_zones=["ZONE_5A"],
            rarity_flag=True,
        )
        plain = create_variety(
            variety_name="VN", category="FLOWER", approved_zones=["ZONE_5A"]
        )
        member = create_member(ctx["site"]["id"])
        submit_and_accept(
            ctx["event"]["id"], member["id"], rare["id"], "PLANT_START", "GOOD"
        )
        submit_and_accept(
            ctx["event"]["id"], member["id"], plain["id"], "SEED_PACKET",
            "EXCELLENT",
        )
        summary = get_credit_summary(member["id"])
        assert summary["credits_earned_total"] == 10
        assert summary["credits_balance"] == 10
        assert_credit_conservation(summary)

    def test_cancel_appends_compensating_revoked_entries(self):
        """PRD §2.10: "For each member, the total credits ever earned at swap
        events always equal the sum of the credits redeemed, the credits
        expired, the credits revoked, and the outstanding balance; the ledger
        never loses a credit, it only reclassifies it."
        PRD §3.6: "hop two, caused by each accepted item's return, appends a
        `REVOKED` entry for each member equal to everything they earned at the
        event, recomputing `credits_revoked_total` and `credits_balance`."

        10 earned -> cancel -> 10 revoked, balance 0:
        10 == 0 redeemed + 0 expired + 10 revoked + 0 balance.

        Design: Difficulty/compensating_invariant/credit_units_conservation_earn_then_revoke_on_cancel
        """
        ctx = setup_intake_open_event(
            start_at="2026-11-07T10:00:00Z", end_at="2026-11-07T12:00:00Z"
        )
        rare = create_variety(
            variety_name="VR", category="NATIVE", approved_zones=["ZONE_5A"],
            rarity_flag=True,
        )
        plain = create_variety(
            variety_name="VN", category="FLOWER", approved_zones=["ZONE_5A"]
        )
        member = create_member(ctx["site"]["id"])
        submit_and_accept(
            ctx["event"]["id"], member["id"], rare["id"], "PLANT_START", "GOOD"
        )
        submit_and_accept(
            ctx["event"]["id"], member["id"], plain["id"], "SEED_PACKET",
            "EXCELLENT",
        )
        resp = api_client.cancel_swap_event(ctx["event"]["id"], ADMIN)
        validate_success(resp, 200)
        summary = get_credit_summary(member["id"])
        assert summary["credits_earned_total"] == 10
        assert summary["credits_redeemed_total"] == 0
        assert summary["credits_expired_total"] == 0
        assert summary["credits_revoked_total"] == 10
        assert summary["credits_balance"] == 0
        assert_credit_conservation(summary)


class TestCancelGuard:
    def test_cancel_blocked_once_redemption_exists(self):
        """PRD §3.6: "Cancellation is permitted from `SCHEDULED` or
        `INTAKE_OPEN` only and is forbidden outright — with
        `ERR_EVENT_NOT_CANCELLABLE` — once any `REDEEMED` entry exists for the
        event, because spent credit cannot be unspent."

        Design: Corner/validations/val_event_not_cancellable_after_redemption
        """
        ctx = setup_intake_open_event(
            start_at="2026-11-21T10:00:00Z", end_at="2026-11-21T12:00:00Z"
        )
        variety = create_variety(
            category="FLOWER", approved_zones=["ZONE_5A"]
        )
        member = create_member(ctx["site"]["id"])
        submit_and_accept(
            ctx["event"]["id"], member["id"], variety["id"], "SEED_PACKET",
            "GOOD",
        )
        redeem(ctx["event"]["id"], member["id"], 2)
        resp = api_client.cancel_swap_event(ctx["event"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_CANCELLABLE)


class TestCompleteCascadeAtomicity:
    def test_complete_swaps_items_and_expires_unredeemed_credits(self):
        """PRD §3.6: "Completion moves `INTAKE_CLOSED` → `COMPLETED`, flips
        every `ACCEPTED` item to `SWAPPED`, and expires the event's unredeemed
        credit: for each member with earnings scoped to the event, the expired
        increment is the earned-at-event total minus the redeemed-at-event
        total, floored at zero, and a positive increment is appended as an
        `EXPIRED` entry with the member's totals recomputed."

        Earn 7 (rare PLANT_START/GOOD), redeem 2, complete: expired 5, balance
        0, item SWAPPED — all visible immediately after the single request.

        Design: Corner/consistency_model/consistency_cascade_atomic_single_request
        """
        ctx = setup_intake_open_event(
            start_at="2027-03-06T10:00:00Z", end_at="2027-03-06T12:00:00Z"
        )
        rare = create_variety(
            variety_name="VR", category="NATIVE", approved_zones=["ZONE_5A"],
            rarity_flag=True,
        )
        member = create_member(ctx["site"]["id"])
        item = submit_and_accept(
            ctx["event"]["id"], member["id"], rare["id"], "PLANT_START", "GOOD"
        )
        assert item["credit_value"] == 7
        redeem(ctx["event"]["id"], member["id"], 2)
        resp = api_client.close_intake(ctx["event"]["id"], ADMIN)
        validate_success(resp, 200)
        resp = api_client.complete_swap_event(ctx["event"]["id"], ADMIN)
        event = validate_success(resp, 200)
        assert event["status"] == "COMPLETED"
        item_after = validate_success(
            api_client.get_intake_item(item["id"], ADMIN), 200
        )
        assert item_after["status"] == "SWAPPED"
        summary = get_credit_summary(member["id"])
        assert summary["credits_earned_total"] == 7
        assert summary["credits_redeemed_total"] == 2
        assert summary["credits_expired_total"] == 5, (
            f"max(0, 7-2) = 5 expires atomically, "
            f"got {summary['credits_expired_total']}"
        )
        assert summary["credits_balance"] == 0
        assert_credit_conservation(summary)


class TestSiteDeactivationGuard:
    def test_site_with_live_event_cannot_be_deactivated(self):
        """PRD §3.1: "moving a site from `ACTIVE` to `INACTIVE` is refused with
        `ERR_INVALID_STATE` while the site still hosts a swap event in any of
        `DRAFT`, `SCHEDULED`, `INTAKE_OPEN`, or `INTAKE_CLOSED`, and the
        reverse move from `INACTIVE` back to `ACTIVE` is unconditional."

        Design: Corner/endpoints/ep_conditional_action_site_deactivation_guarded
        """
        site = create_site(site_type="GARDEN")
        event = create_swap_event(
            site["id"],
            start_at="2027-01-09T10:00:00Z", end_at="2027-01-09T12:00:00Z",
        )
        publish_event(event["id"])
        resp = api_client.update_site(site["id"], {"status": "INACTIVE"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSwapEventOptimisticConcurrency:
    def test_stale_reschedule_rejected_fresh_reschedule_succeeds(self):
        """PRD §3.6: "While an event sits in `DRAFT` or `SCHEDULED`, an
        administrator may still rename or reschedule it under the
        optimistic-concurrency rule — the request carries
        `expected_swap_event_version`, a stale view draws `ERR_STALE_VERSION`,
        and any change to the times re-runs the overlap check".
        PRD §2.7: "A successful guarded write increments the entity's
        `version`, advancing the watermark every subsequent writer must match."

        Publish bumps the version; a PATCH carrying the pre-publish version is
        stale; a PATCH carrying the post-publish version succeeds.

        Design: Corner/cross_cutting_layers/occ_swap_event_reschedule_stale_version
        """
        site = create_site(site_type="GARDEN")
        event = create_swap_event(
            site["id"],
            start_at="2027-02-06T10:00:00Z", end_at="2027-02-06T12:00:00Z",
        )
        pre_publish_version = event["version"]
        published = publish_event(event["id"])
        assert published["version"] == pre_publish_version + 1
        resp = api_client.update_swap_event(
            event["id"],
            {
                "expected_swap_event_version": pre_publish_version,
                "title": "stale edit",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        resp = api_client.update_swap_event(
            event["id"],
            {
                "expected_swap_event_version": published["version"],
                "title": "fresh edit",
            },
            ADMIN,
        )
        updated = validate_success(resp, 200)
        assert updated["title"] == "fresh edit"
        assert updated["version"] == published["version"] + 1
