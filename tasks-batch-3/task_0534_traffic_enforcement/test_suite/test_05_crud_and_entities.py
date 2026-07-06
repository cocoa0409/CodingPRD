"""CRUD, entity creation, defaults, computed/system fields (breadth).

Translates the corner `entities` section instances.
"""
import pytest
from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID,
    create_program_payload, create_camera_payload, create_owner_payload,
    create_program, create_camera, add_calibration, create_owner,
    capture_citation, review_to_cited,
    TEST_USERS,
)

SYS = TEST_USERS["system_admin_headers"]
PA = TEST_USERS["program_admin_headers"]
AUD = TEST_USERS["auditor_headers"]


def test_create_program_returns_201_with_fields(api):
    """PRD §3.1: "A program is created with a `jurisdiction_name` and the money knobs
    that drive every downstream calculation".
    PRD §2.4: "`version` — an integer that starts at its initial value on creation
    and increments by one on every mutation."

    Design: Corner/entities/create_program_returns_201_with_fields
    """
    res = api.create_program(create_program_payload(jurisdiction_name="Metro"), SYS)
    program = validate_success(res, 201)
    assert program["jurisdiction_name"] == "Metro"
    assert program["version"] == 1


def test_get_program_not_found(api):
    """PRD §2.7: "the system validates them in left-to-right order and rejects the
    request at the first identifier that does not resolve to an existing resource,
    with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_program_not_found
    """
    res = api.get_program(NON_EXISTENT_UUID, SYS)
    validate_error(res, "ERR_NOT_FOUND")


def test_list_cameras_paginated_envelope(api):
    """PRD §2.3: "Every list response reports pagination state inside the envelope's
    `meta` object using the fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_cameras_paginated_envelope
    """
    program = create_program()
    create_camera(program["id"], camera_type="RED_LIGHT")
    data, meta = validate_paginated(
        api.list_cameras(PA, params={"program_id": program["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_create_camera_missing_required_field(api):
    """PRD §2.10: "a body that is missing a required field or carries a value of the
    wrong type or an unknown enum member is rejected with `ERR_INVALID_REQUEST` (HTTP
    422); this required-field/type check is the lowest-priority business validation
    and applies to all create and action endpoints."

    Design: Corner/entities/create_camera_missing_required_field
    """
    program = create_program()
    res = api.create_camera(
        {"program_id": program["id"], "intersection_code": "INT-1"}, PA)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_response_window_days_default_applied(api):
    """PRD §3.1: "`response_window_days` defaults to 30 and is the number of days from
    notice issuance until a citation is due; `repeat_offender_window_days` defaults to
    365 and is the lookback that defines a repeat offense for the same owner; and
    `repeat_offender_surcharge_pct` defaults to 0.5, expressing the fractional
    surcharge on the base fine for a repeat offense — a value of 0.5 meaning a
    fifty-percent add-on."

    Design: Corner/entities/response_window_days_default_applied
    """
    res = api.create_program(
        {"jurisdiction_name": "Metro", "base_red_light_fine_cents": 10000,
         "base_speed_fine_cents": 8000, "admin_fee_cents": 2500,
         "late_fee_cents": 4000}, SYS)
    program = validate_success(res, 201)
    assert program["response_window_days"] == 30
    assert program["repeat_offender_surcharge_pct"] == 0.5


def test_owner_portal_pin_is_system_minted(api):
    """PRD §3.2: "At registration the server mints a `portal_access_pin` for the owner
    — this is the credential the owner later presents, paired with their
    `registered_owner_id`, to authenticate in the evidence portal."

    Design: Corner/entities/owner_portal_pin_is_system_minted
    """
    program = create_program()
    res = api.create_owner(create_owner_payload(program["id"], plate_number="ABC123"), PA)
    owner = validate_success(res, 201)
    assert owner.get("portal_access_pin")


def test_camera_type_invalid_enum_rejected(api):
    """PRD §3.1: "has a `camera_type` that is exactly one of `RED_LIGHT` or `SPEED`".
    PRD §2.10: "a body that is missing a required field or carries a value of the
    wrong type or an unknown enum member is rejected with `ERR_INVALID_REQUEST`".

    Design: Corner/entities/camera_type_invalid_enum_rejected
    """
    program = create_program()
    res = api.create_camera(
        create_camera_payload(program["id"], camera_type="LIDAR"), PA)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_red_light_camera_with_speed_limit_rejected(api):
    """PRD §3.1: "a red-light camera must be created with `speed_limit_mph` absent or
    null; either shape violation is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/red_light_camera_with_speed_limit_rejected
    """
    program = create_program()
    res = api.create_camera(
        create_camera_payload(program["id"], camera_type="RED_LIGHT",
                              speed_limit_mph=40), PA)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_citation_capture_wrong_program_camera_not_found(api):
    """PRD §2.7: "The same existence discipline applies to body-referenced foreign
    keys on citation capture: the referenced `program_id` and `camera_id` must exist
    and belong to the same program, and a mismatch or missing target yields
    `ERR_NOT_FOUND` as well."

    Design: Corner/entities/citation_capture_wrong_program_camera_not_found
    """
    program_a = create_program(jurisdiction_name="A")
    camera_a = create_camera(program_a["id"], intersection_code="INT-A",
                             camera_type="RED_LIGHT")
    program_b = create_program(jurisdiction_name="B")
    from test_helpers import create_citation_payload, make_review_officer_headers
    res = api.create_citation(
        create_citation_payload(program_b["id"], camera_a["id"],
                                captured_plate_number="X"),
        make_review_officer_headers("ro-1"))
    validate_error(res, "ERR_NOT_FOUND")


def test_notice_record_appended_on_citation_issuance(api):
    """PRD §3.3: "it appends a `NoticeRecord` of `notice_type` `INITIAL`, carrying the
    `registered_owner_id`, an `issued_at_clock` of now, and an
    `amount_owed_snapshot_cents` equal to the assessed amount."

    Design: Corner/entities/notice_record_appended_on_citation_issuance
    """
    program = create_program()
    camera = create_camera(program["id"], camera_type="RED_LIGHT")
    add_calibration(camera["id"])
    create_owner(program["id"], plate_number="ABC123", full_name="Pat")
    citation = capture_citation(program["id"], camera["id"])
    review_to_cited(citation["id"])
    data, meta = validate_paginated(api.list_citation_notices(citation["id"], AUD))
    assert meta["total_count"] == 1
    assert data[0]["notice_type"] == "INITIAL"
    assert data[0]["amount_owed_snapshot_cents"] == 12500
