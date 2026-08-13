"""Composite setup helpers.

The interesting claims in this PRD require deep system state: a cheese batch
exists only after clock -> plant -> vat -> intake -> accept -> two additive
lots -> two lot releases -> make sheet -> start -> N alternating step
sign-offs -> complete. These helpers collapse those chains so tests stay thin.
All setup calls use get_success_data() so a setup failure surfaces as a clear
"Setup failed" pytest error rather than a confusing assertion failure.
"""
import pytest

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import MAKE_STEPS_REQUIRED
from .factories import (
    DEFAULTS,
    complete_make_payload,
    create_additive_lot_payload,
    create_aging_room_payload,
    create_aging_unit_payload,
    create_allocation_order_payload,
    create_cut_wrap_run_payload,
    create_export_certificate_payload,
    create_grading_event_payload,
    create_make_sheet_payload,
    create_milk_intake_payload,
    create_plant_payload,
    create_vat_payload,
)
from .test_users import CM_ALICE, CM_BOB, QA_CAROL, TEST_USERS, make_cheesemaker_headers, make_qa_grader_headers

ADMIN = TEST_USERS["plant_admin_headers"]
RECEIVER = TEST_USERS["milk_receiver_headers"]
PLANNER = TEST_USERS["make_planner_headers"]
QA = TEST_USERS["qa_grader_headers"]
CELLAR = TEST_USERS["aging_room_operator_headers"]
SALES = TEST_USERS["sales_planner_headers"]
CUTTER = TEST_USERS["cut_wrap_operator_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]

# Wheel weight used at the cut-and-wrap room, per variety (PRD section 3.8).
_WHEEL_WEIGHT = {"CHEDDAR": 18.0, "COLBY": 12.0, "BRICK": 2.5, "MUENSTER": 3.0}


def _setup_ok(response, label):
    if response.status_code >= 400:
        pytest.fail(
            f"Setup failed at {label}: HTTP {response.status_code} body={response.text}"
        )
    return get_success_data(response)


def set_clock(to_iso8601):
    return _setup_ok(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN), "set_clock")


def create_plant(export_listed=None, **overrides):
    payload = create_plant_payload(**overrides)
    if export_listed is not None:
        payload["export_listed"] = export_listed
    return _setup_ok(api_client.create_plant(payload, ADMIN), "create_plant")


def create_vat(plant_id, **overrides):
    return _setup_ok(
        api_client.create_vat(plant_id, create_vat_payload(**overrides), ADMIN), "create_vat"
    )


def create_intake(plant_id, accept=True, **overrides):
    intake = _setup_ok(
        api_client.create_milk_intake(plant_id, create_milk_intake_payload(**overrides), RECEIVER),
        "create_milk_intake",
    )
    if accept:
        intake = _setup_ok(api_client.accept_milk_intake(intake["id"], RECEIVER), "accept_milk")
    return intake


def create_released_additive_pair(plant_id, culture_qty=None, coagulant_qty=None):
    """Create a CULTURE lot and a COAGULANT lot, release both. Returns (culture, coagulant)."""
    culture = _setup_ok(
        api_client.create_additive_lot(
            plant_id,
            create_additive_lot_payload(
                kind="CULTURE",
                supplier_lot_no=DEFAULTS["CULTURE_LOT_NO"],
                quantity_initial=culture_qty if culture_qty is not None else DEFAULTS["CULTURE_QTY"],
            ),
            ADMIN,
        ),
        "create_culture_lot",
    )
    coagulant = _setup_ok(
        api_client.create_additive_lot(
            plant_id,
            create_additive_lot_payload(
                kind="COAGULANT",
                supplier_lot_no=DEFAULTS["COAGULANT_LOT_NO"],
                quantity_initial=coagulant_qty if coagulant_qty is not None else DEFAULTS["COAGULANT_QTY"],
            ),
            ADMIN,
        ),
        "create_coagulant_lot",
    )
    culture = _setup_ok(api_client.release_additive_lot(culture["id"], QA), "release_culture")
    coagulant = _setup_ok(api_client.release_additive_lot(coagulant["id"], QA), "release_coagulant")
    return culture, coagulant


def get_vat(vat_id, headers=None):
    return _setup_ok(api_client.get_vat(vat_id, headers or PLANNER), "get_vat")


def get_room(room_id, headers=None):
    return _setup_ok(api_client.get_aging_room(room_id, headers or CELLAR), "get_aging_room")


def create_make_sheet(vat_id, vat_version, milk_intake_id, culture_lot_id, coagulant_lot_id,
                      **overrides):
    """Book a make sheet (OCC on the vat). Returns the SCHEDULED make sheet."""
    payload = create_make_sheet_payload(
        vat_id=vat_id,
        milk_intake_id=milk_intake_id,
        culture_lot_id=culture_lot_id,
        coagulant_lot_id=coagulant_lot_id,
        expected_vat_version=vat_version,
        **overrides,
    )
    return _setup_ok(api_client.create_make_sheet(payload, PLANNER), "create_make_sheet")


def start_make(make_id, cheesemaker_id=CM_ALICE):
    return _setup_ok(
        api_client.start_make_sheet(make_id, make_cheesemaker_headers(cheesemaker_id)),
        "start_make",
    )


def sign_steps_through_curd_ready(make_id, variety, first_signer=CM_ALICE, second_signer=CM_BOB):
    """Sign every make-procedure step, alternating two cheesemakers (the same
    cheesemaker may not sign two consecutive steps). Ends in CURD_READY."""
    makers = [first_signer, second_signer]
    for step_no in range(1, MAKE_STEPS_REQUIRED[variety] + 1):
        signer = makers[(step_no - 1) % 2]
        _setup_ok(
            api_client.sign_off_step(make_id, step_no, make_cheesemaker_headers(signer)),
            f"sign_off_step_{step_no}",
        )


def complete_make(make_id, green_weight_kg=500.0, wheels_produced=4, completer=CM_ALICE):
    return _setup_ok(
        api_client.complete_make_sheet(
            make_id,
            complete_make_payload(
                green_weight_kg=green_weight_kg, wheels_produced=wheels_produced
            ),
            make_cheesemaker_headers(completer),
        ),
        "complete_make",
    )


def batch_id_for_make(make_id):
    data = _setup_ok(
        api_client.list_cheese_batches(PLANNER, params={"make_sheet_id": make_id}),
        "list_cheese_batches",
    )
    assert isinstance(data, list) and len(data) == 1, (
        f"Setup failed: expected exactly one cheese batch for make {make_id}, got {data!r}"
    )
    return data[0]["id"]


def get_cheese_batch(batch_id, headers=None):
    return _setup_ok(api_client.get_cheese_batch(batch_id, headers or QA), "get_cheese_batch")


def whey_stream_for_make(make_id):
    # PRD section 4 authorizes GET /plant/whey-streams for PlantAdmin,
    # Cheesemaker, and QAGrader only — MakePlanner is rejected with 403.
    data = _setup_ok(
        api_client.list_whey_streams(QA, params={"make_sheet_id": make_id}),
        "list_whey_streams",
    )
    assert isinstance(data, list) and len(data) == 1, (
        f"Setup failed: expected exactly one whey stream for make {make_id}, got {data!r}"
    )
    return data[0]


def create_aging_room(plant_id, **overrides):
    return _setup_ok(
        api_client.create_aging_room(plant_id, create_aging_room_payload(**overrides), ADMIN),
        "create_aging_room",
    )


def place_wheels(batch_id, room, wheel_count):
    """Create an aging unit with a fresh OCC read of the room version."""
    fresh = get_room(room["id"])
    return _setup_ok(
        api_client.create_aging_unit(
            create_aging_unit_payload(
                cheese_batch_id=batch_id,
                aging_room_id=room["id"],
                wheel_count=wheel_count,
                expected_aging_room_version=fresh["version"],
            ),
            CELLAR,
        ),
        "create_aging_unit",
    )


def grade_batch(batch_id, grader_id=QA_CAROL, **reading_overrides):
    return _setup_ok(
        api_client.create_grading_event(
            create_grading_event_payload(cheese_batch_id=batch_id, **reading_overrides),
            make_qa_grader_headers(grader_id),
        ),
        "create_grading_event",
    )


def release_batch(batch_id):
    return _setup_ok(api_client.release_cheese_batch(batch_id, QA), "release_batch")


def create_allocation_order(batch_id, **overrides):
    return _setup_ok(
        api_client.create_allocation_order(
            create_allocation_order_payload(cheese_batch_id=batch_id, **overrides), SALES
        ),
        "create_allocation_order",
    )


def create_cut_wrap_run(order_id, **overrides):
    return _setup_ok(
        api_client.create_cut_wrap_run(
            create_cut_wrap_run_payload(allocation_order_id=order_id, **overrides), CUTTER
        ),
        "create_cut_wrap_run",
    )


def reconcile_run(run_id):
    return _setup_ok(api_client.reconcile_cut_wrap_run(run_id, CUTTER), "reconcile_cut_wrap_run")


def create_export_certificate(run_id, **overrides):
    return _setup_ok(
        api_client.create_export_certificate(
            create_export_certificate_payload(cut_wrap_run_id=run_id, **overrides), COMPLIANCE
        ),
        "create_export_certificate",
    )


def make_completed_batch(
    variety="MUENSTER",
    volume_liters=5000.0,
    liters_committed=5000.0,
    green_weight_kg=500.0,
    wheels_produced=4,
    culture_qty=None,
    coagulant_qty=None,
    culture_units_planned=None,
    coagulant_ml_planned=None,
    export_listed=None,
    fat_pct=None,
    protein_pct=None,
    plant_name=None,
    set_initial_clock=True,
    complete=True,
    steps_to_sign=None,
):
    """Full base chain through make completion.

    Steps: (optional) initial clock set -> plant -> vat -> intake -> accept ->
    culture + coagulant lots -> release both -> make sheet -> start -> all
    variety steps signed off by two alternating cheesemakers -> complete.

    Returns a dict with the plant, vat, intake, lots, make sheet, and (when
    complete=True) the batch id and whey stream.
    """
    if set_initial_clock:
        set_clock("2026-08-01T00:00:00Z")
    plant_kwargs = {}
    if plant_name:
        plant_kwargs["name"] = plant_name
    plant = create_plant(export_listed=export_listed, **plant_kwargs)
    vat = create_vat(plant["id"])
    intake_kwargs = {"volume_liters": volume_liters}
    if fat_pct is not None:
        intake_kwargs["fat_pct"] = fat_pct
    if protein_pct is not None:
        intake_kwargs["protein_pct"] = protein_pct
    intake = create_intake(plant["id"], **intake_kwargs)
    culture, coagulant = create_released_additive_pair(
        plant["id"], culture_qty=culture_qty, coagulant_qty=coagulant_qty
    )
    make_overrides = {"liters_committed": liters_committed}
    if culture_units_planned is not None:
        make_overrides["culture_units_planned"] = culture_units_planned
    if coagulant_ml_planned is not None:
        make_overrides["coagulant_ml_planned"] = coagulant_ml_planned
    make = create_make_sheet(
        vat["id"], vat["version"], intake["id"], culture["id"], coagulant["id"],
        variety=variety, **make_overrides,
    )
    start_make(make["id"])
    if steps_to_sign is None:
        sign_steps_through_curd_ready(make["id"], variety)
    else:
        makers = [CM_ALICE, CM_BOB]
        for step_no in range(1, steps_to_sign + 1):
            signer = makers[(step_no - 1) % 2]
            _setup_ok(
                api_client.sign_off_step(make["id"], step_no, make_cheesemaker_headers(signer)),
                f"sign_off_step_{step_no}",
            )
    result = {
        "plant": plant,
        "vat": get_vat(vat["id"]),
        "intake": intake,
        "culture": culture,
        "coagulant": coagulant,
        "make": make,
    }
    if complete:
        complete_make(
            make["id"], green_weight_kg=green_weight_kg, wheels_produced=wheels_produced
        )
        result["batch_id"] = batch_id_for_make(make["id"])
        result["whey"] = whey_stream_for_make(make["id"])
    return result


def make_graded_batch(
    variety="MUENSTER",
    wheels_produced=4,
    green_weight_kg=500.0,
    volume_liters=5000.0,
    liters_committed=5000.0,
    room_capacity=100,
    age_to=None,
    grade_readings=None,
    grader_id=QA_CAROL,
    culture_qty=None,
    coagulant_qty=None,
    culture_units_planned=None,
    coagulant_ml_planned=None,
    export_listed=None,
):
    """Completed batch -> aging room -> all wheels placed -> (optional clock
    advance) -> one grading event. Returns a dict with the full chain plus
    `room`, `unit`, `batch` (post-grading), and `grading_event`."""
    ctx = make_completed_batch(
        variety=variety,
        volume_liters=volume_liters,
        liters_committed=liters_committed,
        green_weight_kg=green_weight_kg,
        wheels_produced=wheels_produced,
        culture_qty=culture_qty,
        coagulant_qty=coagulant_qty,
        culture_units_planned=culture_units_planned,
        coagulant_ml_planned=coagulant_ml_planned,
        export_listed=export_listed,
    )
    room = create_aging_room(ctx["plant"]["id"], capacity_wheels=room_capacity)
    unit = place_wheels(ctx["batch_id"], room, wheels_produced)
    if age_to is not None:
        set_clock(age_to)
    event = grade_batch(ctx["batch_id"], grader_id=grader_id, **(grade_readings or {}))
    ctx.update(
        {
            "room": room,
            "unit": unit,
            "grading_event": event,
            "batch": get_cheese_batch(ctx["batch_id"]),
        }
    )
    return ctx


def make_released_batch(**kwargs):
    """Graded (GRADE_A readings) batch taken through release."""
    ctx = make_graded_batch(**kwargs)
    release_batch(ctx["batch_id"])
    ctx["batch"] = get_cheese_batch(ctx["batch_id"])
    return ctx


def reconciled_run_inputs(variety, wheels_in):
    """Default saleable/trim weights that keep a run well inside tolerance for
    the given variety and wheel count."""
    input_weight = wheels_in * _WHEEL_WEIGHT[variety]
    trim = round(input_weight * 0.01, 2)
    finished = round(input_weight - trim, 2)
    return {"wheels_in": wheels_in, "finished_case_weight_kg": finished, "trim_waste_kg": trim}
