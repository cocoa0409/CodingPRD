"""
The licensed seat axis and the single sign-on identity axis move independently.

One student account walks its whole life in four separate acts, and no act ever
moves both axes: setting the password provisions the identity while the seat stays
reserved, vendor telemetry activates the seat while the identity stays exactly
where it was, deprovisioning switches the identity off while the building keeps
paying for the seat, and only an explicit release gives the seat and its money
back. The account therefore ends in a combination — RELEASED on one axis,
DEPROVISIONED on the other — that no single trigger could have produced.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.assertions import assert_account_axes, assert_seat_counters
from test_helpers.types import (
    GradeBand,
    IdentityStatus,
    OveragePolicy,
    PasswordState,
    SeatModel,
    SeatStatus,
)

STARTUP_CLOCK = "2026-08-01T00:00:00Z"
ACTIVITY_DATE = "2026-08-01"
DEPROVISION_DATE = "2026-08-01"
FULL_PRICE_PER_SEAT = 1000
REAL_PASSWORD = "Rostering2026"
REPORTED_MINUTES = 45
REPORTED_SESSIONS = 2


def _seated_account_world(api):
    """
    One elementary building with the district's default password policy inside an
    ACTIVE Fall 2026 term, holding a three-seat per-student licence whose seats all
    landed on that building, and one freshly provisioned account for its single
    enrolled student: seat RESERVED, identity PENDING_PROVISION, password TEMP_SET.
    """
    fx.set_clock(api, STARTUP_CLOCK, headers=users.IDENTITY_ADMIN)
    school = fx.create_school(
        api,
        grade_band=GradeBand.ELEMENTARY,
        name="Northside Elementary",
        sis_school_id="SCH-NE",
        building_code="NE",
    )
    term = fx.create_active_term(api)
    student = fx.create_student(
        api,
        school["id"],
        grade_level=4,
        sis_student_id="STU-2001",
        first_name="Alex",
        last_name="Nakamura",
        date_of_birth="2016-05-04",
    )
    vendor_app = fx.create_vendor_app(
        api,
        term["id"],
        total_seats=3,
        price_per_seat_cents=FULL_PRICE_PER_SEAT,
        grade_band_scope=[GradeBand.ELEMENTARY],
        name="MathBlast",
        vendor_code="MBX",
        seat_model=SeatModel.PER_STUDENT,
        overage_policy=OveragePolicy.BLOCK,
    )
    vendor_app = fx.activate_license(api, vendor_app["id"])
    allocation = fx.allocation_for_school(
        api, vendor_app["id"], school["id"], headers=users.IDENTITY_ADMIN
    )
    account = fx.provision_account(
        api,
        allocation["id"],
        vendor_app_id=vendor_app["id"],
        student_id=student["id"],
    )
    return {
        "school": school,
        "term": term,
        "student": student,
        "vendor_app": vendor_app,
        "allocation": allocation,
        "account": account,
    }


def _provisioned_identity_world(api):
    """The world after the identity admin set a real password on the account."""
    world = _seated_account_world(api)
    world["account"] = fx.set_account_password(
        api, world["account"]["id"], new_password=REAL_PASSWORD
    )
    return world


def _active_seat_world(api):
    """The world after vendor telemetry proved the seat consumed."""
    world = _provisioned_identity_world(api)
    world["account"] = fx.record_usage(
        api,
        world["account"]["id"],
        ACTIVITY_DATE,
        REPORTED_MINUTES,
        session_count=REPORTED_SESSIONS,
        failed_logins=0,
    )
    return world


def _deprovisioned_identity_world(api):
    """The world after the identity was switched off with the seat still held."""
    world = _active_seat_world(api)
    world["account"] = fx.deprovision_account(
        api, world["account"]["id"], DEPROVISION_DATE
    )
    return world


def test_a_new_account_reserves_a_seat_before_any_identity_exists(api):
    """Provisioning takes the seat and mints a temporary password, nothing more.

    "The account is created with `seat_status` of `RESERVED` on the seat axis and
    `identity_status` of `PENDING_PROVISION` on the identity axis. `PROVISIONED` is
    never reached by creation; only a later password set gets there. Its
    `password_state` is `TEMP_SET`". Its `seat_charge_cents` is "frozen at the
    per-seat rate for the provisioning clock date" — 2026-08-01 is on or before the
    term's 2026-09-15 add/drop cutoff, so the seat costs the full list price.

    Design: Difficulty/non_linear_state_machine/app_account_parallel_seat_and_identity_axes
    """
    world = _seated_account_world(api)
    account = world["account"]

    assert_account_axes(
        account,
        seat_status=SeatStatus.RESERVED,
        identity_status=IdentityStatus.PENDING_PROVISION,
        password_state=PasswordState.TEMP_SET,
    )
    assert account["seat_charge_cents"] == FULL_PRICE_PER_SEAT == 1000
    assert account["refunded_charge_cents"] == 0


def test_setting_the_password_advances_only_the_identity_axis(api):
    """A real password provisions the identity and leaves the seat reserved.

    "On acceptance the identity axis advances from `PENDING_PROVISION` to
    `PROVISIONED` ...; `password_state` becomes `USER_SET`" — and "the seat axis is
    not touched by a password set". The building's seat counter therefore still
    reads the one seat it lent, because `consumed_seats` counts accounts "whose
    `seat_status` is `RESERVED` or `ACTIVE`" and this one is still `RESERVED`.

    Design: Difficulty/non_linear_state_machine/app_account_parallel_seat_and_identity_axes
    """
    world = _provisioned_identity_world(api)

    assert_account_axes(
        world["account"],
        seat_status=SeatStatus.RESERVED,
        identity_status=IdentityStatus.PROVISIONED,
        password_state=PasswordState.USER_SET,
    )

    allocation = fx.read_allocation(api, world["allocation"]["id"])
    assert allocation["consumed_seats"] == 1


def test_vendor_telemetry_advances_only_the_seat_axis(api):
    """Reported classroom minutes prove the seat consumed and touch nothing else.

    "The account's `active_minutes_total` grows by the reported `active_minutes`
    ... When the reported `active_minutes` is greater than zero and the seat axis
    is still `RESERVED`, the seat advances to `ACTIVE` — the seat has been proven
    consumed by telemetry rather than merely held." The identity axis is no part of
    that transition, so it stays exactly where the password set left it.

    Design: Difficulty/non_linear_state_machine/app_account_parallel_seat_and_identity_axes
    """
    world = _active_seat_world(api)
    account = world["account"]

    assert_account_axes(
        account,
        seat_status=SeatStatus.ACTIVE,
        identity_status=IdentityStatus.PROVISIONED,
        password_state=PasswordState.USER_SET,
    )
    assert account["active_minutes_total"] == REPORTED_MINUTES == 45


def test_deprovisioning_the_identity_leaves_the_seat_and_its_charge_intact(api):
    """Switching the identity off does not give the district its money back.

    Deprovisioning "moves `identity_status` to `DEPROVISIONED` ..., stamps
    `deprovision_scheduled_date` with that `effective_date`, and sets
    `password_state` to `EXPIRED` — while leaving the seat axis untouched, so a
    deprovisioned identity may keep a `RESERVED` or `ACTIVE` seat until somebody
    releases it". The building's consumed seat and the licence's
    `committed_charge_cents`, defined as the accounts' `seat_charge_cents` less
    their `refunded_charge_cents`, therefore both stand.

    Design: Difficulty/non_linear_state_machine/app_account_parallel_seat_and_identity_axes
    """
    world = _deprovisioned_identity_world(api)
    account = world["account"]

    assert_account_axes(
        account,
        seat_status=SeatStatus.ACTIVE,
        identity_status=IdentityStatus.DEPROVISIONED,
        password_state=PasswordState.EXPIRED,
    )
    assert account["deprovision_scheduled_date"] == DEPROVISION_DATE == "2026-08-01"

    allocation = fx.read_allocation(api, world["allocation"]["id"])
    assert allocation["consumed_seats"] == 1

    vendor_app = fx.read_vendor_app(api, world["vendor_app"]["id"])
    assert_seat_counters(vendor_app, committed_charge_cents=FULL_PRICE_PER_SEAT)


def test_only_releasing_the_seat_returns_it_and_refunds_the_charge(api):
    """The fourth act frees the seat, and the account lands in a combined terminal state.

    Releasing moves the seat "from `RESERVED` or `ACTIVE` to `RELEASED`",
    sets "`refunded_charge_cents` ... to the account's `seat_charge_cents` when the
    clock date is on or before the term's `add_drop_cutoff_date`", decrements "the
    owning allocation's `consumed_seats` by one" and recomputes the licence's
    `committed_charge_cents` — while "`identity_status` is deliberately left
    alone". The account therefore rests on RELEASED plus DEPROVISIONED, a
    combination reached only because each axis was moved by its own trigger.

    Design: Difficulty/non_linear_state_machine/app_account_parallel_seat_and_identity_axes
    """
    world = _deprovisioned_identity_world(api)

    released = validate_success(
        api.release_seat(world["account"]["id"], users.IDENTITY_ADMIN), 200
    )

    assert_account_axes(
        released,
        seat_status=SeatStatus.RELEASED,
        identity_status=IdentityStatus.DEPROVISIONED,
    )
    assert released["refunded_charge_cents"] == FULL_PRICE_PER_SEAT == 1000

    allocation = fx.read_allocation(api, world["allocation"]["id"])
    assert allocation["consumed_seats"] == 0

    vendor_app = fx.read_vendor_app(api, world["vendor_app"]["id"])
    assert_seat_counters(vendor_app, committed_charge_cents=0)
