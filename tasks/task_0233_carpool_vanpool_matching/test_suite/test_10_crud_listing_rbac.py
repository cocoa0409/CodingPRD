"""Resource creation, defaults, computed fields, listing, immutability, and RBAC
(PRD §2.1, §2.3, §2.4, §3.1-§3.3, §3.10).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, ApiErrorId,
    make_driver_headers, make_rider_headers, make_program_admin_headers,
    setup_completed_single_rider_trip, setup_active_pool, create_trip, create_reservation,
)

PA = make_program_admin_headers()


def test_create_employer_program_returns_201_with_defaults(api):
    """PRD §3.1: "A new program is born `ACTIVE` with `subsidy_consumed_cents` at 0".
    PRD §3.1: "The optional `grh_max_events_per_year` defaults to 4 approved GRH
    events per member per calendar year when omitted."

    Design: Corner/entities/create_employer_program_returns_201_with_defaults
    """
    program = validate_success(api.create_employer_program(
        {"employer_name": "Acme", "hov_discount_pct": 0.50, "employer_match_pct": 0.30,
         "monthly_benefit_cap_cents": 31500, "grh_annual_cap_cents": 20000,
         "grh_per_event_cap_cents": 6000, "subsidy_budget_cents": 1000000}, PA),
        expected_status=201)
    assert program["status"] == "ACTIVE"
    assert program["subsidy_consumed_cents"] == 0
    assert program["grh_max_events_per_year"] == 4


def test_get_member_not_found_returns_404(api):
    """PRD §2.9: "Where a path carries an `id`, that resource must exist or the
    request fails with `ERR_NOT_FOUND` before any body validation runs."

    Design: Corner/entities/get_member_not_found_returns_404
    """
    validate_error(api.get_member("00000000-0000-4000-8000-000000000000", PA),
                   ApiErrorId.ERR_NOT_FOUND.value)


def test_create_member_missing_full_name_returns_invalid_request(api):
    """PRD §2.8: "Request well-formedness is fourth: required fields must be present
    ... failing which the request is rejected with `ERR_INVALID_REQUEST`."
    PRD §3.2: "registers a **member** under a program by supplying the
    `employer_program_id`, the member's `full_name`, and their corridor zones
    `home_zone` and `work_zone`."

    full_name has no default, so omitting it is rejected.

    Design: Corner/entities/create_member_missing_required_field_returns_invalid_request
    """
    program = get_success_data(api.create_employer_program(
        {"employer_name": "Acme", "hov_discount_pct": 0.50, "employer_match_pct": 0.30,
         "monthly_benefit_cap_cents": 31500, "grh_annual_cap_cents": 20000,
         "grh_per_event_cap_cents": 6000, "subsidy_budget_cents": 1000000}, PA))
    validate_error(api.create_member(
        {"employer_program_id": program["id"], "home_zone": "Z-N", "work_zone": "Z-DT"}, PA),
        ApiErrorId.ERR_INVALID_REQUEST.value)


def test_member_optional_fields_default_when_omitted(api):
    """PRD §3.2: "The `can_drive` flag defaults to false ... `wallet_balance_cents`
    is the member's prepaid balance and defaults to 0. A freshly registered member
    starts with `reliability_score` at 100.0".

    Design: Corner/entities/member_defaults_applied_when_optional_omitted
    """
    program = get_success_data(api.create_employer_program(
        {"employer_name": "Acme", "hov_discount_pct": 0.50, "employer_match_pct": 0.30,
         "monthly_benefit_cap_cents": 31500, "grh_annual_cap_cents": 20000,
         "grh_per_event_cap_cents": 6000, "subsidy_budget_cents": 1000000}, PA))
    member = validate_success(api.create_member(
        {"employer_program_id": program["id"], "full_name": "Rae", "home_zone": "Z-N",
         "work_zone": "Z-DT"}, PA), expected_status=201)
    assert member["can_drive"] is False
    assert member["wallet_balance_cents"] == 0
    assert member["reliability_score"] == 100.0


def test_pool_seat_capacity_copied_from_vehicle(api):
    """PRD §3.3: "At creation the pool's `seat_capacity` is copied from the linked
    vehicle's `seat_capacity`, `committed_seat_count` starts at 0, and the pool
    enters the `FORMING` state."

    Design: Corner/entities/pool_seat_capacity_computed_from_vehicle_ignores_input
    """
    program = get_success_data(api.create_employer_program(
        {"employer_name": "Acme", "hov_discount_pct": 0.50, "employer_match_pct": 0.30,
         "monthly_benefit_cap_cents": 31500, "grh_annual_cap_cents": 20000,
         "grh_per_event_cap_cents": 6000, "subsidy_budget_cents": 1000000}, PA))
    drv = get_success_data(api.create_member(
        {"employer_program_id": program["id"], "full_name": "Dee", "home_zone": "Z-N",
         "work_zone": "Z-DT", "can_drive": True}, PA))
    veh = get_success_data(api.create_vehicle(
        {"owner_member_id": drv["id"], "plate": "VAN-1", "seat_capacity": 6},
        make_driver_headers(drv["id"])))
    pool = validate_success(api.create_pool(
        {"employer_program_id": program["id"], "driver_member_id": drv["id"],
         "vehicle_id": veh["id"], "kind": "VANPOOL", "origin_zone": "Z-N", "dest_zone": "Z-DT",
         "departure_days": ["MON", "TUE", "WED", "THU", "FRI"],
         "base_cost_cents": 2000, "per_mile_cents": 120}, make_driver_headers(drv["id"])),
        expected_status=201)
    assert pool["seat_capacity"] == 6
    assert pool["committed_seat_count"] == 0
    assert pool["status"] == "FORMING"


def test_match_request_with_inverted_window_returns_invalid_request(api):
    """PRD §3.4: "the acceptable departure window expressed as minutes after local
    midnight: `earliest_departure_min` and `latest_departure_min`, each at least 0
    and below 1440, with the later bound at least the earlier."

    latest 400 < earliest 600 violates the range constraint.

    Design: Corner/entities/match_request_invalid_window_returns_invalid_request
    """
    program = get_success_data(api.create_employer_program(
        {"employer_name": "Acme", "hov_discount_pct": 0.50, "employer_match_pct": 0.30,
         "monthly_benefit_cap_cents": 31500, "grh_annual_cap_cents": 20000,
         "grh_per_event_cap_cents": 6000, "subsidy_budget_cents": 1000000}, PA))
    rider = get_success_data(api.create_member(
        {"employer_program_id": program["id"], "full_name": "Rae", "home_zone": "Z-N",
         "work_zone": "Z-DT"}, PA))
    validate_error(api.create_match_request(
        {"rider_member_id": rider["id"], "origin_zone": "Z-N", "dest_zone": "Z-DT",
         "needed_days": ["MON"], "earliest_departure_min": 600, "latest_departure_min": 400},
        make_rider_headers(rider["id"])), ApiErrorId.ERR_INVALID_REQUEST.value)


def test_subsidy_ledger_entry_is_immutable_audit_record(api):
    """PRD §2.4: "a `SubsidyLedgerEntry` and a `ReliabilityEvent` carry only `id` and
    `created_at`. Neither has an `updated_at` field and neither has a `version` field
    — once written, they are never modified."
    PRD §3.7: "For each finalized reservation a `SubsidyLedgerEntry` debit equal to
    the `final_subsidy_cents` with reason `RESERVATION_FINALIZED` is appended".

    A finalized reservation produces a DEBIT ledger row; the program's
    subsidy_consumed_cents reconciles to 2080.

    Design: Corner/entities/subsidy_ledger_entry_is_immutable_no_version_field
    """
    ctx = setup_completed_single_rider_trip(
        api=api, base_cost_cents=2000, per_mile_cents=120, distance_miles=10.0,
        hov_lane_used_create=True, hov_lane_used_complete=True, pay_now=True)
    entries, _meta = validate_paginated(api.list_program_ledger(ctx["program_id"], PA))
    assert len(entries) >= 1
    first = entries[0]
    assert first["entry_type"] == "DEBIT"
    assert "updated_at" not in first
    assert "version" not in first
    assert get_success_data(api.get_employer_program(ctx["program_id"], PA))[
        "subsidy_consumed_cents"] == 2080


def test_list_members_pagination_envelope(api):
    """PRD §2.3: "Each list response carries the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope."

    Two members under one program, limit=1 -> total_count 2, has_more true, one row.

    Design: Corner/entities/list_members_pagination_envelope_fields_present
    """
    program = get_success_data(api.create_employer_program(
        {"employer_name": "Acme", "hov_discount_pct": 0.50, "employer_match_pct": 0.30,
         "monthly_benefit_cap_cents": 31500, "grh_annual_cap_cents": 20000,
         "grh_per_event_cap_cents": 6000, "subsidy_budget_cents": 1000000}, PA))
    for nm in ("A", "B"):
        get_success_data(api.create_member(
            {"employer_program_id": program["id"], "full_name": nm, "home_zone": "Z-N",
             "work_zone": "Z-DT"}, PA))
    data, meta = validate_paginated(api.list_members(
        PA, params={"employer_program_id": program["id"], "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_list_reservations_filtered_by_trip_id(api):
    """PRD §2.9: "List endpoints that accept a filter (for example a ... `trip_id`
    filter) return only the rows whose corresponding foreign key matches".

    Design: Corner/endpoints/list_reservations_filtered_by_trip_id
    """
    ctx = setup_active_pool(api=api, seed_rider_name="Rae", seed_rider_wallet=50000)
    drv_id, pool_id = ctx["driver_id"], ctx["pool_id"]
    rider = ctx["seed"]
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=10.0)
    res = create_reservation(trip["id"], rider["id"], trip["version"], api=api, seat_count=1)
    data, _meta = validate_paginated(api.list_reservations(
        make_driver_headers(drv_id), params={"trip_id": trip["id"]}))
    assert len(data) == 1
    assert data[0]["id"] == res["id"]


def test_rider_cannot_create_pool_returns_forbidden(api):
    """PRD §2.1: "When a role is present and well-formed but is not permitted to
    invoke the requested operation ... the request is rejected with `ERR_FORBIDDEN`."

    POST /pools is a Driver/PlatformOps operation; a Rider is denied.

    Design: Corner/rbac/rider_cannot_create_pool_returns_forbidden
    """
    program = get_success_data(api.create_employer_program(
        {"employer_name": "Acme", "hov_discount_pct": 0.50, "employer_match_pct": 0.30,
         "monthly_benefit_cap_cents": 31500, "grh_annual_cap_cents": 20000,
         "grh_per_event_cap_cents": 6000, "subsidy_budget_cents": 1000000}, PA))
    drv = get_success_data(api.create_member(
        {"employer_program_id": program["id"], "full_name": "Dee", "home_zone": "Z-N",
         "work_zone": "Z-DT", "can_drive": True}, PA))
    rider = get_success_data(api.create_member(
        {"employer_program_id": program["id"], "full_name": "Rae", "home_zone": "Z-N",
         "work_zone": "Z-DT"}, PA))
    veh = get_success_data(api.create_vehicle(
        {"owner_member_id": drv["id"], "plate": "VAN-1", "seat_capacity": 6},
        make_driver_headers(drv["id"])))
    validate_error(api.create_pool(
        {"employer_program_id": program["id"], "driver_member_id": drv["id"],
         "vehicle_id": veh["id"], "kind": "VANPOOL", "origin_zone": "Z-N", "dest_zone": "Z-DT",
         "departure_days": ["MON"], "base_cost_cents": 2000, "per_mile_cents": 120},
        make_rider_headers(rider["id"])), ApiErrorId.ERR_FORBIDDEN.value)


def test_rider_cannot_reserve_for_another_member_returns_forbidden(api):
    """PRD §2.1: "a `Rider` reserving a seat must supply a `rider_member_id` equal to
    `X-User-ID`; a mismatch is an ownership failure surfaced as `ERR_FORBIDDEN`."

    Design: Corner/rbac/rider_cannot_reserve_for_another_member_returns_forbidden
    """
    ctx = setup_active_pool(api=api, seed_rider_name="A", seed_rider_wallet=50000)
    prog_id, drv_id, pool_id = ctx["program_id"], ctx["driver_id"], ctx["pool_id"]
    a = ctx["seed"]
    b = get_success_data(api.create_member(
        {"employer_program_id": prog_id, "full_name": "B", "home_zone": "Z-N",
         "work_zone": "Z-DT", "wallet_balance_cents": 50000}, PA))
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=10.0)
    # Rider A acts (X-User-ID = a) but supplies rider_member_id = b.
    validate_error(api.create_reservation(
        {"trip_id": trip["id"], "rider_member_id": b["id"],
         "expected_trip_version": trip["version"], "seat_count": 1},
        make_rider_headers(a["id"])), ApiErrorId.ERR_FORBIDDEN.value)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    validate_error(api.create_employer_program(
        {"employer_name": "Acme", "hov_discount_pct": 0.50, "employer_match_pct": 0.30,
         "monthly_benefit_cap_cents": 31500, "grh_annual_cap_cents": 20000,
         "grh_per_event_cap_cents": 6000, "subsidy_budget_cents": 1000000}, {}),
        ApiErrorId.ERR_UNAUTHENTICATED.value)
