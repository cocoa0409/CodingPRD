"""Pinned fee constants, rounding residues, accrual floors and export sums."""

from test_helpers import (
    LINES_FOUR_1500,
    LINES_TWO_2000,
    MONDAY_NOON,
    TEST_USERS,
    TUESDAY_NOON,
    WEDNESDAY_NOON,
    ApiErrorId,
    acknowledge_export,
    add_employee_with_period,
    add_member_order,
    api_client,
    assert_expense_export,
    cancel_order_as_employee,
    confirm_order,
    create_group_order,
    create_location,
    create_restaurant,
    deliver_order,
    draft_order,
    generate_export,
    lock_group_order,
    open_period,
    order_line,
    place_order,
    place_order_raw,
    read_employee,
    read_group_order,
    read_imputed_records,
    read_order,
    read_period,
    set_clock,
    setup_program_base,
    setup_scenario,
    submit_group_order,
    validate_error,
    validate_paginated,
)

_PROGRAM = TEST_USERS["program_admin_headers"]
_CONTROLLER = TEST_USERS["controller_drafter_headers"]


def _deliver(order, ns):
    return deliver_order(confirm_order(order, ns.restaurant), ns.restaurant)


def test_the_free_delivery_threshold_and_the_service_fee_floor_both_bite():
    """4,000 cents earns free delivery; 500 cents pays the 99-cent minimum.

    PRD §3.5: "For a solo order, a `subtotal_cents` of at least the free-delivery
    threshold of 3,500 cents earns free delivery and `delivery_fee_cents` of 0;
    below that threshold the flat base delivery fee of 599 cents applies."

    PRD §3.5: "Stage 2b clamps that raw figure into the range from 99 cents to 500
    cents inclusive: anything below 99 becomes 99, anything above 500 becomes 500."

    Design: Corner/calculations/fee_constants_apply_at_the_free_delivery_threshold_and_the_service_fee_floor
    """
    ns = setup_scenario()

    first = place_order(
        draft_order(
            ns.employee,
            ns.period,
            ns.restaurant,
            ns.location,
            requested_delivery_at=MONDAY_NOON,
        ),
        ns.employee,
    )
    assert first["subtotal_cents"] == 1000
    assert first["tax_cents"] == 88
    assert first["delivery_fee_cents"] == 599
    assert first["service_fee_cents"] == 100
    assert first["covered_base_cents"] == 1787

    second = place_order(
        draft_order(
            ns.employee,
            ns.period,
            ns.restaurant,
            ns.location,
            requested_delivery_at=TUESDAY_NOON,
            lines=LINES_TWO_2000,
        ),
        ns.employee,
    )
    assert second["subtotal_cents"] == 4000
    assert second["tax_cents"] == 350
    assert second["delivery_fee_cents"] == 0, "4,000 clears the 3,500-cent threshold"
    assert second["service_fee_cents"] == 400
    assert second["covered_base_cents"] == 4750
    assert second["employer_covered_cents"] == 2500
    assert second["employee_card_cents"] == 2250

    third = place_order(
        draft_order(
            ns.employee,
            ns.period,
            ns.restaurant,
            ns.location,
            requested_delivery_at=WEDNESDAY_NOON,
            lines=[order_line("Spring Rolls", 500, 1)],
        ),
        ns.employee,
    )
    assert third["subtotal_cents"] == 500
    assert third["tax_cents"] == 44
    assert third["delivery_fee_cents"] == 599
    assert third["service_fee_cents"] == 99, "the raw 50 is lifted to the 99 floor"
    assert third["covered_base_cents"] == 1242
    assert third["employer_covered_cents"] == 1242

    period = read_period(ns.period["id"])
    assert period["reserved_cents"] == 5529
    assert period["available_cents"] == 44471


def test_the_administration_fee_rounds_a_half_cent_residue_upward():
    """1,990 at five percent is 99.5 cents, which rounds away from zero to 100.

    PRD §2.6: "Where a rate is applied to a cents amount, the product is rounded
    to a whole cent using round-half-up — a residue of exactly half a cent rounds
    away from zero, upward."

    PRD §3.5: "The fee is `employer_covered_cents` multiplied by that rate,
    rounded half-up to a whole cent."

    Design: Corner/calculations/admin_fee_rounds_half_up_so_1990_yields_100_while_1787_yields_89
    """
    ns = setup_scenario()

    first = place_order(
        draft_order(
            ns.employee,
            ns.period,
            ns.restaurant,
            ns.location,
            requested_delivery_at=MONDAY_NOON,
        ),
        ns.employee,
    )
    assert first["employer_covered_cents"] == 1787
    assert first["admin_fee_cents"] == 89, "89.35 truncates downward under half-up"

    second = place_order(
        draft_order(
            ns.employee,
            ns.period,
            ns.restaurant,
            ns.location,
            requested_delivery_at=TUESDAY_NOON,
            lines=[order_line("Pad Thai", 1000, 1), order_line("Iced Tea", 171, 1)],
        ),
        ns.employee,
    )
    assert second["subtotal_cents"] == 1171
    assert second["tax_cents"] == 103
    assert second["service_fee_cents"] == 117
    assert second["covered_base_cents"] == 1990
    assert second["employer_covered_cents"] == 1990
    assert second["admin_fee_cents"] == 100, "99.5 rounds up, never down to 99"


def test_de_minimis_taxes_only_the_employer_cents_above_the_2000_floor():
    """A 1,787-cent share is untaxed while a 2,500-cent share yields 500.

    PRD §3.7: "Under the `DE_MINIMIS_EXCLUSION` method, only the part of the
    employer share above the per-meal de-minimis floor of 2,000 cents — twenty
    dollars — is taxable, and the taxable amount never goes below zero: an employer
    share of 2,500 cents yields `taxable_cents` of 500, and an employer share of
    1,800 cents yields 0."

    Design: Corner/calculations/de_minimis_taxes_only_the_employer_share_above_2000_per_meal
    """
    ns = setup_scenario()

    small = _deliver(
        place_order(
            draft_order(
                ns.employee,
                ns.period,
                ns.restaurant,
                ns.location,
                requested_delivery_at=MONDAY_NOON,
            ),
            ns.employee,
        ),
        ns,
    )
    assert small["employer_net_cents"] == 1787
    assert small["taxable_cents"] == 0

    large = _deliver(
        place_order(
            draft_order(
                ns.employee,
                ns.period,
                ns.restaurant,
                ns.location,
                requested_delivery_at=TUESDAY_NOON,
                lines=LINES_FOUR_1500,
            ),
            ns.employee,
        ),
        ns,
    )
    assert large["covered_base_cents"] == 6974
    assert large["employer_net_cents"] == 2500
    assert large["taxable_cents"] == 500, "only the 500 cents above the floor"

    records = read_imputed_records(ns.employee["id"])
    assert len(records) == 1
    record = records[0]
    assert record["tax_month"] == "2026-08"
    assert record["method"] == "DE_MINIMIS_EXCLUSION"
    assert record["status"] == "ACCRUING"
    assert record["gross_employer_paid_cents"] == 4287
    assert record["taxable_cents"] == 500, "not the 2,287 a whole-share method gives"

    employee = read_employee(ns.employee["id"])
    assert employee["ytd_imputed_cents"] == 500
    assert employee["tax_treatment_flag"] == "NONE"


def test_the_export_bucket_ignores_undelivered_cancelled_and_other_month_orders():
    """Only one of four orders is a delivered August receipt.

    PRD §3.9: "The bucket is the program's delivered, non-voided orders whose
    `tax_month` matches. `receipt_count` is the number of orders in the bucket;
    `employer_gross_cents` is the sum of their `employer_covered_cents`;
    `employer_refund_cents` is the sum of their `employer_refunded_cents`;
    `net_of_refunds_cents` is `employer_gross_cents` minus `employer_refund_cents`;
    `admin_fee_total_cents` is the sum of their `admin_fee_cents`; and
    `imputed_total_cents` is the sum of their `taxable_cents`."

    Design: Corner/calculations/expense_export_bucket_excludes_undelivered_cancelled_and_other_month_orders
    """
    ns = setup_scenario()

    delivered = _deliver(
        place_order(
            draft_order(
                ns.employee,
                ns.period,
                ns.restaurant,
                ns.location,
                requested_delivery_at=MONDAY_NOON,
            ),
            ns.employee,
        ),
        ns,
    )
    assert delivered["employer_covered_cents"] == 1787
    assert delivered["admin_fee_cents"] == 89

    place_order(
        draft_order(
            ns.employee,
            ns.period,
            ns.restaurant,
            ns.location,
            requested_delivery_at=TUESDAY_NOON,
        ),
        ns.employee,
    )

    cancelled = place_order(
        draft_order(
            ns.employee,
            ns.period,
            ns.restaurant,
            ns.location,
            requested_delivery_at=WEDNESDAY_NOON,
        ),
        ns.employee,
    )
    cancel_order_as_employee(cancelled, ns.employee)

    set_clock("2026-09-01T09:00:00Z")
    september_period = open_period(ns.employee["id"], period_month="2026-09")
    september = _deliver(
        place_order(
            draft_order(
                ns.employee,
                september_period,
                ns.restaurant,
                ns.location,
                requested_delivery_at="2026-09-01T12:00:00Z",
            ),
            ns.employee,
        ),
        ns,
    )
    assert september["tax_month"] == "2026-09"

    export = generate_export(
        ns.program["id"], tax_month="2026-08", format="CSV_EXPENSE_REPORT"
    )
    assert_expense_export(export)
    assert export["status"] == "GENERATED"
    assert export["receipt_count"] == 1
    assert export["employer_gross_cents"] == 1787
    assert export["employer_refund_cents"] == 0
    assert export["net_of_refunds_cents"] == 1787
    assert export["admin_fee_total_cents"] == 89
    assert export["imputed_total_cents"] == 0


def test_an_export_sums_two_receipts_while_an_empty_month_is_created_failed():
    """Two August deliveries roll up; July has nothing and lands in FAILED.

    PRD §3.9: "An empty bucket is not a zero-valued success: when `receipt_count`
    is 0 the export is created with status `FAILED` instead of `GENERATED`."

    PRD §3.9: "Downstream acceptance is recorded by acknowledging a `GENERATED`
    export, which moves it `GENERATED → ACKNOWLEDGED`, increments its `version` by 1,
    and makes it immutable."

    Design: Corner/calculations/expense_export_sums_two_delivered_orders_and_fails_on_an_empty_month
    """
    ns = setup_scenario()

    first = _deliver(
        place_order(
            draft_order(
                ns.employee,
                ns.period,
                ns.restaurant,
                ns.location,
                requested_delivery_at=MONDAY_NOON,
            ),
            ns.employee,
        ),
        ns,
    )
    second = _deliver(
        place_order(
            draft_order(
                ns.employee,
                ns.period,
                ns.restaurant,
                ns.location,
                requested_delivery_at=TUESDAY_NOON,
                lines=LINES_FOUR_1500,
            ),
            ns.employee,
        ),
        ns,
    )
    assert first["admin_fee_cents"] == 89
    assert second["admin_fee_cents"] == 125

    export = generate_export(ns.program["id"], tax_month="2026-08")
    assert export["status"] == "GENERATED"
    assert export["receipt_count"] == 2
    assert export["employer_gross_cents"] == 4287
    assert export["employer_refund_cents"] == 0
    assert export["net_of_refunds_cents"] == 4287
    assert export["admin_fee_total_cents"] == 214
    assert export["imputed_total_cents"] == 500

    acknowledged = acknowledge_export(export["id"])
    assert acknowledged["status"] == "ACKNOWLEDGED"

    empty = generate_export(ns.program["id"], tax_month="2026-07")
    assert empty["status"] == "FAILED"
    assert empty["receipt_count"] == 0
    assert empty["employer_gross_cents"] == 0
    assert empty["employer_refund_cents"] == 0
    assert empty["net_of_refunds_cents"] == 0
    assert empty["admin_fee_total_cents"] == 0
    assert empty["imputed_total_cents"] == 0

    _rows, meta = validate_paginated(
        api_client.list_expense_exports(
            ns.program["id"], _CONTROLLER, params={"tax_month": "2026-08"}
        )
    )
    assert meta["total_count"] == 1


def test_the_group_delivery_fee_remainder_walks_the_created_at_order():
    """Three members split 1,250 as 417, 417 and 416 in join order.

    PRD §3.6: "Order the members by `created_at` ascending and, where two were
    created at the same instant, by the ordering employee's `email` ascending —
    never by identifier. Then walk that ordered list from the front: each of the
    first *remainder*-many members receives the base share plus one cent as its
    `delivery_fee_cents`, and every member after that receives exactly the base
    share."

    Design: Corner/calculations/group_delivery_fee_remainder_follows_created_at_before_email
    """
    ns = setup_program_base(clock="2026-08-03T09:00:00Z")
    cleo, cleo_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Cleo Chen", "email": "cleo@acme.test"}
    )
    ada, ada_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Ada Lovelace", "email": "ada@acme.test"}
    )
    ben, ben_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Ben Barnes", "email": "ben@acme.test"}
    )

    group_order = create_group_order(ns, cleo)
    member_orders = []
    for instant, employee, period in (
        ("2026-08-03T10:00:00Z", cleo, cleo_period),
        ("2026-08-03T10:05:00Z", ada, ada_period),
        ("2026-08-03T10:10:00Z", ben, ben_period),
    ):
        set_clock(instant)
        member_orders.append(
            add_member_order(ns, employee, period, group_order, place=True)
        )

    lock_group_order(group_order, cleo)
    set_clock("2026-08-03T11:00:00Z")
    submitted = submit_group_order(group_order, cleo)

    assert submitted["status"] == "SUBMITTED"
    assert submitted["member_order_count"] == 3
    assert submitted["allocated_delivery_fee_cents"] == 1250

    shares = [read_order(o["id"])["delivery_fee_cents"] for o in member_orders]
    assert shares == [417, 417, 416], f"remainder waterfall broken: {shares}"
    assert sum(shares) == 1250

    cleo_order = read_order(member_orders[0]["id"])
    ben_order = read_order(member_orders[2]["id"])
    assert cleo_order["covered_base_cents"] == 1605
    assert cleo_order["employer_covered_cents"] == 1605
    assert ben_order["covered_base_cents"] == 1604
    assert ben_order["employer_covered_cents"] == 1604
    assert read_group_order(group_order["id"])["member_order_count"] == 3


def test_the_eligible_search_ranks_by_distance_then_name_and_can_return_nothing():
    """Two restaurants tie at 5 km and the alphabet breaks the tie.

    PRD §3.4: "Survivors are ranked by that rounded distance ascending and, where
    two restaurants tie on distance, by `name` ascending; the identifier is never a
    sort key. When nothing qualifies, the answer is a successful empty array with
    `total_count` of 0 — an empty result is not a not-found."

    PRD §3.4: "must be less than or equal to the effective limit for that
    restaurant, which is the smaller of the program's `max_delivery_radius_km` and
    the restaurant's own `delivery_radius_km`."

    Design: Corner/calculations/eligible_restaurants_rank_by_distance_then_name_and_return_an_empty_set
    """
    ns = setup_program_base(
        program_overrides={"eligible_cuisines": ["THAI", "SALAD"]}
    )
    far_dock = create_location(
        ns.program["id"], label="Far Dock", grid_x_km=0.0, grid_y_km=30.0
    )
    create_restaurant(
        name="Thai Annex", cuisine="THAI", grid_x_km=0.0, grid_y_km=5.0,
        delivery_radius_km=10.0,
    )
    create_restaurant(
        name="Thai Local", cuisine="THAI", grid_x_km=0.0, grid_y_km=3.0,
        delivery_radius_km=2.0,
    )
    create_restaurant(
        name="Salad Mid", cuisine="SALAD", grid_x_km=6.0, grid_y_km=0.0,
        delivery_radius_km=12.0,
    )
    create_restaurant(
        name="Sushi Nine", cuisine="SUSHI", grid_x_km=1.0, grid_y_km=0.0,
        delivery_radius_km=12.0,
    )
    create_restaurant(
        name="Pizza Rim", cuisine="PIZZA", grid_x_km=0.0, grid_y_km=9.0,
        delivery_radius_km=12.0,
    )

    rows, meta = validate_paginated(
        api_client.list_eligible_restaurants(
            ns.program["id"],
            _PROGRAM,
            params={"delivery_location_id": ns.location["id"]},
        )
    )
    assert meta["total_count"] == 3
    assert [row["name"] for row in rows] == ["Thai Annex", "Thai Garden", "Salad Mid"], (
        "5.000 twice, tie broken by name, then 6.000"
    )
    names = [row["name"] for row in rows]
    assert "Thai Local" not in names, "its own 2 km radius is the tighter limit"
    assert "Sushi Nine" not in names and "Pizza Rim" not in names, (
        "neither cuisine is in the program allow-list"
    )

    empty, empty_meta = validate_paginated(
        api_client.list_eligible_restaurants(
            ns.program["id"], _PROGRAM, params={"delivery_location_id": far_dock["id"]}
        )
    )
    assert empty == []
    assert empty_meta["total_count"] == 0, "an empty result is not a not-found"


def test_an_exhausted_period_refuses_the_order_instead_of_truncating_the_share():
    """1,213 cents left is below the 1,787 the covered base needs.

    PRD §3.5: "Next, if the period's `available_cents` is below the smaller of the
    covered base and the per-meal cap, the placement is refused with
    `ERR_PERIOD_BUDGET_EXCEEDED` — an exhausted period never silently truncates the
    employer share, it refuses the order."

    Design: Corner/calculations/employer_share_is_clamped_by_remaining_period_budget_and_then_refused
    """
    ns = setup_scenario(
        group_overrides={"name": "Interns"},
        rule_overrides={"daily_meal_limit": 3, "monthly_allocation_cents": 3000},
        employee_overrides={"full_name": "Dee Knuth", "email": "dee@acme.test"},
    )

    first = place_order(
        draft_order(
            ns.employee,
            ns.period,
            ns.restaurant,
            ns.location,
            requested_delivery_at="2026-08-03T12:00:00Z",
        ),
        ns.employee,
    )
    assert first["employer_covered_cents"] == 1787
    assert read_period(ns.period["id"])["available_cents"] == 1213

    second = draft_order(
        ns.employee,
        ns.period,
        ns.restaurant,
        ns.location,
        requested_delivery_at="2026-08-03T13:00:00Z",
    )
    error = validate_error(
        place_order_raw(second, ns.employee), ApiErrorId.ERR_PERIOD_BUDGET_EXCEEDED
    )
    assert error["error_id"] != ApiErrorId.ERR_DAILY_MEAL_LIMIT_EXCEEDED.value, (
        "the daily limit of 3 leaves room; it is the budget that is exhausted"
    )

    refused = read_order(second["id"])
    assert refused["fulfillment_status"] == "DRAFT"
    assert refused["settlement_status"] == "UNSETTLED"

    period = read_period(ns.period["id"])
    assert period["reserved_cents"] == 1787
    assert period["available_cents"] == 1213
    assert period["version"] == 2, "the refused placement bumped nothing"
