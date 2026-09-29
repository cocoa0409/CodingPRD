"""Structurally valid bodies that the semantic rules still refuse.

Natural-key collisions, mutually inconsistent term dates, an online portion
larger than the load it belongs to, a clock asked to move backwards, and a
compliance checklist with one box left unticked.
"""

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers.fixtures import create_program, create_student, read_student
from test_helpers.test_users import VA_HEADERS

OTHER_PROGRAM_NAME = "Accounting MS"
OTHER_OFFICIAL_NAME = "Rowan Diaz"
LATER_WINDOW_END = "2028-07-01"

SIX_CREDIT_HOURS = 6
NINE_CREDIT_HOURS_ONLINE = 9

CLOCK_ONE_SECOND_EARLY = "2026-07-31T23:59:59Z"
CLOCK_FORWARD_DATE = "2026-09-05"


# ─── Natural-key collisions ───────────────────────────────────────────
def test_a_reused_student_number_is_refused_and_leaves_the_first_student_alone(
    api, baseline
):
    """Every other field differs, and the collision still decides the response.

    PRD: "On veteran student creation, `student_number` is not already used by
    another veteran student, else `ERR_DUPLICATE_STUDENT_NUMBER` (409)."

    Design: Corner/validations/each_natural_key_collision_returns_its_own_duplicate_error
    """
    student_id = create_student(api, baseline.sco_headers)

    response = api.create_veteran_student(
        f.veteran_student_payload(
            full_name=c.SECOND_STUDENT_NAME,
            chapter=c.CHAPTER_CH30,
            delimiting_date=c.SECOND_DELIMITING_DATE,
        ),
        baseline.sco_headers,
    )
    validate_error(response, "ERR_DUPLICATE_STUDENT_NUMBER", expected_status=409)

    rows, meta = validate_paginated(api.list_veteran_students(baseline.sco_headers))
    assert meta["total_count"] == 1
    assert len(rows) == 1
    student = read_student(api, baseline.sco_headers, student_id)
    a.assert_fields(
        student,
        {
            "student_number": c.STUDENT_NUMBER,
            "full_name": c.STUDENT_NAME,
            "chapter": c.STUDENT_CHAPTER_CH33,
        },
    )


def test_a_reused_term_code_is_refused_even_with_a_different_term_and_dates(
    api, baseline
):
    """A spring term borrowing the fall term's code collides on the code alone.

    PRD: "On academic term creation, `term_code` is not already used by another
    term, else `ERR_DUPLICATE_TERM_CODE` (409)."

    Design: Corner/validations/each_natural_key_collision_returns_its_own_duplicate_error
    """
    response = api.create_academic_term(
        f.spring_term_payload(term_code=c.TERM_CODE), baseline.sup_headers
    )
    validate_error(response, "ERR_DUPLICATE_TERM_CODE", expected_status=409)

    rows, meta = validate_paginated(api.list_academic_terms(baseline.sup_headers))
    assert meta["total_count"] == 1
    assert rows[0]["term_code"] == c.TERM_CODE


def test_a_reused_program_code_is_refused_even_at_a_different_degree_level(
    api, baseline
):
    """A graduate program cannot borrow the undergraduate program's code.

    PRD: "On program creation, `program_code` is not already used by another
    program, else `ERR_DUPLICATE_PROGRAM_CODE` (409)."

    Design: Corner/validations/each_natural_key_collision_returns_its_own_duplicate_error
    """
    response = api.create_program(
        f.program_payload(
            name=OTHER_PROGRAM_NAME, degree_level=c.DEGREE_LEVEL_GRADUATE
        ),
        baseline.sup_headers,
    )
    validate_error(response, "ERR_DUPLICATE_PROGRAM_CODE", expected_status=409)

    rows, meta = validate_paginated(api.list_programs(baseline.sup_headers))
    assert meta["total_count"] == 1
    assert rows[0]["program_code"] == c.PROGRAM_CODE
    assert rows[0]["degree_level"] == c.DEGREE_LEVEL_UNDERGRAD


def test_a_reused_official_email_is_refused_even_at_a_different_authority_tier(
    api, baseline
):
    """The front-line official's address cannot be re-credentialed as supervisory.

    PRD: "On certifying official creation, `email` is not already used by another
    official, else `ERR_DUPLICATE_OFFICIAL_EMAIL` (409)."

    Design: Corner/validations/each_natural_key_collision_returns_its_own_duplicate_error
    """
    response = api.create_certifying_official(
        f.sco_official_payload(
            full_name=OTHER_OFFICIAL_NAME, official_level=c.LEVEL_SUPERVISORY
        ),
        VA_HEADERS,
    )
    validate_error(response, "ERR_DUPLICATE_OFFICIAL_EMAIL", expected_status=409)

    rows, meta = validate_paginated(api.list_certifying_officials(VA_HEADERS))
    assert meta["total_count"] == 2
    levels = sorted(row["official_level"] for row in rows)
    assert levels == [c.LEVEL_SCO, c.LEVEL_SUPERVISORY]


# ─── Semantic date and split rules ────────────────────────────────────
@pytest.mark.parametrize(
    "overrides",
    [
        {"start_date": "2026-12-20"},
        {"drop_deadline": "2026-12-20"},
        {"certification_deadline": "2026-08-01"},
    ],
    ids=["start_after_end", "drop_deadline_past_end", "deadline_before_start"],
)
def test_mutually_inconsistent_term_dates_are_refused(api, baseline, overrides):
    """Each of the three ordering clauses is independently blocking.

    PRD: "On academic term creation, `start_date` is strictly before `end_date`,
    `drop_deadline` is on or after `start_date` and on or before `end_date`, and
    `certification_deadline` is on or after `start_date`, else
    `ERR_INVALID_TERM_DATES` (422)."

    Design: Corner/validations/term_date_ordering_and_credit_split_violations_are_rejected
    """
    dates = {
        "start_date": c.TERM_START,
        "end_date": c.TERM_END,
        "drop_deadline": c.TERM_DROP_DEADLINE,
        "certification_deadline": c.TERM_CERTIFICATION_DEADLINE,
    }
    dates.update(overrides)

    response = api.create_academic_term(
        f.spring_term_payload(term_code=c.SPRING_TERM_CODE, **dates),
        baseline.sup_headers,
    )
    validate_error(response, "ERR_INVALID_TERM_DATES", expected_status=422)

    rows, meta = validate_paginated(api.list_academic_terms(baseline.sup_headers))
    assert meta["total_count"] == 1
    assert rows[0]["term_code"] == c.TERM_CODE


def test_an_online_portion_larger_than_the_total_load_is_refused(api, baseline):
    """Nine online hours against a six-hour load is not a certifiable enrollment.

    PRD: "An online portion exceeding the total is refused with
    `ERR_INVALID_CREDIT_SPLIT`."

    Design: Corner/validations/term_date_ordering_and_credit_split_violations_are_rejected
    """
    student_id = create_student(api, baseline.sco_headers)

    response = api.create_enrollment_certification(
        f.certification_payload(
            student_id,
            baseline.term_id,
            baseline.program_id,
            credit_hours_total=SIX_CREDIT_HOURS,
            credit_hours_online=NINE_CREDIT_HOURS_ONLINE,
        ),
        baseline.sco_headers,
    )
    validate_error(response, "ERR_INVALID_CREDIT_SPLIT", expected_status=422)

    _rows, meta = validate_paginated(
        api.list_enrollment_certifications(baseline.sco_headers)
    )
    assert meta["total_count"] == 0


# ─── The logical clock ────────────────────────────────────────────────
def test_the_clock_refuses_an_instant_one_second_before_its_current_value(api):
    """Rewinding by a single second is refused just as a whole day would be.

    PRD: "The clock never moves backwards: if the supplied instant is earlier than
    the clock's current value, the request is rejected with `ERR_CLOCK_REWIND`
    (HTTP 422)."

    Design: Corner/validations/the_logical_clock_refuses_to_move_backwards
    """
    response = api.set_clock(f.clock_payload(CLOCK_ONE_SECOND_EARLY), VA_HEADERS)
    validate_error(response, "ERR_CLOCK_REWIND", expected_status=422)


def test_setting_the_clock_to_its_current_value_is_accepted(api):
    """The guard is strictly-earlier, so an equal instant is not a rewind.

    PRD: "A value equal to the current clock is accepted."

    Design: Corner/validations/the_logical_clock_refuses_to_move_backwards
    """
    response = api.set_clock(
        f.clock_payload(f.clock_instant(c.CLOCK_START_DATE)), VA_HEADERS
    )
    validate_success(response)


def test_after_a_forward_move_the_old_instant_is_itself_a_rewind(api):
    """The comparison is against the clock's current value, not its startup value.

    PRD: "On advancing the clock, `to_iso8601` is on or after the current logical
    clock value, else `ERR_CLOCK_REWIND` (422)."

    Design: Corner/validations/the_logical_clock_refuses_to_move_backwards
    """
    validate_success(
        api.set_clock(f.clock_payload(f.clock_instant(CLOCK_FORWARD_DATE)), VA_HEADERS)
    )

    response = api.set_clock(
        f.clock_payload(f.clock_instant(c.CLOCK_START_DATE)), VA_HEADERS
    )
    validate_error(response, "ERR_CLOCK_REWIND", expected_status=422)

    validate_success(
        api.set_clock(f.clock_payload(f.clock_instant(CLOCK_FORWARD_DATE)), VA_HEADERS)
    )


# ─── The compliance checklist ─────────────────────────────────────────
def _draft_catalog(api, sup_headers, program_id, **overrides):
    """A catalog version sitting at DRAFT with the given attestation overrides."""
    return get_success_data(
        api.create_catalog_version(
            f.catalog_version_payload(program_id, **overrides), sup_headers
        ),
        expected_status=201,
    )


@pytest.mark.parametrize(
    "unticked",
    [
        "has_published_tuition_schedule",
        "has_refund_policy",
        "has_program_length_disclosure",
    ],
)
def test_one_unticked_attestation_blocks_the_submission_to_the_agency(
    api, officials, unticked
):
    """Each of the three booleans is independently blocking.

    PRD: "All three compliance attestations must be true at that moment, or the
    submission is refused with `ERR_CATALOG_COMPLIANCE_INCOMPLETE`."

    Design: Corner/validations/an_incomplete_catalog_checklist_cannot_be_sent_to_the_state_approving_agency
    """
    program_id = create_program(api, officials.sup_headers)
    catalog = _draft_catalog(
        api, officials.sup_headers, program_id, **{unticked: False}
    )

    response = api.submit_catalog_version_to_saa(
        catalog["id"], {}, officials.sup_headers
    )
    validate_error(response, "ERR_CATALOG_COMPLIANCE_INCOMPLETE", expected_status=422)

    assert (
        get_success_data(api.get_catalog_version(catalog["id"], officials.sup_headers))[
            "review_status"
        ]
        == c.CATALOG_REVIEW_DRAFT
    )
    assert (
        get_success_data(api.get_program(program_id, officials.sup_headers))[
            "approval_status"
        ]
        == c.PROGRAM_STATUS_DRAFT
    )


def test_a_fully_ticked_checklist_reaches_the_agency(api, officials):
    """With all three boxes ticked the version moves on to await the agency.

    PRD: "The submission moves the version to `PENDING_SAA`, and when it comes from
    `SUSPENDED` it also clears the stored `suspension_reason`."

    Design: Corner/validations/an_incomplete_catalog_checklist_cannot_be_sent_to_the_state_approving_agency
    """
    program_id = create_program(api, officials.sup_headers)
    catalog = _draft_catalog(api, officials.sup_headers, program_id)

    submitted = get_success_data(
        api.submit_catalog_version_to_saa(catalog["id"], {}, officials.sup_headers)
    )
    assert submitted["review_status"] == c.CATALOG_REVIEW_PENDING_SAA


def test_the_cascade_reaches_the_program_only_on_the_compliant_submission(
    api, officials
):
    """The program follows its catalog into review once the submission is accepted.

    PRD: "Whatever the program's `approval_status` was — `DRAFT`, `APPROVED`,
    `CONDITIONAL` or `SUSPENDED` — it is set to `PENDING_SAA`, because an open
    agency re-review suspends the program's certifiable posture regardless of where
    it stood before."

    Design: Corner/validations/an_incomplete_catalog_checklist_cannot_be_sent_to_the_state_approving_agency
    """
    program_id = create_program(api, officials.sup_headers)
    incomplete = _draft_catalog(
        api, officials.sup_headers, program_id, has_refund_policy=False
    )
    validate_error(
        api.submit_catalog_version_to_saa(
            incomplete["id"], {}, officials.sup_headers
        ),
        "ERR_CATALOG_COMPLIANCE_INCOMPLETE",
        expected_status=422,
    )
    assert (
        get_success_data(api.get_program(program_id, officials.sup_headers))[
            "approval_status"
        ]
        == c.PROGRAM_STATUS_DRAFT
    )

    compliant = _draft_catalog(
        api,
        officials.sup_headers,
        program_id,
        catalog_year=c.CATALOG_YEAR,
        effective_start=c.CATALOG_EFFECTIVE_END,
        effective_end=LATER_WINDOW_END,
    )
    get_success_data(
        api.submit_catalog_version_to_saa(compliant["id"], {}, officials.sup_headers)
    )

    assert (
        get_success_data(api.get_program(program_id, officials.sup_headers))[
            "approval_status"
        ]
        == c.PROGRAM_STATUS_PENDING_SAA
    )
