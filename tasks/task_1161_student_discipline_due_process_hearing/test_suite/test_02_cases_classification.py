"""Case referral, classification, occurrence counting, and OCC on classify."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_discipline_case, assert_student,
    create_student_payload, create_case_payload, create_classify_payload,
    set_clock, create_offense_code_with_bands, create_offense_code,
    create_student, create_case, classify_case, make_confirmed_case,
    make_school_admin_headers,
    TEST_USERS, NON_EXISTENT_UUID, ApiErrorId,
)

ADMIN = TEST_USERS["district_admin_headers"]
REF = TEST_USERS["school_referrer_headers"]
CLS = TEST_USERS["school_classifier_headers"]


def test_case_created_in_initial_state_submitted(api):
    """PRD §3.2: "The referral creates a discipline case in `SUBMITTED` status
    and stamps `referrer_id` with the acting administrator's `X-User-ID`".

    Design: Corner/state_machines/case_created_in_initial_state_submitted
    """
    student = create_student(full_name="Stu Init", guardian_id="gi1")
    res = api.create_case(
        create_case_payload(student["id"], "2026-05-01T08:00:00Z",
                            description="initial state check"),
        make_school_admin_headers("admin_ref_1"))
    case = validate_success(res, 201)
    assert_discipline_case(case)
    assert case["status"] == "SUBMITTED", f"got {case['status']!r}"
    assert case["referrer_id"] == "admin_ref_1", (
        f"referrer_id must be the creator's X-User-ID, got {case['referrer_id']!r}")
    assert case.get("offense_code_id") is None


def test_get_case_not_found_returns_404(api):
    """PRD §2.6: "The system confirms each identifier in path order — a case
    before its conference, a hearing before its evidence, a placement before
    its re-entry plan — and rejects the request at the first identifier that
    does not resolve to an existing resource, answering `ERR_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/entities/get_case_not_found_returns_404
    """
    res = api.get_case(NON_EXISTENT_UUID, CLS)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_cases_filtered_by_student_id(api):
    """PRD §3.2: "The case register can be listed with reverse-lookup filters
    on `student_id`, `offense_code_id`, and `status`".

    Design: Corner/endpoints/cases_filtered_by_student_id
    """
    s1 = create_student(full_name="F One", date_of_birth="2010-01-01T00:00:00Z",
                        demographic_group="BLACK", guardian_id="gf1")
    s2 = create_student(full_name="F Two", date_of_birth="2010-01-02T00:00:00Z",
                        demographic_group="WHITE", guardian_id="gf2")
    for date, desc in (("2026-05-01T08:00:00Z", "c1"),
                       ("2026-05-02T08:00:00Z", "c2")):
        validate_success(api.create_case(
            create_case_payload(s1["id"], date, description=desc),
            REF), 201)
    validate_success(api.create_case(
        create_case_payload(s2["id"], "2026-05-03T08:00:00Z", description="c3"),
        REF), 201)

    data, meta = validate_paginated(
        api.list_cases(REF, params={"student_id": s1["id"]}))
    assert len(data) == 2, f"expected exactly s1's two cases, got {len(data)}"
    assert meta["total_count"] == 2
    assert all(row["student_id"] == s1["id"] for row in data)


def test_occurrence_excludes_submitted_priors(api):
    """PRD §3.2: "The prior set comprises every other case of the same student
    — the case being classified never counts itself — whose status is one of
    `CLASSIFIED`, `SANCTION_PROPOSED`, `NOTICE_ISSUED`, `CONFIRMED`,
    `EXPULSION_REFERRED`, `EXPULSION_ACTIVE`, or `CLOSED`, and whose assigned
    offense code belongs to the same `category` as the offense code now being
    assigned; cases still `SUBMITTED` and cases already `EXPUNGED` never
    contribute."

    Design: Corner/calculations/occurrence_excludes_submitted_priors
    """
    set_clock("2026-05-04T09:00:00Z")
    oc = create_offense_code_with_bands(bands=((1, 1, 3), (2, 2, 4)))
    student = create_student(full_name="Stu Occ", guardian_id="go1")
    # Counted prior: fully confirmed.
    make_confirmed_case(
        student["id"], oc["id"], incident_date="2026-05-04T08:00:00Z",
        sanction_days=2, work_clock="2026-05-04T09:00:00Z",
        confirm_clock="2026-05-11T00:00:00Z", description="counted prior")
    # Uncounted prior: left SUBMITTED.
    create_case(student["id"], "2026-05-05T08:00:00Z", "uncounted submitted prior")
    case3 = create_case(student["id"], "2026-05-06T08:00:00Z", "case under test")

    classified = validate_success(api.classify_case(
        case3["id"],
        create_classify_payload(oc["id"], case3["version"]),
        CLS), 200)
    assert classified["occurrence_index"] == 2, (
        f"the SUBMITTED prior must be excluded; only the CONFIRMED prior "
        f"counts, so occurrence_index must be 2, got {classified['occurrence_index']}")


def test_immediate_visibility_classify_response(api):
    """PRD §3.2: "A successful classification records the offense code on the
    case, stamps `classified_by` with the classifier's `X-User-ID`, computes
    both occurrence indices described below, and increments the case `version`
    by one."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/consistency_model/immediate_visibility_classify_response
    """
    oc = create_offense_code_with_bands(bands=((1, 1, 3),))
    student = create_student(full_name="Stu Imm", guardian_id="gimm")
    case = create_case(student["id"], "2026-05-04T08:00:00Z")

    res = api.classify_case(
        case["id"], create_classify_payload(oc["id"], case["version"]),
        make_school_admin_headers("admin_adj_1"))
    classified = validate_success(res, 200)
    assert classified["status"] == "CLASSIFIED"
    assert classified["offense_code_id"] == oc["id"]
    assert classified["classified_by"] == "admin_adj_1"
    # First case in this category: the prior tally is zero, so both indices
    # are the tally plus one (PRD §3.2).
    assert classified["occurrence_index"] == 1
    assert classified["occurrence_index_ay"] == 1
    assert classified["version"] == case["version"] + 1, (
        f"version must increment by exactly one: {case['version']} -> "
        f"{classified['version']}")


def test_occ_reclassify_stale_version_returns_412(api):
    """PRD §3.2: "Each reclassification increments `version` again, which is
    what makes the OCC token meaningful here: a client holding a version
    captured before another administrator's reclassification finds its
    `expected_case_version` rejected with `ERR_STALE_VERSION`."

    Design: Corner/cross_cutting_layers/occ_reclassify_stale_version_returns_412
    """
    oc1 = create_offense_code(code="DISR-01", title="Disruption")
    oc2 = create_offense_code(code="DISR-02", title="Disruption other")
    student = create_student(full_name="Stu OCC", guardian_id="gocc")
    case = create_case(student["id"], "2026-05-04T08:00:00Z")
    v1 = case["version"]

    after_first = validate_success(api.classify_case(
        case["id"], create_classify_payload(oc1["id"], v1), CLS), 200)
    assert after_first["version"] == v1 + 1, (
        "classification increments the case version by one (PRD §3.2)")

    after_second = validate_success(api.classify_case(
        case["id"], create_classify_payload(oc2["id"], after_first["version"]),
        CLS), 200)
    assert after_second["version"] == after_first["version"] + 1

    # Reclassify back with the version captured before the second write: stale.
    res = api.classify_case(
        case["id"], create_classify_payload(oc1["id"], after_first["version"]),
        CLS)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    settled = validate_success(api.get_case(case["id"], CLS), 200)
    assert settled["offense_code_id"] == oc2["id"], (
        "the rejected stale write must change nothing")
    assert settled["version"] == after_second["version"]


# ─── Difficulty: dual occurrence-window variants ──────

def _setup_summer_and_january_priors(api):
    """One student with two CONFIRMED DISRUPTION priors — incident 2025-06-15
    (academic year 2024-25) and incident 2026-01-15 (academic year 2025-26) —
    plus a third case (incident 2026-05-01) left SUBMITTED."""
    oc = create_offense_code_with_bands(
        bands=((1, 1, 3), (2, 2, 4), (3, 4, 8)))
    student = create_student(full_name="Stu One", date_of_birth="2009-03-01T00:00:00Z",
                             grade_level=10, guardian_id="guard_1")
    make_confirmed_case(
        student["id"], oc["id"], incident_date="2025-06-15T00:00:00Z",
        sanction_days=2, work_clock="2025-06-10T00:00:00Z",
        confirm_clock="2025-06-17T00:00:00Z", description="June prior incident")
    make_confirmed_case(
        student["id"], oc["id"], incident_date="2026-01-15T00:00:00Z",
        sanction_days=3, work_clock="2026-01-15T00:00:00Z",
        confirm_clock="2026-01-21T00:00:00Z", description="January prior incident")
    set_clock("2026-05-01T00:00:00Z")
    case3 = create_case(student["id"], "2026-05-01T00:00:00Z",
                        "May incident under test")
    return oc, student, case3


def test_occurrence_rolling_365_counts_summer_prior(api):
    """PRD §3.2: "The canonical rolling-window count looks back 365 days from
    the case's `incident_date`: priors whose own `incident_date` falls inside
    the window that begins 365 days before the incident and ends the day the
    incident occurred (the incident day itself excluded) are tallied, and the
    case's `occurrence_index` is that tally plus one."
    PRD §3.2: "A prior incident from June of the preceding academic year can
    therefore still count under the rolling window while falling outside the
    academic-year bucket."

    Design: Difficulty/dual_variant_calc/occurrence_window_variants_diverge_on_summer_incident
    """
    oc, student, case3 = _setup_summer_and_january_priors(api)

    classified = validate_success(api.classify_case(
        case3["id"], create_classify_payload(oc["id"], case3["version"]),
        CLS), 200)
    # 2025-06-15 and 2026-01-15 both fall inside [2025-05-01, 2026-05-01).
    assert classified["occurrence_index"] == 3, (
        f"ROLLING_365 must count both priors: occurrence_index must be 3, "
        f"got {classified['occurrence_index']}")
    # The band lookup clamps with the lesser of the index and three (PRD §3.2);
    # here min(3, 3) = 3, where the academic-year variant would have used 2.
    band_index = min(classified["occurrence_index"], 3)
    assert band_index == 3


def test_occurrence_academic_year_drops_summer_prior(api):
    """PRD §3.2: "the academic year of any date runs from July 1 of year Y
    through June 30 of year Y+1, where Y is the date's own calendar year when
    its month is July or later and the prior calendar year otherwise, and
    `occurrence_index_ay` is the number of priors sharing the incident's
    academic year, again plus one."
    PRD §3.2: "A prior incident from June of the preceding academic year can
    therefore still count under the rolling window while falling outside the
    academic-year bucket."

    Design: Difficulty/dual_variant_calc/occurrence_window_variants_diverge_on_summer_incident
    """
    oc, student, case3 = _setup_summer_and_january_priors(api)

    classified = validate_success(api.classify_case(
        case3["id"], create_classify_payload(oc["id"], case3["version"]),
        CLS), 200)
    # Incident 2026-05-01 sits in AY 2025-26; the 2025-06-15 prior sits in
    # AY 2024-25 and is discarded, only the 2026-01-15 prior shares the bucket.
    assert classified["occurrence_index_ay"] == 2, (
        f"ACADEMIC_YEAR must count only the January prior: "
        f"occurrence_index_ay must be 2, got {classified['occurrence_index_ay']}")
    assert classified["occurrence_index"] != classified["occurrence_index_ay"], (
        "the two variants must diverge on this history")
