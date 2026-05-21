"""Status match — pending, approved, activate, cooling-off, expiry."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    STATUS_MATCH_BONUS_POINTS,
    STATUS_MATCH_COOLING_OFF_MONTHS,
    advance_clock_seconds,
    create_member,
    create_status_match_request_payload,
    filter_transactions_by_kind,
    get_member,
    list_points_transactions,
    make_member_headers,
    promote_member_to_tier_via_status_match,
    setup_approved_status_match,
    setup_pending_status_match,
    validate_error,
    validate_success,
)


class TestStatusMatchSubmit:

    def test_new_request_starts_in_pending(self, api):
        """PRD §3.7: "The new request enters PENDING."
        """
        member, smr = setup_pending_status_match()
        assert smr["status"] == "PENDING"


class TestStatusMatchApprove:

    def test_approve_sets_granted_fields(self, api, admin_headers):
        """PRD §3.7: "On approval, granted_tier is set to the lesser of
        competitor_tier and PLATINUM; granted_at is set to the approval
        instant; expires_at is set 12 months after granted_at; and
        cooling_off_until is set 36 months after granted_at. The
        pending request transitions to APPROVED."
        """
        member, approved = setup_approved_status_match(
            competitor_tier="GOLD",
        )
        assert approved["status"] == "APPROVED"
        assert approved["granted_tier"] == "GOLD"
        assert approved.get("granted_at") is not None
        assert approved.get("expires_at") is not None
        assert approved.get("cooling_off_until") is not None

    def test_approve_only_from_pending(self, api, admin_headers):
        """PRD §2.7 priority 4 + §3.7: "A request that is not in
        PENDING cannot be approved or rejected
        (ERR_STATUS_MATCH_NOT_PENDING)."
        """
        member, approved = setup_approved_status_match()
        resp = api.approve_status_match_request(
            member["id"], approved["id"], admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STATUS_MATCH_NOT_PENDING.value)


class TestCoolingOff:

    def test_cooling_off_blocks_new_approval(self, api, admin_headers):
        """PRD §3.7: "The cooling-off rule is a hard 36-month bar from
        the previous granted_at: no second status match can be approved
        before that instant. The bar applies independently of whether
        the previous grant has since expired, been activated, or
        remained merely APPROVED."

        # difficulty: resource_temporal_overlap/status_match_cooling_off_window_36_months
        Claim: a second approval inside the 36-month window is
        rejected with ERR_STATUS_MATCH_COOLING_OFF.
        """
        member, first = setup_approved_status_match(
            competitor_tier="GOLD",
        )
        # Submit a second status-match request from the SAME member.
        second_resp = api.create_status_match_request(
            member["id"],
            create_status_match_request_payload(
                competitor_tier="PLATINUM",
            ),
            make_member_headers(member["id"]),
        )
        second = validate_success(second_resp, expected_status=201)
        # Within the 36-month bar — approval must fail.
        resp = api.approve_status_match_request(
            member["id"], second["id"], admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STATUS_MATCH_COOLING_OFF.value)


class TestActivation:

    def test_activate_flips_tier_and_posts_bonus(self, api):
        """PRD §3.7: "Activation requires the member's current tier to
        be strictly below granted_tier ... On activation, Member.tier
        is set to granted_tier, tier_source is set to STATUS_MATCH, and
        a single STATUS_MATCH_BONUS row is appended with points_delta
        equal to 5 000 (a one-time goodwill bonus); the member's
        points_balance is incremented accordingly."
        """
        member = create_member()
        member = promote_member_to_tier_via_status_match(
            member["id"], target_tier="GOLD",
        )
        assert member["tier"] == "GOLD"
        assert member["tier_source"] == "STATUS_MATCH"
        ledger = list_points_transactions(member["id"])
        bonus_rows = filter_transactions_by_kind(ledger, "STATUS_MATCH_BONUS")
        assert len(bonus_rows) == 1
        assert bonus_rows[0]["points_delta"] == STATUS_MATCH_BONUS_POINTS
        # Balance reflects the bonus.
        assert member["points_balance"] >= STATUS_MATCH_BONUS_POINTS

    def test_activate_requires_approved_state(self, api):
        """PRD §3.7: "A request that is not in APPROVED cannot be
        activated (ERR_STATUS_MATCH_NOT_APPROVED)."
        """
        member, smr = setup_pending_status_match()
        # Not yet approved — activate should fail.
        resp = api.activate_status_match_request(
            member["id"], smr["id"],
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STATUS_MATCH_NOT_APPROVED.value)
