"""CullDecision routes (PRD §3.10)."""
from flask import Blueprint, request

import db
import errors
import serializers
import domain
from errors import err
from middleware import require_roles
from records import make_record, touch
from response import object_response, array_response
from domain import paginate, sorted_by_creation
import clock
import validators as V

bp = Blueprint("culls", __name__)

REASONS = {"LOW_PRODUCTION", "REPRO_FAILURE", "HIGH_SCC", "INJURY", "AGE"}
DISPOSITIONS = {"SLAUGHTER", "DAIRY_SALE", "DIED"}


@bp.route("/herds/cull-decisions", methods=["POST"])
@require_roles("HerdManager")
def create_cull_decision():
    body = V.require_json_object()
    animal_id = V.require_fk(body, "animal_id")
    reason = V.require_enum(body, "reason", REASONS)
    disposition = V.require_enum(body, "disposition", DISPOSITIONS)
    decided_at = V.require_datetime(body, "decided_at")
    replacement_animal_id = V.opt_str(body, "replacement_animal_id", default=None)
    # existence: animal then replacement
    animal = V.get_or_404("animal", animal_id)
    replacement = None
    if replacement_animal_id is not None:
        replacement = V.get_or_404("animal", replacement_animal_id)
    with db.lock:
        # state (priority 5): animal must be ACTIVE or DRY
        if animal["status"] not in ("ACTIVE", "DRY"):
            raise err(errors.ERR_ANIMAL_NOT_CULLABLE,
                      "Animal is not in a cullable state")
        # cross-herd referential (priority 8): replacement is a HEIFER in same herd
        if replacement is not None:
            if replacement["herd_id"] != animal["herd_id"]:
                raise err(errors.ERR_CROSS_HERD_REFERENCE,
                          "Replacement belongs to a different herd")
            if replacement["status"] != "HEIFER":
                raise err(errors.ERR_CROSS_HERD_REFERENCE,
                          "Replacement must be a HEIFER")
        # safety gate (priority 12): slaughter blocked by active meat withdrawal
        if disposition == "SLAUGHTER":
            now = clock.now()
            for t in db.health_treatments.values():
                if t["animal_id"] != animal_id:
                    continue
                if t["status"] != "ACTIVE":
                    continue
                if t["_meat_withdrawal_until_dt"] > now:
                    raise err(errors.ERR_MEAT_WITHDRAWAL_ACTIVE,
                              "An active meat-withdrawal window blocks slaughter")
        # execute cull
        rec = make_record({
            "animal_id": animal_id,
            "herd_id": animal["herd_id"],
            "reason": reason,
            "disposition": disposition,
            "replacement_animal_id": replacement_animal_id,
            "decided_at": body["decided_at"],
            "status": "EXECUTED",
        })
        db.cull_decisions[rec["id"]] = rec
        # animal terminal status
        animal["status"] = "DIED" if disposition == "DIED" else "CULLED"
        # close any OPEN/DRY lactation
        lac = domain.open_or_dry_lactation(animal_id)
        if lac is not None:
            lac["status"] = "CLOSED"
            touch(lac)
        animal["milk_eligible"] = False
        touch(animal)
        # herd active_animal_count recomputed (bump herd version)
        domain.bump_herd_for_count(animal["herd_id"])
        return object_response(serializers.cull_decision_out(rec), 201)


@bp.route("/herds/cull-decisions", methods=["GET"])
@require_roles("HerdManager", "CoopSettlementAgent", "Auditor")
def list_cull_decisions():
    items = list(db.cull_decisions.values())
    animal_id = request.args.get("animal_id")
    herd_id = request.args.get("herd_id")
    replacement_animal_id = request.args.get("replacement_animal_id")
    if animal_id is not None:
        items = [r for r in items if r["animal_id"] == animal_id]
    if herd_id is not None:
        items = [r for r in items if r["herd_id"] == herd_id]
    if replacement_animal_id is not None:
        items = [r for r in items if r.get("replacement_animal_id") == replacement_animal_id]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items, request.args)
    return array_response([serializers.cull_decision_out(r) for r in page], limit, offset, total)


@bp.route("/herds/cull-decisions/<cull_id>", methods=["GET"])
@require_roles("HerdManager", "CoopSettlementAgent", "Auditor")
def get_cull_decision(cull_id):
    if cull_id not in db.cull_decisions:
        raise err(errors.ERR_ANIMAL_NOT_FOUND, "cull decision not found")
    return object_response(serializers.cull_decision_out(db.cull_decisions[cull_id]), 200)
