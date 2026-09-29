"""
Proportional seat allocation across three equal elementary buildings.

Seven purchased seats do not divide evenly over three buildings that each hold
two enrolled students. The district contract fixes what happens to the leftover
seat: every building is granted the floor of its exact share first, and only then
is the single remaining seat handed to the top of the recipients ranking. These
tests hold the service to that order, and to the seat conservation it guarantees.
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
    VendorAppStatus,
)

TOTAL_SEATS = 7
HEADCOUNT_PER_BUILDING = 2


def _district_of_three_equal_buildings(api):
    """
    Three ACTIVE elementary buildings registered in the order Alpha, Bravo,
    Charlie, each holding exactly two ENROLLED students, under a DRAFT
    proportional-headcount licence for seven seats that is then activated.

    Returns the three building ids, the licence and the activated licence record.
    """
    fx.set_clock(api, c.CLOCK_STARTUP_DEFAULT, users.ROSTER_OPERATOR)

    school_a = fx.create_school(
        api,
        grade_band=GradeBand.ELEMENTARY,
        name="Alpha Elementary",
        sis_school_id="SCH-A",
        building_code="AAA",
    )
    school_b = fx.create_school(
        api,
        grade_band=GradeBand.ELEMENTARY,
        name="Bravo Elementary",
        sis_school_id="SCH-B",
        building_code="BBB",
    )
    school_c = fx.create_school(
        api,
        grade_band=GradeBand.ELEMENTARY,
        name="Charlie Elementary",
        sis_school_id="SCH-C",
        building_code="CCC",
    )

    # Registering the licence needs a term; seat allocation does not need it open.
    term = fx.create_term(api)

    fx.create_student(
        api, school_a["id"], grade_level=3, sis_student_id="STU-A1",
        first_name="Ada", last_name="Ahmed", date_of_birth="2017-01-05",
    )
    fx.create_student(
        api, school_a["id"], grade_level=3, sis_student_id="STU-A2",
        first_name="Abel", last_name="Arnesen", date_of_birth="2017-02-06",
    )
    fx.create_student(
        api, school_b["id"], grade_level=3, sis_student_id="STU-B1",
        first_name="Bea", last_name="Barros", date_of_birth="2017-03-07",
    )
    fx.create_student(
        api, school_b["id"], grade_level=3, sis_student_id="STU-B2",
        first_name="Ben", last_name="Bianchi", date_of_birth="2017-04-08",
    )
    fx.create_student(
        api, school_c["id"], grade_level=3, sis_student_id="STU-C1",
        first_name="Cleo", last_name="Costa", date_of_birth="2017-05-09",
    )
    fx.create_student(
        api, school_c["id"], grade_level=3, sis_student_id="STU-C2",
        first_name="Cai", last_name="Chen", date_of_birth="2017-06-10",
    )

    vendor_app = fx.create_vendor_app(
        api,
        term["id"],
        total_seats=TOTAL_SEATS,
        price_per_seat_cents=1000,
        grade_band_scope=[GradeBand.ELEMENTARY],
        name="ReadRight",
        vendor_code="RRX",
        rostering_standard=RosteringStandard.ONEROSTER_CSV_1P1,
        identifier_strategy=IdentifierStrategy.SIS_ID,
        username_domain="apps.district.k12",
        seat_model=SeatModel.PER_STUDENT,
        allocation_policy=AllocationPolicy.PROPORTIONAL_HEADCOUNT,
        overage_policy=OveragePolicy.BLOCK,
    )
    activated = fx.activate_license(api, vendor_app["id"])

    return {
        "school_a_id": school_a["id"],
        "school_b_id": school_b["id"],
        "school_c_id": school_c["id"],
        "vendor_app_id": vendor_app["id"],
        "vendor_app": activated,
    }


def test_the_single_leftover_seat_goes_to_the_first_building_in_the_ranking(api):
    """Seven seats over three two-student buildings are cut 3 / 2 / 2, not 2 / 2 / 2.

    Each building's exact share is "`total_seats` multiplied by that building's
    `enrolled_student_count` and divided by the district headcount, held as an
    exact fraction with no rounding at all" — seven times two over six. "Each
    building is then granted the **floor** of its exact share", giving 2, 2 and 2,
    and the one leftover seat is "handed out one seat at a time to buildings
    ranked by the fractional part of their exact share descending, breaking ties
    first by `enrolled_student_count` descending and then by `created_at`
    ascending". All three fractional parts and headcounts tie, so the ranking
    falls through to creation order and Alpha takes the leftover seat. "Rounding
    each raw share to the nearest whole seat is forbidden, because per-share
    rounding does not conserve the purchased total."

    Design: Difficulty/combinatorial_formula/building_seat_allocation_remainder_rounding_order
    """
    world = _district_of_three_equal_buildings(api)

    a.assert_vendor_app(world["vendor_app"], status=VendorAppStatus.ACTIVE)

    alpha = fx.allocation_for_school(api, world["vendor_app_id"], world["school_a_id"])
    bravo = fx.allocation_for_school(api, world["vendor_app_id"], world["school_b_id"])
    charlie = fx.allocation_for_school(api, world["vendor_app_id"], world["school_c_id"])

    assert alpha["allocated_seats"] == 3, (
        "the earliest-created building takes the leftover seat, so Alpha holds 3"
    )
    assert alpha["allocated_seats"] != 2, (
        "rounding each 2.3333 share to the nearest whole seat would leave Alpha "
        "on 2 and strand a purchased seat"
    )
    assert bravo["allocated_seats"] == 2
    assert charlie["allocated_seats"] == 2

    granted = (
        alpha["allocated_seats"] + bravo["allocated_seats"] + charlie["allocated_seats"]
    )
    assert granted == TOTAL_SEATS, (
        f"the three grants must conserve the seven purchased seats, got {granted}"
    )
    assert granted != 6, (
        "a floor-only split that never distributes the leftover strands one seat"
    )

    licence = fx.read_vendor_app(api, world["vendor_app_id"])
    a.assert_seat_counters(licence, consumed_seats=0, unallocated_seats=0)
    assert licence["total_seats"] == TOTAL_SEATS


def test_every_building_allocation_records_its_headcount_snapshot_and_hard_cap(api):
    """Activation writes one allocation row per eligible building, each cut from the same headcount.

    "Each created allocation records the `vendor_app_id` of its licence and the
    `school_id` of its building ... together with its `allocated_seats`, a
    `consumed_seats` and `borrowed_seats` of zero, a `hard_cap` flag that is true
    exactly when the licence's `overage_policy` was `BLOCK` at the moment the row
    was written, and an `eligible_headcount_snapshot` holding the building's
    `enrolled_student_count` as observed during the split." Three ACTIVE
    elementary buildings are eligible, so exactly three rows exist and each one
    snapshots the two students it held.

    Design: Difficulty/combinatorial_formula/building_seat_allocation_remainder_rounding_order
    """
    world = _district_of_three_equal_buildings(api)

    response = api.list_building_allocations(
        users.IDENTITY_ADMIN, vendor_app_id=world["vendor_app_id"], limit=100
    )
    rows, meta = validate_paginated(response)

    assert len(rows) == 3, f"expected one allocation per eligible building, got {len(rows)}"
    a.assert_pagination_meta(meta, total_count=3)

    assert {row["school_id"] for row in rows} == {
        world["school_a_id"],
        world["school_b_id"],
        world["school_c_id"],
    }

    for row in rows:
        a.assert_allocation(
            row,
            vendor_app_id=world["vendor_app_id"],
            eligible_headcount_snapshot=HEADCOUNT_PER_BUILDING,
            consumed_seats=0,
            borrowed_seats=0,
            hard_cap=True,
        )
