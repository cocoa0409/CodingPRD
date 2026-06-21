"""Validation priority conflicts across different error-category pairs.

PRD §2.10 fixes a deterministic priority order: auth < unauth < not_found <
state < OCC < business-safety (excluded before velocity-suspended) <
business-temporal < uniqueness < interval-overlap < single-session cap."""
import pytest

from test_helpers import (
    validate_error,
    set_clock,
    create_property,
    create_member,
    record_gaming_session,
    get_member_version,
    create_booking,
    confirm_booking,
    cancel_booking_as_manager,
    self_exclude_member,
    ApiErrorId,
    make_loyalty_manager_headers,
    bootstrap_platinum_with_pending_booking,
)


class TestStateVsBusinessSafetyExcludedAlreadyCancelledBooking:
    """PRD §2.10: state-machine eligibility check (priority 4,
    ERR_INVALID_STATE) is evaluated BEFORE the business-safety band that
    includes ERR_MEMBER_EXCLUDED. Even when both would fire, state wins."""

    def test_confirm_already_cancelled_booking_returns_invalid_state_not_excluded(
        self, api,
    ):
        """PRD §2.10: "Authentication is checked first ... then role
        authorisation ... then existence of every path-segment id and body
        foreign-key id resolved strictly left to right ..., then
        state-machine eligibility of the target resource
        (ERR_INVALID_STATE, HTTP 409), then the OCC version check on
        Member.version where applicable (ERR_STALE_MEMBER_VERSION, HTTP
        412), and only then the business-safety, business-referential,
        business-constraint, business-temporal, and business-fiscal rules
        described in §3."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_excluded_already_cancelled_booking
        """
        ctx = bootstrap_platinum_with_pending_booking(
            clock="2026-04-01T00:00:00Z",
            check_in="2026-06-01T15:00:00Z",
            check_out="2026-06-02T11:00:00Z",
        )
        # Cancel the booking so it is in a non-confirmable terminal state.
        cancel_booking_as_manager(ctx["booking"]["id"])
        # Self-exclude the member so business-safety would also fire.
        self_exclude_member(
            member_id=ctx["member"]["id"],
            exclusion_until="2027-04-02T00:00:00Z",
            reason="priority test",
        )
        # Attempt /confirm — both ERR_INVALID_STATE (state cancelled) AND
        # ERR_MEMBER_EXCLUDED would fire; state wins by priority.
        resp = api.confirm_comp_room_booking(
            ctx["booking"]["id"], make_loyalty_manager_headers("lm_1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_state_check_wins_over_excluded_on_check_in_attempt(self, api):
        """PRD §2.10: "Authentication is checked first ... then state-machine
        eligibility of the target resource (ERR_INVALID_STATE, HTTP 409),
        then the OCC version check on Member.version where applicable
        (ERR_STALE_MEMBER_VERSION, HTTP 412), and only then the
        business-safety, business-referential, business-constraint,
        business-temporal, and business-fiscal rules described in §3."

        A /check-in attempt on a PENDING (not CONFIRMED) booking whose
        Member is also EXCLUDED must surface ERR_INVALID_STATE — the state
        precondition is evaluated before the business-safety exclusion
        gate.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_excluded_already_cancelled_booking
        """
        ctx = bootstrap_platinum_with_pending_booking(
            clock="2026-04-10T00:00:00Z",
            check_in="2026-06-10T15:00:00Z",
            check_out="2026-06-11T11:00:00Z",
        )
        # Self-exclude the member; cascade cancels the PENDING booking.
        self_exclude_member(
            member_id=ctx["member"]["id"],
            exclusion_until="2027-04-11T00:00:00Z",
            reason="priority test 2",
        )
        # Booking is now CANCELLED. /check-in fails on state, not on
        # exclusion, even though the member is also EXCLUDED.
        resp = api.check_in_comp_room_booking(
            ctx["booking"]["id"], make_loyalty_manager_headers("lm_1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestBusinessSafetyVsBusinessConstraintTierEligibility:
    """PRD §3.6 + §2.10: exclusion gating (rule 6, ERR_MEMBER_EXCLUDED) is
    evaluated BEFORE tier eligibility for comp (rule 11,
    ERR_TIER_INELIGIBLE_FOR_COMP). When a member is both excluded and
    GOLD-ineligible, exclusion wins. The two error-classes are tested
    individually below, each in a setup where only one can fire."""

    def test_booking_create_for_excluded_member_returns_member_excluded(
        self, api,
    ):
        """PRD §3.6: "The booking is refused if the member is excluded
        (ERR_MEMBER_EXCLUDED), if the member is velocity-suspended
        (ERR_MEMBER_VELOCITY_SUSPENDED), if check_out is not strictly
        greater than check_in (ERR_BOOKING_INVALID_DATES), if the supplied
        member version is stale (ERR_STALE_MEMBER_VERSION)".
        PRD §3.7: "the server transitions the member's exclusion_status
        from NOT_EXCLUDED (or REINSTATED, on a repeat self-exclusion) to
        EXCLUDED".

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_constraint_excluded_overrides_tier_eligibility
        """
        set_clock("2026-04-05T00:00:00Z")
        prop = create_property()
        mem = create_member(
            property_id=prop["id"], full_name="M Pr2", email="mpr2@x.com",
        )
        # Member is GOLD by default. Self-exclude.
        self_exclude_member(
            member_id=mem["id"],
            exclusion_until="2027-04-06T00:00:00Z",
            reason="priority test2",
        )
        v = get_member_version(mem["id"])
        # Attempt to create a comp-room booking. Endpoint is gated by
        # exclusion (ERR_MEMBER_EXCLUDED).
        resp = api.create_comp_room_booking(
            {
                "member_id": mem["id"], "property_id": prop["id"],
                "check_in": "2026-07-05T15:00:00Z",
                "check_out": "2026-07-06T11:00:00Z",
                "expected_member_version": v,
            },
            make_loyalty_manager_headers("lm_1"),
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_EXCLUDED.value)

    def test_confirm_gold_member_booking_returns_tier_ineligible_for_comp(
        self, api,
    ):
        """PRD §3.6: "Confirmation is refused unless the member is not
        excluded (ERR_MEMBER_EXCLUDED), the member is not velocity-suspended
        (ERR_MEMBER_VELOCITY_SUSPENDED), and the member's tier_status is
        currently in the set PLATINUM, DIAMOND, or SEVEN_STARS — GOLD
        members are not eligible for comp rooms, and the refusal is
        ERR_TIER_INELIGIBLE_FOR_COMP."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_constraint_excluded_overrides_tier_eligibility
        """
        set_clock("2026-04-07T00:00:00Z")
        prop = create_property()
        mem = create_member(
            property_id=prop["id"], full_name="M Gold",
            email="mgold@x.com",
        )
        # GOLD member with no exclusion. Create a PENDING booking
        # (PRD §3.6 allows booking creation regardless of tier).
        v = get_member_version(mem["id"])
        booking = create_booking(
            member_id=mem["id"], property_id=prop["id"],
            expected_member_version=v,
            check_in="2026-06-05T15:00:00Z",
            check_out="2026-06-06T11:00:00Z",
        )
        # /confirm refuses GOLD with ERR_TIER_INELIGIBLE_FOR_COMP.
        resp = api.confirm_comp_room_booking(
            booking["id"], make_loyalty_manager_headers("lm_1"),
        )
        validate_error(resp, ApiErrorId.ERR_TIER_INELIGIBLE_FOR_COMP.value)
