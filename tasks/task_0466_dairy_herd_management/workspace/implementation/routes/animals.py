"""Animal, Lactation, TestDayRecord routes (PRD §3.2, §3.4, §3.11)."""
import math

from flask import Blueprint, request

import db
import errors
import serializers
import calculations
import domain
from errors import err
from middleware import require_roles
from records import make_record, touch
from response import object_response, array_response
from domain import paginate, sorted_by_creation
import validators as V

bp = Blueprint("animals", __name__)

ALL_ROLES = ("HerdManager", "ParlorTech", "Veterinarian", "CoopSettlementAgent", "Auditor")


# ---------------------------------------------------------------------------
# Animal (PRD §3.2)
# ---------------------------------------------------------------------------
@bp.route("/herds/animals", methods=["POST"])
@require_roles("HerdManager")
def create_animal():
    body = V.require_json_object()
    herd_id = V.require_fk(body, "herd_id")
    ear_tag = V.require_str(body, "ear_tag")
    birth_date = V.require_datetime(body, "birth_date")
    dam_id = V.opt_str(body, "dam_id", default=None)
    # existence (priority 3): herd path-equivalent body FK first, then dam FK
    herd = V.get_or_404("herd", herd_id)
    dam = None
    if dam_id is not None:
        dam = V.get_or_404("animal", dam_id)
    with db.lock:
        # uniqueness: ear_tag unique within herd (priority 7)
        for existing in db.animals.values():
            if existing["herd_id"] == herd_id and existing["ear_tag"] == ear_tag:
                raise err(errors.ERR_DUPLICATE_KEY, "ear_tag already exists in this herd")
        # cross-herd referential: dam must be in same herd (priority 8)
        if dam is not None and dam["herd_id"] != herd_id:
            raise err(errors.ERR_CROSS_HERD_REFERENCE, "dam belongs to a different herd")
        rec = make_record({
            "herd_id": herd_id,
            "ear_tag": ear_tag,
            "birth_date": body["birth_date"],
            "dam_id": dam_id,
            "parity": 0,
            "status": "HEIFER",
            "milk_eligible": True,
        })
        db.animals[rec["id"]] = rec
        return object_response(serializers.animal_out(rec), 201)


@bp.route("/herds/animals", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_animals():
    items = list(db.animals.values())
    herd_id = request.args.get("herd_id")
    dam_id = request.args.get("dam_id")
    status = request.args.get("status")
    if herd_id is not None:
        items = [r for r in items if r["herd_id"] == herd_id]
    if dam_id is not None:
        items = [r for r in items if r.get("dam_id") == dam_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items, request.args)
    return array_response([serializers.animal_out(r) for r in page], limit, offset, total)


@bp.route("/herds/animals/<animal_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_animal(animal_id):
    rec = V.get_or_404("animal", animal_id)
    return object_response(serializers.animal_out(rec), 200)


@bp.route("/herds/animals/<animal_id>/dry-off", methods=["POST"])
@require_roles("HerdManager")
def dry_off(animal_id):
    animal = V.get_or_404("animal", animal_id)
    with db.lock:
        # state preconditions (PRD §3.2)
        if animal["status"] != "ACTIVE":
            raise err(errors.ERR_ANIMAL_NOT_MILKING, "Animal is not ACTIVE")
        lac = domain.open_lactation(animal_id)
        if lac is None:
            raise err(errors.ERR_NO_OPEN_LACTATION, "Animal has no OPEN lactation")
        # cascaded lactation transition requires OPEN
        if lac["status"] != "OPEN":
            raise err(errors.ERR_LACTATION_NOT_OPEN, "Lactation is not OPEN")
        # ACTIVE -> DRY ; OPEN lactation -> DRY, stamp dry_off_date
        animal["status"] = "DRY"
        touch(animal)
        lac["status"] = "DRY"
        lac["dry_off_date"] = request_dry_off_date(animal)
        touch(lac)
        return object_response(serializers.animal_out(animal), 200)


def request_dry_off_date(animal):
    """dry_off_date stamped at dry-off. The PRD describes 'the date the lactation
    was dried off'; the dry-off endpoint takes no body date, so we stamp the
    current logical clock."""
    import clock
    from util import iso_format
    return iso_format(clock.now())


# ---------------------------------------------------------------------------
# Income Over Feed Cost (PRD §3.11)
# ---------------------------------------------------------------------------
@bp.route("/herds/animals/<animal_id>/iofc", methods=["GET"])
@require_roles("HerdManager", "Veterinarian", "CoopSettlementAgent", "Auditor")
def iofc(animal_id):
    animal = V.get_or_404("animal", animal_id)
    ration_id = request.args.get("ration_id")
    blend_raw = request.args.get("blend_price_per_cwt")
    if ration_id is None:
        raise err(errors.ERR_INVALID_REQUEST, "Missing query parameter: ration_id")
    if blend_raw is None:
        raise err(errors.ERR_INVALID_REQUEST, "Missing query parameter: blend_price_per_cwt")
    try:
        blend_price = float(blend_raw)
    except (TypeError, ValueError):
        raise err(errors.ERR_INVALID_REQUEST, "blend_price_per_cwt must be a number")
    ration = V.get_or_404("ration", ration_id)
    # ration must be ACTIVE (PRD §3.11)
    if ration["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_REQUEST, "Ration must be ACTIVE")
    lac = domain.open_lactation(animal_id)
    if lac is None:
        raise err(errors.ERR_INVALID_REQUEST, "Animal has no OPEN lactation")
    tests = domain.lactation_tests_sorted(lac["id"])
    if not tests:
        raise err(errors.ERR_INVALID_REQUEST, "No test-day record on the OPEN lactation")
    latest = tests[-1]
    result = calculations.income_over_feed_cost(
        latest["milk_weight_lbs"], blend_price, ration["daily_feed_cost_per_cow"])
    return object_response(result, 200)


# ---------------------------------------------------------------------------
# Lactation reads (PRD §3.2)
# ---------------------------------------------------------------------------
@bp.route("/herds/lactations", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_lactations():
    items = list(db.lactations.values())
    animal_id = request.args.get("animal_id")
    herd_id = request.args.get("herd_id")
    calving_event_id = request.args.get("calving_event_id")
    if animal_id is not None:
        items = [r for r in items if r["animal_id"] == animal_id]
    if herd_id is not None:
        items = [r for r in items if r["herd_id"] == herd_id]
    if calving_event_id is not None:
        items = [r for r in items if r.get("calving_event_id") == calving_event_id]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items, request.args)
    return array_response([serializers.lactation_out(r) for r in page], limit, offset, total)


@bp.route("/herds/lactations/<lactation_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_lactation(lactation_id):
    rec = V.get_or_404("lactation", lactation_id)
    return object_response(serializers.lactation_out(rec), 200)


# ---------------------------------------------------------------------------
# TestDayRecord (PRD §3.4)
# ---------------------------------------------------------------------------
@bp.route("/herds/test-day-records", methods=["POST"])
@require_roles("HerdManager", "ParlorTech")
def create_test_day_record():
    body = V.require_json_object()
    lactation_id = V.require_fk(body, "lactation_id")
    test_date = V.require_datetime(body, "test_date")
    milk_weight = V.require_number(body, "milk_weight_lbs", minimum=0)
    fat_pct = V.require_number(body, "fat_pct", minimum=0, maximum=15)
    protein_pct = V.require_number(body, "protein_pct", minimum=0, maximum=10)
    scc = V.require_int(body, "scc_thousands", minimum=0)
    # existence
    lac = V.get_or_404("lactation", lactation_id)
    with db.lock:
        # state: lactation must not be CLOSED (priority 5)
        if lac["status"] == "CLOSED":
            raise err(errors.ERR_LACTATION_CLOSED, "Lactation is CLOSED")
        # temporal (priority 9): test_date >= start_date and day_in_milk strictly
        # greater than the latest existing test on this lactation.
        from util import parse_datetime
        start_dt = parse_datetime(lac["start_date"])
        if test_date < start_dt:
            raise err(errors.ERR_TEST_DATE_NOT_AFTER_PRIOR,
                      "test_date is before lactation start_date")
        day_in_milk = math.floor((test_date - start_dt).total_seconds() / 86400.0)
        existing = domain.lactation_tests_sorted(lactation_id)
        if existing:
            max_dim = max(t["day_in_milk"] for t in existing)
            if day_in_milk <= max_dim:
                raise err(errors.ERR_TEST_DATE_NOT_AFTER_PRIOR,
                          "day_in_milk not strictly greater than prior test")
        rec = make_record({
            "lactation_id": lactation_id,
            "animal_id": lac["animal_id"],
            "herd_id": lac["herd_id"],
            "test_date": body["test_date"],
            "day_in_milk": day_in_milk,
            "milk_weight_lbs": milk_weight,
            "fat_pct": fat_pct,
            "protein_pct": protein_pct,
            "scc_thousands": scc,
            "included_in_milk_check_id": None,
        }, common=False)
        db.test_day_records[rec["id"]] = rec
        # recompute owning lactation's production figures
        domain.recompute_lactation_production(lac)
        return object_response(serializers.test_day_record_out(rec), 201)


@bp.route("/herds/test-day-records", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_test_day_records():
    items = list(db.test_day_records.values())
    lactation_id = request.args.get("lactation_id")
    animal_id = request.args.get("animal_id")
    herd_id = request.args.get("herd_id")
    included = request.args.get("included_in_milk_check_id")
    if lactation_id is not None:
        items = [r for r in items if r["lactation_id"] == lactation_id]
    if animal_id is not None:
        items = [r for r in items if r["animal_id"] == animal_id]
    if herd_id is not None:
        items = [r for r in items if r["herd_id"] == herd_id]
    if included is not None:
        items = [r for r in items if r.get("included_in_milk_check_id") == included]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items, request.args)
    return array_response([serializers.test_day_record_out(r) for r in page], limit, offset, total)


@bp.route("/herds/test-day-records/<tdr_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_test_day_record(tdr_id):
    if tdr_id not in db.test_day_records:
        raise err(errors.ERR_LACTATION_NOT_FOUND, "test-day record not found")
    return object_response(serializers.test_day_record_out(db.test_day_records[tdr_id]), 200)
