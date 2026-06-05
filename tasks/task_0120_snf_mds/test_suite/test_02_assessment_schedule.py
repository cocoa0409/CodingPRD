"""MDS assessment schedule, case-mix classification, correction chains, and OCC.

Covers difficulty rules: combinatorial_formula (pdpm classification),
cross_entity_state_dependency (reopen lock), resource_temporal_overlap
(assessment window conflict), plus corner ARD/OCC/idempotency instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    fixtures,
    factories as f,
)

COORD = TEST_USERS["admissions_coordinator_headers"]
MDS = TEST_USERS["mds_coordinator_headers"]
BILLING = TEST_USERS["billing_analyst_headers"]


# =====================================================================
# Difficulty/combinatorial_formula/pdpm_classification_nonlinear_three_input_branch
# =====================================================================

def test_pdpm_classification_three_input_branch_tb_sb_nb():
    """PRD §3.4: "a pt_function_score from 0 through 5 yields TA, from 6 through 9
    yields TB, from 10 through 23 yields TC, and exactly 24 yields TD. The SLP
    case-mix group, slp_case_mix_group, is selected by component count: 0 yields SA,
    1 yields SB, 2 yields SC, and 3 yields SF. The NTA case-mix group,
    nta_case_mix_group, is selected from comorbidity points in tiers: at least 12
    yields NA, from 9 through 11 yields NB, from 6 through 8 yields NC, from 3 through
    5 yields ND, and from 0 through 2 yields NE".

    Design: Difficulty/combinatorial_formula/pdpm_classification_nonlinear_three_input_branch
    """
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(
        payer_source="MEDICARE_A", with_qualifying=True,
    )
    assessment = fixtures.schedule_assessment(
        admission["id"], pt_function_score=7, slp_components_count=1, nta_comorbidity_points=10,
    )
    get_success_data(api_client.start_assessment(assessment["id"], {}, MDS))
    data = validate_success(api_client.complete_assessment(assessment["id"], {}, MDS))
    assert data["pt_ot_case_mix_group"] == "TB", f"pt_ot expected TB, got {data['pt_ot_case_mix_group']}"
    assert data["slp_case_mix_group"] == "SB", f"slp expected SB, got {data['slp_case_mix_group']}"
    assert data["nta_case_mix_group"] == "NB", f"nta expected NB, got {data['nta_case_mix_group']}"


def test_pdpm_classification_distinct_bands_tc_sa_na():
    """PRD §3.4: "a pt_function_score ... from 10 through 23 yields TC ... The SLP
    case-mix group ... 0 yields SA ... The NTA case-mix group ... at least 12 yields
    NA".

    Design: Difficulty/combinatorial_formula/pdpm_classification_nonlinear_three_input_branch
    """
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(
        payer_source="MEDICARE_A", with_qualifying=True,
    )
    assessment = fixtures.schedule_assessment(
        admission["id"], pt_function_score=15, slp_components_count=0, nta_comorbidity_points=14,
    )
    get_success_data(api_client.start_assessment(assessment["id"], {}, MDS))
    data = validate_success(api_client.complete_assessment(assessment["id"], {}, MDS))
    assert data["pt_ot_case_mix_group"] == "TC", f"pt_ot expected TC, got {data['pt_ot_case_mix_group']}"
    assert data["slp_case_mix_group"] == "SA", f"slp expected SA, got {data['slp_case_mix_group']}"
    assert data["nta_case_mix_group"] == "NA", f"nta expected NA, got {data['nta_case_mix_group']}"


# =====================================================================
# Difficulty/cross_entity_state_dependency/assessment_reopen_blocked_by_finalized_claim
# =====================================================================
#
# SKIPPED (not PRD-uniquely-derivable). This instance asserts that reopening an
# assessment driven by a FINALIZED claim returns ERR_ASSESSMENT_LOCKED_BY_CLAIM. But a
# claim can only be created against a SUBMITTED driving assessment (PRD §3.9), and
# reopen's legal from-state is COMPLETED (PRD §3.4: "A completed assessment can be
# reopened"). Once an assessment is SUBMITTED there is no PRD path back to COMPLETED, so
# the only feasible reopen attempt here is from SUBMITTED — which PRD §2.7's structural
# state gate ("the target resource must be in a state from which the requested
# transition is legal, else ERR_INVALID_STATE") rejects before any §3 business rule,
# including the claim-lock check, is reached. A faithful PRD-only implementer therefore
# returns ERR_INVALID_STATE, not ERR_ASSESSMENT_LOCKED_BY_CLAIM. The asserted outcome is
# unreachable; the gap stays a gap.


# =====================================================================
# Difficulty/resource_temporal_overlap/assessment_window_conflict_inclusive_adjacent_collides
# =====================================================================

def test_assessment_window_conflict_same_type_overlap():
    """PRD §3.4: "the ARD window of the assessment being started must not overlap the
    ARD window of another non-superseded assessment of the same assessment_type for
    the admission — only one open assessment per type-window is allowed — and because
    the windows are inclusive-closed, even adjacency at exactly a window boundary
    counts as a conflict; a violation is rejected with ERR_ASSESSMENT_WINDOW_CONFLICT".

    Design: Difficulty/resource_temporal_overlap/assessment_window_conflict_inclusive_adjacent_collides
    """
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(
        payer_source="MEDICARE_A", with_qualifying=True,
    )
    mds1 = fixtures.schedule_assessment(
        admission["id"], assessment_type="ADMISSION_5DAY",
        assessment_reference_date="2026-02-05T00:00:00Z",
        pt_function_score=7, slp_components_count=1, nta_comorbidity_points=10,
    )
    get_success_data(api_client.start_assessment(mds1["id"], {}, MDS))

    mds2 = fixtures.schedule_assessment(
        admission["id"], assessment_type="ADMISSION_5DAY",
        assessment_reference_date="2026-02-06T00:00:00Z",
        pt_function_score=9, slp_components_count=2, nta_comorbidity_points=8,
    )
    validate_error(api_client.start_assessment(mds2["id"], {}, MDS),
                   ApiErrorId.ERR_ASSESSMENT_WINDOW_CONFLICT.value)


def test_assessment_start_succeeds_no_conflict_single_type():
    """PRD §3.4: "Starting an assessment advances it from SCHEDULED to IN_PROGRESS,
    and is permitted only while the parent admission is in ACTIVE, NON_COVERED, or
    DISCHARGE_PLANNED".

    Design: Difficulty/resource_temporal_overlap/assessment_window_conflict_inclusive_adjacent_collides
    """
    # A single ADMISSION_5DAY assessment with no competing same-type window starts cleanly.
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(
        payer_source="MEDICARE_A", with_qualifying=True,
    )
    mds1 = fixtures.schedule_assessment(
        admission["id"], assessment_type="ADMISSION_5DAY",
        assessment_reference_date="2026-02-05T00:00:00Z",
    )
    data = validate_success(api_client.start_assessment(mds1["id"], {}, MDS))
    assert data["status"] == "IN_PROGRESS", f"expected IN_PROGRESS, got {data['status']}"


# =====================================================================
# Corner/validations/error_ard_out_of_window_on_assessment_start
# =====================================================================

def test_ard_out_of_window_rejected():
    """PRD §3.4: "the assessment_reference_date must fall inside the ARD window for the
    assessment's type, or the start is rejected with ERR_ARD_OUT_OF_WINDOW. The
    windows are: for ADMISSION_5DAY, stay-days 1 through 8 inclusive (counting the
    admit day as day 1)".

    Design: Corner/validations/error_ard_out_of_window_on_assessment_start
    """
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(
        payer_source="MEDICARE_A", with_qualifying=True,
    )
    # admit_at 2026-02-01 -> day 8 is 2026-02-08; ARD 2026-02-20 is past the window.
    mds = fixtures.schedule_assessment(
        admission["id"], assessment_type="ADMISSION_5DAY",
        assessment_reference_date="2026-02-20T00:00:00Z",
    )
    validate_error(api_client.start_assessment(mds["id"], {}, MDS),
                   ApiErrorId.ERR_ARD_OUT_OF_WINDOW.value)


# =====================================================================
# Corner/state_machines/assessment_submit_twice_idempotency_rejected
# =====================================================================

def test_submit_already_submitted_assessment_rejected():
    """PRD §2.7: "on a transition endpoint, the target resource must be in a state
    from which the requested transition is legal, else ERR_INVALID_STATE".
    PRD §3.4: "From COMPLETED, an assessment may instead be submitted, advancing it to
    SUBMITTED".

    Design: Corner/state_machines/assessment_submit_twice_idempotency_rejected
    """
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(
        payer_source="MEDICARE_A", with_qualifying=True,
    )
    submitted = fixtures.create_submitted_assessment(admission["id"])
    validate_error(api_client.submit_assessment(submitted["id"], {}, MDS),
                   ApiErrorId.ERR_INVALID_STATE.value)


# =====================================================================
# Corner/consistency_model/immediate_visibility_assessment_groups_in_complete_response
# =====================================================================

def test_case_mix_groups_present_in_complete_response():
    """PRD §3.4: "Completing an assessment advances it from IN_PROGRESS to COMPLETED
    ... On completion the three case-mix groups are computed".

    Design: Corner/consistency_model/immediate_visibility_assessment_groups_in_complete_response
    """
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(
        payer_source="MEDICARE_A", with_qualifying=True,
    )
    assessment = fixtures.schedule_assessment(admission["id"])
    get_success_data(api_client.start_assessment(assessment["id"], {}, MDS))
    data = validate_success(api_client.complete_assessment(assessment["id"], {}, MDS))
    assert data["status"] == "COMPLETED", f"expected COMPLETED in same response, got {data['status']}"
    assert data["pt_ot_case_mix_group"] == "TB", (
        f"groups must be present in the complete response, got {data['pt_ot_case_mix_group']}"
    )


# =====================================================================
# Corner/cross_cutting_complexity_layers/occ_assessment_correction_stale_version_rejected
# =====================================================================

def test_correction_stale_version_rejected():
    """PRD §2.6: "The request must include expected_assessment_version, carrying the
    client's last observed version of the assessment being corrected. If another
    writer has advanced that assessment's version since the client read it ... the
    request is rejected with ERR_STALE_VERSION (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_assessment_correction_stale_version_rejected
    """
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(
        payer_source="MEDICARE_A", with_qualifying=True,
    )
    orig = fixtures.create_submitted_assessment(admission["id"])
    payload = f.create_assessment_payload(
        assessment_type="INTERIM_IPA", assessment_reference_date="2026-02-12T00:00:00Z",
        pt_function_score=9, slp_components_count=2, nta_comorbidity_points=8,
    )
    payload["expected_assessment_version"] = orig["version"] - 1  # deliberately stale
    resp = api_client.correct_assessment(orig["id"], payload, MDS)
    assert resp.status_code == 412, f"expected 412, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# =====================================================================
# Corner/endpoints/list_assessments_by_corrects_assessment_id_self_ref
# =====================================================================

def test_list_assessments_by_corrects_assessment_id():
    """PRD §3.4: "A successful correction creates a new SCHEDULED assessment under the
    same admission ... whose corrects_assessment_id points at the target ...
    Assessments may be listed and filtered by their admission_id, by their
    corrects_assessment_id (to walk a correction chain)".

    Design: Corner/endpoints/list_assessments_by_corrects_assessment_id_self_ref
    """
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(
        payer_source="MEDICARE_A", with_qualifying=True,
    )
    orig = fixtures.create_submitted_assessment(admission["id"])
    corr_payload = f.create_assessment_payload(
        assessment_type="INTERIM_IPA", assessment_reference_date="2026-02-12T00:00:00Z",
        pt_function_score=9, slp_components_count=2, nta_comorbidity_points=8,
    )
    corr_payload["expected_assessment_version"] = orig["version"]
    corr = get_success_data(api_client.correct_assessment(orig["id"], corr_payload, MDS))

    resp = api_client.list_assessments(MDS, params={"corrects_assessment_id": orig["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    assert data[0]["id"] == corr["id"], "filter must return the correcting assessment"
