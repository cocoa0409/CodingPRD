"""Onboarding and entity-shape claims: creation defaults, required fields, type
constraints, not-found, listing envelope, immutability, FK integrity, computed
fields.

Each test cites a verbatim PRD sentence and ends with a Design: tag mapping it to
the corner-design instance it translates.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, RANDOM_UUID,
    create_student_payload, create_aircraft_payload, create_syllabus_payload,
    assert_student, assert_aircraft, assert_syllabus,
    create_syllabus, create_student,
)


def test_create_student_returns_201_with_zeroed_defaults(api, school_admin_headers):
    """PRD §3.1: "the new record starts with `status` of `ACTIVE`, a
    `no_show_strikes` count of zero, and all three deposit totals —
    `deposit_balance_cents`, `deposit_held_cents`, and `deposit_consumed_cents` —
    set to zero."
    PRD §2.4: "a `version`, an integer that begins at 1 and increments by one with
    each mutation."

    Design: Corner/entities/create_student_returns_201_with_defaults
    """
    data = validate_success(api.create_student(create_student_payload(), school_admin_headers), 201)
    assert_student(data)
    assert data["deposit_balance_cents"] == 0
    assert data["deposit_held_cents"] == 0
    assert data["deposit_consumed_cents"] == 0
    assert data["no_show_strikes"] == 0
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1


def test_create_aircraft_missing_billing_basis_rejected(api, school_admin_headers):
    """PRD §2.11: "a malformed body — a missing required field, an invalid enum
    value, or an out-of-range number ... — yields `ERR_INVALID_REQUEST` (400)."
    PRD §3.1: "Onboarding an aircraft records its unique `tail_number`, its
    `model`, the wet rental rate `rental_rate_cents_per_hour`, the `billing_basis`
    of either `HOBBS` or `TACH` that selects which meter bills flight time..."

    Design: Corner/entities/create_aircraft_missing_billing_basis_returns_invalid_request
    """
    payload = create_aircraft_payload()
    del payload["billing_basis"]
    validate_error(api.create_aircraft(payload, school_admin_headers), ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_aircraft_invalid_billing_basis_enum_rejected(api, school_admin_headers):
    """PRD §2.11: "a malformed body — a missing required field, an invalid enum
    value, or an out-of-range number ... — yields `ERR_INVALID_REQUEST` (400)."
    PRD §3.1: "the `billing_basis` of either `HOBBS` or `TACH` that selects which
    meter bills flight time..."

    Design: Corner/entities/create_aircraft_invalid_billing_basis_enum
    """
    payload = create_aircraft_payload(billing_basis="WALLCLOCK")
    validate_error(api.create_aircraft(payload, school_admin_headers), ApiErrorId.ERR_INVALID_REQUEST.value)


def test_aircraft_is_complex_defaults_false(api, school_admin_headers):
    """PRD §3.1: "an optional `is_complex` flag that defaults to false and drives
    the complexity surcharge tier on bookings. At creation the aircraft is
    `AVAILABLE`, its `open_squawk_count` is zero, its `version` is 1, and its live
    meters `current_hobbs` and `current_tach` are initialized from `initial_hobbs`
    and `initial_tach` respectively."

    Design: Corner/entities/aircraft_default_is_complex_false
    """
    payload = create_aircraft_payload(initial_hobbs=0.0, initial_tach=0.0)
    payload.pop("is_complex", None)
    data = validate_success(api.create_aircraft(payload, school_admin_headers), 201)
    assert_aircraft(data)
    assert data["is_complex"] is False
    assert data["status"] == "AVAILABLE"
    assert data["current_hobbs"] == 0.0


def test_get_student_nonexistent_returns_not_found(api, school_admin_headers):
    """PRD §2.5: "when a request names a resource by an identifier in its path,
    that resource's existence is verified before any body or business validation
    runs, and a missing target yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_student_nonexistent_returns_not_found
    """
    validate_error(api.get_student(RANDOM_UUID, school_admin_headers), ApiErrorId.ERR_NOT_FOUND.value)


def test_list_students_returns_paginated_envelope(api, school_admin_headers):
    """PRD §2.3: "List and array responses carry the pagination bookkeeping in the
    `meta` object of the envelope, namely `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/entities/list_students_pagination_envelope
    """
    create_student()
    data, meta = validate_paginated(api.list_students(school_admin_headers))
    assert isinstance(data, list)
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, f"pagination meta missing {key}"
    assert meta["total_count"] >= 1


def test_syllabus_is_immutable_no_version_field(api, school_admin_headers):
    """PRD §2.4: "A `Syllabus` is a configuration record that is immutable after
    creation, and a `DepositTransaction` is an append-only ledger event. Both carry
    only `id` and `created_at`; neither has an `updated_at` nor a `version`, and
    that absence is intentional — they are never modified in place."

    Design: Corner/entities/syllabus_immutable_no_version_field
    """
    data = validate_success(
        api.create_syllabus(
            create_syllabus_payload(name="INSTRUMENT", required_solo_hours=0, stage_count=2),
            school_admin_headers,
        ),
        201,
    )
    assert_syllabus(data)
    assert "version" not in data
    assert "updated_at" not in data


def test_enrollment_with_unknown_student_returns_not_found(api, school_admin_headers):
    """PRD §2.5: "every referenced resource (the aircraft, instructor, enrollment,
    booking, syllabus, or student a payload points to) is validated left-to-right,
    and the first one that does not exist produces `ERR_NOT_FOUND` before deeper
    rules are considered."

    Design: Corner/entities/flat_topology_fk_enrollment_bad_student_not_found
    """
    syllabus = create_syllabus()
    validate_error(
        api.create_enrollment(
            {"student_id": RANDOM_UUID, "syllabus_id": syllabus["id"]},
            school_admin_headers,
        ),
        ApiErrorId.ERR_NOT_FOUND.value,
    )
