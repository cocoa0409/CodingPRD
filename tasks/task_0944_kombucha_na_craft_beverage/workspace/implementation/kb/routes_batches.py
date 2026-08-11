"""Pitching a batch and driving the process axis."""

from decimal import Decimal
from flask import Blueprint

from . import constants as C
from . import lookup
from .auth import authorize
from .calc import batch_projected_abv, abv_class_for, recompute_vitality
from .envelope import list_response, object_response
from .errors import ApiError
from .routes_recipes import require_id
from .store import base_record, collection_sorted, db, touch
from .util import add_days, add_hours, dec, round2
from .validate import (
    body_dict,
    field,
    pagination,
    paginate,
    parse_body,
    query_enum,
    query_string,
)

bp = Blueprint("batches", __name__)

READ_ROLES = ("ProductionOperator", "QaManager", "ComplianceOfficer", "PlatformAdmin")
FERMENT_STAGES = ("F1_ACTIVE", "F2_ACTIVE", "READY_TO_PACKAGE", "PACKAGED", "DUMPED")
QA_DISPOSITIONS = ("PENDING", "CONFORMING", "AT_RISK", "NONCONFORMING")


def readings_of(batch_id, reading_type=None):
    rows = [
        r
        for r in db.qa_readings.values()
        if r["batch_id"] == batch_id
        and (reading_type is None or r["reading_type"] == reading_type)
    ]
    rows.sort(key=lambda r: (r["reading_at"], r["created_at"], r["_seq"]))
    return rows


def free_vessel_for(batch):
    vessel = db.vessels.get(batch["vessel_id"])
    if vessel is None or vessel.get("current_batch_id") != batch["id"]:
        return
    vessel["state"] = "DIRTY"
    vessel["current_batch_id"] = None
    # occupancy_start_at / occupancy_end_at are deliberately RETAINED
    touch(vessel)


@bp.post("/batches")
def pitch_batch():
    authorize("ProductionOperator", "PlatformAdmin")
    payload = body_dict()

    # gates 3, 4, 5 -- existence, in the declared order
    recipe = lookup.recipe(require_id(payload, "recipe_id"))
    culture = lookup.scoby_culture(require_id(payload, "scoby_culture_id"))
    vessel = lookup.vessel(require_id(payload, "vessel_id"))

    # gate 6 -- field shapes
    data = parse_body(
        payload,
        [
            field("batch_code", "string", required=True),
            field("recipe_id", "string", required=True),
            field("scoby_culture_id", "string", required=True),
            field("vessel_id", "string", required=True),
            field("pitched_liters", "number", required=True, positive=True),
            field("planned_f2_days", "integer", required=True),
            field("f2_added_sugar_g_per_l", "number", default=Decimal("0")),
            field("pitched_at", "datetime"),
        ],
    )
    planned_f2_days = int(data["planned_f2_days"])
    if planned_f2_days < 1 or planned_f2_days > C.F2_MAX_DAYS:
        raise ApiError(
            "ERR_VALIDATION",
            "planned_f2_days must be between 1 and %d inclusive." % C.F2_MAX_DAYS,
        )
    pitched_at = data["pitched_at"] or db.clock
    if pitched_at > db.clock:
        raise ApiError(
            "ERR_VALIDATION", "pitched_at may not be later than the logical clock."
        )

    # gate 7 -- culture state
    if culture["state"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "The culture must be ACTIVE to be pitched.")

    # gate 8 -- generation cap
    generation = int(culture["generation_number"])
    if generation > C.SCOBY_GENERATION_CAP:
        raise ApiError("ERR_SCOBY_GENERATION_CAP", "The lineage cap has been passed.")
    if generation == C.SCOBY_GENERATION_CAP:
        last = culture.get("last_reverified_at")
        if last is None or db.clock > add_days(last, C.SCOBY_REVERIFICATION_VALID_DAYS):
            raise ApiError(
                "ERR_SCOBY_GENERATION_CAP",
                "A generation %d culture needs a reverification no older than %d days."
                % (C.SCOBY_GENERATION_CAP, C.SCOBY_REVERIFICATION_VALID_DAYS),
            )

    # gate 9 -- vitality floor
    if int(culture["vitality_score"]) < C.SCOBY_VITALITY_FLOOR:
        raise ApiError(
            "ERR_SCOBY_VITALITY_TOO_LOW",
            "The culture's vitality_score is below the floor of %d."
            % C.SCOBY_VITALITY_FLOOR,
        )

    # gate 10 -- vessel state
    if vessel["state"] != "SANITIZED":
        raise ApiError(
            "ERR_VESSEL_UNAVAILABLE", "The vessel must be SANITIZED to be charged."
        )

    # gate 11 -- CIP freshness
    cip_completed_at = vessel.get("cip_completed_at")
    if cip_completed_at is None or db.clock > add_hours(
        cip_completed_at, C.VESSEL_CIP_VALID_HOURS
    ):
        raise ApiError(
            "ERR_VESSEL_CIP_EXPIRED",
            "The vessel's sanitation window has expired.",
        )

    # gate 12 -- occupancy interval overlap
    occupancy_end_at = add_days(
        pitched_at, int(recipe["planned_f1_days"]) + planned_f2_days
    )
    retained_start = vessel.get("occupancy_start_at")
    retained_end = vessel.get("occupancy_end_at")
    if retained_start is not None and retained_end is not None:
        if pitched_at < retained_end and retained_start < occupancy_end_at:
            raise ApiError(
                "ERR_VESSEL_UNAVAILABLE",
                "The requested occupancy interval overlaps the vessel's retained one.",
            )

    # gate 13 -- headspace allowance
    pitched_liters = round2(data["pitched_liters"])
    ceiling = dec(vessel["capacity_liters"]) * (
        Decimal("100") - C.VESSEL_HEADSPACE_PCT
    ) / Decimal("100")
    if pitched_liters > ceiling:
        raise ApiError(
            "ERR_VESSEL_CAPACITY_EXCEEDED",
            "pitched_liters exceeds the vessel's usable capacity.",
        )

    record = base_record()
    record.update(
        {
            "batch_code": data["batch_code"],
            "recipe_id": recipe["id"],
            "recipe_version_number_at_pitch": int(recipe["recipe_version_number"]),
            "scoby_culture_id": culture["id"],
            "vessel_id": vessel["id"],
            "pitched_liters": pitched_liters,
            "remaining_liters": pitched_liters,
            "drawn_liters": Decimal("0.00"),
            "loss_liters": Decimal("0.00"),
            "pitched_at": pitched_at,
            "planned_f2_days": planned_f2_days,
            "f2_added_sugar_g_per_l": dec(data["f2_added_sugar_g_per_l"]),
            "f1_completed_at": None,
            "f2_started_at": None,
            "f2_completed_at": None,
            "f1_measured_abv_pct": None,
            "projected_abv_pct": None,
            "projected_abv_class": None,
            "packaging_abv_pct": None,
            "ferment_stage": "F1_ACTIVE",
            "qa_disposition": "PENDING",
            "flagged_reading_count": 0,
            "temp_excursion_count": 0,
            "ph_target_hit_day_index": None,
            "qa_signoff_count": 0,
            "last_flagged_reading_by_user_id": None,
            "occupancy_end_at": occupancy_end_at,
        }
    )
    db.batches[record["id"]] = record

    vessel["state"] = "OCCUPIED"
    vessel["current_batch_id"] = record["id"]
    vessel["occupancy_start_at"] = pitched_at
    vessel["occupancy_end_at"] = occupancy_end_at
    touch(vessel)

    culture["pitch_count"] = int(culture["pitch_count"]) + 1
    recompute_vitality(culture)
    touch(culture)

    return object_response(record, 201)


@bp.post("/batches/<id>/advance-to-f2")
def advance_to_f2(id):
    authorize("ProductionOperator", "PlatformAdmin")
    batch = lookup.batch(id)
    body_dict()
    if batch["ferment_stage"] != "F1_ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE", "Only an F1_ACTIVE batch may advance to secondary."
        )
    if batch["qa_disposition"] == "NONCONFORMING":
        raise ApiError(
            "ERR_INVALID_STATE", "A NONCONFORMING batch may not advance."
        )
    f1_readings = readings_of(batch["id"], "F1")
    if not f1_readings:
        raise ApiError(
            "ERR_PH_WINDOW_MISSED",
            "The batch carries no F1 reading, so the pH window was never met.",
        )
    if batch["ph_target_hit_day_index"] is None:
        raise ApiError(
            "ERR_PH_WINDOW_MISSED",
            "The effective pH ceiling was not reached inside the day 5 to 14 window.",
        )

    batch["f1_completed_at"] = db.clock
    batch["f2_started_at"] = db.clock
    batch["ferment_stage"] = "F2_ACTIVE"
    batch["f1_measured_abv_pct"] = round2(f1_readings[-1]["abv_pct"])
    projected = batch_projected_abv(
        batch["f1_measured_abv_pct"],
        batch["planned_f2_days"],
        batch["f2_added_sugar_g_per_l"],
    )
    batch["projected_abv_pct"] = projected
    batch["projected_abv_class"] = abv_class_for(projected)
    touch(batch)
    return object_response(batch)


@bp.post("/batches/<id>/complete-f2")
def complete_f2(id):
    authorize("ProductionOperator", "PlatformAdmin")
    batch = lookup.batch(id)
    body_dict()
    if batch["ferment_stage"] != "F2_ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE", "Only an F2_ACTIVE batch may close secondary."
        )
    if batch["qa_disposition"] == "NONCONFORMING":
        raise ApiError(
            "ERR_INVALID_STATE", "A NONCONFORMING batch may not close secondary."
        )
    if db.clock > add_days(batch["f2_started_at"], C.F2_MAX_DAYS):
        raise ApiError(
            "ERR_PH_WINDOW_MISSED",
            "Secondary fermentation ran past its %d-day limit." % C.F2_MAX_DAYS,
        )

    batch["f2_completed_at"] = db.clock
    batch["ferment_stage"] = "READY_TO_PACKAGE"
    touch(batch)
    free_vessel_for(batch)
    return object_response(batch)


@bp.post("/batches/<id>/dump")
def dump_batch(id):
    authorize("ProductionOperator", "PlatformAdmin")
    batch = lookup.batch(id)
    payload = body_dict()
    parse_body(payload, [field("reason", "string")])
    if batch["ferment_stage"] not in ("F1_ACTIVE", "F2_ACTIVE", "READY_TO_PACKAGE"):
        raise ApiError("ERR_INVALID_STATE", "This batch may no longer be dumped.")

    batch["loss_liters"] = round2(
        dec(batch["loss_liters"]) + dec(batch["remaining_liters"])
    )
    batch["remaining_liters"] = Decimal("0.00")
    batch["ferment_stage"] = "DUMPED"
    touch(batch)
    free_vessel_for(batch)
    return object_response(batch)


@bp.get("/batches/<id>")
def read_batch(id):
    authorize(*READ_ROLES)
    return object_response(lookup.batch(id))


@bp.get("/batches")
def list_batches():
    authorize(*READ_ROLES)
    recipe_id = query_string("recipe_id")
    culture_id = query_string("scoby_culture_id")
    vessel_id = query_string("vessel_id")
    stage = query_enum("ferment_stage", FERMENT_STAGES)
    disposition = query_enum("qa_disposition", QA_DISPOSITIONS)
    limit, offset = pagination()

    def keep(b):
        if recipe_id is not None and b["recipe_id"] != recipe_id:
            return False
        if culture_id is not None and b["scoby_culture_id"] != culture_id:
            return False
        if vessel_id is not None and b["vessel_id"] != vessel_id:
            return False
        if stage is not None and b["ferment_stage"] != stage:
            return False
        if disposition is not None and b["qa_disposition"] != disposition:
            return False
        return True

    rows = collection_sorted(db.batches, keep)
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)
