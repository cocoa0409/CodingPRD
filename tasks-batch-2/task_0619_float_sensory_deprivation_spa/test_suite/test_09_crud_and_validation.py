"""CRUD basics, defaults, not-found, body validation, configuration-error paths, listing,
filtering, and existence-before-state precedence."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, is_valid_uuid,
    setup_member_and_tank, setup_inactive_plan_pending_membership, setup_void_gift_card,
    create_member, create_member_payload, create_tank_payload, create_booking_payload,
    create_gift_card_payload, create_booking,
    set_clock, RANDOM_UUID, api_client, TEST_USERS,
)

FRONTDESK = TEST_USERS["frontdesk_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ─── Member creation defaults (create_member_returns_201_with_defaults) ───
def test_create_member_returns_defaults(api):
    """PRD §3.2: "Every new member starts life with `status` equal to `ACTIVE`,
    `orientation_completed` set to false, `waiver_signed_version` set to 0, and
    `no_show_strikes` set to 0."

    Design: Corner/entities/create_member_returns_201_with_defaults
    """
    set_clock("2026-01-05T00:00:00Z")
    res = api.create_member(create_member_payload(email="fresh@x.com", full_name="Fresh Face"),
                            FRONTDESK)
    member = validate_success(res, 201)
    assert member["status"] == "ACTIVE"
    assert member["orientation_completed"] is False
    assert member["waiver_signed_version"] == 0
    assert member["no_show_strikes"] == 0
    assert is_valid_uuid(member["id"]), "id must be a bare UUID without a type prefix"


# ─── Not found (get_tank_not_found_returns_404) ───────────────────────────
def test_get_unknown_tank_returns_not_found(api):
    """PRD §2.6: "The first identifier that does not resolve to an existing resource causes
    the request to be rejected with `ERR_NOT_FOUND` before any business rule runs."

    Design: Corner/entities/get_tank_not_found_returns_404
    """
    set_clock("2026-01-05T00:00:00Z")
    res = api.get_tank(RANDOM_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# ─── Required fields (create_booking_missing_required_field_returns_422) ──
def test_create_booking_missing_pay_source_rejected(api):
    """PRD §2.7: "Fourth comes request well-formedness — required fields present, enum values
    in range, `end_utc` strictly after `start_utc`, and `session_minutes` being one of the two
    allowed lengths — which fails with `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_booking_missing_required_field_returns_422
    """
    ctx = setup_member_and_tank()
    payload = create_booking_payload(ctx["member"]["id"], ctx["tank"]["id"], 60,
                                     "2026-02-01T10:00:00Z", "CASH")
    del payload["pay_source"]
    res = api.create_booking(payload, FRONTDESK)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


# ─── Type constraint (create_booking_invalid_session_minutes_returns_422) ──
def test_create_booking_invalid_session_minutes_rejected(api):
    """PRD §3.5: "Creating one requires a `member_id` ..., a `session_minutes` value of either
    60 or 90". PRD §2.7: "`session_minutes` being one of the two allowed lengths — which fails
    with `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_booking_invalid_session_minutes_returns_422
    """
    ctx = setup_member_and_tank()
    payload = create_booking_payload(ctx["member"]["id"], ctx["tank"]["id"], 75,
                                     "2026-02-01T10:00:00Z", "CASH")
    res = api.create_booking(payload, FRONTDESK)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


# ─── Defaults (tank_turnover_buffer_default_applied) ──────────────────────
def test_tank_turnover_buffer_defaults_to_30(api):
    """PRD §3.1: "an optional `turnover_buffer_minutes` (defaulting to 30) reserving sanitation
    time after each session before the pod may be re-booked."

    Design: Corner/entities/tank_turnover_buffer_default_applied
    """
    set_clock("2026-01-05T00:00:00Z")
    res = api.create_tank(create_tank_payload(name="Pod-Def", capacity_kind="SINGLE"), ADMIN)
    tank = validate_success(res, 201)
    assert tank["turnover_buffer_minutes"] == 30


# ─── Listing (list_tanks_paginated_envelope) ──────────────────────────────
def test_list_tanks_paginated_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more`
    inside the `meta` object." PRD §2.3: "The `limit` parameter caps the number of items
    returned".

    Design: Corner/entities/list_tanks_paginated_envelope
    """
    set_clock("2026-01-05T00:00:00Z")
    validate_success(api.create_tank(create_tank_payload(name="Pod-L1", capacity_kind="SINGLE"),
                                     ADMIN), 201)
    validate_success(api.create_tank(create_tank_payload(name="Pod-L2", capacity_kind="DUAL"),
                                     ADMIN), 201)
    data, meta = validate_paginated(api.list_tanks(ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ─── Existence before state (existence_before_state_on_unknown_booking_confirm) ──
def test_confirm_unknown_booking_returns_not_found(api):
    """PRD §2.7: "Reference existence is third, per §2.6, failing with `ERR_NOT_FOUND` (HTTP
    404). ... Only once a request is authenticated, authorized, resolvable, well-formed, and
    in-range does the system evaluate state-machine legality".

    Design: Corner/validations/existence_before_state_on_unknown_booking_confirm
    """
    set_clock("2026-01-05T00:00:00Z")
    res = api.confirm_booking("00000000-0000-4000-8000-000000000abc", FRONTDESK)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# ─── Plan inactive (error_plan_inactive_on_activate) ──────────────────────
def test_activate_membership_on_inactive_plan_rejected(api):
    """PRD §3.3: "From `PENDING`, activation requires that the membership's plan still be open
    to new memberships — its `active` flag must be true — and a plan that is no longer active
    rejects activation with `ERR_PLAN_INACTIVE`."

    Design: Corner/errors/error_plan_inactive_on_activate
    """
    ctx = setup_inactive_plan_pending_membership()
    ship = ctx["membership"]
    res = api.activate_membership(ship["id"], FRONTDESK)
    validate_error(res, "ERR_PLAN_INACTIVE", expected_status=409)
    after = validate_success(api.get_membership(ship["id"], FRONTDESK), 200)
    assert after["status"] == "PENDING"


# ─── Gift card inactive (error_gift_card_inactive_on_booking) ─────────────
def test_booking_with_void_gift_card_rejected(api):
    """PRD §3.5: "When the chosen `pay_source` is `GIFT_CARD`, the referenced card must be
    `ACTIVE` — neither `VOID` nor `DEPLETED` — and a non-active card is refused with
    `ERR_GIFT_CARD_INACTIVE`."

    Design: Corner/errors/error_gift_card_inactive_on_booking
    """
    ctx = setup_void_gift_card()
    member, tank, gc = ctx["member"], ctx["tank"], ctx["gift_card"]
    res = api.create_booking(create_booking_payload(
        member["id"], tank["id"], 60, "2026-02-01T10:00:00Z", "GIFT_CARD",
        gift_card_id=gc["id"]), FRONTDESK)
    validate_error(res, "ERR_GIFT_CARD_INACTIVE", expected_status=409)


# ─── Validation range (error_validation_range_negative_giftcard) ──────────
def test_issue_gift_card_zero_balance_rejected(api):
    """PRD §3.5: "Staff issue one with a unique `code` and an `initial_balance_cents` face
    value that must be strictly greater than zero". PRD §2.7: "the numeric-range checks on
    configuration creation (described in §3.1 and §3.6) fail with `ERR_VALIDATION_RANGE` (HTTP
    422)."

    Design: Corner/errors/error_validation_range_negative_giftcard
    """
    set_clock("2026-01-05T00:00:00Z")
    res = api.create_gift_card(create_gift_card_payload(code="GC-NEG", initial_balance_cents=0),
                               FRONTDESK)
    validate_error(res, "ERR_VALIDATION_RANGE", expected_status=422)


# ─── Filtered list (filtered_list_bookings_by_tank) ───────────────────────
def test_list_bookings_filtered_by_tank(api):
    """PRD §3.5: "The booking list is filterable by `member_id`, `tank_id`, `membership_id`,
    `gift_card_id`, and `status`."

    Design: Corner/endpoints/filtered_list_bookings_by_tank
    """
    ctx = setup_member_and_tank()
    member, tank = ctx["member"], ctx["tank"]
    booking = create_booking(member["id"], tank["id"], 60, "2026-02-01T10:00:00Z", "CASH")
    data, meta = validate_paginated(api.list_bookings(FRONTDESK, params={"tank_id": tank["id"]}))
    assert meta["total_count"] == 1
    assert all(b["tank_id"] == tank["id"] for b in data)
    assert booking["id"] in [b["id"] for b in data]
