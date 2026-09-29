"""
Seat money, roster arithmetic and identity-clock calculations.

Every figure this service publishes is an integer the contract derives from a
pinned sequence of steps: the roster scope a vendor extract sees, the per-seat
rate frozen onto a licensed seat, the username a subject is issued, the instant a
temporary credential dies, the way purchased seats are cut across buildings, the
invoice the renewal conversation opens with, and the score that recommends
renewing or dropping the product. These tests hold the service to the exact
integers, never to a range.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as errors
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.assertions import (
    assert_account_axes,
    assert_contains_id,
    assert_integer_cents,
)
from test_helpers.types import (
    AllocationPolicy,
    GradeBand,
    IdentifierStrategy,
    OveragePolicy,
    PasswordState,
    RenewalBasis,
    RenewalRecommendation,
    RunType,
    SchoolStatus,
    SeatStatus,
    SectionStatus,
    SyncRunState,
    TermState,
    IdentityStatus,
    VendorAppStatus,
)

# The rollover-eligible instant for a term ending 18 December 2026, and the two
# instants that bracket a 72-hour temporary credential minted at term-planning
# time.
CLOCK_ON_TERM_END_MORNING = "2026-12-18T09:00:00Z"
CLOCK_ONE_MILLISECOND_BEFORE_TEMP_EXPIRY = "2026-08-03T23:59:59.999Z"
CLOCK_AT_TEMP_EXPIRY = "2026-08-04T00:00:00.000Z"


def test_extract_counts_omit_cancelled_sections_and_dropped_roster_rows(api):
    """A vendor extract prices only the roster that is really there.

    Scope resolution admits the sections of the licence's term "whose `status` is
    `ACTIVE` for a `FULL` or `DELTA` run" and states that "`CANCELLED` sections
    and closed buildings are never in scope", while the enrollments in scope are
    those "whose `roster_status` is `PENDING_ADD`, `ACTIVE` or `PENDING_DROP`" —
    "`DROPPED` rows are excluded". So a building holding two sections and two
    enrollment rows, one section cancelled and one row dropped, extracts one
    section and one enrollment. The transform then counts "the number of feed
    sections, plus the number of in-scope students restricted to feed sections,
    plus the number of in-scope teachers", and the teachers in scope "are empty
    unless the licence's `seat_model` is `PER_STUDENT_AND_TEACHER`", giving
    1 + 1 + 0 = 2. The single subject's provisional charge date is 20 August
    2026, on or before the 15 September add/drop cutoff, so it "costs the full
    `price_per_seat_cents`" of 1000 cents.

    Design: Corner/calculations/sync_scope_resolution_excludes_dropped_and_cancelled
    """
    fx.set_clock(api, c.CLOCK_BEFORE_TERM)
    school = fx.create_school(api, grade_band=GradeBand.ELEMENTARY)
    term = fx.create_active_term(api)
    teacher = fx.create_teacher(api, school["id"], full_name="Dana Reed")
    live_section = fx.create_section(
        api, school["id"], term["id"], primary_teacher_id=teacher["id"],
        period_index=3, max_seats=5,
    )
    cancelled_section = fx.create_section(
        api, school["id"], term["id"], primary_teacher_id=teacher["id"],
        period_index=6, max_seats=5,
    )
    stays = fx.create_student(api, school["id"], grade_level=4, last_name="Nakamura")
    leaves = fx.create_student(api, school["id"], grade_level=4, last_name="Raman")

    fx.set_clock(api, c.CLOCK_IN_WINDOW)
    fx.create_enrollment(api, live_section["id"], stays["id"], "2026-08-20")
    withdrawn_row = fx.create_enrollment(
        api, live_section["id"], leaves["id"], "2026-08-20"
    )
    fx.drop_enrollment(api, withdrawn_row["id"], "2026-08-20")
    validate_success(
        api.update_section(
            cancelled_section["id"],
            f.section_patch(status=SectionStatus.CANCELLED),
            users.ROSTER_OPERATOR,
        ),
        200,
    )

    vendor_app = fx.create_vendor_app(
        api, term["id"], total_seats=4,
        price_per_seat_cents=c.STANDARD_PRICE_PER_SEAT_CENTS,
        grade_band_scope=[GradeBand.ELEMENTARY],
    )
    vendor_app = fx.activate_license(api, vendor_app["id"])

    run = fx.open_sync_run(api, vendor_app["id"], run_type=RunType.FULL)
    assert run["extracted_section_count"] == 1
    assert run["extracted_enrollment_count"] == 1

    transformed = fx.transform_run(api, run["id"])
    assert transformed["state"] == SyncRunState.TRANSFORMED
    assert transformed["blocking_error_count"] == 0
    assert transformed["advisory_error_count"] == 0
    assert transformed["transformed_record_count"] == 2
    assert transformed["projected_seat_delta"] == 1
    assert_integer_cents(
        transformed["projected_charge_cents"], "sync_run.projected_charge_cents"
    )
    assert transformed["projected_charge_cents"] == 1000


def test_seat_provisioned_after_the_cutoff_is_prorated_to_the_exact_cent(api):
    """A seat bought in October costs the remaining slice of the term, rounded up.

    The contract fixes the rate: "A seat priced on a date on or before the term's
    `add_drop_cutoff_date` costs the full `price_per_seat_cents`. A seat priced
    after the cutoff is prorated: take `price_per_seat_cents`, multiply by the
    remaining days, divide by the total days, and round the result up to the next
    whole cent." For the Fall 2026 term — 10 August through 18 December 2026, 131
    total days — "a seat priced on 1 October 2026 has 79 remaining days and costs
    the ceiling of 603.0534, which is 604 cents". The licence's
    `committed_charge_cents` is then "the sum, over every app account of that
    licence regardless of `seat_status`, of that account's `seat_charge_cents`
    minus its `refunded_charge_cents`", so it carries that same per-subject
    integer.

    Design: Corner/calculations/seat_charge_prorated_after_add_drop_cutoff
    """
    world = fx.licensed_building(
        api,
        clock=c.CLOCK_BEFORE_TERM,
        student_count=1,
        total_seats=4,
        price_per_seat_cents=c.STANDARD_PRICE_PER_SEAT_CENTS,
    )
    fx.set_clock(api, c.CLOCK_OCTOBER_FIRST)

    account = fx.provision_account(
        api,
        world["allocation_id"],
        vendor_app_id=world["vendor_app_id"],
        student_id=world["student_id"],
    )
    assert_integer_cents(account["seat_charge_cents"], "app_account.seat_charge_cents")
    assert account["seat_charge_cents"] == c.PRORATED_RATE_ON_OCTOBER_FIRST
    assert account["seat_charge_cents"] == 604
    assert account["refunded_charge_cents"] == 0

    licence = fx.read_vendor_app(api, world["vendor_app_id"])
    assert licence["committed_charge_cents"] == 604
    assert licence["consumed_seats"] == 1


def test_username_is_truncated_before_the_collision_suffix_is_appended(api):
    """Two similarly named children get distinct, reusable single sign-on names.

    Normalisation runs "in exactly this order: lower-case it; replace every
    maximal run of characters outside the set of lower-case letters and digits
    with a single period; strip leading periods; truncate to 20 characters; and
    only then strip trailing periods", and a collision is resolved with "the
    smallest whole number not below 2". The contract works this very case:
    `Vandenberghe-Mwangi.M` becomes the 21-character `vandenberghe.mwangi.m`,
    truncates to `vandenberghe.mwangi.` and loses its trailing period, so the
    first child is `vandenberghe.mwangi@apps.district.k12` and the second
    receives `vandenberghe.mwangi+2@apps.district.k12` — "a 21-character local
    part, which is correct". A username is taken only while "another account of
    the same licence holds it with a `seat_status` other than `RELEASED`", so
    once the first seat goes back the base form is issued again.

    Design: Corner/calculations/username_derivation_truncates_before_collision_suffix
    """
    fx.set_clock(api, c.CLOCK_BEFORE_TERM)
    school = fx.create_school(api, grade_band=GradeBand.ELEMENTARY)
    term = fx.create_active_term(api)
    hyphenated = fx.create_student(
        api, school["id"], grade_level=4,
        first_name="Maria-Jo", last_name="Vandenberghe-Mwangi",
    )
    spaced = fx.create_student(
        api, school["id"], grade_level=4,
        first_name="Maria", last_name="Vandenberghe Mwangi",
    )
    vendor_app = fx.create_vendor_app(
        api, term["id"], total_seats=4,
        grade_band_scope=[GradeBand.ELEMENTARY],
        identifier_strategy=IdentifierStrategy.EMAIL_LOCALPART,
        username_domain="apps.district.k12",
    )
    vendor_app = fx.activate_license(api, vendor_app["id"])
    allocation = fx.allocation_for_school(api, vendor_app["id"], school["id"])
    fx.set_clock(api, c.CLOCK_IN_WINDOW)

    first = fx.provision_account(
        api, allocation["id"], vendor_app_id=vendor_app["id"],
        student_id=hyphenated["id"],
    )
    assert first["username"] == "vandenberghe.mwangi@apps.district.k12"

    second = fx.provision_account(
        api, allocation["id"], vendor_app_id=vendor_app["id"],
        student_id=spaced["id"],
    )
    assert second["username"] == "vandenberghe.mwangi+2@apps.district.k12"

    released = fx.release_seat(api, first["id"])
    assert released["username"] == "vandenberghe.mwangi@apps.district.k12"

    reissued = fx.provision_account(
        api, allocation["id"], vendor_app_id=vendor_app["id"],
        student_id=hyphenated["id"],
    )
    assert reissued["username"] == "vandenberghe.mwangi@apps.district.k12"


def test_temporary_password_is_live_one_millisecond_before_its_expiry_instant(api):
    """A temporary credential minted on 1 August dies exactly at midnight on the 4th.

    "At provisioning the account is minted with a temporary password:
    `password_state` is `TEMP_SET` and `password_expires_at` is the account's
    `created_at` plus the subject building's `temp_password_ttl_hours`", the
    district default being 72 hours, and expiry is evaluated on every
    single-account read with the comparison "that the clock instant is at or
    after `password_expires_at`". The contract works the boundary itself: "an
    account created at `2026-08-01T00:00:00.000Z` under a 72-hour temporary
    lifetime expires at `2026-08-04T00:00:00.000Z`, so at
    `2026-08-03T23:59:59.999Z` it is still `TEMP_SET` and at
    `2026-08-04T00:00:00.000Z` it is `EXPIRED`". Expiry moves only the password
    sub-state, so neither the seat axis nor the identity axis reacts.

    Design: Corner/calculations/temp_password_expiry_boundary_is_inclusive
    """
    world = fx.seated_account(api, clock=c.CLOCK_BEFORE_TERM, total_seats=4)
    account = world["account"]
    assert account["password_state"] == PasswordState.TEMP_SET
    assert account["password_expires_at"] == "2026-08-04T00:00:00.000Z"

    fx.set_clock(api, CLOCK_ONE_MILLISECOND_BEFORE_TEMP_EXPIRY)
    still_live = fx.read_account(api, world["account_id"])
    assert_account_axes(
        still_live,
        seat_status=SeatStatus.RESERVED,
        identity_status=IdentityStatus.PENDING_PROVISION,
        password_state=PasswordState.TEMP_SET,
    )

    fx.set_clock(api, CLOCK_AT_TEMP_EXPIRY)
    expired = fx.read_account(api, world["account_id"])
    assert_account_axes(
        expired,
        seat_status=SeatStatus.RESERVED,
        identity_status=IdentityStatus.PENDING_PROVISION,
        password_state=PasswordState.EXPIRED,
    )


def test_licence_cannot_be_activated_when_no_building_matches_its_grade_band(api):
    """A licence bought for middle schools cannot go live in a district that has none open.

    Activation "computes the candidate buildings: every `School` whose `status` is
    `ACTIVE` and whose `grade_band` appears in the licence's `grade_band_scope`",
    and "if no building is eligible the activation is refused with
    `ERR_NO_ELIGIBLE_BUILDINGS` and the licence stays `DRAFT`". A district whose
    only middle school is closed therefore has an empty candidate set even though
    an elementary building is open, and the refused activation writes nothing: no
    allocations, no version bump, no activating officer recorded.

    Design: Corner/calculations/building_seat_allocation_no_eligible_buildings_rejected
    """
    fx.set_clock(api, c.CLOCK_BEFORE_TERM)
    fx.create_school(api, grade_band=GradeBand.ELEMENTARY)
    closed_middle_school = fx.create_school(api, grade_band=GradeBand.MIDDLE)
    validate_success(
        api.update_school(
            closed_middle_school["id"],
            f.school_policy_patch(status=SchoolStatus.CLOSED),
            users.ROSTER_OPERATOR,
        ),
        200,
    )
    term = fx.create_active_term(api)
    vendor_app = fx.create_vendor_app(
        api, term["id"], total_seats=6, grade_band_scope=[GradeBand.MIDDLE]
    )

    validate_error(
        api.activate_license(vendor_app["id"], users.DATA_GOVERNANCE_OFFICER),
        errors.ERR_NO_ELIGIBLE_BUILDINGS,
        422,
    )

    untouched = fx.read_vendor_app(api, vendor_app["id"])
    assert untouched["status"] == VendorAppStatus.DRAFT
    assert untouched["version"] == 1
    assert untouched["unallocated_seats"] == 6
    assert untouched["activated_by_user_id"] is None
    assert fx.list_allocations(api, vendor_app["id"]) == []


def test_fixed_block_activation_fills_buildings_in_ranked_order_until_seats_run_out(api):
    """Fixed blocks are handed out largest-building-first and the last one is short-changed.

    Under `FIXED_BUILDING_BLOCKS` the split "walks the candidate buildings in
    order and gives each the smaller of `block_seats` and the seats still
    unassigned, so a later building can receive fewer seats than a block and a
    building can receive zero", the candidate order being "`enrolled_student_count`
    descending, then `created_at` ascending". Seven seats in blocks of three
    across buildings of 2, 1 and 0 children therefore land as 3, 3 and 1, each
    allocation recording the headcount it was cut from and, because the licence
    blocks overage, a `hard_cap` of true. The split "assigns every seat", so the
    licence keeps nothing back.

    Design: Corner/calculations/building_seat_allocation_fixed_blocks_fills_in_order
    """
    world = fx.licensed_district(
        api,
        buildings=[
            {"student_count": 2},
            {"student_count": 1},
            {"student_count": 0},
        ],
        clock=c.CLOCK_BEFORE_TERM,
        total_seats=7,
        license_overrides={
            "allocation_policy": AllocationPolicy.FIXED_BUILDING_BLOCKS,
            "block_seats": 3,
            "overage_policy": OveragePolicy.BLOCK,
        },
    )

    allocations = world["allocations"]
    assert len(allocations) == 3
    ranked = [world["allocations_by_school"][sid] for sid in world["school_ids"]]
    assert [row["allocated_seats"] for row in ranked] == [3, 3, 1]
    assert [row["eligible_headcount_snapshot"] for row in ranked] == [2, 1, 0]
    assert [row["consumed_seats"] for row in ranked] == [0, 0, 0]
    assert [row["borrowed_seats"] for row in ranked] == [0, 0, 0]
    assert [row["hard_cap"] for row in ranked] == [True, True, True]
    assert sum(row["allocated_seats"] for row in allocations) == 7

    licence = world["vendor_app"]
    assert licence["status"] == VendorAppStatus.ACTIVE
    assert licence["unallocated_seats"] == 0


def test_third_seat_borrows_from_the_district_pool_and_the_fourth_is_refused(api):
    """A building over its block borrows a district seat, then the district runs dry.

    Seat admission tests "whether the building's allocation has a free seat,
    meaning `allocated_seats` minus `consumed_seats` is at least one"; if it does
    not and the licence's `overage_policy` is `POOL_FALLBACK`, the request
    "consumes an unallocated district seat instead: `borrowed_seats` on the
    allocation increases by one" and "`unallocated_seats` on the licence falls by
    one", while "if the district pool is empty as well the request is refused with
    `ERR_DISTRICT_SEATS_EXHAUSTED`". A three-seat licence cut into one two-seat
    block therefore seats two children inside the block, borrows the last district
    seat for the third, and turns the fourth away.

    Design: Corner/calculations/seat_admission_pool_fallback_borrows_then_district_exhausted
    """
    world = fx.licensed_building(
        api,
        student_count=4,
        total_seats=3,
        license_overrides={
            "allocation_policy": AllocationPolicy.FIXED_BUILDING_BLOCKS,
            "block_seats": 2,
            "overage_policy": OveragePolicy.POOL_FALLBACK,
        },
    )
    assert world["allocation"]["allocated_seats"] == 2
    assert world["vendor_app"]["unallocated_seats"] == 1

    for student_id in world["student_ids"][:2]:
        fx.provision_account(
            api, world["allocation_id"],
            vendor_app_id=world["vendor_app_id"], student_id=student_id,
        )

    borrowed_seat_account = fx.provision_account(
        api, world["allocation_id"],
        vendor_app_id=world["vendor_app_id"],
        student_id=world["student_ids"][2],
    )
    assert borrowed_seat_account["seat_status"] == SeatStatus.RESERVED

    allocation = fx.read_allocation(api, world["allocation_id"])
    assert allocation["allocated_seats"] == 2
    assert allocation["consumed_seats"] == 3
    assert allocation["borrowed_seats"] == 1

    licence = fx.read_vendor_app(api, world["vendor_app_id"])
    assert licence["unallocated_seats"] == 0
    assert licence["consumed_seats"] == 3

    current_version = fx.vendor_app_version(api, world["vendor_app_id"])
    validate_error(
        api.create_app_account(
            f.app_account_payload(
                world["allocation_id"], current_version,
                student_id=world["student_ids"][3],
            ),
            users.IDENTITY_ADMIN,
        ),
        errors.ERR_DISTRICT_SEATS_EXHAUSTED,
        409,
    )
    assert len(fx.accounts_of_allocation(api, world["allocation_id"])) == 3


def test_zero_retention_rollover_closes_the_archive_window_the_moment_it_opens(api):
    """A term kept for zero days locks its archived roster the instant it rolls over.

    Rollover stamps "`archived_access_expires_at` ... to the term's `end_date` plus
    its `archive_retention_days`, anchored at `00:00:00.000Z` on that date —
    calendar-day addition on a date, not an arithmetic of hours", and then "every
    section of this term whose `status` is `ACTIVE` becomes `ARCHIVED`". Reading an
    archived section is admitted only "while the clock instant is strictly before
    `archived_access_expires_at`". A term ending 18 December 2026 with a retention
    of zero days therefore expires at `2026-12-18T00:00:00.000Z`, so a rollover run
    at nine that same morning archives the section and closes its window in the
    same breath.

    Design: Corner/calculations/archived_access_window_zero_retention_closed_immediately
    """
    world = fx.district_with_active_term(
        api, clock=c.CLOCK_BEFORE_TERM, term_overrides={"archive_retention_days": 0}
    )
    teacher = fx.create_teacher(api, world["school_id"])
    section = fx.create_section(
        api, world["school_id"], world["term_id"], primary_teacher_id=teacher["id"]
    )

    fx.set_clock(api, CLOCK_ON_TERM_END_MORNING)
    rolled_over = fx.rollover_term(api, world["term_id"])
    assert rolled_over["state"] == TermState.ROLLED_OVER
    assert rolled_over["archived_access_expires_at"] == "2026-12-18T00:00:00.000Z"

    archived_rows = validate_success(
        api.list_sections(
            users.ROSTER_OPERATOR,
            term_id=world["term_id"],
            status=SectionStatus.ARCHIVED,
            limit=100,
        ),
        200,
    )
    assert_contains_id(archived_rows, section["id"], "archived sections")

    validate_error(
        api.get_section(section["id"], users.ROSTER_OPERATOR),
        errors.ERR_ARCHIVE_WINDOW_CLOSED,
        409,
    )


def test_small_licence_invoice_falls_to_the_platform_fee_floor_in_the_zero_tier(api):
    """A tiny licence still pays the platform fee floor and scores only on utilisation.

    The invoice runs in seven pinned steps: the gross seat charge is the licence's
    `committed_charge_cents`; the discount rate is "0.00 below" 500000 cents; the
    net is the gross less that discount; "the platform fee is the larger of a
    25000-cent floor and the net seat charge multiplied by 0.03 rounded up"; the
    shelfware credit is "the smaller of the net seat charge and the licence's
    `unallocated_seats` multiplied by its `price_per_seat_cents` multiplied by
    0.25"; and "the invoice total is the net seat charge plus the platform fee
    minus the shelfware credit". Four seats at 1000 cents therefore give a gross of
    4000, a fee of 25000 rather than 120, no credit because every seat is
    allocated, and a total of 29000. Scoring sees four consumed seats out of four
    but nothing provisioned, so "cost per engaged seat ... is null when nothing is
    engaged" and "cost efficiency ... is zero when nothing is engaged", leaving
    0.50 times 1 times 100 — a score of exactly 50.00, which is `RENEGOTIATE`
    because that tier runs "at 40 or above but below 70".

    Design: Corner/calculations/license_invoice_projection_fee_floor_and_zero_tier
    """
    world = fx.licensed_building(
        api,
        student_count=4,
        total_seats=4,
        price_per_seat_cents=c.STANDARD_PRICE_PER_SEAT_CENTS,
    )
    for student_id in world["student_ids"]:
        fx.provision_account(
            api, world["allocation_id"],
            vendor_app_id=world["vendor_app_id"], student_id=student_id,
        )

    summary = validate_success(
        api.get_renewal_summary(
            world["vendor_app_id"], users.VENDOR_INTEGRATION_MANAGER
        ),
        200,
    )
    assert summary["vendor_app_id"] == world["vendor_app_id"]
    assert summary["basis"] == RenewalBasis.FINAL

    assert summary["gross_seat_cents"] == 4000
    assert summary["discount_rate"] == 0.00
    assert summary["discount_cents"] == 0
    assert summary["net_seat_cents"] == 4000
    assert summary["platform_fee_cents"] == c.PLATFORM_FEE_MINIMUM_CENTS
    assert summary["platform_fee_cents"] == 25000
    assert summary["shelfware_credit_cents"] == 0
    assert_integer_cents(summary["invoice_total_cents"], "invoice_total_cents")
    assert summary["invoice_total_cents"] == 29000

    assert summary["consumed_seats"] == 4
    assert summary["provisioned_seats"] == 0
    assert summary["engaged_seats"] == 0
    assert summary["utilization"] == 1.0
    assert summary["engagement"] == 0
    assert summary["cost_per_engaged_cents"] is None
    assert summary["cost_efficiency"] == 0
    assert summary["renewal_score"] == 50.00
    assert summary["renewal_recommendation"] == RenewalRecommendation.RENEGOTIATE


def test_one_seat_of_five_scores_below_the_renegotiate_floor_and_recommends_dropping(api):
    """A licence the district barely touched is recommended for the chopping block.

    "Utilization is the consumed count divided by the licence's `total_seats`", the
    three terms are "weighted — utilization at 0.50, engagement at 0.30 and cost
    efficiency at 0.20 — and the weighted sum is multiplied by 100 and rounded half
    up to two decimal places exactly once, at the very end", and the tiers use
    inclusive floors so `DROP` is anything "below 40". One consumed seat out of
    five purchased gives a utilisation of 0.2 with nothing provisioned and nothing
    engaged, so the score is 0.50 times 0.2 times 100 — exactly 10.00 — and the
    recommendation is `DROP`. The same single seat still carries the full 1000-cent
    list price with the 25000-cent fee floor on top, and no shelfware credit is due
    because activation allocated every purchased seat.

    Design: Corner/calculations/renewal_score_drop_band_below_renegotiate_floor
    """
    world = fx.licensed_building(
        api,
        student_count=1,
        total_seats=5,
        price_per_seat_cents=c.STANDARD_PRICE_PER_SEAT_CENTS,
    )
    fx.provision_account(
        api, world["allocation_id"],
        vendor_app_id=world["vendor_app_id"], student_id=world["student_id"],
    )

    summary = validate_success(
        api.get_renewal_summary(
            world["vendor_app_id"], users.DATA_GOVERNANCE_OFFICER
        ),
        200,
    )
    assert summary["consumed_seats"] == 1
    assert summary["provisioned_seats"] == 0
    assert summary["engaged_seats"] == 0
    assert summary["utilization"] == 0.2
    assert summary["engagement"] == 0
    assert summary["cost_efficiency"] == 0
    assert summary["renewal_score"] == 10.00
    assert summary["renewal_recommendation"] == RenewalRecommendation.DROP

    assert summary["gross_seat_cents"] == 1000
    assert summary["discount_cents"] == 0
    assert summary["net_seat_cents"] == 1000
    assert summary["platform_fee_cents"] == 25000
    assert summary["shelfware_credit_cents"] == 0
    assert summary["invoice_total_cents"] == 26000

    licence = fx.read_vendor_app(api, world["vendor_app_id"])
    assert licence["renewal_score"] == 10.00
    assert licence["renewal_recommendation"] == RenewalRecommendation.DROP


def test_fifth_cumulative_failed_login_locks_the_password_and_nothing_else(api):
    """Four bad sign-in attempts leave a child working; the fifth locks the credential.

    "Reported `failed_logins` accumulate into `failed_login_count`, and the moment
    that cumulative count reaches the subject building's
    `password_lockout_threshold` the `password_state` becomes `LOCKED`; with the
    default threshold of 5, a cumulative count of 4 leaves the account usable and 5
    locks it." Lockout is deliberately narrow: "a `LOCKED` password changes neither
    `identity_status` nor `seat_status`, because a locked password still occupies
    its licensed seat" — and the seat is already `ACTIVE` because "when the reported
    `active_minutes` is greater than zero and the seat axis is still `RESERVED`, the
    seat advances to `ACTIVE`". Once locked, a password set is refused with
    `ERR_ACCOUNT_LOCKED`.

    Design: Corner/calculations/password_lockout_locks_exactly_at_threshold
    """
    world = fx.seated_account(api, total_seats=4)
    account = fx.set_account_password(api, world["account_id"], c.VALID_PASSWORD)
    assert_account_axes(
        account,
        seat_status=SeatStatus.RESERVED,
        identity_status=IdentityStatus.PROVISIONED,
        password_state=PasswordState.USER_SET,
    )

    below_threshold = fx.record_usage(
        api, world["account_id"], "2026-08-20", 10, failed_logins=4
    )
    assert below_threshold["failed_login_count"] == 4
    assert_account_axes(
        below_threshold,
        seat_status=SeatStatus.ACTIVE,
        identity_status=IdentityStatus.PROVISIONED,
        password_state=PasswordState.USER_SET,
    )

    at_threshold = fx.record_usage(
        api, world["account_id"], "2026-08-20", 5, failed_logins=1
    )
    assert at_threshold["failed_login_count"] == 5
    assert_account_axes(
        at_threshold,
        seat_status=SeatStatus.ACTIVE,
        identity_status=IdentityStatus.PROVISIONED,
        password_state=PasswordState.LOCKED,
    )

    validate_error(
        api.set_password(
            world["account_id"],
            f.password_set_payload("Newpass2026"),
            users.IDENTITY_ADMIN,
        ),
        errors.ERR_ACCOUNT_LOCKED,
        403,
    )
    locked_rows = fx.accounts_of_allocation(
        api, world["allocation_id"], password_state=PasswordState.LOCKED
    )
    assert_contains_id(locked_rows, world["account_id"], "locked accounts")
