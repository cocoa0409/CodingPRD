"""Logical clock, reference catalogues and mailbox lifecycle."""

from flask import Blueprint, g, request

import calc
import domain
import ladder as L
import serializers as S
import store
from errors import ApiError
from response import created, empty, listing, ok, touch
from store import DB, insert, rows
from util import CLOCK, parse_instant

bp = Blueprint("catalogue", __name__)


# ------------------------------------------------------------------ logical clock
@bp.post("/_clock/set_current_utc")
@L.endpoint(roles=["PlatformAdmin"])
def set_clock():
    b = L.body()
    raw = L.req_str(b, "to_iso8601")
    instant = parse_instant(raw)
    if instant is None:
        L._bad("to_iso8601", "must be an ISO 8601 instant")
    domain.advance_clock(instant)
    return empty()


# ------------------------------------------------------------------ plan tiers
@bp.post("/plan-tiers")
@L.endpoint(roles=["PlatformAdmin"])
def create_plan_tier():
    b = L.body()
    L.req_present(b, "tier_code")
    name = L.req_str(b, "name")
    rank = L.req_int(b, "rank", 1, 4)
    monthly = L.req_int(b, "monthly_fee_cents", 0)
    inc_rec = L.req_int(b, "included_recipients", 1)
    inc_scan = L.req_int(b, "included_scan_pages", 0)
    inc_fwd = L.req_int(b, "included_forwards", 0)
    inc_store = L.req_int(b, "included_storage_days", 0)
    ov_scan = L.req_int(b, "overage_scan_page_cents", 0)
    ov_fwd = L.req_int(b, "overage_forward_cents", 0)
    ov_store = L.req_int(b, "overage_storage_day_cents", 0)
    ov_rec = L.req_int(b, "overage_recipient_cents", 0)
    allows = L.req_bool(b, "allows_overage", True)
    tier_code = L.enum_body(b, "tier_code", "tier_code")
    for t in DB.plan_tiers.values():
        if t["tier_code"] == tier_code:
            L._bad("tier_code", "must be unique across the catalogue")
        if t["rank"] == rank:
            L._bad("rank", "must be unique across the catalogue")
    row = insert(DB.plan_tiers, {
        "tier_code": tier_code, "name": name, "rank": rank,
        "monthly_fee_cents": monthly, "included_recipients": inc_rec,
        "included_scan_pages": inc_scan, "included_forwards": inc_fwd,
        "included_storage_days": inc_store, "overage_scan_page_cents": ov_scan,
        "overage_forward_cents": ov_fwd, "overage_storage_day_cents": ov_store,
        "overage_recipient_cents": ov_rec, "allows_overage": allows,
    }, common=False)
    return created(S.plan_tier(row))


@bp.get("/plan-tiers")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "ComplianceOfficer", "BoxHolder",
                   "Recipient", "Notary"])
def list_plan_tiers():
    # Rung 10's closed list enumerates the enum-valued QUERY filters, and
    # tier_code is not among them: an unmatched value simply filters to empty.
    code = request.args.get("tier_code")
    data = [t for t in rows(DB.plan_tiers) if code is None or t["tier_code"] == code]
    items, total, limit, offset = L.paginate(data, S.plan_tier)
    return listing(items, total, limit, offset)


# ------------------------------------------------------------------ carrier rules
@bp.post("/carrier-rules")
@L.endpoint(roles=["PlatformAdmin"])
def create_carrier_rule():
    b = L.body()
    L.req_present(b, "carrier_code")
    divisor = L.req_int(b, "dim_divisor", 1)
    max_lpg = L.req_num(b, "max_length_plus_girth_in", exclusive_min=0)
    max_wt = L.req_num(b, "max_actual_weight_lb", exclusive_min=0)
    accepts = L.req_bool(b, "accepts_signature_required", True)
    fee = L.req_int(b, "acceptance_fee_cents", 0)
    rate = L.req_int(b, "base_rate_cents_per_lb", 0)
    code = L.enum_body(b, "carrier_code", "carrier_code")
    for r in DB.carrier_rules.values():
        if r["carrier_code"] == code:
            L._bad("carrier_code", "must be unique across the catalogue")
    row = insert(DB.carrier_rules, {
        "carrier_code": code, "dim_divisor": divisor,
        "max_length_plus_girth_in": max_lpg, "max_actual_weight_lb": max_wt,
        "accepts_signature_required": accepts, "acceptance_fee_cents": fee,
        "base_rate_cents_per_lb": rate,
    }, common=False)
    return created(S.carrier_rule(row))


@bp.get("/carrier-rules")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "ComplianceOfficer", "BoxHolder"])
def list_carrier_rules():
    # Not an enum-valued query filter per rung 10's closed list.
    code = request.args.get("carrier_code")
    data = [t for t in rows(DB.carrier_rules) if code is None or t["carrier_code"] == code]
    items, total, limit, offset = L.paginate(data, S.carrier_rule)
    return listing(items, total, limit, offset)


# ------------------------------------------------------------------ boxes
@bp.post("/boxes")
@L.endpoint(roles=["CmraOperator"])
def create_box():
    b = L.body()
    # rung 5 -- a plan_tier_id supplied in the body resolves
    if b.get("plan_tier_id") is not None:
        if not isinstance(b["plan_tier_id"], str) or b["plan_tier_id"] not in DB.plan_tiers:
            raise ApiError("ERR_PLAN_TIER_NOT_FOUND")
    number = L.req_str(b, "box_number")
    plan_tier_id = L.req_str(b, "plan_tier_id")
    holder_name = L.req_str(b, "holder_name")
    holder_email = L.req_str(b, "holder_email")
    deposit = L.opt_int(b, "security_deposit_cents", 0, 0)
    slots = L.opt_int(b, "extra_recipient_slots", 0, 0)
    prepaid = L.opt_int(b, "prepaid_balance_cents", 0, 0)
    for existing in DB.boxes.values():
        if existing["box_number"] == number:
            L._bad("box_number", "must be unique across all mailboxes")
    row = insert(DB.boxes, {
        "box_number": number, "plan_tier_id": plan_tier_id, "pending_plan_tier_id": None,
        "holder_name": holder_name, "holder_email": holder_email,
        "security_deposit_cents": deposit, "extra_recipient_slots": slots,
        "prepaid_balance_cents": prepaid,
        "service_status": "PENDING_SETUP", "compliance_status": "COMPLIANT",
        "suspended_reason": "NONE", "activated_at": None, "cycle_anchor_date": None,
    })
    return created(S.box(row))


@bp.get("/boxes")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "ComplianceOfficer"])
def list_boxes():
    status = L.enum_query("service_status", "service_status")
    plan = request.args.get("plan_tier_id")
    pending = request.args.get("pending_plan_tier_id")
    data = rows(DB.boxes)
    if plan is not None:
        data = [x for x in data if x["plan_tier_id"] == plan]
    if pending is not None:
        data = [x for x in data if x["pending_plan_tier_id"] == pending]
    if status is not None:
        data = [x for x in data if x["service_status"] == status]
    items, total, limit, offset = L.paginate(data, S.box)
    return listing(items, total, limit, offset)


@bp.get("/boxes/<ident>")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "ComplianceOfficer", "BoxHolder"],
            primary="box", scope=True)
def read_box(box):
    return ok(S.box(box))


@bp.post("/boxes/<ident>/activate")
@L.endpoint(roles=["CmraOperator"], primary="box")
def activate_box(box):
    L.gate_b("box_activate", box)
    if box["service_status"] != "PENDING_SETUP":
        raise ApiError("ERR_INVALID_STATE")
    box["service_status"] = "ACTIVE"
    box["activated_at"] = CLOCK.now
    box["cycle_anchor_date"] = CLOCK.date()
    touch(box)
    domain.create_cycle(box, 1, box["cycle_anchor_date"])
    return ok(S.box(box))


@bp.post("/boxes/<ident>/plan-change")
@L.endpoint(roles=["BoxHolder"], primary="box")
def plan_change(box):
    b = L.body()
    # rung 5
    if b.get("new_plan_tier_id") is not None:
        if not isinstance(b["new_plan_tier_id"], str) or b["new_plan_tier_id"] not in DB.plan_tiers:
            raise ApiError("ERR_PLAN_TIER_NOT_FOUND")
    L.scope_check("box", box)                                   # rung 8
    new_tier_id = L.req_str(b, "new_plan_tier_id")              # rung 9
    L.req_int(b, "expected_box_version", 0)
    new_tier = DB.plan_tiers[new_tier_id]
    old_tier = store.tier_of_box(box)
    if old_tier is not None and new_tier["rank"] == old_tier["rank"]:
        L._bad("new_plan_tier_id", "must name a tier of a different rank")
    L.gate_a("plan_change", box)                                # rung 11
    L.gate_b("plan_change", box)                                # rung 12
    L.occ(b, "expected_box_version", box)                       # rung 13
    cycle = store.open_cycle(box["id"])
    if new_tier["rank"] > old_tier["rank"]:
        credit, charge = domain.proration(old_tier, new_tier, cycle) if cycle else (0, 0)
        box["plan_tier_id"] = new_tier["id"]
        box["pending_plan_tier_id"] = None
    else:
        credit, charge = 0, 0
        box["pending_plan_tier_id"] = new_tier["id"]
    if cycle is not None:
        cycle["proration_credit_cents"] = credit
        cycle["proration_charge_cents"] = charge
        touch(cycle)
    touch(box)
    return ok(S.box(box))


@bp.get("/boxes/<ident>/summary")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "ComplianceOfficer", "BoxHolder"],
            primary="box", scope=True)
def box_summary(box):
    cycle = store.open_cycle(box["id"])
    items = store.mail_items_of_box(box["id"])
    return ok({
        "box_id": box["id"],
        "service_status": box["service_status"],
        "compliance_status": box["compliance_status"],
        "release_gate_state": S.release_gate_state(box),
        "roster_authorized_count": sum(
            1 for r in store.recipients_of_box(box["id"]) if r["roster_status"] == "AUTHORIZED"),
        "open_billing_cycle_id": cycle["id"] if cycle else None,
        "scan_pages_consumed": cycle["scan_pages_consumed"] if cycle else 0,
        "forwards_consumed": cycle["forwards_consumed"] if cycle else 0,
        "storage_days_consumed": cycle["storage_days_consumed"] if cycle else 0,
        "recipients_consumed": cycle["recipients_consumed"] if cycle else 0,
        "outstanding_overage_cents": calc.outstanding_overage(box["id"]),
        "items_in_custody": sum(1 for m in items
                                if m["storage_status"] in ("FREE_WINDOW", "ACCRUING")),
        "items_released": sum(1 for m in items if m["storage_status"] == "RELEASED"),
        "items_destroyed": sum(1 for m in items if m["storage_status"] == "DESTROYED"),
    })
