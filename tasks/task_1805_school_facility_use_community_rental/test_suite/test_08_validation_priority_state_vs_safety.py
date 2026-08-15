"""Validation pipeline order: lifecycle state (tier 4) masks safety gates
(tier 5) on approve (PRD §2.9)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    make_booking_env, make_draft_request, submit_request, begin_review,
    api_client,
    TEST_USERS,
    ApiErrorId,
)

DIRECTOR = TEST_USERS["director_headers"]


def _submitted_with_revoked_cert(api):
    """Request SUBMITTED (never reviewed) whose sole insurance certificate is
    then REVOKED — simultaneously wrong-state and safety-violating."""
    env = make_booking_env()
    req = make_draft_request(env, event_title="Charity Auction", headcount_estimate=200,
                             starts_at="2026-12-12T01:00:00Z",
                             ends_at="2026-12-12T05:00:00Z")
    submitted = submit_request(env, req["id"])
    validate_success(api.revoke_insurance_certificate(
        env["cert"]["id"], {"reason": "Insurer cancelled policy"}, DIRECTOR))
    return env, submitted


class TestStateVsBusinessSafetyOnApprove:
    def test_approve_wrong_state_masks_insurance_violation(self, api):
        """PRD §2.9: "When several checks could reject the same request, the
        server evaluates them in a fixed priority order and surfaces the first
        failure; a failure at an earlier tier masks every later tier."
        PRD §2.9: "**Lifecycle state legality.** The target resource's current
        state must permit the operation — approval requires `UNDER_REVIEW` ... —
        else `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_approve
        """
        env, submitted = _submitted_with_revoked_cert(api)
        res = api.approve_request(
            submitted["id"], {"expected_request_version": submitted["version"]}, DIRECTOR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        after = validate_success(api.get_request(submitted["id"], DIRECTOR))
        assert after["request_status"] == "SUBMITTED"
        permits = validate_success(api.list_request_permits(submitted["id"], DIRECTOR))
        assert permits == [], "no Permit created by the rejected approval"

    def test_approve_right_state_surfaces_insurance_violation(self, api):
        """PRD §2.9: "**Safety gates: capacity and insurance.** The estimated
        headcount must fit the facility, and the renter's insurance must be valid,
        cover the full event window, and meet the headcount tier — else
        `ERR_CAPACITY_EXCEEDED` or `ERR_INSURANCE_INSUFFICIENT` (HTTP 422)."
        PRD §3.4: "The insurance gate of §3.3 must pass for a non-`INTERNAL`
        renter (else `ERR_INSURANCE_INSUFFICIENT`)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_approve
        """
        env, submitted = _submitted_with_revoked_cert(api)
        # The revoke cascade only touches UNDER_REVIEW requests; this one was
        # SUBMITTED, so begin_review moves it into UNDER_REVIEW...
        reviewed = begin_review(submitted["id"])
        assert reviewed["request_status"] == "UNDER_REVIEW"
        # ...and now, with the state tier satisfied, the safety tier surfaces.
        res = api.approve_request(
            submitted["id"], {"expected_request_version": reviewed["version"]}, DIRECTOR)
        validate_error(res, ApiErrorId.ERR_INSURANCE_INSUFFICIENT)
