"""Supplier engagements for scope 3 data (PRD 3.5)."""
from flask import Blueprint, g, request

import calc
import domain
from envelope import ok, ok_list
from errors import err, invalid_state, not_found, unauthorized
from http_util import (
    ANALYST,
    ENGAGEMENT_READ_ROLES,
    SUPPLIER,
    get_body,
    parse_pagination,
    require_roles,
    v_datetime,
    v_enum,
    v_num,
    v_str,
)
from store import db, new_entity, now_iso, touch

bp = Blueprint("engagements", __name__, url_prefix="/sustainability")

CATEGORIES = {"PURCHASED_GOODS", "CAPITAL_GOODS", "UPSTREAM_TRANSPORT"}
DECISIONS = {"ACCEPT", "REQUEST_REVISION", "REINVITE"}

COLLECTING = ("DATA_COLLECTION", "UNDER_REVIEW")


def load_engagement(engagement_id):
    eng = db.engagements.get(engagement_id)
    if eng is None:
        raise not_found(f"SupplierEngagement {engagement_id} not found")
    return eng


@bp.route("/supplier-engagements", methods=["POST"])
@require_roles(ANALYST)
def create_engagement():
    body = get_body()
    # Priority 3: body FK.
    cid = body.get("cycle_id")
    if cid is not None and (not isinstance(cid, str) or cid not in db.cycles):
        raise not_found("Field cycle_id does not resolve to an existing resource")
    # Priority 4: request shape.
    cycle = db.cycles[v_str(body, "cycle_id")]
    supplier_name = v_str(body, "supplier_name")
    category = v_enum(body, "category", CATEGORIES)
    spend_usd = v_num(body, "spend_usd", gte=0)
    contact_user_id = v_str(body, "contact_user_id")
    due_raw, due_dt = v_datetime(body, "due_date")
    eng = new_entity(
        {
            "cycle_id": cycle["id"],
            "supplier_name": supplier_name,
            "category": category,
            "spend_usd": spend_usd,
            "contact_user_id": contact_user_id,
            "due_date": due_raw,
            "status": "INVITED",
            "round": 1,
            "supplier_tco2e": None,
            "responded_at": None,
            "_due_dt": due_dt,
        }
    )
    db.engagements[eng["id"]] = eng
    return ok(domain.ser_engagement(eng), status=201)


@bp.route("/supplier-engagements/<engagement_id>", methods=["GET"])
@require_roles(*ENGAGEMENT_READ_ROLES)
def get_engagement(engagement_id):
    return ok(domain.ser_engagement(load_engagement(engagement_id)))


@bp.route("/supplier-engagements", methods=["GET"])
@require_roles(*ENGAGEMENT_READ_ROLES)
def list_engagements():
    limit, offset = parse_pagination()
    items = sorted(db.engagements.values(), key=lambda x: x["_seq"])
    cycle_id = request.args.get("cycle_id")
    status = request.args.get("status")
    if cycle_id is not None:
        items = [e for e in items if e["cycle_id"] == cycle_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([domain.ser_engagement(e) for e in page], limit, offset, total)


@bp.route("/supplier-engagements/<engagement_id>/respond", methods=["POST"])
@require_roles(SUPPLIER)
def respond(engagement_id):
    # Priority 3: path existence (needed before the ownership comparison).
    eng = load_engagement(engagement_id)
    # Priority 2: the caller must be the engagement's registered contact.
    if g.user_id != eng["contact_user_id"]:
        raise unauthorized("X-User-ID does not match the engagement's contact_user_id")
    # Priority 4: request shape.
    body = get_body()
    supplier_tco2e = v_num(body, "supplier_tco2e")
    # Priority 6: from-state gate (INVITED or NEEDS_REVISION).
    if eng["status"] not in ("INVITED", "NEEDS_REVISION"):
        raise invalid_state(
            f"SupplierEngagement in status {eng['status']} cannot be responded to"
        )
    eng["supplier_tco2e"] = supplier_tco2e
    eng["responded_at"] = now_iso()
    eng["status"] = "RESPONDED"
    # Lighter tier of the staleness propagation: inventory STALE, nothing more.
    cycle = db.cycles[eng["cycle_id"]]
    calc.mark_inventory_stale(cycle)
    touch(eng)
    touch(cycle)
    return ok(domain.ser_engagement(eng))


@bp.route("/supplier-engagements/<engagement_id>/decision", methods=["POST"])
@require_roles(ANALYST)
def decide(engagement_id):
    eng = load_engagement(engagement_id)
    body = get_body()
    decision = v_enum(body, "decision", DECISIONS)
    # Priority 6: from-state gate.
    legal_from = {
        "ACCEPT": "RESPONDED",
        "REQUEST_REVISION": "RESPONDED",
        "REINVITE": "NEEDS_REVISION",
    }[decision]
    if eng["status"] != legal_from:
        raise invalid_state(
            f"SupplierEngagement in status {eng['status']} does not accept decision {decision}"
        )
    # Priority 6: parent-cycle gate.
    cycle = db.cycles[eng["cycle_id"]]
    if cycle["status"] not in COLLECTING:
        raise err(
            "ERR_CYCLE_NOT_COLLECTING",
            409,
            f"Cycle in status {cycle['status']} does not permit engagement decisions",
        )
    if decision == "ACCEPT":
        eng["status"] = "ACCEPTED"
        # Full three-link staleness cascade; both versions advance.
        calc.cascade_staleness(cycle)
        touch(eng)
        touch(cycle)
    elif decision == "REQUEST_REVISION":
        eng["status"] = "NEEDS_REVISION"
        touch(eng)
    else:  # REINVITE — cyclic negotiation loop, round += 1
        eng["status"] = "INVITED"
        eng["round"] += 1
        touch(eng)
    return ok(domain.ser_engagement(eng))
