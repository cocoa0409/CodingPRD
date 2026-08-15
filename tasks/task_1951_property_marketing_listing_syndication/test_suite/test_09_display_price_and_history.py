"""Portal display price rounding and the listing event history: nested-rounding
order, half-up at the exact half increment, per-listing seq monotonicity, and the
price-history-head invariant (PRD §3.5, §3.7)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_price_change_payload,
    create_active_listing, create_syndicated_listing, create_portal,
    subscribe_listing, owner_headers, get_listing, get_summary,
    list_jobs_of_subscription, find_job,
    TEST_USERS,
    ApiErrorId,
)

MC = TEST_USERS["marketing_coordinator_headers"]


class TestNestedRoundingDisplayPrice:
    def _setup_two_portal_listing(self, api):
        """Listing priced 50005000 subscribed to two portals.

        Note: PRD §3.5 constrains `rounding_increment_cents` to one of 10000,
        50000, 100000, or 1000000, so the discount portal here uses 1000000 — under
        the pinned formula 50005000 * (1 - 0.037) = 48154815, divided by 1000000 is
        48.1548, which rounds half up to 48 and yields 48000000 (rounding the price
        to the increment first and discounting afterwards would give 48150000, which
        is exactly the ordering the PRD forbids)."""
        agent, active = create_active_listing(list_price_cents=50005000)
        portal_a = create_portal(discount_pct=0.037, rounding_increment_cents=1000000)
        portal_b = create_portal(rounding_increment_cents=100000)
        sub_a = subscribe_listing(active, portal_a)
        sub_b = subscribe_listing(active, portal_b)
        return agent, active, portal_a, portal_b, sub_a, sub_b

    def test_headline_is_minimum_display_price_across_subscriptions(self, api):
        """PRD §3.5: "Start from the exact, unrounded product of the listing's
        `list_price_cents` and one minus the portal's `discount_pct`. Divide that
        exact figure by the portal's `rounding_increment_cents`, round the quotient
        half up to a whole number, and multiply back by `rounding_increment_cents`;
        the result is the display price in cents."
        PRD §3.5: "The listing's `headline_display_price_cents` is the minimum
        display price across its `SUBSCRIBED` subscriptions, and null when there are
        none."

        Design: Difficulty/combinatorial_formula/portal_display_price_nested_rounding
        """
        agent, active, pa, pb, sub_a, sub_b = self._setup_two_portal_listing(api)
        summary = get_summary(active["id"])
        # Portal A: 48154815 exact -> 48000000; portal B: 50005000 -> 50000000.
        assert summary["headline_display_price_cents"] == 48000000

    def test_full_sync_jobs_snapshot_each_portal_display_price(self, api):
        """PRD §3.5: "A new subscription starts `SUBSCRIBED`, and the system
        immediately queues a `FULL_SYNC` syndication job for it, snapshotting the
        portal display price into the job's `payload_display_price_cents` at
        creation."
        PRD §3.5: "The pinned order matters — the discount is applied to the
        unrounded price and the single rounding happens at the increment division;
        rounding to the increment first and discounting afterwards would produce
        different cents and is not the contract."

        Design: Difficulty/combinatorial_formula/portal_display_price_nested_rounding
        """
        agent, active, pa, pb, sub_a, sub_b = self._setup_two_portal_listing(api)
        job_a = find_job(list_jobs_of_subscription(sub_a["id"]), job_type="FULL_SYNC")
        job_b = find_job(list_jobs_of_subscription(sub_b["id"]), job_type="FULL_SYNC")
        assert job_a["payload_display_price_cents"] == 48000000
        assert job_b["payload_display_price_cents"] == 50000000


def test_display_price_round_half_up_at_half_increment(api):
    """PRD §2.7: "Portal display prices are rounded half up exactly once as well, at
    the division by the portal's rounding increment, as detailed in §3.5."
    50000000 * (1 - 0.03) = 48500000; divided by 1000000 the quotient is exactly
    48.5, which rounds half up to 49, giving 49000000 cents.

    Design: Corner/calculations/display_price_round_half_up_at_half_increment
    """
    agent, active, portal, sub = create_syndicated_listing(
        portal_overrides={"discount_pct": 0.03, "rounding_increment_cents": 1000000})

    summary = get_summary(active["id"])
    assert summary["headline_display_price_cents"] == 49000000

    job = find_job(list_jobs_of_subscription(sub["id"]), job_type="FULL_SYNC")
    assert job["payload_display_price_cents"] == 49000000


class TestPriceHistoryHeadInvariant:
    def test_forward_and_compensating_revert_leave_no_drift(self, api):
        """PRD §3.7: "An accepted price change updates `list_price_cents`, appends a
        `PRICE_CHANGE` event capturing `old_price_cents` and `new_price_cents`,
        increments the listing's `version`"
        A forward change (50000000 -> 48000000) followed by its compensating revert
        (-> 50000000) leaves the price equal to the newest history head with zero
        drift.

        Design: Difficulty/compensating_invariant/price_history_head_revert_consistency
        """
        agent, active = create_active_listing()
        validate_success(api.create_price_change(
            active["id"], create_price_change_payload(48000000, active["version"]),
            owner_headers(agent)), 201)
        current = get_listing(active["id"])
        validate_success(api.create_price_change(
            active["id"], create_price_change_payload(50000000, current["version"]),
            owner_headers(agent)), 201)

        listing = get_listing(active["id"])
        assert listing["list_price_cents"] == 50000000

        events = get_success_data(
            api.list_listing_events(active["id"], MC, params={"event_type": "PRICE_CHANGE"}), 200)
        assert len(events) == 2
        head = max(events, key=lambda e: e["seq"])
        assert head["new_price_cents"] == listing["list_price_cents"], (
            "the listing price always equals the PRICE_CHANGE event with the highest seq"
        )

    def test_price_history_records_old_and_new_in_seq_order(self, api):
        """PRD §3.7: "The listing event history is an append-only, per-listing log
        ordered by `seq`, a monotonic sequence starting at 1 for each listing"
        PRD §3.7: "Every entry carries an `event_type` of `PRICE_CHANGE`,
        `REMARKS_UPDATE`, or `STATUS_CHANGE`, and exactly the pair of payload fields
        matching its type — `old_price_cents` and `new_price_cents` for a price
        change, `old_remarks` and `new_remarks` for a remarks update, `from_lifecycle`
        and `to_lifecycle` for a status change — with the other four fields null."

        Design: Difficulty/compensating_invariant/price_history_head_revert_consistency
        """
        agent, active = create_active_listing()
        validate_success(api.create_price_change(
            active["id"], create_price_change_payload(48000000, active["version"]),
            owner_headers(agent)), 201)
        current = get_listing(active["id"])
        validate_success(api.create_price_change(
            active["id"], create_price_change_payload(50000000, current["version"]),
            owner_headers(agent)), 201)

        events = get_success_data(
            api.list_listing_events(active["id"], MC, params={"event_type": "PRICE_CHANGE"}), 200)
        by_seq = sorted(events, key=lambda e: e["seq"])
        assert [(e["old_price_cents"], e["new_price_cents"]) for e in by_seq] == [
            (50000000, 48000000),
            (48000000, 50000000),
        ]
        for e in by_seq:
            assert e["old_remarks"] is None and e["new_remarks"] is None
            assert e["from_lifecycle"] is None and e["to_lifecycle"] is None


def test_listing_events_seq_monotonic_per_listing(api):
    """PRD §3.7: "The listing event history is an append-only, per-listing log
    ordered by `seq`, a monotonic sequence starting at 1 for each listing; entries
    are selected and ordered by the highest `seq` last."
    PRD §3.7: "Every lifecycle transition in this document appends a `STATUS_CHANGE`
    entry and increments the listing's `version` by one, so the history doubles as
    an audit trail of the listing's public life."

    Design: Corner/entities/listing_events_seq_monotonic_per_listing
    """
    agent, active = create_active_listing()
    validate_success(api.create_price_change(
        active["id"], create_price_change_payload(49500000, active["version"]),
        owner_headers(agent)), 201)

    events = get_success_data(api.list_listing_events(active["id"], MC), 200)
    assert [e["seq"] for e in events] == [1, 2, 3]
    assert [e["event_type"] for e in events] == [
        "STATUS_CHANGE",  # DRAFT -> PENDING_REVIEW (submit)
        "STATUS_CHANGE",  # PENDING_REVIEW -> ACTIVE (activate)
        "PRICE_CHANGE",   # 50000000 -> 49500000
    ]
    price_event = events[2]
    assert price_event["old_price_cents"] == 50000000
    assert price_event["new_price_cents"] == 49500000
