"""Rider-to-pool matching: scoring, the cyclic reject/re-match loop, confirm
membership creation, and the no-candidate fallback (PRD §3.4).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_driver_headers, make_rider_headers, make_program_admin_headers,
)

PA = make_program_admin_headers()


def _make_driver(program_id, name):
    return get_success_data(api_create_member(program_id, name, can_drive=True))


def api_create_member(program_id, name, **kw):
    from test_helpers import api_client
    payload = {"employer_program_id": program_id, "full_name": name,
               "home_zone": "Z-N", "work_zone": "Z-DT"}
    payload.update(kw)
    return api_client.create_member(payload, PA)


def test_match_request_cyclic_reject_returns_to_open_and_rematches_next_pool(api):
    """PRD §3.4: "Each qualifying candidate is scored as ten times the number of
    needed days, plus one times the seat room (the pool's `seat_capacity` minus its
    `committed_seat_count`), plus five hundredths times the driving member's
    `reliability_score`, with that weighted sum rounded half-up to two decimal
    places."
    PRD §3.4: "Rejecting clears `matched_pool_id` and `match_score`, returns the
    request to `OPEN`, and records the rejected pool in the exclusion set so a later
    match never re-selects it."

    PoolA (cap 6, committed 1, driver reliability 100) scores 10*5 + 1*5 + 0.05*100
    == 60.00 and is matched first; after reject the request returns to OPEN and a
    second match selects PoolB.

    Design: Difficulty/non_linear_state_machine/matchrequest_cyclic_matched_to_open_revert
    """
    program = get_success_data(api.create_employer_program(
        {"employer_name": "Acme", "hov_discount_pct": 0.50, "employer_match_pct": 0.30,
         "monthly_benefit_cap_cents": 100000, "grh_annual_cap_cents": 20000,
         "grh_per_event_cap_cents": 6000, "subsidy_budget_cents": 1000000}, PA))
    drv_a = get_success_data(api_create_member(program["id"], "DrvA", can_drive=True))
    drv_b = get_success_data(api_create_member(program["id"], "DrvB", can_drive=True))
    fillers = [get_success_data(api_create_member(program["id"], f"Filler{i}")) for i in (1, 2, 3)]
    rider = get_success_data(api_create_member(program["id"], "Rae"))

    veh_a = get_success_data(api.create_vehicle(
        {"owner_member_id": drv_a["id"], "plate": "VAN-A", "seat_capacity": 6},
        make_driver_headers(drv_a["id"])))
    veh_b = get_success_data(api.create_vehicle(
        {"owner_member_id": drv_b["id"], "plate": "VAN-B", "seat_capacity": 4},
        make_driver_headers(drv_b["id"])))
    pool_a = get_success_data(api.create_pool(
        {"employer_program_id": program["id"], "driver_member_id": drv_a["id"],
         "vehicle_id": veh_a["id"], "kind": "VANPOOL", "origin_zone": "Z-N", "dest_zone": "Z-DT",
         "departure_days": ["MON", "TUE", "WED", "THU", "FRI"],
         "base_cost_cents": 2000, "per_mile_cents": 120}, make_driver_headers(drv_a["id"])))
    pool_b = get_success_data(api.create_pool(
        {"employer_program_id": program["id"], "driver_member_id": drv_b["id"],
         "vehicle_id": veh_b["id"], "kind": "VANPOOL", "origin_zone": "Z-N", "dest_zone": "Z-DT",
         "departure_days": ["MON", "TUE", "WED", "THU", "FRI"],
         "base_cost_cents": 2000, "per_mile_cents": 120}, make_driver_headers(drv_b["id"])))

    # PoolA: one seed membership (committed 1, seat_room 5).
    get_success_data(api.create_membership(
        {"pool_id": pool_a["id"], "rider_member_id": fillers[0]["id"],
         "expected_pool_version": pool_a["version"]}, make_rider_headers(fillers[0]["id"])))
    # PoolB: two seed memberships (committed 2, seat_room 2).
    get_success_data(api.create_membership(
        {"pool_id": pool_b["id"], "rider_member_id": fillers[1]["id"],
         "expected_pool_version": pool_b["version"]}, make_rider_headers(fillers[1]["id"])))
    pool_b_v1 = get_success_data(api.get_pool(pool_b["id"], make_rider_headers(fillers[2]["id"])))["version"]
    get_success_data(api.create_membership(
        {"pool_id": pool_b["id"], "rider_member_id": fillers[2]["id"],
         "expected_pool_version": pool_b_v1}, make_rider_headers(fillers[2]["id"])))

    get_success_data(api.activate_pool(pool_a["id"], make_driver_headers(drv_a["id"])))
    get_success_data(api.activate_pool(pool_b["id"], make_driver_headers(drv_b["id"])))

    mr = get_success_data(api.create_match_request(
        {"rider_member_id": rider["id"], "origin_zone": "Z-N", "dest_zone": "Z-DT",
         "needed_days": ["MON", "TUE", "WED", "THU", "FRI"],
         "earliest_departure_min": 480, "latest_departure_min": 600},
        make_rider_headers(rider["id"])))

    matched = validate_success(api.match_match_request(mr["id"], make_rider_headers(rider["id"])))
    assert matched["matched_pool_id"] == pool_a["id"]
    assert matched["match_score"] == 60.0
    assert matched["status"] == "MATCHED"

    reverted = validate_success(api.reject_match_request(mr["id"], make_rider_headers(rider["id"])))
    assert reverted["status"] == "OPEN"

    rematched = validate_success(api.match_match_request(mr["id"], make_rider_headers(rider["id"])))
    assert rematched["matched_pool_id"] == pool_b["id"]
    assert rematched["status"] == "MATCHED"


def test_confirm_match_request_creates_membership_and_bumps_committed_seat_count(api):
    """PRD §3.4: "it creates an `ACTIVE` membership for the rider on the matched pool
    with `recurring_seats` of 1, recomputes the matched pool's
    `committed_seat_count` (adding the one new seat), and moves the request to the
    terminal `CONFIRMED` state."

    Design: Corner/state_machines/confirm_match_request_creates_membership_and_bumps_committed
    """
    program = get_success_data(api.create_employer_program(
        {"employer_name": "Acme", "hov_discount_pct": 0.50, "employer_match_pct": 0.30,
         "monthly_benefit_cap_cents": 31500, "grh_annual_cap_cents": 20000,
         "grh_per_event_cap_cents": 6000, "subsidy_budget_cents": 1000000}, PA))
    drv = get_success_data(api_create_member(program["id"], "Dee", can_drive=True))
    seed = get_success_data(api_create_member(program["id"], "Seed"))
    rider = get_success_data(api_create_member(program["id"], "Rae"))
    veh = get_success_data(api.create_vehicle(
        {"owner_member_id": drv["id"], "plate": "VAN-1", "seat_capacity": 6},
        make_driver_headers(drv["id"])))
    pool = get_success_data(api.create_pool(
        {"employer_program_id": program["id"], "driver_member_id": drv["id"],
         "vehicle_id": veh["id"], "kind": "VANPOOL", "origin_zone": "Z-N", "dest_zone": "Z-DT",
         "departure_days": ["MON", "TUE", "WED", "THU", "FRI"],
         "base_cost_cents": 2000, "per_mile_cents": 120}, make_driver_headers(drv["id"])))
    get_success_data(api.create_membership(
        {"pool_id": pool["id"], "rider_member_id": seed["id"],
         "expected_pool_version": pool["version"]}, make_rider_headers(seed["id"])))
    get_success_data(api.activate_pool(pool["id"], make_driver_headers(drv["id"])))

    mr = get_success_data(api.create_match_request(
        {"rider_member_id": rider["id"], "origin_zone": "Z-N", "dest_zone": "Z-DT",
         "needed_days": ["MON", "TUE", "WED", "THU", "FRI"],
         "earliest_departure_min": 480, "latest_departure_min": 600},
        make_rider_headers(rider["id"])))
    get_success_data(api.match_match_request(mr["id"], make_rider_headers(rider["id"])))
    confirmed = validate_success(api.confirm_match_request(mr["id"], make_rider_headers(rider["id"])))
    assert confirmed["status"] == "CONFIRMED"
    pool_after = get_success_data(api.get_pool(pool["id"], make_rider_headers(rider["id"])))
    assert pool_after["committed_seat_count"] == 2


def test_match_with_no_eligible_pool_returns_no_match_and_stays_open(api):
    """PRD §3.4: "If no candidate qualifies, the request stays `OPEN` and the matcher
    returns `ERR_NO_MATCH_FOUND`."

    The only ACTIVE pool serves Z-DT while the request seeks Z-W, so no candidate
    qualifies.

    Design: Corner/validations/no_match_found_returns_422_status_stays_open
    """
    program = get_success_data(api.create_employer_program(
        {"employer_name": "Acme", "hov_discount_pct": 0.50, "employer_match_pct": 0.30,
         "monthly_benefit_cap_cents": 31500, "grh_annual_cap_cents": 20000,
         "grh_per_event_cap_cents": 6000, "subsidy_budget_cents": 1000000}, PA))
    drv = get_success_data(api_create_member(program["id"], "Dee", can_drive=True))
    seed = get_success_data(api_create_member(program["id"], "Seed"))
    rider = get_success_data(api_create_member(program["id"], "Rae", work_zone="Z-W"))
    veh = get_success_data(api.create_vehicle(
        {"owner_member_id": drv["id"], "plate": "VAN-1", "seat_capacity": 6},
        make_driver_headers(drv["id"])))
    pool = get_success_data(api.create_pool(
        {"employer_program_id": program["id"], "driver_member_id": drv["id"],
         "vehicle_id": veh["id"], "kind": "VANPOOL", "origin_zone": "Z-N", "dest_zone": "Z-DT",
         "departure_days": ["MON", "TUE", "WED", "THU", "FRI"],
         "base_cost_cents": 2000, "per_mile_cents": 120}, make_driver_headers(drv["id"])))
    get_success_data(api.create_membership(
        {"pool_id": pool["id"], "rider_member_id": seed["id"],
         "expected_pool_version": pool["version"]}, make_rider_headers(seed["id"])))
    get_success_data(api.activate_pool(pool["id"], make_driver_headers(drv["id"])))

    mr = get_success_data(api.create_match_request(
        {"rider_member_id": rider["id"], "origin_zone": "Z-N", "dest_zone": "Z-W",
         "needed_days": ["MON"], "earliest_departure_min": 480, "latest_departure_min": 600},
        make_rider_headers(rider["id"])))
    validate_error(api.match_match_request(mr["id"], make_rider_headers(rider["id"])),
                   ApiErrorId.ERR_NO_MATCH_FOUND.value)
    after = get_success_data(api.get_match_request(mr["id"], make_rider_headers(rider["id"])))
    assert after["status"] == "OPEN"
