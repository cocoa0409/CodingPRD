"""Humane handling audits, noncompliance records, recall exercises."""

from decimal import Decimal
from flask import Blueprint, request

from db import store, new_id
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from validation import get_body, req_string, req_enum, req_number
from errors import (raise_error, ERR_NOT_FOUND, ERR_DAY_NOT_OPEN,
                    ERR_NONCOMPLIANCE_INVALID_STATE, ERR_SEGREGATION_OF_DUTIES_VIOLATION,
                    ERR_RECALL_ALREADY_COMPLETED, ERR_RECALL_TARGET_INVALID)
from serializers import audit_out, nr_out, recall_out
from services import (touch, create_noncompliance_record, recompute_operating_status,
                      round2)

bp = Blueprint("audits_nrs_recalls", __name__)

READ_ROLES = ("PlantAdmin", "QAManager", "QATech", "LabAnalyst", "Inspector", "ProductionManager")
SCOPES = {"ONE_STEP_BACK", "ONE_STEP_FORWARD", "FULL"}

STUNNING_MIN = 99.0
SLIPS_MAX = 3.0
VOCAL_MAX = 10.0
RECALL_PASS_THRESHOLD = Decimal("0.995")


# ---------------------------------------------------------------------------
# Humane handling audits
# ---------------------------------------------------------------------------

@bp.route("/plants/<pid>/humane-audits", methods=["POST"])
def create_audit(pid):
    user_id, _ = require_roles("Inspector")
    body = get_body()
    production_day_id = req_string(body, "production_day_id")
    stunning = req_number(body, "stunning_efficacy_pct", ge=0, le=100)
    slips = req_number(body, "slips_falls_pct", ge=0, le=100)
    vocal = req_number(body, "vocalization_pct", ge=0, le=100)

    plant = store.plants.get(pid)
    if not plant:
        raise_error(ERR_NOT_FOUND, "Plant not found")
    day = store.production_days.get(production_day_id)
    if not day or day["plant_id"] != pid:
        raise_error(ERR_NOT_FOUND, "Production day not found for this plant")
    if day["status"] != "OPEN":
        raise_error(ERR_DAY_NOT_OPEN, "Production day is not OPEN")

    passed = (stunning >= STUNNING_MIN and slips <= SLIPS_MAX and vocal <= VOCAL_MAX)
    outcome = "PASSED" if passed else "FAILED"

    now = store.now_iso()
    audit = {
        "id": new_id(),
        "plant_id": pid,
        "production_day_id": production_day_id,
        "auditor_user_id": user_id,
        "stunning_efficacy_pct": stunning,
        "slips_falls_pct": slips,
        "vocalization_pct": vocal,
        "outcome": outcome,
        "noncompliance_record_id": None,
        "created_at": now,
    }
    store.humane_audits[audit["id"]] = audit

    if outcome == "FAILED":
        nr = create_noncompliance_record(
            plant_id=pid,
            production_day_id=production_day_id,
            category="HUMANE_HANDLING",
            severity="CRITICAL",
            created_by=user_id,
            description=f"Humane handling audit failed: stunning_efficacy_pct={stunning}, slips_falls_pct={slips}, vocalization_pct={vocal}",
        )
        audit["noncompliance_record_id"] = nr["id"]

    return success_object(audit_out(audit), 201)


@bp.route("/humane-audits/<aid>", methods=["GET"])
def get_audit(aid):
    require_roles(*READ_ROLES)
    a = store.humane_audits.get(aid)
    if not a:
        raise_error(ERR_NOT_FOUND, "Humane handling audit not found")
    return success_object(audit_out(a))


@bp.route("/humane-audits", methods=["GET"])
def list_audits():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    plant_id = request.args.get("plant_id")
    day_id = request.args.get("production_day_id")
    outcome = request.args.get("outcome")
    items = sorted(store.humane_audits.values(), key=lambda a: (a["created_at"], a["id"]))
    if plant_id is not None:
        items = [a for a in items if a["plant_id"] == plant_id]
    if day_id is not None:
        items = [a for a in items if a["production_day_id"] == day_id]
    if outcome is not None:
        items = [a for a in items if a["outcome"] == outcome]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([audit_out(a) for a in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Noncompliance records
# ---------------------------------------------------------------------------

@bp.route("/noncompliance-records/<nid>", methods=["GET"])
def get_nr(nid):
    require_roles(*READ_ROLES)
    nr = store.noncompliance_records.get(nid)
    if not nr:
        raise_error(ERR_NOT_FOUND, "Noncompliance record not found")
    return success_object(nr_out(nr))


@bp.route("/noncompliance-records", methods=["GET"])
def list_nrs():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    plant_id = request.args.get("plant_id")
    day_id = request.args.get("production_day_id")
    category = request.args.get("category")
    status = request.args.get("status")
    items = sorted(store.noncompliance_records.values(), key=lambda n: (n["created_at"], n["id"]))
    if plant_id is not None:
        items = [n for n in items if n["plant_id"] == plant_id]
    if day_id is not None:
        items = [n for n in items if n["production_day_id"] == day_id]
    if category is not None:
        items = [n for n in items if n["category"] == category]
    if status is not None:
        items = [n for n in items if n["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([nr_out(n) for n in page], limit, offset, total)


@bp.route("/noncompliance-records/<nid>/appeal", methods=["POST"])
def appeal_nr(nid):
    user_id, _ = require_roles("QAManager")
    body = get_body()
    appeal_note = req_string(body, "appeal_note")
    nr = store.noncompliance_records.get(nid)
    if not nr:
        raise_error(ERR_NOT_FOUND, "Noncompliance record not found")
    if nr["status"] != "OPEN":
        raise_error(ERR_NONCOMPLIANCE_INVALID_STATE, "NR must be OPEN to appeal")
    nr["status"] = "APPEALED"
    nr["appeal_note"] = appeal_note
    touch(nr)
    return success_object(nr_out(nr))


@bp.route("/noncompliance-records/<nid>/resolve", methods=["POST"])
def resolve_nr(nid):
    user_id, _ = require_roles("Inspector")
    body = get_body()
    resolution_note = req_string(body, "resolution_note")
    nr = store.noncompliance_records.get(nid)
    if not nr:
        raise_error(ERR_NOT_FOUND, "Noncompliance record not found")
    if nr["status"] not in ("OPEN", "APPEALED"):
        raise_error(ERR_NONCOMPLIANCE_INVALID_STATE, "NR must be OPEN or APPEALED to resolve")
    if user_id == nr["created_by"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES_VIOLATION, "Resolver must differ from created_by")
    nr["status"] = "CLOSED"
    nr["resolved_by"] = user_id
    nr["resolution_note"] = resolution_note
    touch(nr)
    recompute_operating_status(nr["plant_id"])
    return success_object(nr_out(nr))


# ---------------------------------------------------------------------------
# Recall exercises
# ---------------------------------------------------------------------------

@bp.route("/plants/<pid>/recall-exercises", methods=["POST"])
def create_recall(pid):
    user_id, _ = require_roles("PlantAdmin")
    body = get_body()
    target_finished_lot_id = req_string(body, "target_finished_lot_id")
    scope = req_enum(body, "scope", SCOPES)

    plant = store.plants.get(pid)
    if not plant:
        raise_error(ERR_NOT_FOUND, "Plant not found")
    fl = store.finished_lots.get(target_finished_lot_id)
    if not fl:
        raise_error(ERR_NOT_FOUND, "Target finished lot not found")
    # Target must belong to this plant
    fl_day = store.production_days.get(fl["production_day_id"])
    if not fl_day or fl_day["plant_id"] != pid:
        raise_error(ERR_RECALL_TARGET_INVALID, "Target finished lot does not belong to this plant")

    from datetime import timedelta
    now = store.now_iso()
    now_dt = store.now()
    re = {
        "id": new_id(),
        "plant_id": pid,
        "target_finished_lot_id": target_finished_lot_id,
        "scope": scope,
        "initiated_at": now,
        "deadline_at": None,
        "basis_weight_lbs": fl["total_weight_lbs"],
        "recovery_pct": None,
        "status": "INITIATED",
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    from db import iso_format
    re["deadline_at"] = iso_format(now_dt + timedelta(hours=24))
    store.recall_exercises[re["id"]] = re
    return success_object(recall_out(re), 201)


@bp.route("/recall-exercises/<rid>", methods=["GET"])
def get_recall(rid):
    require_roles(*READ_ROLES)
    re = store.recall_exercises.get(rid)
    if not re:
        raise_error(ERR_NOT_FOUND, "Recall exercise not found")
    return success_object(recall_out(re))


@bp.route("/recall-exercises", methods=["GET"])
def list_recalls():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    plant_id = request.args.get("plant_id")
    target_id = request.args.get("target_finished_lot_id")
    status = request.args.get("status")
    items = sorted(store.recall_exercises.values(), key=lambda r: (r["created_at"], r["id"]))
    if plant_id is not None:
        items = [r for r in items if r["plant_id"] == plant_id]
    if target_id is not None:
        items = [r for r in items if r["target_finished_lot_id"] == target_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([recall_out(r) for r in page], limit, offset, total)


@bp.route("/recall-exercises/<rid>/complete", methods=["POST"])
def complete_recall(rid):
    user_id, _ = require_roles("QAManager")
    body = get_body()
    reconciled_weight_lbs = req_number(body, "reconciled_weight_lbs", ge=0)
    re = store.recall_exercises.get(rid)
    if not re:
        raise_error(ERR_NOT_FOUND, "Recall exercise not found")
    if re["status"] != "INITIATED":
        raise_error(ERR_RECALL_ALREADY_COMPLETED, "Recall exercise already completed")

    now_dt = store.now()
    from db import parse_iso
    deadline = parse_iso(re["deadline_at"])
    basis = Decimal(str(re["basis_weight_lbs"]))
    reconciled = Decimal(str(reconciled_weight_lbs))
    capped = min(reconciled, basis)
    ratio = capped / basis if basis > 0 else Decimal("0")
    recovery_pct = round2(100 * capped / basis) if basis > 0 else 0

    within_deadline = now_dt <= deadline
    passed = within_deadline and (ratio >= RECALL_PASS_THRESHOLD)

    re["recovery_pct"] = recovery_pct
    re["completed_at"] = store.now_iso()
    re["status"] = "PASSED" if passed else "FAILED"
    touch(re)

    if not passed:
        create_noncompliance_record(
            plant_id=re["plant_id"],
            production_day_id=None,
            category="TRACEABILITY",
            severity="CRITICAL",
            created_by=user_id,
            description=f"Recall exercise failed: recovery_pct={recovery_pct}, deadline_at={re['deadline_at']}",
        )
    return success_object(recall_out(re))
