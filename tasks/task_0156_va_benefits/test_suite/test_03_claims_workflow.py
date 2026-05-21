"""Claim lifecycle, segregation of duties, and supplemental rules — PRD §3.3."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    appeal_claim,
    assert_claim,
    create_claim,
    create_claim_payload,
    create_veteran,
    deny_claim_for_veteran,
    grant_claim_for_veteran,
    make_rater_headers,
    make_veteran_headers,
    push_denied_claim_to_final,
    start_review_claim,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Filing
# ===========================================================================
class TestClaimFiling:

    def test_create_original_claim_initial_state_is_submitted(self, api):
        """PRD §3.3: "A newly filed claim begins life in SUBMITTED."
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        resp = api.create_claim(
            create_claim_payload(
                veteran_id=vet["id"],
                claim_type="ORIGINAL",
                proposed_rating=30,
            ),
            make_veteran_headers(vet["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert_claim(data)
        assert data["status"] == "SUBMITTED"
        assert data["claim_type"] == "ORIGINAL"

    def test_supplemental_without_original_claim_id_rejected(self, api):
        """PRD §3.3: "required only when claim_type is SUPPLEMENTAL —
        the original_claim_id referencing a prior claim. ... if the
        reference is missing or points to a claim in any other status
        (notably DENIED awaiting appeal), the request is rejected with
        ERR_SUPPLEMENTAL_REFERENCE_INVALID."
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        resp = api.create_claim(
            create_claim_payload(
                veteran_id=vet["id"],
                claim_type="SUPPLEMENTAL",
                proposed_rating=30,
                # original_claim_id intentionally omitted
            ),
            make_veteran_headers(vet["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SUPPLEMENTAL_REFERENCE_INVALID.value)

    def test_supplemental_against_denied_claim_rejected(self, api):
        """PRD §3.3: "A supplemental's referenced original_claim_id MUST
        point to a claim whose status is either GRANTED or DENIED_FINAL;
        if the reference is missing or points to a claim in any other
        status (notably DENIED awaiting appeal), the request is rejected
        with ERR_SUPPLEMENTAL_REFERENCE_INVALID."
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        denied = deny_claim_for_veteran(vet["id"])
        assert denied["status"] == "DENIED"
        resp = api.create_claim(
            create_claim_payload(
                veteran_id=vet["id"],
                claim_type="SUPPLEMENTAL",
                original_claim_id=denied["id"],
                proposed_rating=30,
            ),
            make_veteran_headers(vet["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SUPPLEMENTAL_REFERENCE_INVALID.value)

    def test_supplemental_against_granted_claim_accepted(self, api):
        """PRD §3.3: "A supplemental's referenced original_claim_id MUST
        point to a claim whose status is either GRANTED or DENIED_FINAL"
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        granted = grant_claim_for_veteran(vet["id"], granted_rating=30)
        assert granted["status"] == "GRANTED"
        resp = api.create_claim(
            create_claim_payload(
                veteran_id=vet["id"],
                claim_type="SUPPLEMENTAL",
                original_claim_id=granted["id"],
                proposed_rating=40,
            ),
            make_veteran_headers(vet["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert_claim(data)
        assert data["claim_type"] == "SUPPLEMENTAL"


# ===========================================================================
# State machine
# ===========================================================================
class TestClaimStateTransitions:

    def test_start_review_from_submitted(self, api):
        """PRD §3.3: "starting a review by a Rater moves a claim from
        SUBMITTED to UNDER_REVIEW and stamps the rater's X-User-ID as
        rater_id."
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        claim = create_claim(veteran_id=vet["id"], proposed_rating=30)
        resp = api.start_review_claim(
            claim["id"], make_rater_headers("rater-A"),
        )
        data = validate_success(resp)
        assert data["status"] == "UNDER_REVIEW"
        assert data.get("rater_id") == "rater-A"

    def test_grant_from_under_review(self, api):
        """PRD §3.3: "Granting the claim requires a granted_rating in
        the request body, which must be an integer in {0, 10, 20, 30,
        40, 50, 60, 70, 80, 90, 100} ... A successful grant writes
        granted_rating and decided_at on the claim".
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        claim = create_claim(veteran_id=vet["id"], proposed_rating=40)
        start_review_claim(claim["id"], rater_operator_id="rater-A")
        resp = api.grant_claim(
            claim["id"], {"granted_rating": 40},
            make_rater_headers("rater-A"),
        )
        data = validate_success(resp)
        assert data["status"] == "GRANTED"
        assert data["granted_rating"] == 40
        assert data["decided_at"] is not None

    def test_grant_with_invalid_rating_value_rejected(self, api):
        """PRD §3.3: "must be an integer in {0, 10, 20, 30, 40, 50, 60,
        70, 80, 90, 100} — any other value is rejected with
        ERR_INVALID_RATING."
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        claim = create_claim(veteran_id=vet["id"], proposed_rating=30)
        start_review_claim(claim["id"], rater_operator_id="rater-A")
        resp = api.grant_claim(
            claim["id"], {"granted_rating": 37},
            make_rater_headers("rater-A"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_RATING.value)

    def test_deny_from_under_review(self, api):
        """PRD §3.3: "Denying the claim moves it from UNDER_REVIEW to
        DENIED, stamps decided_at, and writes no rating."
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        claim = create_claim(veteran_id=vet["id"], proposed_rating=30)
        start_review_claim(claim["id"], rater_operator_id="rater-A")
        resp = api.deny_claim(claim["id"], make_rater_headers("rater-A"))
        data = validate_success(resp)
        assert data["status"] == "DENIED"
        assert data.get("granted_rating") is None
        assert data["decided_at"] is not None

    def test_start_review_on_wrong_state_returns_invalid_state(self, api):
        """PRD §2.8: "state-machine FROM-state guards
        (ERR_INVALID_STATE)" — a SUBMITTED claim cannot accept /deny,
        /grant, etc. We exercise /deny on SUBMITTED here.
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        claim = create_claim(veteran_id=vet["id"], proposed_rating=30)
        # Skip start-review — claim is still SUBMITTED.
        resp = api.deny_claim(claim["id"], make_rater_headers("rater-A"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_appeal_denied_claim_as_owning_veteran(self, api):
        """PRD §3.3: "A denied claim can be appealed by the owning
        veteran — the appeal transition flips DENIED to APPEALED and is
        gated on the caller being the owning veteran (X-User-ID equal
        to Claim.veteran_id)."
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        denied = deny_claim_for_veteran(vet["id"])
        resp = api.appeal_claim(
            denied["id"], make_veteran_headers(vet["id"]),
        )
        data = validate_success(resp)
        assert data["status"] == "APPEALED"

    def test_reappeal_path_back_to_under_review_with_different_rater(
        self, api,
    ):
        """PRD §3.3: "when a claim is in APPEALED, starting a review
        again moves it back to UNDER_REVIEW, but the rater handling the
        appealed re-review MUST have an X-User-ID different from the
        rater_id that performed the prior decision".

        # difficulty: non_linear_state_machine/claim_appeal_cycle
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        # Rater A starts review and denies.
        denied = deny_claim_for_veteran(
            vet["id"], rater_operator_id="rater-A",
        )
        appealed = appeal_claim(denied["id"], vet["id"])
        # Now Rater B (different X-User-ID) starts review again.
        resp = api.start_review_claim(
            appealed["id"], make_rater_headers("rater-B"),
        )
        data = validate_success(resp)
        assert data["status"] == "UNDER_REVIEW"
        # PRD §3.3: "On a successful re-review the rater_id is
        # overwritten with the new rater."
        assert data["rater_id"] == "rater-B"

    def test_reappeal_by_same_rater_returns_segregation_violation(self, api):
        """PRD §3.3: "a same-rater reattempt is rejected with
        ERR_SEGREGATION_VIOLATION."
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        denied = deny_claim_for_veteran(
            vet["id"], rater_operator_id="rater-A",
        )
        appeal_claim(denied["id"], vet["id"])
        resp = api.start_review_claim(
            denied["id"], make_rater_headers("rater-A"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_VIOLATION.value)


# ===========================================================================
# Segregation of duties on grant/deny
# ===========================================================================
class TestSegregationOfDuties:

    def test_reopen_by_different_rater_succeeds(self, api):
        """PRD §3.3: "A granted claim can be reopened by a different
        rater."
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        granted = grant_claim_for_veteran(
            vet["id"], granted_rating=30, starter_rater_id="rater-A",
        )
        resp = api.reopen_claim(
            granted["id"], make_rater_headers("rater-B"),
        )
        data = validate_success(resp)
        assert data["status"] == "UNDER_REVIEW"

    def test_reopen_by_same_rater_returns_segregation_violation(self, api):
        """PRD §3.3: "Reopening flips GRANTED back to UNDER_REVIEW, and
        like the appealed-claim re-review it enforces segregation: the
        rater performing the reopen MUST have an X-User-ID different
        from the rater_id already on the claim."
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        granted = grant_claim_for_veteran(
            vet["id"], granted_rating=30, starter_rater_id="rater-A",
        )
        resp = api.reopen_claim(
            granted["id"], make_rater_headers("rater-A"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_VIOLATION.value)


# ===========================================================================
# Concurrency / duplicate-supplemental — PRD §2.11
# ===========================================================================
class TestSupplementalUniqueness:

    def test_two_open_supplementals_against_same_original_rejects_second(
        self, api,
    ):
        """PRD §2.11: "Two attempts to create a supplemental claim
        against the same original claim (when the original is currently
        GRANTED) collide on a uniqueness constraint over
        (original_claim_id, status in {SUBMITTED, UNDER_REVIEW}) and
        the loser receives ERR_DUPLICATE_SUPPLEMENTAL at HTTP 409."
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        granted = grant_claim_for_veteran(vet["id"], granted_rating=30)
        first = create_claim(
            veteran_id=vet["id"], claim_type="SUPPLEMENTAL",
            original_claim_id=granted["id"], proposed_rating=40,
        )
        assert first["status"] == "SUBMITTED"
        resp = api.create_claim(
            create_claim_payload(
                veteran_id=vet["id"], claim_type="SUPPLEMENTAL",
                original_claim_id=granted["id"], proposed_rating=50,
            ),
            make_veteran_headers(vet["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SUPPLEMENTAL.value)


# ===========================================================================
# DENIED -> DENIED_FINAL via sweep — PRD §3.3 + §3.8
# ===========================================================================
class TestDeniedFinalSweep:

    def test_denied_after_365_days_promotes_to_denied_final(self, api):
        """PRD §3.3: "An unappealed denied claim becomes terminal after
        365 days: the periodic sweep advances any claim whose
        decided_at is at least 365 days in the past and which has not
        been appealed from DENIED to DENIED_FINAL."
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        denied = deny_claim_for_veteran(vet["id"])
        finalized = push_denied_claim_to_final(denied["id"])
        assert finalized["status"] == "DENIED_FINAL"
