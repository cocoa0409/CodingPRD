"""Recurring maintenance: the two consumable clocks and the compliance latch."""

from test_helpers import (
    ApiErrorId,
    OFFICER_ALPHA,
    TEST_USERS,
    assert_close,
    assert_instant_equals,
    fixtures,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]

CLEAN_ANALYTES = {
    "nitrate_mg_l": 1.0,
    "arsenic_mg_l": 0.001,
    "lead_mg_l": 0.001,
    "iron_mg_l": 0.10,
}


def test_a_plan_suspends_resumes_and_only_terminates_from_suspended(api):
    """PRD 3.10: "A `PlatformAdmin` may suspend an `ACTIVE` plan, moving it to `SUSPENDED`
    with `version` up by 1, and may resume a `SUSPENDED` plan, which recomputes
    `interval_days_as_operated` and `next_due_at` from the current duty-cycle class and
    raises `version` by 1, closing the active-suspended-active cycle. A `SUSPENDED` plan
    may be terminated, moving it to `TERMINATED` with `version` up by 1; an `ACTIVE` plan
    cannot be terminated directly."
    PRD 3.10: "a movement from the wrong state — including a salt delivery, a filter change
    or a compliance evaluation on a plan that is not `ACTIVE` — is refused with
    `ERR_MAINTENANCE_PLAN_INVALID_STATE`."

    Design: Corner/state_machines/corner_maintenance_plan_suspend_resume_terminate_cycle
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account = fixtures.new_account("Plan Cycle Co", "JUR_ALPHA", "pc@corner.example")
    prop = fixtures.new_property(account["id"], "5 Plan", "JUR_ALPHA", 10.0, 2)
    well = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 200.0, 6.0)
    plan = fixtures.new_maintenance_plan(well["id"], account["id"])

    validate_error(
        api.terminate_maintenance_plan(plan["id"], ADMIN),
        ApiErrorId.ERR_MAINTENANCE_PLAN_INVALID_STATE.value,
        409,
    )
    validate_success(api.suspend_maintenance_plan(plan["id"], ADMIN))
    resumed = validate_success(api.resume_maintenance_plan(plan["id"], ADMIN))

    assert resumed["status"] == "ACTIVE"
    assert resumed["interval_days_as_operated"] == 270
    assert_instant_equals(
        resumed["next_due_at"], "2027-02-26T09:00:00Z", "MaintenancePlan.next_due_at"
    )


def test_the_overdue_latch_survives_an_interval_recomputation(api):
    """PRD 3.10: "A `PlatformAdmin` runs the evaluation against an `ACTIVE`, `COMPLIANT`
    plan; when the logical clock is **strictly past** `next_due_at`, the plan moves
    `COMPLIANT → OVERDUE`, `overdue_latched_at` is stamped from the logical clock and
    `version` rises by 1. That latch is never cleared by an interval recomputation that
    happens to push `next_due_at` back into the future — a naive as-of rule would silently
    un-overdue the plan, and the latch forbids it."
    PRD 3.1: "`interval_days_as_designed` is untouched, and so is any overdue latch."

    Design: Corner/state_machines/corner_maintenance_compliance_latch_survives_interval_recomputation
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account = fixtures.new_account("Latch Co", "JUR_ALPHA", "lt@corner.example")
    prop = fixtures.new_property(account["id"], "6 Latch", "JUR_ALPHA", 10.0, 2)
    well = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 200.0, 6.0)
    plan = fixtures.new_maintenance_plan(well["id"], account["id"])

    fixtures.set_clock("2027-03-01T09:00:00Z")
    validate_success(api.evaluate_plan_compliance(plan["id"], ADMIN))

    updated_well = validate_success(
        api.replace_pressure_tank(well["id"], {"new_drawdown_gallons": 12.0}, ADMIN)
    )
    assert_close(updated_well["duty_cycle_ratio"], 2.50, "WellProfile.duty_cycle_ratio")
    assert updated_well["duty_cycle_class"] == "LOW"

    latched = fixtures.get_plan(plan["id"])
    assert latched["interval_days_as_operated"] == 365
    assert_instant_equals(
        latched["next_due_at"], "2027-06-01T09:00:00Z", "MaintenancePlan.next_due_at"
    )
    assert latched["compliance_state"] == "OVERDUE"
    assert_instant_equals(
        latched["overdue_latched_at"],
        "2027-03-01T09:00:00Z",
        "MaintenancePlan.overdue_latched_at",
    )


def test_the_salt_and_filter_clocks_reset_on_different_schedules(api):
    """PRD 3.10: "otherwise the day count is the surplus multiplied by 30 and divided by
    `monthly_salt_lbs`, taking the floor. `salt_next_due_date` is
    `last_salt_delivery_date` plus that many days."
    PRD 3.10: "The **filter clock** is a fixed interval from the change date: 90 days for
    `SEDIMENT`, 180 days for `CARBON` and 1825 days for `SOFTENER_RESIN`."
    PRD 3.10: "A delivery **does not touch the filter clock and does not touch
    `compliance_state`**."

    Design: Corner/calculations/corner_salt_and_filter_clocks_reset_on_different_schedules
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Twoclock Co",
        email="tc2@corner.example",
        address_line="2 Twoclock",
        household_size=5,
        drawdown=12.0,
        technician_name="Twoclock Tech",
    )
    plan = fixtures.new_maintenance_plan(world["well_id"], world["account_id"])
    chem = fixtures.chemical_panel(
        world["well_id"],
        world["technician_id"],
        "2026-06-01T00:00:00Z",
        "2026-06-01T06:00:00Z",
        OFFICER_ALPHA,
        hardness_gpg=20.0,
        **CLEAN_ANALYTES,
    )
    recommendation = fixtures.create_recommendation(world["well_id"], chem["id"])
    fixtures.accept_recommendation(recommendation["id"], world["account_id"])

    fixtures.deliver_salt(plan["id"], 300.0)
    fixtures.change_filter(plan["id"], world["technician_headers"])

    refreshed = fixtures.get_plan(plan["id"])
    assert_close(refreshed["monthly_salt_lbs"], 64.3, "MaintenancePlan.monthly_salt_lbs")
    assert_close(
        refreshed["salt_remaining_lbs"], 300.0, "MaintenancePlan.salt_remaining_lbs"
    )
    assert_instant_equals(
        refreshed["last_salt_delivery_date"],
        "2026-06-01T09:00:00Z",
        "MaintenancePlan.last_salt_delivery_date",
    )
    assert_instant_equals(
        refreshed["salt_next_due_date"],
        "2026-09-30T09:00:00Z",
        "MaintenancePlan.salt_next_due_date",
    )
    assert_instant_equals(
        refreshed["last_filter_change_date"],
        "2026-06-01T09:00:00Z",
        "MaintenancePlan.last_filter_change_date",
    )
    assert_instant_equals(
        refreshed["filter_next_due_date"],
        "2031-05-31T09:00:00Z",
        "MaintenancePlan.filter_next_due_date",
    )
    assert refreshed["filter_media"] == "SOFTENER_RESIN"


def test_the_salt_capacity_ceiling_is_inclusive_and_the_minimum_is_a_payload_rule(api):
    """PRD 3.10: "A delivery that would push `salt_remaining_lbs` above
    `SALT_TANK_CAPACITY_LBS` (300 pounds) is refused with
    `ERR_SALT_DELIVERY_EXCEEDS_CAPACITY`, and landing exactly on 300.0 is allowed."
    PRD 3.10: "A delivery smaller than `SALT_DELIVERY_MIN_LBS` (40.0 pounds) is refused at
    the payload gate with `ERR_VALIDATION`, and exactly 40.0 is allowed."
    PRD 3.10: "It is null whenever `monthly_salt_lbs` is at most 0.0 or
    `last_salt_delivery_date` is still null."

    Design: Corner/validations/corner_validation_salt_delivery_capacity_and_minimum_boundaries
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    account = fixtures.new_account("Salt Capacity Co", "JUR_ALPHA", "sc@corner.example")
    prop = fixtures.new_property(account["id"], "300 Salt", "JUR_ALPHA", 10.0, 3)
    well = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 200.0)
    plan = fixtures.new_maintenance_plan(well["id"], account["id"])

    validate_success(
        api.record_salt_delivery(
            plan["id"],
            {"delivered_lbs": 300.0, "expected_maintenance_plan_version": plan["version"]},
            ADMIN,
        )
    )
    current = fixtures.plan_version(plan["id"])

    validate_error(
        api.record_salt_delivery(
            plan["id"],
            {"delivered_lbs": 40.0, "expected_maintenance_plan_version": current},
            ADMIN,
        ),
        ApiErrorId.ERR_SALT_DELIVERY_EXCEEDS_CAPACITY.value,
        422,
    )
    validate_error(
        api.record_salt_delivery(
            plan["id"],
            {"delivered_lbs": 39.9, "expected_maintenance_plan_version": current},
            ADMIN,
        ),
        ApiErrorId.ERR_VALIDATION.value,
        400,
    )

    refreshed = fixtures.get_plan(plan["id"])
    assert_close(
        refreshed["salt_remaining_lbs"], 300.0, "MaintenancePlan.salt_remaining_lbs"
    )
    assert_instant_equals(
        refreshed["last_salt_delivery_date"],
        "2026-06-01T00:00:00Z",
        "MaintenancePlan.last_salt_delivery_date",
    )
    assert refreshed["salt_next_due_date"] is None
    assert refreshed["version"] == current


def test_the_filter_change_minimum_interval_is_strictly_less_than_thirty_days(api):
    """PRD 3.10: "A change recorded **fewer than** `FILTER_MIN_DAYS_BETWEEN_CHANGES` (30
    days) after the previous one is refused with `ERR_FILTER_CHANGE_TOO_SOON`; exactly 30
    days is allowed."
    PRD 3.10: "`filter_next_due_date` is null while `filter_media` is `NONE` and null while
    `last_filter_change_date` is null; otherwise it is `last_filter_change_date` plus the
    media's interval."
    PRD 3.10: "A filter change **does not touch the salt clock and does not clear an
    overdue latch**."

    Design: Corner/validations/corner_validation_filter_change_minimum_interval_boundary
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    account = fixtures.new_account("Filter Clock Co", "JUR_ALPHA", "fc@corner.example")
    prop = fixtures.new_property(account["id"], "30 Filter", "JUR_ALPHA", 10.0, 3)
    well = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 200.0)
    plan = fixtures.new_maintenance_plan(well["id"], account["id"])

    validate_success(api.record_filter_change(plan["id"], DISPATCHER))

    fixtures.set_clock("2026-06-30T00:00:00Z")
    validate_error(
        api.record_filter_change(plan["id"], DISPATCHER),
        ApiErrorId.ERR_FILTER_CHANGE_TOO_SOON.value,
        422,
    )

    fixtures.set_clock("2026-07-01T00:00:00Z")
    validate_success(api.record_filter_change(plan["id"], DISPATCHER))

    refreshed = fixtures.get_plan(plan["id"])
    assert_instant_equals(
        refreshed["last_filter_change_date"],
        "2026-07-01T00:00:00Z",
        "MaintenancePlan.last_filter_change_date",
    )
    assert refreshed["filter_media"] == "NONE"
    assert refreshed["filter_next_due_date"] is None
    assert_close(
        refreshed["salt_remaining_lbs"], 0.0, "MaintenancePlan.salt_remaining_lbs"
    )
    assert refreshed["last_salt_delivery_date"] is None


def test_the_shared_well_and_plan_uniqueness_gates_each_own_their_error(api):
    """PRD 3.1: "Two rules guard creation, in this order. First, no `ACTIVE` agreement may
    already link that well to that account; a repeat is refused with
    `ERR_DUPLICATE_SHARED_WELL_AGREEMENT`."
    PRD 3.10: "**At most one plan whose `status` is `ACTIVE` or `SUSPENDED` may exist per
    well**; a second is refused with `ERR_PLAN_ALREADY_EXISTS_FOR_WELL`."
    PRD 3.10: "A delivery that would push `salt_remaining_lbs` above
    `SALT_TANK_CAPACITY_LBS` (300 pounds) is refused with
    `ERR_SALT_DELIVERY_EXCEEDS_CAPACITY`, and landing exactly on 300.0 is allowed."

    Design: Corner/errors/corner_shared_well_and_plan_uniqueness_gates_rejected
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account_a = fixtures.new_account("Uniq A", "JUR_ALPHA", "ua@corner.example")
    account_b = fixtures.new_account("Uniq B", "JUR_ALPHA", "ub@corner.example")
    account_c = fixtures.new_account("Uniq C", "JUR_ALPHA", "uc@corner.example")
    prop = fixtures.new_property(account_a["id"], "9 Uniq", "JUR_ALPHA", 10.0, 5)
    well = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 200.0, 12.0)
    agreement_b = fixtures.new_shared_well_agreement(well["id"], account_b["id"], 60.00)
    plan = fixtures.new_maintenance_plan(well["id"], account_a["id"])
    technician = fixtures.new_technician("Uniq Tech", "JOURNEYMAN", "JUR_ALPHA")

    chem = fixtures.chemical_panel(
        well["id"],
        technician["id"],
        "2026-06-01T00:00:00Z",
        "2026-06-01T06:00:00Z",
        OFFICER_ALPHA,
        hardness_gpg=20.0,
        **CLEAN_ANALYTES,
    )
    recommendation = fixtures.create_recommendation(well["id"], chem["id"])
    fixtures.accept_recommendation(recommendation["id"], account_a["id"])
    fixtures.change_filter(plan["id"], fixtures.make_technician_headers(technician["id"]))
    plan_version = fixtures.plan_version(plan["id"])

    fixtures.set_clock("2026-06-30T09:00:00Z")

    validate_error(
        api.create_shared_well_agreement(
            {
                "well_profile_id": well["id"],
                "account_id": account_b["id"],
                "split_pct": 10.00,
            },
            BILLING,
        ),
        ApiErrorId.ERR_DUPLICATE_SHARED_WELL_AGREEMENT.value,
        409,
    )
    validate_error(
        api.create_shared_well_agreement(
            {
                "well_profile_id": well["id"],
                "account_id": account_c["id"],
                "split_pct": 50.00,
            },
            BILLING,
        ),
        ApiErrorId.ERR_SHARED_WELL_SPLIT_INVALID.value,
        422,
    )
    validate_error(
        api.create_maintenance_plan(
            {"well_profile_id": well["id"], "account_id": account_a["id"]}, ADMIN
        ),
        ApiErrorId.ERR_PLAN_ALREADY_EXISTS_FOR_WELL.value,
        409,
    )
    validate_error(
        api.record_salt_delivery(
            plan["id"],
            {
                "delivered_lbs": 301.0,
                "expected_maintenance_plan_version": plan_version,
            },
            DISPATCHER,
        ),
        ApiErrorId.ERR_SALT_DELIVERY_EXCEEDS_CAPACITY.value,
        422,
    )
    validate_error(
        api.record_filter_change(
            plan["id"], fixtures.make_technician_headers(technician["id"])
        ),
        ApiErrorId.ERR_FILTER_CHANGE_TOO_SOON.value,
        422,
    )

    refreshed = fixtures.get_plan(plan["id"])
    assert_close(
        refreshed["salt_remaining_lbs"], 0.0, "MaintenancePlan.salt_remaining_lbs"
    )
    assert_instant_equals(
        refreshed["last_filter_change_date"],
        "2026-06-01T09:00:00Z",
        "MaintenancePlan.last_filter_change_date",
    )
    assert_close(
        fixtures.get_agreement(agreement_b["id"])["split_pct"],
        60.00,
        "SharedWellAgreement.split_pct",
    )


def test_a_salt_delivery_rejects_a_replayed_plan_version(api):
    """PRD 2.8: "Recording a salt delivery against a maintenance plan requires
    `expected_maintenance_plan_version` carrying the client's last observed `version` of
    that `MaintenancePlan`. A mismatch is rejected with
    `ERR_STALE_MAINTENANCE_PLAN_VERSION` (HTTP 412). Deliveries are legitimately repeatable
    and top up the same brine tank, so the check exists to stop a driver topping up against
    a remaining-pounds figure it never observed."
    PRD 3.10: "On success the delivered pounds are added to `salt_remaining_lbs`,
    `last_salt_delivery_date` is stamped from the logical clock, `salt_next_due_date` is
    recomputed, and the plan's `version` rises by 1."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_salt_delivery_rejects_a_replayed_plan_version
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    account = fixtures.new_account("Plan OCC Co", "JUR_ALPHA", "po@corner.example")
    prop = fixtures.new_property(account["id"], "412 Plan", "JUR_ALPHA", 10.0, 3)
    well = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 200.0)
    plan = fixtures.new_maintenance_plan(well["id"], account["id"])
    original = plan["version"]
    assert original == 1

    validate_error(
        api.record_salt_delivery(
            plan["id"],
            {
                "delivered_lbs": 100.0,
                "expected_maintenance_plan_version": original - 1,
            },
            DISPATCHER,
        ),
        ApiErrorId.ERR_STALE_MAINTENANCE_PLAN_VERSION.value,
        412,
    )
    validate_success(
        api.record_salt_delivery(
            plan["id"],
            {"delivered_lbs": 100.0, "expected_maintenance_plan_version": original},
            DISPATCHER,
        )
    )
    validate_error(
        api.record_salt_delivery(
            plan["id"],
            {"delivered_lbs": 100.0, "expected_maintenance_plan_version": original},
            DISPATCHER,
        ),
        ApiErrorId.ERR_STALE_MAINTENANCE_PLAN_VERSION.value,
        412,
    )

    refreshed = fixtures.get_plan(plan["id"])
    assert_close(
        refreshed["salt_remaining_lbs"], 100.0, "MaintenancePlan.salt_remaining_lbs"
    )
    assert_instant_equals(
        refreshed["last_salt_delivery_date"],
        "2026-06-01T00:00:00Z",
        "MaintenancePlan.last_salt_delivery_date",
    )
    assert refreshed["salt_next_due_date"] is None
    assert refreshed["version"] == 2
