"""Validation priority resolution, concurrency races, and RBAC ownership
guards — PRD §2.1, §2.8, §2.11."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    build_user_headers,
    create_claim,
    create_claim_payload,
    create_dependent,
    create_enrollment_payload,
    create_school,
    create_veteran,
    current_clock,
    deny_claim_for_veteran,
    grant_claim_for_veteran,
    iso_utc,
    make_rater_headers,
    make_veteran_headers,
    post_housing_payment,
    run_race,
    setup_active_enrollment,
    setup_certified_enrollment,
    setup_veteran_with_granted_claim,
    start_review_claim,
    utc_midnight,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from datetime import timedelta


# ===========================================================================
# Validation priority — PRD §2.8
# ===========================================================================
class TestValidationPriority:

    def test_business_referential_beats_invalid_rating_on_create_claim(
        self, api,
    ):
        """PRD §2.8: "then the supplemental-claim reference check
        (ERR_SUPPLEMENTAL_REFERENCE_INVALID), then enrollment term-range
        validity (ERR_INVALID_TERM_RANGE) ... then granted-rating value
        validity (ERR_INVALID_RATING) ... When two competing failures
        could fire, the lower-priority check is suppressed."

        BUT: ERR_INVALID_RATING applies_to is POST /claims/{id}/grant
        (not POST /claims). The /claims body uses proposed_rating; PRD
        §3.3 says it "is an integer in {0,...,100}" but ERR_INVALID_RATING
        is defined for granted_rating (PRD §5 entry). On POST /claims a
        proposed_rating of 37 has no explicit named error in PRD prose.
        So the priority pair the difficulty-design references is
        between ERR_SUPPLEMENTAL_REFERENCE_INVALID (priority 9) and
        whatever-error handles a bad proposed_rating on create.

        PRD silence on which error fires for an off-ladder proposed_rating
        on POST /claims (computed-field / enum-write-pathway). We
        therefore test only the supplemental-reference rule in isolation
        with a valid proposed_rating, which exercises the
        ERR_SUPPLEMENTAL_REFERENCE_INVALID precedence path.

        # difficulty: priority_pair_validation_conflict/business_referential_vs_business_temporal_conflict
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        # Need an original Claim in DENIED (not GRANTED/DENIED_FINAL).
        denied = deny_claim_for_veteran(vet["id"])
        resp = api.create_claim(
            create_claim_payload(
                veteran_id=vet["id"],
                claim_type="SUPPLEMENTAL",
                original_claim_id=denied["id"],
                proposed_rating=30,  # valid
            ),
            make_veteran_headers(vet["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SUPPLEMENTAL_REFERENCE_INVALID.value)


# ===========================================================================
# Concurrency — PRD §2.11
# ===========================================================================
class TestConcurrency:

    def test_two_simultaneous_start_review_calls_one_wins(self, api):
        """PRD §2.11: "When two raters issue start-review on the same
        SUBMITTED claim simultaneously, exactly one becomes the
        recorded rater_id; the loser receives ERR_INVALID_STATE at HTTP
        409 because the claim has already left SUBMITTED."
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        claim = create_claim(veteran_id=vet["id"], proposed_rating=30)
        results = run_race(
            lambda: api.start_review_claim(
                claim["id"], make_rater_headers("rater-A"),
            ),
            lambda: api.start_review_claim(
                claim["id"], make_rater_headers("rater-B"),
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # PRD explicitly names ERR_INVALID_STATE for the loser.
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_INVALID_STATE.value)

    def test_two_simultaneous_certify_one_wins(self, api):
        """PRD §2.11: "Two simultaneous certify attempts on the same
        SUBMITTED enrollment likewise resolve to one winner with the
        loser receiving ERR_INVALID_STATE."
        """
        # Build a SUBMITTED enrollment.
        vet = setup_veteran_with_granted_claim(granted_rating=10)
        school = create_school(program_type="PUBLIC_IN_STATE")
        base = current_clock().date() + timedelta(days=30)
        from test_helpers import create_enrollment
        enr = create_enrollment(
            veteran_id=vet["id"], school_id=school["id"],
            term_start=iso_utc(utc_midnight(base)),
            term_end=iso_utc(utc_midnight(base + timedelta(days=120))),
            tuition_charged=5000.00,
        )
        results = run_race(
            lambda: api.certify_enrollment(
                enr["id"], TEST_USERS["va_clerk_headers"],
            ),
            lambda: api.certify_enrollment(
                enr["id"], TEST_USERS["va_clerk_2_headers"],
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_INVALID_STATE.value)

    def test_duplicate_housing_payment_race_loser_already_posted(self, api):
        """PRD §2.11: "Two creations of a housing payment for the same
        (enrollment_id, month_year) pair collide on a uniqueness
        constraint and the loser receives ERR_PAYMENT_ALREADY_POSTED at
        HTTP 409."
        """
        bundle = setup_active_enrollment(
            delivery_mode="ONLINE_ONLY",
            training_time="FULL_TIME",
        )
        enr_id = bundle["enrollment"]["id"]
        ts = bundle["term_start_date"]
        month_year = f"{ts.year:04d}-{ts.month:02d}"
        results = run_race(
            lambda: api.create_housing_payment(
                enr_id, {"month_year": month_year},
                TEST_USERS["va_clerk_headers"],
            ),
            lambda: api.create_housing_payment(
                enr_id, {"month_year": month_year},
                TEST_USERS["va_clerk_2_headers"],
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_PAYMENT_ALREADY_POSTED.value)


# ===========================================================================
# RBAC ownership — PRD §2.1
# ===========================================================================
class TestVeteranOwnership:

    def test_veteran_cannot_appeal_someone_elses_claim(self, api):
        """PRD §3.3: "A denied claim can be appealed by the owning
        veteran — the appeal transition flips DENIED to APPEALED and is
        gated on the caller being the owning veteran (X-User-ID equal
        to Claim.veteran_id)."

        PRD §2.1: "any ownership mismatch is treated as a forbidden
        operation."
        """
        owner = create_veteran(aggregate_active_duty_days=1100)
        denied = deny_claim_for_veteran(owner["id"])
        other = create_veteran(aggregate_active_duty_days=1100)
        # Other veteran tries to appeal owner's claim.
        resp = api.appeal_claim(
            denied["id"], make_veteran_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_veteran_cannot_withdraw_someone_elses_enrollment(self, api):
        """PRD §3.9: "the owning veteran withdraws mid-term (their
        X-User-ID must equal the enrollment's veteran_id), moving it
        from ACTIVE to WITHDRAWN."
        """
        bundle = setup_active_enrollment(
            granted_rating=10,
            aggregate_active_duty_days=1100,
            tuition_charged=5000.00,
        )
        intruder = create_veteran(aggregate_active_duty_days=1100)
        resp = api.withdraw_enrollment(
            bundle["enrollment"]["id"],
            make_veteran_headers(intruder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_veteran_cannot_post_housing_payment(self, api):
        """PRD §4: housing-payment posting is restricted to VAClerk.
        PRD §2.1: "If the headers are well-formed but the role is not
        authorized to invoke the requested endpoint as defined in §4,
        the request is rejected with ERR_FORBIDDEN."
        """
        bundle = setup_active_enrollment(
            granted_rating=10,
            delivery_mode="ONLINE_ONLY",
            training_time="FULL_TIME",
        )
        ts = bundle["term_start_date"]
        month_year = f"{ts.year:04d}-{ts.month:02d}"
        resp = api.create_housing_payment(
            bundle["enrollment"]["id"],
            {"month_year": month_year},
            make_veteran_headers(bundle["veteran"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
