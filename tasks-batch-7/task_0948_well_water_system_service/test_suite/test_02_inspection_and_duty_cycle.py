"""Inspections, the duty-cycle cascade and the interval it retimes."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_close,
    assert_instant_equals,
    fixtures,
    ids_of,
    make_technician_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def _five_hop_world():
    """Account, property, moderate-duty well, ACTIVE plan and a started inspection."""
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account = fixtures.new_account("Windrow Acres", "JUR_DELTA", "ap@windrow.example", "NONE")
    prop = fixtures.new_property(account["id"], "5 Windrow", "JUR_DELTA", 22.0, 4, False)
    well = fixtures.new_well(prop["id"], "JUR_DELTA", "DRILLED", 190.0, 6.0)
    plan = fixtures.new_maintenance_plan(well["id"], account["id"])
    technician = fixtures.new_technician("Tomas Weir", "JOURNEYMAN", "JUR_DELTA")
    inspection = fixtures.started_inspection(
        well["id"], technician["id"], "2026-06-01T10:00:00Z"
    )
    return {
        "well_id": well["id"],
        "plan_id": plan["id"],
        "technician_id": technician["id"],
        "inspection_id": inspection["id"],
    }


def test_inspection_completion_writes_the_well_measurements_and_ratio(api):
    """PRD 3.2: "Then, in this exact order: the well's `measured_yield_gpm` is set from
    the inspection's, and the well's `last_inspection_completed_at` is set from the
    inspection's `completed_at`; the well's `pressure_tank_drawdown_gallons` is set from
    the inspection's `observed_drawdown_gallons`, so the duty-cycle ratio is recomputed;
    because the ratio moved, `duty_cycle_class` is re-banded; because the class moved,
    every `ACTIVE` maintenance plan on the well recomputes `interval_days_as_operated`;
    and because the interval moved, those plans recompute `next_due_at`."
    PRD 3.1: "A drawdown of 12.0 gallons gives 2.50; 10.0 gives 3.00; 6.0 gives 5.00;
    5.0 gives 6.00; 4.0 gives 7.50."

    Design: Difficulty/transitive_cascade/inspection_completion_five_hop_cascade_retimes_the_maintenance_plan
    """
    world = _five_hop_world()
    completed = validate_success(
        api.complete_inspection(
            world["inspection_id"],
            {
                "measured_yield_gpm": 15.0,
                "static_level_feet": 42.0,
                "observed_drawdown_gallons": 12.0,
            },
            make_technician_headers(world["technician_id"]),
        )
    )
    assert completed["status"] == "COMPLETED"
    assert_instant_equals(
        completed["completed_at"], "2026-06-01T09:00:00Z", "Inspection.completed_at"
    )

    well = fixtures.get_well(world["well_id"])
    assert_close(well["measured_yield_gpm"], 15.0, "WellProfile.measured_yield_gpm")
    assert_instant_equals(
        well["last_inspection_completed_at"],
        "2026-06-01T09:00:00Z",
        "WellProfile.last_inspection_completed_at",
    )
    assert_close(
        well["pressure_tank_drawdown_gallons"],
        12.0,
        "WellProfile.pressure_tank_drawdown_gallons",
    )
    assert_close(well["duty_cycle_ratio"], 2.50, "WellProfile.duty_cycle_ratio")
    assert well["duty_cycle_class"] == "LOW"


def test_inspection_completion_retimes_the_operated_interval_only(api):
    """PRD 3.10: "`interval_days_as_designed` is computed once at plan creation from the
    duty-cycle class and media in force at that instant, and then **frozen forever** — a
    later pressure-tank replacement leaves it untouched. `interval_days_as_operated` is
    recomputed on every duty-cycle change and every media change, and it alone drives
    `next_due_at`."
    PRD 3.2: "The plans' `compliance_state` is deliberately **not** re-derived here — an
    overdue latch survives this recomputation intact."

    Design: Difficulty/transitive_cascade/inspection_completion_five_hop_cascade_retimes_the_maintenance_plan
    """
    world = _five_hop_world()
    validate_success(
        api.complete_inspection(
            world["inspection_id"],
            {
                "measured_yield_gpm": 15.0,
                "static_level_feet": 42.0,
                "observed_drawdown_gallons": 12.0,
            },
            make_technician_headers(world["technician_id"]),
        )
    )
    plan = fixtures.get_plan(world["plan_id"])
    assert plan["interval_days_as_operated"] == 365
    assert plan["interval_days_as_designed"] == 270
    assert_instant_equals(
        plan["next_due_at"], "2027-06-01T09:00:00Z", "MaintenancePlan.next_due_at"
    )
    assert plan["compliance_state"] == "COMPLIANT"


def _tank_swap_world():
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account = fixtures.new_account(
        "Cedar Hollow Trust", "JUR_ALPHA", "ap@cedarhollow.example", "NONE"
    )
    prop = fixtures.new_property(account["id"], "4 Cedar Hollow", "JUR_ALPHA", 12.0, 3, False)
    well = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 180.0, 6.0)
    plan = fixtures.new_maintenance_plan(well["id"], account["id"])
    return {"well_id": well["id"], "plan_id": plan["id"]}


def test_pressure_tank_replacement_rebands_the_duty_cycle(api):
    """PRD 3.1: "A `PlatformAdmin` or a `Technician` supplies a `new_drawdown_gallons`
    figure; the server writes it onto `pressure_tank_drawdown_gallons`, re-derives the
    duty-cycle ratio and then the duty-cycle class in that order, and — because the class
    may have moved — recomputes `interval_days_as_operated` and then `next_due_at` on
    every `ACTIVE` maintenance plan on that well."
    PRD 3.1: "a ratio of at most 3.00 is `LOW`, a ratio above 3.00 and at most 6.00 is
    `MODERATE`, and anything above 6.00 is `HIGH`."

    Design: Difficulty/dual_variant_calc/maintenance_interval_as_designed_diverges_from_as_operated_after_tank_swap
    """
    world = _tank_swap_world()
    updated = validate_success(
        api.replace_pressure_tank(world["well_id"], {"new_drawdown_gallons": 4.0}, ADMIN)
    )
    assert_close(updated["duty_cycle_ratio"], 7.50, "WellProfile.duty_cycle_ratio")
    assert updated["duty_cycle_class"] == "HIGH"


def test_designed_interval_freezes_while_the_operated_interval_moves(api):
    """PRD 3.10: "The two disagree whenever the well has moved since the plan was
    created: a plan created while the well was `MODERATE` with no media freezes at 270,
    and a pressure-tank replacement that drops the drawdown to 4.0 gallons raises the
    ratio to 7.50, re-bands the class to `HIGH`, and leaves the operated interval at 180
    — same plan, same well, 90 days apart."
    PRD 3.10: "`next_due_at` is always `last_service_date` plus
    `interval_days_as_operated` whole days, with the time-of-day component of the anchor
    preserved."

    Design: Difficulty/dual_variant_calc/maintenance_interval_as_designed_diverges_from_as_operated_after_tank_swap
    """
    world = _tank_swap_world()
    validate_success(
        api.replace_pressure_tank(world["well_id"], {"new_drawdown_gallons": 4.0}, ADMIN)
    )
    plan = fixtures.get_plan(world["plan_id"])
    assert plan["interval_days_as_designed"] == 270
    assert plan["interval_days_as_operated"] == 180
    assert_instant_equals(
        plan["last_service_date"],
        "2026-06-01T09:00:00Z",
        "MaintenancePlan.last_service_date",
    )
    assert_instant_equals(
        plan["next_due_at"], "2026-11-28T09:00:00Z", "MaintenancePlan.next_due_at"
    )
    assert plan["compliance_state"] == "COMPLIANT"


def test_inspection_cannot_be_completed_before_it_is_started(api):
    """PRD 3.2: "It opens in `SCHEDULED`; the other states are `IN_PROGRESS`, `COMPLETED`
    and `CANCELLED`, the last two terminal."
    PRD 3.2: "Starting an inspection that is not in `SCHEDULED` is refused with
    `ERR_INSPECTION_INVALID_STATE`, and that same error guards completion and
    cancellation."

    Design: Corner/state_machines/corner_inspection_starts_in_scheduled_and_cannot_be_completed_first
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Insp Init Co",
        email="ii@corner.example",
        address_line="1 Insp",
        household_size=2,
        technician_name="Insp Tech",
    )
    inspection = fixtures.schedule_inspection(
        world["well_id"], world["technician_id"], "2026-06-01T10:00:00Z"
    )
    assert inspection["status"] == "SCHEDULED"

    validate_error(
        api.complete_inspection(
            inspection["id"],
            {
                "measured_yield_gpm": 10.0,
                "static_level_feet": 30.0,
                "observed_drawdown_gallons": 6.0,
            },
            world["technician_headers"],
        ),
        ApiErrorId.ERR_INSPECTION_INVALID_STATE.value,
        409,
    )
    after = fixtures.get_inspection(inspection["id"])
    assert after["status"] == "SCHEDULED"
    assert after["completed_at"] is None
    assert fixtures.get_well(world["well_id"])["measured_yield_gpm"] is None


def test_completed_inspection_cannot_be_cancelled(api):
    """PRD 3.2: "It opens in `SCHEDULED`; the other states are `IN_PROGRESS`, `COMPLETED`
    and `CANCELLED`, the last two terminal."
    PRD 3.2: "Starting an inspection that is not in `SCHEDULED` is refused with
    `ERR_INSPECTION_INVALID_STATE`, and that same error guards completion and
    cancellation."

    Design: Corner/state_machines/corner_inspection_cancel_from_completed_is_rejected
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Terminal Co",
        email="tc@corner.example",
        address_line="2 Terminal",
        household_size=2,
        technician_name="Term Tech",
    )
    inspection = fixtures.completed_inspection(
        world["well_id"],
        world["technician_id"],
        "2026-06-01T10:00:00Z",
        measured_yield_gpm=14.0,
        static_level_feet=30.0,
        observed_drawdown_gallons=6.0,
    )
    validate_error(
        api.cancel_inspection(inspection["id"], DISPATCHER),
        ApiErrorId.ERR_INSPECTION_INVALID_STATE.value,
        409,
    )
    assert fixtures.get_inspection(inspection["id"])["status"] == "COMPLETED"
    assert_close(
        fixtures.get_well(world["well_id"])["measured_yield_gpm"],
        14.0,
        "WellProfile.measured_yield_gpm",
    )


def test_cancelling_an_in_progress_inspection_leaves_the_well_untouched(api):
    """PRD 3.2: "Cancellation is a dispatcher's act and is available from either
    `SCHEDULED` or `IN_PROGRESS`; it moves the inspection to `CANCELLED` and raises its
    `version` by 1. Nothing on the well is touched by a cancellation."
    PRD 3.1: "A new well profile also starts with `potability_status` `UNKNOWN`,
    `treatment_media` `NONE`, and `measured_yield_gpm`, `hardness_gpg`,
    `last_inspection_completed_at` and `advisory_reason` all null."

    Design: Corner/endpoints/corner_endpoint_inspection_cancel_from_in_progress_leaves_the_well_untouched
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Cancel Inspection Co",
        email="ci@corner.example",
        address_line="1 Cancel",
        technician_name="Cancel Tech",
    )
    inspection = fixtures.schedule_inspection(
        world["well_id"], world["technician_id"], "2026-06-01T10:00:00Z"
    )
    validate_success(api.start_inspection(inspection["id"], world["technician_headers"]))

    cancelled = validate_success(api.cancel_inspection(inspection["id"], DISPATCHER))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["completed_at"] is None
    assert cancelled["measured_yield_gpm"] is None

    well = fixtures.get_well(world["well_id"])
    assert well["measured_yield_gpm"] is None
    assert well["last_inspection_completed_at"] is None
    assert_close(
        well["pressure_tank_drawdown_gallons"],
        6.0,
        "WellProfile.pressure_tank_drawdown_gallons",
    )
    assert_close(well["duty_cycle_ratio"], 5.00, "WellProfile.duty_cycle_ratio")
    assert well["duty_cycle_class"] == "MODERATE"

    rows, _ = validate_paginated(
        api.list_inspections(
            DISPATCHER,
            params={"well_profile_id": world["well_id"], "status": "CANCELLED"},
        )
    )
    assert ids_of(rows) == [inspection["id"]]


def test_duty_cycle_band_edges_drive_the_designed_interval(api):
    """PRD 3.1: "Both band ceilings are inclusive, so the default drawdown of 6.0
    produces a ratio of exactly 5.00 and a class of `MODERATE`, a drawdown of exactly
    10.0 produces exactly 3.00 and `LOW`, and a drawdown of 4.99 produces 6.01 and
    `HIGH`."
    PRD 3.10: "The base intervals are 365 days for `LOW`, 270 for `MODERATE` and 180 for
    `HIGH`."
    PRD 3.10: "At creation the plan sets both intervals, sets `last_service_date` to the
    plan's own `created_at`, sets `next_due_at` to `last_service_date` plus
    `interval_days_as_operated` days, mirrors `filter_media` from the well's
    `treatment_media`, and starts `monthly_salt_lbs` and `salt_remaining_lbs` at 0.0 with
    `last_filter_change_date`, `filter_next_due_date`, `last_salt_delivery_date`,
    `salt_next_due_date` and `overdue_latched_at` all null."

    Design: Corner/calculations/corner_calc_duty_cycle_bands_drive_the_designed_maintenance_interval
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    account = fixtures.new_account("Duty Band Co", "JUR_ALPHA", "db@corner.example")
    prop = fixtures.new_property(account["id"], "3 Duty", "JUR_ALPHA", 10.0, 3)

    cases = [
        (10.0, 3.00, "LOW", 365, "2027-06-01T00:00:00Z"),
        (5.0, 6.00, "MODERATE", 270, "2027-02-26T00:00:00Z"),
        (4.99, 6.01, "HIGH", 180, "2026-11-28T00:00:00Z"),
    ]
    for drawdown, ratio, band, interval, next_due in cases:
        well = validate_success(
            api.create_well_profile(
                {
                    "property_id": prop["id"],
                    "jurisdiction_code": "JUR_ALPHA",
                    "well_type": "DRILLED",
                    "depth_feet": 200.0,
                    "pressure_tank_drawdown_gallons": drawdown,
                },
                ADMIN,
            ),
            201,
        )
        assert_close(well["duty_cycle_ratio"], ratio, "WellProfile.duty_cycle_ratio")
        assert well["duty_cycle_class"] == band

        plan = validate_success(
            api.create_maintenance_plan(
                {"well_profile_id": well["id"], "account_id": account["id"]}, ADMIN
            ),
            201,
        )
        assert plan["interval_days_as_designed"] == interval
        assert plan["interval_days_as_operated"] == interval
        assert_instant_equals(
            plan["next_due_at"], next_due, "MaintenancePlan.next_due_at"
        )
        if drawdown == 10.0:
            assert plan["filter_media"] == "NONE"
            assert_close(plan["monthly_salt_lbs"], 0.0, "MaintenancePlan.monthly_salt_lbs")
            assert plan["compliance_state"] == "COMPLIANT"
            assert plan["overdue_latched_at"] is None
