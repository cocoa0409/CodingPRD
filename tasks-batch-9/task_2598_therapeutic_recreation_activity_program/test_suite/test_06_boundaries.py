"""Exact edges: the staffing comparator at equality and the engagement window when empty."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_rounded, assert_values


def _single_staff_session_with_three_enrolled(api):
    """A one-staff, denominator-four session already carrying three TIER_1 residents.

    Returns the session and the two residents still to be enrolled: the fourth lands the
    load on exactly one required staff member, the fifth pushes it to two.
    """
    program = fx.create_program(
        api,
        name="Sing Along",
        domain="CREATIVE",
        staffing_ratio_denominator=4,
        max_group_size=10,
        max_supervision_tier="TIER_3",
    )
    room = fx.create_room(api, name="Chapel Annex", capacity=10, buffer_minutes=0)
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-09T10:00:00Z",
        ends_at="2026-08-09T11:00:00Z",
        assigned_staff_count=1,
    )
    residents = []
    for index in range(5):
        resident, _ = fx.assessed_resident(
            api,
            resident_kwargs={
                "full_name": f"Boundary {index + 1}",
                "room_number": f"4{index:02d}A",
                "admission_date": "2026-06-01",
            },
            cognitive_level="MILD_IMPAIRMENT",
            functional_mobility="INDEPENDENT",
            interest_domains=["CREATIVE"],
            preferred_group_size="LARGE",
            effective_date="2026-07-20",
        )
        residents.append(resident)
    for resident in residents[:3]:
        fx.enroll(api, session["id"], resident["id"])
    return session, residents[3], residents[4]


def test_staffing_ratio_boundary_exact_equality_admitted(api, aide):
    """The fourth TIER_1 enrollment brings the load to exactly 4.0, which divides into
    exactly one required staff member against one rostered, so it is admitted.

    PRD: "The enrollment is admitted only while `required_staff_count` is less than or
    equal to the session's `assigned_staff_count`; a load that divides exactly into the
    rostered staff is still admissible"

    Design: Difficulty/boundary_precision_check/staffing_ratio_boundary_exact_equality_admitted
    """
    session, fourth, _ = _single_staff_session_with_three_enrolled(api)

    response = api.create_enrollment(
        session["id"], f.enrollment_payload(fourth["id"]), aide
    )
    created = validate_success(response, 201)
    assert_values(created, status="PLANNED")

    stored = fx.read_session(api, session["id"])
    assert_rounded(stored["weighted_supervision_load"], 4.0, 2)
    assert_values(stored, required_staff_count=1, enrolled_count=4,
                  assigned_staff_count=1)


def test_staffing_ratio_boundary_exact_equality_admitted_next_body_rejected(api, aide):
    """One body past the edge needs two staff against one rostered, so the fifth
    enrollment is refused and the session's figures stay where the fourth left them.

    PRD: "one body over the line reports `ERR_STAFFING_RATIO_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/staffing_ratio_boundary_exact_equality_admitted
    """
    session, fourth, fifth = _single_staff_session_with_three_enrolled(api)
    fx.enroll(api, session["id"], fourth["id"])

    response = api.create_enrollment(
        session["id"], f.enrollment_payload(fifth["id"]), aide
    )
    validate_error(response, ApiErrorId.STAFFING_RATIO_EXCEEDED, 409)

    stored = fx.read_session(api, session["id"])
    assert_values(stored, enrolled_count=4, required_staff_count=1)
    assert_rounded(stored["weighted_supervision_load"], 4.0, 2)


def _first_ever_record_on_started_session(api):
    """A resident with no participation history at all, enrolled on a started session."""
    resident, _ = fx.assessed_resident(
        api,
        resident_kwargs={"full_name": "Edith Kowal", "room_number": "133A",
                         "admission_date": "2026-05-01"},
        cognitive_level="MODERATE_IMPAIRMENT",
        functional_mobility="ASSIST_1",
        interest_domains=["SPIRITUAL"],
        effective_date="2026-07-20",
    )
    program = fx.create_program(api, name="Morning Devotional", domain="SPIRITUAL")
    room = fx.create_room(api, name="Chapel", capacity=20, buffer_minutes=0)
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-03T09:00:00Z",
        ends_at="2026-08-03T10:00:00Z",
    )
    record = fx.enroll(api, session["id"], resident["id"])
    fx.advance_clock(api, "2026-08-03T09:00:00Z")
    fx.start_session(api, session["id"])
    return resident, record


def test_engagement_index_empty_window_is_zero(api, aide):
    """An absence needs no engagement level and records none, which leaves the resident's
    only documented row outside the engagement window entirely.

    PRD: "`PLANNED → ABSENT` requires that **neither** `engagement_level` nor
    `refusal_reason` is supplied."

    Design: Difficulty/boundary_precision_check/engagement_index_empty_window_is_zero
    """
    _, record = _first_ever_record_on_started_session(api)

    response = api.document_participation(record["id"], f.absence_payload(), aide)
    documented = validate_success(response, 200)
    assert_values(documented, outcome="ABSENT")
    assert documented.get("engagement_level") is None, (
        f"An absence stores no engagement level, got {documented.get('engagement_level')!r}"
    )


def test_engagement_index_empty_window_is_zero_resident_figures(api, aide):
    """With the window empty the index reads exactly 0.0 rather than null, the absence is
    counted, and the refusal run is untouched because an absence is not a refusal.

    PRD: "If the window is empty the index is 0.0."

    Design: Difficulty/boundary_precision_check/engagement_index_empty_window_is_zero
    """
    resident, record = _first_ever_record_on_started_session(api)

    before = fx.read_resident(api, resident["id"])
    assert_values(before, absence_count=0)
    assert_rounded(before["engagement_index"], 0.0, 3)

    validate_success(
        api.document_participation(record["id"], f.absence_payload(), aide), 200
    )

    stored = fx.read_resident(api, resident["id"])
    assert_rounded(stored["engagement_index"], 0.0, 3)
    assert_values(stored, absence_count=1, refusal_streak=0)
