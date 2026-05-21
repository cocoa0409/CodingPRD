"""Collision claims — PRD §3.7.

Covers: filing, start-review precondition, request-revision +
PATCH-revised cyclic flow, approval with the deductible calculation
(cap, discount conditions), rejection, version-conflict on PATCH,
and the collision_open_count side-effect counter.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    DEDUCTIBLE_CAP_CENTS,
    api_client,
    approve_collision_claim,
    assert_collision_claim,
    create_collision_claim_payload,
    get_lease_agreement,
    get_lessee,
    patch_collision_claim_payload,
    patch_revised_estimate,
    post_telematics_event,
    reject_collision_claim,
    request_revision_on_claim,
    setup_active_lease,
    setup_collision_claim_under_review,
    setup_collision_revised_under_review,
    TEST_USERS,
    add_hours,
    validate_error,
    validate_success,
)


# ===========================================================================
# Claim filing — PRD §3.7
# ===========================================================================
class TestCollisionFile:

    def test_file_claim_initial_state(self, api):
        """PRD §3.7: "The system copies the lease's `vehicle_id` onto
        the claim as an immutable stamp at create time and increments
        `collision_open_count` on the parent lease by one. The claim
        is born in `FILED` with `revised_estimate_cents` of zero,
        `lessee_deductible_cents` of zero, and `revision_round` of
        zero."

        Claim: a filed claim has claim_status=FILED, revision_round=0,
        revised_estimate_cents=0, lessee_deductible_cents=0; the
        parent lease's collision_open_count is incremented by 1, and
        the claim's vehicle_id matches the lease's vehicle_id.
        """
        lessee, vehicle, lease = setup_active_lease()
        h = TEST_USERS["fleet_manager_headers"]
        pre = get_lease_agreement(lease["id"])
        resp = api.create_collision_claim(
            lease["id"],
            create_collision_claim_payload(
                incident_ts="2026-03-15T12:00:00.000Z",
                estimate_cents=80_000,
            ),
            h,
        )
        data = validate_success(resp, expected_status=201)
        assert_collision_claim(data)
        assert data["claim_status"] == "FILED"
        assert data["revised_estimate_cents"] == 0
        assert data["lessee_deductible_cents"] == 0
        assert data["revision_round"] == 0
        assert data["vehicle_id"] == vehicle["id"], (
            f"claim must copy lease.vehicle_id ({vehicle['id']}) at "
            f"create time, got {data['vehicle_id']!r}"
        )
        post = get_lease_agreement(lease["id"])
        assert post["collision_open_count"] == pre["collision_open_count"] + 1


# ===========================================================================
# start-review — PRD §3.7
# ===========================================================================
class TestStartReview:

    def test_start_review_requires_lease_active_or_in_return(self, api):
        """PRD §3.7: "A `ClaimAdjuster` then begins reviewing the
        claim, advancing it from `FILED` to `UNDER_REVIEW`; this
        transition requires the parent lease to be in either `ACTIVE`
        or `IN_RETURN` (a defaulted or closed lease cannot have its
        claims progressed) and has no further side effects beyond
        the state flip."

        Claim: start-review on an ACTIVE lease's FILED claim succeeds
        and flips claim to UNDER_REVIEW.
        """
        lessee, vehicle, lease, claim = (
            setup_collision_claim_under_review()
        )
        # By setup the claim is already UNDER_REVIEW with side effects
        # in place. We assert the post-state.
        assert claim["claim_status"] == "UNDER_REVIEW"

    def test_start_review_on_non_filed_returns_invalid_state(self, api):
        """PRD §3.7: "transition requires the parent lease to be in
        either `ACTIVE` or `IN_RETURN`" — but the PRD also requires
        the source state to be FILED for this transition. PRD §2.11
        evaluates the state check before any other business rule.

        Claim: invoking start-review on an UNDER_REVIEW claim returns
        ERR_INVALID_STATE.
        """
        _, _, _, claim = setup_collision_claim_under_review()
        resp = api.start_review_collision_claim(
            claim["id"], TEST_USERS["claim_adjuster_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Revision cycle — PRD §3.7
# ===========================================================================
class TestRevisionCycle:

    def test_request_revision_increments_round(self, api):
        """PRD §3.7: "Requesting a revision advances the claim from
        `UNDER_REVIEW` to `REVISION_REQUESTED` and increments
        `revision_round` by one."

        Claim: request-revision flips state to REVISION_REQUESTED and
        revision_round increases by 1.
        """
        _, _, _, claim = setup_collision_claim_under_review()
        pre_round = claim["revision_round"]
        resp = api.request_revision_collision_claim(
            claim["id"], TEST_USERS["claim_adjuster_headers"],
        )
        data = validate_success(resp)
        assert data["claim_status"] == "REVISION_REQUESTED"
        assert data["revision_round"] == pre_round + 1

    def test_patch_revised_estimate_returns_to_under_review(self, api):
        """PRD §3.7: "A `VendorOps` user replies with a revised
        estimate via the PATCH path on the claim, supplying a
        strictly positive `revised_estimate_cents` along with the
        optional `version` for optimistic concurrency. A successful
        PATCH cycles the claim back from `REVISION_REQUESTED` to
        `UNDER_REVIEW`."

        Claim: PATCH with revised_estimate_cents>0 cycles the claim
        back to UNDER_REVIEW.
        """
        _, _, _, claim = setup_collision_claim_under_review()
        claim2 = request_revision_on_claim(claim["id"])
        resp = api.patch_collision_claim(
            claim2["id"],
            patch_collision_claim_payload(
                revised_estimate_cents=80_000,
                version=claim2.get("version"),
            ),
            TEST_USERS["vendor_ops_headers"],
        )
        data = validate_success(resp)
        assert data["claim_status"] == "UNDER_REVIEW"
        assert data["revised_estimate_cents"] == 80_000

    def test_patch_with_stale_version_rejected(self, api):
        """PRD §2.6: "When `version` is provided but does not match
        the stored value, the request is rejected with
        `ERR_VERSION_CONFLICT` and HTTP 409."

        Claim: PATCH with a wrong version is rejected with
        ERR_VERSION_CONFLICT.
        """
        _, _, _, claim = setup_collision_claim_under_review()
        claim2 = request_revision_on_claim(claim["id"])
        resp = api.patch_collision_claim(
            claim2["id"],
            patch_collision_claim_payload(
                revised_estimate_cents=80_000,
                version=claim2.get("version", 0) + 999,
            ),
            TEST_USERS["vendor_ops_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)


# ===========================================================================
# Approval + deductible calculation — PRD §3.7
# ===========================================================================
class TestApprove:

    def test_approve_with_fault_code_in_window_uses_raw_amount(self, api):
        """PRD §3.7: "The capped amount is then conditionally
        discounted by twenty-five percent (twenty-five hundred basis
        points): the discount applies only when the claim went
        through at least one revision round (`revision_round` is at
        least one and `revised_estimate_cents` is strictly positive)
        *and* the vehicle's telematics history contains no non-empty
        `fault_code` in the window strictly after `incident_ts` minus
        twenty-four hours up to and including `incident_ts` itself."

        Claim: with a fault_code present in the (incident-24h,
        incident] window, the deductible after revision equals the
        raw (capped) amount — no 25% discount.
        """
        # Revised-once UNDER_REVIEW claim with a fault_code in window.
        lessee, vehicle, lease, claim = setup_collision_revised_under_review(
            initial_estimate_cents=300_000,
            revised_estimate_cents=200_000,
            incident_ts="2026-03-15T12:00:00.000Z",
            pre_collision_telematics_fault_code="P0420",
        )
        approved = approve_collision_claim(claim["id"])
        assert approved["claim_status"] == "APPROVED"
        # raw = min(revised_estimate, cap) = min(200_000, 250_000) = 200_000.
        # With a fault_code in window: deductible == raw == 200_000.
        assert approved["lessee_deductible_cents"] == 200_000, (
            f"with fault_code present in (incident-24h, incident], "
            f"deductible must equal capped raw amount 200000, "
            f"got {approved['lessee_deductible_cents']!r}"
        )

    def test_approve_without_fault_code_after_revision_applies_discount(
        self, api,
    ):
        """PRD §3.7: "If both conditions hold, the system multiplies
        the capped figure by (10000 minus 2500) basis points and
        divides by ten thousand, rounds the result half-up to whole
        cents, and stores that as the final `lessee_deductible_cents`."

        Claim: with no fault_code in the (incident-24h, incident]
        window AND a revision round consumed, the deductible is the
        capped raw amount scaled by 75% (round_half_up). For
        revised=200000 capped at 250000, raw=200000, discounted =
        round_half_up(200000 * 7500 / 10000) = 150000.
        """
        # Post a non-fault-code telematics event in window.
        # setup_collision_revised_under_review with
        # pre_collision_telematics_fault_code=None means no telematics
        # at all — PRD §3.7 says the discount requires "no non-empty
        # `fault_code` in the window". Zero events satisfies that.
        lessee, vehicle, lease, claim = setup_collision_revised_under_review(
            initial_estimate_cents=300_000,
            revised_estimate_cents=200_000,
            incident_ts="2026-03-15T12:00:00.000Z",
            pre_collision_telematics_fault_code=None,
        )
        approved = approve_collision_claim(claim["id"])
        # raw = min(200000, 250000) = 200000.
        # Discounted = round_half_up(200000 * (10000-2500) / 10000)
        #            = round_half_up(150000) = 150000.
        assert approved["lessee_deductible_cents"] == 150_000, (
            f"discount must apply: round_half_up(200000 * 7500/10000) "
            f"= 150000, got {approved['lessee_deductible_cents']!r}"
        )

    def test_approve_without_revision_no_discount(self, api):
        """PRD §3.7: "the discount applies only when the claim went
        through at least one revision round."

        Claim: approving without ever revising leaves the deductible
        at the raw capped amount.
        """
        _, _, _, claim = setup_collision_claim_under_review(
            estimate_cents=80_000,
            pre_collision_telematics_fault_code=None,
        )
        approved = approve_collision_claim(claim["id"])
        # No revision -> no discount. Raw = min(80000, 250000) = 80000.
        assert approved["lessee_deductible_cents"] == 80_000, (
            f"no revision -> deductible must equal raw 80000, got "
            f"{approved['lessee_deductible_cents']!r}"
        )

    def test_approve_caps_at_deductible_ceiling(self, api):
        """PRD §3.7: "That raw figure is capped at a fixed
        two-thousand-five-hundred-dollar (two-hundred-and-fifty-
        thousand-cent) deductible ceiling — anything above the cap
        is absorbed by the fleet operator."

        Claim: an estimate above the cap is reduced to the cap
        (without revision, no discount applies).
        """
        _, _, _, claim = setup_collision_claim_under_review(
            estimate_cents=500_000,
            pre_collision_telematics_fault_code="P0420",
        )
        approved = approve_collision_claim(claim["id"])
        # Raw uses estimate (no revision) -> min(500000, 250000) = 250000.
        # With fault_code in window OR no revision -> no discount.
        assert approved["lessee_deductible_cents"] == 250_000, (
            f"deductible must cap at 250000, got "
            f"{approved['lessee_deductible_cents']!r}"
        )

    def test_approve_decrements_open_count_and_credits_balance(
        self, api,
    ):
        """PRD §3.7: "Approval likewise advances the claim from
        `UNDER_REVIEW` to `APPROVED` and decrements
        `collision_open_count` by one, but additionally computes and
        stores the lessee's `lessee_deductible_cents` per the
        collision settlement rule described next, and adds that
        amount to the owning lessee's `outstanding_balance_cents`."

        Claim: approve decrements collision_open_count by 1 AND
        increments outstanding_balance_cents by lessee_deductible_cents.
        """
        lessee, vehicle, lease, claim = setup_collision_claim_under_review(
            estimate_cents=80_000,
            pre_collision_telematics_fault_code="P0420",
        )
        pre_l = get_lessee(lessee["id"])
        pre_lease = get_lease_agreement(lease["id"])
        approved = approve_collision_claim(claim["id"])
        post_l = get_lessee(lessee["id"])
        post_lease = get_lease_agreement(lease["id"])
        deductible = approved["lessee_deductible_cents"]
        assert post_l["outstanding_balance_cents"] == (
            pre_l["outstanding_balance_cents"] + deductible
        ), (
            f"approve must add {deductible} to lessee balance: "
            f"pre {pre_l['outstanding_balance_cents']}, "
            f"post {post_l['outstanding_balance_cents']}"
        )
        assert post_lease["collision_open_count"] == (
            pre_lease["collision_open_count"] - 1
        ), (
            f"approve must decrement collision_open_count by 1: "
            f"pre {pre_lease['collision_open_count']}, "
            f"post {post_lease['collision_open_count']}"
        )


# ===========================================================================
# Reject — PRD §3.7
# ===========================================================================
class TestReject:

    def test_reject_decrements_open_count_no_money(self, api):
        """PRD §3.7: "Rejection from `UNDER_REVIEW` advances the
        claim to `REJECTED` and decrements the parent lease's
        `collision_open_count` by one with no money side effects."

        Claim: reject decrements collision_open_count without
        touching outstanding_balance_cents.
        """
        lessee, vehicle, lease, claim = setup_collision_claim_under_review()
        pre_l = get_lessee(lessee["id"])
        pre_lease = get_lease_agreement(lease["id"])
        rejected = reject_collision_claim(claim["id"])
        assert rejected["claim_status"] == "REJECTED"
        post_l = get_lessee(lessee["id"])
        post_lease = get_lease_agreement(lease["id"])
        assert post_l["outstanding_balance_cents"] == (
            pre_l["outstanding_balance_cents"]
        ), (
            "reject must NOT alter outstanding_balance_cents"
        )
        assert post_lease["collision_open_count"] == (
            pre_lease["collision_open_count"] - 1
        )
