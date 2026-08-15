"""Fields, the maturity cycle, re-seeding rotation, field inventory listing,
archive soft-delete, and system-managed field properties (PRD §2.4, §3.2)."""
from test_helpers import (
    TEST_USERS,
    assert_instant_equals,
    assert_money_eq,
    create_batch,
    create_config,
    create_field,
    create_variety,
    factories,
    get_field,
    get_success_data,
    is_valid_uuid,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId

FARM = TEST_USERS["farm_manager_headers"]
SALES = TEST_USERS["sales_rep_headers"]
HARVEST = TEST_USERS["harvest_supervisor_headers"]

ZERO_UUID = "00000000-0000-0000-0000-000000000000"


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / field_maturity_cycle_via_reseed
# Field planted 2025-10-01 (age 304 at the default 2026-08-01 clock ->
# OVERAGED), plan target 240.00 lbs, completion loops the cycle to SEEDED.
# ---------------------------------------------------------------------------

def _overaged_field_with_started_plan(api):
    v = create_variety(api)
    f = create_field(
        api, v["id"],
        name="South 12",
        last_planted_at="2025-10-01T00:00:00Z",
        mow_count=5,
        health_score=75,
    )
    plan = get_success_data(api.create_reseed_plan(
        f["id"], factories.create_reseed_plan_payload(), FARM
    ))
    get_success_data(api.start_reseed_plan(plan["id"], FARM))
    return f, plan


def test_reseed_completion_completes_plan_with_target(api):
    """PRD §3.2: "A `FarmManager` opens a re-seed plan for a field with a `planned_date`; the plan starts in `PLANNING` and immediately computes `target_seed_lbs` as the field's `field_sqft` multiplied by the variety's `seed_lbs_per_1000_sqft`, divided by one thousand, rounded half-up to two decimal places."
    PRD §3.2: "Completion requires the payload's `actual_seed_lbs` to be at least `target_seed_lbs` — anything less fails with `ERR_SEED_SHORTFALL` — and stamps `completed_at`."

    Design: Difficulty/non_linear_state_machine/field_maturity_cycle_via_reseed
    """
    f, plan = _overaged_field_with_started_plan(api)
    assert_money_eq(plan["target_seed_lbs"], 240.00, "target_seed_lbs")  # 40000*6/1000

    completed = get_success_data(api.complete_reseed_plan(
        plan["id"], factories.complete_reseed_plan_payload(240.00), FARM
    ))
    assert completed["status"] == "COMPLETED"
    assert_money_eq(completed["target_seed_lbs"], 240.00, "target_seed_lbs")
    assert_money_eq(completed["actual_seed_lbs"], 240.00, "actual_seed_lbs")
    assert completed.get("completed_at"), "completed_at must be stamped"


def test_reseed_completion_resets_field_crop_cycle(api):
    """PRD §3.2: "Completion also resets the crop cycle: the field's maturity hops to `SEEDED`, `last_planted_at` becomes the current clock instant, `remaining_sqft` returns to `field_sqft`, and `mow_count` zeroes; the stubble goes with the old crop, so every `PENDING` batch of the field and every `COMPLETE` batch still unlinked to an order becomes `CANCELLED`."
    PRD §3.2: "Comparing `age_days` with the variety's windows yields `maturity_state`: `SEEDED` while age is at most `germination_max_days`, `GROWING` while at most `growing_max_days`, `READY` while at most `ready_max_days`, `MATURE` while at most `mature_max_days`, and `OVERAGED` beyond that."

    Design: Difficulty/non_linear_state_machine/field_maturity_cycle_via_reseed
    """
    f, plan = _overaged_field_with_started_plan(api)
    # Sanity: at the default clock (2026-08-01) the field is 304 days old.
    assert get_field(api, f["id"])["maturity_state"] == "OVERAGED"

    get_success_data(api.complete_reseed_plan(
        plan["id"], factories.complete_reseed_plan_payload(240.00), FARM
    ))
    after = get_field(api, f["id"])
    assert after["maturity_state"] == "SEEDED", "cycle loops OVERAGED -> SEEDED"
    assert_money_eq(after["remaining_sqft"], 40000, "remaining_sqft reset to field_sqft")
    assert after["mow_count"] == 0, "mow_count zeroes at cycle reset"


# ---------------------------------------------------------------------------
# Corner: state_machines / reseed_gates_and_seed_shortfall
# GROWING field -> ERR_RESEED_NOT_ALLOWED; MATURE field opens; 239.99 lbs ->
# ERR_SEED_SHORTFALL; 240.00 lbs completes.
# ---------------------------------------------------------------------------

def test_reseed_gates_and_seed_shortfall(api):
    """PRD §3.2: "Opening a plan is refused with `ERR_RESEED_NOT_ALLOWED` unless three conditions all hold: the field's maturity is `MATURE` or `OVERAGED`; no batch of the field is linked to an order in `PLACED`, `CONFIRMED`, `OUT_FOR_DELIVERY`, `DELIVERED`, `INSTALLING`, or `INSTALLED`; and the field has no other plan in `PLANNING` or `IN_PROGRESS`."
    PRD §3.2: "Completion requires the payload's `actual_seed_lbs` to be at least `target_seed_lbs` — anything less fails with `ERR_SEED_SHORTFALL` — and stamps `completed_at`."

    Design: Corner/state_machines/reseed_gates_and_seed_shortfall
    """
    v = create_variety(api)
    # Age 17 at the default clock -> GROWING.
    fg = create_field(api, v["id"], name="G-17",
                      last_planted_at="2026-07-15T00:00:00Z", mow_count=1)
    # Age 212 at the default clock -> MATURE.
    fm = create_field(api, v["id"], name="M-212",
                      last_planted_at="2026-01-01T00:00:00Z",
                      mow_count=6, health_score=75)

    resp = api.create_reseed_plan(
        fg["id"], factories.create_reseed_plan_payload(planned_date="2026-08-05"), FARM
    )
    validate_error(resp, ApiErrorId.ERR_RESEED_NOT_ALLOWED, 409)

    plan = get_success_data(api.create_reseed_plan(
        fm["id"], factories.create_reseed_plan_payload(planned_date="2026-08-05"), FARM
    ))
    assert_money_eq(plan["target_seed_lbs"], 240.00, "target_seed_lbs")
    get_success_data(api.start_reseed_plan(plan["id"], FARM))

    resp = api.complete_reseed_plan(
        plan["id"], factories.complete_reseed_plan_payload(239.99), FARM
    )
    validate_error(resp, ApiErrorId.ERR_SEED_SHORTFALL, 422)

    completed = get_success_data(api.complete_reseed_plan(
        plan["id"], factories.complete_reseed_plan_payload(240.00), FARM
    ))
    assert completed["status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# Corner: endpoints / maturity_lazy_recompute_on_read_no_version_bump
# Planted 2026-06-25: GROWING at age 37 (default clock), READY at age 61
# (clock 2026-08-25); lazy recompute never bumps version.
# ---------------------------------------------------------------------------

def test_maturity_lazy_recompute_on_read_no_version_bump(api):
    """PRD §3.2: "The state is recomputed lazily whenever the field is read or its maturity feeds a precondition, and a `FarmManager` can force the recomputed value to be persisted with a maturity scan; per §2.4, recomputation never increments the field's `version`."
    PRD §2.4: "One deliberate exception narrows the versioning convention: recomputing a field's maturity — whether lazily on read or through an explicit maturity scan — does not increment the field's `version`, even when the persisted `maturity_state` changes (§3.2)."
    PRD §3.2: "Band boundaries lean young — a field whose age equals `germination_max_days` is still `SEEDED`, and likewise for the later bands."

    Design: Corner/endpoints/maturity_lazy_recompute_on_read_no_version_bump
    """
    v = create_variety(api)
    f = create_field(api, v["id"], name="West 3", field_sqft=20000,
                     last_planted_at="2026-06-25T00:00:00Z",
                     mow_count=2, health_score=80)

    read1 = get_field(api, f["id"])
    assert read1["maturity_state"] == "GROWING", "age 37 must be GROWING"
    set_clock(api, "2026-08-25T00:00:00Z")
    read2 = get_field(api, f["id"])
    assert read2["maturity_state"] == "READY", "age 61 must be READY (boundary > 60)"
    assert read2["version"] == read1["version"], (
        "lazy maturity recompute must not increment version"
    )


# ---------------------------------------------------------------------------
# Corner: entities / field_inventory_filtered_listing
# ---------------------------------------------------------------------------

def test_field_inventory_filtered_listing(api):
    """PRD §3.2: "Archiving moves the field's status from `ACTIVE` to `ARCHIVED` — its terminal state — and archived fields disappear from the field inventory list unless the caller explicitly passes the `status` filter for `ARCHIVED`. The inventory list also accepts `variety_id` and `maturity_state` filters, which compose."
    PRD §2.3: "Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order."

    Design: Corner/entities/field_inventory_filtered_listing
    """
    v1 = create_variety(api, name="Tifway 419 Bermuda")
    v2 = create_variety(api, name="Celebration Bermuda")
    f1 = create_field(api, v1["id"], name="F1")  # age 92 -> READY
    f2 = create_field(api, v2["id"], name="F2", field_sqft=20000,
                      last_planted_at="2026-07-15T00:00:00Z", mow_count=1)  # age 17 -> GROWING

    all_rows, _ = validate_paginated(api.list_fields(FARM))
    assert [r["id"] for r in all_rows] == [f1["id"], f2["id"]], (
        "unfiltered inventory lists every non-archived field, created_at ascending"
    )

    ready_rows, ready_meta = validate_paginated(
        api.list_fields(SALES, params={"maturity_state": "READY"})
    )
    assert [r["id"] for r in ready_rows] == [f1["id"]]
    assert ready_meta["total_count"] == 1

    v2_rows, v2_meta = validate_paginated(
        api.list_fields(HARVEST, params={"variety_id": v2["id"]})
    )
    assert [r["id"] for r in v2_rows] == [f2["id"]]
    assert v2_meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Corner: cross_cutting / archived_field_hidden_then_filterable
# ---------------------------------------------------------------------------

def test_archived_field_hidden_then_filterable(api):
    """PRD §3.2: "Archiving moves the field's status from `ACTIVE` to `ARCHIVED` — its terminal state — and archived fields disappear from the field inventory list unless the caller explicitly passes the `status` filter for `ARCHIVED`."
    PRD §2.9: "6. **Terminal guard** — the target entity is not in a terminal state for this action; otherwise `ERR_ALREADY_TERMINAL`."

    Design: Corner/cross_cutting/archived_field_hidden_then_filterable
    """
    v = create_variety(api)
    f = create_field(api, v["id"], name="Old 5", field_sqft=20000)

    archived = get_success_data(api.archive_field(f["id"], FARM))
    assert archived["status"] == "ARCHIVED"

    default_rows, default_meta = validate_paginated(api.list_fields(FARM))
    assert default_rows == [] and default_meta["total_count"] == 0, (
        "archived fields disappear from the default inventory list"
    )
    archived_rows, archived_meta = validate_paginated(
        api.list_fields(FARM, params={"status": "ARCHIVED"})
    )
    assert [r["id"] for r in archived_rows] == [f["id"]]
    assert archived_meta["total_count"] == 1

    # Batch create on the terminal field is rejected at the terminal guard,
    # which precedes the field-version (OCC) guard in the PRD §2.9 order.
    resp = api.create_harvest_batch(
        factories.create_harvest_batch_payload(
            f["id"], f["version"], pallet_count=2, scheduled_date="2026-08-02"
        ),
        HARVEST,
    )
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL, 409)


# ---------------------------------------------------------------------------
# Corner: entities / field_create_client_supplied_system_fields_input_ignored
# ---------------------------------------------------------------------------

def test_field_create_ignores_client_supplied_system_fields(api):
    """PRD §2.4: "- `id` (string): a server-minted UUID, with no type prefix."
    PRD §2.4: "- `version` (integer): a system-managed counter that increments with every modification — state transitions, derived-field writes, and cascading updates that touch the entity all count as modifications."
    PRD §3.2: "A new field starts `ACTIVE` with `remaining_sqft` initialized to `field_sqft`."

    Design: Corner/entities/field_create_client_supplied_system_fields_input_ignored
    """
    v = create_variety(api)
    payload = factories.create_field_payload(name="North 40")
    payload["variety_id"] = v["id"]
    payload["id"] = ZERO_UUID  # client-supplied system fields must be ignored
    payload["version"] = 99
    resp = api.create_field(payload, FARM)
    f = validate_success(resp, 201)
    assert f["id"] != ZERO_UUID and is_valid_uuid(f["id"]), (
        "the server mints the id; a client-supplied id is ignored"
    )
    assert isinstance(f["version"], int) and f["version"] != 99, (
        "version is system-managed; a client-supplied counter is ignored"
    )
    assert f["status"] == "ACTIVE"
    assert_money_eq(f["remaining_sqft"], 40000, "remaining_sqft initialized to field_sqft")
