"""Entity creation, field validation, computed defaults, FK integrity, listing /
pagination / filtering, and the wallet floor.

Covers corner entities instances and the endpoints instances
wallet_adjustment_debit_below_zero_rejected and enrollment_filtered_list_by_session.
"""
import pytest
from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID,
    setup_catalogue, create_guardian, create_member, create_belt_level,
    create_open_session, enroll_drop_in, credit_wallet,
    make_guardian_headers, TEST_USERS,
    api_client,
)

ADMIN = TEST_USERS["center_admin_headers"]


# ─── Corner / entities / create_program_returns_201_with_all_fields ─
def test_create_program_returns_201_with_all_fields(api):
    """PRD §2.4: "A unique, server-minted identifier formatted as a UUID, with no type
    prefix."
    PRD §2.4: "A system-managed integer that begins at its initial value and increments
    by one with every mutation of the resource."
    PRD §3.1: "is created with a `name`, a short unique `code`, a `min_age`, a `max_age`,
    and a `drop_in_fee_cents`."

    Design: Corner/entities/create_program_returns_201_with_all_fields
    """
    res = api.create_program(
        {"name": "Create Coding", "code": "CRE10", "min_age": 6, "max_age": 14,
         "drop_in_fee_cents": 4500}, ADMIN)
    program = validate_success(res, 201)
    assert program["version"] == 1
    assert program["min_age"] == 6
    assert program["drop_in_fee_cents"] == 4500


# ─── Corner / entities / create_member_malformed_birth_date_returns_invalid_field ─
def test_create_member_malformed_birth_date_rejected(api):
    """PRD §5 / §3.5: field-shape validation guards "valid enums, and in-range numbers
    (yielding `ERR_INVALID_FIELD`, HTTP 422)."
    PRD §3.2: "a `birth_date` (an ISO 8601 value whose date portion is authoritative)."

    Design: Corner/entities/create_member_malformed_birth_date_returns_invalid_field
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    res = api.create_member(
        {"guardian_id": guardian["id"], "program_id": program["id"], "full_name": "M",
         "birth_date": "not-a-date"},
        make_guardian_headers(guardian["id"]),
    )
    validate_error(res, "ERR_INVALID_FIELD")


# ─── Corner / entities / create_member_defaults_current_belt_to_rank1_computed ─
def test_create_member_defaults_current_belt_to_rank1(api):
    """PRD §3.2: "On creation, the member's `current_belt_level_id` is automatically set
    to the rank-1 belt of the member's program, and the member's `active_badge_count` is
    initialized to 0."

    Design: Corner/entities/create_member_defaults_current_belt_to_rank1_computed
    """
    center, program, belt1 = setup_catalogue(drop_in_fee_cents=4000, required_badge_count=2)
    guardian = create_guardian()
    res = api.create_member(
        {"guardian_id": guardian["id"], "program_id": program["id"], "full_name": "M",
         "birth_date": "2016-01-01"},
        make_guardian_headers(guardian["id"]),
    )
    member = validate_success(res, 201)
    assert member["current_belt_level_id"] == belt1["id"]
    assert member["active_badge_count"] == 0


# ─── Corner / entities / create_program_duplicate_code_returns_invalid_field ─
def test_create_program_duplicate_code_rejected(api):
    """PRD §3.1: "The `code` must be unique across all programs and consist of 2 to 8
    uppercase characters drawn from A–Z and 0–9."

    Design: Corner/entities/create_program_duplicate_code_returns_invalid_field
    """
    api.create_program(
        {"name": "P1", "code": "DUP1", "min_age": 4, "max_age": 18, "drop_in_fee_cents": 4000},
        ADMIN)
    res = api.create_program(
        {"name": "P2", "code": "DUP1", "min_age": 4, "max_age": 18, "drop_in_fee_cents": 5000},
        ADMIN)
    validate_error(res, "ERR_INVALID_FIELD")


# ─── Corner / entities / create_session_camp_week_count_one_returns_invalid_field ─
def test_create_session_after_school_multiweek_rejected(api):
    """PRD §3.4: "the `week_count` must be at least 1 and must equal 1 unless the format
    is `CAMP`."

    Design: Corner/entities/create_session_camp_week_count_one_returns_invalid_field
    """
    center = get_success_data(api.create_center(
        {"name": "C1", "device_count": 20, "min_student_instructor_ratio": 6}, ADMIN))
    program = get_success_data(api.create_program(
        {"name": "P", "code": "WC1", "min_age": 4, "max_age": 18, "drop_in_fee_cents": 4000},
        ADMIN))
    res = api.create_session(
        {"center_id": center["id"], "program_id": program["id"], "format": "AFTER_SCHOOL",
         "week_count": 3, "starts_at": "2026-05-01T16:00:00Z", "ends_at": "2026-05-01T18:00:00Z",
         "device_seats_requested": 1, "assigned_instructor_count": 2}, ADMIN)
    validate_error(res, "ERR_INVALID_FIELD")


# ─── Corner / entities / create_session_ends_before_starts_returns_invalid_field ─
def test_create_session_inverted_interval_rejected(api):
    """PRD §3.4: "The `starts_at` and `ends_at` are ISO 8601 UTC instants, and `ends_at`
    must be strictly after `starts_at`."

    Design: Corner/entities/create_session_ends_before_starts_returns_invalid_field
    """
    center = get_success_data(api.create_center(
        {"name": "C1", "device_count": 20, "min_student_instructor_ratio": 6}, ADMIN))
    program = get_success_data(api.create_program(
        {"name": "P", "code": "EB1", "min_age": 4, "max_age": 18, "drop_in_fee_cents": 4000},
        ADMIN))
    res = api.create_session(
        {"center_id": center["id"], "program_id": program["id"], "format": "AFTER_SCHOOL",
         "week_count": 1, "starts_at": "2026-05-01T18:00:00Z", "ends_at": "2026-05-01T16:00:00Z",
         "device_seats_requested": 1, "assigned_instructor_count": 2}, ADMIN)
    validate_error(res, "ERR_INVALID_FIELD")


# ─── Corner / entities / get_member_nonexistent_returns_not_found ─
def test_get_nonexistent_member_returns_not_found(api):
    """PRD §2.9: "rejects the request with `ERR_RESOURCE_NOT_FOUND` (HTTP 404) at the
    first identifier, whether in the path or the body, that does not correspond to an
    existing resource."

    Design: Corner/entities/get_member_nonexistent_returns_not_found
    """
    res = api.get_member(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_RESOURCE_NOT_FOUND")


# ─── Corner / entities / create_belt_level_bad_program_fk_returns_not_found ─
def test_create_belt_level_bad_program_fk_returns_not_found(api):
    """PRD §2.9: "the system validates the existence of every referenced resource
    left-to-right in the canonical order"
    PRD §2.9: "rejects the request with `ERR_RESOURCE_NOT_FOUND` (HTTP 404) at the first
    identifier, whether in the path or the body, that does not correspond to an existing
    resource."

    Design: Corner/entities/create_belt_level_bad_program_fk_returns_not_found
    """
    res = api.create_belt_level(
        {"program_id": NON_EXISTENT_UUID, "name": "White", "rank": 1, "required_badge_count": 0},
        ADMIN)
    validate_error(res, "ERR_RESOURCE_NOT_FOUND")


# ─── Corner / entities / list_members_paginated_envelope ─
def test_list_members_paginated_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_members_paginated_envelope
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    create_member(guardian["id"], program["id"])
    create_member(guardian["id"], program["id"])
    res = api.list_members(make_guardian_headers(guardian["id"]),
                           params={"guardian_id": guardian["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ─── Corner / entities / belt_level_self_referential_prereq_filter ─
def test_belt_level_self_referential_prereq_filter(api):
    """PRD §3.1: "Belt levels may be listed and filtered by `program_id` or by
    `prereq_belt_level_id`."

    Design: Corner/entities/belt_level_self_referential_prereq_filter
    """
    program = get_success_data(api.create_program(
        {"name": "P", "code": "SR1", "min_age": 4, "max_age": 18, "drop_in_fee_cents": 4000},
        ADMIN))
    belt1 = create_belt_level(program["id"], rank=1, required_badge_count=1)
    belt2 = create_belt_level(program["id"], rank=2, prereq_belt_level_id=belt1["id"],
                              required_badge_count=1)
    res = api.list_belt_levels(ADMIN, params={"prereq_belt_level_id": belt1["id"]})
    data, _ = validate_paginated(res)
    assert len(data) == 1
    assert data[0]["id"] == belt2["id"]


# ─── Corner / endpoints / wallet_adjustment_debit_below_zero_rejected ─
def test_wallet_debit_below_zero_rejected(api):
    """PRD §3.2: "If a negative adjustment would drive the wallet below zero — that is, the
    magnitude of the debit exceeds the current balance — the request is rejected with
    `ERR_WALLET_INSUFFICIENT` (HTTP 409)."

    Design: Corner/endpoints/wallet_adjustment_debit_below_zero_rejected
    """
    guardian = create_guardian()
    credit_wallet(guardian["id"], 1000, reason="seed")
    res = api.adjust_wallet(guardian["id"], {"amount_cents": -5000, "reason": "overdraw"}, ADMIN)
    validate_error(res, "ERR_WALLET_INSUFFICIENT")
    after = get_success_data(api.get_guardian(guardian["id"], ADMIN))
    assert after["wallet_credit_cents"] == 1000


# ─── Corner / endpoints / enrollment_filtered_list_by_session ─
def test_enrollment_filtered_list_by_session(api):
    """PRD §3.5: "Enrollments may be listed and filtered by `session_id` or `member_id`."

    Design: Corner/endpoints/enrollment_filtered_list_by_session
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    session, _ = create_open_session(center["id"], program["id"], assigned_instructor_count=5)
    enrollment = enroll_drop_in(guardian["id"], session["id"], member["id"])
    res = api.list_enrollments(ADMIN, params={"session_id": session["id"]})
    data, _ = validate_paginated(res)
    assert len(data) == 1
    assert data[0]["id"] == enrollment["id"]
