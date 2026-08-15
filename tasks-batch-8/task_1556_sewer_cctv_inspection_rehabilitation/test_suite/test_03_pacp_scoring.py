"""PACP scoring on certification: quick rating vs weighted index, recomputation."""
import pytest

from test_helpers import (
    add_defects,
    certify_inspection,
    create_district,
    create_open_cycle,
    create_segment,
    create_technician,
    drive_inspection_to_coding,
    get_segment,
    make_coder_headers,
    make_qa_reviewer_headers,
    reject_inspection,
    schedule_inspection,
    set_clock,
    setup_certified_segment,
    submit_for_qa,
    validate_success,
    TEST_USERS,
)

ENGINEER = TEST_USERS["engineer_headers"]


def test_quick_rating_no_structural_observations_is_0000(api):
    """PRD §3.3: "Grades of {5, 5, 4, 3, 1} therefore encode as `5241`, and an
    inspection with no structural observations yields `0000`."
    PRD §3.3: "`structural_index` becomes the extent-weighted mean of the structural
    observations: each observation contributes its grade multiplied by its weight,
    where the weight is the larger of the defect's `extent_m` and 1.0, and the sum of
    those products is divided by the sum of the weights; the result is stored to two
    decimal places, rounded half-up, and remains null when the inspection carries no
    structural observations."

    Design: Corner/calculations/quick_rating_no_structural_observations_is_0000
    """
    ctx = setup_certified_segment(
        defects=[{"pacp_code": "RTL", "family": "OM", "grade": 3,
                  "distance_m": 50, "clock_position": 0}]
    )
    segment = ctx["segment"]
    assert segment["quick_rating"] == "0000"
    assert segment["structural_grade"] == 0
    assert segment["structural_index"] is None
    assert segment["om_grade"] == 3


def test_quick_rating_count_cap_at_9(api):
    """PRD §3.3: "`quick_rating` becomes the four-character PACP Quick Rating: the
    first character is the highest structural grade observed; the second is the count
    of observations at that grade, capped at 9; the third is the second-highest grade,
    or 0 when no second grade exists; the fourth is the count at that second grade,
    capped at 9, or 0."
    Ten grade-5 point defects therefore encode as `5900`.

    Design: Corner/calculations/quick_rating_count_cap_at_9
    """
    defects = [
        {"pacp_code": "B", "family": "STRUCTURAL", "grade": 5,
         "distance_m": 5 + 10 * i, "clock_position": 12}
        for i in range(10)
    ]
    ctx = setup_certified_segment(defects=defects)
    segment = ctx["segment"]
    assert segment["quick_rating"] == "5900", "count digit caps at 9"
    assert segment["structural_grade"] == 5
    assert segment["structural_index"] == pytest.approx(5.0, abs=1e-9)


def test_pacp_quick_rating_ordinal_encoding(api):
    """PRD §3.3: "The quick rating is an ordinal triage and regulatory-reporting
    code that ignores extent entirely — a segment with one grade-5 point defect and a
    long grade-4 crack reports a severity of the `5141` style."

    Design: Difficulty/dual_variant_calc/pacp_quick_rating_vs_weighted_index_divergence
    """
    ctx = setup_certified_segment(defects=[
        {"pacp_code": "B", "family": "STRUCTURAL", "grade": 5,
         "distance_m": 10, "clock_position": 12, "extent_m": 0},
        {"pacp_code": "CRK", "family": "STRUCTURAL", "grade": 4,
         "distance_m": 20, "clock_position": 3, "extent_m": 30},
    ])
    segment = ctx["segment"]
    assert segment["quick_rating"] == "5141", "highest grade 5 x1, second grade 4 x1"
    assert segment["structural_grade"] == 5


def test_pacp_weighted_index_diverges_from_quick_rating(api):
    """PRD §3.3: "The weighted index, by contrast, lets longitudinal defects count
    for more: that same observation set produces an index of 4.03."
    For grades {5 (extent 0 -> weight 1), 4 (extent 30 -> weight 30)}:
    (5*1 + 4*30) / (1 + 30) = 125/31 = 4.0322... -> 4.03, which disagrees with the
    ordinal quick rating's worst-grade picture.

    Design: Difficulty/dual_variant_calc/pacp_quick_rating_vs_weighted_index_divergence
    """
    ctx = setup_certified_segment(defects=[
        {"pacp_code": "B", "family": "STRUCTURAL", "grade": 5,
         "distance_m": 10, "clock_position": 12, "extent_m": 0},
        {"pacp_code": "CRK", "family": "STRUCTURAL", "grade": 4,
         "distance_m": 20, "clock_position": 3, "extent_m": 30},
    ])
    segment = ctx["segment"]
    assert segment["structural_index"] == pytest.approx(4.03, abs=1e-9)
    assert segment["structural_index"] < 5.0, (
        "extent weighting pulls the index below the worst-grade ordinal implied by '5141'"
    )


def test_derived_grades_recomputed_on_recertification_after_loop(api):
    """PRD §3.3: "On certification the inspection records the acting technician as
    `qa_reviewer_id` and stamps `certified_at`, and the parent segment's condition
    scores are recomputed from this inspection's observations alone, across both
    families"
    After a QA reject loop in which the coder deletes the grade-5 defect, the
    re-certified observation set is just the grade-2 crack, so the segment's derived
    scores track the post-edit set (grade 2, quick rating `2100`).

    Design: Corner/cross_cutting_layers/derived_grades_recomputed_on_recertification_after_loop
    """
    set_clock("2026-08-10T00:00:00Z")
    district = create_district(name="D-L3", ii_reduction_target_pct=20, budget_cents=1000000)
    coder = create_technician(["CODER"])
    qa = create_technician(["QA_REVIEWER"])
    cycle = create_open_cycle(district["id"])
    segment = create_segment(district["id"], segment_ref="MH-1->MH-2")
    inspection = schedule_inspection(segment["id"], cycle["id"], coder["id"])
    drive_inspection_to_coding(inspection["id"], coder["id"])
    grade5 = add_defects(inspection["id"], coder["id"],
                         [{"pacp_code": "B", "family": "STRUCTURAL", "grade": 5,
                           "distance_m": 10, "clock_position": 12}])[0]
    add_defects(inspection["id"], coder["id"],
                [{"pacp_code": "CRK", "family": "STRUCTURAL", "grade": 2,
                  "distance_m": 50, "clock_position": 6}])
    submit_for_qa(inspection["id"], coder["id"])
    reject_inspection(inspection["id"], qa["id"], "verify grade-5 defect")

    delete_resp = api.delete_defect(inspection["id"], grade5["id"], make_coder_headers(coder["id"]))
    assert delete_resp.status_code == 204, (
        f"Setup failed: defect delete returned {delete_resp.status_code}"
    )
    submit_for_qa(inspection["id"], coder["id"])
    certify_inspection(inspection["id"], qa["id"])

    segment_after = get_segment(segment["id"])
    assert segment_after["structural_grade"] == 2, "deleted grade-5 defect no longer scores"
    assert segment_after["quick_rating"] == "2100"


def test_certify_response_immediately_reflects_segment_grades(api):
    """PRD §2.6: "State changes propagate along this hierarchy in both directions,
    and the propagation is always immediate: every side effect of a request is
    visible in that request's response."
    PRD §3.3: "`structural_grade` becomes the worst (highest) grade among the
    inspection's structural observations, or 0 when there are none."

    Design: Corner/consistency_model/certify_response_immediately_reflects_segment_grades
    """
    set_clock("2026-08-10T00:00:00Z")
    district = create_district(name="D-K1", ii_reduction_target_pct=20, budget_cents=1000000)
    coder = create_technician(["CODER"])
    qa = create_technician(["QA_REVIEWER"])
    cycle = create_open_cycle(district["id"])
    segment = create_segment(district["id"], segment_ref="MH-1->MH-2")
    inspection = schedule_inspection(segment["id"], cycle["id"], coder["id"])
    drive_inspection_to_coding(inspection["id"], coder["id"])
    add_defects(inspection["id"], coder["id"],
                [{"pacp_code": "B", "family": "STRUCTURAL", "grade": 4,
                  "distance_m": 10, "clock_position": 12}])
    submit_for_qa(inspection["id"], coder["id"])

    resp = api.certify_inspection(inspection["id"], make_qa_reviewer_headers(qa["id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "CERTIFIED"

    segment_after = get_segment(segment["id"])  # same-instant GET, no async lag
    assert segment_after["structural_grade"] == 4
    assert segment_after["quick_rating"] == "4100"
