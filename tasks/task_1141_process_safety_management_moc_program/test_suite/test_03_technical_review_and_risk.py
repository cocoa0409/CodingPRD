"""Technical review: definitive risk variants, revision cycle, reviewer guards."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    classify,
    drive_moc_to_technical_review,
    drive_unit_to_frozen_via_overdue_and_study,
    get_moc,
    get_unit,
    list_moc_reviews,
    make_reviewer_headers,
    new_draft_moc,
    new_personnel,
    open_review_round,
    resubmit,
    setup_unit_with_study,
    submit,
    submit_verdict_on_open_review,
    validate_error,
    validate_success,
    verdict_payload,
)

MANAGER = TEST_USERS["manager_headers"]


def _scenario_with_open_review(change_class="PERMANENT", severity=2, likelihood=2, **temp):
    """Unit + CURRENT study + req/rev; MOC in TECHNICAL_REVIEW. Returns ids."""
    unit, _ = setup_unit_with_study()
    req = new_personnel("Req", "E-REQ")
    rev = new_personnel("Rev", "E-REV", qualifications=["CHEMICAL"])
    moc = drive_moc_to_technical_review(unit["id"], req["id"], rev["id"],
                                        change_class=change_class, severity=severity,
                                        likelihood=likelihood, **temp)
    return unit, req, rev, moc


class TestDefinitiveVariant:
    def test_definitive_variant_recomputed_at_verdict(self, api):
        """PRD §3.3: "a base value is formed from `severity_score` times
        `likelihood_score`, capped at 25 — a product above 25 yields a base of 25;
        a detection factor is derived as one plus one quarter of (detection score
        minus one), so detection 1 yields 1.00 and each further point adds 0.25 up
        to 2.00 at detection 5; and a posture factor of 1.25 applies when the
        unit's `process_safety_index` is 70 or higher at verdict time, otherwise
        1.0. The `definitive_risk_score` is the base multiplied by the same
        change-class multiplier used at screening, multiplied by the detection
        factor, multiplied by the posture factor, rounded half-up to two decimal
        places, and the `risk_rank` is recomputed from it under the same band
        mapping as screening."
        Here: min(25, 3*3) × 1.2 × 2.00 × 1.0 = 21.60 → CRITICAL, while the
        provisional screening score on identical inputs was 10.80 (MEDIUM).

        Design: Difficulty/dual_variant_calc/moc_screening_vs_definitive_risk_score
        """
        unit, req, rev, moc = _scenario_with_open_review(
            change_class="TEMPORARY", severity=3, likelihood=3,
            temporary_start_date="2026-06-01", temporary_duration_days=180)
        assert get_unit(unit["id"])["process_safety_index"] == 0  # NORMAL → posture factor 1.0

        review = open_review_round(moc["id"])
        resp = api.submit_verdict(review["id"], verdict_payload(
            severity_score=3, likelihood_score=3, detection_score=5, verdict="ACCEPT"),
            make_reviewer_headers(rev["id"]))
        validate_success(resp, 200)

        after = get_moc(moc["id"])
        assert after["screening_risk_score"] == pytest.approx(10.80, abs=0.001)
        assert after["definitive_risk_score"] == pytest.approx(21.60, abs=0.001), (
            f"definitive must be 21.60, got {after['definitive_risk_score']}"
        )
        assert after["risk_rank"] == "CRITICAL", (
            f"rank must be recomputed from definitive (CRITICAL), got {after['risk_rank']}"
        )
        assert after["status"] == "APPROVAL_PENDING"


class TestDefinitivePostureBranch:
    def test_posture_branch_setup_reaches_frozen_at_exactly_70(self, api):
        """PRD §2.10: "fifteen points per overdue open action item, plus
        twenty-five if the study is overdue, plus twenty if a revalidation is
        required, plus ten per open high-severity incident, plus five per open
        major nonconformance — the total capped at one hundred" and "an index
        below 40 is `NORMAL`, an index of at least 40 but below 70 is
        `RESTRICTED`, and an index of 70 or higher is `FROZEN` — so exactly 40
        is `RESTRICTED` and exactly 70 is `FROZEN`."
        Three overdue P1 items (45) plus an OVERDUE study (25) land exactly on 70.

        Design: Difficulty/combinatorial_formula/definitive_risk_posture_branch_mode_a
        """
        unit, _ = setup_unit_with_study(validated_at="2026-01-15", method="WHAT_IF")
        req = new_personnel("Req", "E-REQ")
        rev = new_personnel("Rev", "E-REV", qualifications=["CHEMICAL"])
        moc = drive_moc_to_technical_review(unit["id"], req["id"], rev["id"],
                                            change_class="TEMPORARY", severity=4, likelihood=4,
                                            temporary_start_date="2026-06-01",
                                            temporary_duration_days=180)
        frozen = drive_unit_to_frozen_via_overdue_and_study(unit["id"], req["id"],
                                                            clock_iso="2027-01-11")
        assert frozen["process_safety_index"] == 70, (
            f"3*15 overdue + 25 overdue study must be exactly 70, got {frozen['process_safety_index']}"
        )
        assert frozen["psm_posture"] == "FROZEN"
        assert get_moc(moc["id"])["status"] == "TECHNICAL_REVIEW"

    def test_posture_factor_applies_at_verdict_time(self, api):
        """PRD §3.3: "a posture factor of 1.25 applies when the unit's
        `process_safety_index` is 70 or higher at verdict time, otherwise 1.0."
        With the unit driven to index 70 before the verdict: min(25, 4*4) × 1.2 ×
        (1 + 3×0.25) × 1.25 = 42.00, and a RETURN verdict loops the MOC to
        RETURNED_FOR_REVISION (PRD §3.3: "A `RETURN` verdict carries no checklist
        requirement and loops the MOC from `TECHNICAL_REVIEW` to
        `RETURNED_FOR_REVISION`").

        Design: Difficulty/combinatorial_formula/definitive_risk_posture_branch_mode_a
        """
        unit, _ = setup_unit_with_study(validated_at="2026-01-15", method="WHAT_IF")
        req = new_personnel("Req", "E-REQ")
        rev = new_personnel("Rev", "E-REV", qualifications=["CHEMICAL"])
        moc = drive_moc_to_technical_review(unit["id"], req["id"], rev["id"],
                                            change_class="TEMPORARY", severity=4, likelihood=4,
                                            temporary_start_date="2026-06-01",
                                            temporary_duration_days=180)
        drive_unit_to_frozen_via_overdue_and_study(unit["id"], req["id"], clock_iso="2027-01-11")

        review = open_review_round(moc["id"])
        resp = api.submit_verdict(review["id"], verdict_payload(
            severity_score=4, likelihood_score=4, detection_score=4, verdict="RETURN"),
            make_reviewer_headers(rev["id"]))
        validate_success(resp, 200)

        after = get_moc(moc["id"])
        assert after["definitive_risk_score"] == pytest.approx(42.00, abs=0.001), (
            f"16 × 1.2 × 1.75 × 1.25 must be 42.00, got {after['definitive_risk_score']}"
        )
        assert after["status"] == "RETURNED_FOR_REVISION"


class TestRevisionCycle:
    def test_revision_cycle_mints_fresh_open_round(self, api):
        """PRD §3.3: "A `RETURN` verdict carries no checklist requirement and
        loops the MOC from `TECHNICAL_REVIEW` to `RETURNED_FOR_REVISION`."
        PRD §3.3: "The requester resubmits from `RETURNED_FOR_REVISION` (any other
        state: `ERR_MOC_INVALID_STATE`; any other user: `ERR_NOT_RESOURCE_OWNER`),
        which moves the MOC back to `TECHNICAL_REVIEW`, increments `review_round`
        once more, and creates a fresh `OPEN` review for the new round."

        Design: Difficulty/non_linear_state_machine/moc_review_revision_cycle
        """
        unit, req, rev, moc = _scenario_with_open_review(severity=2, likelihood=2)
        r1 = open_review_round(moc["id"])

        submit_verdict_on_open_review(moc["id"], rev["id"], severity=2, likelihood=2,
                                      detection=2, verdict="RETURN", checklist_ok=False)
        assert get_moc(moc["id"])["status"] == "RETURNED_FOR_REVISION"

        resubmit(moc["id"], req["id"])
        after = get_moc(moc["id"])
        assert after["status"] == "TECHNICAL_REVIEW"
        assert after["review_round"] == 2, f"review_round must be 2 after one loop, got {after['review_round']}"

        reviews = list_moc_reviews(moc["id"])
        assert len(reviews) == 2
        assert reviews[0]["id"] == r1["id"]
        assert reviews[0]["status"] == "SUBMITTED", "the old round stays SUBMITTED"
        assert reviews[1]["round_number"] == 2
        assert reviews[1]["status"] == "OPEN"

    def test_revision_cycle_second_accept_computes_definitive(self, api):
        """PRD §3.3: the revision cycle "may repeat without bound" and after the
        fresh round's ACCEPT the MOC moves to APPROVAL_PENDING; the definitive
        score here is min(25, 2*2) × 1.0 × 1.00 × 1.0 = 4.00, which bands LOW
        ("below 5 is `LOW`", PRD §3.2).

        Design: Difficulty/non_linear_state_machine/moc_review_revision_cycle
        """
        unit, req, rev, moc = _scenario_with_open_review(severity=2, likelihood=2)
        submit_verdict_on_open_review(moc["id"], rev["id"], severity=2, likelihood=2,
                                      detection=2, verdict="RETURN", checklist_ok=False)
        resubmit(moc["id"], req["id"])
        submit_verdict_on_open_review(moc["id"], rev["id"], severity=2, likelihood=2,
                                      detection=1, verdict="ACCEPT")

        after = get_moc(moc["id"])
        assert after["status"] == "APPROVAL_PENDING"
        assert after["review_round"] == 2
        assert after["definitive_risk_score"] == pytest.approx(4.00, abs=0.001)
        assert after["risk_rank"] == "LOW"
        reviews = list_moc_reviews(moc["id"])
        assert [r["status"] for r in reviews] == ["SUBMITTED", "SUBMITTED"]


class TestVerdictGuards:
    def test_verdict_twice_on_same_review_returns_invalid_state(self, api):
        """PRD §3.3: "A `TechnicalReviewer` files a verdict on an `OPEN` review
        (`ERR_REVIEW_INVALID_STATE` otherwise)" — a SUBMITTED review is terminal,
        so a second verdict on the same review id is rejected.

        Design: Corner/state_machines/verdict_twice_on_same_review_returns_invalid_state
        """
        unit, req, rev, moc = _scenario_with_open_review()
        review = open_review_round(moc["id"])
        submit_verdict_on_open_review(moc["id"], rev["id"], verdict="ACCEPT")

        resp = api.submit_verdict(review["id"], verdict_payload(verdict="ACCEPT"),
                                  make_reviewer_headers(rev["id"]))
        validate_error(resp, ApiErrorId.ERR_REVIEW_INVALID_STATE.value)

    def test_sod_reviewer_is_requester_rejected(self, api):
        """PRD §3.3: "the reviewer must hold a qualification matching the MOC's
        `discipline` (`ERR_QUALIFICATION_MISSING`), and the reviewer must not be
        the MOC's requester (`ERR_SOD_REVIEWER_IS_REQUESTER`)" — here the reviewer
        holds the right qualification but IS the requester, so the segregation-of-
        duties error fires.

        Design: Corner/validations/sod_reviewer_is_requester_rejected
        """
        unit, _ = setup_unit_with_study()
        req = new_personnel("Req", "E-REQ", qualifications=["CHEMICAL"])
        moc = new_draft_moc(unit["id"], req["id"])
        classify(moc["id"], change_class="PERMANENT", severity=2, likelihood=2)
        submit(moc["id"], req["id"])
        review = open_review_round(moc["id"])

        resp = api.submit_verdict(review["id"], verdict_payload(verdict="ACCEPT"),
                                  make_reviewer_headers(req["id"]))
        validate_error(resp, ApiErrorId.ERR_SOD_REVIEWER_IS_REQUESTER.value)
        reviews = list_moc_reviews(moc["id"])
        assert reviews[0]["status"] == "OPEN"
        assert get_moc(moc["id"])["status"] == "TECHNICAL_REVIEW"

    def test_reviewer_qualification_missing_rejected(self, api):
        """PRD §3.3: "the reviewer must hold a qualification matching the MOC's
        `discipline` (`ERR_QUALIFICATION_MISSING`)" — a MECHANICAL-only reviewer
        cannot file a verdict on a CHEMICAL MOC.

        Design: Corner/validations/reviewer_qualification_missing_rejected
        """
        unit, _ = setup_unit_with_study()
        req = new_personnel("Req", "E-REQ")
        rev = new_personnel("Rev", "E-REV", qualifications=["MECHANICAL"])
        moc = new_draft_moc(unit["id"], req["id"], discipline="CHEMICAL")
        classify(moc["id"], change_class="PERMANENT", severity=2, likelihood=2)
        submit(moc["id"], req["id"])
        review = open_review_round(moc["id"])

        resp = api.submit_verdict(review["id"], verdict_payload(verdict="ACCEPT"),
                                  make_reviewer_headers(rev["id"]))
        validate_error(resp, ApiErrorId.ERR_QUALIFICATION_MISSING.value)
