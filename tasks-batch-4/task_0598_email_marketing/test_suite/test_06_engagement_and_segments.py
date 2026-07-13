"""Subscriber engagement scoring (both variants) and dynamic segment membership."""
from test_helpers import (
    PLATFORM,
    add_subscriber,
    assert_segment,
    create_audience,
    create_segment,
    open_send,
    provision_tenant,
    read_subscriber,
    segments_of,
    setup_lifetime_vs_rolling_engagement,
)


class TestEngagementScoreVariants:
    def test_lifetime_score_admits_every_delivered_send_ever_received(self, api):
        """PRD §3.4: "The `LIFETIME` variant, stored on `engagement_score`, admits every delivered
        send the contact has ever received. The `ROLLING_90D` variant, stored on
        `engagement_score_90d`, admits only sends whose `delivered_at` falls on or after the instant
        90 days before the clock, and its recency term therefore sees only opens inside that window;
        a contact who clicked four months ago and merely opened last week can score 70 on the
        lifetime variant and 40 on the rolling one from identical data."
        PRD §3.4: "Within a variant, if the input set is empty, the score is 50 — the neutral value
        of an unmeasured contact. Otherwise, let the open count be the number of sends in the set
        whose `engagement_status` is `OPENED` or `CLICKED`, and the click count be the number whose
        `engagement_status` is `CLICKED`. Divide each by the size of the set to get an open rate and
        a click rate. The base is 100 multiplied by the sum of four tenths of the open rate and six
        tenths of the click rate."

        Design: Difficulty/dual_variant_calc/subscriber_engagement_lifetime_vs_rolling_90d
        """
        env = setup_lifetime_vs_rolling_engagement()

        open_send(env["new_send_id"])
        subscriber = read_subscriber(env["subscriber_id"])

        assert subscriber["delivered_send_count"] == 2
        # LIFETIME: n = 2, opens = 2, clicks = 1 -> base = 100 * (0.4 * 1.0 + 0.6 * 0.5) = 70.0;
        # recency 1.0 (opened today); volume bonus min(10, max(0, 2 - 2) * 2) = 0.
        assert subscriber["engagement_score"] == 70

    def test_rolling_90d_score_drops_the_out_of_window_click(self, api):
        """PRD §3.4: "The `LIFETIME` variant, stored on `engagement_score`, admits every delivered
        send the contact has ever received. The `ROLLING_90D` variant, stored on
        `engagement_score_90d`, admits only sends whose `delivered_at` falls on or after the instant
        90 days before the clock, and its recency term therefore sees only opens inside that window;
        a contact who clicked four months ago and merely opened last week can score 70 on the
        lifetime variant and 40 on the rolling one from identical data."
        PRD §3.4: "Otherwise the contact is `ENGAGED` when `engagement_score` is at least 70,
        `DORMANT` when it is at least 40 and below 70, and `LAPSED` when it is below 40."

        Design: Difficulty/dual_variant_calc/subscriber_engagement_lifetime_vs_rolling_90d
        """
        env = setup_lifetime_vs_rolling_engagement()

        open_send(env["new_send_id"])
        subscriber = read_subscriber(env["subscriber_id"])

        # ROLLING_90D: only the 2026-09-02 send is in window -> n = 1, opens = 1, clicks = 0
        # -> base = 100 * (0.4 * 1.0 + 0.6 * 0.0) = 40.0; recency 1.0; volume bonus 0.
        assert subscriber["engagement_score_90d"] == 40
        assert subscriber["engagement_state"] == "ENGAGED", "the state follows the lifetime score"


class TestSegmentMembership:
    def test_min_engagement_score_comparison_is_inclusive(self, api):
        """PRD §3.4: "A subscriber is a member of a segment when it belongs to the segment's own
        audience, its `consent_state` is one of the values listed in `consent_states`, its
        `engagement_score` is greater than or equal to `min_engagement_score` (the comparison is
        inclusive, so a score exactly equal to the floor qualifies), and — when `max_days_since_open`
        is not null — its `last_opened_at` is not null and the whole number of days between
        `last_opened_at` and the clock, computed by discarding any fractional remainder, is less than
        or equal to `max_days_since_open`."
        PRD §3.2: "Either way, `unsubscribed_at` and `last_opened_at` are null,
        `delivered_send_count`, `opened_send_count` and `clicked_send_count` are 0,
        `engagement_state` is `NEW`, and both `engagement_score` and `engagement_score_90d` read 50."

        Design: Corner/calculations/segment_min_engagement_score_inclusive_boundary
        """
        tenant = provision_tenant(with_author=False, with_approver=False)
        audience = create_audience(tenant, double_optin_required=False, headers=PLATFORM)
        s1 = add_subscriber(audience["id"], "s1@x.com", PLATFORM)
        add_subscriber(audience["id"], "s2@x.com", PLATFORM)
        assert s1["engagement_score"] == 50

        at_least_50 = create_segment(
            audience["id"], PLATFORM, name="AtLeast50", min_engagement_score=50
        )
        at_least_51 = create_segment(
            audience["id"], PLATFORM, name="AtLeast51", min_engagement_score=51
        )

        assert_segment(at_least_50)
        assert at_least_50["member_count"] == 2, "a score exactly equal to the floor qualifies"
        assert at_least_51["member_count"] == 0

    def test_member_count_is_recomputed_on_every_read(self, api):
        """PRD §3.4: "`member_count` is the size of that member set and is recomputed on every read
        of the segment and every time a campaign freezes its recipients."

        Design: Corner/endpoints/segment_member_count_recomputed_on_list_read
        """
        tenant = provision_tenant(with_author=False, with_approver=False)
        audience = create_audience(tenant, double_optin_required=False, headers=PLATFORM)
        add_subscriber(audience["id"], "s1@x.com", PLATFORM)
        segment = create_segment(audience["id"], PLATFORM, name="All", min_engagement_score=0)
        assert segment["member_count"] == 1

        add_subscriber(audience["id"], "s2@x.com", PLATFORM)

        listed = segments_of(audience["id"])
        assert len(listed) == 1
        assert listed[0]["member_count"] == 2, "the count is not a frozen snapshot"
