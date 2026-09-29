"""Conditional, aggregate and temporal gates, plus the writes and reads they guard."""

from test_helpers import (
    AllocationStatus,
    ApiErrorId,
    AppointmentStatus,
    CycleStatus,
    DrawPosture,
    EligibilityDetermination,
    FormulaVariant,
    LotStatus,
    OrderStatus,
    SECOND_COMPLIANCE_REVIEWER_ID,
    assert_instant,
    assert_lot_ledger,
    assert_pounds,
    assert_ratio,
    assert_version_incremented,
    factories as f,
    fixtures as fx,
    make_agency_coordinator_headers,
    make_warehouse_operator_headers,
    validate_error,
    validate_success,
)

RICE_CODE = "BULK_RICE"
CHICKEN_CODE = "FROZEN_CHICKEN"


def _agency_with_twenty_cases(api):
    """An ELIGIBLE agency holding 20 transferred cases against an OPEN cycle."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area North", county_code="C001", poverty_population=40000
    )
    agency = fx.create_agency(
        api,
        area["id"],
        name="Agency Alpha",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=120000,
        prior_period_allocated_cases=400,
    )
    fx.make_agency_eligible(api, agency["id"])
    rice = fx.create_bulk_rice(api)
    warehouse = fx.create_warehouse(api, name="WH North")
    lot = fx.create_posted_lot(
        api,
        rice["id"],
        warehouse["id"],
        federal_lot_code="FL-R-001",
        cases_received=100,
        pack_date="2026-06-01",
        best_by_date="2028-06-01",
    )
    transfer = fx.propose_transfer(api, lot["id"], agency["id"], 20)
    fx.accept_transfer(api, transfer["id"], agency["id"])
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27A",
        formula_variant=FormulaVariant.STANDARD,
        allocatable_cases=1000,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=[RICE_CODE],
    )
    fx.compute_allocations(api, cycle["id"])
    fx.open_window(api, cycle["id"])
    fx.set_clock(api, "2026-08-06T00:00:00Z")
    return {"agency": agency, "cycle": cycle, "rice": rice}


def _record_over_the_limit(api, env, participates_in_snap):
    return api.create_household_distribution(
        f.household_distribution_payload(
            env["agency"]["id"],
            env["cycle"]["id"],
            env["rice"]["id"],
            household_size=3,
            declared_monthly_income_cents=400000,
            participates_in_snap=participates_in_snap,
            self_declaration_signed=True,
            cases_distributed=2,
            distribution_date="2026-08-06",
        ),
        headers=make_agency_coordinator_headers(env["agency"]["id"]),
    )


def test_01_income_above_the_limit_without_snap_is_refused_and_writes_nothing(api):
    """PRD §3.9: "If the declared income exceeds the limit and `participates_in_snap` is
    `false`, the request is refused with `ERR_HOUSEHOLD_INELIGIBLE`, no row is persisted,
    and no rollup figure or on-hand counter moves at all."

    Design: Corner/validations/snap_participation_overrides_the_income_test_and_absent_snap_is_refused
    """
    env = _agency_with_twenty_cases(api)

    response = _record_over_the_limit(api, env, participates_in_snap=False)

    validate_error(response, ApiErrorId.ERR_HOUSEHOLD_INELIGIBLE, 422)
    agency = fx.read_agency(api, env["agency"]["id"])
    assert agency["agency_cases_on_hand"] == 20, (
        f"a refused record may not debit the agency but on hand reads "
        f"{agency['agency_cases_on_hand']}"
    )
    allocation = fx.read_allocation(api, env["cycle"]["id"], env["agency"]["id"])
    assert allocation["distribution_record_count"] == 0, (
        f"distribution_record_count expected 0 but got "
        f"{allocation['distribution_record_count']}"
    )
    assert_pounds(allocation["distributed_pounds"], 0.0, "distributed_pounds")


def test_02_the_same_income_with_snap_qualifies_categorically(api):
    """PRD §3.9: "If the declared income exceeds the limit but `participates_in_snap` is
    `true`, the household qualifies categorically regardless of income and
    `eligibility_determination` is written as `CATEGORICALLY_ELIGIBLE`." PRD §3.9: "The
    distribution's `pounds_distributed` is its `cases_distributed` multiplied by the
    commodity's `net_weight_lbs_per_case`, rounded half up to two decimals."

    Design: Corner/validations/snap_participation_overrides_the_income_test_and_absent_snap_is_refused
    """
    env = _agency_with_twenty_cases(api)
    _record_over_the_limit(api, env, participates_in_snap=False)

    record = validate_success(
        _record_over_the_limit(api, env, participates_in_snap=True), 201
    )

    assert (
        record["eligibility_determination"]
        == EligibilityDetermination.CATEGORICALLY_ELIGIBLE
    ), (
        f"eligibility_determination expected CATEGORICALLY_ELIGIBLE but got "
        f"{record['eligibility_determination']}"
    )
    assert record["income_limit_cents"] == 331000, (
        f"income_limit_cents expected 331000 but got {record['income_limit_cents']}"
    )
    assert_pounds(record["pounds_distributed"], 40.0, "pounds_distributed")
    agency = fx.read_agency(api, env["agency"]["id"])
    assert agency["agency_cases_on_hand"] == 18, (
        f"agency_cases_on_hand expected 18 but got {agency['agency_cases_on_hand']}"
    )
    allocation = fx.read_allocation(api, env["cycle"]["id"], env["agency"]["id"])
    assert_pounds(allocation["distributed_pounds"], 40.0, "distributed_pounds")
    assert allocation["distribution_record_count"] == 1, (
        f"distribution_record_count expected 1 but got "
        f"{allocation['distribution_record_count']}"
    )
    assert_ratio(allocation["record_compliance_pct"], 1.0, "record_compliance_pct")


def _two_frozen_pallets_against_a_two_pallet_pool(api):
    """WH Cold holds only 2 frozen pallets; Alpha already stages 1 from 10:00 to 12:00."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area North", county_code="C001", poverty_population=40000
    )
    agencies = []
    for name in ("Agency Alpha", "Agency Bravo"):
        agency = fx.create_agency(
            api,
            area["id"],
            name=name,
            cold_storage_pallet_capacity=10,
            prior_period_pounds_distributed=60000,
            prior_period_allocated_cases=400,
        )
        fx.make_agency_eligible(api, agency["id"])
        agencies.append(agency)
    alpha, bravo = agencies

    chicken = fx.create_frozen_chicken(api)
    warehouse = fx.create_warehouse(
        api, name="WH Cold", dock_count=2, frozen_pallet_capacity=2
    )
    fx.create_posted_lot(
        api,
        chicken["id"],
        warehouse["id"],
        federal_lot_code="FL-C-001",
        cases_received=100,
        pack_date="2026-06-01",
        best_by_date="2027-06-01",
    )
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27F",
        formula_variant=FormulaVariant.STANDARD,
        allocatable_cases=1000,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=[CHICKEN_CODE],
    )
    fx.compute_allocations(api, cycle["id"])
    fx.open_window(api, cycle["id"])
    fx.set_clock(api, "2026-08-06T00:00:00Z")

    order_a = fx.create_order(api, cycle["id"], alpha["id"], warehouse["id"])
    fx.add_line(api, order_a["id"], alpha["id"], chicken["id"], 23)
    fx.submit_order(api, order_a["id"], alpha["id"])
    fx.approve_order(api, order_a["id"])
    appointment_a = fx.book_appointment(
        api,
        order_a["id"],
        dock_number=1,
        window_start="2026-08-10T10:00:00Z",
        window_end="2026-08-10T12:00:00Z",
    )

    order_b = fx.create_order(api, cycle["id"], bravo["id"], warehouse["id"])
    fx.add_line(api, order_b["id"], bravo["id"], chicken["id"], 50)
    fx.submit_order(api, order_b["id"], bravo["id"])
    fx.approve_order(api, order_b["id"])

    return {
        "warehouse": warehouse,
        "appointment_a": appointment_a,
        "order_b": order_b,
    }


def _book_for_bravo(api, env, window_start, window_end):
    return api.create_delivery_appointment(
        f.delivery_appointment_payload(env["order_b"]["id"], 2, window_start, window_end),
        headers=make_warehouse_operator_headers(env["warehouse"]["id"]),
    )


def test_03_the_frozen_pool_is_summed_over_every_overlapping_peer_at_the_warehouse(api):
    """PRD §3.7: "For each of the three storage classes independently, the new
    appointment's pallets of that class plus the sum of that class's pallets over the
    overlapping peers must not exceed the warehouse's matching capacity — `dry_pallets`
    against `dry_pallet_capacity`, `cold_pallets` against `cold_pallet_capacity`,
    `frozen_pallets` against `frozen_pallet_capacity`." PRD §3.7: "Any of the three
    breaching answers `ERR_WAREHOUSE_COLD_CAPACITY_EXCEEDED`."

    Design: Corner/validations/warehouse_frozen_capacity_is_aggregated_across_overlapping_appointments
    """
    env = _two_frozen_pallets_against_a_two_pallet_pool(api)
    assert env["appointment_a"]["frozen_pallets"] == 1, (
        f"the staged appointment frozen_pallets expected 1 but got "
        f"{env['appointment_a']['frozen_pallets']}"
    )
    assert env["appointment_a"]["dry_pallets"] == 0, (
        f"dry_pallets expected 0 but got {env['appointment_a']['dry_pallets']}"
    )
    assert env["appointment_a"]["cold_pallets"] == 0, (
        f"cold_pallets expected 0 but got {env['appointment_a']['cold_pallets']}"
    )

    response = _book_for_bravo(
        api, env, "2026-08-10T11:00:00Z", "2026-08-10T13:00:00Z"
    )

    validate_error(response, ApiErrorId.ERR_WAREHOUSE_COLD_CAPACITY_EXCEEDED, 409)
    order = fx.read_order(api, env["order_b"]["id"])
    assert order["status"] == OrderStatus.APPROVED, (
        f"the refused booking must leave the order APPROVED but got {order['status']}"
    )


def test_04_a_window_clear_of_the_peer_takes_the_whole_pool(api):
    """PRD §3.7: "The peers are appointments at the same `warehouse_id` whose `status` is
    `SCHEDULED` or `BLOCKED` — a delivered appointment no longer consumes staging — and
    which overlap the new window in the half-open sense: the peer starts strictly before
    the new window ends *and* the new window starts strictly before the peer ends, so
    windows that merely touch at an endpoint do not interact." PRD §3.7: "The appointment
    lands in `status` `SCHEDULED` with `delivered_pounds` 0.0 and both
    `confirmed_by_user_id` and `cancel_reason` null, and it moves its order `APPROVED →
    SCHEDULED`, incrementing the order's `version`."

    Design: Corner/validations/warehouse_frozen_capacity_is_aggregated_across_overlapping_appointments
    """
    env = _two_frozen_pallets_against_a_two_pallet_pool(api)
    _book_for_bravo(api, env, "2026-08-10T11:00:00Z", "2026-08-10T13:00:00Z")

    appointment = validate_success(
        _book_for_bravo(api, env, "2026-08-10T12:30:00Z", "2026-08-10T14:30:00Z"), 201
    )

    assert appointment["status"] == AppointmentStatus.SCHEDULED, (
        f"status expected SCHEDULED but got {appointment['status']}"
    )
    assert appointment["frozen_pallets"] == 2, (
        f"frozen_pallets expected 2 but got {appointment['frozen_pallets']}"
    )
    assert_pounds(appointment["delivered_pounds"], 0.0, "delivered_pounds")
    assert appointment["confirmed_by_user_id"] is None, (
        f"confirmed_by_user_id expected null but got {appointment['confirmed_by_user_id']}"
    )
    order = fx.read_order(api, env["order_b"]["id"])
    assert order["status"] == OrderStatus.SCHEDULED, (
        f"the order expected SCHEDULED but got {order['status']}"
    )


def _two_drafts_before_the_window_opens(api):
    """Two DRAFT orders against a cycle whose window opens at 2026-08-05T00:00:00Z."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area North", county_code="C001", poverty_population=40000
    )
    agencies = []
    for name in ("Agency Alpha", "Agency Bravo"):
        agency = fx.create_agency(
            api,
            area["id"],
            name=name,
            cold_storage_pallet_capacity=10,
            prior_period_pounds_distributed=60000,
            prior_period_allocated_cases=400,
        )
        fx.make_agency_eligible(api, agency["id"])
        agencies.append(agency)
    alpha, bravo = agencies

    rice = fx.create_bulk_rice(api)
    warehouse = fx.create_warehouse(api, name="WH North")
    fx.create_posted_lot(
        api,
        rice["id"],
        warehouse["id"],
        federal_lot_code="FL-R-001",
        cases_received=100,
        pack_date="2026-06-01",
        best_by_date="2028-06-01",
    )
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27A",
        formula_variant=FormulaVariant.STANDARD,
        allocatable_cases=1000,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=[RICE_CODE],
        order_window_open_at="2026-08-05T00:00:00Z",
        order_window_close_at="2026-08-20T00:00:00Z",
    )
    fx.compute_allocations(api, cycle["id"])
    fx.open_window(api, cycle["id"])

    orders = []
    for agency in (alpha, bravo):
        order = fx.create_order(api, cycle["id"], agency["id"], warehouse["id"])
        fx.add_line(api, order["id"], agency["id"], rice["id"], 10)
        orders.append(order)
    return {
        "alpha": alpha,
        "bravo": bravo,
        "cycle": cycle,
        "order_a": orders[0],
        "order_b": orders[1],
    }


def test_05_the_open_instant_is_inclusive_and_one_second_earlier_is_refused(api):
    """PRD §3.5: "The order's cycle must be in `status` `OPEN` and the current instant
    must be at or after `order_window_open_at`, either failing answering
    `ERR_ORDER_WINDOW_NOT_OPEN`." PRD §3.5: "On success `submitted_at` is stamped from the
    logical clock and the order's `version` is incremented; note that `submitted_at`
    records the *most recent* submit, so a resubmission after a revision round trip
    overwrites it."

    Design: Corner/validations/order_window_open_instant_is_inclusive_and_close_instant_is_exclusive
    """
    env = _two_drafts_before_the_window_opens(api)
    coordinator = make_agency_coordinator_headers(env["alpha"]["id"])

    fx.set_clock(api, "2026-08-04T23:59:59Z")
    early = api.submit_order(env["order_a"]["id"], headers=coordinator)

    validate_error(early, ApiErrorId.ERR_ORDER_WINDOW_NOT_OPEN, 422)
    order = fx.read_order(api, env["order_a"]["id"])
    assert order["status"] == OrderStatus.DRAFT, (
        f"the refused submit must leave the order DRAFT but got {order['status']}"
    )

    fx.set_clock(api, "2026-08-05T00:00:00Z")
    submitted = validate_success(
        api.submit_order(env["order_a"]["id"], headers=coordinator)
    )
    assert submitted["status"] == OrderStatus.SUBMITTED, (
        f"status expected SUBMITTED but got {submitted['status']}"
    )
    assert_instant(submitted["submitted_at"], "2026-08-05T00:00:00Z", "submitted_at")
    cycle = fx.read_cycle(api, env["cycle"]["id"])
    assert cycle["status"] == CycleStatus.OPEN, (
        f"the window instants gate submit, not the cycle, but status is {cycle['status']}"
    )


def test_06_the_close_instant_is_exclusive_so_submitting_exactly_at_it_is_refused(api):
    """PRD §3.5: "The current instant must be strictly before `order_window_close_at`;
    exactly at the close instant the window is shut, and the request is refused with
    `ERR_ORDER_WINDOW_CLOSED`."

    Design: Corner/validations/order_window_open_instant_is_inclusive_and_close_instant_is_exclusive
    """
    env = _two_drafts_before_the_window_opens(api)

    fx.set_clock(api, "2026-08-20T00:00:00Z")
    response = api.submit_order(
        env["order_b"]["id"],
        headers=make_agency_coordinator_headers(env["bravo"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_ORDER_WINDOW_CLOSED, 422)
    order = fx.read_order(api, env["order_b"]["id"])
    assert order["status"] == OrderStatus.DRAFT, (
        f"the refused submit must leave the order DRAFT but got {order['status']}"
    )
    assert order["submitted_at"] is None, (
        f"submitted_at expected null but got {order['submitted_at']}"
    )
    cycle = fx.read_cycle(api, env["cycle"]["id"])
    assert cycle["status"] == CycleStatus.OPEN, (
        f"the cycle must still read OPEN but got {cycle['status']}"
    )


def _submitted_two_line_order(api):
    """A submitted order carrying a 10-case rice line and a 3-case chicken line."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area North", county_code="C001", poverty_population=40000
    )
    agency = fx.create_agency(
        api,
        area["id"],
        name="Agency Alpha",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=120000,
        prior_period_allocated_cases=400,
    )
    fx.make_agency_eligible(api, agency["id"])
    rice = fx.create_bulk_rice(api)
    chicken = fx.create_frozen_chicken(api)
    warehouse = fx.create_warehouse(api, name="WH North")
    rice_lot = fx.create_posted_lot(
        api,
        rice["id"],
        warehouse["id"],
        federal_lot_code="FL-R-001",
        cases_received=100,
        pack_date="2026-06-01",
        best_by_date="2028-06-01",
    )
    chicken_lot = fx.create_posted_lot(
        api,
        chicken["id"],
        warehouse["id"],
        federal_lot_code="FL-C-001",
        cases_received=50,
        pack_date="2026-06-01",
        best_by_date="2027-06-01",
    )
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27M",
        formula_variant=FormulaVariant.STANDARD,
        allocatable_cases=1000,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=[RICE_CODE, CHICKEN_CODE],
    )
    fx.compute_allocations(api, cycle["id"])
    fx.open_window(api, cycle["id"])
    fx.set_clock(api, "2026-08-06T00:00:00Z")

    order = fx.create_order(api, cycle["id"], agency["id"], warehouse["id"])
    rice_line = fx.add_line(api, order["id"], agency["id"], rice["id"], 10)
    chicken_line = fx.add_line(api, order["id"], agency["id"], chicken["id"], 3)
    fx.submit_order(api, order["id"], agency["id"])
    return {
        "agency": agency,
        "cycle": cycle,
        "order": order,
        "rice_line": rice_line,
        "chicken_line": chicken_line,
        "rice_lot": rice_lot,
        "chicken_lot": chicken_lot,
    }


def _approve_with_rice_trim(api, env):
    return validate_success(
        api.approve_order(
            env["order"]["id"],
            headers=fx.SECOND_REVIEWER,
            payload=f.line_adjustments_payload(
                [f.line_adjustment(env["rice_line"]["id"], 6)]
            ),
        )
    )


def test_07_an_adjustment_trims_only_the_line_it_names(api):
    """PRD §3.6: "The reviewer may trim the order by supplying an optional
    `line_adjustments` array, whose entries each take the form of an `order_line_id`
    naming a line of *this* order together with a `cases_approved` value between 1 and
    that line's `cases_requested` inclusive; an entry naming a foreign line or an
    out-of-range figure answers `ERR_INVALID_REQUEST`." PRD §3.6: "Any line without a
    matching adjustment entry is approved at its full `cases_requested`."

    Design: Corner/endpoints/approve_with_line_adjustments_trims_one_line_and_leaves_the_other_intact
    """
    env = _submitted_two_line_order(api)

    order = _approve_with_rice_trim(api, env)

    assert order["status"] == OrderStatus.APPROVED, (
        f"status expected APPROVED but got {order['status']}"
    )
    assert order["approved_by_user_id"] == SECOND_COMPLIANCE_REVIEWER_ID, (
        f"approved_by_user_id expected {SECOND_COMPLIANCE_REVIEWER_ID} but got "
        f"{order['approved_by_user_id']}"
    )
    lines = {line["id"]: line for line in fx.read_order_lines(api, env["order"]["id"])}
    rice_line = lines[env["rice_line"]["id"]]
    assert rice_line["cases_requested"] == 10, (
        f"cases_requested expected 10 but got {rice_line['cases_requested']}"
    )
    assert rice_line["cases_approved"] == 6, (
        f"the trimmed line cases_approved expected 6 but got {rice_line['cases_approved']}"
    )
    assert_pounds(rice_line["line_pounds"], 120.0, "rice line_pounds")
    assert rice_line["line_pallets"] == 1, (
        f"rice line_pallets expected 1 but got {rice_line['line_pallets']}"
    )
    chicken_line = lines[env["chicken_line"]["id"]]
    assert chicken_line["cases_approved"] == 3, (
        f"the untouched line cases_approved expected 3 but got "
        f"{chicken_line['cases_approved']}"
    )
    assert_pounds(chicken_line["line_pounds"], 90.38, "chicken line_pounds")
    assert chicken_line["line_pallets"] == 1, (
        f"chicken line_pallets expected 1 but got {chicken_line['line_pallets']}"
    )


def test_08_the_order_totals_and_reservations_follow_the_approved_quantities(api):
    """PRD §3.6: "Once conversion and reservation succeed, the order's
    `total_cases_approved` is written as the sum of the lines' `cases_approved`, and that
    figure must not exceed the entitlement's `cases_remaining`, otherwise
    `ERR_ALLOCATION_EXCEEDED`." PRD §3.6: "The order's `total_pounds` is the sum of the
    per-line rounded `line_pounds` values, and its `total_pallets` is the sum of the
    per-line ceilinged `line_pallets` values." PRD §2.9: "Approval adds each line's
    reserved cases to that lot's `cases_committed` and adds the order's
    `total_cases_approved` to the allocation's `cases_committed`."

    Design: Corner/endpoints/approve_with_line_adjustments_trims_one_line_and_leaves_the_other_intact
    """
    env = _submitted_two_line_order(api)

    order = _approve_with_rice_trim(api, env)

    assert order["total_cases_requested"] == 13, (
        f"total_cases_requested expected 13 but got {order['total_cases_requested']}"
    )
    assert order["total_cases_approved"] == 9, (
        f"total_cases_approved expected 9 but got {order['total_cases_approved']}"
    )
    assert_pounds(order["total_pounds"], 210.38, "total_pounds")
    assert order["total_pallets"] == 2, (
        f"total_pallets expected 2 but got {order['total_pallets']}"
    )
    rice_lot = fx.read_lot(api, env["rice_lot"]["id"])
    assert rice_lot["cases_committed"] == 6, (
        f"the rice lot cases_committed expected 6 but got {rice_lot['cases_committed']}"
    )
    chicken_lot = fx.read_lot(api, env["chicken_lot"]["id"])
    assert chicken_lot["cases_committed"] == 3, (
        f"the chicken lot cases_committed expected 3 but got "
        f"{chicken_lot['cases_committed']}"
    )
    allocation = fx.read_allocation(api, env["cycle"]["id"], env["agency"]["id"])
    assert allocation["cases_committed"] == 9, (
        f"cases_committed expected 9 but got {allocation['cases_committed']}"
    )
    assert allocation["cases_remaining"] == 991, (
        f"cases_remaining expected 991 but got {allocation['cases_remaining']}"
    )


def _locked_allocation_then_later_edits(api):
    """A computed cycle whose inputs are then revised two days later."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area North", county_code="C001", poverty_population=40000
    )
    agency = fx.create_agency(
        api,
        area["id"],
        name="Agency Alpha",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=120000,
        prior_period_allocated_cases=400,
    )
    fx.make_agency_eligible(api, agency["id"])
    fx.create_bulk_rice(api)
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27A",
        formula_variant=FormulaVariant.STANDARD,
        allocatable_cases=100,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=[RICE_CODE],
    )
    fx.compute_allocations(api, cycle["id"])
    area_before = fx.read_service_area(api, area["id"])
    agency_before = fx.read_agency(api, agency["id"])
    fx.set_clock(api, "2026-08-03T00:00:00Z")
    return {
        "area": area_before,
        "agency": agency_before,
        "cycle": cycle,
    }


def test_09_the_patches_land_on_their_own_rows(api):
    """PRD §3.1: "A `StateAdmin` may later revise `poverty_population` and `urban_rural`;
    such a revision only affects cycles whose allocations are computed after the change,
    since a computed allocation freezes its inputs." PRD §3.2: "A `StateAdmin` may later
    revise `cold_storage_pallet_capacity`, `prior_period_pounds_distributed`, and
    `prior_period_allocated_cases`."

    Design: Corner/endpoints/patching_a_service_area_or_agency_does_not_retro_edit_a_locked_allocation
    """
    env = _locked_allocation_then_later_edits(api)

    area = validate_success(
        api.patch_service_area(
            env["area"]["id"],
            {"poverty_population": 80000, "urban_rural": "MIXED"},
            headers=fx.ADMIN,
        )
    )
    agency = validate_success(
        api.patch_agency(
            env["agency"]["id"], {"prior_period_allocated_cases": 1600}, headers=fx.ADMIN
        )
    )

    assert area["poverty_population"] == 80000, (
        f"poverty_population expected 80000 but got {area['poverty_population']}"
    )
    assert area["urban_rural"] == "MIXED", (
        f"urban_rural expected MIXED but got {area['urban_rural']}"
    )
    assert_version_incremented(area["version"], env["area"]["version"])
    assert agency["prior_period_allocated_cases"] == 1600, (
        f"prior_period_allocated_cases expected 1600 but got "
        f"{agency['prior_period_allocated_cases']}"
    )
    assert_pounds(
        agency["prior_period_pounds_distributed"], 120000.0,
        "prior_period_pounds_distributed",
    )
    assert_version_incremented(agency["version"], env["agency"]["version"])


def test_10_the_computed_entitlement_keeps_the_figures_the_run_froze(api):
    """PRD §3.4: "Service-area poverty figures and agency prior-period figures are read
    at run time and frozen into the entitlement rows the run creates, which is why later
    revisions to a service area or an agency do not disturb an allocation that has already
    been computed." PRD §3.4: "The run stamps `allocation_locked_at` from the logical
    clock and records into the cycle's `eligible_agency_count` how many agencies the
    included set held."

    Design: Corner/endpoints/patching_a_service_area_or_agency_does_not_retro_edit_a_locked_allocation
    """
    env = _locked_allocation_then_later_edits(api)

    api.patch_service_area(
        env["area"]["id"],
        {"poverty_population": 80000, "urban_rural": "MIXED"},
        headers=fx.ADMIN,
    )
    api.patch_agency(
        env["agency"]["id"], {"prior_period_allocated_cases": 1600}, headers=fx.ADMIN
    )

    allocation = fx.read_allocation(api, env["cycle"]["id"], env["agency"]["id"])
    assert_ratio(allocation["poverty_factor"], 40000.0, "poverty_factor")
    assert allocation["allocated_cases"] == 100, (
        f"allocated_cases expected 100 but got {allocation['allocated_cases']}"
    )
    assert allocation["floor_cases"] == 0, (
        f"floor_cases expected 0 but got {allocation['floor_cases']}"
    )
    cycle = fx.read_cycle(api, env["cycle"]["id"])
    assert_instant(
        cycle["allocation_locked_at"], "2026-08-01T00:00:00Z", "allocation_locked_at"
    )
    assert cycle["total_allocated_cases"] == 100, (
        f"total_allocated_cases expected 100 but got {cycle['total_allocated_cases']}"
    )


def _scheduled_ten_case_delivery(api):
    """A 10-case order against a 10-case lot, booked for 2026-08-10 at 10:00."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area North", county_code="C001", poverty_population=40000
    )
    agency = fx.create_agency(
        api,
        area["id"],
        name="Agency Alpha",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=120000,
        prior_period_allocated_cases=400,
    )
    fx.make_agency_eligible(api, agency["id"])
    rice = fx.create_bulk_rice(api)
    warehouse = fx.create_warehouse(api, name="WH North")
    lot = fx.create_posted_lot(
        api,
        rice["id"],
        warehouse["id"],
        federal_lot_code="FL-R-001",
        cases_received=10,
        pack_date="2026-06-01",
        best_by_date="2028-06-01",
    )
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27A",
        formula_variant=FormulaVariant.STANDARD,
        allocatable_cases=1000,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=[RICE_CODE],
    )
    fx.compute_allocations(api, cycle["id"])
    fx.open_window(api, cycle["id"])
    fx.set_clock(api, "2026-08-06T00:00:00Z")

    order = fx.create_order(api, cycle["id"], agency["id"], warehouse["id"])
    fx.add_line(api, order["id"], agency["id"], rice["id"], 10)
    fx.submit_order(api, order["id"], agency["id"])
    fx.approve_order(api, order["id"])
    appointment = fx.book_appointment(
        api,
        order["id"],
        dock_number=1,
        window_start="2026-08-10T10:00:00Z",
        window_end="2026-08-10T12:00:00Z",
    )
    return {
        "agency": agency,
        "cycle": cycle,
        "warehouse": warehouse,
        "lot": lot,
        "order": order,
        "appointment": appointment,
    }


def test_11_confirmation_waits_for_the_window_start_and_then_drains_the_lot(api):
    """PRD §3.7: "The current instant must be at or after `window_start`, otherwise
    `ERR_APPOINTMENT_WINDOW_INVALID`." PRD §3.7: "The appointment moves `SCHEDULED →
    DELIVERED`, capturing `delivered_pounds` from the order's `total_pounds` and recording
    the confirming operator in `confirmed_by_user_id`." PRD §3.7: "Each reserved lot has
    the reserved cases subtracted from `cases_on_hand`, subtracted from `cases_committed`,
    and added to `cases_shipped_to_date`; a lot whose `cases_on_hand` reaches zero moves to
    `DEPLETED` with its `monitor_flag` reset to `NONE`."

    Design: Corner/endpoints/confirm_delivery_is_refused_before_the_window_start_and_depletes_the_lot_at_it
    """
    env = _scheduled_ten_case_delivery(api)
    operator = make_warehouse_operator_headers(env["warehouse"]["id"])

    fx.set_clock(api, "2026-08-10T09:59:00Z")
    early = api.confirm_delivery(env["appointment"]["id"], headers=operator)

    validate_error(early, ApiErrorId.ERR_APPOINTMENT_WINDOW_INVALID, 422)
    waiting = fx.read_appointment(api, env["appointment"]["id"])
    assert waiting["status"] == AppointmentStatus.SCHEDULED, (
        f"the refused confirmation must leave the appointment SCHEDULED but got "
        f"{waiting['status']}"
    )

    fx.set_clock(api, "2026-08-10T10:00:00Z")
    delivered = validate_success(
        api.confirm_delivery(env["appointment"]["id"], headers=operator)
    )
    assert delivered["status"] == AppointmentStatus.DELIVERED, (
        f"status expected DELIVERED but got {delivered['status']}"
    )
    assert_pounds(delivered["delivered_pounds"], 200.0, "delivered_pounds")
    assert delivered["confirmed_by_user_id"] == env["warehouse"]["id"], (
        f"confirmed_by_user_id expected {env['warehouse']['id']} but got "
        f"{delivered['confirmed_by_user_id']}"
    )
    lot = fx.read_lot(api, env["lot"]["id"])
    assert lot["status"] == LotStatus.DEPLETED, (
        f"the drained lot expected DEPLETED but got {lot['status']}"
    )
    assert_lot_ledger(lot, cases_on_hand=0, cases_committed=0, cases_shipped_to_date=10)
    order = fx.read_order(api, env["order"]["id"])
    assert order["status"] == OrderStatus.DELIVERED, (
        f"the order expected DELIVERED but got {order['status']}"
    )


def test_12_delivery_credits_the_agency_and_blocks_a_second_appointment(api):
    """PRD §3.7: "The entitlement then has `total_cases_approved` subtracted from its
    `cases_committed` and added to its `cases_delivered`, its `cases_remaining` is
    recomputed, and its `status` becomes `FULLY_DRAWN` when `cases_remaining` reaches zero
    and `PARTIALLY_DRAWN` otherwise." PRD §3.7: "Finally the receiving agency's
    `agency_cases_on_hand` and `delivered_cases_ytd` each grow by the order's
    `total_cases_approved` — the first is the live stock the agency may hand out or return,
    the second a cumulative year-to-date figure that never falls." PRD §3.7: "The order
    must not already have a live appointment: if one exists in `SCHEDULED`, `BLOCKED`, or
    `DELIVERED`, the request answers `ERR_APPOINTMENT_ALREADY_EXISTS` even when the
    requested window is entirely free."

    Design: Corner/endpoints/confirm_delivery_is_refused_before_the_window_start_and_depletes_the_lot_at_it
    """
    env = _scheduled_ten_case_delivery(api)
    fx.set_clock(api, "2026-08-10T10:00:00Z")
    fx.confirm_delivery(api, env["appointment"]["id"], env["warehouse"]["id"])

    agency = fx.read_agency(api, env["agency"]["id"])
    assert agency["agency_cases_on_hand"] == 10, (
        f"agency_cases_on_hand expected 10 but got {agency['agency_cases_on_hand']}"
    )
    assert agency["delivered_cases_ytd"] == 10, (
        f"delivered_cases_ytd expected 10 but got {agency['delivered_cases_ytd']}"
    )
    allocation = fx.read_allocation(api, env["cycle"]["id"], env["agency"]["id"])
    assert allocation["cases_delivered"] == 10, (
        f"cases_delivered expected 10 but got {allocation['cases_delivered']}"
    )
    assert allocation["cases_committed"] == 0, (
        f"cases_committed expected 0 but got {allocation['cases_committed']}"
    )
    assert allocation["cases_remaining"] == 990, (
        f"cases_remaining expected 990 but got {allocation['cases_remaining']}"
    )
    assert allocation["status"] == AllocationStatus.PARTIALLY_DRAWN, (
        f"entitlement status expected PARTIALLY_DRAWN but got {allocation['status']}"
    )
    cycle = fx.read_cycle(api, env["cycle"]["id"])
    assert cycle["draw_posture"] == DrawPosture.PARTIAL, (
        f"draw_posture expected PARTIAL but got {cycle['draw_posture']}"
    )

    response = api.create_delivery_appointment(
        f.delivery_appointment_payload(
            env["order"]["id"], 2, "2026-08-11T10:00:00Z", "2026-08-11T12:00:00Z"
        ),
        headers=make_warehouse_operator_headers(env["warehouse"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_APPOINTMENT_ALREADY_EXISTS, 409)
