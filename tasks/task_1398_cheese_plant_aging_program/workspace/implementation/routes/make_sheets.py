"""Make sheet resources: vat booking, start, step sign-offs, complete, cancel
(PRD 3.3 and 3.4)."""

from flask import request

from calc import (
    D,
    MIN_AGE_DAYS,
    STEPS_REQUIRED,
    VARIETIES,
    actual_yield_pct,
    f2,
    provisional_yield_pct,
)
from db import STORES, new_record, now, touch
from errors import ApiError, invalid_request, invalid_state, stale_version
from helpers import (
    auth,
    body,
    f_dt,
    f_enum,
    f_int,
    f_num,
    f_str,
    filter_and_page,
    get_or_404,
)
from response import serialize, success
from routes import make_bp
from services import (
    active_makes_on_vat,
    rederive_vat_status,
    refill_lot_if_live,
    uncommit_milk_if_live,
)

bp = make_bp("make_sheets")

GET_ROLES = ("PlantAdmin", "MakePlanner", "Cheesemaker", "QAGrader")


@bp.post("/plant/make-sheets")
def create_make_sheet():
    auth("MakePlanner")
    b = body()
    # --- parse-time validation (400) ---
    vat_id = f_str(b, "vat_id")
    milk_intake_id = f_str(b, "milk_intake_id")
    variety = f_enum(b, "variety", VARIETIES)
    start_raw, start_dt = f_dt(b, "scheduled_start")
    end_raw, end_dt = f_dt(b, "scheduled_end")
    if not end_dt > start_dt:
        invalid_request("scheduled_end must be after scheduled_start")
    liters_committed = f_num(b, "liters_committed", positive=True)
    culture_lot_id = f_str(b, "culture_lot_id")
    coagulant_lot_id = f_str(b, "coagulant_lot_id")
    culture_units_planned = f_num(b, "culture_units_planned", positive=True)
    coagulant_ml_planned = f_num(b, "coagulant_ml_planned", positive=True)
    expected_vat_version = f_int(b, "expected_vat_version")
    # --- existence, body references in order (404) ---
    vat = get_or_404("vats", vat_id, "vat")
    get_or_404("milk_intakes", milk_intake_id, "milk intake")
    get_or_404("additive_lots", culture_lot_id, "additive lot")
    get_or_404("additive_lots", coagulant_lot_id, "additive lot")
    # --- optimistic concurrency (412) ---
    if expected_vat_version != vat["version"]:
        stale_version("expected_vat_version does not match the vat's current version")
    # --- state (409) ---
    if vat["status"] == "DECOMMISSIONED":
        invalid_state("Vat is DECOMMISSIONED")
    # --- booking gates (PRD 3.3): clean, overlap, capacity ---
    if not vat["cip_clean"]:
        raise ApiError("ERR_VAT_NOT_CLEAN", 409, "Vat is not CIP-clean")
    for m in active_makes_on_vat(vat["id"]):
        # Half-open [start, end) intersection; back-to-back adjacency allowed.
        if start_dt < m["_end_dt"] and end_dt > m["_start_dt"]:
            raise ApiError(
                "ERR_VAT_OVERLAP",
                409,
                "Requested interval overlaps an existing active booking on the vat",
            )
    if D(liters_committed) > D(vat["capacity_liters"]):
        raise ApiError("ERR_VAT_CAPACITY", 409, "liters_committed exceeds vat capacity")
    # --- create ---
    rec = new_record()
    rec.update(
        plant_id=vat["plant_id"],
        vat_id=vat_id,
        milk_intake_id=milk_intake_id,
        variety=variety,
        scheduled_start=start_raw,
        scheduled_end=end_raw,
        _start_dt=start_dt,
        _end_dt=end_dt,
        liters_committed=liters_committed,
        culture_lot_id=culture_lot_id,
        coagulant_lot_id=coagulant_lot_id,
        culture_units_planned=culture_units_planned,
        coagulant_ml_planned=coagulant_ml_planned,
        make_steps_completed=0,
        make_steps_required=STEPS_REQUIRED[variety],
        step_signer_ids=[],
        status="SCHEDULED",
    )
    STORES["make_sheets"][rec["id"]] = rec
    # Booking mutates the vat: first active booking IDLE -> BOOKED; queued
    # bookings keep it BOOKED; every booking bumps the vat's version.
    vat["status"] = "BOOKED"
    touch(vat)
    return success(serialize(rec), 201)


@bp.get("/plant/make-sheets/<makeSheetId>")
def get_make_sheet(makeSheetId):
    auth(*GET_ROLES)
    rec = get_or_404("make_sheets", makeSheetId, "make sheet")
    return success(serialize(rec))


@bp.get("/plant/make-sheets")
def list_make_sheets():
    auth(*GET_ROLES)
    data, pagination = filter_and_page(
        "make_sheets",
        [
            ("plant_id", request.args.get("plant_id")),
            ("vat_id", request.args.get("vat_id")),
            ("milk_intake_id", request.args.get("milk_intake_id")),
            ("culture_lot_id", request.args.get("culture_lot_id")),
            ("coagulant_lot_id", request.args.get("coagulant_lot_id")),
            ("status", request.args.get("status")),
        ],
        serialize,
    )
    return success(data, 200, pagination)


@bp.post("/plant/make-sheets/<makeSheetId>/start")
def start_make_sheet(makeSheetId):
    auth("Cheesemaker")
    body(required=False)
    ms = get_or_404("make_sheets", makeSheetId, "make sheet")
    if ms["status"] != "SCHEDULED":
        invalid_state("Make sheet is not SCHEDULED")
    culture = STORES["additive_lots"][ms["culture_lot_id"]]
    coagulant = STORES["additive_lots"][ms["coagulant_lot_id"]]
    intake = STORES["milk_intakes"][ms["milk_intake_id"]]
    vat = STORES["vats"][ms["vat_id"]]
    # Rung 7/10: additive usability — RELEASED and expires strictly later
    # than the current logical time (expiry exactly at now fails).
    current = now()
    for lot in (culture, coagulant):
        if lot["status"] != "RELEASED" or not lot["_expires_dt"] > current:
            raise ApiError(
                "ERR_ADDITIVE_LOT_UNUSABLE",
                422,
                "Referenced additive lot is not RELEASED or is expired",
            )
    # Rung 8: milk must be ACCEPTED.
    if intake["status"] != "ACCEPTED":
        raise ApiError("ERR_MILK_NOT_ACCEPTED", 409, "Milk intake is not ACCEPTED")
    # Rung 9: lot sufficiency (exact equality passes) then milk shortfall.
    if D(culture["quantity_on_hand"]) < D(ms["culture_units_planned"]):
        raise ApiError("ERR_ADDITIVE_INSUFFICIENT", 422, "Culture lot quantity insufficient")
    if D(coagulant["quantity_on_hand"]) < D(ms["coagulant_ml_planned"]):
        raise ApiError("ERR_ADDITIVE_INSUFFICIENT", 422, "Coagulant lot quantity insufficient")
    if D(intake["volume_liters"]) - D(intake["consumed_liters"]) < D(ms["liters_committed"]):
        raise ApiError(
            "ERR_MILK_SHORTFALL", 422, "liters_committed exceeds unconsumed intake volume"
        )
    # --- effects: consume lots, commit milk, flip states ---
    for lot, planned in (
        (culture, ms["culture_units_planned"]),
        (coagulant, ms["coagulant_ml_planned"]),
    ):
        lot["quantity_on_hand"] = float(D(lot["quantity_on_hand"]) - D(planned))
        if D(lot["quantity_on_hand"]) == 0:
            lot["status"] = "DEPLETED"
        touch(lot)
    intake["consumed_liters"] = float(D(intake["consumed_liters"]) + D(ms["liters_committed"]))
    if D(intake["consumed_liters"]) == D(intake["volume_liters"]):
        intake["status"] = "CONSUMED"
    touch(intake)
    ms["status"] = "IN_PROGRESS"
    touch(ms)
    vat["status"] = "IN_MAKE"
    touch(vat)
    return success(serialize(ms))


@bp.post("/plant/make-sheets/<makeSheetId>/steps/<stepNo>/sign-off")
def sign_off_step(makeSheetId, stepNo):
    uid, _role = auth("Cheesemaker")
    body(required=False)
    try:
        step = int(stepNo)
    except (TypeError, ValueError):
        invalid_request("stepNo must be an integer")
    ms = get_or_404("make_sheets", makeSheetId, "make sheet")
    if ms["status"] != "IN_PROGRESS":
        invalid_state("Make sheet is not IN_PROGRESS")
    # Rung 7 (segregation of duties) before rung 9 (step order), PRD 2.9.
    if ms["step_signer_ids"] and ms["step_signer_ids"][-1] == uid:
        raise ApiError(
            "ERR_STEP_SOLE_OPERATOR",
            422,
            "The same cheesemaker may not sign two consecutive steps",
        )
    if ms["make_steps_completed"] != step - 1:
        raise ApiError(
            "ERR_STEP_OUT_OF_ORDER", 409, "Step sign-off attempted out of strict sequence"
        )
    ms["step_signer_ids"].append(uid)
    ms["make_steps_completed"] += 1
    if ms["make_steps_completed"] == ms["make_steps_required"]:
        ms["status"] = "CURD_READY"
    touch(ms)
    return success(serialize(ms))


@bp.post("/plant/make-sheets/<makeSheetId>/complete")
def complete_make_sheet(makeSheetId):
    auth("Cheesemaker")
    ms = get_or_404("make_sheets", makeSheetId, "make sheet")
    if ms["status"] != "CURD_READY":
        invalid_state("Make sheet is not CURD_READY")
    b = body()
    green_weight_kg = f_num(b, "green_weight_kg", positive=True)
    wheels_produced = f_int(b, "wheels_produced", positive=True)
    if D(green_weight_kg) > D(ms["liters_committed"]):
        raise ApiError(
            "ERR_YIELD_IMPOSSIBLE", 422, "green_weight_kg exceeds liters_committed"
        )
    intake = STORES["milk_intakes"][ms["milk_intake_id"]]
    vat = STORES["vats"][ms["vat_id"]]
    variety = ms["variety"]
    liters = ms["liters_committed"]
    # --- cascade: CheeseBatch (GREEN) ---
    batch = new_record()
    batch.update(
        plant_id=ms["plant_id"],
        make_sheet_id=ms["id"],
        variety=variety,
        green_weight_kg=green_weight_kg,
        yield_provisional_pct=provisional_yield_pct(
            variety, liters, intake["fat_pct"], intake["protein_pct"]
        ),
        yield_actual_pct=actual_yield_pct(green_weight_kg, liters),
        wheels_produced=wheels_produced,
        wheels_placed=0,
        moisture_pct=None,
        fat_dry_basis_pct=None,
        current_grade="UNGRADED",
        release_decision="PENDING",
        min_age_days=MIN_AGE_DAYS[variety],
        status="GREEN",
    )
    STORES["cheese_batches"][batch["id"]] = batch
    # --- cascade: WheyStream (total fixed at creation) ---
    total_whey = f2(D(liters) - D(green_weight_kg))
    whey = new_record()
    whey.update(
        plant_id=ms["plant_id"],
        make_sheet_id=ms["id"],
        total_whey_kg=total_whey,
        valorized_kg=0.0,
        disposed_kg=total_whey,
        valorization_rate_pct=0.0,
    )
    STORES["whey_streams"][whey["id"]] = whey
    # --- cascade: vat to CLEANING, closed to bookings until CIP ---
    vat["status"] = "CLEANING"
    vat["cip_clean"] = False
    touch(vat)
    ms["status"] = "COMPLETED"
    touch(ms)
    return success(serialize(ms))


@bp.post("/plant/make-sheets/<makeSheetId>/cancel")
def cancel_make_sheet(makeSheetId):
    auth("MakePlanner")
    body(required=False)
    ms = get_or_404("make_sheets", makeSheetId, "make sheet")
    if ms["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        invalid_state("Only a SCHEDULED or IN_PROGRESS make sheet may be cancelled")
    if ms["status"] == "IN_PROGRESS":
        # Full compensation: refund additive lots and un-commit milk.
        # Reversals apply only to non-terminal resources (PRD 2.5).
        refill_lot_if_live(
            STORES["additive_lots"][ms["culture_lot_id"]], ms["culture_units_planned"]
        )
        refill_lot_if_live(
            STORES["additive_lots"][ms["coagulant_lot_id"]], ms["coagulant_ml_planned"]
        )
        uncommit_milk_if_live(
            STORES["milk_intakes"][ms["milk_intake_id"]], ms["liters_committed"]
        )
    ms["status"] = "CANCELLED"
    touch(ms)
    vat = STORES["vats"][ms["vat_id"]]
    rederive_vat_status(vat)
    touch(vat)
    return success(serialize(ms))
