"""
Everything the district can observe is already reconciled by the next read.

This service keeps no eventual bookkeeping. One write leaves every aggregate it
touches — the child rows it cascades to, the counters two and three levels up, the
building's headcount and the licence's committed money — in its final state before
the response is sent, so the very first read afterwards is the settled picture.
There is no publish to wait for, no clock to advance and no second write to nudge
a stale counter into agreement.

These tests exercise that guarantee against a live service over HTTP.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.constants import (
    CLOCK_IN_WINDOW,
    STANDARD_PRICE_PER_SEAT_CENTS,
    TERM_ADD_DROP_CUTOFF_DATE,
)
from test_helpers.types import (
    EnrollmentState,
    GradeBand,
    IdentityStatus,
    MeetingDay,
    RosterStatus,
    SeatStatus,
)

# A school day inside the add/drop window, two weeks after the class was rostered.
WITHDRAWAL_DATE = "2026-09-01"
CLOCK_ON_WITHDRAWAL = WITHDRAWAL_DATE + "T00:00:00Z"


def test_one_withdrawal_leaves_six_aggregates_already_settled(api):
    """A family moves away and the whole picture is square before anybody reads it.

    The withdrawal cascade runs four hops in the one request: the enrollment
    "becomes `DROPPED` when the withdrawal date is on or before the clock date" with
    the withdrawal date stamped as its `drop_effective_date`; the seat is released
    with "`refunded_charge_cents` set to the account's `seat_charge_cents` when the
    clock date is on or before the term's `add_drop_cutoff_date`", the identity
    becomes `DEPROVISIONED` and `deprovision_scheduled_date` carries the withdrawal
    date; then "each release decrements the owning allocation's `consumed_seats` by
    one and then recomputes the license's `consumed_seats`, `unallocated_seats`,
    `committed_charge_cents`". Committed money "is the sum, over every app account
    of that license regardless of `seat_status`, of that account's
    `seat_charge_cents` minus its `refunded_charge_cents`", so a charge fully
    refunded nets to zero, while the building's `enrolled_student_count` and the
    section's `active_enrollment_count` are recomputed by the same request.

    Design: Corner/Consistency Model/immediate_consistency_withdrawal_cascade_visible_to_the_very_next_read
    """
    world = fx.rostered_section(
        api,
        clock=CLOCK_IN_WINDOW,
        student_count=1,
        grade_level=4,
        period_index=3,
        meeting_days=list(MeetingDay.MWF),
        max_seats=5,
    )
    vendor_app = fx.create_vendor_app(
        api,
        world["term_id"],
        total_seats=4,
        price_per_seat_cents=STANDARD_PRICE_PER_SEAT_CENTS,
        grade_band_scope=[GradeBand.ELEMENTARY],
    )
    fx.activate_license(api, vendor_app["id"])
    allocation = fx.allocation_for_school(api, vendor_app["id"], world["school_id"])
    account = fx.provision_account(
        api,
        allocation["id"],
        vendor_app_id=vendor_app["id"],
        student_id=world["student_id"],
    )
    assert account["seat_charge_cents"] == STANDARD_PRICE_PER_SEAT_CENTS

    fx.set_clock(api, CLOCK_ON_WITHDRAWAL)
    assert WITHDRAWAL_DATE <= TERM_ADD_DROP_CUTOFF_DATE

    withdrawn = validate_success(
        api.withdraw_student(
            world["student_id"],
            f.withdrawal_payload(WITHDRAWAL_DATE),
            users.DATA_GOVERNANCE_OFFICER,
        )
    )
    assert withdrawn["enrollment_state"] == EnrollmentState.WITHDRAWN
    assert withdrawn["withdrawal_effective_date"] == WITHDRAWAL_DATE

    enrollment = validate_success(
        api.get_enrollment(world["enrollment_id"], users.ROSTER_OPERATOR)
    )
    assert enrollment["roster_status"] == RosterStatus.DROPPED
    assert enrollment["drop_effective_date"] == WITHDRAWAL_DATE

    settled_account = fx.read_account(api, account["id"])
    assert settled_account["seat_status"] == SeatStatus.RELEASED
    assert settled_account["refunded_charge_cents"] == STANDARD_PRICE_PER_SEAT_CENTS
    assert settled_account["identity_status"] == IdentityStatus.DEPROVISIONED
    assert settled_account["deprovision_scheduled_date"] == WITHDRAWAL_DATE

    settled_allocation = fx.read_allocation(api, allocation["id"])
    assert settled_allocation["consumed_seats"] == 0
    assert settled_allocation["allocated_seats"] == 4

    settled_licence = fx.read_vendor_app(api, vendor_app["id"])
    assert settled_licence["consumed_seats"] == 0
    assert settled_licence["unallocated_seats"] == 0
    assert settled_licence["committed_charge_cents"] == 0

    building = validate_success(
        api.get_school(world["school_id"], users.ROSTER_OPERATOR)
    )
    assert building["enrolled_student_count"] == 0

    section = validate_success(
        api.get_section(world["section_id"], users.ROSTER_OPERATOR)
    )
    assert section["active_enrollment_count"] == 0


def test_one_provisioning_lands_on_both_ancestors_without_moving_the_grant(api):
    """Minting one identity charges the licence at once and leaves the grant alone.

    Provisioning "increments the allocation's `consumed_seats` by one", "recomputes
    the license's `consumed_seats` and `committed_charge_cents`" and freezes
    `seat_charge_cents` "at the per-seat rate for the provisioning clock date" — and
    "a seat priced on a date on or before the term's `add_drop_cutoff_date` costs the
    full `price_per_seat_cents`". Consumption is not allocation: the licence's
    `unallocated_seats` is "`total_seats` minus the sum of `allocated_seats` across
    its allocations minus the sum of `borrowed_seats`", none of which a provisioning
    touches, so the building's grant and the district pool stay exactly where the
    activation split left them.

    Design: Corner/Consistency Model/immediate_consistency_provisioning_charge_reaches_parent_before_next_read
    """
    world = fx.licensed_building(
        api,
        clock=CLOCK_IN_WINDOW,
        student_count=1,
        grade_level=4,
        total_seats=4,
        price_per_seat_cents=STANDARD_PRICE_PER_SEAT_CENTS,
    )
    before = fx.read_vendor_app(api, world["vendor_app_id"])
    assert before["consumed_seats"] == 0
    assert before["committed_charge_cents"] == 0
    assert before["unallocated_seats"] == 0
    assert before["version"] == 2

    account = validate_success(
        api.create_app_account(
            f.app_account_payload(
                world["allocation_id"], before["version"], student_id=world["student_id"]
            ),
            users.IDENTITY_ADMIN,
        ),
        201,
    )
    assert account["seat_charge_cents"] == STANDARD_PRICE_PER_SEAT_CENTS
    assert account["seat_status"] == SeatStatus.RESERVED

    after = fx.read_vendor_app(api, world["vendor_app_id"])
    assert after["consumed_seats"] == 1
    assert after["committed_charge_cents"] == account["seat_charge_cents"]
    assert after["unallocated_seats"] == 0
    assert after["version"] == 3

    allocation = fx.read_allocation(api, world["allocation_id"])
    assert allocation["consumed_seats"] == 1
    assert allocation["allocated_seats"] == 4
    assert allocation["borrowed_seats"] == 0

    rows, meta = validate_paginated(
        api.list_app_accounts(
            users.IDENTITY_ADMIN,
            building_allocation_id=world["allocation_id"],
            seat_status=SeatStatus.RESERVED,
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == account["id"]
