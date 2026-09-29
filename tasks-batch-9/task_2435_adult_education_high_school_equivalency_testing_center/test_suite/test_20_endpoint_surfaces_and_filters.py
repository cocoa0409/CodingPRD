"""The endpoint surfaces themselves: filters that compose with the paging window, a signed
adjustment endpoint that behaves as a ledger, the side-effect-free preview beside its committing
run, an optional cross-reference that is stored and filterable, and a conditional assignment.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import ApiErrorId, api_client, factories, fixtures
from test_helpers.assertions import assert_allocation_preview, assert_hours_value
from test_helpers.test_users import (
    make_center_administrator_headers,
    make_instructor_headers,
    make_program_coordinator_headers,
    make_registrar_headers,
    make_state_authority_headers,
)
from test_helpers.types import (
    AllocationStatus,
    AllocationVariant,
    CenterDecision,
    MeasureType,
    ProctorCertificationStatus,
    ProctorDecision,
    ProgramTrack,
    SectionStatus,
    SessionStatus,
    Subtest,
    TestEventPurpose,
    TestEventStatus,
    TestForm,
)

MORNING = {
    "title": "HSE Morning",
    "instructor_user_id": "instructor-31",
    "min_efl_level": 2,
    "max_efl_level": 6,
    "seats_total": 20,
    "weekly_hours": 9.00,
}
EVENING = {
    "title": "HSE Evening",
    "instructor_user_id": "instructor-32",
    "min_efl_level": 3,
    "max_efl_level": 6,
    "seats_total": 15,
    "weekly_hours": 6.00,
}
BEGINNERS = {
    "title": "ESL Beginners",
    "instructor_user_id": "instructor-33",
    "min_efl_level": 1,
    "max_efl_level": 3,
    "seats_total": 12,
    "weekly_hours": 4.00,
}

FIRST_CREDIT_CENTS = 5000
SECOND_CREDIT_CENTS = 1400
DEBIT_CENTS = -2400
NO_OP_CENTS = 0
BALANCE_AFTER_FIRST = 5000
BALANCE_AFTER_SECOND = 6400
BALANCE_AFTER_DEBIT = 4000

PREVIEW_LABEL = "FY27-H1"
PREVIEW_WINDOW = ("2026-08-01", "2027-02-01")
PREVIEW_RATE_CENTS = 8000
PREVIEW_POOL_CENTS = 400000
EMPLOYMENT_LINE_CENTS = 10000
POSTSECONDARY_LINE_CENTS = 11200
COMMITTED_TOTAL_CENTS = 21200
REMAINING_CENTS = 378800
TOTAL_WEIGHT = 2.65
RECORDING_COORDINATOR = "coord-1"
CERTIFYING_AUTHORITY = "state-1"

PRE_TEST_AT = "2026-08-02T09:00:00Z"
LINK_SECTION = {
    "title": "Linked Events",
    "instructor_user_id": "instructor-34",
    "min_efl_level": 1,
    "max_efl_level": 6,
    "seats_total": 10,
    "weekly_hours": 8.00,
}
FULL_DAY_DATES = ("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07")
FULL_DAY_HOURS = 8.00
LEDGER_CLOCK = "2026-08-08T09:00:00Z"
THIRTY_DAYS_ON = "2026-09-02T09:00:00Z"
POST_TEST_AT = "2026-09-03T09:00:00Z"

CONDITIONAL_SITTING = ("2026-08-25T09:00:00Z", "2026-08-25T11:00:00Z")
CONDITIONAL_SEATS = 6
USABLE_EXPIRY = "2027-01-01T00:00:00Z"


def _section(program_track, status, spec):
    return fixtures.create_section(status=status, program_track=program_track, **spec)


def _three_sections():
    planned = _section(ProgramTrack.HSE_PREP, SectionStatus.PLANNED, MORNING)
    open_hse = _section(ProgramTrack.HSE_PREP, SectionStatus.OPEN, EVENING)
    open_esl = _section(ProgramTrack.ESL, SectionStatus.OPEN, BEGINNERS)
    return planned, open_hse, open_esl


def _list_sections(headers, **params):
    return validate_paginated(
        api_client.list_class_sections(
            headers=headers, params={"limit": 10, "offset": 0, **params}
        )
    )


def _adjust(student_id, delta_cents, headers):
    return validate_success(
        api_client.adjust_voucher(
            student_id, factories.voucher_adjustment_payload(delta_cents), headers=headers
        )
    )


def _list_outcomes(period_id, allocation_status):
    return validate_paginated(
        api_client.list_outcome_records(
            headers=make_state_authority_headers(CERTIFYING_AUTHORITY),
            params={
                "funding_period_id": period_id,
                "allocation_status": allocation_status,
                "limit": 10,
                "offset": 0,
            },
        )
    )


def _setup_two_certified_claims():
    period = fixtures.create_funding_period(
        label=PREVIEW_LABEL,
        start_date=PREVIEW_WINDOW[0],
        end_date=PREVIEW_WINDOW[1],
        rate_cents_per_weight=PREVIEW_RATE_CENTS,
        total_cents=PREVIEW_POOL_CENTS,
    )
    first = fixtures.create_student(
        full_name="Ilse Vogt", email="ilse.vogt@example.org", primary_track=ProgramTrack.HSE_PREP
    )
    second = fixtures.create_student(
        full_name="Kwame Osei", email="kwame.osei@example.org", primary_track=ProgramTrack.HSE_PREP
    )
    coordinator = make_program_coordinator_headers(RECORDING_COORDINATOR)
    authority = make_state_authority_headers(CERTIFYING_AUTHORITY)
    employment = fixtures.record_outcome(
        first["id"],
        period["id"],
        measure_type=MeasureType.EMPLOYMENT_Q2,
        evidence_ref="ev-ilse-q2",
        headers=coordinator,
    )
    postsecondary = fixtures.record_outcome(
        second["id"],
        period["id"],
        measure_type=MeasureType.POSTSECONDARY_ENROLLMENT,
        evidence_ref="ev-kwame-ps",
        headers=coordinator,
    )
    fixtures.decide_outcome(employment["id"], headers=authority)
    fixtures.decide_outcome(postsecondary["id"], headers=authority)
    return {
        "period": period,
        "employment_id": employment["id"],
        "postsecondary_id": postsecondary["id"],
    }


def _setup_enrollment_with_forty_hours():
    placed = fixtures.create_placed_student(
        scale_score=205,
        test_form=TestForm.CASAS_R_900,
        pre_test_at=PRE_TEST_AT,
        full_name="Lena Marsh",
        email="lena.marsh@example.org",
        primary_track=ProgramTrack.HSE_PREP,
    )
    section = _section(ProgramTrack.HSE_PREP, SectionStatus.OPEN, LINK_SECTION)
    enrollment = fixtures.enroll(placed["student_id"], section["id"])
    fixtures.set_clock(LEDGER_CLOCK)
    for attendance_date in FULL_DAY_DATES:
        fixtures.post_attendance(enrollment["id"], attendance_date, FULL_DAY_HOURS)
    fixtures.set_clock(THIRTY_DAYS_ON)
    return {
        "student_id": placed["student_id"],
        "pre_test_id": placed["pre_test"]["id"],
        "enrollment_id": enrollment["id"],
    }


def test_01_a_section_read_reports_its_band_seats_and_transition_count():
    """"A new section opens its life with `status` `PLANNED`, `seats_taken` at 0 and
    `seats_available` equal to `seats_total`." and "Each accepted transition increases the
    section's `version` by one."

    Design: Corner/endpoints/class_section_standard_crud_create_read_and_filtered_list
    """
    _planned, open_hse, _open_esl = _three_sections()

    stored = fixtures.read_class_section(open_hse["id"], headers=make_instructor_headers())
    assert stored["title"] == EVENING["title"]
    assert stored["status"] == SectionStatus.OPEN
    assert stored["seats_taken"] == 0
    assert stored["version"] == 2
    assert stored["min_efl_level"] == EVENING["min_efl_level"]
    assert stored["seats_available"] == EVENING["seats_total"]


def test_02_section_filters_are_applied_before_the_paging_window():
    """"List instructional sections, filterable by programme track and status." and
    "`total_count` is the number of records matching the filters before the pagination window is
    applied, and `has_more` states whether any matching record remains beyond the returned window."

    Design: Corner/endpoints/class_section_standard_crud_create_read_and_filtered_list
    """
    planned, open_hse, open_esl = _three_sections()
    registrar = make_registrar_headers()

    by_track, track_meta = _list_sections(registrar, program_track=ProgramTrack.HSE_PREP)
    assert track_meta["total_count"] == 2
    assert track_meta["has_more"] is False
    assert {row["id"] for row in by_track} == {planned["id"], open_hse["id"]}

    windowed, window_meta = validate_paginated(
        api_client.list_class_sections(
            headers=registrar,
            params={"status": SectionStatus.OPEN, "limit": 1, "offset": 1},
        )
    )
    assert len(windowed) == 1
    assert window_meta["total_count"] == 2
    assert window_meta["has_more"] is False
    assert windowed[0]["id"] in {open_hse["id"], open_esl["id"]}

    empty, empty_meta = _list_sections(
        make_state_authority_headers(),
        program_track=ProgramTrack.ESL,
        status=SectionStatus.PLANNED,
    )
    assert empty_meta["total_count"] == 0
    assert empty == []


def test_03_each_adjustment_answers_with_the_balance_it_produced():
    """"A `ProgramCoordinator` or `StateAuthority` adjusts a learner's voucher funds by
    submitting a `delta_cents` amount, which is added both to the lifetime
    `voucher_granted_cents` and to the spendable `voucher_balance_cents`. A negative
    `delta_cents` claws funds back."

    Design: Corner/endpoints/voucher_adjustment_action_endpoint_credits_then_debits_the_balance
    """
    student = fixtures.create_student(
        full_name="Omar Tessier",
        email="omar.tessier@example.org",
        primary_track=ProgramTrack.HSE_PREP,
    )
    assert fixtures.read_student(student["id"])["voucher_balance_cents"] == 0

    coordinator = make_program_coordinator_headers()
    first = _adjust(student["id"], FIRST_CREDIT_CENTS, coordinator)
    assert first["voucher_balance_cents"] == BALANCE_AFTER_FIRST

    second = _adjust(student["id"], SECOND_CREDIT_CENTS, make_state_authority_headers())
    assert second["voucher_balance_cents"] == BALANCE_AFTER_SECOND

    third = _adjust(student["id"], DEBIT_CENTS, coordinator)
    assert third["voucher_balance_cents"] == BALANCE_AFTER_DEBIT

    no_op = _adjust(student["id"], NO_OP_CENTS, coordinator)
    assert no_op["voucher_balance_cents"] == BALANCE_AFTER_DEBIT

    assert (
        fixtures.read_student(student["id"])["voucher_balance_cents"] == BALANCE_AFTER_DEBIT
    )


def test_04_the_preview_forecasts_the_run_without_touching_anything():
    """"A side-effect-free preview of the same computation is available to a `StateAuthority` or
    `ProgramCoordinator`, taking an optional `variant` that defaults to `FINAL`. It writes nothing
    at all — no claim's `allocation_status` moves and no counter advances"

    Design: Corner/endpoints/allocation_preview_computed_read_matches_the_committed_run
    """
    context = _setup_two_certified_claims()
    period = context["period"]
    version_before = fixtures.read_funding_period(period["id"])["version"]

    preview = assert_allocation_preview(
        fixtures.read_allocation_preview(
            period["id"],
            variant=AllocationVariant.FINAL,
            headers=make_program_coordinator_headers(RECORDING_COORDINATOR),
        )
    )
    assert preview["funding_period_id"] == period["id"]
    assert preview["variant"] == AllocationVariant.FINAL
    assert preview["line_count"] == 2
    assert preview["deferred_line_count"] == 0
    assert float(preview["total_weight"]) == TOTAL_WEIGHT
    assert preview["projected_committed_cents"] == COMMITTED_TOTAL_CENTS
    assert preview["projected_available_cents"] == REMAINING_CENTS

    after_preview = fixtures.read_funding_period(period["id"])
    assert after_preview["version"] == version_before
    assert after_preview["committed_cents"] == 0
    assert after_preview["allocation_run_count"] == 0

    _rows, meta = _list_outcomes(period["id"], AllocationStatus.UNALLOCATED)
    assert meta["total_count"] == 2


def test_05_the_run_commits_the_previewed_figure_and_the_replay_is_refused():
    """"When the walk finishes, the period's `committed_cents` rises by the exact integer sum of
    the committed line amounts, each already rounded, and `available_cents` is recomputed as
    `total_cents` less `committed_cents`." and "a run supersedes the previous view of the pool, so
    a stale `expected_funding_period_version` is refused with
    `ERR_STALE_FUNDING_PERIOD_VERSION` before the period's own `OPEN` status is even examined."

    Design: Corner/endpoints/allocation_preview_computed_read_matches_the_committed_run
    """
    context = _setup_two_certified_claims()
    period = context["period"]
    fixtures.read_allocation_preview(period["id"], variant=AllocationVariant.FINAL)
    version_before_run = fixtures.read_funding_period(period["id"])["version"]

    run = fixtures.run_allocation(
        period["id"],
        variant=AllocationVariant.FINAL,
        expected_funding_period_version=version_before_run,
    )
    assert run["committed_cents"] == COMMITTED_TOTAL_CENTS
    assert run["available_cents"] == REMAINING_CENTS

    rows, meta = _list_outcomes(period["id"], AllocationStatus.COMMITTED)
    assert meta["total_count"] == 2
    allocated_by_id = {row["id"]: row["allocated_cents"] for row in rows}
    assert allocated_by_id[context["employment_id"]] == EMPLOYMENT_LINE_CENTS
    assert allocated_by_id[context["postsecondary_id"]] == POSTSECONDARY_LINE_CENTS

    replay = api_client.run_allocation(
        period["id"],
        factories.allocation_run_payload(
            version_before_run, variant=AllocationVariant.FINAL
        ),
        headers=make_state_authority_headers(CERTIFYING_AUTHORITY),
    )
    validate_error(replay, ApiErrorId.STALE_FUNDING_PERIOD_VERSION, expected_status=412)

    assert (
        fixtures.read_funding_period(period["id"])["committed_cents"]
        == COMMITTED_TOTAL_CENTS
    )


def test_06_only_the_post_test_carries_the_enrollment_that_justified_it():
    """"A `POST_TEST` additionally requires the `enrollment_id` whose hours support it; an intake
    `PRE_TEST` leaves `enrollment_id` null" and "List test events, filterable by learner,
    enrollment, purpose and status."

    Design: Corner/endpoints/test_event_cross_reference_link_binds_the_event_to_an_enrollment
    """
    context = _setup_enrollment_with_forty_hours()
    assert fixtures.read_test_event(context["pre_test_id"])["enrollment_id"] is None

    post_test = validate_success(
        api_client.create_test_event(
            factories.create_test_event_payload(
                context["student_id"],
                POST_TEST_AT,
                purpose=TestEventPurpose.POST_TEST,
                test_form=TestForm.CASAS_R_900,
                enrollment_id=context["enrollment_id"],
            ),
            headers=make_registrar_headers(),
        ),
        expected_status=201,
    )
    assert post_test["enrollment_id"] == context["enrollment_id"]
    assert post_test["status"] == TestEventStatus.SCHEDULED

    coordinator = make_program_coordinator_headers()
    linked, linked_meta = validate_paginated(
        api_client.list_test_events(
            headers=coordinator,
            params={"enrollment_id": context["enrollment_id"], "limit": 10, "offset": 0},
        )
    )
    assert linked_meta["total_count"] == 1
    assert linked[0]["id"] == post_test["id"]

    _all_events, all_meta = validate_paginated(
        api_client.list_test_events(
            headers=coordinator,
            params={"student_id": context["student_id"], "limit": 10, "offset": 0},
        )
    )
    assert all_meta["total_count"] == 2

    enrollment = fixtures.read_enrollment(context["enrollment_id"])
    assert_hours_value(enrollment["posted_hours"], 40.00)
    assert enrollment["post_test_eligible"] is True


def test_07_an_uncertified_proctor_cannot_be_assigned_and_the_draft_is_untouched():
    """"A proctor who is `PENDING` or `REVOKED` is refused with the distinct code
    `ERR_PROCTOR_NOT_CERTIFIED` instead." and "`CERTIFY` applies to a `PENDING` proctor and moves
    them to `CERTIFIED`"

    Design: Corner/endpoints/proctor_assignment_is_conditional_on_current_certification
    """
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Conditional Assignment Center", state_code="ME"
    )
    room = fixtures.create_room(center["id"], room_code="COND-1", seat_capacity=10)
    proctor = fixtures.create_proctor(
        center["id"], full_name="Ruth Nakamura", daily_hour_cap=8.00
    )
    assert proctor["certification_status"] == ProctorCertificationStatus.PENDING

    session = fixtures.create_session(
        center["id"],
        room["id"],
        CONDITIONAL_SITTING[0],
        CONDITIONAL_SITTING[1],
        subtest=Subtest.MATH,
        requested_seats=CONDITIONAL_SEATS,
    )
    original_version = session["version"]

    def _assign():
        return api_client.assign_proctor(
            session["id"],
            factories.proctor_assignment_payload(proctor["id"]),
            headers=make_center_administrator_headers(center["id"]),
        )

    validate_error(_assign(), ApiErrorId.PROCTOR_NOT_CERTIFIED, expected_status=409)

    untouched = fixtures.read_session(session["id"])
    assert untouched["status"] == SessionStatus.DRAFT
    assert untouched["proctor_id"] is None
    assert untouched["version"] == original_version

    fixtures.decide_proctor(
        proctor["id"],
        ProctorDecision.CERTIFY,
        certification_expires_at=USABLE_EXPIRY,
    )

    assigned = validate_success(_assign())
    assert assigned["proctor_id"] == proctor["id"]
    assert assigned["status"] == SessionStatus.SCHEDULED
    assert assigned["version"] == original_version + 1
