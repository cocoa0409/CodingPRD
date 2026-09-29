"""The two record-keeping score variants that differ only in which documents they see,
and the structural adequacy score at the inclusive pass threshold.

The rolling grade lets an old rejection age out of its trailing window while the lifetime
grade never forgets it, and a weighted score landing exactly on the threshold passes the
attempt where two and a half points less fails it.
"""

import pytest

from test_helpers import (
    ADEQUACY_PASS_THRESHOLD,
    assert_checkpoint_results_complete,
    assert_inspection,
    assert_rebuilder,
    checkpoint_results,
    complete_inspection,
    file_parts_document,
    read_application,
    read_parts_document,
    read_rebuilder,
    record_finding,
    reject_parts_document,
    set_clock,
    setup_completed_inspection,
    setup_draft_application,
    setup_inspection_in_progress,
    verify_parts_document,
)

# A weighted set of outcomes summing to exactly the inclusive pass threshold:
# 35 + 10 + 20 + 0 + 5.
RESULTS_SCORING_SEVENTY = checkpoint_results(
    structural_frame="PASS",
    restraint_system="MARGINAL",
    vin_integrity="PASS",
    suspension_steering="FAIL",
    lamps_glazing="MARGINAL",
)

# The nearest reachable score below the threshold: 17.5 + 20 + 20 + 0 + 10.
RESULTS_SCORING_SIXTY_SEVEN_FIFTY = checkpoint_results(
    structural_frame="MARGINAL",
    restraint_system="PASS",
    vin_integrity="PASS",
    suspension_steering="FAIL",
    lamps_glazing="PASS",
)


class TestRecordkeepingScoreVariants:
    """One rebuilder, two grades, differing only in the window they consider."""

    def test_an_aged_out_rejection_leaves_the_rolling_grade_at_one_hundred(self):
        """A rejection older than the trailing window depresses only the lifetime grade.

        PRD: "The rolling variant, published as `recordkeeping_score_rolling`, keeps only those documents whose `created_at` falls within the trailing 365-day window ending at the logical clock, inclusive at both ends, so that old rejections age out."

        Design: Difficulty/dual_variant_calc/recordkeeping_score_rolling_window_diverges_from_lifetime_cumulative
        """
        set_clock("2025-01-10T00:00:00Z")
        env = setup_draft_application(
            report_overrides={"report_effective_at": "2025-01-05T00:00:00Z"}
        )
        aged_document = file_parts_document(
            env["application_id"],
            env["rebuilder_id"],
            doc_type="RECEIPT",
            part_class="BODY_PANEL",
            source_type="NEW",
            amount_cents=40_000,
            vendor_name="Valley Body Supply",
        )
        reject_parts_document(aged_document["id"], env["inspector_id"], "ILLEGIBLE")

        set_clock("2026-08-01T00:00:00Z")
        fresh_document = file_parts_document(
            env["application_id"],
            env["rebuilder_id"],
            doc_type="PARTS_INVOICE",
            part_class="STRUCTURAL",
            source_type="NEW",
            amount_cents=200_000,
            vendor_name="OEM Frame Supply",
            part_serial_number="FR-88231",
        )
        verify_parts_document(fresh_document["id"], env["inspector_id"])

        rebuilder = read_rebuilder(env["rebuilder_id"])
        assert_rebuilder(rebuilder)
        assert rebuilder["recordkeeping_score_rolling"] == pytest.approx(100.00, abs=0.01), (
            "only the traceable verified document sits inside the trailing window, so the "
            f"rolling grade is 100.00, got {rebuilder['recordkeeping_score_rolling']}"
        )
        assert rebuilder["recordkeeping_score_lifetime"] == pytest.approx(50.00, abs=0.01), (
            "100 points over two lifetime documents is 50.00, got "
            f"{rebuilder['recordkeeping_score_lifetime']}"
        )
        assert (
            rebuilder["recordkeeping_score_lifetime"]
            < rebuilder["recordkeeping_score_rolling"]
        ), (
            "a document predating the window must leave the lifetime grade strictly lower: "
            f"{rebuilder['recordkeeping_score_lifetime']} against "
            f"{rebuilder['recordkeeping_score_rolling']}"
        )
        assert read_parts_document(aged_document["id"])["status"] == "REJECTED", (
            "the aged document stays rejected"
        )
        verified = read_parts_document(fresh_document["id"])
        assert verified["status"] == "VERIFIED", (
            f"the fresh document must be verified, got {verified['status']}"
        )
        assert verified["traceable"] is True, (
            "a document sourced NEW is traceable, got False"
        )

    def test_both_grades_agree_when_no_document_predates_the_window(self):
        """With both documents inside the window the rejection depresses both grades alike.

        PRD: "Documents that are still `SUBMITTED` and documents that are `REJECTED` earn zero points but nevertheless enter the denominator — this is the whole mechanism by which sloppy paperwork depresses the grade."

        Design: Difficulty/dual_variant_calc/recordkeeping_score_rolling_window_diverges_from_lifetime_cumulative
        """
        env = setup_draft_application()
        rejected_document = file_parts_document(
            env["application_id"],
            env["rebuilder_id"],
            doc_type="RECEIPT",
            part_class="BODY_PANEL",
            source_type="NEW",
            amount_cents=40_000,
            vendor_name="Valley Body Supply",
        )
        reject_parts_document(rejected_document["id"], env["inspector_id"], "ILLEGIBLE")
        verified_document = file_parts_document(
            env["application_id"],
            env["rebuilder_id"],
            doc_type="PARTS_INVOICE",
            part_class="STRUCTURAL",
            source_type="NEW",
            amount_cents=200_000,
            vendor_name="OEM Frame Supply",
            part_serial_number="FR-88232",
        )
        verify_parts_document(verified_document["id"], env["inspector_id"])

        rebuilder = read_rebuilder(env["rebuilder_id"])
        assert rebuilder["recordkeeping_score_rolling"] == pytest.approx(50.00, abs=0.01), (
            "the rejected document enters the rolling denominator, so the grade is 50.00, got "
            f"{rebuilder['recordkeeping_score_rolling']}"
        )
        assert rebuilder["recordkeeping_score_lifetime"] == pytest.approx(50.00, abs=0.01), (
            "the lifetime grade sees the same two documents, so it is 50.00 too, got "
            f"{rebuilder['recordkeeping_score_lifetime']}"
        )
        assert rebuilder["recordkeeping_score_rolling"] == pytest.approx(
            rebuilder["recordkeeping_score_lifetime"], abs=0.01
        ), (
            "with nothing predating the window the two variants must agree: "
            f"{rebuilder['recordkeeping_score_rolling']} against "
            f"{rebuilder['recordkeeping_score_lifetime']}"
        )
        assert (
            read_application(env["application_id"])["documented_parts_cost_cents"] == 200_000
        ), "only the verified amount is documented"


class TestAdequacyScoreAtThePassThreshold:
    """The weighted adequacy score decided against an inclusive threshold."""

    def test_score_of_exactly_seventy_passes_the_attempt(self):
        """A frame pass, two marginals and a suspension failure score 70.00 and still pass.

        PRD: "The attempt's `result` is `PASS` when none of those three conditions holds *and* `adequacy_score` is at least 70.00; the comparison is inclusive, so a score of exactly 70.00 passes."

        Design: Difficulty/boundary_precision_check/adequacy_score_exactly_seventy_passes_the_inspection
        """
        env = setup_completed_inspection(results=RESULTS_SCORING_SEVENTY)

        inspection = env["inspection"]
        assert_inspection(inspection)
        assert_checkpoint_results_complete(inspection)
        assert inspection["adequacy_score"] == pytest.approx(ADEQUACY_PASS_THRESHOLD, abs=0.01), (
            "35 plus 10 plus 20 plus 0 plus 5 must score 70.00, got "
            f"{inspection['adequacy_score']}"
        )
        assert inspection["result"] == "PASS", (
            f"a score of exactly 70.00 passes, got {inspection['result']}"
        )
        assert inspection["status"] == "COMPLETED_PASS", (
            f"a passing completion lands in COMPLETED_PASS, got {inspection['status']}"
        )
        assert inspection["vin_verified"] is True, (
            "the transcribed plate matches the vehicle's identification number"
        )
        assert inspection["forced_fail"] is False, (
            "no finding was recorded, so nothing latched the forced-fail flag"
        )

        application = read_application(env["application_id"])
        assert application["status"] == "PASSED", (
            f"a passing attempt drives the application to PASSED, got {application['status']}"
        )
        assert application["attempts_completed"] == 1, (
            f"the completed attempt must be counted, got {application['attempts_completed']}"
        )
        assert application["last_inspection_result"] == "PASS", (
            f"the application records the outcome, got {application['last_inspection_result']}"
        )

    def test_score_of_sixty_seven_point_five_fails_the_attempt(self):
        """A marginal frame outcome scores 67.50 and falls short of the threshold.

        PRD: "Each checkpoint's outcome contributes a factor: an outcome of `PASS` contributes the full weight, an outcome of `MARGINAL` contributes exactly half the weight, and an outcome of `FAIL` contributes nothing."

        Design: Difficulty/boundary_precision_check/adequacy_score_exactly_seventy_passes_the_inspection
        """
        env = setup_completed_inspection(results=RESULTS_SCORING_SIXTY_SEVEN_FIFTY)

        inspection = env["inspection"]
        assert inspection["adequacy_score"] == pytest.approx(67.50, abs=0.01), (
            "17.5 plus 20 plus 20 plus 0 plus 10 must score 67.50, got "
            f"{inspection['adequacy_score']}"
        )
        assert inspection["adequacy_score"] < ADEQUACY_PASS_THRESHOLD, (
            f"67.50 must sit below the pass threshold, got {inspection['adequacy_score']}"
        )
        assert inspection["result"] == "FAIL", (
            f"a score below 70.00 fails, got {inspection['result']}"
        )
        assert inspection["status"] == "COMPLETED_FAIL", (
            f"a failing completion lands in COMPLETED_FAIL, got {inspection['status']}"
        )
        assert inspection["vin_verified"] is True, (
            "the plate still matched, so the failure is the score's doing alone"
        )

        application = read_application(env["application_id"])
        assert application["status"] == "FAILED", (
            f"a failing attempt drives the application to FAILED, got {application['status']}"
        )
        assert application["attempts_completed"] == 1, (
            f"the failed attempt is still a completed attempt, got {application['attempts_completed']}"
        )
        assert application["last_inspection_result"] == "FAIL", (
            f"the application records the outcome, got {application['last_inspection_result']}"
        )

    def test_a_latched_forced_fail_overrides_a_score_of_exactly_seventy(self):
        """A critical finding fails the attempt even though the score lands on the threshold.

        PRD: "The first time `blocking_findings_count` reaches 1 or more, the attempt's `forced_fail` latches to true, and once latched it stays true for the remainder of that attempt and forces a `FAIL` result no matter what the adequacy arithmetic says."

        Design: Difficulty/boundary_precision_check/adequacy_score_exactly_seventy_passes_the_inspection
        """
        env = setup_inspection_in_progress()
        record_finding(
            env["inspection_id"],
            env["inspector_id"],
            category="STRUCTURAL_INADEQUACY",
            severity="CRITICAL",
            description="frame rail weld does not meet the published repair standard",
        )

        inspection = complete_inspection(
            env["inspection_id"],
            env["inspector_id"],
            env["vin"],
            RESULTS_SCORING_SEVENTY,
        )

        assert inspection["adequacy_score"] == pytest.approx(ADEQUACY_PASS_THRESHOLD, abs=0.01), (
            "the same outcomes still score 70.00, got "
            f"{inspection['adequacy_score']}"
        )
        assert inspection["forced_fail"] is True, (
            "a critical finding latches the forced-fail flag"
        )
        assert inspection["blocking_findings_count"] == 1, (
            f"the critical finding is blocking, got {inspection['blocking_findings_count']}"
        )
        assert inspection["result"] == "FAIL", (
            "the latched flag forces a failure regardless of the score, got "
            f"{inspection['result']}"
        )
        assert inspection["status"] == "COMPLETED_FAIL", (
            f"the attempt closes as COMPLETED_FAIL, got {inspection['status']}"
        )
        assert read_application(env["application_id"])["status"] == "FAILED", (
            "the application follows the failing attempt to FAILED"
        )
