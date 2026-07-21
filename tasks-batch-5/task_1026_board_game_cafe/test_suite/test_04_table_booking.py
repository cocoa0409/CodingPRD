"""Table booking: turnover-buffer temporal conflict, capacity / out-of-service
guards, creation, required-field validation, and FK reverse-reachability."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, TEST_USERS,
    create_table, create_membership, create_reservation, set_clock,
)

MGR = TEST_USERS["manager_headers"]
STAFF = TEST_USERS["staff_headers"]


# ─── Difficulty/resource_temporal_overlap/table_reservation_turnover_buffer_conflict ─
def test_reservation_within_turnover_buffer_conflicts(api):
    """PRD §2.7: "a requested window conflicts with an existing one when the requested
    `start_at` is earlier than the existing `end_at` plus 15 minutes, and simultaneously
    the requested `end_at` plus 15 minutes is later than the existing `start_at`. A gap of
    exactly 15 minutes between the two windows is acceptable and is not a conflict. A
    violation is rejected with `ERR_TABLE_TIME_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/table_reservation_turnover_buffer_conflict
    """
    table = create_table(api, label="T11", seats=4, half_hour_rate_cents=500,
                         day_pass_cents=6000, cover_fee_cents=0, min_spend_cents=0)
    set_clock(api, "2026-07-06T10:00:00Z")
    create_reservation(api, table["id"], "2026-07-06T18:00:00Z", "2026-07-06T20:00:00Z",
                       party_size=2)
    # 20:10 start is 10 minutes after the existing 20:00 end -> gap 10 < 15
    res = api.create_reservation(
        {"table_id": table["id"], "party_size": 2,
         "start_at": "2026-07-06T20:10:00Z", "end_at": "2026-07-06T21:00:00Z"}, STAFF)
    validate_error(res, "ERR_TABLE_TIME_CONFLICT")


def test_reservation_with_exact_buffer_gap_accepted(api):
    """PRD §2.7: "A gap of exactly 15 minutes between the two windows is acceptable and is
    not a conflict."

    Design: Difficulty/resource_temporal_overlap/table_reservation_turnover_buffer_conflict
    """
    table = create_table(api, label="T11b", seats=4, half_hour_rate_cents=500,
                         day_pass_cents=6000, cover_fee_cents=0, min_spend_cents=0)
    set_clock(api, "2026-07-06T10:00:00Z")
    create_reservation(api, table["id"], "2026-07-06T18:00:00Z", "2026-07-06T20:00:00Z",
                       party_size=2)
    # 20:15 start is exactly 15 minutes after the 20:00 end -> accepted
    ok = validate_success(api.create_reservation(
        {"table_id": table["id"], "party_size": 2,
         "start_at": "2026-07-06T20:15:00Z", "end_at": "2026-07-06T21:00:00Z"}, STAFF),
        expected_status=201)
    assert ok["status"] == "BOOKED"


# ─── Corner/validations/reservation_party_exceeds_seats_returns_capacity ───
def test_party_exceeds_seats_returns_capacity_exceeded(api):
    """PRD §3.2: "the `party_size` must not exceed the table's `seats`, or the booking is
    rejected with `ERR_TABLE_CAPACITY_EXCEEDED`"

    Design: Corner/validations/reservation_party_exceeds_seats_returns_capacity
    """
    table = create_table(api, label="C10", seats=4, half_hour_rate_cents=0, day_pass_cents=0,
                         cover_fee_cents=0, min_spend_cents=0)
    set_clock(api, "2026-07-05T10:00:00Z")
    res = api.create_reservation(
        {"table_id": table["id"], "party_size": 5,
         "start_at": "2026-07-05T18:00:00Z", "end_at": "2026-07-05T20:00:00Z"}, STAFF)
    validate_error(res, "ERR_TABLE_CAPACITY_EXCEEDED")


# ─── Corner/validations/book_out_of_service_table_returns_out_of_service ───
def test_book_out_of_service_table_returns_out_of_service(api):
    """PRD §3.2: "the table must not be `OUT_OF_SERVICE`, or the booking is rejected with
    `ERR_TABLE_OUT_OF_SERVICE`"

    Design: Corner/validations/book_out_of_service_table_returns_out_of_service
    """
    table = create_table(api, label="C11", seats=4, half_hour_rate_cents=0, day_pass_cents=0,
                         cover_fee_cents=0, min_spend_cents=0)
    validate_success(api.update_table(table["id"], {"status": "OUT_OF_SERVICE"}, MGR))
    set_clock(api, "2026-07-05T10:00:00Z")
    res = api.create_reservation(
        {"table_id": table["id"], "party_size": 2,
         "start_at": "2026-07-05T18:00:00Z", "end_at": "2026-07-05T20:00:00Z"}, STAFF)
    validate_error(res, "ERR_TABLE_OUT_OF_SERVICE")


# ─── Corner/entities/create_table_returns_201_with_fields ──────────────────
def test_create_table_returns_201_available(api):
    """PRD §3.2: "A table begins `AVAILABLE`; a `Manager` may later update its rates or
    `status`"
    PRD §3.2: "a `zone` (one of `MAIN`, `QUIET`, or `PATIO`, defaulting to `MAIN`)"

    Design: Corner/entities/create_table_returns_201_with_fields
    """
    data = validate_success(api.create_table(
        {"label": "C1", "seats": 6, "half_hour_rate_cents": 500, "day_pass_cents": 6000,
         "cover_fee_cents": 300, "min_spend_cents": 2000, "zone": "PATIO"}, MGR),
        expected_status=201)
    assert data["status"] == "AVAILABLE"
    assert data["zone"] == "PATIO"


# ─── Corner/entities/create_reservation_missing_start_at_returns_validation ─
def test_create_reservation_missing_start_at_returns_validation(api):
    """PRD §2.8: "Body well-formedness is checked next — required fields present, enums
    valid, integers within range, `end_at` strictly after `start_at`, `email` unique,
    `barcode` unique — failing with `ERR_VALIDATION`."

    Design: Corner/entities/create_reservation_missing_start_at_returns_validation
    """
    table = create_table(api, label="C2", seats=4, half_hour_rate_cents=0, day_pass_cents=0,
                         cover_fee_cents=0, min_spend_cents=0)
    res = api.create_reservation(
        {"table_id": table["id"], "party_size": 2, "end_at": "2026-07-05T20:00:00Z"}, STAFF)
    validate_error(res, "ERR_VALIDATION")


# ─── Corner/endpoints/list_reservations_by_membership_finds_child ──────────
def test_list_reservations_filtered_by_membership(api):
    """PRD §3.2: "Reservations can be listed and filtered by `table_id`, by `membership_id`,
    and by `status`."

    Design: Corner/endpoints/list_reservations_by_membership_finds_child
    """
    table = create_table(api, label="C13", seats=4, half_hour_rate_cents=0, day_pass_cents=0,
                         cover_fee_cents=0, min_spend_cents=0)
    member = create_membership(api, email="own@x.com", full_name="Owner")
    set_clock(api, "2026-07-05T10:00:00Z")
    resv = create_reservation(api, table["id"], "2026-07-05T18:00:00Z", "2026-07-05T20:00:00Z",
                              party_size=2, membership_id=member["id"])
    data, meta = validate_paginated(api.list_reservations(STAFF, params={"membership_id": member["id"]}))
    assert meta["total_count"] == 1
    assert any(r["id"] == resv["id"] for r in data)
