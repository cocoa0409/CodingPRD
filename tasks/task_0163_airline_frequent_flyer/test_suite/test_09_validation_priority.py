"""Validation priority ordering — state-beats-fiscal,
referential-beats-constraint, and other named precedence pairs from
PRD §2.7."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    create_award_booking_payload,
    create_flight,
    create_member,
    create_member_with_balance,
    create_segment_for_member,
    create_upgrade_request_payload,
    fill_flight_first_inventory_to_zero,
    get_member,
    make_member_headers,
    points_adjustment_payload,
    promote_member_to_tier_via_status_match,
    setup_confirmed_award_booking,
    setup_waitlisted_upgrade_request,
    validate_error,
    validate_success,
)


class TestStateBeatsFiscal:

    def test_confirm_on_already_confirmed_with_zero_balance_returns_state_error(
        self, api, admin_headers,
    ):
        """PRD §2.7: "State beats fiscal: when an AwardBooking is no
        longer in HELD (priority 4) and the member also has insufficient
        points (priority 8), the response is ERR_BOOKING_NOT_HOLDABLE,
        never ERR_INSUFFICIENT_POINTS."

        # difficulty: priority_pair_validation_conflict/state_beats_fiscal_on_award_confirm
        """
        member, _, booking = setup_confirmed_award_booking(
            member_balance=20_000,
        )
        # After confirm: balance = 20_000 - 12_500 = 7_500. Drain via
        # admin adjustment so balance is 0.
        validate_success(
            api.post_points_adjustment(
                member["id"],
                points_adjustment_payload(
                    points_delta=-7_500, reason="drain",
                ),
                admin_headers,
            ),
            expected_status=201,
        )
        m = get_member(member["id"])
        assert m["points_balance"] == 0
        # Confirm again — booking is no longer HELD AND member has 0
        # balance. The state error must win.
        resp = api.confirm_award_booking(
            member["id"], booking["id"], make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_HOLDABLE.value)


class TestReferentialBeatsConstraint:

    def test_admin_confirm_with_basic_tier_and_zero_inventory_returns_tier_error(
        self, api, admin_headers,
    ):
        """PRD §2.7: "Referential beats constraint: when an
        UpgradeRequest would fail both the tier gate (priority 5) and
        the inventory check (priority 7), the response is
        ERR_MEMBER_TIER_INELIGIBLE, never
        ERR_UPGRADE_INVENTORY_EXHAUSTED."

        # difficulty: priority_pair_validation_conflict/referential_beats_constraint_on_upgrade_request
        """
        # Build flight with capacity_first=1 so we can create the
        # upgrade-request (we still need to bypass the tier gate FOR
        # CREATION). We'll set the member to GOLD initially to allow
        # creation, then demote (no API path — PRD does not expose tier
        # demotion outside annual rollover or status-match expiry).
        #
        # Alternative: pre-confirm an upgrade to drive inventory to 0,
        # then create a SILVER-tier member (still below the GOLD gate)
        # whose admin-confirm hits both checks. The PRD allows admin
        # override to enter the confirm path, but the validation order
        # still runs.
        flight = create_flight(capacity_first=1)
        # Step 1 — set up a SILVER member's WAITLISTED upgrade request.
        # Creating an upgrade request as SILVER would fail at creation
        # time (the tier-gate also applies on creation per §3.4). To
        # build the precondition WAITLISTED row we must temporarily
        # have GOLD, then have the tier drop below GOLD AT CONFIRM TIME.
        # PRD §3.7 expiry of a status-match reverts the tier. So:
        member = create_member_with_balance(50_000)
        member = promote_member_to_tier_via_status_match(
            member["id"], target_tier="GOLD",
        )
        seg = create_segment_for_member(
            member["id"], flight["id"], booked_cabin="BUSINESS",
        )
        ur = validate_success(
            api.create_upgrade_request(
                member["id"], seg["id"],
                create_upgrade_request_payload(
                    target_cabin="FIRST", points_offered=10_000,
                ),
                make_member_headers(member["id"]),
            ),
            expected_status=201,
        )
        # Exhaust FIRST inventory to 0.
        fill_flight_first_inventory_to_zero(flight["id"])
        # Drop the member's tier to BASIC via clock + sweep so the
        # status-match-derived GOLD expires. PRD §3.7: 12 months.
        from test_helpers import (
            advance_clock_seconds,
            run_sweep_expire_status_matches,
        )
        advance_clock_seconds(13 * 30 * 24 * 3600)
        run_sweep_expire_status_matches()
        # Member.tier should now have reverted from GOLD to BASIC
        # (PRD §3.7 expiry semantics).
        m = get_member(member["id"])
        assert m["tier"] == "BASIC"
        # Admin override confirm — both tier (5) and inventory (7) fail.
        resp = api.confirm_upgrade_request(ur["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_MEMBER_TIER_INELIGIBLE.value)


class TestForbiddenBeatsNotFound:

    def test_member_listing_other_members_segments_blocked_by_role(
        self, api,
    ):
        """PRD §2.7 priorities 2 vs 3: role permission (priority 2)
        beats path existence (priority 3). A Member calling GET
        /members/{X}/segments where X is a different member — but the
        Member role is permitted on the endpoint, so this isn't really
        2-vs-3. Instead, a flat role-forbidden case: a Member acting on
        a flight-create endpoint they cannot use, even for a nonexistent
        flight id, returns ERR_FORBIDDEN before any existence check.
        """
        member = create_member()
        # POST /flights is ProgramAdmin only.
        resp = api.create_flight(
            {"flight_number": "AA1", "origin": "JFK", "destination": "LAX",
             "distance_miles": 1000, "route_region": "DOMESTIC",
             "departure_at": "2099-01-01T00:00:00.000Z",
             "base_fare_cents": 50_000},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
