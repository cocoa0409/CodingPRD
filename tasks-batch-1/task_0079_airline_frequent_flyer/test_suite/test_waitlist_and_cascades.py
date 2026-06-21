"""Queue A (Difficulty) — upgrade-waitlist branching, certificate cycle,
accrual/gift cascades, and boundary precision.

Covers non_linear_state_machine, transitive_cascade, boundary_precision_check,
and the seat/balance cross-entity dependency and resource-overlap instances.
"""
from test_helpers import validate_success
from test_helpers.test_users import TEST_USERS
from test_helpers.fixtures import (
    set_clock, create_member, member_headers_for, grant_status_match,
    create_companion_certificate, create_pool, current_pool_version,
    inject_qualifying_segments, inject_points, create_flown_segment, accrue_segment,
    create_pending_gift, member_version,
)
from test_helpers.factories import (
    create_award_booking_payload, create_upgrade_request_payload, create_points_gift_payload,
)

AGENT = TEST_USERS["agent_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestUpgradeBranchingFork:
    """Design rule non_linear_state_machine / upgrade_request_branching_fork."""

    def test_higher_tier_cleared_lower_tier_denied(self, api):
        """PRD §3.8: "Walking that order, each request is granted a seat
        (WAITLISTED -> CLEARED) while seats remain, consuming one seat by incrementing
        seats_cleared and decrementing seats_remaining; once the pool is exhausted,
        every remaining request is denied (WAITLISTED -> DENIED)."
        PRD §3.8: "Because the 1000-point tier gap exceeds the maximum fare weight of
        30, a higher tier always outranks a lower tier regardless of fare."

        Design: Difficulty/non_linear_state_machine/upgrade_request_branching_fork
        """
        set_clock(api, "2026-04-01T00:00:00.000Z")
        mhi = create_member(api)
        mlo = create_member(api)
        grant_status_match(api, mhi["id"], rival_tier="PLATINUM")  # effective GOLD
        pool = create_pool(api, flight_number="UA1", departure_at="2026-04-10T08:00:00.000Z", premium_capacity=1)

        v0 = current_pool_version(api, pool["id"])
        reqhi = validate_success(
            api.create_upgrade_request(
                create_upgrade_request_payload(mhi["id"], pool["id"], v0, booked_fare_class="ECONOMY"),
                member_headers_for(mhi),
            ), 201,
        )
        v1 = current_pool_version(api, pool["id"])
        reqlo = validate_success(
            api.create_upgrade_request(
                create_upgrade_request_payload(mlo["id"], pool["id"], v1, booked_fare_class="ECONOMY"),
                member_headers_for(mlo),
            ), 201,
        )
        set_clock(api, "2026-04-10T09:00:00.000Z")
        validate_success(api.clear_waitlist(pool["id"], AGENT))

        hi = validate_success(api.get_upgrade_request(reqhi["id"], AGENT))
        lo = validate_success(api.get_upgrade_request(reqlo["id"], AGENT))
        assert hi["status"] == "CLEARED", hi
        assert lo["status"] == "DENIED", lo

    def test_waitlisted_request_can_be_withdrawn(self, api):
        """PRD §3.8: "A member may withdraw their own still-waitlisted request
        (WAITLISTED -> WITHDRAWN), but only while the pool has not yet been cleared."

        Design: Difficulty/non_linear_state_machine/upgrade_request_branching_fork
        """
        set_clock(api, "2026-04-01T00:00:00.000Z")
        m = create_member(api)
        pool = create_pool(api, flight_number="UA1B", departure_at="2026-04-10T08:00:00.000Z", premium_capacity=1)
        v0 = current_pool_version(api, pool["id"])
        req = validate_success(
            api.create_upgrade_request(
                create_upgrade_request_payload(m["id"], pool["id"], v0, booked_fare_class="ECONOMY"),
                member_headers_for(m),
            ), 201,
        )
        withdrawn = validate_success(api.withdraw_upgrade_request(req["id"], member_headers_for(m)))
        assert withdrawn["status"] == "WITHDRAWN", withdrawn


class TestCompanionCertificateCycle:
    """Design rule non_linear_state_machine / companion_certificate_cycle."""

    def test_cancel_quoted_award_returns_cert_to_issued(self, api):
        """PRD §3.5: "Cancelling a still-QUOTED award (QUOTED -> CANCELLED) never
        debited points, so no refund row is written; if a certificate was attached it
        is released back to ISSUED and its attached_award_id is cleared."

        Design: Difficulty/non_linear_state_machine/companion_certificate_cycle
        """
        set_clock(api, "2026-05-01T00:00:00.000Z")
        m = create_member(api)
        cert = create_companion_certificate(
            api, m["id"], valid_from="2026-01-01T00:00:00.000Z", valid_until="2026-12-31T00:00:00.000Z"
        )
        hdrs = member_headers_for(m)
        award = validate_success(
            api.create_award_booking(
                create_award_booking_payload(m["id"], cabin="ECONOMY", pricing_mode="FIXED",
                                             companion_certificate_id=cert["id"]),
                hdrs,
            ), 201,
        )
        validate_success(api.cancel_award_booking(award["id"], hdrs))
        cert_after = validate_success(api.get_companion_certificate(cert["id"], hdrs))
        assert cert_after["status"] == "ISSUED", cert_after
        assert cert_after["attached_award_id"] is None, cert_after

    def test_attach_reserves_certificate(self, api):
        """PRD §3.5: "A valid attachment moves the certificate ISSUED -> RESERVED and
        records the new award's id as the certificate's attached_award_id, so the
        certificate is held against the quote."

        Design: Difficulty/non_linear_state_machine/companion_certificate_cycle
        """
        set_clock(api, "2026-05-01T00:00:00.000Z")
        m = create_member(api)
        cert = create_companion_certificate(
            api, m["id"], valid_from="2026-01-01T00:00:00.000Z", valid_until="2026-12-31T00:00:00.000Z"
        )
        hdrs = member_headers_for(m)
        award = validate_success(
            api.create_award_booking(
                create_award_booking_payload(m["id"], cabin="ECONOMY", pricing_mode="FIXED",
                                             companion_certificate_id=cert["id"]),
                hdrs,
            ), 201,
        )
        cert_after = validate_success(api.get_companion_certificate(cert["id"], hdrs))
        assert cert_after["status"] == "RESERVED", cert_after
        assert cert_after["attached_award_id"] == award["id"], cert_after


class TestAccrueDepth3Cascade:
    """Design rule transitive_cascade / accrue_depth3_tier_promotion."""

    def test_accrue_15th_segment_promotes_silver(self, api):
        """PRD §3.2: "If the segment is qualifying, the member's
        qualifying_segments_ytd increases by 1, which triggers a tier recomputation."
        PRD §3.4: "comparing qualifying_segments_ytd against the thresholds BASE at 0,
        SILVER at 15, GOLD at 30, and PLATINUM at 60 - a tier is reached when the count
        is at least its threshold."

        Design: Difficulty/transitive_cascade/accrue_depth3_tier_promotion
        """
        set_clock(api, "2026-06-01T00:00:00.000Z")
        m = create_member(api)
        inject_qualifying_segments(api, m["id"], 14)
        seg = create_flown_segment(
            api, m["id"], "2026-06-01T00:00:01.000Z",
            origin="SFO", destination="LAX", fare_class="BUSINESS",
            distance_miles=340, base_fare_usd=400, scheduled_departure="2026-05-20T08:00:00.000Z",
        )
        accrue_segment(api, seg["id"])
        member = validate_success(api.get_member(m["id"], ADMIN))
        assert member["qualifying_segments_ytd"] == 15, member
        assert member["tier"] == "SILVER", member
        assert member["points_balance"] > 0, member

    def test_accrue_appends_balance_increase(self, api):
        """PRD §3.2: "An ACCRUAL ledger row is appended for the member with a positive
        delta equal to the awarded points, source_type FlightSegment, and an
        expires_at of the current instant plus the expiration window (see Section
        3.6); the member's points_balance increases by that amount and
        last_activity_at is set to the current instant."

        Design: Difficulty/transitive_cascade/accrue_depth3_tier_promotion
        """
        set_clock(api, "2026-06-01T00:00:00.000Z")
        m = create_member(api)
        seg = create_flown_segment(
            api, m["id"], "2026-06-01T00:00:01.000Z",
            origin="SFO", destination="LAX", fare_class="ECONOMY",
            distance_miles=340, base_fare_usd=300, scheduled_departure="2026-05-20T08:00:00.000Z",
        )
        accrued = accrue_segment(api, seg["id"])
        member = validate_success(api.get_member(m["id"], ADMIN))
        # base=300*1.0=300; floor=170; max=300; BASE 0% -> 300
        assert accrued["points_awarded"] == 300, accrued
        assert member["points_balance"] == 300, member


class TestGiftSettleDepth2Cascade:
    """Design rule transitive_cascade / gift_settle_depth2_recipient_credit."""

    def test_settle_credits_recipient(self, api):
        """PRD §3.6: "symmetrically a GIFT_IN ledger row with a positive delta equal to
        the amount and an expires_at of the current instant plus the expiration window
        is appended on the recipient, the recipient's balance rises by the same amount
        and the recipient's last_activity_at is updated."

        Design: Difficulty/transitive_cascade/gift_settle_depth2_recipient_credit
        """
        set_clock(api, "2026-07-01T00:00:00.000Z")
        sender = create_member(api)
        recipient = create_member(api)
        inject_points(api, sender["id"], 5000)
        gift = create_pending_gift(api, sender, recipient["id"], amount=2000)
        mv = member_version(api, sender["id"])
        validate_success(
            api.settle_points_gift(gift["id"], {"expected_member_version": mv}, member_headers_for(sender))
        )
        r = validate_success(api.get_member(recipient["id"], ADMIN))
        assert r["points_balance"] == 2000, r

    def test_settle_debits_sender(self, api):
        """PRD §3.6: "a GIFT_OUT ledger row with a negative delta equal to the amount
        is appended on the sender, the sender's balance drops by the amount and the
        sender's last_activity_at is updated."

        Design: Difficulty/transitive_cascade/gift_settle_depth2_recipient_credit
        """
        set_clock(api, "2026-07-01T00:00:00.000Z")
        sender = create_member(api)
        recipient = create_member(api)
        inject_points(api, sender["id"], 5000)
        gift = create_pending_gift(api, sender, recipient["id"], amount=2000)
        mv = member_version(api, sender["id"])
        validate_success(
            api.settle_points_gift(gift["id"], {"expected_member_version": mv}, member_headers_for(sender))
        )
        s = validate_success(api.get_member(sender["id"], ADMIN))
        assert s["points_balance"] == 3000, s


class TestTierThresholdBoundary:
    """Design rule boundary_precision_check / tier_threshold_ge_boundary."""

    def test_exactly_15_promotes_silver(self, api):
        """PRD §3.4: "comparing qualifying_segments_ytd against the thresholds BASE at
        0, SILVER at 15, GOLD at 30, and PLATINUM at 60 - a tier is reached when the
        count is at least its threshold."

        Design: Difficulty/boundary_precision_check/tier_threshold_ge_boundary
        """
        set_clock(api, "2026-10-01T00:00:00.000Z")
        m = create_member(api)
        inject_qualifying_segments(api, m["id"], 14)
        seg = create_flown_segment(
            api, m["id"], "2026-10-01T00:00:01.000Z",
            origin="SFO", destination="LAX", fare_class="ECONOMY",
            distance_miles=340, base_fare_usd=200, scheduled_departure="2026-09-20T08:00:00.000Z",
        )
        accrue_segment(api, seg["id"])
        member = validate_success(api.get_member(m["id"], ADMIN))
        assert member["qualifying_segments_ytd"] == 15, member
        assert member["tier"] == "SILVER", member

    def test_14_segments_stays_base(self, api):
        """PRD §3.4: "first determine the earned tier as the highest tier whose
        qualifying-segment threshold the member has reached, comparing
        qualifying_segments_ytd against the thresholds BASE at 0, SILVER at 15, GOLD at
        30, and PLATINUM at 60 - a tier is reached when the count is at least its
        threshold."

        Design: Difficulty/boundary_precision_check/tier_threshold_ge_boundary
        """
        set_clock(api, "2026-10-01T00:00:00.000Z")
        m = create_member(api)
        inject_qualifying_segments(api, m["id"], 14)
        member = validate_success(api.get_member(m["id"], ADMIN))
        assert member["qualifying_segments_ytd"] == 14, member
        assert member["tier"] == "BASE", member


class TestEmptyWaitlistClearNoop:
    """Design rule boundary_precision_check / empty_waitlist_clear_noop."""

    def test_clear_empty_pool_leaves_capacity_intact(self, api):
        """PRD §3.8: "The invariant that cleared plus remaining always equals capacity
        holds throughout."
        PRD §3.8: "The run then marks the pool cleared."

        Design: Difficulty/boundary_precision_check/empty_waitlist_clear_noop
        """
        set_clock(api, "2026-11-01T00:00:00.000Z")
        pool = create_pool(api, flight_number="UA3", departure_at="2026-11-05T08:00:00.000Z", premium_capacity=3)
        set_clock(api, "2026-11-05T09:00:00.000Z")
        cleared = validate_success(api.clear_waitlist(pool["id"], AGENT))
        assert cleared["seats_remaining"] == 3, cleared
        assert cleared["seats_cleared"] == 0, cleared
        assert cleared["cleared"] is True, cleared

    def test_clear_empty_pool_capacity_one(self, api):
        """PRD §3.8: "The pool tracks seats_cleared (consumed seats), seats_remaining
        (capacity minus cleared seats), and a cleared flag that becomes true once the
        clearing run has executed."

        Design: Difficulty/boundary_precision_check/empty_waitlist_clear_noop
        """
        set_clock(api, "2026-11-01T00:00:00.000Z")
        pool = create_pool(api, flight_number="UA3B", departure_at="2026-11-05T08:00:00.000Z", premium_capacity=1)
        set_clock(api, "2026-11-05T09:00:00.000Z")
        cleared = validate_success(api.clear_waitlist(pool["id"], AGENT))
        assert cleared["seats_remaining"] == 1, cleared
        assert cleared["seats_cleared"] == 0, cleared
        assert cleared["cleared"] is True, cleared


class TestAwardIssueDependsOnBalance:
    """Design rule cross_entity_state_dependency / award_issue_depends_on_member_balance."""

    def test_issue_blocked_by_insufficient_balance(self, api):
        """PRD §3.5: "Issuing the award (QUOTED -> ISSUED) is owner-only and requires
        the member's points_balance to be at least the pinned points_price; an
        insufficient balance is rejected with ERR_INSUFFICIENT_POINTS."

        Design: Difficulty/cross_entity_state_dependency/award_issue_depends_on_member_balance
        """
        from test_helpers import validate_error
        set_clock(api, "2026-03-15T00:00:00.000Z")
        m = create_member(api)
        inject_points(api, m["id"], 10000)
        hdrs = member_headers_for(m)
        award = validate_success(
            api.create_award_booking(
                create_award_booking_payload(m["id"], cabin="ECONOMY", pricing_mode="FIXED"), hdrs,
            ), 201,
        )  # price 25000 > 10000
        validate_error(api.issue_award_booking(award["id"], hdrs), "ERR_INSUFFICIENT_POINTS")

    def test_issue_succeeds_with_sufficient_balance(self, api):
        """PRD §3.5: "Issuance appends a REDEMPTION ledger row with a negative delta
        equal to the pinned price (source_type AwardBooking), lowers the member's
        points_balance by that amount, and sets last_activity_at to the current
        instant."

        Design: Difficulty/cross_entity_state_dependency/award_issue_depends_on_member_balance
        """
        set_clock(api, "2026-03-15T00:00:00.000Z")
        m = create_member(api)
        inject_points(api, m["id"], 30000)
        hdrs = member_headers_for(m)
        award = validate_success(
            api.create_award_booking(
                create_award_booking_payload(m["id"], cabin="ECONOMY", pricing_mode="FIXED"), hdrs,
            ), 201,
        )
        issued = validate_success(api.issue_award_booking(award["id"], hdrs))
        assert issued["status"] == "ISSUED", issued
        member = validate_success(api.get_member(m["id"], ADMIN))
        assert member["points_balance"] == 5000, member  # 30000 - 25000


class TestUpgradeClearDependsOnSeats:
    """Design rule cross_entity_state_dependency / upgrade_clear_depends_on_pool_seats."""

    def test_zero_capacity_pool_denies_request(self, api):
        """PRD §3.8: "once the pool is exhausted, every remaining request is denied
        (WAITLISTED -> DENIED)."

        Design: Difficulty/cross_entity_state_dependency/upgrade_clear_depends_on_pool_seats
        """
        set_clock(api, "2026-04-15T00:00:00.000Z")
        m = create_member(api)
        pool = create_pool(api, flight_number="UA4", departure_at="2026-04-20T08:00:00.000Z", premium_capacity=0)
        v0 = current_pool_version(api, pool["id"])
        req = validate_success(
            api.create_upgrade_request(
                create_upgrade_request_payload(m["id"], pool["id"], v0, booked_fare_class="ECONOMY"),
                member_headers_for(m),
            ), 201,
        )
        set_clock(api, "2026-04-20T09:00:00.000Z")
        validate_success(api.clear_waitlist(pool["id"], AGENT))
        after = validate_success(api.get_upgrade_request(req["id"], AGENT))
        assert after["status"] == "DENIED", after

    def test_one_seat_clears_single_request(self, api):
        """PRD §3.8: "each request is granted a seat (WAITLISTED -> CLEARED) while
        seats remain, consuming one seat by incrementing seats_cleared and decrementing
        seats_remaining."

        Design: Difficulty/cross_entity_state_dependency/upgrade_clear_depends_on_pool_seats
        """
        set_clock(api, "2026-04-15T00:00:00.000Z")
        m = create_member(api)
        pool = create_pool(api, flight_number="UA4B", departure_at="2026-04-20T08:00:00.000Z", premium_capacity=1)
        v0 = current_pool_version(api, pool["id"])
        req = validate_success(
            api.create_upgrade_request(
                create_upgrade_request_payload(m["id"], pool["id"], v0, booked_fare_class="ECONOMY"),
                member_headers_for(m),
            ), 201,
        )
        set_clock(api, "2026-04-20T09:00:00.000Z")
        cleared_pool = validate_success(api.clear_waitlist(pool["id"], AGENT))
        after = validate_success(api.get_upgrade_request(req["id"], AGENT))
        assert after["status"] == "CLEARED", after
        assert cleared_pool["seats_cleared"] == 1 and cleared_pool["seats_remaining"] == 0, cleared_pool


class TestCompanionWindowInclusive:
    """Design rule resource_temporal_overlap / companion_window_inclusive_containment."""

    def test_attach_at_valid_until_boundary_succeeds(self, api):
        """PRD §3.5: "A companion certificate is itself issued by a ProgramAdmin to a
        member_id with a validity window bounded by its valid_from (inclusive start)
        and valid_until (inclusive end) instants, where valid_until must be strictly
        after valid_from."

        Design: Difficulty/resource_temporal_overlap/companion_window_inclusive_containment
        """
        set_clock(api, "2026-12-31T00:00:00.000Z")
        m = create_member(api)
        cert = create_companion_certificate(
            api, m["id"], valid_from="2026-01-01T00:00:00.000Z", valid_until="2026-12-31T00:00:00.000Z"
        )
        award = validate_success(
            api.create_award_booking(
                create_award_booking_payload(m["id"], cabin="ECONOMY", pricing_mode="FIXED",
                                             companion_certificate_id=cert["id"]),
                member_headers_for(m),
            ), 201,
        )
        assert award["status"] == "QUOTED", award

    def test_attach_within_window_succeeds(self, api):
        """PRD §3.5: "The attachment is only valid when the certificate is in state
        ISSUED, is owned by the acting member, and its validity window from valid_from
        through valid_until contains the award's intended travel and the current
        instant falls within that window."

        Design: Difficulty/resource_temporal_overlap/companion_window_inclusive_containment
        """
        set_clock(api, "2026-06-15T00:00:00.000Z")
        m = create_member(api)
        cert = create_companion_certificate(
            api, m["id"], valid_from="2026-01-01T00:00:00.000Z", valid_until="2026-12-31T00:00:00.000Z"
        )
        award = validate_success(
            api.create_award_booking(
                create_award_booking_payload(m["id"], cabin="ECONOMY", pricing_mode="FIXED",
                                             companion_certificate_id=cert["id"]),
                member_headers_for(m),
            ), 201,
        )
        assert award["status"] == "QUOTED", award


class TestFlightPoolAggregateCapacity:
    """Design rule resource_temporal_overlap / flightpool_aggregate_capacity_overlap."""

    def test_second_occupant_collides_with_full_capacity(self, api):
        """PRD §3.8: "once the pool is exhausted, every remaining request is denied
        (WAITLISTED -> DENIED)."
        PRD §3.8: "The invariant that cleared plus remaining always equals capacity
        holds throughout."

        Design: Difficulty/resource_temporal_overlap/flightpool_aggregate_capacity_overlap
        """
        set_clock(api, "2026-04-25T00:00:00.000Z")
        m1 = create_member(api)
        m2 = create_member(api)
        pool = create_pool(api, flight_number="UA5", departure_at="2026-04-30T08:00:00.000Z", premium_capacity=1)
        v0 = current_pool_version(api, pool["id"])
        validate_success(
            api.create_upgrade_request(
                create_upgrade_request_payload(m1["id"], pool["id"], v0, booked_fare_class="BUSINESS"),
                member_headers_for(m1),
            ), 201,
        )
        v1 = current_pool_version(api, pool["id"])
        req2 = validate_success(
            api.create_upgrade_request(
                create_upgrade_request_payload(m2["id"], pool["id"], v1, booked_fare_class="ECONOMY"),
                member_headers_for(m2),
            ), 201,
        )
        set_clock(api, "2026-04-30T09:00:00.000Z")
        cleared_pool = validate_success(api.clear_waitlist(pool["id"], AGENT))
        st2 = validate_success(api.get_upgrade_request(req2["id"], AGENT))
        assert cleared_pool["seats_cleared"] == 1 and cleared_pool["seats_remaining"] == 0, cleared_pool
        assert st2["status"] == "DENIED", st2

    def test_capacity_two_clears_both(self, api):
        """PRD §3.8: "each request is granted a seat (WAITLISTED -> CLEARED) while
        seats remain, consuming one seat by incrementing seats_cleared and decrementing
        seats_remaining."

        Design: Difficulty/resource_temporal_overlap/flightpool_aggregate_capacity_overlap
        """
        set_clock(api, "2026-04-25T00:00:00.000Z")
        m1 = create_member(api)
        m2 = create_member(api)
        pool = create_pool(api, flight_number="UA5B", departure_at="2026-04-30T08:00:00.000Z", premium_capacity=2)
        v0 = current_pool_version(api, pool["id"])
        validate_success(
            api.create_upgrade_request(
                create_upgrade_request_payload(m1["id"], pool["id"], v0, booked_fare_class="BUSINESS"),
                member_headers_for(m1),
            ), 201,
        )
        v1 = current_pool_version(api, pool["id"])
        req2 = validate_success(
            api.create_upgrade_request(
                create_upgrade_request_payload(m2["id"], pool["id"], v1, booked_fare_class="ECONOMY"),
                member_headers_for(m2),
            ), 201,
        )
        set_clock(api, "2026-04-30T09:00:00.000Z")
        cleared_pool = validate_success(api.clear_waitlist(pool["id"], AGENT))
        st2 = validate_success(api.get_upgrade_request(req2["id"], AGENT))
        assert cleared_pool["seats_cleared"] == 2 and cleared_pool["seats_remaining"] == 0, cleared_pool
        assert st2["status"] == "CLEARED", st2
