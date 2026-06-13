"""Reservation pricing: seasonal base, borrow surcharge, exchange credits.

Difficulty: combinatorial_formula (borrow branch), boundary_precision (II divisor),
resource_temporal_overlap (borrow overflow). Corner: computed points_value,
RCI credit divisor, HELD initial state, borrow-ceiling rejection.
"""
from test_helpers import (
    get_success_data, validate_success, validate_error,
    ApiErrorId,
    create_resort, create_owner, create_inventory_unit, create_active_contract,
    create_confirmed_reservation, get_points_account,
    create_reservation_payload, deposit_exchange_payload,
    setup_active_contract_with_unit,
    make_owner_headers, TEST_USERS,
)

_RM = TEST_USERS["resort_manager_headers"]


# =========================================================================== #
# Difficulty: combinatorial_formula
# =========================================================================== #
def test_reservation_borrows_shortfall_with_surcharge(api):
    """PRD §3.4: "If instead the discounted cost exceeds available points, the shortfall — the
    discounted cost minus the available points — must be borrowed from the future:
    `borrowed_points` is set to that shortfall, a surcharge equal to the shortfall
    multiplied by the resort's `borrow_surcharge_pct` and rounded up to the next
    whole point is computed, and `points_cost` becomes the discounted cost plus that
    surcharge."
    PRD §3.4: "The borrow source is the contract's account for `use_year` plus one; the reservation
    records the funding account as `source_use_year_account_id` and, when borrowing
    occurs, the borrowed-from account as `borrow_source_account_id`."

    Design: Difficulty/combinatorial_formula/reservation_points_cost_nonlinear_borrow_branch
    """
    resort = create_resort(borrow_surcharge_pct=0.10)
    owner = create_owner(resort["id"])
    unit = create_inventory_unit(resort["id"], unit_label="Villa Plat", week_number=10, season="PLATINUM")
    contract = create_active_contract(resort["id"], owner["id"], annual_points_allotment=1000)

    acct = get_points_account(contract["id"], 2026, owner["id"])
    headers = make_owner_headers(owner["id"])
    resp = api.create_reservation(
        create_reservation_payload(contract["id"], unit["id"], 2026, acct["version"]), headers)
    data = validate_success(resp, 201)

    # base = round_half_up(1000 * 1.50) = 1500; avail 1000; shortfall 500;
    # surcharge = ceil(500 * 0.10) = 50; points_cost = 1500 + 50 = 1550.
    assert data["points_cost"] == 1550, f"expected points_cost 1550, got {data['points_cost']}"
    assert data["borrowed_points"] == 500, f"expected borrowed_points 500, got {data['borrowed_points']}"
    assert data["borrow_source_account_id"], "borrow_source_account_id must be set (the 2027 account)"


def test_reservation_borrow_within_balance_baseline(api):
    """PRD §3.4: "If the discounted cost is less than or equal to the source account's
    `available_points`, then `borrowed_points` is 0 and `points_cost` equals the
    discounted cost; no surcharge applies and the next year's account is untouched."

    Design: Difficulty/combinatorial_formula/reservation_points_cost_nonlinear_borrow_branch
    """
    # Same PLATINUM unit but enough allotment so no borrow occurs -> the within-balance branch.
    resort = create_resort(borrow_surcharge_pct=0.10)
    owner = create_owner(resort["id"])
    unit = create_inventory_unit(resort["id"], unit_label="Villa Plat", week_number=11, season="PLATINUM")
    contract = create_active_contract(resort["id"], owner["id"], annual_points_allotment=5000)

    acct = get_points_account(contract["id"], 2026, owner["id"])
    headers = make_owner_headers(owner["id"])
    resp = api.create_reservation(
        create_reservation_payload(contract["id"], unit["id"], 2026, acct["version"]), headers)
    data = validate_success(resp, 201)

    # base = round_half_up(1000 * 1.50) = 1500 <= 5000 avail -> no borrow, no surcharge.
    assert data["points_cost"] == 1500, f"expected points_cost 1500, got {data['points_cost']}"
    assert data["borrowed_points"] == 0, f"expected borrowed_points 0, got {data['borrowed_points']}"


# =========================================================================== #
# Difficulty: boundary_precision_check — exchange credit divisor (II)
# =========================================================================== #
def test_exchange_credit_ii_divisor_boundary_at_120(api):
    """PRD §3.6: "Its `exchange_credits` are granted by network: the reservation's `points_cost` is
    divided by the network's credit divisor — 100 for `RCI`, 120 for `II` — and
    floored to a whole number of credits. At the boundary, a `points_cost` exactly
    equal to the divisor yields exactly one credit, while one point below the
    divisor yields zero."

    Design: Difficulty/boundary_precision_check/exchange_credit_divisor_boundary_ii
    """
    # base 120 so GOLD unit (x1.00) costs exactly 120 points.
    resort = create_resort(points_per_week_base=120)
    owner = create_owner(resort["id"])
    unit = create_inventory_unit(resort["id"], unit_label="Villa Gold", week_number=15, season="GOLD")
    contract = create_active_contract(resort["id"], owner["id"], annual_points_allotment=5000)

    confirmed = create_confirmed_reservation(resort, owner, contract, unit)
    assert confirmed["points_cost"] == 120, f"expected points_cost 120, got {confirmed['points_cost']}"

    headers = make_owner_headers(owner["id"])
    resp = api.deposit_exchange(confirmed["id"], deposit_exchange_payload("II"), headers)
    data = validate_success(resp, 201)
    assert data["exchange_credits"] == 1, f"floor(120/120) == 1, got {data['exchange_credits']}"


def test_exchange_credit_ii_divisor_one_below_yields_zero(api):
    """PRD §3.6: "the reservation's `points_cost` is divided by the network's credit divisor — 100 for
    `RCI`, 120 for `II` — and floored to a whole number of credits. At the boundary,
    a `points_cost` exactly equal to the divisor yields exactly one credit, while
    one point below the divisor yields zero."

    Design: Difficulty/boundary_precision_check/exchange_credit_divisor_boundary_ii
    """
    # base 119 so GOLD unit (x1.00) costs exactly 119 points -> floor(119/120)=0.
    resort = create_resort(points_per_week_base=119)
    owner = create_owner(resort["id"])
    unit = create_inventory_unit(resort["id"], unit_label="Villa Gold", week_number=16, season="GOLD")
    contract = create_active_contract(resort["id"], owner["id"], annual_points_allotment=5000)

    confirmed = create_confirmed_reservation(resort, owner, contract, unit)
    assert confirmed["points_cost"] == 119, f"expected points_cost 119, got {confirmed['points_cost']}"

    headers = make_owner_headers(owner["id"])
    resp = api.deposit_exchange(confirmed["id"], deposit_exchange_payload("II"), headers)
    data = validate_success(resp, 201)
    assert data["exchange_credits"] == 0, f"floor(119/120) == 0, got {data['exchange_credits']}"


# =========================================================================== #
# Difficulty: resource_temporal_overlap — borrow overflow (aggregate capacity)
# =========================================================================== #
def test_reservation_borrow_exceeds_next_year_available_rejected(api):
    """PRD §3.4: "The borrowed amount may not exceed the borrow-source account's `available_points`;
    if it would, the reservation is rejected with `ERR_INSUFFICIENT_POINTS`."

    Design: Difficulty/resource_temporal_overlap/points_account_aggregate_capacity_borrow_overflow
    """
    # base 10000 -> PLATINUM unit costs round_half_up(10000*1.5)=15000. Allotment 1000
    # in 2026; shortfall 14000 > lazily-created 2027 account's allotment 1000 available.
    resort = create_resort(points_per_week_base=10000, borrow_surcharge_pct=0.10)
    owner = create_owner(resort["id"])
    unit = create_inventory_unit(resort["id"], unit_label="Villa Plat", week_number=45, season="PLATINUM")
    contract = create_active_contract(resort["id"], owner["id"], annual_points_allotment=1000)

    acct = get_points_account(contract["id"], 2026, owner["id"])
    headers = make_owner_headers(owner["id"])
    resp = api.create_reservation(
        create_reservation_payload(contract["id"], unit["id"], 2026, acct["version"]), headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS.value)

    # No reservation row created on overflow.
    data, _meta = _list(api.list_reservations(headers, params={"contract_id": contract["id"]}))
    assert data == [], f"expected no reservations after overflow, got {len(data)}"


def test_reservation_borrow_at_exact_ceiling_succeeds(api):
    """PRD §3.4: "The borrowed amount may not exceed the borrow-source account's `available_points`;
    if it would, the reservation is rejected with `ERR_INSUFFICIENT_POINTS`."
    PRD §3.4: "`borrowed_points` is set to that shortfall".

    Design: Difficulty/resource_temporal_overlap/points_account_aggregate_capacity_borrow_overflow
    """
    # PLATINUM cost 1500; 2026 allotment 1000 -> shortfall 500; the lazily-created
    # 2027 account has allotment 1000 >= 500, so the borrow is at/under the
    # ceiling and the reservation succeeds.
    resort = create_resort(points_per_week_base=1000, borrow_surcharge_pct=0.10)
    owner = create_owner(resort["id"])
    unit = create_inventory_unit(resort["id"], unit_label="Villa Plat", week_number=46, season="PLATINUM")
    contract = create_active_contract(resort["id"], owner["id"], annual_points_allotment=1000)
    acct = get_points_account(contract["id"], 2026, owner["id"])
    headers = make_owner_headers(owner["id"])
    resp = api.create_reservation(
        create_reservation_payload(contract["id"], unit["id"], 2026, acct["version"]), headers)
    data = validate_success(resp, 201)
    assert data["borrowed_points"] == 500, f"borrowed_points 500, got {data['borrowed_points']}"
    assert data["status"] == "HELD", f"reservation HELD, got {data['status']}"


def _list(response):
    body = response.json()
    return body["data"], body.get("meta", {})


# =========================================================================== #
# Corner: entities / state_machines / calculations
# =========================================================================== #
def test_inventory_unit_points_value_computed_from_season(api):
    """PRD §3.1: "its `points_value` is computed at creation: it is the resort's
    `points_per_week_base` multiplied by the season multiplier — 1.50 for
    `PLATINUM`, 1.00 for `GOLD`, and 0.60 for `SILVER` — with the product rounded
    half up to a whole number of points."

    Design: Corner/entities/inventory_unit_points_value_computed_ignores_input
    """
    resort = create_resort(points_per_week_base=1000)
    resp = api.create_inventory_unit(
        {"resort_id": resort["id"], "unit_label": "Villa Silver", "week_number": 5, "season": "SILVER"},
        _RM)
    data = validate_success(resp, 201)
    assert data["points_value"] == 600, f"round_half_up(1000*0.60)==600, got {data['points_value']}"
    assert data["status"] == "AVAILABLE", f"new unit must be AVAILABLE, got {data['status']}"


def test_reservation_starts_held_with_computed_cost(api):
    """PRD §3.4: "A new reservation is created in `HELD` status, and its cost is priced immediately
    and pinned thereafter."
    PRD §3.4: "If the discounted cost is less than or equal to the source account's
    `available_points`, then `borrowed_points` is 0 and `points_cost` equals the
    discounted cost; no surcharge applies and the next year's account is untouched."

    Design: Corner/state_machines/reservation_starts_in_held_initial_state
    """
    resort, owner, contract, unit = setup_active_contract_with_unit(
        season="GOLD", week_number=9)
    acct = get_points_account(contract["id"], 2026, owner["id"])
    headers = make_owner_headers(owner["id"])
    resp = api.create_reservation(
        create_reservation_payload(contract["id"], unit["id"], 2026, acct["version"]), headers)
    data = validate_success(resp, 201)
    assert data["status"] == "HELD", f"expected HELD, got {data['status']}"
    # GOLD on base 1000 = 1000 points; allotment 5000 so no borrow.
    assert data["points_cost"] == 1000, f"expected points_cost 1000, got {data['points_cost']}"
    assert data["borrowed_points"] == 0, f"expected borrowed_points 0, got {data['borrowed_points']}"


def test_exchange_credit_rci_divisor_floor(api):
    """PRD §3.6: "the reservation's `points_cost` is divided by the network's credit divisor — 100 for
    `RCI`, 120 for `II` — and floored to a whole number of credits."

    Design: Corner/calculations/exchange_credit_rci_divisor_correct
    """
    resort, owner, contract, unit = setup_active_contract_with_unit(
        season="GOLD", week_number=18)
    confirmed = create_confirmed_reservation(resort, owner, contract, unit)
    headers = make_owner_headers(owner["id"])
    resp = api.deposit_exchange(confirmed["id"], deposit_exchange_payload("RCI"), headers)
    data = validate_success(resp, 201)
    # GOLD base 1000 -> points_cost 1000; floor(1000/100) = 10.
    assert data["exchange_credits"] == 10, f"floor(1000/100)==10, got {data['exchange_credits']}"
    assert data["status"] == "DEPOSITED", f"expected DEPOSITED, got {data['status']}"
    reserv = get_success_data(api.get_reservation(confirmed["id"], headers))
    assert reserv["status"] == "DEPOSITED_TO_EXCHANGE", \
        f"reservation should be DEPOSITED_TO_EXCHANGE, got {reserv['status']}"
