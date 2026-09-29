"""
What is conserved, and what is not, across a provision-then-release round trip.

Two ledgers run alongside each other on a vendor licence and they behave
differently. Seats are conserved absolutely: the purchased total always equals the
district pool plus the building grants plus whatever has been borrowed out of that
pool, and giving every seat back puts every counter exactly where activation left
it. Money is conserved only by identity: the committed charge always equals the
summed seat charges less the summed refunds, but a seat handed back after the
add/drop cutoff earns no refund, so the money never returns to its baseline even
though the seat does. These tests pin both ledgers to exact integers at every step.
"""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.types import (
    AllocationPolicy,
    GradeBand,
    IdentifierStrategy,
    OveragePolicy,
    RosteringStandard,
    SeatModel,
    SeatStatus,
)

# ── the borrowing district: 6 seats, two blocks of 2, a pool of 2 ────────────
BORROW_TOTAL_SEATS = 6
BORROW_BLOCK_SEATS = 2
BORROW_PRICE_PER_SEAT_CENTS = 1000

# ── the refund district: 4 seats, all in one building, priced at 1000 ────────
REFUND_TOTAL_SEATS = 4
REFUND_PRICE_PER_SEAT_CENTS = 1000


def _district_with_a_borrowable_pool(api):
    """
    Northside (three students) and Southmeadow (two students) inside an ACTIVE
    Fall 2026 term, under an ACTIVE six-seat licence cut into blocks of two with
    a POOL_FALLBACK overage policy. Northside and Southmeadow each hold two
    granted seats and the district pool holds the remaining two.

    Returns the two allocation ids, Northside's three student ids and the licence.
    """
    fx.set_clock(api, c.CLOCK_STARTUP_DEFAULT, users.IDENTITY_ADMIN)

    northside = fx.create_school(
        api,
        grade_band=GradeBand.ELEMENTARY,
        name="Northside Elementary",
        sis_school_id="SCH-NE",
        building_code="NE",
    )
    southmeadow = fx.create_school(
        api,
        grade_band=GradeBand.ELEMENTARY,
        name="Southmeadow Elementary",
        sis_school_id="SCH-SM",
        building_code="SM",
    )
    term = fx.create_active_term(api)

    student_1 = fx.create_student(
        api, northside["id"], grade_level=4, sis_student_id="STU-2001",
        first_name="Alex", last_name="Nakamura", date_of_birth="2016-05-04",
    )
    student_2 = fx.create_student(
        api, northside["id"], grade_level=4, sis_student_id="STU-2002",
        first_name="Priya", last_name="Raman", date_of_birth="2016-07-11",
    )
    student_3 = fx.create_student(
        api, northside["id"], grade_level=4, sis_student_id="STU-2003",
        first_name="Lena", last_name="Sorensen", date_of_birth="2016-09-19",
    )
    fx.create_student(
        api, southmeadow["id"], grade_level=5, sis_student_id="STU-2101",
        first_name="Mateo", last_name="Vargas", date_of_birth="2015-11-23",
    )
    fx.create_student(
        api, southmeadow["id"], grade_level=5, sis_student_id="STU-2102",
        first_name="Iris", last_name="Whitfield", date_of_birth="2015-12-30",
    )

    vendor_app = fx.create_vendor_app(
        api,
        term["id"],
        total_seats=BORROW_TOTAL_SEATS,
        price_per_seat_cents=BORROW_PRICE_PER_SEAT_CENTS,
        grade_band_scope=[GradeBand.ELEMENTARY],
        name="SciSpark",
        vendor_code="SSX",
        rostering_standard=RosteringStandard.VENDOR_NATIVE_JSON,
        identifier_strategy=IdentifierStrategy.SIS_ID,
        username_domain="apps.district.k12",
        seat_model=SeatModel.PER_STUDENT,
        allocation_policy=AllocationPolicy.FIXED_BUILDING_BLOCKS,
        block_seats=BORROW_BLOCK_SEATS,
        overage_policy=OveragePolicy.POOL_FALLBACK,
    )
    licence = fx.activate_license(api, vendor_app["id"])

    northside_allocation = fx.allocation_for_school(
        api, vendor_app["id"], northside["id"]
    )
    southmeadow_allocation = fx.allocation_for_school(
        api, vendor_app["id"], southmeadow["id"]
    )

    return {
        "vendor_app_id": vendor_app["id"],
        "licence": licence,
        "northside_allocation_id": northside_allocation["id"],
        "southmeadow_allocation_id": southmeadow_allocation["id"],
        "student_ids": [student_1["id"], student_2["id"], student_3["id"]],
    }


def _seat_invariant_holds(api, world):
    """
    The purchased total equals the district pool plus every building's grant plus
    every borrowed seat, and the licence's consumed count equals the summed
    consumed counts of its allocations.
    """
    licence = fx.read_vendor_app(api, world["vendor_app_id"])
    allocations = fx.list_allocations(api, world["vendor_app_id"])

    granted = sum(row["allocated_seats"] for row in allocations)
    borrowed = sum(row["borrowed_seats"] for row in allocations)
    consumed = sum(row["consumed_seats"] for row in allocations)

    assert licence["total_seats"] == licence["unallocated_seats"] + granted + borrowed, (
        f"seat conservation broken: total {licence['total_seats']} != pool "
        f"{licence['unallocated_seats']} + granted {granted} + borrowed {borrowed}"
    )
    assert licence["consumed_seats"] == consumed, (
        f"licence consumed_seats {licence['consumed_seats']} must equal the summed "
        f"allocation consumed_seats {consumed}"
    )
    return licence


def test_activation_leaves_two_seats_in_the_district_pool_and_nothing_consumed(api):
    """Six purchased seats split into two blocks of two, leaving a two-seat district pool.

    Under `FIXED_BUILDING_BLOCKS` "each building is granted the smaller of
    `block_seats` and the seats still unallocated", so Northside and Southmeadow
    each take two. "`VendorApp.unallocated_seats` is the licence's `total_seats`
    minus the sum of `allocated_seats` across its allocations minus the sum of
    `borrowed_seats` across its allocations", which is six minus four minus zero.
    Each new allocation is written with "a `consumed_seats` and `borrowed_seats`
    of zero", and a licence with no accounts yet has a `committed_charge_cents` of
    zero.

    Design: Difficulty/compensating_invariant/seat_conservation_across_provision_and_release
    """
    world = _district_with_a_borrowable_pool(api)

    northside = fx.read_allocation(api, world["northside_allocation_id"])
    southmeadow = fx.read_allocation(api, world["southmeadow_allocation_id"])

    a.assert_allocation(
        northside, allocated_seats=2, consumed_seats=0, borrowed_seats=0
    )
    a.assert_allocation(
        southmeadow, allocated_seats=2, consumed_seats=0, borrowed_seats=0
    )

    licence = _seat_invariant_holds(api, world)
    a.assert_seat_counters(
        licence, consumed_seats=0, unallocated_seats=2, committed_charge_cents=0
    )
    assert licence["total_seats"] == BORROW_TOTAL_SEATS


def test_the_third_northside_seat_is_borrowed_out_of_the_district_pool(api):
    """A third seat in a two-seat building is taken from the district pool, which shrinks by exactly one.

    "When there is at least one free seat the account is admitted and nothing is
    borrowed. When there is none ... under `POOL_FALLBACK` the account is admitted
    by borrowing exactly one seat from the district pool, which increments the
    allocation's `borrowed_seats` by one ... On admission the allocation's
    `consumed_seats` is incremented by one and the licence's `unallocated_seats`
    is recomputed as `total_seats` minus the summed `allocated_seats` minus the
    summed `borrowed_seats`." The borrowed seat therefore leaves the pool rather
    than being conjured: six equals one plus four plus one. Southmeadow lent
    nothing and is untouched.

    Design: Difficulty/compensating_invariant/seat_conservation_across_provision_and_release
    """
    world = _district_with_a_borrowable_pool(api)
    allocation_id = world["northside_allocation_id"]

    fx.provision_account(
        api, allocation_id, vendor_app_id=world["vendor_app_id"],
        student_id=world["student_ids"][0],
    )
    fx.provision_account(
        api, allocation_id, vendor_app_id=world["vendor_app_id"],
        student_id=world["student_ids"][1],
    )

    northside = fx.read_allocation(api, allocation_id)
    a.assert_allocation(
        northside, allocated_seats=2, consumed_seats=2, borrowed_seats=0
    )
    licence = _seat_invariant_holds(api, world)
    a.assert_seat_counters(
        licence, consumed_seats=2, unallocated_seats=2, committed_charge_cents=2000
    )

    fx.provision_account(
        api, allocation_id, vendor_app_id=world["vendor_app_id"],
        student_id=world["student_ids"][2],
    )

    northside = fx.read_allocation(api, allocation_id)
    a.assert_allocation(
        northside, allocated_seats=2, consumed_seats=3, borrowed_seats=1
    )
    licence = _seat_invariant_holds(api, world)
    a.assert_seat_counters(licence, consumed_seats=3, unallocated_seats=1)

    southmeadow = fx.read_allocation(api, world["southmeadow_allocation_id"])
    a.assert_allocation(
        southmeadow, allocated_seats=2, consumed_seats=0, borrowed_seats=0
    )


def test_releasing_every_seat_returns_the_borrowed_seat_and_all_counters_to_baseline(api):
    """Handing the three Northside seats back restores the two-seat pool exactly, with no drift.

    A release decrements "the owning allocation's `consumed_seats` ... by one —
    decrementing `borrowed_seats` first when this account had taken a borrowed
    seat — and the licence's `consumed_seats`, `unallocated_seats`,
    `committed_charge_cents` ... are recomputed". Releasing the borrowed seat
    therefore compensates the borrow exactly: `borrowed_seats` falls back to zero
    and the district pool returns to two. Releasing the remaining two takes
    Northside's `consumed_seats` to zero while its `allocated_seats` grant stays
    at two, because "`BuildingAllocation.consumed_seats` is the number of app
    accounts drawing on that allocation whose `seat_status` is `RESERVED` or
    `ACTIVE`" and a release is a state change, never a delete.

    Design: Difficulty/compensating_invariant/seat_conservation_across_provision_and_release
    """
    world = _district_with_a_borrowable_pool(api)
    allocation_id = world["northside_allocation_id"]

    account_1 = fx.provision_account(
        api, allocation_id, vendor_app_id=world["vendor_app_id"],
        student_id=world["student_ids"][0],
    )
    account_2 = fx.provision_account(
        api, allocation_id, vendor_app_id=world["vendor_app_id"],
        student_id=world["student_ids"][1],
    )
    account_3 = fx.provision_account(
        api, allocation_id, vendor_app_id=world["vendor_app_id"],
        student_id=world["student_ids"][2],
    )

    fx.release_seat(api, account_3["id"])

    northside = fx.read_allocation(api, allocation_id)
    a.assert_allocation(
        northside, allocated_seats=2, consumed_seats=2, borrowed_seats=0
    )
    licence = _seat_invariant_holds(api, world)
    a.assert_seat_counters(licence, consumed_seats=2, unallocated_seats=2)

    fx.release_seat(api, account_2["id"])
    fx.release_seat(api, account_1["id"])

    northside = fx.read_allocation(api, allocation_id)
    a.assert_allocation(
        northside, allocated_seats=2, consumed_seats=0, borrowed_seats=0
    )
    southmeadow = fx.read_allocation(api, world["southmeadow_allocation_id"])
    a.assert_allocation(
        southmeadow, allocated_seats=2, consumed_seats=0, borrowed_seats=0
    )
    licence = _seat_invariant_holds(api, world)
    a.assert_seat_counters(licence, consumed_seats=0, unallocated_seats=2)

    response = api.list_app_accounts(
        users.IDENTITY_ADMIN, building_allocation_id=allocation_id, limit=100
    )
    accounts, meta = validate_paginated(response)
    assert len(accounts) == 3, (
        f"the three released accounts must still exist, got {len(accounts)}"
    )
    a.assert_pagination_meta(meta, total_count=3)
    for account in accounts:
        a.assert_account_axes(account, seat_status=SeatStatus.RELEASED)


def _building_with_two_seated_students(api):
    """
    Northside alone inside an ACTIVE Fall 2026 term, under an ACTIVE four-seat
    licence at 1000 cents a seat whose whole grant lands on that one building, with
    two accounts provisioned while the clock is still 1 August 2026 — comfortably
    inside the 15 September add/drop window.

    Returns the allocation id, the two accounts and the licence id.
    """
    fx.set_clock(api, c.CLOCK_STARTUP_DEFAULT, users.IDENTITY_ADMIN)

    northside = fx.create_school(
        api,
        grade_band=GradeBand.ELEMENTARY,
        name="Northside Elementary",
        sis_school_id="SCH-NE",
        building_code="NE",
    )
    term = fx.create_active_term(api)

    student_1 = fx.create_student(
        api, northside["id"], grade_level=4, sis_student_id="STU-2001",
        first_name="Alex", last_name="Nakamura", date_of_birth="2016-05-04",
    )
    student_2 = fx.create_student(
        api, northside["id"], grade_level=4, sis_student_id="STU-2002",
        first_name="Priya", last_name="Raman", date_of_birth="2016-07-11",
    )

    vendor_app = fx.create_vendor_app(
        api,
        term["id"],
        total_seats=REFUND_TOTAL_SEATS,
        price_per_seat_cents=REFUND_PRICE_PER_SEAT_CENTS,
        grade_band_scope=[GradeBand.ELEMENTARY],
        name="MathBlast",
        vendor_code="MBX",
        rostering_standard=RosteringStandard.ONEROSTER_REST_1P2,
        identifier_strategy=IdentifierStrategy.SIS_ID,
        username_domain="apps.district.k12",
        seat_model=SeatModel.PER_STUDENT,
        allocation_policy=AllocationPolicy.PROPORTIONAL_HEADCOUNT,
        overage_policy=OveragePolicy.BLOCK,
    )
    fx.activate_license(api, vendor_app["id"])
    allocation = fx.allocation_for_school(api, vendor_app["id"], northside["id"])

    account_1 = fx.provision_account(
        api, allocation["id"], vendor_app_id=vendor_app["id"],
        student_id=student_1["id"],
    )
    account_2 = fx.provision_account(
        api, allocation["id"], vendor_app_id=vendor_app["id"],
        student_id=student_2["id"],
    )

    return {
        "vendor_app_id": vendor_app["id"],
        "allocation_id": allocation["id"],
        "account_1_id": account_1["id"],
        "account_2_id": account_2["id"],
    }


def _charge_ledger_holds(api, world):
    """
    The licence's committed charge equals the summed seat charges of its accounts
    less their summed refunds, whatever the seat axis says.
    """
    licence = fx.read_vendor_app(api, world["vendor_app_id"])
    accounts = fx.accounts_of_allocation(api, world["allocation_id"])
    expected = sum(
        account["seat_charge_cents"] - account["refunded_charge_cents"]
        for account in accounts
    )
    assert licence["committed_charge_cents"] == expected, (
        f"committed_charge_cents {licence['committed_charge_cents']} must equal the "
        f"summed seat charges less refunds, {expected}"
    )
    return licence


def test_two_seats_taken_inside_the_window_commit_two_thousand_cents(api):
    """Two seats bought on 1 August each freeze the full list price, committing 2000 cents.

    "A seat priced on a date on or before the term's `add_drop_cutoff_date` costs
    the full `price_per_seat_cents`", and each account's "`seat_charge_cents` is
    frozen at the per-seat rate for the provisioning clock date".
    `VendorApp.committed_charge_cents` "is the sum, over every app account of that
    licence regardless of `seat_status`, of that account's `seat_charge_cents`
    minus its `refunded_charge_cents`" — 1000 plus 1000, with nothing refunded
    yet. All four purchased seats sit in the single eligible building, so no
    borrowing is possible.

    Design: Difficulty/compensating_invariant/charge_conservation_across_provision_and_release
    """
    world = _building_with_two_seated_students(api)

    account_1 = fx.read_account(api, world["account_1_id"])
    account_2 = fx.read_account(api, world["account_2_id"])
    a.assert_app_account(
        account_1, seat_charge_cents=1000, refunded_charge_cents=0
    )
    a.assert_app_account(
        account_2, seat_charge_cents=1000, refunded_charge_cents=0
    )

    allocation = fx.read_allocation(api, world["allocation_id"])
    a.assert_allocation(
        allocation, allocated_seats=4, consumed_seats=2, borrowed_seats=0
    )

    licence = _charge_ledger_holds(api, world)
    a.assert_seat_counters(
        licence, consumed_seats=2, committed_charge_cents=2000
    )


def test_a_release_inside_the_add_drop_window_refunds_the_whole_seat_charge(api):
    """Giving a seat back on 1 August refunds all 1000 cents and halves the committed charge.

    On a release "`refunded_charge_cents` is set to the account's
    `seat_charge_cents` when the clock date is on or before the term's
    `add_drop_cutoff_date` and to zero otherwise", and the licence's
    `consumed_seats` and `committed_charge_cents` are recomputed. With the clock
    at 1 August, well inside the window that closes on 15 September, the refund is
    the full 1000 cents, so the ledger identity leaves 2000 minus 1000, or 1000
    cents committed, against one seat still consumed.

    Design: Difficulty/compensating_invariant/charge_conservation_across_provision_and_release
    """
    world = _building_with_two_seated_students(api)

    released = fx.release_seat(api, world["account_1_id"])
    a.assert_app_account(
        released, seat_charge_cents=1000, refunded_charge_cents=1000
    )
    a.assert_account_axes(released, seat_status=SeatStatus.RELEASED)

    licence = _charge_ledger_holds(api, world)
    a.assert_seat_counters(
        licence, consumed_seats=1, committed_charge_cents=1000
    )


def test_a_post_cutoff_release_returns_the_seat_but_not_the_money(api):
    """The last seat handed back on 16 September earns no refund, so the seats reach zero while 1000 cents stay committed.

    A release sets "`refunded_charge_cents` ... to the account's
    `seat_charge_cents` when the clock date is on or before the term's
    `add_drop_cutoff_date` and to zero otherwise". The cutoff is 15 September, so a
    release on 16 September refunds nothing and the account keeps its 1000-cent
    `seat_charge_cents`. Because `committed_charge_cents` is "the sum ... of that
    account's `seat_charge_cents` minus its `refunded_charge_cents`" over every
    account "regardless of `seat_status`", the licence stays committed to 1000
    cents even though `consumed_seats` — "the number of accounts ... whose
    `seat_status` is `RESERVED` or `ACTIVE`" — has fallen to zero. That asymmetry
    between the two ledgers is the contract.

    Design: Difficulty/compensating_invariant/charge_conservation_across_provision_and_release
    """
    world = _building_with_two_seated_students(api)

    fx.release_seat(api, world["account_1_id"])

    fx.set_clock(api, c.CLOCK_AFTER_CUTOFF, users.IDENTITY_ADMIN)
    released = fx.release_seat(api, world["account_2_id"])

    a.assert_app_account(
        released, seat_charge_cents=1000, refunded_charge_cents=0
    )
    a.assert_account_axes(released, seat_status=SeatStatus.RELEASED)

    licence = _charge_ledger_holds(api, world)
    a.assert_seat_counters(
        licence, consumed_seats=0, committed_charge_cents=1000
    )
    assert licence["committed_charge_cents"] != 0, (
        "money does not return to its baseline: the post-cutoff release earned no "
        "refund, so 1000 cents stay committed"
    )

    allocation = fx.read_allocation(api, world["allocation_id"])
    a.assert_allocation(
        allocation, allocated_seats=4, consumed_seats=0, borrowed_seats=0
    )

    response = api.list_app_accounts(
        users.IDENTITY_ADMIN,
        building_allocation_id=world["allocation_id"],
        seat_status=SeatStatus.RELEASED,
        limit=100,
    )
    accounts, meta = validate_paginated(response)
    assert len(accounts) == 2, (
        f"both accounts must be filtered out as RELEASED, got {len(accounts)}"
    )
    a.assert_pagination_meta(meta, total_count=2)
