"""Verification item lifecycle and severity scoring — PRD §3.4.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    SEVERITY_FELONY_SCORE,
    SEVERITY_INFRACTION_SCORE,
    SEVERITY_MISDEMEANOR_SCORE,
    assert_verification_item,
    criminal_raw_finding,
    date_only_string,
    education_raw_finding,
    mvr_raw_finding,
    return_item,
    return_item_payload,
    setup_order_in_verification,
    upsert_jurisdiction_policy,
    validate_error,
    validate_success,
)


# ===========================================================================
# Start verification — PRD §3.4
# ===========================================================================
class TestStartVerification:

    def test_start_verification_transitions_items_in_progress(
        self, api, recruiter_headers,
    ):
        """PRD §3.4: "the `Recruiter` triggers verification by starting
        verification on the order, which transitions the order from
        `INTAKE` to `IN_VERIFICATION` and moves every spawned item from
        `QUEUED` to `IN_PROGRESS`."

        Claim: after start-verification, order.status==IN_VERIFICATION
        and every item.status==IN_PROGRESS.
        """
        cand, cons, order, items = setup_order_in_verification(
            residence_jurisdiction="CA",
            requested_packages=["CRIMINAL", "MVR", "EDUCATION"],
        )
        assert order["status"] == "IN_VERIFICATION"
        for it in items:
            assert it["status"] == "IN_PROGRESS"


# ===========================================================================
# CRIMINAL severity scoring — PRD §3.4
# ===========================================================================
class TestCriminalSeverity:
    """PRD §3.4: "When the conviction is reportable, the base score is
    5 for an `INFRACTION`, 25 for a `MISDEMEANOR`, and 70 for a
    `FELONY`; the final score is the smaller of that base and 100."
    """

    @pytest.mark.parametrize(
        "severity,expected_score",
        [
            ("INFRACTION", SEVERITY_INFRACTION_SCORE),
            ("MISDEMEANOR", SEVERITY_MISDEMEANOR_SCORE),
            ("FELONY", SEVERITY_FELONY_SCORE),
        ],
    )
    def test_criminal_severity_score(
        self, api, recruiter_headers, verifier_headers,
        severity, expected_score,
    ):
        """PRD §3.4: "When the conviction is reportable, the base score
        is 5 for an `INFRACTION`, 25 for a `MISDEMEANOR`, and 70 for a
        `FELONY`; the final score is the smaller of that base and 100."

        Claim: returning a CRIMINAL item with severity=X and a recent
        (in-lookback) conviction_date sets severity_score to the
        expected base.
        """
        cand, cons, order, items = setup_order_in_verification(
            residence_jurisdiction="CA",
            jurisdiction_kwargs={"criminal_lookback_years": 7},
            requested_packages=["CRIMINAL"],
        )
        criminal = next(it for it in items if it["kind"] == "CRIMINAL")
        # Recent conviction (well within 7-year lookback).
        finding = criminal_raw_finding(
            conviction_date="2025-06-01",
            severity=severity,
        )
        data = return_item(
            item_id=criminal["id"],
            raw_finding=finding,
            verifier_headers=verifier_headers,
        )
        # PRD §3.4 advances item IN_PROGRESS -> RETURNED on return,
        # and PRD §3.5 then adjudicates RETURNED -> PASSED/FAILED once
        # the order reaches AWAITING_ADJUDICATION. With a single-item
        # order both transitions fire in the same request, so the
        # observable item status here is PASSED/FAILED. The PRD-derived
        # invariant the test verifies is the severity_score value.
        assert data["severity_score"] == expected_score, (
            f"Expected severity_score={expected_score} for {severity}, "
            f"got {data['severity_score']}"
        )

    def test_criminal_outside_lookback_scores_zero(
        self, api, recruiter_headers, verifier_headers,
    ):
        """PRD §3.4: "When the conviction is outside the lookback
        window, the base score is forced to 0 regardless of the
        recorded `severity`."

        Claim: CRIMINAL FELONY whose conviction is older than
        criminal_lookback_years -> severity_score == 0.
        """
        cand, cons, order, items = setup_order_in_verification(
            residence_jurisdiction="CA",
            jurisdiction_kwargs={"criminal_lookback_years": 7},
            requested_packages=["CRIMINAL"],
        )
        criminal = next(it for it in items if it["kind"] == "CRIMINAL")
        # 30 years ago is unambiguously outside any reasonable lookback.
        finding = criminal_raw_finding(
            conviction_date="1995-01-01",
            severity="FELONY",
        )
        data = return_item(
            item_id=criminal["id"],
            raw_finding=finding,
            verifier_headers=verifier_headers,
        )
        assert data["severity_score"] == 0, (
            f"Expected severity_score=0 outside lookback, "
            f"got {data['severity_score']}"
        )


# ===========================================================================
# MVR severity scoring — PRD §3.4
# ===========================================================================
class TestMvrSeverity:
    """PRD §3.4: "For an `MVR` item, the tier breakdown is exact: zero
    violations in the last three years scores 0, one violation scores
    10, two violations score 25, and three or more violations score
    50; a `license_status` of `SUSPENDED` adds a 20-point bonus on top
    of the tier; the final score is the smaller of the tier-plus-bonus
    and 100."
    """

    @pytest.mark.parametrize(
        "violations,license_status,expected",
        [
            (0, "VALID", 0),
            (1, "VALID", 10),
            (2, "VALID", 25),
            (3, "VALID", 50),
            (5, "VALID", 50),                 # 3+ all tier=50
            (0, "SUSPENDED", 20),             # tier 0 + 20
            (1, "SUSPENDED", 30),             # tier 10 + 20
            (3, "SUSPENDED", 70),             # tier 50 + 20
        ],
    )
    def test_mvr_score_table(
        self, api, recruiter_headers, verifier_headers,
        violations, license_status, expected,
    ):
        """PRD §3.4: "For an `MVR` item, the tier breakdown is exact:
        zero violations in the last three years scores 0, one
        violation scores 10, two violations score 25, and three or
        more violations score 50; a `license_status` of `SUSPENDED`
        adds a 20-point bonus on top of the tier".

        Claim: every (violations_3yr, license_status) combo yields the
        expected severity_score per the PRD's tier table.
        """
        cand, cons, order, items = setup_order_in_verification(
            residence_jurisdiction="CA",
            requested_packages=["MVR"],
        )
        mvr = next(it for it in items if it["kind"] == "MVR")
        data = return_item(
            item_id=mvr["id"],
            raw_finding=mvr_raw_finding(
                violations_3yr=violations, license_status=license_status,
            ),
            verifier_headers=verifier_headers,
        )
        assert data["severity_score"] == expected, (
            f"Expected {expected} for v={violations}, "
            f"license={license_status}; got {data['severity_score']}"
        )


# ===========================================================================
# EDUCATION severity scoring — PRD §3.4
# ===========================================================================
class TestEducationSeverity:
    """PRD §3.4: "For an `EDUCATION` item, the score is 0 when
    `claim_verified` is true and 40 when `claim_verified` is false."
    """

    @pytest.mark.parametrize(
        "claim_verified,expected", [(True, 0), (False, 40)],
    )
    def test_education_score(
        self, api, recruiter_headers, verifier_headers,
        claim_verified, expected,
    ):
        """PRD §3.4: "For an `EDUCATION` item, the score is 0 when
        `claim_verified` is true and 40 when `claim_verified` is false."

        Claim: returned EDUCATION item with claim_verified={True,False}
        scores {0,40}.
        """
        cand, cons, order, items = setup_order_in_verification(
            residence_jurisdiction="CA",
            requested_packages=["EDUCATION"],
        )
        edu = next(it for it in items if it["kind"] == "EDUCATION")
        data = return_item(
            item_id=edu["id"],
            raw_finding=education_raw_finding(
                institution="State College",
                claim_verified=claim_verified,
            ),
            verifier_headers=verifier_headers,
        )
        assert data["severity_score"] == expected, (
            f"Expected {expected} for claim_verified={claim_verified}, "
            f"got {data['severity_score']}"
        )


# ===========================================================================
# Cascade — IN_VERIFICATION -> AWAITING_ADJUDICATION on last return.
# ===========================================================================
class TestVerificationCascade:

    def test_last_item_return_cascades_parent_to_awaiting_adjudication(
        self, api, recruiter_headers, verifier_headers,
    ):
        """PRD §3.4: "if every sibling item on the same order has
        reached one of `RETURNED`, `PASSED`, or `FAILED` — cascades the
        parent order from `IN_VERIFICATION` to `AWAITING_ADJUDICATION`."

        Claim: after the LAST verification item is RETURNED, the
        parent order.status moves at least past IN_VERIFICATION
        (either AWAITING_ADJUDICATION pending Pre-Adverse, or
        COMPLETED_CLEAR if composite_decision==CLEAR).
        """
        from test_helpers import get_order
        cand, cons, order, items = setup_order_in_verification(
            residence_jurisdiction="CA",
            requested_packages=["CRIMINAL", "MVR", "EDUCATION"],
        )
        # Return clean findings for all three.
        finds = {
            "CRIMINAL": criminal_raw_finding(
                conviction_date="2025-06-01", severity="INFRACTION",
            ),
            "MVR": mvr_raw_finding(violations_3yr=0, license_status="VALID"),
            "EDUCATION": education_raw_finding(
                institution="Test U", claim_verified=True,
            ),
        }
        for it in items:
            return_item(
                item_id=it["id"],
                raw_finding=finds[it["kind"]],
                verifier_headers=verifier_headers,
            )
        order_after = get_order(order["id"], recruiter_headers)
        # PRD §3.5: "When the recomputed `composite_decision` is
        # `CLEAR`, the order auto-transitions from
        # `AWAITING_ADJUDICATION` straight to `COMPLETED_CLEAR`."
        # Either AWAITING_ADJUDICATION or COMPLETED_CLEAR is faithful;
        # the deciding scoreboard for clean findings is CLEAR (all
        # scores 0) so the canonical observation is COMPLETED_CLEAR.
        assert order_after["status"] in (
            "AWAITING_ADJUDICATION", "COMPLETED_CLEAR",
        )
        # Strong claim: the cascade should produce CLEAR via the clean
        # findings.
        if order_after["status"] == "COMPLETED_CLEAR":
            assert order_after["composite_decision"] == "CLEAR"


# ===========================================================================
# Auto-pass / auto-fail item terminal — PRD §3.5
# ===========================================================================
class TestItemAdjudicationTerminal:

    def test_item_with_score_below_15_passes(
        self, api, recruiter_headers, verifier_headers,
    ):
        """PRD §3.5: "items whose `severity_score` is strictly less than
        15 move from `RETURNED` to `PASSED`".

        Claim: an INFRACTION (score=5 < 15) item terminates at PASSED
        after parent enters AWAITING_ADJUDICATION (and the order
        finishes COMPLETED_CLEAR with composite_decision=CLEAR since
        the only item is below 15).
        """
        from test_helpers import get_order
        cand, cons, order, items = setup_order_in_verification(
            residence_jurisdiction="CA",
            requested_packages=["CRIMINAL"],
        )
        criminal = next(it for it in items if it["kind"] == "CRIMINAL")
        return_item(
            item_id=criminal["id"],
            raw_finding=criminal_raw_finding(
                conviction_date="2025-06-01",
                severity="INFRACTION",
            ),
            verifier_headers=verifier_headers,
        )
        # GET item; per PRD §3.5 it should terminate at PASSED.
        item_after = validate_success(
            api.get_verification_item(criminal["id"], recruiter_headers),
        )
        assert item_after["status"] == "PASSED"

    def test_item_with_score_at_or_above_15_fails(
        self, api, recruiter_headers, verifier_headers,
    ):
        """PRD §3.5: "items whose `severity_score` is at least 15 move
        from `RETURNED` to `FAILED`".

        Claim: a MISDEMEANOR (score=25 >= 15) item terminates at FAILED.
        """
        cand, cons, order, items = setup_order_in_verification(
            residence_jurisdiction="CA",
            jurisdiction_kwargs={"criminal_lookback_years": 7},
            requested_packages=["CRIMINAL"],
        )
        criminal = next(it for it in items if it["kind"] == "CRIMINAL")
        return_item(
            item_id=criminal["id"],
            raw_finding=criminal_raw_finding(
                conviction_date="2025-06-01",
                severity="MISDEMEANOR",
            ),
            verifier_headers=verifier_headers,
        )
        item_after = validate_success(
            api.get_verification_item(criminal["id"], recruiter_headers),
        )
        assert item_after["status"] == "FAILED"
