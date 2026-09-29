"""Substitution proposals and quality adjudication (PRD §3.8)."""
from flask import Blueprint

import calc
import domain
import envelope
import serialize
import store
import validate as v
from auth import authenticate
from common import fk_lookup, path_lookup
from errors import fail
from store import D, lb

bp = Blueprint("subs", __name__)

SUB_STATES = ("REQUESTED", "UNDER_REVIEW", "REVISION_REQUESTED",
              "APPROVED", "REJECTED", "WITHDRAWN")
OPEN_STATES = ("REQUESTED", "REVISION_REQUESTED")
READ_ROLES = ("TechnicalSpecialist", "QualityManager", "AccountManager",
              "PricingController", "PlatformAdmin")


def _parent_order(request_rec):
    line = store.get("order_lines", request_rec["order_line_id"])
    if line is None:
        return None, None
    return store.get("orders", line["order_id"]), line


def _require_sod(actor, rec):
    if actor.user_id == rec["requested_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The adjudicating quality manager may not be the requesting specialist")


def _require_requester(actor, rec):
    if actor.user_id != rec["requested_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "Only the originating specialist may perform this action")


def _require_parent_open(rec):
    order, line = _parent_order(rec)
    if order is None:
        fail("ERR_RELATED_ENTITY_STATE_INVALID", "The parent order no longer exists")
    if order["fulfillment_status"] not in ("NEW", "ALLOCATED"):
        fail("ERR_RELATED_ENTITY_STATE_INVALID",
             "The parent order is %s and is beyond substitution"
             % order["fulfillment_status"])
    return order, line


@bp.post("/substitution-requests")
def create_request():
    actor = authenticate(("TechnicalSpecialist",))
    body = v.body()
    order_line_id = v.string(body, "order_line_id", min_len=1)
    proposed_product_id = v.string(body, "proposed_product_id", min_len=1)
    rationale = v.string(body, "rationale", min_len=1, max_len=500)
    expected_version = v.integer(body, "expected_order_version", minimum=0)
    supplied_order_id = v.string(body, "order_id", required=False, default=None)
    line = fk_lookup("order_lines", order_line_id)
    fk_lookup("products", proposed_product_id)
    if supplied_order_id is not None:
        fk_lookup("orders", supplied_order_id)
    order = store.get("orders", line["order_id"])
    if order is None or order["version"] != expected_version:
        fail("ERR_STALE_ORDER_VERSION",
             "expected_order_version %s does not match the current order version"
             % expected_version)
    if supplied_order_id is not None and supplied_order_id != line["order_id"]:
        fail("ERR_ENTITY_LINK_MISMATCH",
             "The order line belongs to a different order than the one supplied")
    for other in store.sort_created(store.all_of("subs")):
        if other["order_line_id"] != order_line_id:
            continue
        if other["status"] not in OPEN_STATES:
            continue
        other["status"] = "WITHDRAWN"
        store.bump(other)
    rec = store.base_record()
    rec.update({
        "order_line_id": order_line_id,
        "proposed_product_id": proposed_product_id,
        "rationale": rationale,
        "status": "REQUESTED",
        "revision_round": 0,
        "requested_by_user_id": actor.user_id,
        "decided_by_user_id": None,
    })
    store.insert("subs", rec)
    store.bump(order)
    return envelope.created(serialize.substitution(rec))


@bp.get("/substitution-requests")
def list_requests():
    authenticate(READ_ROLES)
    limit, offset = v.pagination()
    order_line_id = v.q_str("order_line_id")
    proposed_product_id = v.q_str("proposed_product_id")
    status = v.q_enum("status", SUB_STATES)
    rows = [r for r in store.all_of("subs")
            if (order_line_id is None or r["order_line_id"] == order_line_id)
            and (proposed_product_id is None
                 or r["proposed_product_id"] == proposed_product_id)
            and (status is None or r["status"] == status)]
    rows = store.sort_created(rows)
    data, total = v.page(rows, limit, offset, serialize.substitution)
    return envelope.listing(data, limit, offset, total)


@bp.get("/substitution-requests/<rid>")
def read_request(rid):
    authenticate(READ_ROLES)
    return envelope.ok(serialize.substitution(path_lookup("subs", rid)))


@bp.post("/substitution-requests/<rid>/claim")
def claim_request(rid):
    actor = authenticate(("QualityManager",))
    v.body()
    rec = path_lookup("subs", rid)
    if rec["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A request in %s cannot be claimed" % rec["status"])
    _require_parent_open(rec)
    _require_sod(actor, rec)
    rec["status"] = "UNDER_REVIEW"
    rec["decided_by_user_id"] = actor.user_id
    store.bump(rec)
    return envelope.ok(serialize.substitution(rec))


@bp.post("/substitution-requests/<rid>/request-revision")
def request_revision(rid):
    authenticate(("QualityManager",))
    body = v.body()
    v.string(body, "revision_note", min_len=1, max_len=500)
    rec = path_lookup("subs", rid)
    if rec["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A request in %s cannot be sent back for revision" % rec["status"])
    if rec["revision_round"] >= 2:
        fail("ERR_ROUND_LIMIT_REACHED", "The revision round cap has been reached")
    rec["status"] = "REVISION_REQUESTED"
    rec["decided_by_user_id"] = None
    store.bump(rec)
    return envelope.ok(serialize.substitution(rec))


@bp.post("/substitution-requests/<rid>/resubmit")
def resubmit_request(rid):
    actor = authenticate(("TechnicalSpecialist",))
    body = v.body()
    proposed_product_id = v.string(body, "proposed_product_id", min_len=1)
    rationale = v.string(body, "rationale", min_len=1, max_len=500)
    rec = path_lookup("subs", rid)
    fk_lookup("products", proposed_product_id)
    if rec["status"] != "REVISION_REQUESTED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A request in %s cannot be resubmitted" % rec["status"])
    _require_requester(actor, rec)
    rec["status"] = "REQUESTED"
    rec["revision_round"] += 1
    rec["proposed_product_id"] = proposed_product_id
    rec["rationale"] = rationale
    store.bump(rec)
    return envelope.ok(serialize.substitution(rec))


@bp.post("/substitution-requests/<rid>/withdraw")
def withdraw_request(rid):
    actor = authenticate(("TechnicalSpecialist",))
    v.body()
    rec = path_lookup("subs", rid)
    if rec["status"] not in OPEN_STATES:
        fail("ERR_INVALID_STATE_TRANSITION",
             "A request in %s cannot be withdrawn" % rec["status"])
    _require_requester(actor, rec)
    rec["status"] = "WITHDRAWN"
    store.bump(rec)
    return envelope.ok(serialize.substitution(rec))


@bp.post("/substitution-requests/<rid>/reject")
def reject_request(rid):
    actor = authenticate(("QualityManager",))
    body = v.body()
    v.string(body, "decision_note", required=False, max_len=500)
    rec = path_lookup("subs", rid)
    if rec["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A request in %s cannot be rejected" % rec["status"])
    _require_sod(actor, rec)
    rec["status"] = "REJECTED"
    rec["decided_by_user_id"] = actor.user_id
    store.bump(rec)
    return envelope.ok(serialize.substitution(rec))


@bp.post("/substitution-requests/<rid>/approve")
def approve_request(rid):
    actor = authenticate(("QualityManager",))
    body = v.body()
    v.string(body, "decision_note", required=False, max_len=500)
    rec = path_lookup("subs", rid)
    if rec["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A request in %s cannot be approved" % rec["status"])
    order, line = _require_parent_open(rec)
    if order["pricing_status"] == "INVOICED":
        fail("ERR_RELATED_ENTITY_STATE_INVALID",
             "An INVOICED order is closed to substitution")
    _require_sod(actor, rec)
    customer = store.get("customers", order["customer_id"])
    new_product = store.get("products", rec["proposed_product_id"])
    if new_product is None:
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND", "The proposed product no longer exists")
    domain.check_allergen_program(customer, new_product)

    was_reserved = line["allocation_status"] == "RESERVED"
    old_lot = store.get("lots", line["lot_id"]) if line["lot_id"] else None
    replacement = None
    if was_reserved:
        probe = dict(line)
        probe["product_id"] = new_product["id"]
        override = {}
        if old_lot is not None:
            override[old_lot["id"]] = (D(old_lot["quantity_on_hand_lb"])
                                       + D(line["quantity_lb"]))
        replacement = calc.select_lot(probe, on_hand_override=override)

    # HOP 1 - rewrite the line's SKU
    line["substituted_from_product_id"] = line["product_id"]
    line["product_id"] = new_product["id"]
    store.bump(line)

    # HOP 2 - release the old reservation and re-pick under FEFO
    zones = {}
    if was_reserved:
        qty = D(line["quantity_lb"])
        if old_lot is not None:
            old_lot["quantity_reserved_lb"] = lb(D(old_lot["quantity_reserved_lb"]) - qty)
            old_lot["quantity_on_hand_lb"] = lb(D(old_lot["quantity_on_hand_lb"]) + qty)
            store.bump(old_lot)
            zones[old_lot["zone_id"]] = store.get("zones", old_lot["zone_id"])
        line["allocation_status"] = "RELEASED"
        line["lot_id"] = None
        store.bump(line)
        replacement["quantity_on_hand_lb"] = lb(D(replacement["quantity_on_hand_lb"]) - qty)
        replacement["quantity_reserved_lb"] = lb(D(replacement["quantity_reserved_lb"]) + qty)
        store.bump(replacement)
        zones[replacement["zone_id"]] = store.get("zones", replacement["zone_id"])
        line["lot_id"] = replacement["id"]
        line["allocation_status"] = "RESERVED"
        if order["delivery_mode"] == "BULK":
            silo = calc.find_silo(order["customer_id"], new_product["id"])
            line["silo_id"] = silo["id"] if silo is not None else None
        store.bump(line)
        for zone in zones.values():
            calc.recompute_zone_on_hand(zone)

    rec["status"] = "APPROVED"
    rec["decided_by_user_id"] = actor.user_id
    store.bump(rec)

    # HOP 3 - reprice through the PROVISIONAL self-loop
    if order["pricing_status"] == "PROVISIONAL":
        per_line, totals = calc.price_order(order, "provisional_order_date")
        calc.apply_pricing(order, per_line, totals)
    store.bump(order)

    # HOP 4 - credit standing, HOP 5 - allergen risk
    calc.recompute_open_exposure(customer)
    calc.recompute_risk_score(customer, "exposure_provisional")
    return envelope.ok(serialize.substitution(rec))
