"""Applicant risk score: provisional-in-review variant excluding PENDING
streams; final-complete variant once all three streams report; rounding
order pinned per PRD §3.7 (round-then-sum, two decimals at every step).
"""
import pytest

from test_helpers import (
    validate_success,
    order_complete_with_results, order_with_three_pending_verifications,
    make_recruiter_headers, CO,
)
from test_helpers.fixtures import report_verification


def test_risk_score_provisional_is_zero_then_final_crosses_threshold_after_criminal_fail(api):
    """While the order is IN_REVIEW the provisional variant excludes the
    still-PENDING CRIMINAL stream and the partial score is 0.00 (below the
    0.50 threshold). Once CRIMINAL reports FAIL the order becomes COMPLETE
    and the final-complete variant sums all three contributions: criminal
    0.65 (FAIL) + mvr 0.00 (PASS) + education 0.00 (PASS) = 0.65, above
    threshold.

    PRD §3.7: "Alongside the `overall_result` flag, the system maintains a
    numerical applicant risk score. The score is a weighted aggregation
    over the three verification streams. Each stream contributes a
    sub-score equal to its failure weight when the stream's effective
    `result` is `FAIL`, and zero when the stream's effective `result` is
    `PASS`. The failure weights are pinned: criminal contributes 0.65,
    motor-vehicle 0.25, and education 0.10."
    PRD §3.7: "The provisional-in-review variant applies while the order
    is `IN_REVIEW`: at least one stream is still `PENDING` and is excluded
    from the sum, so the partial score may understate the eventual risk
    relative to the final value. The final-complete variant applies once
    the order is `COMPLETE`: all three streams contribute, and the score
    may rise above the 0.50 risk threshold (and trigger `CONSIDER`) even
    when the in-review score was below the threshold."
    PRD §3.7: "The read returns a `score` (the rounded numerical value),
    a `variant` (the textual variant in effect — provisional or final),
    an `exceeds_threshold` boolean (true when `score` is at or above 0.50),
    and the `threshold` value itself (so that clients do not hardcode it)."

    Design: Difficulty/dual_variant_calc/risk_score_provisional_understates_then_final_crosses_threshold
    """
    (jur, applicant, app, consent, order,
     crim, mvr, edu) = order_with_three_pending_verifications(
         state_code="CA", ban_the_box_enabled=True, salary_history_ban_enabled=True,
         recruiter_id="rec-alice",
    )
    # MVR PASS + EDUCATION PASS → order IN_REVIEW; CRIMINAL still PENDING.
    report_verification(mvr["id"], "PASS", mvr["version"],
                        report_payload={"license": "valid"})
    report_verification(edu["id"], "PASS", edu["version"],
                        report_payload={"degree": "BS"})
    prov_resp = api.get_risk_score(order["id"], make_recruiter_headers("rec-alice"))
    prov = validate_success(prov_resp, 200)
    assert prov["score"] == pytest.approx(0.00, abs=0.001), \
        f"provisional score with PENDING CRIMINAL must be 0.00, got {prov['score']!r}"
    assert prov["variant"] == "provisional_in_review", \
        f"provisional variant tag must be provisional_in_review, got {prov['variant']!r}"
    assert prov["exceeds_threshold"] is False, \
        f"0.00 does not exceed 0.50 threshold, got {prov['exceeds_threshold']!r}"
    assert prov["threshold"] == pytest.approx(0.50, abs=0.001), \
        f"reported threshold must be 0.50, got {prov['threshold']!r}"
    # Now CRIMINAL FAIL → order COMPLETE; final variant.
    report_verification(crim["id"], "FAIL", crim["version"],
                        report_payload={"conviction": "felony"})
    final_resp = api.get_risk_score(order["id"], make_recruiter_headers("rec-alice"))
    final = validate_success(final_resp, 200)
    assert final["score"] == pytest.approx(0.65, abs=0.001), \
        f"final score with CRIMINAL FAIL only must be 0.65, got {final['score']!r}"
    assert final["variant"] == "final_complete", \
        f"final variant tag must be final_complete, got {final['variant']!r}"
    assert final["exceeds_threshold"] is True, \
        f"0.65 exceeds 0.50 threshold, got {final['exceeds_threshold']!r}"


def test_risk_score_all_three_fail_sums_to_exactly_one_with_pinned_rounding(api):
    """With CRIMINAL=FAIL (0.65), MVR=FAIL (0.25), EDUCATION=FAIL (0.10),
    PRD §3.7's pinned formula yields contributions 0.65, 0.25, 0.10 (each
    rounded half-up to two decimals — they are already two-decimal exact),
    then the sum 1.00 is itself rounded half-up to two decimals.

    PRD §3.7: "The failure weights are pinned: criminal contributes 0.65,
    motor-vehicle 0.25, and education 0.10. Evaluation order is also
    pinned — criminal first, motor-vehicle second, education third — and
    each per-stream contribution is rounded half-up to two decimal places
    before being added to the running total. The final sum is then itself
    rounded half-up to two decimal places, yielding a score between 0.00
    and 1.00."

    Design: Difficulty/combinatorial_formula/risk_score_nested_rounding_order_pinned
    """
    (jur, applicant, app, consent, order, crim, mvr, edu) = (
        order_complete_with_results(
            crim_result="FAIL", mvr_result="FAIL", edu_result="FAIL",
            state_code="TX", recruiter_id="rec-bob",
            crim_payload={"hits": 1},
        )
    )
    resp = api.get_risk_score(order["id"], CO)
    rs = validate_success(resp, 200)
    assert rs["score"] == pytest.approx(1.00, abs=0.001), \
        f"all-FAIL order must score 1.00, got {rs['score']!r}"
    assert rs["variant"] == "final_complete", \
        f"COMPLETE order must use final_complete variant, got {rs['variant']!r}"
    assert rs["exceeds_threshold"] is True, \
        f"1.00 exceeds 0.50 threshold, got {rs['exceeds_threshold']!r}"
    assert rs["threshold"] == pytest.approx(0.50, abs=0.001), \
        f"reported threshold must be 0.50, got {rs['threshold']!r}"
