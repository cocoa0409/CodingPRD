"""Entity CRUD, defaults, computed-field reads, immutability, FK integrity
(corner-design section: entities). PRD §2.2, §2.4, §3.1, §3.6, §3.12.

Each test translates exactly one corner-design instance.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    create_classroom_payload, create_tier_payload, create_application_payload,
    create_observation_payload,
    set_clock, create_tier, create_room_with_staff, create_student, enroll_child,
    NON_EXISTENT_UUID, TEST_USERS, api_client,
)

REGISTRAR = TEST_USERS["registrar_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_create_classroom_returns_computed_defaults(api):
    """PRD §3.1: "A new classroom begins life with its derived fields initialized:
    placed_count is 0, assigned_staff_count is 0, and compliance_status is COMPLIANT."
    PRD §2.4: "The version field is an integer that begins at its initial value on
    creation".

    Design: Corner/entities/create_classroom_returns_201_with_computed_defaults
    """
    res = api.create_classroom(
        create_classroom_payload(name="Primary Z", level="PRIMARY", capacity=5,
                                 min_age_months=36, max_age_months=72), COMPLIANCE)
    room = validate_success(res, 201)
    assert room["placed_count"] == 0
    assert room["assigned_staff_count"] == 0
    assert room["compliance_status"] == "COMPLIANT"
    assert room["version"] == 1


def test_get_classroom_returns_stored_entity(api):
    """PRD §2.2: "The data field contains the resource object ... operations that create or
    modify a resource will return the created or updated resource object in the data field."

    Design: Corner/entities/get_classroom_returns_stored_entity
    """
    room = get_success_data(api.create_classroom(
        create_classroom_payload(name="Primary Z", level="PRIMARY", capacity=5), COMPLIANCE))
    res = api.get_classroom(room["id"], REGISTRAR)
    got = validate_success(res, 200)
    assert got["id"] == room["id"]
    assert got["name"] == "Primary Z"


def test_list_classrooms_paginated_envelope(api):
    """PRD §2.3: "Every list response includes four pagination fields in the meta object:
    limit, offset, total_count, and has_more."

    Design: Corner/entities/list_classrooms_paginated_envelope
    """
    get_success_data(api.create_classroom(
        create_classroom_payload(name="Room 1", level="PRIMARY", capacity=5), COMPLIANCE))
    get_success_data(api.create_classroom(
        create_classroom_payload(name="Room 2", level="TODDLER", capacity=6,
                                 min_age_months=18, max_age_months=36), COMPLIANCE))
    res = api.list_classrooms(REGISTRAR, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2, f"got {meta['total_count']}"
    assert len(data) == 1, f"got {len(data)}"
    assert meta["has_more"] is True


def test_get_classroom_not_found(api):
    """PRD §2.9: "The first identifier that does not resolve to an existing resource causes
    the request to be rejected with ERR_NOT_FOUND before any later identifier or business
    rule is evaluated."

    Design: Corner/entities/get_classroom_not_found_returns_404
    """
    res = api.get_classroom(NON_EXISTENT_UUID, REGISTRAR)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_tier_missing_required_field(api):
    """PRD §3.1: "A tuition tier is created with a code ... a base_annual_cents figure".
    PRD §2.10: "Generic request-shape problems — ... a missing required field ... — are
    reported as ERR_INVALID_REQUEST."

    Design: Corner/entities/create_tier_missing_required_field_returns_invalid_request
    """
    res = api.create_tier({"code": "BADTIER", "level": "PRIMARY", "deposit_pct": 0.10},
                          REGISTRAR)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_tier_installments_default_applied(api):
    """PRD §3.1: "The number of monthly installments the annual tuition is split across is
    given by installments, an integer between 1 and 12 inclusive that defaults to 10 when
    omitted. An optional extended_day_annual_cents flat surcharge ... defaults to 0 ...
    Finally, active is a boolean defaulting to true".

    Design: Corner/entities/tier_installments_default_applied
    """
    res = api.create_tier({"code": "DEFTIER", "level": "PRIMARY",
                           "base_annual_cents": 1_000_000, "deposit_pct": 0.10}, REGISTRAR)
    tier = validate_success(res, 201)
    assert tier["installments"] == 10
    assert tier["extended_day_annual_cents"] == 0
    assert tier["active"] is True


def test_deposit_computed_off_base_not_net(api):
    """PRD §3.6: "The enrollment's deposit_cents is the tier's base_annual_cents multiplied
    by the tier's deposit_pct, rounded half up to whole cents. The deposit is taken off
    base_annual_cents, never off net_annual_cents".

    Design: Corner/entities/deposit_computed_off_base_not_net
    """
    room, tier, student, enr = _enroll_standard(api)
    assert enr["deposit_cents"] == 100000
    assert enr["net_annual_cents"] == 1000000
    assert enr["monthly_installment_cents"] == 100000


def test_tier_invalid_level_enum_rejected(api):
    """PRD §2.10: "Generic request-shape problems — a malformed body, an unrecognized enum
    value ... — are reported as ERR_INVALID_REQUEST."

    Design: Corner/entities/tier_invalid_level_enum_rejected
    """
    res = api.create_tier({"code": "X", "level": "MIDDLE_SCHOOL",
                           "base_annual_cents": 1_000_000, "deposit_pct": 0.10}, REGISTRAR)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_observation_immutable_no_version_field(api):
    """PRD §2.4: "an Observation is immutable after it is created. An Observation therefore
    carries only id and created_at; it has neither an updated_at field nor a version field."

    Design: Corner/entities/observation_immutable_no_version_field
    """
    room = get_success_data(api.create_classroom(
        create_classroom_payload(name="Room", level="PRIMARY", capacity=5), COMPLIANCE))
    res = api.create_observation(
        create_observation_payload(room["id"], "V",
                                   "2026-10-01T15:00:00Z", "2026-10-01T15:30:00Z"),
        COMPLIANCE)
    obs = validate_success(res, 201)
    assert "id" in obs and obs["id"]
    assert "created_at" in obs and obs["created_at"]
    assert "version" not in obs, "Observation must not carry a version field"


def test_application_nonexistent_student_fk_not_found(api):
    """PRD §2.9: "For any request whose path or body references other resources, existence is
    validated left-to-right: path identifiers are checked first ... and then body foreign
    keys. The first identifier that does not resolve to an existing resource causes the
    request to be rejected with ERR_NOT_FOUND".

    Design: Corner/entities/application_with_nonexistent_student_fk_returns_404
    """
    room = get_success_data(api.create_classroom(
        create_classroom_payload(name="Room", level="PRIMARY", capacity=5), COMPLIANCE))
    tier = create_tier(code="STD", level="PRIMARY", base_annual_cents=1_000_000,
                       deposit_pct=0.10)
    res = api.create_application(
        create_application_payload(NON_EXISTENT_UUID, room["id"], tier["id"]), REGISTRAR)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_enrollment_filter_by_student_id(api):
    """PRD §3.4: "Enrollments may be listed and filtered by student_id, application_id,
    classroom_id, tier_id, placement_status, or billing_status."

    Design: Corner/entities/flat_fk_enrollment_filter_by_student_id
    """
    room, tier, student, enr = _enroll_standard(api)
    res = api.list_enrollments(REGISTRAR, params={"student_id": student["id"]})
    data, meta = validate_paginated(res)
    assert len(data) == 1, f"got {len(data)}"
    assert data[0]["id"] == enr["id"]
    assert data[0]["student_id"] == student["id"]


def _enroll_standard(api):
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="STD", level="PRIMARY", base_annual_cents=1_000_000,
                       deposit_pct=0.10, installments=10)
    room, _ = create_room_with_staff(level="PRIMARY", capacity=5, staff=1)
    student = create_student(parent_user_id="parent-1")
    enr = enroll_child(student["id"], room["id"], tier["id"], parent_user_id="parent-1")
    return room, tier, student, enr
