"""Census, clinical-record and junction-graph corner cases.

Every test in this module drives the live API over real HTTP against an empty
database whose logical clock reads 2026-08-01T00:00:00Z.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_no_version_fields,
    assert_values,
    ids_of,
)
from test_helpers.constants import ABSENT_UUID, ABSENT_UUID_2, ABSENT_UUID_3
from test_helpers.test_users import make_council_rep_headers


def test_resident_creation_applies_status_default(api, director):
    """A resident admitted without a census status lands ADMITTED, with every
    clinical mirror still unknown and both gate fields at rest.

    PRD §3.1: "A freshly admitted resident starts with `enrollment_gate` set to
    `NONE`, `care_plan_review_due` set to false, `engagement_index` at 0.0,
    `refusal_streak` at 0, and `absence_count` at 0."

    Design: Corner/entities/resident_creation_applies_status_default
    """
    created = validate_success(
        api.create_resident(
            f.resident_payload(
                full_name="Default Diane",
                room_number="101A",
                admission_date="2026-07-01",
            ),
            director,
        ),
        201,
    )

    resident = validate_success(api.get_resident(created["id"], director), 200)
    assert_values(
        resident,
        status="ADMITTED",
        version=1,
        enrollment_gate="NONE",
        care_plan_review_due=False,
        refusal_streak=0,
        absence_count=0,
        cognitive_level=None,
        functional_mobility=None,
        supervision_tier=None,
    )
    assert resident["engagement_index"] == 0.0, (
        f"engagement_index must start at 0.0, got {resident['engagement_index']!r}"
    )
    assert resident["interest_domains"] == [], (
        f"interest_domains must start empty, got {resident['interest_domains']!r}"
    )


def test_resident_not_found_on_unknown_id(api, director):
    """Reading a well-formed but unused resident identifier is a lookup failure,
    not an empty success.

    PRD §2.9: "a resident identifier yields `ERR_RESIDENT_NOT_FOUND`".

    Design: Corner/entities/resident_not_found_on_unknown_id
    """
    real = fx.create_resident(
        api, full_name="Only Resident", room_number="103A", admission_date="2026-07-03"
    )

    validate_error(
        api.get_resident(ABSENT_UUID, director),
        ApiErrorId.RESIDENT_NOT_FOUND.value,
        404,
    )

    untouched = validate_success(api.get_resident(real["id"], director), 200)
    assert_values(untouched, full_name="Only Resident", status="ADMITTED", version=1)


def test_resident_missing_required_admission_date_rejected(api, director):
    """Admitting a resident without an admission date is refused outright and no
    census row is written.

    PRD §2.8: "every non-optional field must be present and non-null"

    Design: Corner/entities/resident_missing_required_admission_date_rejected
    """
    control = fx.create_resident(
        api,
        full_name="Control Resident",
        room_number="104B",
        admission_date="2026-07-04",
    )

    validate_error(
        api.create_resident(
            f.resident_payload(
                full_name="No Admission Date", room_number="105A", admission_date=None
            ),
            director,
        ),
        ApiErrorId.INVALID_REQUEST.value,
        400,
    )

    rows, meta = validate_paginated(api.list_residents(director))
    assert meta["total_count"] == 1, (
        f"Only the control resident may exist, got total_count {meta['total_count']}"
    )
    assert ids_of(rows) == [control["id"]], (
        f"Expected only {control['id']} on the census, got {ids_of(rows)}"
    )


def test_resident_invalid_status_enum_returns_4XX(api, director):
    """A census status outside the declared value set is rejected rather than
    silently coerced to the ADMITTED default.

    PRD §3.1: "the three permitted values are `ADMITTED`, `ON_LEAVE`, and
    `DISCHARGED`."

    Design: Corner/entities/resident_invalid_status_enum_returns_4XX
    """
    control = fx.create_resident(
        api, full_name="Enum Control", room_number="106A", admission_date="2026-07-05"
    )

    validate_error(
        api.create_resident(
            f.resident_payload(
                full_name="Bad Enum",
                room_number="106B",
                admission_date="2026-07-05",
                status="TRANSFERRED",
            ),
            director,
        ),
        ApiErrorId.INVALID_REQUEST.value,
        400,
    )

    rows, meta = validate_paginated(api.list_residents(director))
    assert meta["total_count"] == 1, (
        f"The rejected admission must not persist, got total_count {meta['total_count']}"
    )
    assert [row["full_name"] for row in rows] == ["Enum Control"], (
        f"Expected only the control resident, got {[r['full_name'] for r in rows]}"
    )
    assert control["id"] == rows[0]["id"]


def test_assessment_is_immutable_and_carries_no_version(api, director, therapist):
    """A filed assessment is an append-only clinical record: it exposes an
    identifier and a creation stamp but neither a version nor an update stamp,
    and it is the governing record for its resident.

    PRD §2.4: "an assessment carries only `id` and `created_at`".

    Design: Corner/entities/assessment_is_immutable_and_carries_no_version
    """
    resident = fx.create_resident(
        api, full_name="Immutable Ivy", room_number="107A", admission_date="2026-07-06"
    )
    filed = validate_success(
        api.create_assessment(
            resident["id"],
            f.assessment_payload(
                cognitive_level="MILD_IMPAIRMENT",
                functional_mobility="ASSIST_1",
                interest_domains=["SOCIAL"],
                preferred_group_size="SMALL",
                effective_date="2026-07-06",
            ),
            therapist,
        ),
        201,
    )

    assessment = validate_success(api.get_assessment(filed["id"], therapist), 200)
    assert_no_version_fields(assessment)
    assert_values(assessment, superseded=False, resident_id=resident["id"])
    assert "created_at" in assessment, "An assessment must still expose created_at"


def test_assessment_under_unknown_resident_not_found(api, director, therapist):
    """Filing an assessment beneath an unused resident identifier resolves the
    path segment first and writes no clinical record.

    PRD §2.9: "Identifiers embedded in a URL path are resolved strictly left to
    right, and the first segment that fails to resolve determines the error."

    Design: Corner/entities/assessment_under_unknown_resident_not_found
    """
    fx.create_resident(
        api, full_name="Real Parent", room_number="108A", admission_date="2026-07-07"
    )

    validate_error(
        api.create_assessment(
            ABSENT_UUID_2,
            f.assessment_payload(
                cognitive_level="INTACT",
                functional_mobility="INDEPENDENT",
                interest_domains=["SOCIAL"],
                preferred_group_size="SMALL",
                effective_date="2026-07-07",
            ),
            therapist,
        ),
        ApiErrorId.RESIDENT_NOT_FOUND.value,
        404,
    )

    rows, meta = validate_paginated(api.list_assessments(therapist))
    assert meta["total_count"] == 0, (
        f"No assessment may have been filed, got total_count {meta['total_count']}"
    )
    assert rows == [], f"Expected an empty assessment table, got {ids_of(rows)}"


def test_residents_listing_pagination_envelope(api, director):
    """The facility-wide census list honours limit and offset and reports the
    filtered size and the has-more flag page by page.

    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope".

    Design: Corner/entities/residents_listing_pagination_envelope
    """
    first = fx.create_resident(
        api, full_name="Page One", room_number="301C", admission_date="2026-07-08"
    )
    second = fx.create_resident(
        api, full_name="Page Two", room_number="301D", admission_date="2026-07-08"
    )
    third = fx.create_resident(
        api, full_name="Page Three", room_number="301E", admission_date="2026-07-08"
    )

    page_one_rows, page_one_meta = validate_paginated(
        api.list_residents(director, {"limit": 2, "offset": 0})
    )
    assert len(page_one_rows) == 2, f"Expected 2 rows, got {len(page_one_rows)}"
    assert_values(page_one_meta, limit=2, offset=0, total_count=3, has_more=True)

    page_two_rows, page_two_meta = validate_paginated(
        api.list_residents(director, {"limit": 2, "offset": 2})
    )
    assert len(page_two_rows) == 1, f"Expected 1 row, got {len(page_two_rows)}"
    assert_values(page_two_meta, limit=2, offset=2, total_count=3, has_more=False)

    seen = ids_of(page_one_rows) + ids_of(page_two_rows)
    assert len(seen) == len(set(seen)), f"The two pages overlap: {seen}"
    assert set(seen) == {first["id"], second["id"], third["id"]}, (
        f"The two pages must cover the whole census, got {seen}"
    )


def test_participation_record_retrieval_matches_stored_row(api, director, therapist, aide):
    """A freshly created enrollment read back by identifier reports the same
    resident, session and undocumented planned state the enrollment produced.

    PRD §3.5: "Success creates a `ParticipationRecord` — the junction between one
    resident and one session — in `PLANNED` status, with `engagement_level`,
    `refusal_reason`, `documented_by_user_id`, and `documented_at` all null."

    Design: Corner/entities/participation_record_retrieval_matches_stored_row
    """
    resident, _assessment = fx.assessed_resident(
        api,
        resident_kwargs={
            "full_name": "Readback Rita",
            "room_number": "109A",
            "admission_date": "2026-07-09",
        },
        cognitive_level="INTACT",
        functional_mobility="INDEPENDENT",
        interest_domains=["SOCIAL"],
        preferred_group_size="SMALL",
        effective_date="2026-07-09",
    )
    program, room = fx.calendar(
        api,
        program_kwargs={
            "name": "Readback Social",
            "domain": "SOCIAL",
            "staffing_ratio_denominator": 4,
            "max_group_size": 10,
            "max_supervision_tier": "TIER_3",
        },
        room_kwargs={"name": "Readback Room", "capacity": 10, "buffer_minutes": 0},
    )
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-21T10:00:00Z",
        ends_at="2026-08-21T11:00:00Z",
        assigned_staff_count=2,
    )
    created = validate_success(
        api.create_enrollment(
            session["id"], f.enrollment_payload(resident["id"]), aide
        ),
        201,
    )

    record = validate_success(api.get_participation(created["id"], aide), 200)
    assert_values(
        record,
        resident_id=resident["id"],
        session_id=session["id"],
        status="PLANNED",
        outcome="PLANNED",
        engagement_level=None,
        refusal_reason=None,
        documented_by_user_id=None,
        documented_at=None,
        version=1,
    )


def test_participation_junction_supports_many_to_many_graph(api, director, aide):
    """The participation row is a true resident-by-session junction: two
    residents share one slot while one resident holds rows on two slots, and the
    filtered list reads the same rows from either side.

    PRD §2.3: "It accepts optional `resident_id`, `session_id`, and `outcome`
    filters."

    Design: Corner/entities/participation_junction_supports_many_to_many_graph
    """
    resident_a, _asmt_a = fx.assessed_resident(
        api,
        resident_kwargs={
            "full_name": "Graph A",
            "room_number": "310A",
            "admission_date": "2026-07-10",
        },
        interest_domains=["SOCIAL"],
        preferred_group_size="LARGE",
        effective_date="2026-07-10",
    )
    resident_b, _asmt_b = fx.assessed_resident(
        api,
        resident_kwargs={
            "full_name": "Graph B",
            "room_number": "310B",
            "admission_date": "2026-07-10",
        },
        interest_domains=["SOCIAL"],
        preferred_group_size="LARGE",
        effective_date="2026-07-10",
    )
    program, room = fx.calendar(
        api,
        program_kwargs={
            "name": "Graph Social",
            "domain": "SOCIAL",
            "max_group_size": 10,
            "max_supervision_tier": "TIER_3",
        },
        room_kwargs={"name": "Graph Room", "capacity": 10, "buffer_minutes": 0},
    )
    session_one = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-22T10:00:00Z",
        ends_at="2026-08-22T11:00:00Z",
    )
    session_two = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-22T12:00:00Z",
        ends_at="2026-08-22T13:00:00Z",
    )
    fx.enroll(api, session_one["id"], resident_a["id"])
    fx.enroll(api, session_one["id"], resident_b["id"])
    fx.enroll(api, session_two["id"], resident_a["id"])

    by_resident, resident_meta = validate_paginated(
        api.list_participation(aide, {"resident_id": resident_a["id"]})
    )
    assert resident_meta["total_count"] == 2, (
        f"Resident A holds two rows, got total_count {resident_meta['total_count']}"
    )
    assert {row["session_id"] for row in by_resident} == {
        session_one["id"],
        session_two["id"],
    }, f"Expected one row per session, got {[r['session_id'] for r in by_resident]}"

    by_session, session_meta = validate_paginated(
        api.list_participation(aide, {"session_id": session_one["id"]})
    )
    assert session_meta["total_count"] == 2, (
        f"Session one holds two rows, got total_count {session_meta['total_count']}"
    )
    assert {row["resident_id"] for row in by_session} == {
        resident_a["id"],
        resident_b["id"],
    }, f"Expected one row per resident, got {[r['resident_id'] for r in by_session]}"

    assert fx.read_session(api, session_one["id"])["enrolled_count"] == 2
    assert fx.read_session(api, session_two["id"])["enrolled_count"] == 1


def test_council_request_unknown_program_reference_not_found(api, director):
    """A council request naming a catalogue program that does not exist is a
    body-foreign-key lookup failure and files no request row.

    PRD §2.9: "`program_id` and `requested_program_id` both yield
    `ERR_PROGRAM_NOT_FOUND`".

    Design: Corner/entities/council_request_unknown_program_reference_not_found
    """
    resident = fx.create_resident(
        api, full_name="Council Cal", room_number="111A", admission_date="2026-07-11"
    )
    program = fx.create_program(
        api,
        name="Real Program",
        domain="CREATIVE",
        staffing_ratio_denominator=4,
        max_group_size=10,
        max_supervision_tier="TIER_3",
    )

    validate_error(
        api.create_council_request(
            f.council_request_payload(
                resident["id"],
                requested_domain="CREATIVE",
                requested_program_id=ABSENT_UUID_3,
                vote_count=6,
                note="More pottery please",
            ),
            make_council_rep_headers(resident["id"]),
        ),
        ApiErrorId.PROGRAM_NOT_FOUND.value,
        404,
    )

    rows, meta = validate_paginated(api.list_council_requests(director))
    assert meta["total_count"] == 0, (
        f"No council request may exist, got total_count {meta['total_count']}"
    )
    assert rows == [], f"Expected no council request rows, got {ids_of(rows)}"
    assert fx.read_program(api, program["id"])["council_preference_weight"] == 0
