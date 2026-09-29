"""Fill-cycle creation, adjudication, roll generation, staging and reissue."""

import uuid

from flask import Blueprint

import calc
import clock
import db
import engine
import enums
import middleware
import response
import store
import validators
from errors import ApiError

bp = Blueprint("cycles", __name__)

ADJUDICATION_PASS_STATUSES = ("PLANNED", "HELD_TOO_SOON")


# ------------------------------------------------------------ cycle creation

@bp.post("/fill-cycles")
def create_fill_cycle():
    middleware.authenticate(("PharmacyOperations",))
    body = validators.json_body()
    patient_id = validators.string(body, "patient_id")
    cycle_start_date = validators.date_field(body, "cycle_start_date")
    day_supply_days = validators.integer(
        body, "day_supply_days", required=False, default=28, minimum=1, maximum=90
    )
    sync_mode = validators.enum(
        body, "sync_mode", enums.SYNC_MODES, required=False, default=None
    )

    patient = middleware.lookup("patient", patient_id)

    if patient["sync_status"] != "SYNCED":
        raise ApiError("ERR_PATIENT_NOT_SYNCHRONIZED")
    if patient["autoship_status"] != "ACTIVE":
        raise ApiError("ERR_AUTOSHIP_PAUSED")

    cycle_end_date = store.add_days(cycle_start_date, day_supply_days)
    for other in engine.cycles_of_patient(patient_id):
        if other["packaging_status"] in ("CANCELLED", "CLOSED"):
            continue
        if other["is_partial_reissue"]:
            continue
        other_start = store.d(other["cycle_start_date"])
        other_end = store.d(other["cycle_end_date"])
        if cycle_start_date < other_end and other_start < cycle_end_date:
            raise ApiError("ERR_CYCLE_WINDOW_OVERLAP")

    active = [
        rx for rx in engine.prescriptions_of_patient(patient_id) if rx["status"] == "ACTIVE"
    ]
    if not active:
        raise ApiError("ERR_NO_ACTIVE_PRESCRIPTIONS")

    cycle = store.create(
        db.fill_cycles,
        {
            "patient_id": patient_id,
            "cycle_start_date": store.fmt_date(cycle_start_date),
            "cycle_end_date": store.fmt_date(cycle_end_date),
            "day_supply_days": day_supply_days,
            "sync_mode": sync_mode or patient["sync_mode"],
            "is_partial_reissue": False,
            "reissue_of_cycle_id": None,
            "vacation_exception_id": None,
            "approved_vacation_extra_days": 0,
            "packaging_status": "DRAFT",
            "insurance_status": "NOT_ADJUDICATED",
            "reissue_required": False,
            "roll_pouch_count": 0,
            "total_copay_cents": 0,
            "final_copay_cents": None,
            "reissue_fee_cents": 0,
            "credit_applied_cents": 0,
            "rounding_delta_cents": None,
        },
    )
    for rx in active:
        _stage_line(cycle, rx)

    store.commit()
    return response.object_response(store.serialize(cycle), 201)


def _stage_line(cycle, prescription):
    return store.create(
        db.cycle_lines,
        {
            "cycle_id": cycle["id"],
            "prescription_id": prescription["id"],
            "line_status": "PLANNED",
            "packable_route": None,
            "days_supply_filled": 0,
            "bridge_days_applied": 0,
            "trim_days_applied": 0,
            "line_start_date": None,
            "line_end_date": None,
            "quantity_dispensed": 0,
            "refill_pct_used": 0,
            "allowance_days": 0,
            "copay_cents": 0,
            "hold_reason": None,
        },
    )


# ---------------------------------------------------------------- adjudication

@bp.post("/fill-cycles/<cycle_id>/adjudicate")
def adjudicate(cycle_id):
    middleware.authenticate(("VerifyingPharmacist",))
    body = validators.json_body()
    force_ids = validators.string_array(
        body, "force_pouch_prescription_ids", required=False, default=None
    )
    vacation_exception_id = validators.string(
        body, "vacation_exception_id", required=False, default=None
    )

    cycle = middleware.lookup("fill_cycle", cycle_id)

    forced = []
    for rx_id in force_ids or []:
        forced.append(middleware.lookup("prescription", rx_id))
    if vacation_exception_id is not None:
        middleware.lookup("vacation_exception", vacation_exception_id)

    patient = engine.patient_of_cycle(cycle)
    plan = engine.plan_of(patient)

    if patient["autoship_status"] != "ACTIVE":
        raise ApiError("ERR_AUTOSHIP_PAUSED")
    if cycle["packaging_status"] not in ("DRAFT", "LINES_ADJUDICATED") or cycle[
        "insurance_status"
    ] not in ("NOT_ADJUDICATED", "REJECTED_TOO_SOON"):
        raise ApiError("ERR_INVALID_CYCLE_STATE")

    for rx in forced:
        if rx["refrigerated"]:
            raise ApiError("ERR_COLD_CHAIN_NOT_PACKABLE")
    for rx in forced:
        if not rx["packable"]:
            raise ApiError("ERR_NON_PACKABLE_IN_POUCH_ROUTE")

    exception = None
    if vacation_exception_id is not None:
        exception = db.vacation_exceptions[vacation_exception_id]
        if exception["patient_id"] != cycle["patient_id"] or exception["status"] not in (
            "PHARMACIST_APPROVED",
            "PAYER_OVERRIDE_APPROVED",
        ):
            raise ApiError("ERR_NO_APPROVED_VACATION_EXCEPTION")
    elif cycle["vacation_exception_id"]:
        exception = db.vacation_exceptions.get(cycle["vacation_exception_id"])

    if exception is not None:
        extra_days = exception["approved_extra_days"] or 0
        waives = bool(exception["waives_refill_too_soon"])
    else:
        extra_days = cycle["approved_vacation_extra_days"]
        waives = False

    cycle_start = store.d(cycle["cycle_start_date"])
    pass_lines = [
        line
        for line in engine.lines_of_cycle(cycle_id)
        if line["line_status"] in ADJUDICATION_PASS_STATUSES
    ]

    computed = []
    for line in pass_lines:
        prescription = db.prescriptions[line["prescription_id"]]
        figures = _line_figures(cycle, cycle_start, plan, prescription, extra_days, waives)
        computed.append((line, prescription, figures))

    # Atomic day-supply edit: nothing is written when any line overruns.
    for _line, _rx, figures in computed:
        if figures["days_supply_filled"] > figures["allowance_days"]:
            raise ApiError("ERR_DAY_SUPPLY_EXCEEDS_ALLOWANCE")

    if vacation_exception_id is not None:
        cycle["vacation_exception_id"] = vacation_exception_id
        cycle["approved_vacation_extra_days"] = extra_days

    for line, prescription, figures in computed:
        line["days_supply_filled"] = figures["days_supply_filled"]
        line["bridge_days_applied"] = figures["bridge_days_applied"]
        line["trim_days_applied"] = figures["trim_days_applied"]
        line["line_start_date"] = store.fmt_date(figures["line_start_date"])
        line["line_end_date"] = store.fmt_date(figures["line_end_date"])
        line["packable_route"] = figures["packable_route"]
        line["quantity_dispensed"] = figures["quantity_dispensed"]
        line["refill_pct_used"] = figures["refill_pct_used"]
        line["allowance_days"] = figures["allowance_days"]
        line["copay_cents"] = figures["copay_cents"]

        if not figures["clears_refill_edit"]:
            line["line_status"] = "HELD_TOO_SOON"
            line["hold_reason"] = "REFILL_TOO_SOON"
        elif prescription["refills_remaining"] <= 0:
            line["line_status"] = "HELD_AUTH"
            line["hold_reason"] = "NO_REFILLS_REMAINING"
            if prescription["status"] == "ACTIVE":
                prescription["status"] = "PENDING_AUTHORIZATION"
                store.touch(prescription)
        else:
            line["line_status"] = "ADJUDICATED"
            line["hold_reason"] = None
            engine.stamp_dispense(prescription, line)
        store.touch(line)

    if cycle["packaging_status"] == "DRAFT":
        cycle["packaging_status"] = "LINES_ADJUDICATED"

    all_lines = engine.lines_of_cycle(cycle_id)
    if any(line["line_status"] == "HELD_TOO_SOON" for line in all_lines):
        cycle["insurance_status"] = "REJECTED_TOO_SOON"
    elif any(line["line_status"] == "HELD_AUTH" for line in all_lines):
        cycle["insurance_status"] = "EDITS_PENDING"
    else:
        cycle["insurance_status"] = "CLEARED"

    engine.recompute_total_copay(cycle)
    engine.apply_credits(cycle, patient)
    store.touch(cycle)

    store.commit()
    return response.object_response(store.serialize(cycle))


def _line_figures(cycle, cycle_start, plan, prescription, extra_days, waives):
    bridge, trim, days_filled = calc.alignment(
        cycle["sync_mode"],
        cycle_start,
        cycle["day_supply_days"],
        store.d(prescription["last_dispensed_date"]),
        prescription["last_dispensed_days_supply"],
    )
    line_start = store.add_days(cycle_start, -bridge)
    line_end = store.add_days(line_start, days_filled)
    pct_used = calc.refill_pct_used(
        cycle_start,
        store.d(prescription["last_dispensed_date"]),
        prescription["last_dispensed_days_supply"],
    )
    allowance = calc.allowance_days(
        plan, prescription, cycle["day_supply_days"], bridge, extra_days
    )
    clears = waives or pct_used >= plan["refill_too_soon_threshold_pct"]
    return {
        "bridge_days_applied": bridge,
        "trim_days_applied": trim,
        "days_supply_filled": days_filled,
        "line_start_date": line_start,
        "line_end_date": line_end,
        "refill_pct_used": pct_used,
        "allowance_days": allowance,
        "packable_route": calc.packable_route(prescription),
        "quantity_dispensed": calc.quantity_dispensed(prescription, days_filled),
        "copay_cents": calc.line_copay_cents(plan, prescription, days_filled),
        "clears_refill_edit": clears,
    }


# ------------------------------------------------------------- roll generation

@bp.post("/fill-cycles/<cycle_id>/generate-roll")
def generate_roll(cycle_id):
    middleware.authenticate(("PackagingTechnician",))
    cycle = middleware.lookup("fill_cycle", cycle_id)

    if cycle["packaging_status"] != "LINES_ADJUDICATED":
        raise ApiError("ERR_INVALID_CYCLE_STATE")
    if cycle["insurance_status"] == "EDITS_PENDING":
        raise ApiError("ERR_CYCLE_NOT_CLEARED")

    lines = engine.lines_of_cycle(cycle_id)
    contributing = [
        line
        for line in lines
        if line["line_status"] == "ADJUDICATED" and line["packable_route"] == "POUCH"
    ]
    if not contributing:
        raise ApiError("ERR_NO_PACKABLE_LINES")
    for line in lines:
        if line["line_status"] == "ADJUDICATED":
            if db.prescriptions[line["prescription_id"]]["status"] != "ACTIVE":
                raise ApiError("ERR_RX_PENDING_AUTHORIZATION")

    segment_start = min(store.d(line["line_start_date"]) for line in contributing)
    segment_end = store.add_days(
        max(store.d(line["line_end_date"]) for line in contributing), -1
    )
    for roll in db.pouch_rolls.values():
        if roll["verification_status"] == "FAILED_QUARANTINED":
            continue
        other_cycle = db.fill_cycles.get(roll["cycle_id"])
        if not other_cycle or other_cycle["patient_id"] != cycle["patient_id"]:
            continue
        existing_start = store.d(roll["segment_start_date"])
        existing_end = store.d(roll["segment_end_date"])
        if segment_start <= existing_end and existing_start <= segment_end:
            raise ApiError("ERR_REISSUE_SEGMENT_OVERLAP")

    if cycle["insurance_status"] == "REJECTED_TOO_SOON":
        raise ApiError("ERR_REFILL_TOO_SOON")

    # Contributions are ordered by ascending prescription created_at.
    ordered_contributions = sorted(
        contributing,
        key=lambda line: store.sort_key(db.prescriptions[line["prescription_id"]]),
    )
    pairings = {}
    for line in ordered_contributions:
        prescription = db.prescriptions[line["prescription_id"]]
        start = store.d(line["line_start_date"])
        for offset in range(line["days_supply_filled"]):
            dose_date = store.add_days(start, offset)
            for slot in prescription["dose_times"]:
                pairings.setdefault((dose_date, slot), []).append(prescription)

    roll = store.create(
        db.pouch_rolls,
        {
            "cycle_id": cycle_id,
            "roll_serial": "ROLL-" + uuid.uuid4().hex[:8].upper(),
            "verification_status": "BUILT",
            "pouch_count": len(pairings),
            "segment_start_date": store.fmt_date(segment_start),
            "segment_end_date": store.fmt_date(segment_end),
            "packed_by_user_id": None,
            "packed_at": None,
            "verified_by_user_id": None,
            "verified_at": None,
            "rework_count": 0,
            "mismatch_pouch_count": 0,
        },
    )

    index = 0
    for dose_date, slot in sorted(
        pairings.keys(), key=lambda pair: (pair[0], enums.SLOT_ORDER[pair[1]])
    ):
        index += 1
        contents = [
            {"prescription_id": rx["id"], "quantity": rx["quantity_per_dose"]}
            for rx in pairings[(dose_date, slot)]
        ]
        store.create(
            db.pouches,
            {
                "roll_id": roll["id"],
                "pouch_index": index,
                "dose_date": store.fmt_date(dose_date),
                "dose_slot": slot,
                "contents": contents,
                "expected_pill_count": sum(item["quantity"] for item in contents),
                "verification_result": "PENDING",
                "detected_pill_count": None,
                "image_confidence_pct": None,
                "imaged_by_user_id": None,
                "imaged_at": None,
            },
        )

    cycle["packaging_status"] = "ROLL_GENERATED"
    cycle["roll_pouch_count"] = roll["pouch_count"]
    store.touch(cycle)

    store.commit()
    return response.object_response(store.serialize(roll), 201)


# --------------------------------------------------------------- parcel staging

@bp.post("/fill-cycles/<cycle_id>/shipments")
def stage_shipment(cycle_id):
    middleware.authenticate(("PharmacyOperations",))
    body = validators.json_body()
    shipment_kind = validators.enum(body, "shipment_kind", enums.SHIPMENT_KINDS)
    carrier_service = validators.enum(body, "carrier_service", enums.CARRIER_SERVICES)
    packaging = validators.enum(
        body, "packaging", enums.PACKAGINGS, required=False, default="STANDARD"
    )

    cycle = middleware.lookup("fill_cycle", cycle_id)

    if shipment_kind == "POUCH_ROLL":
        allowed_states = ("VERIFIED", "SHIPPED")
    else:
        allowed_states = (
            "LINES_ADJUDICATED",
            "ROLL_GENERATED",
            "PACKED",
            "VERIFIED",
            "SHIPPED",
        )
    if cycle["packaging_status"] not in allowed_states:
        raise ApiError("ERR_INVALID_CYCLE_STATE")

    if shipment_kind == "COLD_CHAIN":
        if packaging == "STANDARD":
            raise ApiError("ERR_COLD_CHAIN_PACKAGING_INVALID")
    elif packaging in ("INSULATED_GEL", "INSULATED_DRY_ICE"):
        raise ApiError("ERR_COLD_CHAIN_PACKAGING_INVALID")

    route = enums.KIND_TO_ROUTE[shipment_kind]
    covered = [
        line
        for line in engine.lines_of_cycle(cycle_id)
        if line["packable_route"] == route
        and line["line_status"] in ("ADJUDICATED", "PACKED_OUT")
    ]
    if not covered:
        raise ApiError("ERR_NO_LINES_FOR_SHIPMENT_KIND")
    for existing in engine.shipments_of_cycle(cycle_id):
        if existing["shipment_kind"] != shipment_kind:
            continue
        if existing["status"] in ("CANCELLED", "EXCEPTION_RETURNED"):
            continue
        raise ApiError("ERR_NO_LINES_FOR_SHIPMENT_KIND")

    if shipment_kind == "COLD_CHAIN":
        for other in engine.shipments_of_patient(cycle["patient_id"]):
            if other["shipment_kind"] != "COLD_CHAIN":
                continue
            if other["status"] in ("CANCELLED", "EXCEPTION_RETURNED"):
                continue
            staged_at = store.ts(other["staged_at"])
            if staged_at is None:
                continue
            gap_seconds = abs((clock.now() - staged_at).total_seconds())
            if gap_seconds < enums.COLD_CHAIN_GAP_HOURS * 3600:
                raise ApiError("ERR_COLD_CHAIN_GAP_VIOLATION")

    shipment = store.create(
        db.shipments,
        {
            "cycle_id": cycle_id,
            "shipment_kind": shipment_kind,
            "carrier_service": carrier_service,
            "packaging": packaging,
            "status": "STAGED",
            "covers_line_ids": [line["id"] for line in covered],
            "ship_cost_cents": calc.ship_cost_cents(
                shipment_kind, packaging, carrier_service
            ),
            "tracking_number": None,
            "staged_at": clock.now_iso(),
            "dispatched_at": None,
            "delivered_at": None,
            "pickup_confirmed_at": None,
            "cold_chain_excursion_minutes": 0,
        },
    )
    store.touch(cycle)

    store.commit()
    return response.object_response(store.serialize(shipment), 201)


# --------------------------------------------------------------- partial reissue

@bp.post("/fill-cycles/<cycle_id>/reissue")
def reissue(cycle_id):
    middleware.authenticate(("PharmacyOperations",))
    body = validators.json_body()
    effective_date = validators.date_field(body, "effective_date")
    replacement_ids = validators.string_array(body, "replacement_prescription_ids")
    expected_cycle_version = validators.integer(body, "expected_cycle_version")

    cycle = middleware.lookup("fill_cycle", cycle_id)
    replacements = []
    seen = set()
    for rx_id in replacement_ids:
        prescription = middleware.lookup("prescription", rx_id)
        if rx_id not in seen:
            seen.add(rx_id)
            replacements.append(prescription)

    if expected_cycle_version != cycle["version"]:
        raise ApiError("ERR_STALE_CYCLE_VERSION")

    patient = engine.patient_of_cycle(cycle)
    if patient["autoship_status"] != "ACTIVE":
        raise ApiError("ERR_AUTOSHIP_PAUSED")
    if cycle["packaging_status"] not in ("ROLL_GENERATED", "PACKED", "VERIFIED"):
        raise ApiError("ERR_INVALID_CYCLE_STATE")

    cycle_start = store.d(cycle["cycle_start_date"])
    cycle_end = store.d(cycle["cycle_end_date"])
    if effective_date <= cycle_start or effective_date >= cycle_end:
        raise ApiError("ERR_REISSUE_DATE_OUT_OF_WINDOW")

    replacement_ids_set = {rx["id"] for rx in replacements}
    reissued = []
    for line in engine.lines_of_cycle(cycle_id):
        if line["line_status"] == "SUPERSEDED_PENDING_REISSUE":
            reissued.append(line)
        elif (
            line["line_status"] == "ADJUDICATED"
            and line["prescription_id"] in replacement_ids_set
        ):
            reissued.append(line)
    if not reissued:
        raise ApiError("ERR_NOTHING_TO_REISSUE")

    # Step one: the gross credit, rounded per line.
    used_days = store.day_diff(effective_date, cycle_start)
    credits = {}
    gross_credit_cents = 0
    for line in reissued:
        unused_days = line["days_supply_filled"] - used_days
        line_credit = calc.line_reissue_credit_cents(
            line["copay_cents"], unused_days, line["days_supply_filled"]
        )
        credits[line["id"]] = (line_credit, unused_days)
        gross_credit_cents += line_credit

    # Steps two and three: the retained basis selects the fee tier.
    tier_basis_cents = cycle["total_copay_cents"] - gross_credit_cents
    fee_cents = calc.reissue_fee_cents(tier_basis_cents)

    # Step four: the net credit.
    amount_cents = max(0, gross_credit_cents - fee_cents)

    for line in reissued:
        line_credit, unused_days = credits[line["id"]]
        line["line_status"] = "REISSUED"
        line["copay_cents"] = line["copay_cents"] - line_credit
        line["days_supply_filled"] = used_days
        line["line_end_date"] = store.fmt_date(effective_date)
        store.touch(line)

        prescription = db.prescriptions[line["prescription_id"]]
        prescription["last_dispensed_days_supply"] = used_days
        prescription["days_dispensed_total"] -= unused_days
        store.touch(prescription)

    for roll in engine.rolls_of_cycle(cycle_id):
        roll["segment_end_date"] = store.fmt_date(store.add_days(effective_date, -1))
        store.touch(roll)

    cycle["reissue_fee_cents"] = fee_cents
    engine.recompute_total_copay(cycle, extra_statuses=("REISSUED",))
    store.touch(cycle)

    engine.issue_memo(patient, cycle_id, "PARTIAL_REISSUE", amount_cents)

    successor = store.create(
        db.fill_cycles,
        {
            "patient_id": cycle["patient_id"],
            "cycle_start_date": store.fmt_date(effective_date),
            "cycle_end_date": store.fmt_date(cycle_end),
            "day_supply_days": store.day_diff(cycle_end, effective_date),
            "sync_mode": cycle["sync_mode"],
            "is_partial_reissue": True,
            "reissue_of_cycle_id": cycle_id,
            "vacation_exception_id": None,
            "approved_vacation_extra_days": 0,
            "packaging_status": "DRAFT",
            "insurance_status": "NOT_ADJUDICATED",
            "reissue_required": False,
            "roll_pouch_count": 0,
            "total_copay_cents": 0,
            "final_copay_cents": None,
            "reissue_fee_cents": 0,
            "credit_applied_cents": 0,
            "rounding_delta_cents": None,
        },
    )
    for prescription in sorted(replacements, key=store.sort_key):
        _stage_line(successor, prescription)

    store.commit()
    return response.object_response(store.serialize(successor), 201)
