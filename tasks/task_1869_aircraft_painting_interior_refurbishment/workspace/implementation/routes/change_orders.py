"""ChangeOrder endpoints (DRAFT->SUBMITTED->APPROVED/REJECTED/COUNTERED->DRAFT)."""
from flask import Blueprint, request

from db import STORE, new_id, next_seq, now_iso
from domain import (new_entity, bump, bump_program, regen_draft_invoices,
                    get_or_404, by_created, serialize_change_order)
from errors import (ApiError, ref_integrity, invalid_state,
                    ERR_FORBIDDEN_OWNERSHIP, ERR_STALE_PROGRAM_VERSION)
from middleware import auth
from response import success
from validation import get_body, field, paginate

bp = Blueprint("change_orders", __name__)

KINDS = ("SCOPE", "WEIGHT_ACK")


def _ownership_check(user_id, prog):
    if user_id != prog["customer_id"]:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                       "X-User-ID does not match the program's customer_id")


def _next_event_seq(program_id):
    seqs = [e["event_seq"] for e in STORE.delay_events.values()
            if e["program_id"] == program_id]
    return (max(seqs) + 1) if seqs else 1


def _check_weight_ack(program_id, kind, ack_id):
    if kind == "WEIGHT_ACK":
        if not ack_id:
            raise ref_integrity(
                "kind WEIGHT_ACK requires acknowledges_weight_record_id")
    if ack_id is not None:
        rec = STORE.weight_records.get(ack_id)
        if rec is None or rec["program_id"] != program_id:
            raise ref_integrity(
                "acknowledges_weight_record_id must reference a weight record "
                "of the same program")


@bp.post("/change-orders")
def create_change_order():
    auth("ProgramManager")
    data = get_body(required=True)
    program_id = field(data, "program_id", "str")
    delta_price_cents = field(data, "delta_price_cents", "int")
    description = field(data, "description", "str")
    kind = field(data, "kind", "str", required=False, enum=KINDS, default="SCOPE")
    delta_days = field(data, "delta_days", "int", required=False, default=0)
    ack_id = field(data, "acknowledges_weight_record_id", "str",
                   required=False, default=None)
    if program_id not in STORE.programs:
        raise ref_integrity("program_id does not reference an existing program")
    _check_weight_ack(program_id, kind, ack_id)
    co = new_entity()
    co.update({
        "program_id": program_id,
        "kind": kind,
        "delta_price_cents": delta_price_cents,
        "delta_days": delta_days,
        "description": description,
        "acknowledges_weight_record_id": ack_id,
        "status": "DRAFT",
        "counter_note": None,
        "negotiation_round": 1,
    })
    STORE.change_orders[co["id"]] = co
    return success(serialize_change_order(co), status=201)


@bp.get("/change-orders/<cid>")
def get_change_order(cid):
    auth()
    co = get_or_404(STORE.change_orders, cid, "ChangeOrder")
    return success(serialize_change_order(co))


@bp.get("/change-orders")
def list_change_orders():
    auth()
    items = by_created(list(STORE.change_orders.values()))
    for key in ("program_id", "status", "acknowledges_weight_record_id"):
        value = request.args.get(key)
        if value is not None:
            items = [c for c in items if c[key] == value]
    return paginate(items, serialize_change_order)


@bp.post("/change-orders/<cid>/submit")
def submit_change_order(cid):
    auth("ProgramManager")
    co = get_or_404(STORE.change_orders, cid, "ChangeOrder")
    if co["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT change order can be submitted")
    prog = STORE.programs[co["program_id"]]
    if prog["status"] in ("DELIVERED", "CANCELLED"):
        raise invalid_state("Cannot submit a change order for a terminal program")
    _check_weight_ack(co["program_id"], co["kind"], co["acknowledges_weight_record_id"])
    co["status"] = "SUBMITTED"
    bump(co)
    return success(serialize_change_order(co))


@bp.post("/change-orders/<cid>/approve")
def approve_change_order(cid):
    user_id, _ = auth("CustomerRep")
    data = get_body(required=True)
    expected = field(data, "expected_program_version", "int")
    co = get_or_404(STORE.change_orders, cid, "ChangeOrder")
    prog = STORE.programs[co["program_id"]]
    _ownership_check(user_id, prog)
    if expected != prog["version"]:
        raise ApiError(ERR_STALE_PROGRAM_VERSION, 412,
                       "expected_program_version does not match the program version")
    if co["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED change order can be approved")
    co["status"] = "APPROVED"
    bump(co)
    # Cascade link 2: positive delta_days manufactures an already-CONFIRMED
    # CUSTOMER_CAUSED DelayEvent (its impact_days carry the date shift used by
    # the derived committed_delivery_date — link 1).
    if co["delta_days"] > 0:
        event = new_entity()
        event.update({
            "program_id": prog["id"],
            "category": "CUSTOMER_CAUSED",
            "impact_days": co["delta_days"],
            "reason": co["description"],
            "source": "CHANGE_ORDER",
            "status": "CONFIRMED",
            "event_seq": _next_event_seq(prog["id"]),
        })
        STORE.delay_events[event["id"]] = event
    bump_program(prog)
    # Cascade link 3: DRAFT invoices regenerate computed lines.
    regen_draft_invoices(prog["id"])
    return success(serialize_change_order(co))


@bp.post("/change-orders/<cid>/reject")
def reject_change_order(cid):
    user_id, _ = auth("CustomerRep")
    co = get_or_404(STORE.change_orders, cid, "ChangeOrder")
    prog = STORE.programs[co["program_id"]]
    _ownership_check(user_id, prog)
    if co["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED change order can be rejected")
    co["status"] = "REJECTED"
    bump(co)
    return success(serialize_change_order(co))


@bp.post("/change-orders/<cid>/counter")
def counter_change_order(cid):
    user_id, _ = auth("CustomerRep")
    data = get_body(required=True)
    counter_note = field(data, "counter_note", "str")
    co = get_or_404(STORE.change_orders, cid, "ChangeOrder")
    prog = STORE.programs[co["program_id"]]
    _ownership_check(user_id, prog)
    if co["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED change order can be countered")
    co["counter_note"] = counter_note
    co["status"] = "COUNTERED"
    bump(co)
    return success(serialize_change_order(co))


@bp.post("/change-orders/<cid>/revise")
def revise_change_order(cid):
    auth("ProgramManager")
    data = get_body()
    delta_price = field(data, "delta_price_cents", "int", required=False, default=None)
    delta_days = field(data, "delta_days", "int", required=False, default=None)
    description = field(data, "description", "str", required=False, default=None)
    co = get_or_404(STORE.change_orders, cid, "ChangeOrder")
    if co["status"] != "COUNTERED":
        raise invalid_state("Only a COUNTERED change order can be revised")
    if delta_price is not None:
        co["delta_price_cents"] = delta_price
    if delta_days is not None:
        co["delta_days"] = delta_days
    if description is not None:
        co["description"] = description
    co["negotiation_round"] += 1
    co["status"] = "DRAFT"
    bump(co)
    return success(serialize_change_order(co))
