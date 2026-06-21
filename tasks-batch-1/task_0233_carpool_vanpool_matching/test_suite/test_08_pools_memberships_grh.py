"""Pool/trip/GRH state transitions, preconditions, terminal lockdown, and
membership lifecycle (PRD §3.3, §3.5, §3.9).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_driver_headers, make_rider_headers, make_program_admin_headers,
    setup_active_pool, setup_completed_single_rider_trip, create_grh_claim,
)

PA = make_program_admin_headers()


def test_activate_already_active_pool_returns_invalid_state(api):
    """PRD §3.3: "Activating a `FORMING` pool requires that at least one `ACTIVE`
    membership exists ... the pool moves to `ACTIVE` and its `version` increments."

    Re-activating an already-ACTIVE pool is not a permitted transition, so it
    returns ERR_INVALID_STATE.

    Design: Corner/state_machines/activate_pool_from_active_returns_invalid_state
    """
    ctx = setup_active_pool(api=api)
    validate_error(api.activate_pool(ctx["pool_id"], make_driver_headers(ctx["driver_id"])),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_activate_forming_pool_without_membership_returns_invalid_state(api):
    """PRD §3.3: "Activating a `FORMING` pool requires that at least one `ACTIVE`
    membership exists (so `committed_seat_count` is at least 1)".

    A FORMING pool with zero memberships fails the precondition.

    Design: Corner/state_machines/activate_forming_pool_with_no_membership_returns_invalid_state
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
    pool = get_success_data(api.create_pool(
        {"employer_program_id": program["id"], "driver_member_id": drv["id"],
         "vehicle_id": veh["id"], "kind": "VANPOOL", "origin_zone": "Z-N", "dest_zone": "Z-DT",
         "departure_days": ["MON", "TUE", "WED", "THU", "FRI"],
         "base_cost_cents": 2000, "per_mile_cents": 120}, make_driver_headers(drv["id"])))
    validate_error(api.activate_pool(pool["id"], make_driver_headers(drv["id"])),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_completed_trip_is_terminal_locked(api):
    """PRD §3.5: "Cancelling a trip is permitted from `SCHEDULED` (by a `Driver`,
    `ProgramAdmin`, `PlatformOps`, or the system as part of a pool cascade) and from
    `BOARDING` (by a `Driver`, `ProgramAdmin`, or `PlatformOps`)."

    A COMPLETED trip is terminal, so cancel is not a permitted transition and
    returns ERR_INVALID_STATE.

    Design: Corner/state_machines/cancel_completed_trip_terminal_lockdown
    """
    ctx = setup_completed_single_rider_trip(api=api, hov_lane_used_create=False,
                                            hov_lane_used_complete=False)
    assert ctx["trip"]["status"] == "COMPLETED"
    validate_error(api.cancel_trip(ctx["trip_id"], make_driver_headers(ctx["driver_id"])),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_grh_deny_sets_denial_reason_and_moves_no_money(api):
    """PRD §3.9: "a `REQUESTED` claim may be denied: the adjudicator sets
    `denial_reason` from the request body (one of `ANNUAL_CAP`, `EVENT_CAP`, or
    `NOT_ELIGIBLE`) and the claim moves to the terminal `DENIED` state with no money
    moved and no ledger entry."

    Design: Corner/state_machines/grh_branch_deny_sets_denial_reason
    """
    program = get_success_data(api.create_employer_program(
        {"employer_name": "Acme", "hov_discount_pct": 0.50, "employer_match_pct": 0.30,
         "monthly_benefit_cap_cents": 31500, "grh_annual_cap_cents": 20000,
         "grh_per_event_cap_cents": 6000, "subsidy_budget_cents": 1000000}, PA))
    rider = get_success_data(api.create_member(
        {"employer_program_id": program["id"], "full_name": "Rae", "home_zone": "Z-N",
         "work_zone": "Z-DT", "wallet_balance_cents": 1000}, PA))
    grh = create_grh_claim(rider["id"], program["id"], api=api, claimed_fare_cents=4000,
                           reason_code="OVERTIME")
    denied = validate_success(api.deny_grh_claim(grh["id"], {"denial_reason": "NOT_ELIGIBLE"}, PA))
    assert denied["status"] == "DENIED"
    assert denied["denial_reason"] == "NOT_ELIGIBLE"
    assert get_success_data(api.get_member(rider["id"], PA))["wallet_balance_cents"] == 1000


def test_end_membership_releases_committed_seat(api):
    """PRD §3.3: "A membership can later be ended (by the joining rider, the pool's
    driver, or `PlatformOps`), moving its `status` to `ENDED` and recomputing the
    pool's `committed_seat_count`."

    Ending the only ACTIVE membership drops committed_seat_count from 1 to 0.

    Design: Corner/endpoints/end_membership_releases_committed_seat
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
    mem = get_success_data(api.create_membership(
        {"pool_id": pool["id"], "rider_member_id": rider["id"],
         "expected_pool_version": pool["version"]}, make_rider_headers(rider["id"])))
    get_success_data(api.activate_pool(pool["id"], make_driver_headers(drv["id"])))

    ended = validate_success(api.end_membership(mem["id"], make_rider_headers(rider["id"])))
    assert ended["status"] == "ENDED"
    pool_after = get_success_data(api.get_pool(pool["id"], make_rider_headers(rider["id"])))
    assert pool_after["committed_seat_count"] == 0
