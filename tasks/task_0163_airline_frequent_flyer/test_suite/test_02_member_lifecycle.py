"""Member lifecycle — create, conflict, freeze/unfreeze, projected tier."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_seconds,
    assert_member,
    create_member,
    create_member_payload,
    create_member_with_balance,
    fly_one_segment,
    make_member_headers,
    promote_member_to_tier_via_status_match,
    setup_member_with_ytd_qualifying_points,
    validate_error,
    validate_success,
)


class TestMemberCreation:

    def test_new_member_defaults_per_prd(self, api, admin_headers):
        """PRD §3.1: "The new member's status is initialised to ACTIVE,
        the tier to BASIC, and the tier_source to EARNED. Both
        points_balance and the two qualifying counters start at zero."
        """
        member = create_member()
        assert_member(member)
        assert member["status"] == "ACTIVE"
        assert member["tier"] == "BASIC"
        assert member["tier_source"] == "EARNED"
        assert member["points_balance"] == 0
        assert member["current_year_qualifying_segments"] == 0
        assert member["current_year_qualifying_points"] == 0

    def test_duplicate_email_case_insensitive_rejected(self, api,
                                                       admin_headers):
        """PRD §3.1: "The email is unique case-insensitively across the
        programme; a second creation that reuses an existing address
        (in any casing) is rejected with ERR_EMAIL_CONFLICT."
        """
        first = create_member(email="alice@example.com")
        # Same email, different casing.
        payload = create_member_payload(email="ALICE@example.com")
        resp = api.create_member(payload, admin_headers)
        validate_error(resp, ApiErrorId.ERR_EMAIL_CONFLICT.value)


class TestFreezeUnfreeze:

    def test_freeze_blocks_gift_send(self, api, admin_headers):
        """PRD §3.1 + §3.6: "Frozen and closed senders or recipients
        cannot participate in gift flows; the rejection codes are
        ERR_MEMBER_FROZEN and ERR_MEMBER_CLOSED."
        """
        sender = create_member_with_balance(20_000)
        recipient = create_member()
        # Freeze sender.
        validate_success(
            api.freeze_member(sender["id"], admin_headers),
        )
        # Gift attempt should be rejected with ERR_MEMBER_FROZEN.
        resp = api.send_gift(
            sender["id"],
            {"recipient_member_id": recipient["id"], "amount": 1_500,
             "idempotency_key": "k1"},
            make_member_headers(sender["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_FROZEN.value)

    def test_freeze_blocks_recipient_gift(self, api, admin_headers):
        """PRD §3.6: "Frozen and closed senders or recipients cannot
        participate in gift flows."
        """
        sender = create_member_with_balance(20_000)
        recipient = create_member()
        validate_success(
            api.freeze_member(recipient["id"], admin_headers),
        )
        resp = api.send_gift(
            sender["id"],
            {"recipient_member_id": recipient["id"], "amount": 1_500,
             "idempotency_key": "k1"},
            make_member_headers(sender["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_FROZEN.value)

    def test_unfreeze_restores_active_status(self, api, admin_headers):
        """PRD §3.1: "A ProgramAdmin may at any time freeze a member
        (flipping status to FROZEN) or unfreeze them (flipping back to
        ACTIVE)."
        """
        member = create_member()
        validate_success(api.freeze_member(member["id"], admin_headers))
        data = validate_success(
            api.unfreeze_member(member["id"], admin_headers),
        )
        assert data["status"] == "ACTIVE"


class TestProjectedTierEoy:

    def test_projected_tier_is_higher_than_final_when_year_incomplete(
        self, api,
    ):
        """PRD §3.1: "A GET of a member also returns a
        projected_tier_eoy — the tier the member would be granted if
        their current pace held for the rest of the year. The
        projection scales the year-to-date counters linearly to a
        365-day year: project the points by multiplying
        current_year_qualifying_points by 365, dividing by the number
        of days elapsed in the year so far, and taking the floor."

        # difficulty: dual_variant_calc/tier_projected_vs_final_on_member
        Claim: with YTD points well below the PLATINUM threshold but
        early in the year, projected_tier_eoy exceeds the threshold by
        linear extrapolation.
        """
        # Bank 50_000 qualifying_points (reaches GOLD ladder at year
        # end on points). At ~day 73 / 365 ≈ 0.2 of year, the projection
        # multiplies by ~5, well past PLATINUM.
        member, _ = setup_member_with_ytd_qualifying_points(50_000)
        data = validate_success(api.get_member(member["id"],
                                                make_member_headers(member["id"])))
        # Final tier is still BASIC (no rollover yet).
        assert data["tier"] == "BASIC"
        # Projection — informational only and never writes to tier —
        # should be at least GOLD given 50_000 YTD.
        assert data["projected_tier_eoy"] in ("GOLD", "PLATINUM"), (
            "PRD §3.1: projection should scale YTD linearly; at >25%"
            " of year with 50_000 qualifying_points, projection is "
            "at least GOLD."
        )

    def test_projected_tier_eoy_returned_as_informational(self, api):
        """PRD §3.1: "The projection is informational only and never
        writes to tier."
        """
        member = create_member()
        data = validate_success(api.get_member(member["id"],
                                                make_member_headers(member["id"])))
        assert "projected_tier_eoy" in data
        # Brand-new member with zero YTD — projection equals BASIC.
        assert data["projected_tier_eoy"] == "BASIC"
        assert data["tier"] == "BASIC"


class TestMembersListing:

    def test_list_members_returns_paginated_envelope(self, api,
                                                     admin_headers):
        """PRD §2.3: "every list endpoint sorts its results by
        created_at in ascending order. The meta block of every list
        response includes limit, offset, total_count, and has_more."
        """
        # Create a few members so we have something to page.
        for _ in range(3):
            create_member()
        resp = api.list_members(admin_headers, params={"limit": 2,
                                                        "offset": 0})
        body = resp.json()
        meta = body["meta"]
        assert "limit" in meta and meta["limit"] == 2
        assert "offset" in meta and meta["offset"] == 0
        assert "total_count" in meta
        assert "has_more" in meta
