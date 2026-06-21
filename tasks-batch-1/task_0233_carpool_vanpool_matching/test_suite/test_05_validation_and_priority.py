"""Validation ordering, cross-entity gates, and business-rule guards
(PRD §2.6, §2.8, §3.3, §3.6, §3.9).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_driver_headers, make_rider_headers, make_program_admin_headers,
    setup_active_pool, create_trip, create_reservation,
    setup_rider_with_reliability, create_grh_claim, reimburse_grh_event,
)

PA = make_program_admin_headers()


# ---------------------------------------------------------------------------
# Priority-pair conflicts (PRD §2.8 fixed evaluation order)
# ---------------------------------------------------------------------------
def test_state_check_precedes_wallet_check_on_reserve(api):
    """PRD §2.8: "Sixth, the target resource's own state must permit the requested
    transition, or the request fails with `ERR_INVALID_STATE`."
    PRD §2.8: "The remaining business rules described throughout §3 (reliability
    gate, scheduling overlaps, seat and capacity limits, GRH caps, wallet funding)
    are evaluated after these structural checks."

    A rider with an empty wallet reserves on a CANCELLED trip: both the state check
    and the wallet check would fail, but ERR_INVALID_STATE wins because the trip's
    own-state check is structural and precedes the wallet-funding rule.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reserve_terminal_trip
    """
    ctx = setup_active_pool(api=api, seed_rider_name="Rae", seed_rider_wallet=0)
    drv_id, pool_id = ctx["driver_id"], ctx["pool_id"]
    rider = ctx["seed"]
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=10.0)
    cancelled = validate_success(api.cancel_trip(trip["id"], make_driver_headers(drv_id)))
    trip_v1 = cancelled["version"]
    validate_error(api.create_reservation(
        {"trip_id": trip["id"], "rider_member_id": rider["id"],
         "expected_trip_version": trip_v1, "seat_count": 1, "pay_now": True},
        make_rider_headers(rider["id"])), ApiErrorId.ERR_INVALID_STATE.value)


def test_reliability_gate_precedes_seat_capacity_on_reserve(api):
    """PRD §2.8: "When a request could fail more than one check, the checks are
    evaluated in a fixed priority so that the returned `error_id` is deterministic."
    PRD §2.8: "The remaining business rules described throughout §3 (reliability
    gate, scheduling overlaps, seat and capacity limits, GRH caps, wallet funding)
    are evaluated after these structural checks."

    A rider with reliability 55.0 reserves on a 1-seat trip already fully reserved:
    both the reliability gate and the seat-capacity limit would fail, but the
    reliability gate is listed first so ERR_RELIABILITY_TOO_LOW wins.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_reserve_low_reliability_full_trip
    """
    ctx = setup_rider_with_reliability(target_no_shows=3, api=api, rider_wallet=50000)
    prog_id, drv_id, bad_rider_id = ctx["program_id"], ctx["driver_id"], ctx["rider_id"]
    assert get_success_data(api.get_member(bad_rider_id, PA))["reliability_score"] == 55.0

    good = get_success_data(api.create_member(
        {"employer_program_id": prog_id, "full_name": "Rae Good", "home_zone": "Z-N",
         "work_zone": "Z-DT", "wallet_balance_cents": 50000}, PA))
    veh = get_success_data(api.create_vehicle(
        {"owner_member_id": drv_id, "plate": "CAR-1", "seat_capacity": 1},
        make_driver_headers(drv_id)))
    pool = get_success_data(api.create_pool(
        {"employer_program_id": prog_id, "driver_member_id": drv_id, "vehicle_id": veh["id"],
         "kind": "CARPOOL", "origin_zone": "Z-N", "dest_zone": "Z-DT",
         "departure_days": ["MON", "TUE", "WED", "THU", "FRI"],
         "base_cost_cents": 2000, "per_mile_cents": 120}, make_driver_headers(drv_id)))
    get_success_data(api.create_membership(
        {"pool_id": pool["id"], "rider_member_id": good["id"], "expected_pool_version": pool["version"]},
        make_rider_headers(good["id"])))
    get_success_data(api.activate_pool(pool["id"], make_driver_headers(drv_id)))
    trip = create_trip(pool["id"], drv_id, api=api, departure_at="2026-10-01T15:00:00Z",
                       distance_miles=10.0)
    fill = validate_success(api.create_reservation(
        {"trip_id": trip["id"], "rider_member_id": good["id"],
         "expected_trip_version": trip["version"], "seat_count": 1},
        make_rider_headers(good["id"])), expected_status=201)
    assert fill["reservation_status"] == "RESERVED"
    trip_v1 = get_success_data(api.get_trip(trip["id"], make_driver_headers(drv_id)))["version"]
    assert get_success_data(api.get_trip(trip["id"], make_driver_headers(drv_id)))["seats_reserved"] == 1

    validate_error(api.create_reservation(
        {"trip_id": trip["id"], "rider_member_id": bad_rider_id,
         "expected_trip_version": trip_v1, "seat_count": 1},
        make_rider_headers(bad_rider_id)), ApiErrorId.ERR_RELIABILITY_TOO_LOW.value)


# ---------------------------------------------------------------------------
# Cross-entity gates (PRD §2.8 seventh: ERR_DEPENDENCY_NOT_READY)
# ---------------------------------------------------------------------------
def test_grh_approve_blocked_when_program_frozen(api):
    """PRD §3.9: "A `ProgramAdmin` or `PlatformOps` approves a `REQUESTED` claim only
    when the reimbursing program is `ACTIVE` (a frozen or otherwise non-active
    program blocks approval with `ERR_DEPENDENCY_NOT_READY`)".

    Design: Difficulty/cross_entity_state_dependency/grh_approve_requires_program_active_pair_grh_program
    """
    program = get_success_data(api.create_employer_program(
        {"employer_name": "Acme", "hov_discount_pct": 0.50, "employer_match_pct": 0.30,
         "monthly_benefit_cap_cents": 100000, "grh_annual_cap_cents": 20000,
         "grh_per_event_cap_cents": 6000, "subsidy_budget_cents": 1000000}, PA))
    rider = get_success_data(api.create_member(
        {"employer_program_id": program["id"], "full_name": "Rae", "home_zone": "Z-N",
         "work_zone": "Z-DT", "wallet_balance_cents": 50000}, PA))
    grh = create_grh_claim(rider["id"], program["id"], api=api, claimed_fare_cents=4000,
                           reason_code="ILLNESS")
    frozen = validate_success(api.freeze_employer_program(program["id"], PA))
    assert frozen["status"] == "FROZEN"
    validate_error(api.approve_grh_claim(grh["id"], PA),
                   ApiErrorId.ERR_DEPENDENCY_NOT_READY.value)


# ---------------------------------------------------------------------------
# Seat / capacity / wallet / membership guards
# ---------------------------------------------------------------------------
def test_reserve_exceeding_seats_returns_seats_exhausted(api):
    """PRD §3.6: "the trip's current `seats_reserved` plus the requested `seat_count`
    must not exceed the seat capacity of the trip's pool, or the reservation is
    rejected with `ERR_SEATS_EXHAUSTED`."

    Design: Corner/validations/reserve_exceeding_seats_returns_seats_exhausted
    """
    ctx = setup_active_pool(api=api, seat_capacity=1, pool_kind="CARPOOL",
                            seed_rider_name="G", seed_rider_wallet=50000)
    prog_id, drv_id, pool_id = ctx["program_id"], ctx["driver_id"], ctx["pool_id"]
    g = ctx["seed"]
    h = get_success_data(api.create_member(
        {"employer_program_id": prog_id, "full_name": "H", "home_zone": "Z-N",
         "work_zone": "Z-DT", "wallet_balance_cents": 50000}, PA))
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=10.0)
    validate_success(api.create_reservation(
        {"trip_id": trip["id"], "rider_member_id": g["id"],
         "expected_trip_version": trip["version"], "seat_count": 1},
        make_rider_headers(g["id"])), expected_status=201)
    trip_v1 = get_success_data(api.get_trip(trip["id"], make_driver_headers(drv_id)))["version"]
    validate_error(api.create_reservation(
        {"trip_id": trip["id"], "rider_member_id": h["id"],
         "expected_trip_version": trip_v1, "seat_count": 1},
        make_rider_headers(h["id"])), ApiErrorId.ERR_SEATS_EXHAUSTED.value)


def test_reserve_pay_now_without_wallet_funds_returns_insufficient_wallet(api):
    """PRD §3.6: "When `pay_now` is set, the rider's wallet is charged the
    `estimate_cost_share_cents` and `payment_status` becomes `CHARGED`; the wallet
    must be able to cover that charge, or the reservation is rejected with
    `ERR_INSUFFICIENT_WALLET`."

    Sole rider (N=1) on a 3200-cent trip, wallet only 100.

    Design: Corner/validations/reserve_insufficient_wallet_returns_402
    """
    ctx = setup_active_pool(api=api, base_cost_cents=2000, per_mile_cents=120,
                            seed_rider_name="Rae", seed_rider_wallet=100)
    drv_id, pool_id = ctx["driver_id"], ctx["pool_id"]
    rider = ctx["seed"]
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=10.0)
    validate_error(api.create_reservation(
        {"trip_id": trip["id"], "rider_member_id": rider["id"],
         "expected_trip_version": trip["version"], "seat_count": 1, "pay_now": True},
        make_rider_headers(rider["id"])), ApiErrorId.ERR_INSUFFICIENT_WALLET.value)


def test_duplicate_membership_for_same_rider_on_pool_rejected(api):
    """PRD §3.3: "A rider may not hold two live memberships on the same pool: a
    create that would duplicate an existing `ACTIVE` membership for that rider on
    that pool is rejected with `ERR_MEMBERSHIP_DUPLICATE`."

    Design: Corner/validations/membership_duplicate_returns_conflict
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
    pool = get_success_data(api.create_pool(
        {"employer_program_id": program["id"], "driver_member_id": drv["id"],
         "vehicle_id": veh["id"], "kind": "VANPOOL", "origin_zone": "Z-N", "dest_zone": "Z-DT",
         "departure_days": ["MON", "TUE", "WED", "THU", "FRI"],
         "base_cost_cents": 2000, "per_mile_cents": 120}, make_driver_headers(drv["id"])))
    validate_success(api.create_membership(
        {"pool_id": pool["id"], "rider_member_id": rider["id"],
         "expected_pool_version": pool["version"]}, make_rider_headers(rider["id"])),
        expected_status=201)
    pool_v_after = get_success_data(api.get_pool(pool["id"], make_rider_headers(rider["id"])))["version"]
    validate_error(api.create_membership(
        {"pool_id": pool["id"], "rider_member_id": rider["id"],
         "expected_pool_version": pool_v_after}, make_rider_headers(rider["id"])),
        ApiErrorId.ERR_MEMBERSHIP_DUPLICATE.value)


def test_membership_exceeding_pool_capacity_rejected(api):
    """PRD §3.3: "Joining is also bounded by capacity — the recurring seats requested
    plus the pool's existing `committed_seat_count` must not exceed the pool's
    `seat_capacity`, or the create is rejected with `ERR_POOL_CAPACITY_EXCEEDED`."

    A second distinct rider joining a 1-seat pool already at committed_seat_count 1.

    Design: Corner/validations/pool_membership_over_capacity_returns_pool_capacity_exceeded
    """
    program = get_success_data(api.create_employer_program(
        {"employer_name": "Acme", "hov_discount_pct": 0.50, "employer_match_pct": 0.30,
         "monthly_benefit_cap_cents": 31500, "grh_annual_cap_cents": 20000,
         "grh_per_event_cap_cents": 6000, "subsidy_budget_cents": 1000000}, PA))
    drv = get_success_data(api.create_member(
        {"employer_program_id": program["id"], "full_name": "Dee", "home_zone": "Z-N",
         "work_zone": "Z-DT", "can_drive": True}, PA))
    r1 = get_success_data(api.create_member(
        {"employer_program_id": program["id"], "full_name": "R1", "home_zone": "Z-N",
         "work_zone": "Z-DT"}, PA))
    r2 = get_success_data(api.create_member(
        {"employer_program_id": program["id"], "full_name": "R2", "home_zone": "Z-N",
         "work_zone": "Z-DT"}, PA))
    veh = get_success_data(api.create_vehicle(
        {"owner_member_id": drv["id"], "plate": "CAR-1", "seat_capacity": 1},
        make_driver_headers(drv["id"])))
    pool = get_success_data(api.create_pool(
        {"employer_program_id": program["id"], "driver_member_id": drv["id"],
         "vehicle_id": veh["id"], "kind": "CARPOOL", "origin_zone": "Z-N", "dest_zone": "Z-DT",
         "departure_days": ["MON", "TUE", "WED", "THU", "FRI"],
         "base_cost_cents": 2000, "per_mile_cents": 120}, make_driver_headers(drv["id"])))
    validate_success(api.create_membership(
        {"pool_id": pool["id"], "rider_member_id": r1["id"],
         "expected_pool_version": pool["version"]}, make_rider_headers(r1["id"])),
        expected_status=201)
    pool_v_after = get_success_data(api.get_pool(pool["id"], make_rider_headers(r2["id"])))["version"]
    validate_error(api.create_membership(
        {"pool_id": pool["id"], "rider_member_id": r2["id"],
         "expected_pool_version": pool_v_after}, make_rider_headers(r2["id"])),
        ApiErrorId.ERR_POOL_CAPACITY_EXCEEDED.value)


# ---------------------------------------------------------------------------
# GRH caps (PRD §3.9)
# ---------------------------------------------------------------------------
def test_grh_approve_blocked_by_annual_cap(api):
    """PRD §3.9: "the member's `grh_year_used_cents` is strictly below the program's
    `grh_annual_cap_cents`; approval moves the claim to `APPROVED` and moves no
    money."
    PRD §3.9: "A breach of the event-count cap is rejected with `ERR_GRH_EVENT_CAP`,
    and a breach of the annual cap with `ERR_GRH_ANNUAL_CAP`."

    After reimbursing the full 20000 annual cap, a fresh claim's approve is blocked.

    Design: Corner/validations/grh_annual_cap_blocks_approve
    """
    program = get_success_data(api.create_employer_program(
        {"employer_name": "Acme", "hov_discount_pct": 0.50, "employer_match_pct": 0.30,
         "monthly_benefit_cap_cents": 31500, "grh_annual_cap_cents": 20000,
         "grh_per_event_cap_cents": 6000, "subsidy_budget_cents": 1000000,
         "grh_max_events_per_year": 10}, PA))
    rider = get_success_data(api.create_member(
        {"employer_program_id": program["id"], "full_name": "Rae", "home_zone": "Z-N",
         "work_zone": "Z-DT", "wallet_balance_cents": 0}, PA))
    for fare in (6000, 6000, 6000, 2000):
        reimburse_grh_event(rider["id"], program["id"], fare, api=api)
    assert get_success_data(api.get_member(rider["id"], PA))["grh_year_used_cents"] == 20000

    g5 = create_grh_claim(rider["id"], program["id"], api=api, claimed_fare_cents=3000,
                          reason_code="ILLNESS")
    validate_error(api.approve_grh_claim(g5["id"], PA), ApiErrorId.ERR_GRH_ANNUAL_CAP.value)


def test_grh_approve_blocked_by_event_cap(api):
    """PRD §3.9: "the member's `grh_year_event_count` is strictly below the program's
    `grh_max_events_per_year`, and the member's `grh_year_used_cents` is strictly
    below the program's `grh_annual_cap_cents`; approval moves the claim to
    `APPROVED` and moves no money."
    PRD §3.9: "A breach of the event-count cap is rejected with `ERR_GRH_EVENT_CAP`,
    and a breach of the annual cap with `ERR_GRH_ANNUAL_CAP`."

    With grh_max_events_per_year 1 and one REIMBURSED event, a second approve fails.

    Design: Corner/errors/grh_event_cap_error_triggerable
    """
    program = get_success_data(api.create_employer_program(
        {"employer_name": "Acme", "hov_discount_pct": 0.50, "employer_match_pct": 0.30,
         "monthly_benefit_cap_cents": 31500, "grh_annual_cap_cents": 20000,
         "grh_per_event_cap_cents": 6000, "subsidy_budget_cents": 1000000,
         "grh_max_events_per_year": 1}, PA))
    rider = get_success_data(api.create_member(
        {"employer_program_id": program["id"], "full_name": "Rae", "home_zone": "Z-N",
         "work_zone": "Z-DT", "wallet_balance_cents": 0}, PA))
    reimburse_grh_event(rider["id"], program["id"], 3000, api=api)
    assert get_success_data(api.get_member(rider["id"], PA))["grh_year_event_count"] == 1

    g2 = create_grh_claim(rider["id"], program["id"], api=api, claimed_fare_cents=3000,
                          reason_code="ILLNESS")
    validate_error(api.approve_grh_claim(g2["id"], PA), ApiErrorId.ERR_GRH_EVENT_CAP.value)


# ---------------------------------------------------------------------------
# OCC stale-version guards (PRD §2.6)
# ---------------------------------------------------------------------------
def test_reservation_create_with_stale_trip_version_rejected(api):
    """PRD §2.6: "If that value does not equal the trip's current `version` — for
    instance because another writer has already created a reservation that consumed
    the remaining seat and advanced `Trip.version` through the `seats_reserved`
    recompute — the create is rejected with `ERR_STALE_TRIP_VERSION` at HTTP 412".

    Design: Corner/errors/stale_trip_version_error_triggerable
    """
    ctx = setup_active_pool(api=api, seed_rider_name="R1", seed_rider_wallet=50000)
    prog_id, drv_id, pool_id = ctx["program_id"], ctx["driver_id"], ctx["pool_id"]
    r1 = ctx["seed"]
    r2 = get_success_data(api.create_member(
        {"employer_program_id": prog_id, "full_name": "R2", "home_zone": "Z-N",
         "work_zone": "Z-DT", "wallet_balance_cents": 50000}, PA))
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=10.0)
    trip_v0 = trip["version"]
    validate_success(api.create_reservation(
        {"trip_id": trip["id"], "rider_member_id": r1["id"],
         "expected_trip_version": trip_v0, "seat_count": 1},
        make_rider_headers(r1["id"])), expected_status=201)
    # Replay the pre-bump version: the prior reservation advanced Trip.version.
    validate_error(api.create_reservation(
        {"trip_id": trip["id"], "rider_member_id": r2["id"],
         "expected_trip_version": trip_v0, "seat_count": 1},
        make_rider_headers(r2["id"])), ApiErrorId.ERR_STALE_TRIP_VERSION.value)


def test_membership_create_with_stale_pool_version_rejected(api):
    """PRD §2.6: "If that value does not equal the pool's current `version` — for
    instance because another writer has already committed the last recurring seat
    and advanced `Pool.version` through the `committed_seat_count` recompute — the
    create is rejected with `ERR_STALE_POOL_VERSION` at HTTP 412".

    Design: Corner/cross_cutting_complexity_layers/occ_membership_stale_pool_version_returns_412
    """
    program = get_success_data(api.create_employer_program(
        {"employer_name": "Acme", "hov_discount_pct": 0.50, "employer_match_pct": 0.30,
         "monthly_benefit_cap_cents": 31500, "grh_annual_cap_cents": 20000,
         "grh_per_event_cap_cents": 6000, "subsidy_budget_cents": 1000000}, PA))
    drv = get_success_data(api.create_member(
        {"employer_program_id": program["id"], "full_name": "Dee", "home_zone": "Z-N",
         "work_zone": "Z-DT", "can_drive": True}, PA))
    r1 = get_success_data(api.create_member(
        {"employer_program_id": program["id"], "full_name": "R1", "home_zone": "Z-N",
         "work_zone": "Z-DT"}, PA))
    r2 = get_success_data(api.create_member(
        {"employer_program_id": program["id"], "full_name": "R2", "home_zone": "Z-N",
         "work_zone": "Z-DT"}, PA))
    veh = get_success_data(api.create_vehicle(
        {"owner_member_id": drv["id"], "plate": "VAN-1", "seat_capacity": 6},
        make_driver_headers(drv["id"])))
    pool = get_success_data(api.create_pool(
        {"employer_program_id": program["id"], "driver_member_id": drv["id"],
         "vehicle_id": veh["id"], "kind": "VANPOOL", "origin_zone": "Z-N", "dest_zone": "Z-DT",
         "departure_days": ["MON", "TUE", "WED", "THU", "FRI"],
         "base_cost_cents": 2000, "per_mile_cents": 120}, make_driver_headers(drv["id"])))
    pool_v0 = pool["version"]
    validate_success(api.create_membership(
        {"pool_id": pool["id"], "rider_member_id": r1["id"], "expected_pool_version": pool_v0},
        make_rider_headers(r1["id"])), expected_status=201)
    # Replay the pre-bump pool version.
    validate_error(api.create_membership(
        {"pool_id": pool["id"], "rider_member_id": r2["id"], "expected_pool_version": pool_v0},
        make_rider_headers(r2["id"])), ApiErrorId.ERR_STALE_POOL_VERSION.value)
