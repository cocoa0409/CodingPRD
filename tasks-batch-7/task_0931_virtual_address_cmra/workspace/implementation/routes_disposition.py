"""Disposition requests and consolidated forwarding."""

from flask import Blueprint

import calc
import domain
import ladder as L
import serializers as S
import store
from errors import ApiError
from response import created, listing, ok, touch
from store import DB, insert
from util import CLOCK, DISPOSITION_RANK, STATUS_ENUMS

bp = Blueprint("disposition", __name__)


# ------------------------------------------------------------------ dispositions
@bp.post("/mail-items/<ident>/dispositions")
@L.endpoint(roles=["BoxHolder"], primary="mail_item", scope=True)
def create_disposition(item):
    b = L.body()
    L.req_present(b, "disposition_type")                            # rung 9
    L.req_int(b, "expected_mail_item_version", 0)
    dtype = L.enum_body(b, "disposition_type", "disposition_type")  # rung 10
    box = store.box_of_item(item)
    L.gate_a("dispositions_create", box)                            # rung 11
    L.gate_b("dispositions_create", box)                            # rung 12
    L.occ(b, "expected_mail_item_version", item)                    # rung 13
    # Adjudication of friction 4 (reading A): a superseding request lodged
    # against a piece already in PENDING_DISPOSITION is admitted by the
    # precedence rule.  Reading B would make SUPERSEDED, LOST_PRECEDENCE and the
    # whole precedence contest unreachable, since superseding can only ever
    # happen once the piece is already in PENDING_DISPOSITION.
    if item["handling_status"] not in ("HELD", "PENDING_DISPOSITION"):   # rung 14
        raise ApiError("ERR_INVALID_STATE")
    L.gate_c_item(item)                                             # rungs 17-19

    rank = DISPOSITION_RANK[dtype]
    pending = store.pending_dispositions(item["id"])                # rung 27
    if pending and min(p["precedence_rank"] for p in pending) <= rank:
        raise ApiError("ERR_DISPOSITION_CONFLICT")
    for p in pending:
        p["status"] = "SUPERSEDED"
        p["resolution_reason"] = "LOST_PRECEDENCE"
        touch(p)
    row = insert(DB.dispositions, {
        "mail_item_id": item["id"], "disposition_type": dtype, "precedence_rank": rank,
        "status": "PENDING", "resolution_reason": "NONE", "executed_at": None,
    })
    if item["handling_status"] == "HELD":
        item["handling_status"] = "PENDING_DISPOSITION"
        touch(item)
    return created(S.disposition(row))


@bp.get("/mail-items/<ident>/dispositions")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "BoxHolder", "Recipient"],
            primary="mail_item", scope=True)
def list_dispositions(item):
    status = L.enum_query("status", members=STATUS_ENUMS["disposition"])
    data = [d for d in store.dispositions_of_item(item["id"])
            if status is None or d["status"] == status]
    items, total, limit, offset = L.paginate(data, S.disposition)
    return listing(items, total, limit, offset)


@bp.post("/dispositions/<ident>/cancel")
@L.endpoint(roles=["BoxHolder"], primary="disposition", scope=True)
def cancel_disposition(d):
    item = store.mail_item(d["mail_item_id"])
    L.gate_b("disposition_cancel", store.box_of_item(item))
    if d["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE")
    d["status"] = "CANCELLED"
    d["resolution_reason"] = "HOLDER_CANCELLED"
    touch(d)
    _return_to_held(item)
    return ok(S.disposition(d))


def _return_to_held(item):
    """PENDING_DISPOSITION -> HELD once no PENDING request remains; resumes storage."""
    if item["handling_status"] != "PENDING_DISPOSITION":
        return
    if store.pending_dispositions(item["id"]):
        return
    item["handling_status"] = "HELD"
    touch(item)
    domain.evaluate_storage_axis(item)


@bp.post("/dispositions/<ident>/execute")
@L.endpoint(roles=["CmraOperator"], primary="disposition")
def execute_disposition(d):
    item = store.mail_item(d["mail_item_id"])
    box = store.box_of_item(item)
    L.gate_a("disposition_execute", box)                            # rung 11
    L.gate_b("disposition_execute", box)                            # rung 12
    if (d["status"] != "PENDING" or item["handling_status"] != "PENDING_DISPOSITION"
            or d["disposition_type"] not in ("SHRED", "RETURN")):   # rung 14
        raise ApiError("ERR_INVALID_STATE")
    winner = domain.winning_disposition(item["id"])
    if winner is not None and winner["id"] != d["id"]:
        raise ApiError("ERR_INVALID_STATE",
                       "Another pending request on this piece holds a lower precedence rank.")
    L.gate_c_item(item)                                             # rungs 17-19
    if d["disposition_type"] == "SHRED":                            # rung 34
        if domain.sop_retention_blocks(item, store.live_cancellation(item["box_id"])):
            raise ApiError("ERR_RA_RETENTION_ACTIVE")

    d["status"] = "EXECUTED"
    d["resolution_reason"] = "EXECUTED"
    d["executed_at"] = CLOCK.now
    touch(d)
    if d["disposition_type"] == "SHRED":
        item["handling_status"] = "SHREDDED"
        domain.end_custody(item, destroyed=True)
    else:
        item["handling_status"] = "RETURNED"
        domain.end_custody(item)
    touch(item)
    return ok(S.disposition(d))


# ------------------------------------------------------------------ forwarding
def _eligible(item, box):
    if item["box_id"] != box["id"]:
        return False
    if item["handling_status"] != "PENDING_DISPOSITION":
        return False
    winner = domain.winning_disposition(item["id"])
    if winner is None or winner["disposition_type"] != "FORWARD" or winner["status"] != "PENDING":
        return False
    if item["storage_status"] not in ("FREE_WINDOW", "ACCRUING"):
        return False
    if item["forward_shipment_id"] is not None:
        return False
    if item["item_class"] == "SOP":
        return False
    r = store.recipient(item["matched_recipient_id"]) if item["matched_recipient_id"] else None
    return r is not None and r["release_eligibility"] == "RELEASABLE"


@bp.post("/boxes/<ident>/forward-shipments")
@L.endpoint(roles=["BoxHolder"], primary="box")
def create_forward_shipment(box):
    b = L.body()
    # rung 7 -- every id inside mail_item_ids resolves to a mail item.
    # Adjudication of friction 2 (reading B): the resource-typed identifier
    # ERR_MAIL_ITEM_NOT_FOUND is returned, because its catalogued condition
    # covers "a mail item id in the path OR BODY"; under reading A that clause
    # of the catalogue would be unreachable, while ERR_RECIPIENT_NOT_FOUND stays
    # reachable either way through path ids and body recipient_id.
    raw_ids = b.get("mail_item_ids")
    if isinstance(raw_ids, list):
        for mid in raw_ids:
            if not isinstance(mid, str) or mid not in DB.mail_items:
                raise ApiError("ERR_MAIL_ITEM_NOT_FOUND")
    L.scope_check("box", box)                                       # rung 8
    L.req_present(b, "service_level")                               # rung 9
    dest = L.req_str(b, "destination_address")
    ids = L.req_list(b, "mail_item_ids")
    L.req_int(b, "expected_box_version", 0)
    level = L.enum_body(b, "service_level", "service_level")        # rung 10
    L.gate_a("forward_shipment_create", box)                        # rung 11
    L.gate_b("forward_shipment_create", box)                        # rung 12
    L.occ(b, "expected_box_version", box)                           # rung 13

    # Adjudication of friction 1 (reading A, evaluated over the referenced
    # members): Gate C does apply here -- the PRD lists this operation in Gate
    # C's blocked table -- but it blocks only when NO referenced member is
    # RELEASABLE.  Blocking on any single blocked member would make the
    # per-item consolidation-eligibility clause "its matched roster member has
    # release_eligibility RELEASABLE" unreachable, since the gate at rung 17
    # would always pre-empt it.
    members = []
    for mid in ids:
        item = DB.mail_items[mid]
        if item["box_id"] != box["id"] or not item["matched_recipient_id"]:
            continue
        r = store.recipient(item["matched_recipient_id"])
        if r is not None:
            members.append(r)
    if members and not any(r["release_eligibility"] == "RELEASABLE" for r in members):
        L.gate_c_for_recipient(members[0])                          # rungs 17-19

    eligible, seen = [], set()
    for mid in ids:
        item = DB.mail_items[mid]
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        if _eligible(item, box):
            eligible.append(item)
    excluded = len(seen) - len(eligible)
    if not eligible:                                                # rung 32
        raise ApiError("ERR_ITEM_NOT_CONSOLIDATABLE")

    base, discount, total, weight = calc.forward_pricing(eligible, level)
    row = insert(DB.forward_shipments, {
        "box_id": box["id"], "service_level": level, "destination_address": dest,
        "status": "PRICED", "item_count": len(eligible), "excluded_item_count": excluded,
        "total_weight_lb": weight, "base_price_cents": base,
        "consolidation_discount_cents": discount, "total_price_cents": total,
        "shipped_at": None,
    })
    for item in eligible:
        item["forward_shipment_id"] = row["id"]
        touch(item)
    touch(box)
    return created(S.forward_shipment(row))


@bp.get("/boxes/<ident>/forward-shipments")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "BoxHolder"], primary="box", scope=True)
def list_forward_shipments(box):
    status = L.enum_query("status", members=STATUS_ENUMS["forward_shipment"])
    data = [s for s in store.rows(DB.forward_shipments)
            if s["box_id"] == box["id"] and (status is None or s["status"] == status)]
    items, total, limit, offset = L.paginate(data, S.forward_shipment)
    return listing(items, total, limit, offset)


@bp.get("/forward-shipments/<ident>")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "BoxHolder"],
            primary="forward_shipment", scope=True)
def read_forward_shipment(s):
    return ok(S.forward_shipment(s))


@bp.post("/forward-shipments/<ident>/ship")
@L.endpoint(roles=["CmraOperator"], primary="forward_shipment")
def ship_forward_shipment(s):
    box = DB.boxes.get(s["box_id"])
    L.gate_a("forward_shipment_ship", box)                          # rung 11
    L.gate_b("forward_shipment_ship", box)                          # rung 12
    if s["status"] != "PRICED" or s["item_count"] < 1:              # rung 14
        raise ApiError("ERR_INVALID_STATE")
    domain.raise_quota(box, "FORWARD", 1)                           # rung 36

    s["status"] = "SHIPPED"
    s["shipped_at"] = CLOCK.now
    touch(s)
    for item in store.mail_items_of_box(box["id"]):
        if item["forward_shipment_id"] != s["id"]:
            continue
        if item["handling_status"] != "PENDING_DISPOSITION":
            continue
        winner = domain.winning_disposition(item["id"])
        if winner is not None and winner["disposition_type"] == "FORWARD":
            winner["status"] = "EXECUTED"
            winner["resolution_reason"] = "EXECUTED"
            winner["executed_at"] = CLOCK.now
            touch(winner)
        item["handling_status"] = "FORWARDED"
        domain.end_custody(item)
        touch(item)
    domain.meter(box, "FORWARD", 1, "FORWARD_SHIPPED")
    return ok(S.forward_shipment(s))


@bp.post("/forward-shipments/<ident>/cancel")
@L.endpoint(roles=["BoxHolder"], primary="forward_shipment", scope=True)
def cancel_forward_shipment(s):
    box = DB.boxes.get(s["box_id"])
    L.gate_b("forward_shipment_cancel", box)
    if s["status"] != "PRICED":
        raise ApiError("ERR_INVALID_STATE")
    s["status"] = "CANCELLED"
    for item in store.mail_items_of_box(s["box_id"]):
        if item["forward_shipment_id"] == s["id"]:
            item["forward_shipment_id"] = None
            touch(item)
    s["item_count"] = 0
    touch(s)
    return ok(S.forward_shipment(s))
