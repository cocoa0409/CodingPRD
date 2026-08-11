"""Composite setup helpers.

Every helper builds its own state from scratch through declared endpoints; the
harness restarts the server before each test, so nothing here may assume a row
survives from an earlier test.

The canonical production walk these helpers share is:

    clock 2026-05-01 (the default)  ->  recipe / culture / vessel / CIP / pitch
    clock 2026-05-07                ->  three clean F1 readings, advance to F2
    clock 2026-05-09                ->  one F2 reading, close secondary
    clock 2026-05-10                ->  draw, PACKAGING reading, start, complete
    clock 2026-05-12                ->  release (48 h after packaging)

The three clean F1 readings land on day indices 2, 4 and 5 with pH 3.80, 3.55
and 3.40, so the day-5 reading is the one that reaches the effective ceiling
and carries the quality axis to CONFORMING.
"""

from prd_bench_local_runner.testing import get_success_data

from .factories import (
    create_account_payload,
    create_batch_payload,
    create_ingredient_lot_payload,
    create_ingredient_use_payload,
    create_keg_fill_payload,
    create_keg_payload,
    create_label_approval_payload,
    create_packaging_run_payload,
    create_qa_reading_payload,
    create_recipe_payload,
    create_scoby_culture_payload,
    create_shipment_line_payload,
    create_shipment_payload,
    create_source_draw_payload,
    create_subscription_payload,
    create_taproom_fill_payload,
    create_vessel_payload,
    set_clock_payload,
)
from .test_users import (
    COMPLIANCE_APPROVER_USER_ID,
    COMPLIANCE_SUBMITTER_USER_ID,
    OPERATOR_USER_ID,
    QA_USER_ID,
    TEST_USERS,
    make_compliance_officer_headers,
    make_production_operator_headers,
    make_qa_manager_headers,
)

OPERATOR = TEST_USERS["production_operator_headers"]
QA = TEST_USERS["qa_manager_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
COMPLIANCE_APPROVER = TEST_USERS["compliance_officer_approver_headers"]
SALES = TEST_USERS["sales_rep_headers"]
TAPROOM = TEST_USERS["taproom_staff_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]

DEFAULT_CLOCK = "2026-05-01T00:00:00.000Z"

# The shared production timeline
CLOCK_AFTER_F1 = "2026-05-07T00:00:00.000Z"
CLOCK_AFTER_F2 = "2026-05-09T00:00:00.000Z"
CLOCK_AT_PACKAGING = "2026-05-10T00:00:00.000Z"
CLOCK_AT_RELEASE = "2026-05-12T00:00:00.000Z"

F1_READING_DATES = (
    "2026-05-03T00:00:00.000Z",
    "2026-05-05T00:00:00.000Z",
    "2026-05-06T00:00:00.000Z",
)
F1_READING_PHS = (3.80, 3.55, 3.40)
F2_READING_DATE = "2026-05-08T00:00:00.000Z"


# --------------------------------------------------------------------------
# Primitive helpers
# --------------------------------------------------------------------------
def set_clock(api, to_iso8601: str, headers=None) -> dict:
    return get_success_data(api.set_clock(set_clock_payload(to_iso8601), headers or ADMIN))


def new_recipe(api, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_recipe(create_recipe_payload(**overrides), headers or OPERATOR)
    )


def new_culture(api, label="Mother", parent_culture_id=None, headers=None) -> dict:
    payload = create_scoby_culture_payload(label)
    if parent_culture_id is not None:
        payload["parent_culture_id"] = parent_culture_id
    return get_success_data(api.create_scoby_culture(payload, headers or OPERATOR))


def new_lineage(api, depth: int, prefix: str = "G") -> list:
    """Return a list of `depth` cultures, each the daughter of the one before it."""
    cultures = []
    parent_id = None
    for index in range(1, depth + 1):
        culture = new_culture(api, f"{prefix}{index}", parent_culture_id=parent_id)
        cultures.append(culture)
        parent_id = culture["id"]
    return cultures


def new_vessel(api, code="FV-1", capacity_liters=500.0, headers=None) -> dict:
    return get_success_data(
        api.create_vessel(
            create_vessel_payload(code=code, capacity_liters=capacity_liters),
            headers or OPERATOR,
        )
    )


def new_sanitized_vessel(api, code="FV-1", capacity_liters=500.0, headers=None) -> dict:
    """Register a vessel and walk it DIRTY -> CIP_IN_PROGRESS -> SANITIZED."""
    actor = headers or OPERATOR
    vessel = new_vessel(api, code=code, capacity_liters=capacity_liters, headers=actor)
    get_success_data(api.cip_start_vessel(vessel["id"], actor))
    return get_success_data(api.cip_complete_vessel(vessel["id"], actor))


def new_ingredient_lot(api, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_ingredient_lot(create_ingredient_lot_payload(**overrides), headers or OPERATOR)
    )


def record_ingredient_use(api, batch_id, ingredient_lot_id, quantity_used, headers=None) -> dict:
    return get_success_data(
        api.create_ingredient_use(
            batch_id,
            create_ingredient_use_payload(ingredient_lot_id, quantity_used),
            headers or OPERATOR,
        )
    )


def approve_label(
    api,
    recipe_id,
    abv_class="NON_ALCOHOLIC",
    pasteurized=False,
    declared_elements=None,
    submitter_user_id=COMPLIANCE_SUBMITTER_USER_ID,
    approver_user_id=COMPLIANCE_APPROVER_USER_ID,
) -> dict:
    """Open a revision, submit it, and approve it with a different person."""
    submitter = make_compliance_officer_headers(submitter_user_id)
    approver = make_compliance_officer_headers(approver_user_id)
    payload = create_label_approval_payload(
        recipe_id, abv_class=abv_class, pasteurized=pasteurized
    )
    if declared_elements is not None:
        payload["declared_elements"] = list(declared_elements)
    label = get_success_data(api.create_label_approval(payload, submitter))
    get_success_data(api.submit_label_approval(label["id"], submitter))
    return get_success_data(api.approve_label_approval(label["id"], approver))


def draft_label(
    api,
    recipe_id,
    abv_class="NON_ALCOHOLIC",
    pasteurized=False,
    declared_elements=None,
    submitter_user_id=COMPLIANCE_SUBMITTER_USER_ID,
) -> dict:
    submitter = make_compliance_officer_headers(submitter_user_id)
    payload = create_label_approval_payload(
        recipe_id, abv_class=abv_class, pasteurized=pasteurized
    )
    if declared_elements is not None:
        payload["declared_elements"] = list(declared_elements)
    return get_success_data(api.create_label_approval(payload, submitter))


def pitch_batch(api, recipe_id, culture_id, vessel_id, headers=None, **overrides) -> dict:
    payload = create_batch_payload(recipe_id, culture_id, vessel_id, **overrides)
    return get_success_data(api.create_batch(payload, headers or OPERATOR))


def record_reading(api, batch_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_qa_reading(batch_id, create_qa_reading_payload(**overrides), headers or OPERATOR)
    )


def read_batch(api, batch_id, headers=None) -> dict:
    return get_success_data(api.get_batch(batch_id, headers or OPERATOR))


def read_lot(api, lot_id, headers=None) -> dict:
    return get_success_data(api.get_finished_lot(lot_id, headers or QA))


def read_run(api, run_id, headers=None) -> dict:
    return get_success_data(api.get_packaging_run(run_id, headers or OPERATOR))


def read_vessel(api, vessel_id, headers=None) -> dict:
    return get_success_data(api.get_vessel(vessel_id, headers or OPERATOR))


def read_culture(api, culture_id, headers=None) -> dict:
    return get_success_data(api.get_scoby_culture(culture_id, headers or OPERATOR))


def read_recipe(api, recipe_id, headers=None) -> dict:
    return get_success_data(api.get_recipe(recipe_id, headers or OPERATOR))


def read_account(api, account_id, headers=None) -> dict:
    return get_success_data(api.get_account(account_id, headers or SALES))


def read_shipment(api, shipment_id, headers=None) -> dict:
    return get_success_data(api.get_shipment(shipment_id, headers or SALES))


def read_subscription(api, subscription_id, headers=None) -> dict:
    return get_success_data(api.get_subscription(subscription_id, headers or ADMIN))


def read_keg(api, keg_id, headers=None) -> dict:
    return get_success_data(api.get_keg(keg_id, headers or OPERATOR))


def batch_version(api, batch_id, headers=None) -> int:
    return read_batch(api, batch_id, headers)["version"]


def lot_version(api, lot_id, headers=None) -> int:
    return read_lot(api, lot_id, headers)["version"]


# --------------------------------------------------------------------------
# Tier 1 / 2 — walk a batch to READY_TO_PACKAGE
# --------------------------------------------------------------------------
def build_ready_batch(
    api,
    *,
    recipe=None,
    recipe_overrides=None,
    culture=None,
    vessel=None,
    vessel_code="FV-1",
    vessel_capacity=500.0,
    culture_label="Mother",
    batch_code="B-1001",
    pitched_liters=400.0,
    planned_f2_days=3,
    f2_added_sugar_g_per_l=4,
    f1_abvs=(0.10, 0.14, 0.18),
    f2_abv=0.30,
) -> dict:
    """Create recipe / culture / vessel and walk one batch to READY_TO_PACKAGE.

    Leaves the logical clock at 2026-05-09 and the batch CONFORMING with
    ph_target_hit_day_index 5 and f2_completed_at 2026-05-09.
    """
    overrides = dict(recipe_overrides or {})
    overrides.setdefault("f2_added_sugar_g_per_l", f2_added_sugar_g_per_l)
    overrides.setdefault("pasteurization_required", False)
    recipe = recipe or new_recipe(api, **overrides)
    culture = culture or new_culture(api, culture_label)
    vessel = vessel or new_sanitized_vessel(api, code=vessel_code, capacity_liters=vessel_capacity)

    batch = pitch_batch(
        api,
        recipe["id"],
        culture["id"],
        vessel["id"],
        batch_code=batch_code,
        pitched_liters=pitched_liters,
        planned_f2_days=planned_f2_days,
        f2_added_sugar_g_per_l=f2_added_sugar_g_per_l,
    )
    batch = walk_pitched_batch_to_ready(api, batch["id"], f1_abvs=f1_abvs, f2_abv=f2_abv)

    return {"recipe": recipe, "culture": culture, "vessel": vessel, "batch": batch}


def walk_pitched_batch_to_ready(api, batch_id, *, f1_abvs=(0.10, 0.14, 0.18), f2_abv=0.30) -> dict:
    """Carry an F1_ACTIVE batch through the clean QA log to READY_TO_PACKAGE."""
    set_clock(api, CLOCK_AFTER_F1)
    for reading_at, ph, abv in zip(F1_READING_DATES, F1_READING_PHS, f1_abvs):
        record_reading(
            api,
            batch_id,
            reading_type="F1",
            reading_at=reading_at,
            ph=ph,
            temperature_c=24.0,
            brix=5.0,
            abv_pct=abv,
        )
    get_success_data(api.advance_batch_to_f2(batch_id, OPERATOR))

    set_clock(api, CLOCK_AFTER_F2)
    record_reading(
        api,
        batch_id,
        reading_type="F2",
        reading_at=F2_READING_DATE,
        ph=3.30,
        temperature_c=22.0,
        brix=3.5,
        abv_pct=f2_abv,
    )
    return get_success_data(api.complete_batch_f2(batch_id, OPERATOR))


# --------------------------------------------------------------------------
# Tier 3 — packaging runs and finished lots
# --------------------------------------------------------------------------
def open_run(
    api,
    recipe_id,
    label_approval_id,
    run_code="PR-1",
    fmt="BOTTLE",
    pasteurized=False,
    max_units_requested=300,
    creator_user_id=OPERATOR_USER_ID,
) -> dict:
    return get_success_data(
        api.create_packaging_run(
            create_packaging_run_payload(
                recipe_id,
                label_approval_id,
                run_code=run_code,
                format=fmt,
                pasteurized=pasteurized,
                max_units_requested=max_units_requested,
            ),
            make_production_operator_headers(creator_user_id),
        )
    )


def draw_source(api, run_id, batch_id, liters_drawn, headers=None) -> dict:
    """Re-read the batch version, then append one draw with a fresh token."""
    version = batch_version(api, batch_id)
    return get_success_data(
        api.add_packaging_run_source(
            run_id,
            create_source_draw_payload(batch_id, liters_drawn, version),
            headers or OPERATOR,
        )
    )


def build_at_risk_batch(api, *, excursion_user_id=OPERATOR_USER_ID) -> dict:
    """A batch carried to CONFORMING at day 5, then pulled to AT_RISK by a 32.0 C
    excursion reading, then given one further clean reading.

    Leaves ferment_stage F1_ACTIVE, qa_disposition AT_RISK,
    flagged_reading_count 1, temp_excursion_count 1 and the clock at 2026-05-09.
    """
    recorder = make_production_operator_headers(excursion_user_id)
    recipe = new_recipe(api, f2_added_sugar_g_per_l=4, pasteurization_required=False)
    culture = new_culture(api, "Mother E")
    vessel = new_sanitized_vessel(api, code="FV-5", capacity_liters=500.0)
    batch = pitch_batch(
        api, recipe["id"], culture["id"], vessel["id"], batch_code="B-5001",
        pitched_liters=400.0, planned_f2_days=3, f2_added_sugar_g_per_l=4,
    )

    set_clock(api, CLOCK_AFTER_F2)
    for reading_at, ph, abv in (
        ("2026-05-03T00:00:00.000Z", 3.80, 0.10),
        ("2026-05-05T00:00:00.000Z", 3.55, 0.14),
        ("2026-05-06T00:00:00.000Z", 3.40, 0.18),
    ):
        record_reading(
            api, batch["id"], headers=recorder, reading_type="F1", reading_at=reading_at,
            ph=ph, temperature_c=24.0, brix=5.0, abv_pct=abv,
        )
    record_reading(
        api, batch["id"], headers=recorder, reading_type="F1",
        reading_at="2026-05-08T00:00:00.000Z", ph=3.36, temperature_c=32.0,
        brix=4.0, abv_pct=0.20,
    )
    record_reading(
        api, batch["id"], headers=recorder, reading_type="F1",
        reading_at="2026-05-09T00:00:00.000Z", ph=3.30, temperature_c=24.0,
        brix=3.8, abv_pct=0.22,
    )
    return {
        "recipe": recipe,
        "culture": culture,
        "vessel": vessel,
        "batch": read_batch(api, batch["id"]),
    }


def build_draft_run(
    api,
    *,
    intended_abv_class="NON_ALCOHOLIC",
    label_abv_class=None,
    pasteurized=False,
    fmt="BOTTLE",
    max_units_requested=300,
    run_code="PR-EMPTY",
    run_creator_user_id=OPERATOR_USER_ID,
) -> dict:
    """A recipe with one APPROVED label and one run still in DRAFT, never sourced."""
    recipe = new_recipe(api, intended_abv_class=intended_abv_class)
    label = approve_label(
        api,
        recipe["id"],
        abv_class=label_abv_class or intended_abv_class,
        pasteurized=pasteurized,
    )
    run = open_run(
        api,
        recipe["id"],
        label["id"],
        run_code=run_code,
        fmt=fmt,
        pasteurized=pasteurized,
        max_units_requested=max_units_requested,
        creator_user_id=run_creator_user_id,
    )
    return {"recipe": recipe, "label": label, "run": run}


def build_sourced_run(
    api,
    *,
    liters_drawn=120.0,
    run_code="PR-SOURCED",
    fmt="BOTTLE",
    pasteurized=False,
    max_units_requested=300,
    intended_abv_class="NON_ALCOHOLIC",
    label_abv_class=None,
    f1_abvs=(0.10, 0.14, 0.18),
    pitched_liters=400.0,
    vessel_code="FV-8",
    batch_code="B-8001",
    run_creator_user_id=OPERATOR_USER_ID,
    ready=None,
    label=None,
) -> dict:
    """One CONFORMING READY_TO_PACKAGE batch feeding one run in status SOURCED."""
    ready = ready or build_ready_batch(
        api,
        recipe_overrides={"intended_abv_class": intended_abv_class},
        vessel_code=vessel_code,
        batch_code=batch_code,
        pitched_liters=pitched_liters,
        f1_abvs=f1_abvs,
    )
    label = label or approve_label(
        api,
        ready["recipe"]["id"],
        abv_class=label_abv_class or intended_abv_class,
        pasteurized=pasteurized,
    )
    run = open_run(
        api,
        ready["recipe"]["id"],
        label["id"],
        run_code=run_code,
        fmt=fmt,
        pasteurized=pasteurized,
        max_units_requested=max_units_requested,
        creator_user_id=run_creator_user_id,
    )
    run = draw_source(api, run["id"], ready["batch"]["id"], liters_drawn)
    result = dict(ready)
    result.update({"label": label, "run": run})
    return result


def build_held_lot(
    api,
    *,
    intended_abv_class="NON_ALCOHOLIC",
    label_abv_class=None,
    style="KOMBUCHA",
    pasteurized=False,
    fmt="BOTTLE",
    max_units_requested=300,
    liters_drawn=100.0,
    packaging_abv=0.44,
    f1_abvs=(0.10, 0.14, 0.18),
    f2_abv=0.30,
    pitched_liters=400.0,
    vessel_capacity=500.0,
    vessel_code="FV-1",
    batch_code="B-1001",
    culture_label="Mother",
    run_code="PR-1",
    run_creator_user_id=OPERATOR_USER_ID,
    recipe=None,
    ready=None,
) -> dict:
    """Walk a batch to READY_TO_PACKAGE and emit one HELD FinishedLot.

    Leaves the logical clock at 2026-05-10, which is the lot's packaged_at.
    """
    ready = ready or build_ready_batch(
        api,
        recipe=recipe,
        recipe_overrides={"style": style, "intended_abv_class": intended_abv_class},
        vessel_code=vessel_code,
        vessel_capacity=vessel_capacity,
        culture_label=culture_label,
        batch_code=batch_code,
        pitched_liters=pitched_liters,
        f1_abvs=f1_abvs,
        f2_abv=f2_abv,
    )
    label = approve_label(
        api,
        ready["recipe"]["id"],
        abv_class=label_abv_class or intended_abv_class,
        pasteurized=pasteurized,
    )
    run = open_run(
        api,
        ready["recipe"]["id"],
        label["id"],
        run_code=run_code,
        fmt=fmt,
        pasteurized=pasteurized,
        max_units_requested=max_units_requested,
        creator_user_id=run_creator_user_id,
    )
    draw_source(api, run["id"], ready["batch"]["id"], liters_drawn)

    set_clock(api, CLOCK_AT_PACKAGING)
    record_reading(
        api,
        ready["batch"]["id"],
        reading_type="PACKAGING",
        reading_at=CLOCK_AT_PACKAGING,
        ph=3.25,
        temperature_c=20.0,
        brix=3.0,
        abv_pct=packaging_abv,
    )
    get_success_data(api.start_packaging_run(run["id"], OPERATOR))
    run = get_success_data(api.complete_packaging_run(run["id"], OPERATOR))
    lot = read_lot(api, run["finished_lot_id"])

    result = dict(ready)
    result.update({"label": label, "run": run, "lot": lot})
    return result


def build_released_lot(api, *, releaser_user_id=QA_USER_ID, **kwargs) -> dict:
    """As `build_held_lot`, then advance to 2026-05-12 and release the lot."""
    built = build_held_lot(api, **kwargs)
    set_clock(api, CLOCK_AT_RELEASE)
    lot = get_success_data(
        api.release_finished_lot(built["lot"]["id"], make_qa_manager_headers(releaser_user_id))
    )
    built["lot"] = lot
    return built


# --------------------------------------------------------------------------
# Tier 4 — commercial state
# --------------------------------------------------------------------------
def build_raw_and_pasteurized_lots(api) -> dict:
    """Two single-source lots drawn from one batch and packaged on the same day.

    Only one approved artwork per recipe survives at a time, so the raw run is
    completed before the pasteurized artwork is approved. Both runs draw 100.0 L
    from the same 400.0 L batch and complete at 2026-05-10.
    """
    ready = build_ready_batch(
        api, vessel_code="FV-2", batch_code="B-2001", culture_label="Mother B"
    )
    recipe_id = ready["recipe"]["id"]
    batch_id = ready["batch"]["id"]

    label_raw = approve_label(api, recipe_id, abv_class="NON_ALCOHOLIC", pasteurized=False)
    run_raw = open_run(
        api, recipe_id, label_raw["id"], run_code="PR-RAW", fmt="BOTTLE",
        pasteurized=False, max_units_requested=300,
    )
    draw_source(api, run_raw["id"], batch_id, 100.0)

    set_clock(api, CLOCK_AT_PACKAGING)
    record_reading(
        api, batch_id, reading_type="PACKAGING", reading_at=CLOCK_AT_PACKAGING,
        ph=3.25, temperature_c=20.0, brix=3.0, abv_pct=0.44,
    )
    get_success_data(api.start_packaging_run(run_raw["id"], OPERATOR))
    run_raw = get_success_data(api.complete_packaging_run(run_raw["id"], OPERATOR))

    label_past = approve_label(api, recipe_id, abv_class="NON_ALCOHOLIC", pasteurized=True)
    run_past = open_run(
        api, recipe_id, label_past["id"], run_code="PR-PAST", fmt="BOTTLE",
        pasteurized=True, max_units_requested=300,
    )
    draw_source(api, run_past["id"], batch_id, 100.0)
    get_success_data(api.start_packaging_run(run_past["id"], OPERATOR))
    run_past = get_success_data(api.complete_packaging_run(run_past["id"], OPERATOR))

    return {
        "recipe": ready["recipe"],
        "batch": read_batch(api, batch_id),
        "label_raw": label_raw,
        "label_pasteurized": label_past,
        "run_raw": run_raw,
        "run_pasteurized": run_past,
        "lot_raw": read_lot(api, run_raw["finished_lot_id"]),
        "lot_pasteurized": read_lot(api, run_past["finished_lot_id"]),
    }


def build_active_account(api, headers=None, **overrides) -> dict:
    actor = headers or SALES
    account = get_success_data(api.create_account(create_account_payload(**overrides), actor))
    return get_success_data(api.activate_account(account["id"], actor))


def open_shipment(api, account_id, headers=None) -> dict:
    return get_success_data(
        api.create_shipment(create_shipment_payload(account_id), headers or SALES)
    )


def add_line(api, shipment_id, lot_id, units, unit_price, headers=None) -> dict:
    """Re-read the lot version, then add one line with a fresh concurrency token."""
    version = lot_version(api, lot_id, headers or SALES)
    return get_success_data(
        api.add_shipment_line(
            shipment_id,
            create_shipment_line_payload(lot_id, units, unit_price, version),
            headers or SALES,
        )
    )


def build_delivered_shipment(api, account_id, lot_id, lines, headers=None) -> dict:
    """Open a shipment, add every (units, unit_price) line, confirm and deliver it."""
    actor = headers or SALES
    shipment = open_shipment(api, account_id, actor)
    created = [add_line(api, shipment["id"], lot_id, u, p, actor) for u, p in lines]
    get_success_data(api.confirm_shipment(shipment["id"], actor))
    shipment = get_success_data(api.deliver_shipment(shipment["id"], actor))
    return {"shipment": shipment, "lines": created}


def build_subscription(api, recipe_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_subscription(
            create_subscription_payload(recipe_id, **overrides), headers or ADMIN
        )
    )


def allocate_box(api, subscription_id, cycle_index, lot_id, headers=None) -> dict:
    """Re-read the lot version, then allocate one box explicitly against that lot."""
    actor = headers or ADMIN
    version = lot_version(api, lot_id, actor)
    payload = {
        "subscription_id": subscription_id,
        "cycle_index": cycle_index,
        "finished_lot_id": lot_id,
        "expected_finished_lot_version": version,
    }
    return get_success_data(api.create_subscription_allocation(payload, actor))


# --------------------------------------------------------------------------
# Tier 5 — keg assets and the taproom
# --------------------------------------------------------------------------
def build_filled_keg(api, lot_id, asset_code="KEG-001", capacity_liters=19.5, fill_liters=19.5) -> dict:
    keg = get_success_data(
        api.create_keg(create_keg_payload(asset_code, capacity_liters=capacity_liters), OPERATOR)
    )
    return get_success_data(
        api.fill_keg(keg["id"], create_keg_fill_payload(lot_id, fill_liters), OPERATOR)
    )


def build_tapped_keg(api, lot_id, **kwargs) -> dict:
    keg = build_filled_keg(api, lot_id, **kwargs)
    return get_success_data(api.tap_keg(keg["id"], TAPROOM))


def open_fill(api, keg_id, container_type="GLASS_POUR", requested_liters=0.5, **overrides) -> dict:
    payload = create_taproom_fill_payload(
        keg_id, container_type=container_type, requested_liters=requested_liters, **overrides
    )
    return get_success_data(api.create_taproom_fill(payload, TAPROOM))


# --------------------------------------------------------------------------
# Bespoke scenario: a two-source blend whose sources close secondary on
# different days, so the blended shelf clock starts at the earlier one.
# --------------------------------------------------------------------------
def build_ingredient_exposure_chain(api) -> dict:
    """The full traceable chain a raw-ingredient quarantine has to walk.

    One TEA lot is consumed by one batch, that batch is drawn into one completed
    BOTTLE run, its 258-unit lot is released, an ACTIVE wholesale account holds a
    CONFIRMED shipment with a 10-unit line on the lot, and an ACTIVE subscription
    holds an ALLOCATED 6-unit box on the same lot. Leaves the clock at 2026-05-12.
    """
    recipe = new_recipe(api, f2_added_sugar_g_per_l=4, pasteurization_required=False)
    ingredient_lot = new_ingredient_lot(
        api, ingredient_type="TEA", supplier_lot_code="TEA-77",
        expiry_date="2027-01-01T00:00:00.000Z", quantity_received=50.0,
    )
    culture = new_culture(api, "Mother G")
    vessel = new_sanitized_vessel(api, code="FV-7", capacity_liters=500.0)
    batch = pitch_batch(
        api, recipe["id"], culture["id"], vessel["id"], batch_code="B-7001",
        pitched_liters=400.0, planned_f2_days=3, f2_added_sugar_g_per_l=4,
    )
    use = record_ingredient_use(api, batch["id"], ingredient_lot["id"], 10.0)
    batch = walk_pitched_batch_to_ready(api, batch["id"])

    label = approve_label(api, recipe["id"], abv_class="NON_ALCOHOLIC", pasteurized=False)
    run = open_run(
        api, recipe["id"], label["id"], run_code="PR-7", fmt="BOTTLE",
        pasteurized=False, max_units_requested=300,
    )
    draw_source(api, run["id"], batch["id"], 100.0)

    set_clock(api, CLOCK_AT_PACKAGING)
    record_reading(
        api, batch["id"], reading_type="PACKAGING", reading_at=CLOCK_AT_PACKAGING,
        ph=3.25, temperature_c=20.0, brix=3.0, abv_pct=0.44,
    )
    get_success_data(api.start_packaging_run(run["id"], OPERATOR))
    run = get_success_data(api.complete_packaging_run(run["id"], OPERATOR))
    lot_id = run["finished_lot_id"]

    set_clock(api, CLOCK_AT_RELEASE)
    get_success_data(api.release_finished_lot(lot_id, QA))

    account = build_active_account(
        api, account_name="Harbor Foods", credit_limit=5000.0, credit_terms_days=30,
        alcoholic_license_on_file=False,
    )
    shipment = open_shipment(api, account["id"])
    line = add_line(api, shipment["id"], lot_id, 10, 5.00)
    shipment = get_success_data(api.confirm_shipment(shipment["id"], SALES))

    subscription = build_subscription(
        api, recipe["id"], subscriber_email="kai@example.com",
        subscriber_birth_date="1990-03-11T00:00:00.000Z",
    )
    allocation = allocate_box(api, subscription["id"], 1, lot_id)

    return {
        "recipe": recipe,
        "ingredient_lot": ingredient_lot,
        "ingredient_use": use,
        "culture": culture,
        "vessel": vessel,
        "batch": read_batch(api, batch["id"]),
        "label": label,
        "run": run,
        "lot": read_lot(api, lot_id),
        "account": account,
        "shipment": shipment,
        "line": line,
        "subscription": subscription,
        "allocation": allocation,
    }


def build_two_source_blend(api) -> dict:
    """Two batches on one recipe closing F2 on 2026-05-09 and 2026-05-11.

    Their PACKAGING readings carry 0.42 and 0.45, and a raw BOTTLE run draws
    60.0 L from the first and 40.0 L from the second. Leaves the run started
    and the clock at 2026-05-12.
    """
    recipe = new_recipe(api, f2_added_sugar_g_per_l=4, pasteurization_required=False)
    culture = new_culture(api, "Mother Blend")
    v1 = new_sanitized_vessel(api, code="FV-25", capacity_liters=500.0)
    v2 = new_sanitized_vessel(api, code="FV-26", capacity_liters=500.0)

    b1 = pitch_batch(
        api, recipe["id"], culture["id"], v1["id"],
        batch_code="B-25001", pitched_liters=400.0, planned_f2_days=3,
        f2_added_sugar_g_per_l=4,
    )
    b2 = pitch_batch(
        api, recipe["id"], culture["id"], v2["id"],
        batch_code="B-25002", pitched_liters=400.0, planned_f2_days=3,
        f2_added_sugar_g_per_l=4,
    )

    set_clock(api, CLOCK_AFTER_F1)
    for reading_at, ph in zip(F1_READING_DATES, (3.80, 3.55, 3.40)):
        record_reading(api, b1["id"], reading_type="F1", reading_at=reading_at, ph=ph,
                       temperature_c=24.0, brix=5.0,
                       abv_pct={"2026-05-03T00:00:00.000Z": 0.10,
                                "2026-05-05T00:00:00.000Z": 0.14,
                                "2026-05-06T00:00:00.000Z": 0.18}[reading_at])
    for reading_at, ph in zip(F1_READING_DATES, (3.82, 3.58, 3.42)):
        record_reading(api, b2["id"], reading_type="F1", reading_at=reading_at, ph=ph,
                       temperature_c=24.0, brix=5.0,
                       abv_pct={"2026-05-03T00:00:00.000Z": 0.10,
                                "2026-05-05T00:00:00.000Z": 0.14,
                                "2026-05-06T00:00:00.000Z": 0.18}[reading_at])
    get_success_data(api.advance_batch_to_f2(b1["id"], OPERATOR))
    get_success_data(api.advance_batch_to_f2(b2["id"], OPERATOR))

    set_clock(api, CLOCK_AFTER_F2)
    record_reading(api, b1["id"], reading_type="F2", reading_at=F2_READING_DATE, ph=3.30,
                   temperature_c=22.0, brix=3.5, abv_pct=0.30)
    record_reading(api, b2["id"], reading_type="F2", reading_at=F2_READING_DATE, ph=3.32,
                   temperature_c=22.0, brix=3.5, abv_pct=0.30)
    b1 = get_success_data(api.complete_batch_f2(b1["id"], OPERATOR))

    set_clock(api, "2026-05-11T00:00:00.000Z")
    record_reading(api, b1["id"], reading_type="PACKAGING",
                   reading_at=CLOCK_AT_PACKAGING, ph=3.25, temperature_c=20.0,
                   brix=3.0, abv_pct=0.42)
    record_reading(api, b2["id"], reading_type="F2", reading_at=CLOCK_AT_PACKAGING, ph=3.28,
                   temperature_c=22.0, brix=3.2, abv_pct=0.38)
    b2 = get_success_data(api.complete_batch_f2(b2["id"], OPERATOR))

    label = approve_label(api, recipe["id"], abv_class="NON_ALCOHOLIC", pasteurized=False)
    run = open_run(api, recipe["id"], label["id"], run_code="PR-BLEND", fmt="BOTTLE",
                   pasteurized=False, max_units_requested=300)
    draw_source(api, run["id"], b1["id"], 60.0)
    draw_source(api, run["id"], b2["id"], 40.0)

    set_clock(api, "2026-05-12T00:00:00.000Z")
    record_reading(api, b2["id"], reading_type="PACKAGING",
                   reading_at="2026-05-12T00:00:00.000Z", ph=3.24, temperature_c=20.0,
                   brix=3.0, abv_pct=0.45)
    run = get_success_data(api.start_packaging_run(run["id"], OPERATOR))

    return {
        "recipe": recipe,
        "culture": culture,
        "vessel_one": v1,
        "vessel_two": v2,
        "batch_one": b1,
        "batch_two": b2,
        "label": label,
        "run": run,
    }
