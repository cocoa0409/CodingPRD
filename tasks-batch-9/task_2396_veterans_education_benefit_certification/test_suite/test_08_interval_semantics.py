"""The two interval rules that deliberately use different semantics.

An enrollment period is a closed interval scoped to the student, so a shared
endpoint is a collision, while a catalog version's effective window is half-open,
so a shared endpoint is legal.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers.fixtures import (
    create_certification,
    create_verified_student,
    price_certification,
    read_certification,
    submit_certification,
)

FIRST_TERM_CODE = "FA2026A"
FIRST_TERM_START = "2026-08-24"
FIRST_TERM_END = "2026-10-15"
SECOND_TERM_CODE = "FA2026B"
SECOND_TERM_START = "2026-10-15"
SECOND_TERM_END = "2026-12-11"
LATE_DEADLINE = "2026-12-31"

NEXT_CATALOG_YEAR = "2027-2028"
TOUCHING_START = "2027-07-01"
TOUCHING_END = "2028-07-01"
OVERLAPPING_START = "2027-06-30"
OVERLAPPING_END = "2028-06-30"


# ─── Enrollment periods: closed intervals ─────────────────────────────
def _two_back_to_back_terms_for_one_student(api, baseline):
    """Certify nothing yet: one submitted period ending exactly where the next starts."""
    first_term = get_success_data(
        api.create_academic_term(
            f.academic_term_payload(
                term_code=FIRST_TERM_CODE,
                start_date=FIRST_TERM_START,
                end_date=FIRST_TERM_END,
                drop_deadline="2026-09-04",
                certification_deadline=LATE_DEADLINE,
            ),
            baseline.sup_headers,
        )
    )
    second_term = get_success_data(
        api.create_academic_term(
            f.academic_term_payload(
                term_code=SECOND_TERM_CODE,
                start_date=SECOND_TERM_START,
                end_date=SECOND_TERM_END,
                drop_deadline="2026-10-23",
                certification_deadline=LATE_DEADLINE,
            ),
            baseline.sup_headers,
        )
    )
    student_id = create_verified_student(api, baseline.sco_headers)

    first_id, first_version = create_certification(
        api,
        baseline.sco_headers,
        student_id,
        first_term["id"],
        baseline.program_id,
        term_start_certified=FIRST_TERM_START,
        term_end_certified=FIRST_TERM_END,
    )
    price_certification(
        api,
        first_id,
        first_version,
        gross_tuition_cents=1500000,
        mandatory_fees_cents=0,
        tuition_specific_aid_cents=0,
    )
    submit_certification(api, baseline.sco_headers, first_id)

    second_id, second_version = create_certification(
        api,
        baseline.sco_headers,
        student_id,
        second_term["id"],
        baseline.program_id,
        term_start_certified=SECOND_TERM_START,
        term_end_certified=SECOND_TERM_END,
    )
    price_certification(
        api,
        second_id,
        second_version,
        gross_tuition_cents=1500000,
        mandatory_fees_cents=0,
        tuition_specific_aid_cents=0,
    )
    return first_id, second_id


def test_a_touching_endpoint_counts_as_an_enrollment_period_collision(api, baseline):
    """A second period starting on the day the first one ends cannot be submitted.

    PRD: "Enrollment-period collision is judged on a **closed** interval scoped to
    the student: no other enrollment certification of the same student whose
    `status` is `SUBMITTED`, `CERTIFIED` or `AMENDMENT_PENDING` may share **any**
    day with the period running from `term_start_certified` through
    `term_end_certified` inclusive, and a merely touching endpoint counts as a
    collision — if another certification's `term_end_certified` falls on exactly
    this certification's `term_start_certified`, the submission is rejected."

    Design: Difficulty/resource_temporal_overlap/student_enrollment_periods_are_closed_intervals_touching_endpoints_collide
    """
    first_id, second_id = _two_back_to_back_terms_for_one_student(api, baseline)

    response = api.submit_certification(second_id, {}, baseline.sco_headers)
    validate_error(response, e.ERR_OVERLAPPING_ENROLLMENT_PERIOD, 409)

    assert (
        read_certification(api, baseline.sco_headers, second_id)["status"]
        == c.CERT_STATUS_DRAFT
    )
    assert (
        read_certification(api, baseline.sco_headers, first_id)["status"]
        == c.CERT_STATUS_SUBMITTED
    )


def test_moving_the_certified_start_one_day_later_clears_the_collision(api, baseline):
    """With no shared day the submission passes and the inclusive count is 57 days.

    PRD: "First, `certified_days` is the inclusive count of days in the certified
    period: the whole number of days from `term_start_certified` to
    `term_end_certified`, plus one, so that a period whose start and end fall on
    the same day counts as one day."

    Design: Difficulty/resource_temporal_overlap/student_enrollment_periods_are_closed_intervals_touching_endpoints_collide
    """
    _first_id, second_id = _two_back_to_back_terms_for_one_student(api, baseline)
    api.submit_certification(second_id, {}, baseline.sco_headers)

    get_success_data(
        api.update_enrollment_certification(
            second_id, {"term_start_certified": "2026-10-16"}, baseline.sco_headers
        )
    )
    submitted = get_success_data(
        api.submit_certification(second_id, {}, baseline.sco_headers)
    )
    a.assert_fields(
        submitted,
        {
            "status": c.CERT_STATUS_SUBMITTED,
            "term_start_certified": "2026-10-16",
            "certified_days": 57,
        },
    )


# ─── Catalog windows: half-open intervals ─────────────────────────────
def test_a_catalog_window_that_merely_touches_the_previous_one_is_accepted(
    api, baseline
):
    """The new window starts on the day the approved window stops governing.

    PRD: "Because the window semantics are half-open, so is the collision rule: a
    new version may not overlap any other catalog version of the same program
    whose `review_status` is `PENDING_SAA`, `APPROVED` or
    `APPROVED_WITH_CONDITIONS`, and a collision is refused with
    `ERR_CATALOG_WINDOW_OVERLAP` — but two windows that merely touch, where the
    earlier version's `effective_end` equals the new version's `effective_start`,
    are perfectly legal and must be accepted."

    Design: Difficulty/resource_temporal_overlap/catalog_effective_windows_are_half_open_touching_endpoints_are_legal
    """
    response = api.create_catalog_version(
        f.catalog_version_payload(
            baseline.program_id,
            catalog_year=NEXT_CATALOG_YEAR,
            effective_start=TOUCHING_START,
            effective_end=TOUCHING_END,
        ),
        baseline.sup_headers,
    )
    created = get_success_data(response, expected_status=201)
    a.assert_fields(
        created,
        {
            "review_status": c.CATALOG_REVIEW_DRAFT,
            "effective_start": TOUCHING_START,
            "effective_end": TOUCHING_END,
            "suspension_reason": None,
            "conditions_note": None,
        },
    )


def test_a_catalog_window_that_overlaps_by_one_day_is_rejected(api, baseline):
    """Starting a day earlier shares 2027-06-30 with the approved window.

    PRD: "That window is **half-open**: `effective_start` is the first day the
    version governs and is inclusive, while `effective_end` is the day the version
    stops governing and is exclusive."

    Design: Difficulty/resource_temporal_overlap/catalog_effective_windows_are_half_open_touching_endpoints_are_legal
    """
    get_success_data(
        api.create_catalog_version(
            f.catalog_version_payload(
                baseline.program_id,
                catalog_year=NEXT_CATALOG_YEAR,
                effective_start=TOUCHING_START,
                effective_end=TOUCHING_END,
            ),
            baseline.sup_headers,
        ),
        expected_status=201,
    )

    response = api.create_catalog_version(
        f.catalog_version_payload(
            baseline.program_id,
            catalog_year=NEXT_CATALOG_YEAR,
            effective_start=OVERLAPPING_START,
            effective_end=OVERLAPPING_END,
        ),
        baseline.sup_headers,
    )
    validate_error(response, e.ERR_CATALOG_WINDOW_OVERLAP, 409)

    versions = get_success_data(
        api.list_catalog_versions(
            baseline.sup_headers, {"program_id": baseline.program_id, "limit": 100}
        )
    )
    assert len(versions) == 2, f"Expected exactly two catalog versions, got {versions}"
    approved = [
        row for row in versions if row["review_status"] == c.CATALOG_REVIEW_APPROVED
    ]
    assert len(approved) == 1
    assert approved[0]["effective_end"] == c.CATALOG_EFFECTIVE_END
