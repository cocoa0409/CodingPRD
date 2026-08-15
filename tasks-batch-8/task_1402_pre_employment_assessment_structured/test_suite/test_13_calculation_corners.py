"""Corner coverage — calculations: zero-coverage composite, UNDISCLOSED exclusion,
MIN_GROUP_N boundary, no-selections convention, calibration lapse, certification
threshold, and the evidence min-rule."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_vendor,
    create_instrument,
    file_evidence,
    create_candidate,
    invite_candidate,
    schedule_assessment,
    invite_and_complete_candidate,
    create_calibrated_interviewer,
    create_interviewer,
    create_calibration_payload,
    certify_calibration_payload,
    create_snapshot_payload,
    set_clock_payload,
    setup_active_cycle,
    book_completed_session,
    submit_scorecard,
    create_approved_guide,
    get_group_breakdown,
    assert_snapshot,
)

ADMIN = TEST_USERS["admin_headers"]
ADMIN2 = TEST_USERS["admin2_headers"]
HM = TEST_USERS["hm_headers"]
CO = TEST_USERS["co_headers"]


def test_composite_without_scorecards_assessment_only(api):
    """PRD §3.8: "when coverage is zero the guide component is zero" and "The composite
    is six-tenths of the guide component plus four-tenths of the assessment component".

    raw 72, pass_floor 40, max 100 -> assessment component (72-40)/60 = 0.5333 ->
    composite = 0.6*0 + 0.4*0.5333 = 0.2133 at completion, before any scorecard exists.

    Design: Corner/calculations/composite_without_scorecards_assessment_only
    """
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    a1 = invite_candidate(cycle["id"], c1["id"])
    schedule_assessment(a1["id"])
    api.set_clock(set_clock_payload("2026-08-10T09:00:00Z"), ADMIN)
    get_success_data(api.start_assessment(a1["id"], HM))
    resp = api.complete_assessment(a1["id"], {"raw_score": 72}, HM)
    data = validate_success(resp)
    assert data["composite_score"] == pytest.approx(0.2133, abs=0.0001)


def test_adverse_impact_undisclosed_excluded(api):
    """PRD §3.7: "Candidates whose `group_code` is `UNDISCLOSED` are excluded from every
    denominator and reported as a separate breakdown entry whose `excluded_reason` is
    `UNDISCLOSED`."

    GROUP_A stays 2 applicants / 1 selected (rate 0.5000, self-max ratio 1.0000) even
    though 2 UNDISCLOSED assessments exist in the same statuses.

    Design: Corner/calculations/adverse_impact_undisclosed_excluded
    """
    ctx = setup_active_cycle(openings_count=4)
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    interviewer, _ = create_calibrated_interviewer(guide["id"])
    ca1 = create_candidate(external_ref="C-A1", full_name="Cand A1", email="ca1@x.com",
                           group_code="GROUP_A")
    ca2 = create_candidate(external_ref="C-A2", full_name="Cand A2", email="ca2@x.com",
                           group_code="GROUP_A")
    cu1 = create_candidate(external_ref="C-U1", full_name="Cand U1", email="cu1@x.com",
                           group_code="UNDISCLOSED")
    cu2 = create_candidate(external_ref="C-U2", full_name="Cand U2", email="cu2@x.com",
                           group_code="UNDISCLOSED")
    a1 = invite_and_complete_candidate(cycle["id"], ca1["id"], raw_score=72)
    a2 = invite_candidate(cycle["id"], ca2["id"]); schedule_assessment(a2["id"])
    u1 = invite_and_complete_candidate(cycle["id"], cu1["id"], raw_score=72)
    u2 = invite_candidate(cycle["id"], cu2["id"]); schedule_assessment(u2["id"])
    # Lift both COMPLETED assessments to composite 0.7413
    s1 = book_completed_session(cycle["id"], ca1["id"], interviewer["id"], guide["id"],
                                "2026-08-12T09:00:00Z", "2026-08-12T10:00:00Z")
    s2 = book_completed_session(cycle["id"], cu1["id"], interviewer["id"], guide["id"],
                                "2026-08-12T10:00:00Z", "2026-08-12T11:00:00Z")
    submit_scorecard(s1["id"], interviewer["id"])
    submit_scorecard(s2["id"], interviewer["id"])

    resp = api.create_adverse_impact_snapshot(cycle["id"], create_snapshot_payload(), CO)
    snap = validate_success(resp, expected_status=201)
    assert_snapshot(snap)
    group_a = get_group_breakdown(snap, "GROUP_A")
    assert group_a["applicants"] == 2
    assert group_a["selected"] == 1
    assert group_a["selection_rate"] == pytest.approx(0.5, abs=0.0001)
    assert group_a["impact_ratio"] == pytest.approx(1.0, abs=0.0001)
    undisclosed = get_group_breakdown(snap, "UNDISCLOSED")
    assert undisclosed["excluded_reason"] == "UNDISCLOSED"
    assert undisclosed["selection_rate"] is None
    assert snap["flagged"] is False
    assert snap["highest_rate_group_code"] == "GROUP_A"


def test_adverse_impact_min_group_n_boundary(api):
    """PRD §3.7: "any group with fewer than 2 applicants is excluded from comparison
    entirely: its `selection_rate` and `impact_ratio` are null and its `excluded_reason`
    is `INSUFFICIENT_N`."

    GROUP_A with exactly 2 applicants is included; GROUP_C with exactly 1 is excluded.

    Design: Corner/calculations/adverse_impact_min_group_n_boundary
    """
    ctx = setup_active_cycle(openings_count=3)
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    interviewer, _ = create_calibrated_interviewer(guide["id"])
    ca1 = create_candidate(external_ref="C-A1", full_name="Cand A1", email="ca1@x.com",
                           group_code="GROUP_A")
    ca2 = create_candidate(external_ref="C-A2", full_name="Cand A2", email="ca2@x.com",
                           group_code="GROUP_A")
    cc1 = create_candidate(external_ref="C-C1", full_name="Cand C1", email="cc1@x.com",
                           group_code="GROUP_C")
    a1 = invite_and_complete_candidate(cycle["id"], ca1["id"], raw_score=72)
    a2 = invite_candidate(cycle["id"], ca2["id"]); schedule_assessment(a2["id"])
    ac1 = invite_candidate(cycle["id"], cc1["id"]); schedule_assessment(ac1["id"])
    s1 = book_completed_session(cycle["id"], ca1["id"], interviewer["id"], guide["id"],
                                "2026-08-12T09:00:00Z", "2026-08-12T10:00:00Z")
    submit_scorecard(s1["id"], interviewer["id"])

    resp = api.create_adverse_impact_snapshot(cycle["id"], create_snapshot_payload(), CO)
    snap = validate_success(resp, expected_status=201)
    group_a = get_group_breakdown(snap, "GROUP_A")
    assert group_a["applicants"] == 2
    assert group_a["selection_rate"] == pytest.approx(0.5, abs=0.0001)
    assert group_a["impact_ratio"] == pytest.approx(1.0, abs=0.0001)
    group_c = get_group_breakdown(snap, "GROUP_C")
    assert group_c["applicants"] == 1
    assert group_c["selection_rate"] is None
    assert group_c["impact_ratio"] is None
    assert group_c["excluded_reason"] == "INSUFFICIENT_N"
    assert snap["flagged"] is False


def test_adverse_impact_no_selections_convention(api):
    """PRD §3.7: "When the maximum rate is exactly zero, every included group's
    `impact_ratio` is null with `excluded_reason` of `NO_SELECTIONS`, `flagged` is
    false, and `highest_rate_group_code` is null."

    Two groups of 2 SCHEDULED applicants each, no completions, no decisions ->
    rates 0.0000, ratios null.

    Design: Corner/calculations/adverse_impact_no_selections_convention
    """
    ctx = setup_active_cycle(openings_count=4)
    cycle = ctx["cycle"]
    for ref, grp in (("C-A1", "GROUP_A"), ("C-A2", "GROUP_A"),
                     ("C-B1", "GROUP_B"), ("C-B2", "GROUP_B")):
        c = create_candidate(external_ref=ref, full_name=f"Cand {ref}",
                             email=f"{ref.lower()}@x.com", group_code=grp)
        a = invite_candidate(cycle["id"], c["id"])
        schedule_assessment(a["id"])
    resp = api.create_adverse_impact_snapshot(cycle["id"], create_snapshot_payload(), CO)
    snap = validate_success(resp, expected_status=201)
    assert snap["flagged"] is False
    assert snap["highest_rate_group_code"] is None
    for grp in ("GROUP_A", "GROUP_B"):
        entry = get_group_breakdown(snap, grp)
        assert entry["applicants"] == 2
        assert entry["selected"] == 0
        assert entry["selection_rate"] == pytest.approx(0.0, abs=0.0001)
        assert entry["impact_ratio"] is None
        assert entry["excluded_reason"] == "NO_SELECTIONS"


def test_calibration_lapses_below_floor(api):
    """PRD §3.6: "Lapse arrives by two roads: the logical clock moving strictly more
    than 365 days past `certified_at` (equality keeps the record `CALIBRATED`), or a
    recomputed `calibration_index` dropping below 0.5000." and "any `CALIBRATED` record
    whose recomputed index falls below 0.5000 lapses".

    iv1 submits COMM1/ANAL1 against iv2's already-SUBMITTED COMM5/ANAL5: both records
    recompute to index 0.0000 (mean |dev| 4, scale 4) and lapse.

    Design: Corner/calculations/calibration_lapses_below_floor
    """
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    iv1, cal1 = create_calibrated_interviewer(guide["id"], full_name="Ivy One", email="ivy1@x.com")
    iv2, cal2 = create_calibrated_interviewer(guide["id"], full_name="Ivy Two", email="ivy2@x.com")
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    invite_and_complete_candidate(cycle["id"], c1["id"], raw_score=72)
    s1 = book_completed_session(cycle["id"], c1["id"], iv1["id"], guide["id"],
                                "2026-08-12T09:00:00Z", "2026-08-12T10:00:00Z")
    s2 = book_completed_session(cycle["id"], c1["id"], iv2["id"], guide["id"],
                                "2026-08-12T10:00:00Z", "2026-08-12T11:00:00Z")
    submit_scorecard(s2["id"], iv2["id"],
                     ratings=[{"competency_code": "COMM", "rating": 5},
                              {"competency_code": "ANAL", "rating": 5}],
                     overall_recommendation="STRONG_YES")
    # iv1's maximal-deviation submit triggers recompute on both records
    submit_scorecard(s1["id"], iv1["id"],
                     ratings=[{"competency_code": "COMM", "rating": 1},
                              {"competency_code": "ANAL", "rating": 1}],
                     overall_recommendation="STRONG_NO")
    data1 = validate_success(api.get_calibration(cal1["id"], ADMIN))
    assert data1["calibration_index"] == pytest.approx(0.0, abs=0.0001)
    assert data1["status"] == "LAPSED"
    data2 = validate_success(api.get_calibration(cal2["id"], ADMIN))
    assert data2["calibration_index"] == pytest.approx(0.0, abs=0.0001)
    assert data2["status"] == "LAPSED"


def test_certification_threshold_boundary(api):
    """PRD §3.6: "requires a `practice_score` of at least 0.7000 — the boundary is
    inclusive, exactly 0.7000 passes, anything below is
    `ERR_PRACTICE_SCORE_BELOW_THRESHOLD` (HTTP 422)".

    Design: Corner/calculations/certification_threshold_boundary
    """
    guide = create_approved_guide()
    iv1 = create_interviewer(full_name="Ivy One", email="ivy1@x.com")
    iv2 = create_interviewer(full_name="Ivy Two", email="ivy2@x.com")
    cal1 = get_success_data(api.create_calibration(iv1["id"], create_calibration_payload(guide["id"]), ADMIN))
    cal2 = get_success_data(api.create_calibration(iv2["id"], create_calibration_payload(guide["id"]), ADMIN))
    resp = api.certify_calibration(cal1["id"], certify_calibration_payload(practice_score=0.6999), ADMIN)
    validate_error(resp, ApiErrorId.ERR_PRACTICE_SCORE_BELOW_THRESHOLD)
    data1 = validate_success(api.get_calibration(cal1["id"], ADMIN))
    assert data1["status"] == "TRAINED"
    resp = api.certify_calibration(cal2["id"], certify_calibration_payload(practice_score=0.7000), ADMIN)
    assert validate_success(resp)["status"] == "CALIBRATED"


def test_evidence_min_rule_sets_validity(api):
    """PRD §3.2: "A successful validation sets `validity_expires_at` to the earliest
    `effective_until` among the currently valid `CRITERION` and `CONTENT` records".

    CRITERION until 2027-08-01, CONTENT until 2027-06-01 -> 2027-06-01T00:00:00Z.

    Design: Corner/calculations/evidence_min_rule_sets_validity
    """
    vendor = create_vendor()
    instrument = create_instrument(vendor["id"])
    file_evidence(instrument["id"], evidence_type="CRITERION",
                  effective_until="2027-08-01T00:00:00Z")
    file_evidence(instrument["id"], evidence_type="CONTENT",
                  effective_until="2027-06-01T00:00:00Z")
    get_success_data(api.submit_instrument_validation_review(instrument["id"], ADMIN))
    resp = api.validate_instrument(instrument["id"], ADMIN)
    data = validate_success(resp)
    assert data["validation_status"] == "VALIDATED"
    from test_helpers import assert_iso_instant_equal
    assert_iso_instant_equal(data["validity_expires_at"], "2027-06-01T00:00:00Z")


def test_evidence_missing_content_type_rejected(api):
    """PRD §3.2: "When a required type is entirely absent the failure is
    `ERR_EVIDENCE_TYPE_MISSING`".

    Only CRITERION evidence filed -> validate fails with ERR_EVIDENCE_TYPE_MISSING.

    Design: Corner/calculations/evidence_missing_content_type_rejected
    """
    vendor = create_vendor()
    instrument = create_instrument(vendor["id"])
    file_evidence(instrument["id"], evidence_type="CRITERION")
    get_success_data(api.submit_instrument_validation_review(instrument["id"], ADMIN))
    resp = api.validate_instrument(instrument["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_EVIDENCE_TYPE_MISSING)
    data = validate_success(api.get_instrument(instrument["id"], ADMIN))
    assert data["validation_status"] == "VALIDATION_REVIEW"
