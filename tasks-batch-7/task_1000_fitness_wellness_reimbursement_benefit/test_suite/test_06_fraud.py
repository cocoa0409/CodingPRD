"""Fraud scoring variants, fraud-hold approval gate, and flag triage."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_success_data,
    record_hourly_visits,
    record_visit,
    setup_flagged_visit,
    standard_world,
    submit_claim,
    review_claim,
    validate_error,
    validate_paginated,
    validate_success,
    verify_visit,
)

ADMIN = TEST_USERS["benefits_admin_headers"]
REVIEWER = TEST_USERS["claims_reviewer_headers"]


def _provisional_setup(api):
    """Five GEO_FENCE visits v1..v5 (hourly 08:00-13:00), one MANUAL_REVIEW
    visit v6 13:00-14:00; then v1..v3 verified, v4..v5 rejected."""
    world = standard_world()
    v = record_hourly_visits(world, 5)  # 08:00..13:00
    v6 = record_visit(world, "2026-05-02T13:00:00Z", "2026-05-02T14:00:00Z",
                      verification_method="MANUAL_REVIEW")
    verify_visit(v[0]["id"])
    verify_visit(v[1]["id"])
    verify_visit(v[2]["id"])
    get_success_data(api.reject_visit(v[3]["id"], REVIEWER))
    get_success_data(api.reject_visit(v[4]["id"], REVIEWER))
    return world, v6


class TestFraudScoreProvisionalVsFinal:
    def test_provisional_counts_recorded_and_verified(self, api):
        """PRD §3.6: "The provisional variant runs when the visit is recorded:
        it builds the velocity set from visits in `RECORDED` and `VERIFIED`,
        and applies no confirmed-flag multiplier."
        PRD §3.6: "`GEOFENCE_MISMATCH` contributes 30 points when the visit's
        `verification_method` is `MANUAL_REVIEW`. `VELOCITY` contributes 10
        points for every visit beyond the fifth in the trailing seven-day
        window ending at `check_in_at`"

        Design: Difficulty/dual_variant_calc/fraud_score_provisional_vs_final
        """
        world = standard_world()
        v = record_hourly_visits(world, 5)  # five prior visits in the window
        v6 = record_visit(world, "2026-05-02T13:00:00Z", "2026-05-02T14:00:00Z",
                          verification_method="MANUAL_REVIEW")
        # 5 prior RECORDED visits -> v6 is the 6th -> 1 extra x 10, plus 30 manual.
        assert v6["fraud_score"] == 40, (
            f"provisional must be 30 + 1x10 = 40 with RECORDED visits counted, got {v6['fraud_score']}"
        )

    def test_final_counts_verified_only(self, api):
        """PRD §3.6: "The final variant runs at verification: it builds the
        velocity set from `VERIFIED` visits only, doubles any signal backed by
        a `CONFIRMED` fraud flag, and — when the result is at least 50 —
        automatically opens a fraud flag on the visit."

        Design: Difficulty/dual_variant_calc/fraud_score_provisional_vs_final
        """
        world, v6 = _provisional_setup(api)
        final = verify_visit(v6["id"])
        assert final["status"] == "VERIFIED"
        # VERIFIED-only velocity set is v1..v3 -> v6 is the 4th -> 0 extra.
        assert final["fraud_score"] == 30, (
            f"final must drop to 30 (velocity over VERIFIED-only set), got {final['fraud_score']}"
        )
        assert final["fraud_score"] != 40, "provisional 40 and final 30 must diverge"


class TestApproveFraudHoldBeatsAllowanceExceeded:
    def _setup(self, api):
        """Six VERIFIED GEO_FENCE visits; MANUAL_REVIEW visit vt verified with
        final score 50 -> OPEN flag; claim referencing vt, claimed 50000."""
        world = standard_world()
        flagged = setup_flagged_visit(world, verified_geo_count=6)
        claim = submit_claim(world, 50000, "R-FRAUD", service_date="2026-05-02T16:00:00Z",
                             visit_ids=[flagged["id"]])
        review_claim(claim["id"])
        return world, flagged, claim

    def test_final_score_50_opens_flag(self, api):
        """PRD §3.5: "Verification recomputes the final `fraud_score`, and a
        final score of 50 or more automatically opens a fraud flag on the
        visit."
        PRD §3.6: "`VELOCITY` contributes 10 points for every visit beyond the
        fifth in the trailing seven-day window ending at `check_in_at`"

        Design: Difficulty/priority_pair_validation_conflict/approve_fraud_hold_beats_allowance_exceeded
        """
        world = standard_world()
        flagged = setup_flagged_visit(world, verified_geo_count=6)
        # 6 VERIFIED priors -> 2 extra x 10 velocity + 30 manual = 50.
        assert flagged["fraud_score"] == 50, (
            f"final score must be 30 + 2x10 = 50, got {flagged['fraud_score']}"
        )
        flags, meta = validate_paginated(api.list_fraud_flags(REVIEWER, params={"visit_id": flagged["id"]}))
        assert len(flags) == 1 and flags[0]["status"] == "OPEN", (
            f"score 50 must auto-open a flag, got {flags}"
        )

    def test_fraud_hold_wins_over_allowance_exceeded(self, api):
        """PRD §3.8: "the approval gate checks, in order: the claim's
        `fraud_hold` must be false (`ERR_FRAUD_HOLD`); the enrollment must be
        `ACTIVE` (`ERR_ENROLLMENT_NOT_ACTIVE`); the funding account for the
        employer and benefit year must not be `SUSPENDED`
        (`ERR_FUNDING_NOT_ACTIVE`); and the computed payable amount must be
        positive and coverable by funding."
        PRD §3.6: "A claim's `fraud_hold` is true whenever any visit it
        references carries an `OPEN` or `CONFIRMED` flag, and a held claim
        cannot be approved"

        Design: Difficulty/priority_pair_validation_conflict/approve_fraud_hold_beats_allowance_exceeded
        """
        world, flagged, claim = self._setup(api)
        resp = api.approve_claim(claim["id"], REVIEWER)
        err = validate_error(resp, ApiErrorId.ERR_FRAUD_HOLD)
        # claimed 50000 > annual 30000, yet the safety gate fires first.
        assert err["error_id"] != "ERR_ALLOWANCE_EXCEEDED"


def test_flag_confirm_after_clear_rejected(api):
    """PRD §3.6: "Flags start `OPEN`, and a `ClaimsReviewer` may confirm or
    clear a flag only while it is `OPEN` (`ERR_FLAG_NOT_OPEN` otherwise)."

    Design: Corner/validations/flag_confirm_after_clear_rejected
    """
    world = standard_world()
    flagged = setup_flagged_visit(world, verified_geo_count=6)
    flags, _ = validate_paginated(api.list_fraud_flags(REVIEWER, params={"visit_id": flagged["id"]}))
    assert len(flags) == 1 and flags[0]["status"] == "OPEN"
    flag_id = flags[0]["id"]

    validate_success(api.clear_fraud_flag(flag_id, REVIEWER))
    resp = api.confirm_fraud_flag(flag_id, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_FLAG_NOT_OPEN)
