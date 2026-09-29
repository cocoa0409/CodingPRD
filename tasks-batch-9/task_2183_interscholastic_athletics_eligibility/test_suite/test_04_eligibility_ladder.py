"""The five-rung eligibility ladder, the GPA variant selector, and the forms."""
import pytest

from test_helpers import (
    assert_clearance_document,
    assert_three_decimal_places,
    set_clock,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx

IDENTICAL_RECORD = {
    "gpa_prior_period": 2.100,
    "gpa_current_period": 1.800,
    "credits_prior_period": 3,
    "credits_current_period": 4,
}


def _twin_athletes_with_identical_records():
    """Two athletes of one school carrying byte-identical academic records."""
    set_clock("2026-09-10T09:00:00Z")
    school = fx.create_school(name="North High", school_day_end_utc_hhmm="17:00",
                              bus_fleet_size=2, fee_cap_cents=20000)
    season = fx.create_season(grading_lock_date="2026-10-01")
    fx.open_season_to_regular(season["id"])
    people = {}
    for key, name, birth in (("ada", "Ada Reyes", "2009-05-14"),
                             ("ben", "Ben Okafor", "2009-06-02")):
        student = fx.create_student(
            school["id"], full_name=name, birth_date=birth, grade_level=11,
            residency_verified=True, residency_verified_on="2026-08-10",
            free_reduced_lunch=False,
        )
        fx.post_academic_record(student["id"], school["id"], **IDENTICAL_RECORD)
        case = fx.create_case(school["id"], student["id"], season["id"])
        fx.file_all_clearance_documents(case["id"], school["id"])
        people[key] = {"student": student, "case": case}
    return {"school": school, "season": season, **people}


def test_provisional_variant_reads_only_the_prior_period_and_clears_the_rung(api):
    """PRD §3.4: "While the clock's UTC date is strictly before
    `grading_lock_date`, the `PROVISIONAL` variant applies: `effective_gpa` is
    `gpa_prior_period` rounded half up to three decimal places, and the in-progress
    period's grades and credits are ignored entirely even when both are populated."
    PRD §3.4: "Where a clean ladder run returns no failing rung, the case moves to
    `PROVISIONAL_ELIGIBLE` and `ineligibility_reason` is set to null."
    PRD §3.4: "The chosen variant is recorded on the case as `gpa_variant_applied`,
    taking the value `PROVISIONAL` or `FINAL`."

    Design: Difficulty/dual_variant_calc/gpa_variant_flips_academic_rung_on_the_same_student_record
    """
    ctx = _twin_athletes_with_identical_records()

    ruled = validate_success(api.evaluate_case(ctx["ada"]["case"]["id"], fx.REVIEWER), 200)

    assert ruled["gpa_variant_applied"] == "PROVISIONAL"
    assert ruled["effective_gpa"] == pytest.approx(2.100, abs=0.0005)
    assert_three_decimal_places(ruled["effective_gpa"])
    assert ruled["status"] == "PROVISIONAL_ELIGIBLE"
    assert ruled["ineligibility_reason"] is None
    assert ruled["evaluation_count"] == 1


def test_final_variant_after_the_grading_lock_flips_the_identical_record_to_ineligible(api):
    """PRD §3.4: "Once the clock's UTC date reaches or passes `grading_lock_date`,
    the `FINAL` variant applies: the denominator is `credits_prior_period` plus
    `credits_current_period`; if that denominator is zero, `effective_gpa` is 0.000;
    otherwise the numerator is `gpa_prior_period` multiplied by
    `credits_prior_period` plus `gpa_current_period` multiplied by
    `credits_current_period`, and `effective_gpa` is that numerator divided by that
    denominator, rounded half up to three decimal places."
    PRD §3.4: "The athlete's effective grade point average must be at least 2.000."
    PRD §3.4: "Where the ladder returns a failing rung, the case moves to
    `INELIGIBLE` and `ineligibility_reason` records that first failing rung, which
    is one of `AGE_LIMIT`, `RESIDENCY_UNVERIFIED`, `TRANSFER_SITOUT`,
    `DOCS_INCOMPLETE`, or `ACADEMIC_GPA`."

    Design: Difficulty/dual_variant_calc/gpa_variant_flips_academic_rung_on_the_same_student_record
    """
    ctx = _twin_athletes_with_identical_records()
    ada = fx.evaluate_case(ctx["ada"]["case"]["id"])

    fx.set_clock("2026-10-05T09:00:00Z")
    ben = validate_success(api.evaluate_case(ctx["ben"]["case"]["id"], fx.REVIEWER), 200)

    assert ben["gpa_variant_applied"] == "FINAL"
    assert ben["effective_gpa"] == pytest.approx(1.929, abs=0.0005)
    assert ben["status"] == "INELIGIBLE"
    assert ben["ineligibility_reason"] == "ACADEMIC_GPA"
    assert ada["effective_gpa"] != ben["effective_gpa"], (
        "the same stored academic figures must yield different effective_gpa values "
        "under the two variants"
    )


def test_final_gpa_landing_exactly_on_two_point_zero_clears_the_academic_rung(api):
    """PRD §3.4: "The athlete's effective grade point average must be at least
    2.000."
    PRD §3.4: "Once the clock's UTC date reaches or passes `grading_lock_date`, the
    `FINAL` variant applies: the denominator is `credits_prior_period` plus
    `credits_current_period`; if that denominator is zero, `effective_gpa` is 0.000;
    otherwise the numerator is `gpa_prior_period` multiplied by
    `credits_prior_period` plus `gpa_current_period` multiplied by
    `credits_current_period`, and `effective_gpa` is that numerator divided by that
    denominator, rounded half up to three decimal places."

    Design: Difficulty/boundary_precision_check/final_gpa_exactly_at_two_point_zero_clears_the_academic_rung
    """
    ctx = fx.setup_case_ready_for_evaluation(
        clock="2026-10-05T09:00:00Z",
        student_overrides={"full_name": "Gus Iwu", "birth_date": "2009-01-30",
                           "grade_level": 12, "residency_verified": True,
                           "residency_verified_on": "2026-08-10"},
        academic_overrides={"gpa_prior_period": 2.500, "gpa_current_period": 1.250,
                            "credits_prior_period": 3, "credits_current_period": 2},
    )

    ruled = validate_success(api.evaluate_case(ctx["case"]["id"], fx.REVIEWER), 200)

    assert ruled["gpa_variant_applied"] == "FINAL"
    assert ruled["effective_gpa"] == pytest.approx(2.000, abs=0.0005)
    assert ruled["status"] == "PROVISIONAL_ELIGIBLE"
    assert ruled["ineligibility_reason"] is None
    assert ruled["evaluation_count"] == 1


def test_final_gpa_one_notch_below_two_point_zero_fails_the_academic_rung(api):
    """PRD §3.4: "The athlete's effective grade point average must be at least
    2.000. Below that, the rung fails with `ACADEMIC_GPA`."
    PRD §3.4: "Both outcomes are symmetric in everything else they write: both set
    `gpa_variant_applied` and `effective_gpa` from the variant computation —
    including on rungs that fail before academics is ever reached — and both
    increment `evaluation_count` by 1."

    Design: Difficulty/boundary_precision_check/final_gpa_exactly_at_two_point_zero_clears_the_academic_rung
    """
    ctx = fx.setup_case_ready_for_evaluation(
        clock="2026-10-05T09:00:00Z",
        student_overrides={"full_name": "Gus Iwu", "birth_date": "2009-01-30",
                           "grade_level": 12, "residency_verified": True,
                           "residency_verified_on": "2026-08-10"},
        academic_overrides={"gpa_prior_period": 2.500, "gpa_current_period": 1.200,
                            "credits_prior_period": 3, "credits_current_period": 2},
    )

    ruled = validate_success(api.evaluate_case(ctx["case"]["id"], fx.REVIEWER), 200)

    assert ruled["gpa_variant_applied"] == "FINAL"
    assert ruled["effective_gpa"] == pytest.approx(1.980, abs=0.0005)
    assert ruled["status"] == "INELIGIBLE"
    assert ruled["ineligibility_reason"] == "ACADEMIC_GPA"
    assert ruled["evaluation_count"] == 1


def test_transfer_sitout_clears_at_exactly_three_hundred_sixty_five_days(api):
    """PRD §3.4: "For every other transfer, the sit-out is measured as the number
    of whole calendar days between `transfer_date` and the season's
    `first_contest_date`, computed over UTC dates counting the start date and not
    counting the end date. Fewer than 365 such days and the rung fails with
    `TRANSFER_SITOUT`; 365 or more clears it."

    Design: Corner/calculations/transfer_sitout_clears_at_exactly_three_hundred_sixty_five_days
    """
    set_clock("2026-09-10T09:00:00Z")
    school = fx.create_school(name="North High", fee_cap_cents=20000)
    previous = fx.create_school(name="South High", region_code="R-SOUTH")
    season = fx.create_season(first_contest_date="2026-09-01")
    fx.open_season_to_regular(season["id"])

    cases = {}
    for key, name, transfer_date, birth in (
        ("in_time", "Yara Bekele", "2025-09-01", "2009-05-14"),
        ("one_day_short", "Zane Bekele", "2025-09-02", "2009-06-14"),
    ):
        student = fx.create_student(
            school["id"], full_name=name, birth_date=birth, grade_level=11,
            previous_school_id=previous["id"], transfer_date=transfer_date,
            residency_verified=True, residency_verified_on="2026-08-10",
        )
        fx.post_academic_record(student["id"], school["id"], gpa_prior_period=3.000,
                                gpa_current_period=3.000, credits_prior_period=3,
                                credits_current_period=3)
        case = fx.create_case(school["id"], student["id"], season["id"])
        fx.file_all_clearance_documents(case["id"], school["id"])
        cases[key] = case

    cleared = validate_success(api.evaluate_case(cases["in_time"]["id"], fx.REVIEWER), 200)
    failed = validate_success(
        api.evaluate_case(cases["one_day_short"]["id"], fx.REVIEWER), 200
    )

    assert cleared["status"] == "PROVISIONAL_ELIGIBLE"
    assert cleared["ineligibility_reason"] is None
    assert failed["status"] == "INELIGIBLE"
    assert failed["ineligibility_reason"] == "TRANSFER_SITOUT"


def test_athlete_who_is_exactly_nineteen_on_the_cutoff_fails_the_age_rung(api):
    """PRD §3.4: "The athlete's whole completed years of age are measured from
    `birth_date` to the season's `age_cutoff_date`, truncating toward zero, so an
    athlete born on the cutoff date's month and day is exactly that many years old
    on that date. An athlete who is 19 or older on the cutoff fails with
    `AGE_LIMIT`; 18 and under passes."
    PRD §3.4: "Both outcomes are symmetric in everything else they write: both set
    `gpa_variant_applied` and `effective_gpa` from the variant computation —
    including on rungs that fail before academics is ever reached — and both
    increment `evaluation_count` by 1."

    Design: Corner/calculations/student_turning_nineteen_exactly_on_the_cutoff_date_is_age_ineligible
    """
    ctx = fx.setup_case_ready_for_evaluation(
        clock="2026-09-10T09:00:00Z",
        season_overrides={"age_cutoff_date": "2026-09-01"},
        student_overrides={"full_name": "Abe Toledo", "birth_date": "2007-09-01",
                           "grade_level": 12, "residency_verified": True,
                           "residency_verified_on": "2026-08-10"},
        academic_overrides={"gpa_prior_period": 3.400, "gpa_current_period": 3.400,
                            "credits_prior_period": 3, "credits_current_period": 3},
    )

    ruled = validate_success(api.evaluate_case(ctx["case"]["id"], fx.REVIEWER), 200)

    assert ruled["status"] == "INELIGIBLE"
    assert ruled["ineligibility_reason"] == "AGE_LIMIT"
    assert ruled["effective_gpa"] == pytest.approx(3.400, abs=0.0005)


def test_a_physical_expired_against_the_clock_fails_the_documents_rung(api, admin_headers):
    """PRD §3.4: "Each of the three form types is examined in turn, and the case
    must hold, for every one of them, at least one filed form whose `expires_on` is
    on or after the logical clock's UTC date. Freshness here is decided purely by
    that date comparison — there is no stored flag to consult and no filtering on
    any status. If any one of the three types has no such form, the rung fails with
    `DOCS_INCOMPLETE`."
    PRD §3.4: "Its `status` is not stored but derived on every read: `VALID` when
    `expires_on` is on or after the logical clock's UTC date, and `EXPIRED`
    otherwise."

    Design: Corner/calculations/expired_physical_form_fails_the_documents_rung
    """
    ctx = fx.setup_case_ready_for_evaluation(
        clock="2026-09-10T09:00:00Z",
        student_overrides={"full_name": "Bea Cortez", "residency_verified": True,
                           "residency_verified_on": "2026-08-10"},
        academic_overrides={"gpa_prior_period": 3.400, "gpa_current_period": 3.400,
                            "credits_prior_period": 3, "credits_current_period": 3},
        documents=("PARENT_CONSENT", "CONCUSSION_ACK"),
        doc_expires_on="2027-07-20",
    )
    fx.file_document(ctx["case"]["id"], ctx["school"]["id"], "PHYSICAL",
                     issued_on="2025-09-01", expires_on="2026-09-01")

    ruled = validate_success(api.evaluate_case(ctx["case"]["id"], fx.REVIEWER), 200)

    assert ruled["status"] == "INELIGIBLE"
    assert ruled["ineligibility_reason"] == "DOCS_INCOMPLETE"

    forms, _meta = validate_paginated(
        api.list_clearance_documents(ctx["case"]["id"], admin_headers, {"limit": 100})
    )
    assert len(forms) == 3
    freshness = {form["doc_type"]: form["status"] for form in forms}
    assert freshness["PHYSICAL"] == "EXPIRED"
    assert freshness["PARENT_CONSENT"] == "VALID"
    assert freshness["CONCUSSION_ACK"] == "VALID"


def test_ladder_reports_only_the_earliest_failing_rung(api):
    """PRD §3.4: "The rungs are evaluated in exactly this order — age, then
    residency, then transfer, then documents, then academics — and evaluation
    **stops at the first failure**."
    PRD §3.4: "The reported `ineligibility_reason` names that first failure and
    nothing else, which means a case failing three rungs is indistinguishable, in
    what it reports, from a case failing only the earliest of the three."
    PRD §3.4: "The rung fails with `RESIDENCY_UNVERIFIED` in any of three
    situations: `residency_verified` is false, or `residency_verified_on` is null,
    or `residency_verified_on` falls strictly after the season's
    `residency_deadline`."

    Design: Corner/calculations/ladder_reports_only_the_highest_failing_rung_when_three_rungs_fail
    """
    ctx = fx.setup_case_ready_for_evaluation(
        clock="2026-09-10T09:00:00Z",
        student_overrides={"full_name": "Cai Mensah", "residency_verified": False,
                           "residency_verified_on": None},
        academic_overrides={"gpa_prior_period": 1.100, "gpa_current_period": 1.100,
                            "credits_prior_period": 3, "credits_current_period": 3},
        documents=("PHYSICAL", "PARENT_CONSENT"),
    )

    ruled = validate_success(api.evaluate_case(ctx["case"]["id"], fx.REVIEWER), 200)

    assert ruled["status"] == "INELIGIBLE"
    assert ruled["ineligibility_reason"] == "RESIDENCY_UNVERIFIED"
    assert ruled["ineligibility_reason"] != "DOCS_INCOMPLETE"
    assert ruled["ineligibility_reason"] != "ACADEMIC_GPA"
    assert ruled["effective_gpa"] == pytest.approx(1.100, abs=0.0005)


def test_clearance_form_is_immutable_and_reports_freshness_on_read(api, reviewer_headers):
    """PRD §2.4: "A `ClearanceDocument` carries only `id` and `created_at`: it has
    no `updated_at` and no `version`, because a filed form is never edited."
    PRD §3.4: "Its `status` is not stored but derived on every read: `VALID` when
    `expires_on` is on or after the logical clock's UTC date, and `EXPIRED`
    otherwise."

    Design: Corner/entities/clearance_document_is_immutable_and_carries_no_version_field
    """
    ctx = fx.setup_case_ready_for_evaluation(
        clock="2026-09-10T09:00:00Z",
        student_overrides={"full_name": "Mo Idris", "grade_level": 10},
        documents=("PHYSICAL",),
        doc_expires_on="2027-07-15",
    )

    forms, _meta = validate_paginated(
        api.list_clearance_documents(ctx["case"]["id"], reviewer_headers,
                                     {"doc_type": "PHYSICAL"})
    )

    assert len(forms) == 1
    form = forms[0]
    assert_clearance_document(form)
    assert form["status"] == "VALID"
    assert "version" not in form, "a filed form carries no version counter"
    assert "updated_at" not in form, "a filed form carries no updated_at"
