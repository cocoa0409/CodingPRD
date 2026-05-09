"""Equipment registration, events, and decommission."""
import copy
from flask import Blueprint, g, request

import errors as E
from db import store, init_common, init_append_only, touch
from middleware import require_roles, parse_pagination
from response import ok_object, ok_array
from body import get_json_body, require_string, require_enum, require_int
from services.occ import check_version
from services.audit import log as audit_log
from services.budget import find_category, recompute_posture
from services.serializers import serialize_equipment, serialize_equipment_event, paginate


bp = Blueprint("equipment", __name__)


CATEGORIES = {"CAMERA", "LIGHTING", "SOUND", "GRIP", "WARDROBE", "PROPS", "MISC"}
ACQUISITION_MODES = {"RENTAL", "PURCHASE"}
EQUIPMENT_STATUSES = {"AVAILABLE", "CHECKED_OUT", "DAMAGED", "LOST", "RETURNED", "DECOMMISSIONED"}
EVENT_TYPES = {"CHECK_OUT", "CHECK_IN", "REPORT_DAMAGE", "REPORT_LOSS", "RETURN_VERIFIED"}


def _get_equipment(eid):
    e = store.equipment.get(eid)
    if not e:
        E.not_found(f"Equipment {eid} not found")
    return e


@bp.route("/equipment", methods=["POST"])
@require_roles("ProductionCoordinator")
def create_equipment():
    body = get_json_body()
    name = require_string(body, "name")
    category = require_enum(body, "category", CATEGORIES)
    mode = require_enum(body, "acquisition_mode", ACQUISITION_MODES)
    vendor = require_string(body, "vendor_id")
    cost = require_int(body, "unit_cost_cents", minv=0)
    rec = {
        "name": name,
        "category": category,
        "acquisition_mode": mode,
        "vendor_id": vendor,
        "unit_cost_cents": cost,
        "status": "AVAILABLE",
        "last_check_event_id": None,
    }
    init_common(rec)
    store.equipment[rec["id"]] = rec
    return ok_object(serialize_equipment(rec), http_status=201)


@bp.route("/equipment", methods=["GET"])
@require_roles("ProductionCoordinator", "LineProducer", "FinanceController")
def list_equipment():
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    category_filter = request.args.get("category")
    items = list(store.equipment.values())
    if status_filter:
        if status_filter not in EQUIPMENT_STATUSES:
            E.validation_err("Invalid status filter")
        items = [i for i in items if i["status"] == status_filter]
    if category_filter:
        if category_filter not in CATEGORIES:
            E.validation_err("Invalid category filter")
        items = [i for i in items if i["category"] == category_filter]
    page, total, has_more = paginate(items, limit, offset)
    return ok_array(
        [serialize_equipment(e) for e in page], limit, offset, total, has_more
    )


def _last_event_for(equipment_id):
    """Return the most-recent event by insertion order for a given equipment.

    We rely on dict insertion order (preserved in Python 3.7+) instead of
    sorting by created_at — when two events happen within the same logical-
    clock millisecond the created_at strings tie, and a UUID-based tiebreaker
    would scramble the order. Insertion order matches the actual mutation
    sequence in this in-memory store and is the authoritative ordering.
    """
    last = None
    for e in store.equipment_events.values():
        if e["equipment_id"] == equipment_id:
            last = e
    return last


def _previous_check_out_event(equipment_id):
    """Find the most-recent CHECK_OUT event by insertion order."""
    last = None
    for e in store.equipment_events.values():
        if e["equipment_id"] == equipment_id and e["event_type"] == "CHECK_OUT":
            last = e
    return last


@bp.route("/equipment/<eid>/events", methods=["POST"])
@require_roles("ProductionCoordinator", "FinanceController")
def create_equipment_event(eid):
    body = get_json_body()
    with store.lock:
        eq = _get_equipment(eid)
        production_id = require_string(body, "production_id")
        event_type = require_enum(body, "event_type", EVENT_TYPES)
        occurred_at = require_string(body, "occurred_at")
        damage_charge = body.get("damage_charge_cents", 0)
        if damage_charge is None:
            damage_charge = 0
        if not isinstance(damage_charge, int) or isinstance(damage_charge, bool) or damage_charge < 0:
            E.invalid_event_payload("damage_charge_cents must be non-negative integer")

        prod = store.productions.get(production_id)
        if not prod:
            E.reference_mismatch("Production not found")
        if prod.get("posture") == "FROZEN":
            E.posture_blocked("Production posture is FROZEN")

        # Role-based event_type restrictions:
        # ProductionCoordinator can do CHECK_OUT/CHECK_IN/REPORT_DAMAGE/REPORT_LOSS
        # FinanceController can do RETURN_VERIFIED
        if g.role == "ProductionCoordinator" and event_type == "RETURN_VERIFIED":
            E.forbidden("ProductionCoordinator cannot record RETURN_VERIFIED")
        if g.role == "FinanceController" and event_type in {
            "CHECK_OUT", "CHECK_IN", "REPORT_DAMAGE", "REPORT_LOSS"
        }:
            E.forbidden("FinanceController cannot record CHECK_OUT/CHECK_IN/REPORT_DAMAGE/REPORT_LOSS")

        # Damage charge payload validation (priority 17)
        if event_type in {"REPORT_DAMAGE", "REPORT_LOSS"}:
            if damage_charge <= 0:
                E.invalid_event_payload("damage_charge_cents must be > 0 for damage/loss")
        elif event_type in {"CHECK_OUT", "CHECK_IN", "RETURN_VERIFIED"}:
            if damage_charge != 0:
                E.invalid_event_payload("damage_charge_cents must be 0 for non-damage/loss events")

        # State transitions
        eq_cat = find_category(production_id, "EQUIPMENT")

        if event_type == "CHECK_OUT":
            if eq["status"] != "AVAILABLE":
                E.equipment_unavailable("Equipment is not AVAILABLE")
            if prod["status"] not in {"PLANNING", "IN_PRODUCTION"}:
                E.invalid_state("Production must be PLANNING or IN_PRODUCTION")
            eq["status"] = "CHECKED_OUT"
            touch(eq)
            if eq.get("acquisition_mode") == "RENTAL" and eq_cat is not None:
                eq_cat["committed_cents"] = eq_cat.get("committed_cents", 0) + eq["unit_cost_cents"]
                touch(eq_cat)
        elif event_type == "CHECK_IN":
            if eq["status"] != "CHECKED_OUT":
                E.invalid_state("CHECK_IN requires CHECKED_OUT")
            eq["status"] = "AVAILABLE"
            touch(eq)
            if eq.get("acquisition_mode") == "RENTAL" and eq_cat is not None:
                eq_cat["committed_cents"] = eq_cat.get("committed_cents", 0) - eq["unit_cost_cents"]
                eq_cat["actual_cents"] = eq_cat.get("actual_cents", 0) + eq["unit_cost_cents"]
                touch(eq_cat)
        elif event_type == "REPORT_DAMAGE":
            if eq["status"] != "CHECKED_OUT":
                E.invalid_state("REPORT_DAMAGE requires CHECKED_OUT")
            eq["status"] = "DAMAGED"
            touch(eq)
            if eq_cat is not None:
                eq_cat["committed_cents"] = eq_cat.get("committed_cents", 0) + damage_charge
                touch(eq_cat)
        elif event_type == "REPORT_LOSS":
            if eq["status"] != "CHECKED_OUT":
                E.invalid_state("REPORT_LOSS requires CHECKED_OUT")
            eq["status"] = "LOST"
            touch(eq)
            if eq_cat is not None:
                eq_cat["committed_cents"] = eq_cat.get("committed_cents", 0) + damage_charge
                touch(eq_cat)
        elif event_type == "RETURN_VERIFIED":
            if eq["status"] not in {"DAMAGED", "LOST"}:
                E.invalid_state("RETURN_VERIFIED requires DAMAGED or LOST")
            prev = _last_event_for(eid)
            if not prev or prev["event_type"] not in {"REPORT_DAMAGE", "REPORT_LOSS"}:
                E.invalid_state("Previous event must be REPORT_DAMAGE or REPORT_LOSS")
            # Find related vendor invoice
            invoice = None
            for v in store.vendor_invoices.values():
                if (v.get("vendor_id") == eq["vendor_id"]
                    and v.get("production_id") == production_id
                    and v["status"] == "SUBMITTED"):
                    invoice = v
                    break
            if invoice is None:
                E.invalid_state("No matching SUBMITTED vendor invoice for vendor")
            charge = prev["damage_charge_cents"]
            invoice["deduction_cents"] = invoice.get("deduction_cents", 0) + charge
            touch(invoice)
            if eq_cat is not None:
                eq_cat["committed_cents"] = eq_cat.get("committed_cents", 0) - charge
                touch(eq_cat)
            eq["status"] = "RETURNED"
            touch(eq)

        rec = {
            "equipment_id": eid,
            "production_id": production_id,
            "event_type": event_type,
            "occurred_at": occurred_at,
            "actor_user_id": g.user_id,
            "damage_charge_cents": damage_charge,
        }
        init_append_only(rec)
        store.equipment_events[rec["id"]] = rec
        eq["last_check_event_id"] = rec["id"]
        touch(eq)

        # Audit log for damage/loss/return events
        if event_type in {"REPORT_DAMAGE", "REPORT_LOSS", "RETURN_VERIFIED"}:
            audit_log(
                production_id=production_id, actor_user_id=g.user_id,
                action="EQUIPMENT_LOSS", subject_entity="Equipment", subject_id=eid,
                before=None, after=copy.deepcopy(eq),
            )
        # Recompute posture (potentially RED if EQUIPMENT category went OVER)
        if eq_cat is not None:
            recompute_posture(prod, actor_user_id=g.user_id)
        return ok_object(serialize_equipment_event(rec), http_status=201)


@bp.route("/equipment/<eid>/decommission", methods=["POST"])
@require_roles("FinanceController")
def decommission_equipment(eid):
    body = get_json_body()
    with store.lock:
        eq = _get_equipment(eid)
        check_version(eq, body)
        if eq["status"] != "AVAILABLE":
            E.invalid_state("decommission requires AVAILABLE")
        last = _last_event_for(eid)
        if last is not None and last["event_type"] not in {"CHECK_IN", "RETURN_VERIFIED"}:
            E.invalid_state("Cannot decommission: last event must be CHECK_IN or RETURN_VERIFIED")
        eq["status"] = "DECOMMISSIONED"
        touch(eq)
        return ok_object(serialize_equipment(eq))
