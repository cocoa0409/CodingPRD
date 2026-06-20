"""TreatmentCycle endpoints and lifecycle transitions."""
from flask import Blueprint, request

import errors
from db import db
from errors import err
from calculations import scheduled_date
from middleware import get_auth, require_roles
from response import success, list_success
from services import cascade_cancel_children, place_on_hold
from store_helpers import (
    make_common, touch, public, sort_by_created,
    get_cycle, get_patient, get_protocol,
)
from validation import (
    get_body, require_str, require_date,
    get_pagination, paginate,
)

bp = Blueprint("cycles", __name__)

ALL_ROLES = {"Pharmacist", "Nurse", "PriorAuthCoordinator"}
DRUG_ORDER_RESOLVED = {"ADMINISTERED", "CANCELLED"}


@bp.route("/treatment-cycles", methods=["POST"])
def create_cycle():
    _, role = get_auth()
    require_roles(role, {"Pharmacist"})
    body = get_body()
    # FK existence (path before body; both FKs here in body, left-to-right) per §2.10.
    patient_id = require_str(body, "patient_id")
    get_patient(patient_id)
    protocol_id = require_str(body, "regimen_protocol_id")
    get_protocol(protocol_id)
    treatment_start_date = require_date(body, "treatment_start_date")

    with db.lock:
        entity = make_common()
        entity.update({
            "patient_id": patient_id,
            "regimen_protocol_id": protocol_id,
            "treatment_start_date": treatment_start_date,
            "current_cycle_number": 1,
            "status": "PLANNED",
            "bsa_snapshot_m2": None,
            "gfr_snapshot_ml_min": None,
        })
        db.treatment_cycles[entity["id"]] = entity
        return success(public(entity), status=201)


@bp.route("/treatment-cycles", methods=["GET"])
def list_cycles():
    _, role = get_auth()
    require_roles(role, ALL_ROLES)
    limit, offset = get_pagination()
    patient_id = request.args.get("patient_id")
    protocol_id = request.args.get("regimen_protocol_id")
    items = []
    for c in db.treatment_cycles.values():
        if patient_id is not None and c["patient_id"] != patient_id:
            continue
        if protocol_id is not None and c["regimen_protocol_id"] != protocol_id:
            continue
        items.append(c)
    items = sort_by_created(items)
    total = len(items)
    window = [public(c) for c in paginate(items, limit, offset)]
    return list_success(window, limit, offset, total)


@bp.route("/treatment-cycles/<cid>", methods=["GET"])
def get_one_cycle(cid):
    _, role = get_auth()
    require_roles(role, ALL_ROLES)
    entity = get_cycle(cid)
    return success(public(entity), status=200)


@bp.route("/treatment-cycles/<cid>/calendar", methods=["GET"])
def cycle_calendar(cid):
    _, role = get_auth()
    require_roles(role, ALL_ROLES)
    cycle = get_cycle(cid)
    protocol = db.regimen_protocols.get(cycle["regimen_protocol_id"])
    total_cycles = protocol["total_cycles"]
    cycle_length = protocol["cycle_length_days"]
    start = cycle["treatment_start_date"]

    items = [i for i in db.order_set_items.values()
             if i["regimen_protocol_id"] == cycle["regimen_protocol_id"]]
    # Order: cycle_number ASC, day_offset ASC, sequence_index ASC, created_at ASC.
    items_sorted = sorted(
        items,
        key=lambda i: (i["day_offset"], i["sequence_index"], i["created_at"], i.get("_seq", 0)),
    )

    rows = []
    for n in range(1, total_cycles + 1):
        for item in items_sorted:
            rows.append({
                "cycle_number": n,
                "order_set_item_id": item["id"],
                "drug_name": item["drug_name"],
                "role": item["role"],
                "scheduled_date": scheduled_date(start, cycle_length, n, item["day_offset"]),
            })
    # rows are already grouped by cycle_number then the per-item sort order.
    return success(rows, status=200, response_type="array")


@bp.route("/treatment-cycles/<cid>/activate", methods=["POST"])
def activate_cycle(cid):
    _, role = get_auth()
    require_roles(role, {"Pharmacist"})
    cycle = get_cycle(cid)
    with db.lock:
        # Per scaffold, the activate transition (PLANNED -> ACTIVE) lists exactly two
        # preconditions: patient ACTIVE and protocol PUBLISHED. The error catalog has
        # no "cycle not PLANNED" code, so we enforce only the two declared guards
        # (noted default — see summary).
        patient = db.patients.get(cycle["patient_id"])
        protocol = db.regimen_protocols.get(cycle["regimen_protocol_id"])
        if patient["status"] != "ACTIVE":
            raise err(errors.ERR_PATIENT_NOT_ACTIVE, "Patient is not ACTIVE")
        if protocol["status"] != "PUBLISHED":
            raise err(errors.ERR_PROTOCOL_NOT_PUBLISHED, "Protocol is not PUBLISHED")
        cycle["bsa_snapshot_m2"] = patient["bsa_m2"]
        cycle["gfr_snapshot_ml_min"] = patient["gfr_ml_min"]
        cycle["current_cycle_number"] = 1
        cycle["status"] = "ACTIVE"
        touch(cycle, bump_version=True)
        return success(public(cycle), status=200)


@bp.route("/treatment-cycles/<cid>/hold", methods=["POST"])
def hold_cycle(cid):
    _, role = get_auth()
    require_roles(role, {"Nurse", "Pharmacist"})
    cycle = get_cycle(cid)
    with db.lock:
        if cycle["status"] != "ACTIVE":
            raise err(errors.ERR_CYCLE_NOT_ACTIVE, "Cycle is not ACTIVE")
        place_on_hold(cycle)
        return success(public(cycle), status=200)


@bp.route("/treatment-cycles/<cid>/resume", methods=["POST"])
def resume_cycle(cid):
    _, role = get_auth()
    require_roles(role, {"Pharmacist"})
    cycle = get_cycle(cid)
    with db.lock:
        if cycle["status"] != "ON_HOLD":
            raise err(errors.ERR_CYCLE_NOT_ON_HOLD, "Cycle is not ON_HOLD")
        # An unresolved open toxicity event of grade >= 3 blocks resume.
        if _has_unresolved_high_grade_toxicity(cid):
            raise err(errors.ERR_UNRESOLVED_TOXICITY, "Unresolved grade>=3 toxicity remains open")
        cycle["status"] = "ACTIVE"
        touch(cycle, bump_version=True)
        return success(public(cycle), status=200)


@bp.route("/treatment-cycles/<cid>/advance-cycle", methods=["POST"])
def advance_cycle(cid):
    _, role = get_auth()
    require_roles(role, {"Pharmacist"})
    cycle = get_cycle(cid)
    with db.lock:
        if cycle["status"] != "ACTIVE":
            raise err(errors.ERR_CYCLE_NOT_ACTIVE, "Cycle is not ACTIVE")
        if not _all_current_orders_resolved(cycle):
            raise err(errors.ERR_UNRESOLVED_ORDERS,
                      "All current-cycle drug orders must be ADMINISTERED or CANCELLED")
        protocol = db.regimen_protocols.get(cycle["regimen_protocol_id"])
        if cycle["current_cycle_number"] < protocol["total_cycles"]:
            cycle["current_cycle_number"] += 1
            # status stays ACTIVE
        else:
            cycle["status"] = "COMPLETED"
        touch(cycle, bump_version=True)
        return success(public(cycle), status=200)


@bp.route("/treatment-cycles/<cid>/abandon", methods=["POST"])
def abandon_cycle(cid):
    _, role = get_auth()
    require_roles(role, {"Pharmacist"})
    cycle = get_cycle(cid)
    with db.lock:
        if cycle["status"] not in ("PLANNED", "ACTIVE", "ON_HOLD"):
            raise err(errors.ERR_CYCLE_TERMINAL, "Cycle is in a terminal state")
        cycle["status"] = "ABANDONED"
        cascade_cancel_children(cycle)
        touch(cycle, bump_version=True)
        return success(public(cycle), status=200)


def _all_current_orders_resolved(cycle):
    cycle_id = cycle["id"]
    for o in db.drug_orders.values():
        if o["treatment_cycle_id"] == cycle_id and o["status"] not in DRUG_ORDER_RESOLVED:
            return False
    return True


def _has_unresolved_high_grade_toxicity(cycle_id):
    for ev in db.toxicity_events.values():
        if ev["treatment_cycle_id"] == cycle_id and ev["ctcae_grade"] >= 3:
            return True
    return False
