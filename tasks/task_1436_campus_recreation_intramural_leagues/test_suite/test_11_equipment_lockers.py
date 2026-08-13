"""Equipment checkouts: late-fee boundary, unit conservation, fiscal gate and
its priority, terminal lockdown; locker rent/release cycle (PRD §2.8, §2.9,
§3.9)."""
from test_helpers import (
    FACILITY_MANAGER,
    ApiErrorId,
    api_client,
    create_checkout,
    create_eligible_member,
    create_locker,
    create_pool,
    file_injury,
    make_member_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

DUE_AT = "2026-10-01T17:00:00Z"


def _member_and_pool(email="mm@x.edu", total_qty=5):
    member = create_eligible_member(email, full_name="Mem M")
    pool = create_pool(total_qty=total_qty)
    return member, pool


def test_return_exactly_at_due_is_on_time():
    """PRD §3.9: "The late fee's rounding order is pinned: the seconds late
    are the logical now minus `due_at`, floored at zero — a return exactly at
    `due_at` is on time; the days late are the seconds late divided by 86400
    rounded *up*, so even one second late counts as a full day; the raw fee is
    the days late times the pool's `daily_late_fee_cents` times the checkout
    `quantity`; and `late_fee_cents` is the raw fee capped at `quantity` times
    the pool's `unit_replacement_cents` — the ceiling is replacement value. An
    on-time return yields a fee of 0."

    Design: Difficulty/boundary_precision_check/equipment_return_due_boundary
    """
    set_clock("2026-09-01T09:00:00Z")
    member, pool = _member_and_pool()
    checkout = create_checkout(pool["id"], member, quantity=2, due_at=DUE_AT)
    set_clock("2026-10-01T17:00:00Z")  # exactly at the deadline
    returned = validate_success(api_client.return_equipment_checkout(
        checkout["id"], FACILITY_MANAGER))
    assert returned["status"] == "RETURNED"
    assert returned["late_fee_cents"] == 0, (
        "zero seconds late is on time — the deadline is inclusive"
    )


def test_return_one_second_late_counts_a_full_day():
    """PRD §3.9: "the days late are the seconds late divided by 86400 rounded
    *up*, so even one second late counts as a full day; the raw fee is the
    days late times the pool's `daily_late_fee_cents` times the checkout
    `quantity`; and `late_fee_cents` is the raw fee capped at `quantity` times
    the pool's `unit_replacement_cents` — the ceiling is replacement value."
    PRD §3.9: "The return stamps `returned_at` with the logical now, restores
    `quantity` to the pool's `available_qty`, computes `late_fee_cents`, and
    adds that fee to the member's `outstanding_fines_cents`."

    Design: Difficulty/boundary_precision_check/equipment_return_due_boundary
    """
    set_clock("2026-09-01T09:00:00Z")
    member, pool = _member_and_pool()
    checkout = create_checkout(pool["id"], member, quantity=2, due_at=DUE_AT)
    set_clock("2026-10-01T17:00:01Z")  # one second late -> one full day
    returned = validate_success(api_client.return_equipment_checkout(
        checkout["id"], FACILITY_MANAGER))
    assert returned["late_fee_cents"] == 300  # ceil(1/86400)=1 day * 150 * 2
    member_after = validate_success(api_client.get_member(
        member["id"], FACILITY_MANAGER))
    assert member_after["outstanding_fines_cents"] == 300
    pool_after = validate_success(api_client.get_equipment_pool(
        pool["id"], FACILITY_MANAGER))
    assert pool_after["available_qty"] == 5


def test_checkout_then_on_time_return_restores_units():
    """PRD §3.9: "`available_qty` starts equal to `total_qty`, and the pool
    maintains the invariant that `available_qty` plus the quantities of all
    checkouts still `OUT` equals `total_qty`."
    PRD §3.9: "The return stamps `returned_at` with the logical now, restores
    `quantity` to the pool's `available_qty`, computes `late_fee_cents`, and
    adds that fee to the member's `outstanding_fines_cents`."

    Design: Difficulty/compensating_invariant/equipment_pool_unit_conservation
    """
    set_clock("2026-09-01T09:00:00Z")
    member, pool = _member_and_pool()
    checkout = create_checkout(pool["id"], member, quantity=3,
                               due_at="2026-09-10T17:00:00Z")
    pool_mid = validate_success(api_client.get_equipment_pool(
        pool["id"], FACILITY_MANAGER))
    assert pool_mid["available_qty"] == 2
    assert pool_mid["available_qty"] + 3 == pool_mid["total_qty"]
    set_clock("2026-09-02T09:00:00Z")  # on time
    returned = validate_success(api_client.return_equipment_checkout(
        checkout["id"], FACILITY_MANAGER))
    assert returned["late_fee_cents"] == 0
    pool_after = validate_success(api_client.get_equipment_pool(
        pool["id"], FACILITY_MANAGER))
    assert pool_after["available_qty"] == 5, (
        "the compensating return restores the exact initial unit count"
    )
    member_after = validate_success(api_client.get_member(
        member["id"], FACILITY_MANAGER))
    assert member_after["outstanding_fines_cents"] == 0


def test_report_lost_rebinds_unit_invariant_at_lower_total():
    """PRD §3.9: "A `FacilityManager` may instead declare an `OUT` checkout
    lost. The member's `outstanding_fines_cents` increases by `quantity` times
    the pool's `unit_replacement_cents`, and the pool's `total_qty` is
    permanently decremented by `quantity` — `available_qty` is unchanged,
    because the units have left the pool for good. The checkout becomes
    `LOST`; `RETURNED` and `LOST` are terminal."
    PRD §3.9: "`available_qty` starts equal to `total_qty`, and the pool
    maintains the invariant that `available_qty` plus the quantities of all
    checkouts still `OUT` equals `total_qty`."

    Design: Difficulty/compensating_invariant/equipment_pool_unit_conservation
    """
    set_clock("2026-09-01T09:00:00Z")
    member, pool = _member_and_pool()
    checkout = create_checkout(pool["id"], member, quantity=2,
                               due_at="2026-09-05T17:00:00Z")
    lost = validate_success(api_client.report_equipment_lost(
        checkout["id"], FACILITY_MANAGER))
    assert lost["status"] == "LOST"
    pool_after = validate_success(api_client.get_equipment_pool(
        pool["id"], FACILITY_MANAGER))
    assert pool_after["total_qty"] == 3
    assert pool_after["available_qty"] == 3
    assert pool_after["available_qty"] + 0 == pool_after["total_qty"]
    member_after = validate_success(api_client.get_member(
        member["id"], FACILITY_MANAGER))
    assert member_after["outstanding_fines_cents"] == 1800  # 2 * 900


def test_suspended_member_checkout_fires_before_fiscal_gate():
    """PRD §2.8: "When a request fails multiple checks, the error returned is
    determined by a fixed priority order — lower priority number wins." (state
    preconditions are priority 6; the fiscal gate `ERR_OUTSTANDING_FINES` is
    priority 12, "the outstanding-fines check on equipment checkout runs last
    of all.")
    PRD §2.9: "Each requires, in order: the member's `status` must be `ACTIVE`
    (a member under an injury hold is `SUSPENDED` and is rejected with
    `ERR_MEMBER_SUSPENDED`); ... Equipment checkout additionally requires that
    the member's `outstanding_fines_cents` be zero, enforced as the final
    check with `ERR_OUTSTANDING_FINES` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_checkout_precedence
    """
    set_clock("2026-09-01T09:00:00Z")
    member, pool = _member_and_pool()
    checkout = create_checkout(pool["id"], member, quantity=1, due_at=DUE_AT)
    set_clock("2026-10-03T17:00:01Z")  # 2 days + 1s late -> 3 days -> 450
    returned = validate_success(api_client.return_equipment_checkout(
        checkout["id"], FACILITY_MANAGER))
    assert returned["late_fee_cents"] == 450
    file_injury(member["id"], severity="MODERATE", description="sprain")
    # Both conditions now hold (SUSPENDED and fines 450 > 0); the state gate
    # (priority 6) precedes the fiscal gate (priority 12).
    resp = api_client.create_equipment_checkout(
        {"equipment_pool_id": pool["id"], "member_id": member["id"],
         "quantity": 1, "due_at": "2026-10-10T17:00:00Z"},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED)


def test_rejected_checkout_leaves_no_mutation():
    """PRD §3.9: "The return stamps `returned_at` with the logical now,
    restores `quantity` to the pool's `available_qty`, computes
    `late_fee_cents`, and adds that fee to the member's
    `outstanding_fines_cents`."
    PRD §2.8: "When a request fails multiple checks, the error returned is
    determined by a fixed priority order — lower priority number wins."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_checkout_precedence
    """
    set_clock("2026-09-01T09:00:00Z")
    member, pool = _member_and_pool()
    checkout = create_checkout(pool["id"], member, quantity=1, due_at=DUE_AT)
    set_clock("2026-10-03T17:00:01Z")
    validate_success(api_client.return_equipment_checkout(
        checkout["id"], FACILITY_MANAGER))
    file_injury(member["id"], severity="MODERATE", description="sprain")
    resp = api_client.create_equipment_checkout(
        {"equipment_pool_id": pool["id"], "member_id": member["id"],
         "quantity": 1, "due_at": "2026-10-10T17:00:00Z"},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED)
    member_after = validate_success(api_client.get_member(
        member["id"], FACILITY_MANAGER))
    assert member_after["outstanding_fines_cents"] == 450
    _, meta = validate_paginated(api_client.list_equipment_checkouts(
        FACILITY_MANAGER, params={"member_id": member["id"]}))
    assert meta["total_count"] == 1, "the rejected checkout created no row"


def test_checkout_return_twice_returns_invalid_state():
    """PRD §3.9: "A `FacilityManager` processes a return on an `OUT` checkout
    addressed by its `equipment_checkout_id` (any other status is
    `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/checkout_return_twice_returns_invalid_state
    """
    set_clock("2026-09-01T09:00:00Z")
    member, pool = _member_and_pool()
    checkout = create_checkout(pool["id"], member, quantity=1,
                               due_at="2026-09-10T17:00:00Z")
    set_clock("2026-09-02T09:00:00Z")
    validate_success(api_client.return_equipment_checkout(
        checkout["id"], FACILITY_MANAGER))
    resp = api_client.return_equipment_checkout(
        checkout["id"], FACILITY_MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    pool_after = validate_success(api_client.get_equipment_pool(
        pool["id"], FACILITY_MANAGER))
    assert pool_after["available_qty"] == 5, (
        "the second return must not restore units twice"
    )
    member_after = validate_success(api_client.get_member(
        member["id"], FACILITY_MANAGER))
    assert member_after["outstanding_fines_cents"] == 0


def test_error_equipment_insufficient():
    """PRD §3.9: "The eligibility gates of §2.9 apply, the requested
    `quantity` must not exceed the pool's `available_qty` (otherwise
    `ERR_EQUIPMENT_INSUFFICIENT`), and — as the last check of all — the
    member's `outstanding_fines_cents` must be zero (otherwise
    `ERR_OUTSTANDING_FINES`)."

    Design: Corner/errors/error_equipment_insufficient
    """
    set_clock("2026-08-24T00:00:00Z")
    member = create_eligible_member("mm@x.edu", full_name="Mem M")
    pool = create_pool(item_type="YOGA_MAT", total_qty=2,
                       daily_late_fee_cents=50, unit_replacement_cents=1200)
    resp = api_client.create_equipment_checkout(
        {"equipment_pool_id": pool["id"], "member_id": member["id"],
         "quantity": 3, "due_at": "2026-09-01T17:00:00Z"},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_EQUIPMENT_INSUFFICIENT)
    pool_after = validate_success(api_client.get_equipment_pool(
        pool["id"], FACILITY_MANAGER))
    assert pool_after["available_qty"] == 2


def test_error_outstanding_fines_direct():
    """PRD §2.9: "Equipment checkout additionally requires that the member's
    `outstanding_fines_cents` be zero, enforced as the final check with
    `ERR_OUTSTANDING_FINES` (HTTP 402)."
    PRD §3.1: "Members settle debts through fine payments: a self-service
    payment carries `amount_cents`, which must be greater than zero and no
    more than the member's current `outstanding_fines_cents` (violations are
    `ERR_VALIDATION`); the amount is subtracted from `outstanding_fines_cents`
    and the member's `version` increments. The balance never goes negative."

    Design: Corner/errors/error_outstanding_fines_direct
    """
    set_clock("2026-09-01T09:00:00Z")
    member, pool = _member_and_pool()
    checkout = create_checkout(pool["id"], member, quantity=2, due_at=DUE_AT)
    set_clock("2026-10-01T17:00:01Z")  # 1 day late * 150 * qty 2 -> 300
    validate_success(api_client.return_equipment_checkout(
        checkout["id"], FACILITY_MANAGER))

    resp1 = api_client.create_equipment_checkout(
        {"equipment_pool_id": pool["id"], "member_id": member["id"],
         "quantity": 1, "due_at": "2026-10-05T17:00:00Z"},
        make_member_headers(member["id"]),
    )
    validate_error(resp1, ApiErrorId.ERR_OUTSTANDING_FINES)

    paid = validate_success(api_client.pay_fine(
        member["id"], {"amount_cents": 100},
        make_member_headers(member["id"])))
    assert paid["outstanding_fines_cents"] == 200
    resp2 = api_client.create_equipment_checkout(
        {"equipment_pool_id": pool["id"], "member_id": member["id"],
         "quantity": 1, "due_at": "2026-10-05T17:00:00Z"},
        make_member_headers(member["id"]),
    )
    validate_error(resp2, ApiErrorId.ERR_OUTSTANDING_FINES)

    paid2 = validate_success(api_client.pay_fine(
        member["id"], {"amount_cents": 200},
        make_member_headers(member["id"])))
    assert paid2["outstanding_fines_cents"] == 0
    data = validate_success(api_client.create_equipment_checkout(
        {"equipment_pool_id": pool["id"], "member_id": member["id"],
         "quantity": 1, "due_at": "2026-10-05T17:00:00Z"},
        make_member_headers(member["id"]),
    ), 201)
    assert data["status"] == "OUT"


def test_locker_rent_release_cycle():
    """PRD §3.9: "A member rents an `AVAILABLE` locker, addressed by its
    `locker_id`, for a `term`, subject to the eligibility gates of §2.9 —
    explicitly without the outstanding-fines check — and the rule that the
    member may hold at most one `RENTED` locker at a time (otherwise
    `ERR_RENTAL_EXISTS`); renting a non-`AVAILABLE` locker is
    `ERR_LOCKER_UNAVAILABLE`. Rental records `rented_by_member_id` and
    `rental_term` on the locker, moves it `AVAILABLE → RENTED`, and computes
    `rental_fee_cents` as a flat per-term fee by affiliation — 1500 cents for
    `STUDENT`, 1500 cents for `FACULTY`, 3000 cents for `COMMUNITY` — with no
    proration. The current renter or a `FacilityManager` releases a `RENTED`
    locker (releasing a non-`RENTED` locker is `ERR_INVALID_STATE`), returning
    it to `AVAILABLE` and clearing `rented_by_member_id`, `rental_term`, and
    `rental_fee_cents` to null."

    Design: Corner/state_machines/locker_rent_release_cycle
    """
    set_clock("2026-08-24T00:00:00Z")
    member_1 = create_eligible_member("m1@x.edu", full_name="M One",
                                      affiliation="COMMUNITY")
    member_2 = create_eligible_member("m2@x.edu", full_name="M Two")
    locker_1 = create_locker(locker_number=101, size="M")
    locker_2 = create_locker(locker_number=102, size="S")

    rented = validate_success(api_client.rent_locker(
        locker_1["id"], {"member_id": member_1["id"], "term": "FALL_2026"},
        make_member_headers(member_1["id"])))
    assert rented["status"] == "RENTED"
    assert rented["rental_fee_cents"] == 3000  # COMMUNITY flat fee
    assert rented["rented_by_member_id"] == member_1["id"]

    resp1 = api_client.rent_locker(
        locker_1["id"], {"member_id": member_2["id"], "term": "FALL_2026"},
        make_member_headers(member_2["id"]))
    validate_error(resp1, ApiErrorId.ERR_LOCKER_UNAVAILABLE)
    resp2 = api_client.rent_locker(
        locker_2["id"], {"member_id": member_1["id"], "term": "FALL_2026"},
        make_member_headers(member_1["id"]))
    validate_error(resp2, ApiErrorId.ERR_RENTAL_EXISTS)

    released = validate_success(api_client.release_locker(
        locker_1["id"], FACILITY_MANAGER))
    assert released["status"] == "AVAILABLE"
    assert released["rented_by_member_id"] is None
    assert released["rental_term"] is None
    assert released["rental_fee_cents"] is None

    rented_2 = validate_success(api_client.rent_locker(
        locker_2["id"], {"member_id": member_2["id"], "term": "FALL_2026"},
        make_member_headers(member_2["id"])))
    assert rented_2["status"] == "RENTED"
    assert rented_2["rental_fee_cents"] == 1500  # STUDENT flat fee
