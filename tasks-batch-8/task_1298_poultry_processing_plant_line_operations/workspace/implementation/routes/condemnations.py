"""Condemnation records: record, certify, dispute, recertify."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_SOD_CONDEMNATION_SELF_CERTIFY,
    ERR_CONDEMNATION_COUNT_EXCEEDS_HUNG,
    ERR_INSUFFICIENT_PERMISSIONS,
)
from middleware import (
    require_roles,
    get_json_body,
    check_required,
    check_no_unknown,
    check_enum,
    check_int,
    check_string,
)
from response import success_object
from services.core import (
    new_entity,
    _touch,
    recompute_lot_aggregates,
    recompute_certified_yield_for_lot,
    apply_routing_flip,
    maybe_reconcile_run,
    lot_has_uncertified_records,
)
from services.serializers import serialize_condemnation

bp = Blueprint("condemnations", __name__)

ALL_ROLES = (
    "PlantManager", "ShiftSupervisor", "ReceivingClerk", "LineOperator",
    "QATechnician", "SanitationLead", "USDAInspector", "OrderPlanner",
)

CONDEMNATION_CODES = (
    "SEPTICEMIA", "AIR_SACCULITIS", "BRUISING", "CONTAMINATION", "MACHINE_DAMAGE",
)


@bp.route("/poultry/condemnation-records", methods=["POST"])
def create_condemnation():
    user_id, role = require_roles("QATechnician")
    body = get_json_body()
    check_no_unknown(body, {"line_run_id", "condemnation_code", "carcass_count"})
    check_required(body, ["line_run_id", "condemnation_code", "carcass_count"])
    check_string(body["line_run_id"], "line_run_id")
    check_enum(body["condemnation_code"], CONDEMNATION_CODES, "condemnation_code")
    check_int(body["carcass_count"], "carcass_count", min_value=1)

    run = db.line_runs.get(body["line_run_id"])
    if not run:
        raise ApiError(ERR_NOT_FOUND, "Line run not found", 404)
    if run["status"] not in ("COMPLETED", "RECONCILED"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Condemnation coding requires a COMPLETED or RECONCILED run",
            409,
        )

    record = new_entity()
    record.update({
        "line_run_id": run["id"],
        "condemnation_code": body["condemnation_code"],
        "carcass_count": body["carcass_count"],
        "amended_carcass_count": None,
        "effective_count": body["carcass_count"],
        "recorded_by_user_id": user_id,
        "certified_by_user_id": None,
        "status": "DRAFT",
    })
    db.condemnation_records[record["id"]] = record

    # DRAFT counts feed the provisional yield; recompute lot aggregates
    lot = db.flock_lots.get(run["flock_lot_id"])
    if lot:
        recompute_lot_aggregates(lot)
        _touch(lot)
    _touch(run)

    return success_object(serialize_condemnation(record), 201)


@bp.route("/poultry/condemnation-records/<record_id>", methods=["GET"])
def get_condemnation(record_id):
    require_roles(*ALL_ROLES)
    record = db.condemnation_records.get(record_id)
    if not record:
        raise ApiError(ERR_NOT_FOUND, "Condemnation record not found", 404)
    return success_object(serialize_condemnation(record))


@bp.route("/poultry/condemnation-records/<record_id>/advance", methods=["POST"])
def advance_condemnation(record_id):
    user_id, role = require_roles("USDAInspector", "PlantManager")
    record = db.condemnation_records.get(record_id)
    if not record:
        raise ApiError(ERR_NOT_FOUND, "Condemnation record not found", 404)
    body = get_json_body()
    check_no_unknown(body, {"to_status", "amended_carcass_count", "reason"})
    check_required(body, ["to_status"])
    check_enum(body["to_status"], ("CERTIFIED", "DISPUTED"), "to_status")
    to_status = body["to_status"]

    if to_status == "CERTIFIED":
        if role != "USDAInspector":
            raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, "Role not permitted for this action", 403)
        if record["status"] not in ("DRAFT", "DISPUTED"):
            raise ApiError(
                ERR_INVALID_STATE_TRANSITION,
                "CERTIFIED permitted only from DRAFT or DISPUTED",
                409,
            )
        # PRD 3.4: only a recertify (DISPUTED->CERTIFIED) is a provisional-yield
        # recompute trigger, and only while condemnations remain uncertified.
        was_recertify = record["status"] == "DISPUTED"
        # Optional amendment on recertify
        amended = body.get("amended_carcass_count")
        if amended is not None:
            check_int(amended, "amended_carcass_count", min_value=1)
            record["amended_carcass_count"] = amended

        # SoD: certifier != recorder (priority 5, before the count gate)
        if user_id == record["recorded_by_user_id"]:
            raise ApiError(
                ERR_SOD_CONDEMNATION_SELF_CERTIFY,
                "Condemnation record certified by its recorder",
                403,
            )

        # Certification gate: sum(CERTIFIED effective) + this effective <= birds_hung
        run = db.line_runs.get(record["line_run_id"])
        if not run:
            raise ApiError(ERR_NOT_FOUND, "Line run not found", 404)
        this_effective = (
            record["amended_carcass_count"]
            if record.get("amended_carcass_count") is not None
            else record["carcass_count"]
        )
        certified_sum = 0
        for c in db.condemnation_records.values():
            if c["line_run_id"] == run["id"] and c["status"] == "CERTIFIED":
                eff = c.get("effective_count")
                if eff is None:
                    eff = c["amended_carcass_count"] if c.get("amended_carcass_count") is not None else c["carcass_count"]
                certified_sum += eff
        if certified_sum + this_effective > (run.get("birds_hung") or 0):
            raise ApiError(
                ERR_CONDEMNATION_COUNT_EXCEEDS_HUNG,
                "Certified condemnation totals would exceed birds hung",
                422,
            )

        record["status"] = "CERTIFIED"
        record["effective_count"] = this_effective
        record["certified_by_user_id"] = user_id
        _touch(record)

        # Cascade chain
        lot = db.flock_lots.get(run["flock_lot_id"])
        # link 1+2: aggregates + auto-reconcile. First certification is not a
        # PRD 3.4 provisional-yield trigger; a recertify is, while uncertified
        # records remain.
        if lot:
            recompute_lot_aggregates(
                lot,
                recompute_provisional=(
                    was_recertify and lot_has_uncertified_records(lot)
                ),
            )
        _touch(run)
        maybe_reconcile_run(run)
        # link 3: lot certified yield if SETTLED|REOPENED
        if lot:
            if lot["status"] in ("SETTLED", "REOPENED"):
                old, new = recompute_certified_yield_for_lot(lot)
                _touch(lot)
                # link 4: routing flip on decrease
                apply_routing_flip(lot, old, new)
            else:
                _touch(lot)
    else:  # DISPUTED
        if role != "PlantManager":
            raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, "Role not permitted for this action", 403)
        if record["status"] != "CERTIFIED":
            raise ApiError(
                ERR_INVALID_STATE_TRANSITION, "DISPUTED permitted only from CERTIFIED", 409
            )
        reason = body.get("reason")
        if not isinstance(reason, str) or not reason:
            raise ApiError(ERR_INVALID_REQUEST, "reason is required", 400)

        record["status"] = "DISPUTED"
        _touch(record)

        # Compensating bookkeeping: DISPUTED excluded from condemned_accounted;
        # RECONCILED state retained; lot aggregates recomputed; certified yield
        # recomputed when the lot is SETTLED|REOPENED, with routing flip.
        run = db.line_runs.get(record["line_run_id"])
        lot = db.flock_lots.get(run["flock_lot_id"]) if run else None
        if run:
            _touch(run)
        if lot:
            old_cert = lot.get("certified_yield_pct")
            recompute_lot_aggregates(lot)
            if lot["status"] in ("SETTLED", "REOPENED"):
                old, new = recompute_certified_yield_for_lot(lot)
                _touch(lot)
                apply_routing_flip(lot, old, new)
            else:
                _touch(lot)

    return success_object(serialize_condemnation(record))


