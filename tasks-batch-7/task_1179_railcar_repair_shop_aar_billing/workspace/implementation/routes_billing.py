"""Billing Repair Cards, counter-bills, and warranty claims
(PRD 3.7, 3.8, 3.9)."""
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR

from flask import Blueprint, g, request

import db
from errors import ApiError
from common import (
    auth, ok, get_body, req_str, req_int, invalid_request,
    base_fields, touch, get_or_404, ref_or_404, public, sort_items,
    list_response, now, now_iso, parse_dt, rhu_cents, iso,
    AGGREGATE_COUNTER_CAP_PCT, DEFECT_GROUPS,
)
import billing_ops

bp = Blueprint("billing", __name__)

BRC_TERMINAL = ("SETTLED", "WITHDRAWN", "SUPERSEDED")


def brc_out(b):
    return public(b)


def brc_line_out(l):
    return public(l)


def counter_out(c):
    return public(c)


def claim_out(c):
    return public(c)


def wo_of_brc(brc):
    return db.STORE["work_orders"].get(brc["work_order_id"])


# ---------------------------------------------------------------------------
# Billing Repair Cards (PRD 3.7)
# ---------------------------------------------------------------------------

@bp.post("/billing-repair-cards")
@auth("BillingClerk")
def create_brc():
    body = get_body()
    wo = ref_or_404("work_orders", req_str(body, "work_order_id"), "WorkOrder")
    expected = req_int(body, "expected_work_order_version")
    if expected != wo["version"]:
        raise ApiError("ERR_STALE_WORK_ORDER_VERSION", 412,
                       "expected_work_order_version does not match the work order's current version")
    if wo["exec_status"] != "COMPLETED":
        raise ApiError("ERR_WORK_ORDER_NOT_COMPLETED", 409,
                       "A Billing Repair Card requires a COMPLETED work order")
    existing_draft = None
    for b in db.STORE["brcs"].values():
        if b["work_order_id"] != wo["id"]:
            continue
        if b["status"] == "DRAFT":
            existing_draft = b
        elif b["status"] not in BRC_TERMINAL:
            raise ApiError("ERR_BRC_ALREADY_ACTIVE", 409,
                           "A non-draft, non-terminal card already exists for this work order")

    brc = base_fields()
    brc.update({
        "work_order_id": wo["id"],
        "supersedes_brc_id": existing_draft["id"] if existing_draft else None,
        "status": "DRAFT",
        "mobile_surcharge_cents": 0,
        "submitted_total_cents": 0,
        "owner_total_cents": 0,
        "handling_line_total_cents": 0,
        "net_settled_cents": 0,
        "submitted_at": None,
        "dispute_window_ends_at": None,
    })
    db.STORE["brcs"][brc["id"]] = brc

    # Snapshot every FINALIZED repair line (per-line rounding, then sum).
    final_lines = sort_items([l for l in db.STORE["repair_lines"].values()
                              if l["work_order_id"] == wo["id"]
                              and l["status"] == "FINALIZED"])
    sum_finals = 0
    owner_total = 0
    for rl in final_lines:
        pct = rl["owner_pct"] or 0
        owner_share = rhu_cents(Decimal(rl["final_total_cents"]) * Decimal(pct) / Decimal(100))
        bl = base_fields()
        bl.update({
            "brc_id": brc["id"],
            "repair_line_id": rl["id"],
            "job_code": rl["job_code"],
            "final_amount_cents": rl["final_total_cents"],
            "owner_share_cents": owner_share,
            "handling_share_cents": rl["final_total_cents"] - owner_share,
            "accepted_credit_cents": 0,
            "warranty_credit_cents": 0,
        })
        db.STORE["brc_lines"][bl["id"]] = bl
        sum_finals += rl["final_total_cents"]
        owner_total += owner_share

    surcharge = 0
    if wo["routing"] == "MOBILE" and final_lines:
        earliest = final_lines[0]
        entry = db.STORE["price_entries"].get(earliest["price_master_entry_id"])
        if entry is not None:
            surcharge = entry["mobile_trip_surcharge_cents"]
    brc["mobile_surcharge_cents"] = surcharge
    brc["submitted_total_cents"] = sum_finals + surcharge
    if wo["responsible_party"] in ("OWNER", "SHARED"):
        owner_total += surcharge
    brc["owner_total_cents"] = owner_total
    brc["handling_line_total_cents"] = brc["submitted_total_cents"] - owner_total
    brc["net_settled_cents"] = brc["submitted_total_cents"]

    if existing_draft is not None:
        existing_draft["status"] = "SUPERSEDED"
        touch(existing_draft)
    touch(wo)
    return ok(brc_out(brc), code=201)


@bp.get("/billing-repair-cards")
@auth("Any")
def list_brcs():
    items = list(db.STORE["brcs"].values())
    for name in ("work_order_id", "status", "supersedes_brc_id"):
        v = request.args.get(name)
        if v is not None:
            items = [b for b in items if b[name] == v]
    return list_response([brc_out(b) for b in sort_items(items)])


@bp.get("/billing-repair-cards/<bid>")
@auth("Any")
def get_brc(bid):
    return ok(brc_out(get_or_404("brcs", bid, "BillingRepairCard")))


@bp.get("/billing-repair-cards/<bid>/lines")
@auth("Any")
def list_brc_lines(bid):
    brc = get_or_404("brcs", bid, "BillingRepairCard")
    items = billing_ops.brc_lines_of(brc["id"])
    return list_response([brc_line_out(l) for l in sort_items(items)])


@bp.get("/brc-lines/<lid>")
@auth("Any")
def get_brc_line(lid):
    return ok(brc_line_out(get_or_404("brc_lines", lid, "BrcLine")))


@bp.get("/brc-lines")
@auth("Any")
def list_all_brc_lines():
    items = list(db.STORE["brc_lines"].values())
    for name in ("repair_line_id", "brc_id"):
        v = request.args.get(name)
        if v is not None:
            items = [l for l in items if l[name] == v]
    return list_response([brc_line_out(l) for l in sort_items(items)])


@bp.post("/billing-repair-cards/<bid>/submit")
@auth("BillingClerk")
def submit_brc(bid):
    brc = get_or_404("brcs", bid, "BillingRepairCard")
    get_body(required=False)
    if brc["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a DRAFT card can be submitted")
    wo = wo_of_brc(brc)
    if wo is None or wo["exec_status"] != "COMPLETED":
        raise ApiError("ERR_WORK_ORDER_NOT_COMPLETED", 409,
                       "The billed work order must be COMPLETED")
    railcar = db.STORE["railcars"][wo["railcar_id"]]
    shop = db.STORE["shops"].get(railcar["shop_id"])
    window_days = shop["counter_window_days"] if shop else 30
    brc["status"] = "SUBMITTED"
    brc["submitted_at"] = now_iso()
    brc["dispute_window_ends_at"] = iso(now() + timedelta(days=window_days))
    touch(brc)
    return ok(brc_out(brc))


@bp.post("/billing-repair-cards/<bid>/accept")
@auth("CarOwnerRep", "HandlingLineRep")
def accept_brc(bid):
    brc = get_or_404("brcs", bid, "BillingRepairCard")
    get_body(required=False)
    wo = wo_of_brc(brc)
    billing_ops.party_match_or_403(wo)
    if brc["status"] not in ("SUBMITTED", "DISPUTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a SUBMITTED card can be accepted")
    if billing_ops.active_counters(brc["id"]):
        raise ApiError("ERR_COUNTER_BILL_ACTIVE", 409,
                       "An OPEN or REBUTTED counter-bill exists on this card")
    if brc["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a SUBMITTED card can be accepted")
    brc["status"] = "ACCEPTED"
    billing_ops.post_balances(brc, +1)
    touch(brc)
    return ok(brc_out(brc))


@bp.post("/billing-repair-cards/<bid>/withdraw")
@auth("BillingClerk")
def withdraw_brc(bid):
    brc = get_or_404("brcs", bid, "BillingRepairCard")
    get_body(required=False)
    if brc["status"] not in ("DRAFT", "SUBMITTED", "DISPUTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a DRAFT or SUBMITTED card can be withdrawn")
    if billing_ops.active_counters(brc["id"]):
        raise ApiError("ERR_COUNTER_BILL_ACTIVE", 409,
                       "An OPEN or REBUTTED counter-bill exists on this card")
    if brc["status"] == "DISPUTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a DRAFT or SUBMITTED card can be withdrawn")
    brc["status"] = "WITHDRAWN"
    touch(brc)
    return ok(brc_out(brc))


@bp.post("/billing-repair-cards/<bid>/settle")
@auth("BillingClerk")
def settle_brc(bid):
    brc = get_or_404("brcs", bid, "BillingRepairCard")
    get_body(required=False)
    if brc["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only an ACCEPTED card can be settled")
    brc["status"] = "SETTLED"
    billing_ops.post_balances(brc, -1)
    touch(brc)
    return ok(brc_out(brc))


# ---------------------------------------------------------------------------
# Counter-bills (PRD 3.8)
# ---------------------------------------------------------------------------

def validate_counter_items(body):
    items = body.get("items")
    if not isinstance(items, list) or not items:
        raise invalid_request("items must be a non-empty list")
    return items


def check_counter_item_refs(brc, items):
    """Resolve and validate each item against this card's lines."""
    resolved = []
    for item in items:
        if not isinstance(item, dict):
            raise invalid_request("counter items must be objects")
        line_id = item.get("brc_line_id")
        if not isinstance(line_id, str):
            raise invalid_request("counter items require brc_line_id")
        bl = db.STORE["brc_lines"].get(line_id)
        if bl is None or bl["brc_id"] != brc["id"]:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", 404,
                           "BrcLine %s does not exist on this card" % line_id)
        amount = item.get("counter_amount_cents")
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise invalid_request("counter_amount_cents must be a positive integer")
        if not isinstance(item.get("reason"), str):
            raise invalid_request("counter items require a reason")
        resolved.append({"brc_line_id": bl["id"],
                         "counter_amount_cents": amount,
                         "reason": item["reason"]})
    return resolved


def check_counter_ceilings(brc, resolved_items, exclude_counter_id=None):
    """Aggregate ceiling first, then per-line remainder (PRD 3.8)."""
    new_total = sum(i["counter_amount_cents"] for i in resolved_items)
    running = 0
    for cb in billing_ops.counters_of(brc["id"]):
        if exclude_counter_id is not None and cb["id"] == exclude_counter_id:
            continue
        if cb["status"] in ("ACCEPTED", "OPEN", "REBUTTED"):
            running += cb["total_countered_cents"]
    cap = int((AGGREGATE_COUNTER_CAP_PCT * Decimal(brc["submitted_total_cents"]))
              .to_integral_value(rounding=ROUND_FLOOR))
    if running + new_total > cap:
        raise ApiError("ERR_COUNTER_BILL_EXCEEDS_CEILING", 409,
                       "Aggregate countered total would exceed 60 percent of the card")
    for item in resolved_items:
        bl = db.STORE["brc_lines"][item["brc_line_id"]]
        remaining = (bl["final_amount_cents"] - bl["accepted_credit_cents"]
                     - bl["warranty_credit_cents"])
        if item["counter_amount_cents"] > remaining:
            raise ApiError("ERR_CREDIT_EXCEEDS_REMAINING", 409,
                           "Counter amount exceeds the line's remaining credit headroom")
    return new_total


def dispute_window_open(brc):
    if brc["dispute_window_ends_at"] is None:
        return True
    return now() <= parse_dt(brc["dispute_window_ends_at"])


@bp.post("/billing-repair-cards/<bid>/counter-bills")
@auth("CarOwnerRep", "HandlingLineRep")
def create_counter_bill(bid):
    brc = get_or_404("brcs", bid, "BillingRepairCard")
    body = get_body()
    items = validate_counter_items(body)
    resolved = check_counter_item_refs(brc, items)
    wo = wo_of_brc(brc)
    billing_ops.party_match_or_403(wo)
    if brc["status"] not in ("SUBMITTED", "DISPUTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Counter-bills can only be filed against a SUBMITTED or DISPUTED card")
    if not dispute_window_open(brc):
        raise ApiError("ERR_COUNTER_BILL_WINDOW_CLOSED", 409,
                       "The dispute window for this card has closed")
    if billing_ops.active_counters(brc["id"]):
        raise ApiError("ERR_COUNTER_BILL_ACTIVE", 409,
                       "An OPEN or REBUTTED counter-bill already exists on this card")
    total = check_counter_ceilings(brc, resolved)
    cb = base_fields()
    cb.update({
        "brc_id": brc["id"],
        "items": resolved,
        "total_countered_cents": total,
        "status": "OPEN",
        "filed_by_role": g.user_role,
        "filed_by_id": g.user_id,
        "filed_at": now_iso(),
    })
    db.STORE["counter_bills"][cb["id"]] = cb
    if brc["status"] == "SUBMITTED":
        brc["status"] = "DISPUTED"
        touch(brc)
    return ok(counter_out(cb), code=201)


@bp.get("/billing-repair-cards/<bid>/counter-bills")
@auth("Any")
def list_counter_bills(bid):
    brc = get_or_404("brcs", bid, "BillingRepairCard")
    items = billing_ops.counters_of(brc["id"])
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response([counter_out(c) for c in sort_items(items)])


@bp.get("/counter-bills/<cid>")
@auth("Any")
def get_counter_bill(cid):
    return ok(counter_out(get_or_404("counter_bills", cid, "CounterBill")))


@bp.post("/counter-bills/<cid>/accept")
@auth("BillingClerk")
def accept_counter_bill(cid):
    cb = get_or_404("counter_bills", cid, "CounterBill")
    get_body(required=False)
    if cb["status"] not in ("OPEN", "REBUTTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only an OPEN or REBUTTED counter-bill can be accepted")
    brc = db.STORE["brcs"][cb["brc_id"]]
    # Hop 1: credits land on the card lines.
    for item in cb["items"]:
        bl = db.STORE["brc_lines"].get(item["brc_line_id"])
        if bl is not None:
            bl["accepted_credit_cents"] += item["counter_amount_cents"]
            touch(bl)
    cb["status"] = "ACCEPTED"
    touch(cb)
    # Hop 2: card net recompute. Hop 3: DISPUTED -> SUBMITTED when resolved.
    billing_ops.recompute_net_settled(brc)
    billing_ops.maybe_resolve_disputed_brc(brc)
    return ok(counter_out(cb))


@bp.post("/counter-bills/<cid>/rebut")
@auth("BillingClerk")
def rebut_counter_bill(cid):
    cb = get_or_404("counter_bills", cid, "CounterBill")
    get_body(required=False)
    if cb["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only an OPEN counter-bill can be rebutted")
    cb["status"] = "REBUTTED"
    touch(cb)
    return ok(counter_out(cb))


def filer_match_or_403(record):
    if g.user_id != record["filed_by_id"]:
        raise ApiError("ERR_RESPONSIBILITY_MISMATCH", 403,
                       "Only the original filer may perform this operation")


@bp.post("/counter-bills/<cid>/revise")
@auth("CarOwnerRep", "HandlingLineRep")
def revise_counter_bill(cid):
    cb = get_or_404("counter_bills", cid, "CounterBill")
    body = get_body()
    items = validate_counter_items(body)
    filer_match_or_403(cb)
    if cb["status"] != "REBUTTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a REBUTTED counter-bill can be revised")
    brc = db.STORE["brcs"][cb["brc_id"]]
    if not dispute_window_open(brc):
        raise ApiError("ERR_COUNTER_BILL_WINDOW_CLOSED", 409,
                       "The dispute window for this card has closed")
    resolved = check_counter_item_refs(brc, items)
    total = check_counter_ceilings(brc, resolved, exclude_counter_id=cb["id"])
    cb["items"] = resolved
    cb["total_countered_cents"] = total
    cb["status"] = "OPEN"
    touch(cb)
    return ok(counter_out(cb))


@bp.post("/counter-bills/<cid>/withdraw")
@auth("CarOwnerRep", "HandlingLineRep")
def withdraw_counter_bill(cid):
    cb = get_or_404("counter_bills", cid, "CounterBill")
    get_body(required=False)
    filer_match_or_403(cb)
    if cb["status"] not in ("OPEN", "REBUTTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only an OPEN or REBUTTED counter-bill can be withdrawn")
    cb["status"] = "WITHDRAWN"
    touch(cb)
    brc = db.STORE["brcs"][cb["brc_id"]]
    billing_ops.maybe_resolve_disputed_brc(brc)
    return ok(counter_out(cb))


# ---------------------------------------------------------------------------
# Warranty claims (PRD 3.9)
# ---------------------------------------------------------------------------

@bp.post("/warranty-claims")
@auth("CarOwnerRep", "HandlingLineRep")
def create_warranty_claim():
    body = get_body()
    rl = ref_or_404("repair_lines", req_str(body, "repair_line_id"), "RepairLine")
    group = req_str(body, "failure_defect_group")
    if group not in DEFECT_GROUPS:
        raise invalid_request("failure_defect_group must be a valid defect group")
    claimed = req_int(body, "claimed_rework_cost_cents")
    description = req_str(body, "description")
    wo = db.STORE["work_orders"][rl["work_order_id"]]
    billing_ops.party_match_or_403(wo)
    railcar = db.STORE["railcars"][wo["railcar_id"]]
    shop = db.STORE["shops"].get(railcar["shop_id"])
    warranty_days = shop["warranty_days"] if shop else 90
    if wo["completed_at"] is not None:
        window_end = parse_dt(wo["completed_at"]) + timedelta(days=warranty_days)
        if now() > window_end:
            raise ApiError("ERR_WARRANTY_WINDOW_EXPIRED", 409,
                           "The warranty window for this repair has expired")
    defect = db.STORE["defects"].get(rl["defect_finding_id"])
    if rl["status"] != "FINALIZED" or defect is None \
            or defect["defect_group"] != group:
        raise ApiError("ERR_WARRANTY_NOT_APPLICABLE", 409,
                       "Claim requires a FINALIZED line whose defect group matches")
    for c in db.STORE["warranty_claims"].values():
        if c["repair_line_id"] == rl["id"] and c["status"] in ("FILED", "VALIDATED"):
            raise ApiError("ERR_WARRANTY_CLAIM_ACTIVE", 409,
                           "A FILED or VALIDATED claim already exists on this repair line")
    claim = base_fields()
    claim.update({
        "shop_id": railcar["shop_id"],
        "repair_line_id": rl["id"],
        "failure_defect_group": group,
        "description": description,
        "claimed_rework_cost_cents": claimed,
        "credit_cents": None,
        "status": "FILED",
        "filed_by_role": g.user_role,
        "filed_by_id": g.user_id,
        "appeal_count": 0,
    })
    db.STORE["warranty_claims"][claim["id"]] = claim
    return ok(claim_out(claim), code=201)


@bp.get("/warranty-claims")
@auth("Any")
def list_warranty_claims():
    items = list(db.STORE["warranty_claims"].values())
    for name in ("shop_id", "repair_line_id", "status"):
        v = request.args.get(name)
        if v is not None:
            items = [c for c in items if c[name] == v]
    return list_response([claim_out(c) for c in sort_items(items)])


@bp.get("/warranty-claims/<cid>")
@auth("Any")
def get_warranty_claim(cid):
    return ok(claim_out(get_or_404("warranty_claims", cid, "WarrantyClaim")))


@bp.post("/warranty-claims/<cid>/validate")
@auth("QualityInspector")
def validate_warranty_claim(cid):
    claim = get_or_404("warranty_claims", cid, "WarrantyClaim")
    get_body(required=False)
    if claim["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a FILED claim can be validated")
    claim["status"] = "VALIDATED"
    touch(claim)
    return ok(claim_out(claim))


@bp.post("/warranty-claims/<cid>/deny")
@auth("QualityInspector")
def deny_warranty_claim(cid):
    claim = get_or_404("warranty_claims", cid, "WarrantyClaim")
    get_body(required=False)
    if claim["status"] not in ("FILED", "VALIDATED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a FILED or VALIDATED claim can be denied")
    claim["status"] = "DENIED"
    touch(claim)
    return ok(claim_out(claim))


@bp.post("/warranty-claims/<cid>/honor")
@auth("BillingClerk")
def honor_warranty_claim(cid):
    claim = get_or_404("warranty_claims", cid, "WarrantyClaim")
    get_body(required=False)
    if claim["status"] != "VALIDATED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a VALIDATED claim can be honored")
    rl = db.STORE["repair_lines"][claim["repair_line_id"]]
    wo = db.STORE["work_orders"][rl["work_order_id"]]
    # The card line built from this repair line, if any: prefer the latest
    # line on a non-superseded card.
    candidates = [l for l in db.STORE["brc_lines"].values()
                  if l["repair_line_id"] == rl["id"]]
    bl = None
    if candidates:
        live = [l for l in candidates
                if db.STORE["brcs"].get(l["brc_id"]) is not None
                and db.STORE["brcs"][l["brc_id"]]["status"] != "SUPERSEDED"]
        pool = live if live else candidates
        bl = sort_items(pool)[-1]
    base = rl["final_total_cents"] or 0
    remaining = base
    if bl is not None:
        remaining = base - bl["accepted_credit_cents"] - bl["warranty_credit_cents"]
    credit = min(remaining, claim["claimed_rework_cost_cents"])
    pct = rl["owner_pct"] or 0
    owner_credit = rhu_cents(Decimal(credit) * Decimal(pct) / Decimal(100))
    handling_credit = credit - owner_credit
    _, owner, line = billing_ops.parties_for_work_order(wo)
    if owner is not None:
        owner["outstanding_balance_cents"] -= owner_credit
        touch(owner)
    if line is not None:
        line["outstanding_balance_cents"] -= handling_credit
        touch(line)
    if bl is not None:
        bl["warranty_credit_cents"] += credit
        touch(bl)
    claim["credit_cents"] = credit
    claim["status"] = "HONORED"
    touch(claim)
    return ok(claim_out(claim))


@bp.post("/warranty-claims/<cid>/appeal")
@auth("CarOwnerRep", "HandlingLineRep")
def appeal_warranty_claim(cid):
    claim = get_or_404("warranty_claims", cid, "WarrantyClaim")
    get_body(required=False)
    filer_match_or_403(claim)
    if claim["status"] != "DENIED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a DENIED claim can be appealed")
    rl = db.STORE["repair_lines"][claim["repair_line_id"]]
    wo = db.STORE["work_orders"][rl["work_order_id"]]
    railcar = db.STORE["railcars"][wo["railcar_id"]]
    shop = db.STORE["shops"].get(railcar["shop_id"])
    warranty_days = shop["warranty_days"] if shop else 90
    if wo["completed_at"] is not None:
        window_end = parse_dt(wo["completed_at"]) + timedelta(days=warranty_days)
        if now() > window_end:
            raise ApiError("ERR_WARRANTY_WINDOW_EXPIRED", 409,
                           "The warranty window for this repair has expired")
    claim["status"] = "FILED"
    claim["appeal_count"] += 1
    touch(claim)
    return ok(claim_out(claim))
