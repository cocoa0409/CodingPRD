"""Exhibit property between shows: metered storage billing and refurbishment work orders."""

from test_helpers import (
    REFURB_OVERRUN_TOLERANCE,
    STORAGE,
    ApiErrorId,
    assert_crate,
    assert_exhibit_asset,
    assert_refurb_work_order,
    get_asset,
    get_crate,
    get_refurb,
    make_warehouse_agent_headers,
    open_refurb,
    refurb_progress,
    register_asset,
    run_storage_billing,
    setup_refurb_in_progress,
    setup_show_ground,
    setup_warehouse_with_crate,
    validate_error,
    validate_success,
)

# The warehouse terms the storage scenarios are billed against: a thirty-day free
# allowance at 2200 cents per hundredweight per month.
WAREHOUSE_STORAGE_TERMS = {
    "free_days": STORAGE["DEFAULT_FREE_DAYS"],
    "storage_rate_cents_per_cwt_per_month": STORAGE["DEFAULT_RATE_CENTS_PER_CWT_PER_MONTH"],
}
WAREHOUSE_CAPACITY_CWT = 1000

# One 1250 lb crate is thirteen whole hundredweight.
CRATE_WEIGHT_LBS = 1250
CHECKED_IN_AT = "2026-10-01T00:00:00Z"

AS_OF_AT_FREE_DAY_BOUNDARY = "2026-10-31T00:00:00Z"    # exactly 30 days stored
AS_OF_ONE_DAY_PAST_BOUNDARY = "2026-11-01T00:00:00Z"   # 31 days stored
AS_OF_THIRTY_FIVE_DAYS = "2026-11-05T00:00:00Z"        # 35 days stored
AS_OF_SIXTY_ONE_DAYS = "2026-12-01T00:00:00Z"          # 61 days stored

ONE_BILLABLE_MONTH_CENTS = 28600
TWO_BILLABLE_MONTHS_CENTS = 57200

REFURB_ESTIMATE_CENTS = 500000
ACTUAL_AT_TOLERANCE_CEILING_CENTS = 600000
ACTUAL_ONE_CENT_PAST_CEILING_CENTS = 600001
ACTUAL_UNDER_CEILING_CENTS = 550000
ACTUAL_UNDER_ESTIMATE_CENTS = 400000


def _stored_crate_ground():
    """A warehouse on the standard storage terms holding one 1250 lb crate whose
    stored_since is exactly CHECKED_IN_AT."""
    return setup_warehouse_with_crate(
        weight_lbs=CRATE_WEIGHT_LBS,
        capacity_cwt=WAREHOUSE_CAPACITY_CWT,
        checked_in_at=CHECKED_IN_AT,
        warehouse_overrides=dict(WAREHOUSE_STORAGE_TERMS),
    )


class TestStorageBillingFreeDayBoundary:
    """The exact zero-quantity boundary on the storage-day metric."""

    def test_storage_run_at_exactly_free_days_charges_the_crate_nothing(self):
        """PRD §3.4: "The boundary is exact: a crate stored for exactly `free_days`
        days yields zero billable days, zero billable months and a charge of exactly
        zero, while one further day yields a full month."
        PRD §3.4: "The run considers every crate whose `warehouse_id` is this
        warehouse, whose `status` is `AT_ADVANCE_WAREHOUSE` or
        `RETURNED_TO_WAREHOUSE`, and whose `stored_since` is non-null; crates in any
        other status are skipped entirely and keep whatever `storage_charge_cents`
        they already carried."
        PRD §3.4: "The run's response reports the warehouse, the `as_of` instant it
        used, the `crate_count` it charged and the `total_storage_charge_cents`,
        which is the sum of the per-crate rounded charges."

        Design: Difficulty/boundary_precision_check/storage_free_days_exact_boundary_yields_zero_charge
        """
        ground = _stored_crate_ground()
        warehouse_id = ground["warehouse"]["id"]
        crate_id = ground["crate"]["id"]

        run = run_storage_billing(warehouse_id, AS_OF_AT_FREE_DAY_BOUNDARY)

        assert run["warehouse_id"] == warehouse_id, (
            "The run reports the warehouse it was requested against"
        )
        assert run["crate_count"] == 1, (
            "The one AT_ADVANCE_WAREHOUSE crate carrying a non-null stored_since "
            f"qualifies for the run, got crate_count {run['crate_count']}"
        )
        assert run["total_storage_charge_cents"] == 0, (
            "30 days stored against a 30 free-day allowance leaves zero billable "
            "days, so the run total is exactly zero, got "
            f"{run['total_storage_charge_cents']}"
        )

        crate = get_crate(crate_id)
        assert_crate(crate)
        assert crate["status"] == "AT_ADVANCE_WAREHOUSE", (
            "The crate is still held at the advance warehouse and so was metered"
        )
        assert crate["storage_charge_cents"] == 0, (
            "Zero billable months multiplied by thirteen hundredweight at 2200 "
            "cents leaves the crate's storage_charge_cents at exactly zero, got "
            f"{crate['storage_charge_cents']}"
        )

    def test_storage_run_one_day_past_free_days_charges_a_whole_month(self):
        """PRD §3.4: "The boundary is exact: a crate stored for exactly `free_days`
        days yields zero billable days, zero billable months and a charge of exactly
        zero, while one further day yields a full month."
        PRD §3.4: "For each one, the elapsed time from `stored_since` to `as_of` is
        converted to whole days by discarding any partial day; the warehouse's
        `free_days` allowance is subtracted, with the result floored at zero to give
        the billable days; and those billable days are divided by thirty and rounded
        **up** to a whole number of billable months."
        PRD §3.4: "The crate's `storage_charge_cents` is then its `weight_lbs`
        divided by one hundred and rounded up to a whole hundredweight, multiplied by
        the warehouse's `storage_rate_cents_per_cwt_per_month`, multiplied by the
        billable months, all rounded half up to a whole cent."

        Design: Difficulty/boundary_precision_check/storage_free_days_exact_boundary_yields_zero_charge
        """
        ground = _stored_crate_ground()
        warehouse_id = ground["warehouse"]["id"]
        crate_id = ground["crate"]["id"]

        at_boundary = run_storage_billing(warehouse_id, AS_OF_AT_FREE_DAY_BOUNDARY)
        assert at_boundary["total_storage_charge_cents"] == 0, (
            "The free-day arm of the boundary: exactly 30 stored days bills nothing"
        )

        one_day_past = run_storage_billing(warehouse_id, AS_OF_ONE_DAY_PAST_BOUNDARY)
        assert one_day_past["total_storage_charge_cents"] == ONE_BILLABLE_MONTH_CENTS, (
            "One further day leaves one billable day, which ceils to a whole "
            f"billable month of {ONE_BILLABLE_MONTH_CENTS} cents, got "
            f"{one_day_past['total_storage_charge_cents']}"
        )

        five_days_past = run_storage_billing(warehouse_id, AS_OF_THIRTY_FIVE_DAYS)
        assert five_days_past["crate_count"] == 1, (
            "The same single crate is metered on every run"
        )
        assert five_days_past["total_storage_charge_cents"] == ONE_BILLABLE_MONTH_CENTS, (
            "35 stored days leave 5 billable days, still one whole billable month "
            f"of {ONE_BILLABLE_MONTH_CENTS} cents, got "
            f"{five_days_past['total_storage_charge_cents']}"
        )

        crate = get_crate(crate_id)
        assert_crate(crate)
        assert crate["storage_charge_cents"] == ONE_BILLABLE_MONTH_CENTS, (
            "The run stamps the per-crate rounded charge onto the crate itself"
        )


class TestStorageBillingPartialMonthCeiling:
    """A part-used billable month is charged as a whole one."""

    def test_sixty_one_stored_days_ceil_to_two_whole_billable_months(self):
        """PRD §3.4: "For each one, the elapsed time from `stored_since` to `as_of` is
        converted to whole days by discarding any partial day; the warehouse's
        `free_days` allowance is subtracted, with the result floored at zero to give
        the billable days; and those billable days are divided by thirty and rounded
        **up** to a whole number of billable months."
        PRD §3.4: "The crate's `storage_charge_cents` is then its `weight_lbs`
        divided by one hundred and rounded up to a whole hundredweight, multiplied by
        the warehouse's `storage_rate_cents_per_cwt_per_month`, multiplied by the
        billable months, all rounded half up to a whole cent."
        PRD §2.6: "Storage charges are computed and rounded per crate and then added."

        Design: Corner/calculations/storage_billing_ceils_partial_month_to_two_months
        """
        ground = _stored_crate_ground()
        warehouse_id = ground["warehouse"]["id"]
        crate_id = ground["crate"]["id"]

        run = run_storage_billing(warehouse_id, AS_OF_SIXTY_ONE_DAYS)

        assert run["crate_count"] == 1, (
            f"One metered crate sits at this warehouse, got {run['crate_count']}"
        )
        assert run["total_storage_charge_cents"] == TWO_BILLABLE_MONTHS_CENTS, (
            "61 stored days leave 31 billable days, which ceil to two whole "
            f"{STORAGE['DAYS_PER_BILLABLE_MONTH']}-day billable months and bill "
            f"{TWO_BILLABLE_MONTHS_CENTS} cents rather than the "
            f"{ONE_BILLABLE_MONTH_CENTS} a single month would cost, got "
            f"{run['total_storage_charge_cents']}"
        )

        crate = get_crate(crate_id)
        assert_crate(crate)
        assert crate["storage_charge_cents"] == TWO_BILLABLE_MONTHS_CENTS, (
            "The two-month charge is stamped onto the crate that earned it"
        )


class TestRefurbStartRequiresStoredAsset:
    """An OPEN work order may only start against property the shop actually holds."""

    def test_starting_work_on_an_asset_still_in_design_is_refused(self, api):
        """PRD §3.4: "Starting the work moves the order `OPEN → IN_PROGRESS` and
        requires the asset to be `IN_STORAGE` with its `current_warehouse_id` equal
        to the work order's `warehouse_id` — the shop must actually hold the
        property."
        PRD §3.4: "Registered assets begin `IN_DESIGN` with `current_warehouse_id`
        null, `refurb_cycles_count` at 0 and `stored_since` null."
        PRD §2.9: "The target sits in a from-state the requested transition declares
        — otherwise `ERR_INVALID_STATE_TRANSITION` (409)."

        Design: Difficulty/cross_entity_state_dependency/refurb_start_gated_by_asset_not_in_storage
        """
        ground = setup_show_ground(with_warehouse=True)
        warehouse_id = ground["warehouse"]["id"]

        asset = register_asset(ground["exhibitor"]["id"])
        assert_exhibit_asset(asset)
        assert asset["status"] == "IN_DESIGN", (
            "A registered asset that was never fabricated sits at IN_DESIGN, got "
            f"{asset['status']}"
        )
        assert asset["current_warehouse_id"] is None, (
            "An IN_DESIGN asset is held by no warehouse"
        )

        refurb = open_refurb(asset["id"], warehouse_id, scope="STRUCTURAL_REPAIR")
        assert_refurb_work_order(refurb)
        assert refurb["status"] == "OPEN", (
            f"A new work order is born OPEN, got {refurb['status']}"
        )

        response = api.refurb_progress(
            refurb["id"],
            {"to_status": "IN_PROGRESS"},
            make_warehouse_agent_headers(warehouse_id),
        )

        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

    def test_refused_start_leaves_the_work_order_open_and_the_asset_in_design(self, api):
        """PRD §3.4: "Starting also cascades the asset `IN_STORAGE → IN_REFURB`, which
        is what makes it unavailable for staging."
        PRD §3.4: "It is born `OPEN` with `actual_cents`, `variance_cents` and
        `condition_grade_after` all null."
        PRD §2.5: "`version` — an integer that begins at 1 when the row is created
        and increases by exactly 1 on every mutation of that row, again including
        server-initiated cascades."

        Design: Difficulty/cross_entity_state_dependency/refurb_start_gated_by_asset_not_in_storage
        """
        ground = setup_show_ground(with_warehouse=True)
        warehouse_id = ground["warehouse"]["id"]

        asset = register_asset(ground["exhibitor"]["id"])
        refurb = open_refurb(asset["id"], warehouse_id, scope="STRUCTURAL_REPAIR")
        assert refurb["version"] == 1, "The work order has not been mutated yet"

        response = api.refurb_progress(
            refurb["id"],
            {"to_status": "IN_PROGRESS"},
            make_warehouse_agent_headers(warehouse_id),
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

        after = get_refurb(refurb["id"])
        assert_refurb_work_order(after)
        assert after["status"] == "OPEN", (
            f"The refused start leaves the work order at OPEN, got {after['status']}"
        )
        assert after["actual_cents"] is None, "A work order that never started records no cost"
        assert after["variance_cents"] is None, "Variance is only written at completion"
        assert after["condition_grade_after"] is None, (
            "No post-work grade is recorded by a refused start"
        )
        assert after["version"] == 1, (
            "The rejected transition mutated nothing, so the work order's version "
            f"still reads 1, got {after['version']}"
        )

        asset_after = get_asset(asset["id"])
        assert_exhibit_asset(asset_after)
        assert asset_after["status"] == "IN_DESIGN", (
            "The asset never entered IN_REFURB because the start was refused, got "
            f"{asset_after['status']}"
        )
        assert asset_after["current_warehouse_id"] is None, (
            "No warehouse took custody of the asset"
        )
        assert asset_after["refurb_cycles_count"] == 0, (
            "No refurbishment cycle was begun, let alone completed"
        )
        assert asset_after["stored_since"] is None, (
            "The asset never entered storage, so stored_since is still null"
        )


class TestRefurbCompletionOverrunTolerance:
    """The twenty percent overrun ceiling on a completing work order."""

    def test_actual_cost_exactly_at_the_tolerance_ceiling_is_admitted(self, api):
        """PRD §3.4: "It may not exceed the estimate inflated by the twenty percent
        overrun tolerance — that is, `estimate_cents` multiplied by 1.20 and rounded
        half up — unless an `APPLIED` change order exists that covers the overrun; a
        bare overrun is refused with `ERR_REFURB_OVERRUN_UNAPPROVED`."
        PRD §3.4: "On success the work order records `variance_cents` as
        `actual_cents` minus `estimate_cents` — a figure that may legitimately be
        negative when the shop came in under estimate — and the asset cascades
        `IN_REFURB → IN_STORAGE` with `refurb_cycles_count` increased by one,
        `condition_grade` overwritten by `condition_grade_after`, and `stored_since`
        re-stamped with the logical clock's current instant, restarting the free-day
        allowance."

        Design: Corner/calculations/refurb_overrun_tolerance_boundary_exactly_120_percent_allowed
        """
        ground = setup_refurb_in_progress(estimate_cents=REFURB_ESTIMATE_CENTS)
        warehouse_id = ground["warehouse"]["id"]

        response = api.refurb_progress(
            ground["refurb"]["id"],
            {
                "to_status": "COMPLETED",
                "actual_cents": ACTUAL_AT_TOLERANCE_CEILING_CENTS,
                "condition_grade_after": "A",
            },
            make_warehouse_agent_headers(warehouse_id),
        )
        completed = validate_success(response, 200)

        assert_refurb_work_order(completed)
        assert completed["status"] == "COMPLETED", (
            f"{ACTUAL_AT_TOLERANCE_CEILING_CENTS} cents lands exactly on "
            f"{REFURB_ESTIMATE_CENTS} times {REFURB_OVERRUN_TOLERANCE}, which the "
            f"tolerance admits, got {completed['status']}"
        )
        assert completed["actual_cents"] == ACTUAL_AT_TOLERANCE_CEILING_CENTS, (
            "The supplied actual cost is recorded as given"
        )
        assert completed["variance_cents"] == 100000, (
            "variance_cents is the exact integer actual_cents minus estimate_cents, "
            f"got {completed['variance_cents']}"
        )

        asset = get_asset(ground["asset"]["id"])
        assert_exhibit_asset(asset)
        assert asset["refurb_cycles_count"] == 1, (
            "Completing the work lifts refurb_cycles_count by one, got "
            f"{asset['refurb_cycles_count']}"
        )

    def test_actual_cost_one_cent_past_the_ceiling_is_refused(self, api):
        """PRD §3.4: "It may not exceed the estimate inflated by the twenty percent
        overrun tolerance — that is, `estimate_cents` multiplied by 1.20 and rounded
        half up — unless an `APPLIED` change order exists that covers the overrun; a
        bare overrun is refused with `ERR_REFURB_OVERRUN_UNAPPROVED`."
        PRD §2.9: "Refurbishment cost overrun is within tolerance or covered —
        otherwise `ERR_REFURB_OVERRUN_UNAPPROVED` (422)."

        Design: Corner/validations/refurb_overrun_beyond_tolerance_rejected
        """
        ground = setup_refurb_in_progress(estimate_cents=REFURB_ESTIMATE_CENTS)
        warehouse_id = ground["warehouse"]["id"]

        response = api.refurb_progress(
            ground["refurb"]["id"],
            {
                "to_status": "COMPLETED",
                "actual_cents": ACTUAL_ONE_CENT_PAST_CEILING_CENTS,
                "condition_grade_after": "A",
            },
            make_warehouse_agent_headers(warehouse_id),
        )

        validate_error(response, ApiErrorId.ERR_REFURB_OVERRUN_UNAPPROVED, 422)

        refurb = get_refurb(ground["refurb"]["id"])
        assert_refurb_work_order(refurb)
        assert refurb["status"] == "IN_PROGRESS", (
            "A bare overrun leaves the work order where it was, got "
            f"{refurb['status']}"
        )
        assert refurb["variance_cents"] is None, (
            "No variance is written when the completion is refused"
        )

        asset = get_asset(ground["asset"]["id"])
        assert_exhibit_asset(asset)
        assert asset["status"] == "IN_REFURB", (
            "The asset stays in the shop because the completion never happened, got "
            f"{asset['status']}"
        )


class TestRefurbCompletionConditionGrade:
    """The post-work grade may not be worse than the grade the asset carries."""

    def test_completing_with_a_worse_condition_grade_is_refused(self, api):
        """PRD §3.4: "And `condition_grade_after` may not be worse than the asset's
        current `condition_grade`, where the grades run `A` better than `B` better
        than `C` better than `D`; a regression is refused with
        `ERR_CONDITION_GRADE_REGRESSION`."
        PRD §2.9: "The post-refurbishment grade does not regress — otherwise
        `ERR_CONDITION_GRADE_REGRESSION` (422)."
        PRD §3.4: "A `condition_grade` of `A`, `B`, `C` or `D` may be supplied and
        defaults to `A`."

        Design: Corner/validations/condition_grade_regression_on_refurb_rejected
        """
        ground = setup_refurb_in_progress(estimate_cents=REFURB_ESTIMATE_CENTS)
        warehouse_id = ground["warehouse"]["id"]

        response = api.refurb_progress(
            ground["refurb"]["id"],
            {
                "to_status": "COMPLETED",
                "actual_cents": ACTUAL_UNDER_ESTIMATE_CENTS,
                "condition_grade_after": "C",
            },
            make_warehouse_agent_headers(warehouse_id),
        )

        validate_error(response, ApiErrorId.ERR_CONDITION_GRADE_REGRESSION, 422)

        refurb = get_refurb(ground["refurb"]["id"])
        assert_refurb_work_order(refurb)
        assert refurb["status"] == "IN_PROGRESS", (
            "The refused completion leaves the work order IN_PROGRESS, got "
            f"{refurb['status']}"
        )

        asset = get_asset(ground["asset"]["id"])
        assert_exhibit_asset(asset)
        assert asset["status"] == "IN_REFURB", (
            f"The asset is still in the shop, got {asset['status']}"
        )
        assert asset["refurb_cycles_count"] == 0, (
            "A refused completion counts no cycle, got "
            f"{asset['refurb_cycles_count']}"
        )
        assert asset["condition_grade"] == "A", (
            "The grade the asset carries is untouched by the refused write, got "
            f"{asset['condition_grade']}"
        )


class TestRefurbCompletionCyclesAssetBackToStorage:
    """The asset cycles IN_STORAGE to IN_REFURB and back on a completed work order."""

    def test_completion_returns_the_asset_to_storage_and_counts_the_cycle(self):
        """PRD §3.4: "Starting also cascades the asset `IN_STORAGE → IN_REFURB`, which
        is what makes it unavailable for staging."
        PRD §3.4: "On success the work order records `variance_cents` as
        `actual_cents` minus `estimate_cents` — a figure that may legitimately be
        negative when the shop came in under estimate — and the asset cascades
        `IN_REFURB → IN_STORAGE` with `refurb_cycles_count` increased by one,
        `condition_grade` overwritten by `condition_grade_after`, and `stored_since`
        re-stamped with the logical clock's current instant, restarting the free-day
        allowance."

        Design: Corner/state_machines/refurb_completion_cycles_asset_back_to_storage_and_counts_the_cycle
        """
        ground = setup_refurb_in_progress(estimate_cents=REFURB_ESTIMATE_CENTS)
        warehouse_id = ground["warehouse"]["id"]

        mid_asset = get_asset(ground["asset"]["id"])
        assert_exhibit_asset(mid_asset)
        assert mid_asset["status"] == "IN_REFURB", (
            "Starting the work took the asset out of storage and into the shop, got "
            f"{mid_asset['status']}"
        )
        assert mid_asset["refurb_cycles_count"] == 0, (
            "No cycle has completed yet, got "
            f"{mid_asset['refurb_cycles_count']}"
        )

        completed = refurb_progress(
            ground["refurb"]["id"],
            warehouse_id,
            "COMPLETED",
            actual_cents=ACTUAL_UNDER_CEILING_CENTS,
            condition_grade_after="A",
        )

        assert_refurb_work_order(completed)
        assert completed["status"] == "COMPLETED", (
            f"The work order closes at COMPLETED, got {completed['status']}"
        )
        assert completed["variance_cents"] == 50000, (
            "variance_cents is actual_cents minus estimate_cents in exact integer "
            f"arithmetic, got {completed['variance_cents']}"
        )

        asset = get_asset(ground["asset"]["id"])
        assert_exhibit_asset(asset)
        assert asset["status"] == "IN_STORAGE", (
            f"The completed work returns the asset to storage, got {asset['status']}"
        )
        assert asset["refurb_cycles_count"] == 1, (
            "The completed cycle lifts refurb_cycles_count from 0 to 1, got "
            f"{asset['refurb_cycles_count']}"
        )
        assert asset["condition_grade"] == "A", (
            "condition_grade is overwritten by the supplied condition_grade_after, "
            f"got {asset['condition_grade']}"
        )
        assert asset["current_warehouse_id"] == warehouse_id, (
            "The asset comes back to the same warehouse that did the work"
        )
        assert asset["stored_since"] is not None, (
            "stored_since is re-stamped on the way back into storage, restarting "
            "the free-day allowance"
        )
