"""
The renewal invoice projection at the volume-discount tier boundary.

A district that has committed exactly 2,000,000 cents of seat charge sits on the
inclusive floor of the ten-percent discount tier, and it still owns two seats it
never allocated to any building. The invoice the vendor negotiation starts from is
only well defined because the seven steps run in one pinned sequence: the discount
is floored off the gross, the platform fee is ceilinged off the *net*, and the
shelfware credit is floored and subtracted last. These tests hold each figure to
its exact cent.
"""

from prd_bench_local_runner.testing import validate_success

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
)

PRICE_PER_SEAT_CENTS = 500000
TOTAL_SEATS = 6
BLOCK_SEATS = 2

GROSS_SEAT_CENTS = 2000000
DISCOUNT_RATE = 0.10
DISCOUNT_CENTS = 200000
NET_SEAT_CENTS = 1800000
PLATFORM_FEE_CENTS = 54000
SHELFWARE_CREDIT_CENTS = 250000
INVOICE_TOTAL_CENTS = 1604000

FEE_ON_GROSS_CENTS = 60000
INVOICE_TOTAL_UNDER_FEE_ON_GROSS = 1610000


def _district_committed_to_the_tier_boundary(api):
    """
    Two ACTIVE elementary buildings inside an ACTIVE Fall 2026 term, under an
    ACTIVE fixed-block licence of six seats at 500,000 cents each. The waterfall
    grants two seats to each building and leaves two seats unallocated; four
    accounts are then provisioned inside the add/drop window, one per student, so
    the licence's committed charge lands exactly on 2,000,000 cents.

    Returns the licence id together with the two building and allocation ids.
    """
    fx.set_clock(api, c.CLOCK_STARTUP_DEFAULT, users.IDENTITY_ADMIN)

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
    term = fx.create_active_term(api)

    student_a1 = fx.create_student(
        api, school_a["id"], grade_level=3, sis_student_id="STU-A1",
        first_name="Ada", last_name="Ahmed", date_of_birth="2017-01-05",
    )
    student_a2 = fx.create_student(
        api, school_a["id"], grade_level=3, sis_student_id="STU-A2",
        first_name="Abel", last_name="Arnesen", date_of_birth="2017-02-06",
    )
    student_b1 = fx.create_student(
        api, school_b["id"], grade_level=3, sis_student_id="STU-B1",
        first_name="Bea", last_name="Barros", date_of_birth="2017-03-07",
    )
    student_b2 = fx.create_student(
        api, school_b["id"], grade_level=3, sis_student_id="STU-B2",
        first_name="Ben", last_name="Bianchi", date_of_birth="2017-04-08",
    )

    vendor_app = fx.create_vendor_app(
        api,
        term["id"],
        total_seats=TOTAL_SEATS,
        price_per_seat_cents=PRICE_PER_SEAT_CENTS,
        grade_band_scope=[GradeBand.ELEMENTARY],
        name="SciSpark",
        vendor_code="SSX",
        rostering_standard=RosteringStandard.VENDOR_NATIVE_JSON,
        identifier_strategy=IdentifierStrategy.SIS_ID,
        username_domain="apps.district.k12",
        seat_model=SeatModel.PER_STUDENT,
        allocation_policy=AllocationPolicy.FIXED_BUILDING_BLOCKS,
        block_seats=BLOCK_SEATS,
        overage_policy=OveragePolicy.BLOCK,
    )
    fx.activate_license(api, vendor_app["id"])

    allocation_a = fx.allocation_for_school(api, vendor_app["id"], school_a["id"])
    allocation_b = fx.allocation_for_school(api, vendor_app["id"], school_b["id"])

    accounts = [
        fx.provision_account(
            api, allocation_a["id"], vendor_app_id=vendor_app["id"],
            student_id=student_a1["id"],
        ),
        fx.provision_account(
            api, allocation_a["id"], vendor_app_id=vendor_app["id"],
            student_id=student_a2["id"],
        ),
        fx.provision_account(
            api, allocation_b["id"], vendor_app_id=vendor_app["id"],
            student_id=student_b1["id"],
        ),
        fx.provision_account(
            api, allocation_b["id"], vendor_app_id=vendor_app["id"],
            student_id=student_b2["id"],
        ),
    ]

    return {
        "vendor_app_id": vendor_app["id"],
        "allocation_a_id": allocation_a["id"],
        "allocation_b_id": allocation_b["id"],
        "accounts": accounts,
    }


def test_four_full_price_seats_commit_the_tier_two_gross_and_leave_two_seats_unallocated(api):
    """Four seats bought inside the add/drop window commit 2,000,000 cents while two seats stay in the district pool.

    "A seat priced on a date on or before the term's `add_drop_cutoff_date` costs
    the full `price_per_seat_cents`", so each of the four accounts freezes
    `seat_charge_cents` at 500,000 on the 1 August clock, well before the
    15 September cutoff. `VendorApp.committed_charge_cents` "is the sum, over
    every app account of that licence regardless of `seat_status`, of that
    account's `seat_charge_cents` minus its `refunded_charge_cents`", which is
    exactly 2,000,000. The fixed-block waterfall grants "the smaller of
    `block_seats` and the seats still unallocated" to each of the two buildings,
    so `unallocated_seats` — "`total_seats` minus the sum of `allocated_seats`
    ... minus the sum of `borrowed_seats`" — settles at two.

    Design: Difficulty/combinatorial_formula/license_invoice_projection_pinned_evaluation_order
    """
    world = _district_committed_to_the_tier_boundary(api)

    for account in world["accounts"]:
        a.assert_app_account(
            account,
            seat_charge_cents=PRICE_PER_SEAT_CENTS,
            refunded_charge_cents=0,
        )

    licence = fx.read_vendor_app(api, world["vendor_app_id"])
    a.assert_seat_counters(
        licence,
        consumed_seats=4,
        unallocated_seats=2,
        committed_charge_cents=GROSS_SEAT_CENTS,
    )

    allocation_a = fx.read_allocation(api, world["allocation_a_id"])
    allocation_b = fx.read_allocation(api, world["allocation_b_id"])
    a.assert_allocation(allocation_a, allocated_seats=2, consumed_seats=2, borrowed_seats=0)
    a.assert_allocation(allocation_b, allocated_seats=2, consumed_seats=2, borrowed_seats=0)


def test_a_gross_of_exactly_two_million_takes_the_ten_percent_tier(api):
    """The discount tier floors are inclusive, so a gross sitting exactly on 2,000,000 discounts at ten percent.

    Step (1) makes "the gross seat charge ... the licence's
    `committed_charge_cents`, already net of refunds". Step (2) chooses the rate
    "from that gross figure by tier, with inclusive floors: 0.15 at 5000000 cents
    or more, 0.10 at 2000000 cents or more, 0.05 at 500000 cents or more". Step
    (3) makes the discount "the gross figure multiplied by that rate, rounded
    down", and step (4) makes the net "the gross figure minus the discount". A
    gross of exactly 2,000,000 therefore takes 0.10 and not 0.05 — "a gross of
    2000000 takes 0.10, while a gross of 1999999 takes 0.05."

    Design: Difficulty/combinatorial_formula/license_invoice_projection_pinned_evaluation_order
    """
    world = _district_committed_to_the_tier_boundary(api)

    summary = validate_success(
        api.get_renewal_summary(world["vendor_app_id"], users.DATA_GOVERNANCE_OFFICER)
    )

    assert summary["gross_seat_cents"] == GROSS_SEAT_CENTS
    a.assert_integer_cents(summary["gross_seat_cents"], "gross_seat_cents")

    assert summary["discount_rate"] == DISCOUNT_RATE, (
        "an inclusive tier floor puts a gross of exactly 2,000,000 in the "
        "ten-percent band, not the five-percent one"
    )
    assert summary["discount_cents"] == DISCOUNT_CENTS
    a.assert_integer_cents(summary["discount_cents"], "discount_cents")
    assert summary["net_seat_cents"] == NET_SEAT_CENTS
    a.assert_integer_cents(summary["net_seat_cents"], "net_seat_cents")


def test_the_platform_fee_is_taken_on_the_net_and_the_shelfware_credit_is_subtracted_last(api):
    """The invoice reads 1,604,000 cents because the fee follows the discount and the credit comes last.

    Step (5) makes the platform fee "the larger of a 25000-cent floor and the net
    seat charge multiplied by 0.03 rounded up" — the ceiling of 54,000.0 on the
    1,800,000 net, which clears the floor. Step (6) makes the shelfware credit
    "the smaller of the net seat charge and the licence's `unallocated_seats`
    multiplied by its `price_per_seat_cents` multiplied by 0.25, rounded down" —
    two unallocated seats at 500,000 cents give 250,000. Step (7) makes the total
    "the net seat charge plus the platform fee minus the shelfware credit".
    "The order is the contract: the volume discount is applied before the platform
    fee, and the shelfware credit is applied last, after the fee floor has already
    been resolved. Computing the fee on the gross figure first, or subtracting the
    credit before the fee is resolved, produces different totals and is wrong."

    Design: Difficulty/combinatorial_formula/license_invoice_projection_pinned_evaluation_order
    """
    world = _district_committed_to_the_tier_boundary(api)

    summary = validate_success(
        api.get_renewal_summary(world["vendor_app_id"], users.DATA_GOVERNANCE_OFFICER)
    )

    assert summary["platform_fee_cents"] == PLATFORM_FEE_CENTS, (
        "the three-percent fee is taken on the 1,800,000 net seat charge"
    )
    assert summary["platform_fee_cents"] != FEE_ON_GROSS_CENTS, (
        "charging three percent of the gross would bill 60,000 cents of fee"
    )
    assert summary["platform_fee_cents"] > c.PLATFORM_FEE_MINIMUM_CENTS

    assert summary["shelfware_credit_cents"] == SHELFWARE_CREDIT_CENTS
    a.assert_integer_cents(summary["shelfware_credit_cents"], "shelfware_credit_cents")

    assert summary["invoice_total_cents"] == INVOICE_TOTAL_CENTS, (
        "1,800,000 net plus 54,000 fee less 250,000 credit is 1,604,000"
    )
    assert summary["invoice_total_cents"] != INVOICE_TOTAL_UNDER_FEE_ON_GROSS, (
        "resolving the fee against the gross before the discount would invoice "
        "1,610,000 cents"
    )
    assert (
        summary["net_seat_cents"]
        + summary["platform_fee_cents"]
        - summary["shelfware_credit_cents"]
        == INVOICE_TOTAL_CENTS
    )
