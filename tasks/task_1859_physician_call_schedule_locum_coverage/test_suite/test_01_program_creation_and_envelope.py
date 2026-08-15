"""Program/physician creation, defaults, envelope and pagination behavior.

Covers the corner-design entity claims: successful creation with documented
defaults, required-field and range violations, not-found reads, pagination,
system-field minting, and holiday-over-weekend date classification.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_call_program,
    assert_call_slot,
    assert_physician,
    create_draft_program,
    create_physician,
    create_physician_payload,
    create_program_payload,
    generate_program,
    list_slots,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_create_program_success_with_defaults(api):
    """PRD §3.1: "A new program is DRAFT, with `payroll_reserved_cents` and
    `payroll_accrued_cents` at zero and `version` at 1."
    PRD §3.1: "`weekday_primary_required`, `weekend_primary_required`, and
    `holiday_primary_required` each default to 1, while `weekday_backup_required`,
    `weekend_backup_required`, and `holiday_backup_required` each default to 0."
    PRD §3.4: "the slot's `window_start` must be at least `swap_cutoff_hours`
    (default 48 hours) in the future".
    PRD §3.5: "the program's `credentialing_lead_hours` (default 120 hours, five
    days of lead time)".

    Design: Corner/entities/create_program_success_with_defaults
    """
    resp = api.create_program(
        create_program_payload(
            name="Cards Sep",
            period_start="2026-09-08",
            period_end="2026-09-10",
            weekday_primary_required=1,
        ),
        ADMIN,
    )
    data = validate_success(resp, 201)
    assert_call_program(data)
    assert data["status"] == "DRAFT"
    assert data["version"] == 1
    assert data["payroll_reserved_cents"] == 0
    assert data["payroll_accrued_cents"] == 0
    # Documented defaults applied (PRD §2.6-§2.9, §3.3-§3.5).
    assert data["swap_cutoff_hours"] == 48
    assert data["credentialing_lead_hours"] == 120
    assert data["primary_rate_cents"] == 50000
    assert data["backup_rate_cents"] == 20000
    assert data["weekend_multiplier"] == 1.25
    assert data["holiday_multiplier"] == 1.5
    assert data["backup_activation_multiplier"] == 2.0
    assert data["moonlight_premium_multiplier"] == 1.15
    assert data["moonlight_premium_threshold_hours"] == 40
    assert data["weekday_call_points"] == 1.0
    assert data["weekend_call_points"] == 2.0
    assert data["holiday_call_points"] == 3.0
    assert data["backup_point_multiplier"] == 0.5
    assert data["equity_band_points"] == 4.0
    assert data["holiday_dates"] == []


def test_create_program_missing_budget_returns_invalid_request(api):
    """PRD §3.1: "Fiscal configuration is anchored by `payroll_budget_cents`, a
    required, strictly positive cap on reserved payroll."
    PRD §2.11: "Request shape — required fields present, types valid, enum
    members valid, ... violations yield `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_program_missing_budget_returns_invalid_request
    """
    payload = {
        "name": "Cards Sep",
        "service_line": "CARDIOLOGY",
        "period_start": "2026-09-08",
        "period_end": "2026-09-10",
    }
    resp = api.create_program(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    programs, meta = validate_paginated(api.list_programs(ADMIN))
    assert programs == [], "rejected create must not persist a program"
    assert meta["total_count"] == 0


def test_create_program_all_zero_counts_returns_invalid_request(api):
    """PRD §3.1: "Every count must be at least zero, and at least one of the six
    must be strictly positive, or creation fails with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_program_all_zero_counts_returns_invalid_request
    """
    resp = api.create_program(
        create_program_payload(
            name="Empty Program",
            period_start="2026-09-08",
            period_end="2026-09-10",
            weekday_primary_required=0,
            weekend_primary_required=0,
            holiday_primary_required=0,
            weekday_backup_required=0,
            weekend_backup_required=0,
            holiday_backup_required=0,
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_program_period_end_before_start_returns_invalid_request(api):
    """PRD §3.1: "a closed scheduling period running from `period_start` through
    `period_end` — an end earlier than the start is rejected as
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_program_period_end_before_start_returns_invalid_request
    """
    resp = api.create_program(
        create_program_payload(
            name="Backwards", period_start="2026-09-10", period_end="2026-09-08"
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_physician_default_moonlight_cap_applied(api):
    """PRD §3.2: "`moonlight_cap_hours` is optional and defaults to 96. New
    physicians are ACTIVE."

    Design: Corner/entities/create_physician_default_moonlight_cap_applied
    """
    resp = api.create_physician(
        create_physician_payload(full_name="Dr Alvarez"), ADMIN
    )
    data = validate_success(resp, 201)
    assert_physician(data)
    assert data["moonlight_cap_hours"] == 96
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1


def test_get_nonexistent_program_returns_not_found(api):
    """PRD §2.11: "each unknown id surfaces its own 404: `ERR_PROGRAM_NOT_FOUND`,
    `ERR_PHYSICIAN_NOT_FOUND`, ..."

    Design: Corner/entities/get_nonexistent_program_returns_not_found
    """
    resp = api.get_program(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_FOUND, 404)


def test_physician_list_pagination_envelope(api):
    """PRD §2.3: "`limit` sets the maximum number of items returned ... `offset`
    sets the number of items skipped and defaults to 0. The `meta` object of a
    list response carries `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/physician_list_pagination_envelope
    """
    for name in ("Dr A", "Dr B", "Dr C"):
        create_physician(full_name=name)

    page1, meta1 = validate_paginated(api.list_physicians(ADMIN, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(api.list_physicians(ADMIN, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_slot_date_type_holiday_precedence_over_weekend(api):
    """PRD §2.6: "HOLIDAY takes precedence over WEEKEND — a holiday that falls on
    a Sunday is paid and scored as a holiday."
    PRD §2.6: "Every slot's `window_start` is its `date` at 07:00:00Z, and its
    `window_end` is the next date at 07:00:00Z."

    2026-09-12 is a Saturday listed in holiday_dates: the holiday primary count
    (1) drives generation, not the weekend primary count (2).

    Design: Corner/entities/slot_date_type_holiday_precedence_over_weekend
    """
    program = create_draft_program(
        name="Holiday Saturday",
        period_start="2026-09-12",
        period_end="2026-09-12",
        holiday_dates=["2026-09-12"],
        weekday_primary_required=0,
        weekend_primary_required=2,
        holiday_primary_required=1,
    )
    generate_program(program["id"])
    slots = list_slots(program["id"])
    assert len(slots) == 1, "holiday count (1) must win over weekend count (2)"
    slot = slots[0]
    assert_call_slot(slot)
    assert slot["date_type"] == "HOLIDAY"
    assert slot["date"] == "2026-09-12"
    assert slot["window_start"] == "2026-09-12T07:00:00Z"
    assert slot["window_end"] == "2026-09-13T07:00:00Z"


def test_create_physician_system_fields_input_ignored(api):
    """PRD §2.4: "`id` is a server-minted UUID with no type prefix."
    PRD §2.4: "`version` is an integer that starts at 1 when the resource is
    created and increments by one on every mutation."

    Design: Corner/entities/create_physician_system_fields_input_ignored
    """
    client_id = "11111111-1111-1111-1111-111111111111"
    payload = create_physician_payload(full_name="Dr A")
    payload.update(
        {"id": client_id, "version": 99, "created_at": "2020-01-01T00:00:00Z"}
    )
    resp = api.create_physician(payload, ADMIN)
    data = validate_success(resp, 201)
    assert data["id"] != client_id, "server must mint its own UUID"
    assert data["version"] == 1
    assert data["created_at"] != "2020-01-01T00:00:00Z"
