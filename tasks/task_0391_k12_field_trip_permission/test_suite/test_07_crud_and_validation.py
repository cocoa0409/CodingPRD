"""Field-trip CRUD, input validation, listing, system-field handling, append-only
record immutability, and immediate-consistency visibility.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_teacher_headers,
    make_guardian_headers,
    create_field_trip_payload,
    create_permission_slip_payload,
    create_emergency_contact_payload,
    create_teacher_guardian,
    create_guardian,
    create_student,
    create_approved_trip,
    create_slip,
    create_signed_slip,
    add_emergency_contact,
)


_DISTRICT = TEST_USERS["district_admin_headers"]
_PRINCIPAL = TEST_USERS["principal_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Corner/entities
# ─────────────────────────────────────────────────────────────────────────────
def test_create_field_trip_returns_201_with_defaults(api):
    """PRD §3.2: "A `Teacher` opens the lifecycle by creating a field trip, which begins in `DRAFT`. ... On creation the trip's `signed_count` and `collected_fees_cents` are 0 and its `version` is 1."
    PRD §3.2: "The payload may also set `deposit_cents` — the non-refundable deposit portion of each per-student fee, defaulting to 0 — and `has_water_activity`, a flag defaulting to false..."

    Design: Corner/entities/create_field_trip_returns_201_with_defaults
    """
    teacher_id = create_teacher_guardian()
    payload = create_field_trip_payload(
        teacher_id, title="Create", grade_band="MIDDLE", capacity=10,
        base_fee_cents=0, transport_cost_cents=0,
        depart_at="2026-11-01T09:00:00Z", return_at="2026-11-01T12:00:00Z",
    )
    trip = validate_success(api.create_field_trip(payload, make_teacher_headers(teacher_id)), 201)
    assert trip["status"] == "DRAFT"
    assert trip["version"] == 1
    assert trip["signed_count"] == 0
    assert trip["collected_fees_cents"] == 0
    assert trip["deposit_cents"] == 0
    assert trip["has_water_activity"] is False


def test_create_field_trip_missing_required_field_returns_validation(api):
    """PRD §2.11: "Independently of all of these, any request whose body is missing a required field, carries an ill-typed value, or supplies an invalid enum value is rejected with `ERR_VALIDATION` (HTTP 422)."
    PRD §3.2: "The creation payload carries the `title`, the `organizer_teacher_id` (the Guardian-backed identity of the requesting teacher), the `school_code`, the `grade_band`, the departure and return timestamps `depart_at` and `return_at`, the `capacity` of student participants..."

    Omitting the required capacity field → ERR_VALIDATION (422).

    Design: Corner/entities/create_field_trip_missing_required_field_returns_validation
    """
    teacher_id = create_teacher_guardian()
    payload = create_field_trip_payload(
        teacher_id, title="NoCap", grade_band="MIDDLE",
        base_fee_cents=0, transport_cost_cents=0,
        depart_at="2026-11-01T09:00:00Z", return_at="2026-11-01T12:00:00Z",
    )
    del payload["capacity"]
    validate_error(api.create_field_trip(payload, make_teacher_headers(teacher_id)), "ERR_VALIDATION")


def test_get_field_trip_not_found_returns_404(api):
    """PRD §2.6: "A trip identifier is checked first, yielding `ERR_TRIP_NOT_FOUND` if absent..."

    GET on a non-existent trip UUID → ERR_TRIP_NOT_FOUND (404).

    Design: Corner/entities/get_field_trip_not_found_returns_404
    """
    validate_error(api.get_field_trip(NON_EXISTENT_UUID, TEST_USERS["teacher_headers"]),
                   "ERR_TRIP_NOT_FOUND")


def test_list_field_trips_paginated_envelope(api):
    """PRD §2.3: "List responses carry the pagination bookkeeping in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/list_field_trips_paginated_envelope
    """
    teacher_id = create_teacher_guardian()
    validate_success(
        api.create_field_trip(create_field_trip_payload(
            teacher_id, title="L", grade_band="HIGH", capacity=5,
            base_fee_cents=0, transport_cost_cents=0,
            depart_at="2026-11-02T09:00:00Z", return_at="2026-11-02T12:00:00Z",
        ), make_teacher_headers(teacher_id)), 201
    )
    data, meta = validate_paginated(api.list_field_trips(_PRINCIPAL))
    assert meta["total_count"] >= 1
    assert isinstance(meta["has_more"], bool)


def test_field_trip_system_fields_ignored_on_input(api):
    """PRD §3.2: "A `Teacher` opens the lifecycle by creating a field trip, which begins in `DRAFT`. ... On creation the trip's `signed_count` and `collected_fees_cents` are 0 and its `version` is 1."

    Client-supplied status / signed_count / version are ignored; the server forces
    DRAFT, 0, and 1.

    Design: Corner/entities/field_trip_system_fields_ignored_on_input
    """
    teacher_id = create_teacher_guardian()
    payload = create_field_trip_payload(
        teacher_id, title="Sys", grade_band="MIDDLE", capacity=5,
        base_fee_cents=0, transport_cost_cents=0,
        depart_at="2026-11-03T09:00:00Z", return_at="2026-11-03T12:00:00Z",
    )
    payload["status"] = "APPROVED"
    payload["signed_count"] = 99
    payload["version"] = 50
    trip = validate_success(api.create_field_trip(payload, make_teacher_headers(teacher_id)), 201)
    assert trip["status"] == "DRAFT"
    assert trip["signed_count"] == 0
    assert trip["version"] == 1


def test_emergency_contact_immutable_no_version(api):
    """PRD §2.4: "A second class of records is append-only or immutable and therefore carries only `id` and `created_at` — neither `updated_at` nor `version` is present on these. This class comprises `TripApproval ... EmergencyContact` (an immutable child of a slip)..."

    Design: Corner/entities/emergency_contact_immutable_no_version
    """
    teacher_id, trip = create_approved_trip(grade_band="ELEMENTARY", capacity=5)
    trip_id = trip["id"]
    g = create_guardian(full_name="G5")
    st = create_student(teacher_id, full_name="S5", grade_level=5)
    slip = create_slip(teacher_id, trip_id, st["id"], g["id"])
    ec = validate_success(
        api.create_emergency_contact(trip_id, slip["id"], create_emergency_contact_payload(),
                                     make_teacher_headers(teacher_id)), 201
    )
    assert ec.get("created_at") is not None
    assert "version" not in ec, "EmergencyContact must not carry a version field"
    assert "updated_at" not in ec, "EmergencyContact must not carry an updated_at field"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/consistency_model
# ─────────────────────────────────────────────────────────────────────────────
def test_immediate_visibility_of_signed_count(api):
    """PRD §2.5: "Whenever a child operation changes a quantity that feeds a parent's derived field — a slip being signed changing the trip's `signed_count
    ... the server recomputes the parent's derived fields immediately..."
    PRD §2.5: "signed_count` is the number of this trip's permission slips whose `signature_status` is `SIGNED`."

    Signing a slip makes signed_count == 1 visible in the very next GET.

    Design: Corner/consistency_model/immediate_visibility_of_signed_count
    """
    teacher_id, trip = create_approved_trip(grade_band="ELEMENTARY", capacity=5)
    trip_id = trip["id"]
    g = create_guardian(full_name="G32")
    st = create_student(teacher_id, full_name="S32", grade_level=5)
    create_signed_slip(teacher_id, trip_id, st["id"], g["id"])
    trip = get_success_data(api.get_field_trip(trip_id, make_teacher_headers(teacher_id)))
    assert trip["signed_count"] == 1, f"signed_count should be 1 immediately, got {trip['signed_count']}"
