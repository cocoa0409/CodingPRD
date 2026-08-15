"""Auth, path resolution, calculations, cascades, and checkpoint logic."""
import calendar
from datetime import datetime, timedelta, timezone, time as dtime
from decimal import Decimal
from zoneinfo import ZoneInfo

from flask import request

import store as S
from store import (
    banks, customers, agreements, sites, formats, schedules, batches, items,
    exceptions, image_requests, cycles, line_items, incidents, credits,
)
from util import (
    ApiError, ROLES, now, fmt, parse_dt, parse_date, add_business_days, rhu,
    new_entity, touch, pub, invalid, not_found,
)

ALL_ROLES = ROLES


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------

def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not uid.strip():
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "X-User-ID header missing or malformed")
    if role not in ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "X-User-Role header missing or malformed")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE", 403,
                       "role %s is not permitted for this endpoint" % role)


def scope(uid, role, customer_id):
    """CustomerOperator may only touch resources of its own customer."""
    if role == "CustomerOperator" and uid != customer_id:
        not_found("resource not found")


# ---------------------------------------------------------------------------
# Nested path resolution (left to right, bank-scoped)
# ---------------------------------------------------------------------------

def R_bank(bid):
    b = banks.get(bid)
    if not b:
        not_found("bank not found")
    return b


def R_customer(bank, cid, uid=None, role=None):
    c = customers.get(cid)
    if not c or c["bank_id"] != bank["id"]:
        not_found("customer not found")
    if role is not None:
        scope(uid, role, c["id"])
    return c


def R_agreement(customer, aid):
    a = agreements.get(aid)
    if not a or a["customer_id"] != customer["id"]:
        not_found("agreement not found")
    return a


def R_site(agreement, sid):
    s = sites.get(sid)
    if not s or s["agreement_id"] != agreement["id"]:
        not_found("site not found")
    return s


def R_batch(site, bid):
    b = batches.get(bid)
    if not b or b["site_id"] != site["id"]:
        not_found("batch not found")
    return b


def R_item(batch, iid):
    it = items.get(iid)
    if not it or it["batch_id"] != batch["id"]:
        not_found("item not found")
    return it


def R_exception(customer, eid):
    e = exceptions.get(eid)
    if not e or e["customer_id"] != customer["id"]:
        not_found("exception item not found")
    return e


def R_image(customer, rid):
    r = image_requests.get(rid)
    if not r or r["customer_id"] != customer["id"]:
        not_found("image request not found")
    return r


def R_cycle(customer, cyid):
    c = cycles.get(cyid)
    if not c or c["customer_id"] != customer["id"]:
        not_found("analysis cycle not found")
    return c


def R_lineitem(cycle, lid):
    li = line_items.get(lid)
    if not li or li["cycle_id"] != cycle["id"]:
        not_found("line item not found")
    return li


def R_incident(customer, iid):
    i = incidents.get(iid)
    if not i or i["customer_id"] != customer["id"]:
        not_found("sla incident not found")
    return i


def R_credit(customer, rid):
    r = credits.get(rid)
    if not r or r["customer_id"] != customer["id"]:
        not_found("error credit request not found")
    return r


def check_posture(bank):
    if bank["posture"] != "OPERATING":
        raise ApiError("ERR_BANK_NOT_OPERATING", 409,
                       "bank posture %s does not permit this operation" % bank["posture"])


def bad_state(msg="target resource is not in a state permitting this transition"):
    raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, msg)


# ---------------------------------------------------------------------------
# Batch compound status (derived, never directly writable)
# ---------------------------------------------------------------------------

def compound_status(b):
    if b["_compound"] in ("SETTLED", "REJECTED"):
        return b["_compound"]
    if b["_held"]:
        return "HELD"
    if any(i["status"] == "ON_EXCEPTION" for i in items.values() if i["batch_id"] == b["id"]):
        return "DECISIONS_PENDING"
    return b["_compound"]


def batch_pub(b):
    d = pub(b)
    d["batch_status"] = compound_status(b)
    return d


def batch_items(bid):
    return [i for i in items.values() if i["batch_id"] == bid]


# ---------------------------------------------------------------------------
# Availability assignment calculation
# ---------------------------------------------------------------------------

TIER_DAYS = {"SAME_DAY": 0, "ONE_DAY": 1, "TWO_DAY": 2}


def assign_availability(site, item, anchor_date_str):
    elig = [
        s for s in schedules.values()
        if s["site_id"] == site["id"] and s["status"] == "ACTIVE"
        and item["payer_routing_number"].startswith(s["routing_number_pattern"])
        and s["effective_from"] <= anchor_date_str
        and (s["effective_to"] is None or anchor_date_str <= s["effective_to"])
    ]
    if not elig:
        tier = "TWO_DAY"
    else:
        # lowest priority, then later effective_from, then earliest created
        chosen = min(
            elig,
            key=lambda s: (s["priority"],
                           -parse_date(s["effective_from"]).toordinal(),
                           s["created_at"], s["_seq"]),
        )
        tier = chosen["tier"]
    avail = add_business_days(parse_date(anchor_date_str), TIER_DAYS[tier]).isoformat()
    return tier, avail


# ---------------------------------------------------------------------------
# Cycles
# ---------------------------------------------------------------------------

def open_cycle(customer_id):
    for c in cycles.values():
        if c["customer_id"] == customer_id and c["status"] == "OPEN":
            return c
    return None


def last_day_of_month(d):
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def open_new_cycle(bank, customer, cycle_index, start_date, agreement_id):
    end = last_day_of_month(start_date)
    cyc = new_entity({
        "customer_id": customer["id"],
        "bank_id": bank["id"],
        "agreement_id": agreement_id,
        "cycle_index": cycle_index,
        "cycle_start_date": start_date.isoformat(),
        "cycle_end_date": end.isoformat(),
        "average_collected_balance_cents": 0,
        "gross_service_charges_cents": 0,
        "earnings_credit_cents": 0,
        "net_amount_due_cents": 0,
        "accepted_item_count": 0,
        "exception_decision_count": 0,
        "image_retrieval_fulfilled_count": 0,
        "sla_error_count": 0,
        "sla_error_rate_bp": 0,
        "sla_breach": False,
        "sla_credit_cents": 0,
        "status": "OPEN",
        "_finalized_by": None,
        "_settled_by": None,
    })
    cycles[cyc["id"]] = cyc
    return cyc


def active_agreement_for(customer_id):
    cand = [a for a in agreements.values()
            if a["customer_id"] == customer_id and a["status"] == "ACTIVE"]
    if not cand:
        return None
    cand = sorted(cand, key=lambda a: (a["created_at"], a["_seq"]))
    return cand[0]


def emit_line(bank, cyc, kind, qty, unit, extended=None):
    li = new_entity({
        "cycle_id": cyc["id"],
        "bank_id": bank["id"],
        "line_kind": kind,
        "quantity": qty,
        "unit_price_cents": unit,
        "extended_amount_cents": (qty * unit) if extended is None else extended,
    })
    line_items[li["id"]] = li
    return li


def emit_incident(bank, customer_id, kind, occurred, batch_id=None, request_id=None):
    inc = new_entity({
        "customer_id": customer_id,
        "bank_id": bank["id"],
        "cycle_id": None,
        "incident_kind": kind,
        "reference_batch_id": batch_id,
        "reference_request_id": request_id,
        "occurred_on_business_date": occurred,
        "breach_confirmed": False,
        "status": "REPORTED",
    })
    incidents[inc["id"]] = inc
    return inc


def recompute_cycle_sla(bank, cyc):
    cnt = sum(1 for i in incidents.values()
              if i.get("cycle_id") == cyc["id"] and i["breach_confirmed"])
    cyc["sla_error_count"] = cnt
    denom = max(1, cyc["accepted_item_count"] + cyc["exception_decision_count"])
    rate = rhu(Decimal(cnt * 10000) / Decimal(denom))
    cyc["sla_error_rate_bp"] = rate
    breach = rate >= bank["sla_credit_breach_threshold_bp"]
    cyc["sla_breach"] = breach
    cyc["sla_credit_cents"] = (
        rhu(Decimal(cyc["gross_service_charges_cents"]) * Decimal("0.1")) if breach else 0
    )
    net = max(0, cyc["gross_service_charges_cents"] - cyc["earnings_credit_cents"])
    net = max(0, net - cyc["sla_credit_cents"])
    if cyc["status"] == "DISPUTED":
        approved = sum(r["approved_credit_cents"] or 0 for r in credits.values()
                       if r["cycle_id"] == cyc["id"]
                       and r["status"] in ("APPROVED", "PARTIALLY_APPROVED"))
        net = max(0, net - approved)
    cyc["net_amount_due_cents"] = net
    existing = [l for l in line_items.values()
                if l["cycle_id"] == cyc["id"] and l["line_kind"] == "SLA_CREDIT"]
    if breach and not existing:
        emit_line(bank, cyc, "SLA_CREDIT", -1, -cyc["sla_credit_cents"],
                  extended=-cyc["sla_credit_cents"])
    if not breach and existing:
        for l in existing:
            del line_items[l["id"]]
    touch(cyc)


def finalize_cycle(bank, customer, cyc, uid):
    agr = active_agreement_for(customer["id"])
    if agr is None:
        cand = [a for a in agreements.values()
                if a["customer_id"] == customer["id"] and a["status"] != "TERMINATED"]
        cand = sorted(cand, key=lambda a: (a["created_at"], a["_seq"]))
        agr = cand[-1] if cand else None
    cyc["agreement_id"] = agr["id"] if agr else None

    days = customer["days_in_cycle_elapsed"]
    acc = customer["collected_balance_accumulator_cents"]
    avg = 0 if days == 0 else rhu(Decimal(acc) / Decimal(days))
    cyc["average_collected_balance_cents"] = avg

    if agr:
        maint = agr["monthly_maintenance_fee_cents"]
        per_item = agr["per_item_capture_fee_cents"]
        per_exc = agr["per_exception_decision_fee_cents"]
        per_img = agr["per_image_retrieval_fee_cents"]
    else:
        maint = per_item = per_exc = per_img = 0

    # Per-line rounding half-up first, then integer sum.
    gross = (rhu(maint)
             + rhu(cyc["accepted_item_count"] * per_item)
             + rhu(cyc["exception_decision_count"] * per_exc)
             + rhu(cyc["image_retrieval_fulfilled_count"] * per_img))
    cyc["gross_service_charges_cents"] = gross

    if agr and agr["ecr_override_allowed"] and agr["earnings_credit_rate_bp"] is not None:
        ecr_bp = agr["earnings_credit_rate_bp"]
    else:
        ecr_bp = bank["default_earnings_credit_rate_bp"]
    raw = Decimal(avg) * Decimal(ecr_bp) * Decimal(days) / Decimal(360 * 10000)
    ecr = max(0, rhu(raw))
    ecr = min(ecr, gross)
    cyc["earnings_credit_cents"] = ecr

    # Attach incidents occurring within the cycle window.
    for inc in incidents.values():
        if (inc["customer_id"] == customer["id"] and inc["cycle_id"] is None
                and cyc["cycle_start_date"] <= inc["occurred_on_business_date"]
                <= cyc["cycle_end_date"]):
            inc["cycle_id"] = cyc["id"]
            touch(inc)

    cnt = sum(1 for i in incidents.values()
              if i.get("cycle_id") == cyc["id"] and i["breach_confirmed"])
    cyc["sla_error_count"] = cnt
    denom = max(1, cyc["accepted_item_count"] + cyc["exception_decision_count"])
    rate = rhu(Decimal(cnt * 10000) / Decimal(denom))
    cyc["sla_error_rate_bp"] = rate
    breach = rate >= bank["sla_credit_breach_threshold_bp"]
    cyc["sla_breach"] = breach
    sla_credit = rhu(Decimal(gross) * Decimal("0.1")) if breach else 0
    cyc["sla_credit_cents"] = sla_credit

    net = max(0, gross - ecr)
    net = max(0, net - sla_credit)
    cyc["net_amount_due_cents"] = net

    cyc["status"] = "FINALIZED"
    cyc["_finalized_by"] = uid
    touch(cyc)

    # Statement line items.
    emit_line(bank, cyc, "MAINTENANCE", 1, maint)
    emit_line(bank, cyc, "PER_ITEM_CAPTURE", cyc["accepted_item_count"], per_item)
    emit_line(bank, cyc, "PER_EXCEPTION_DECISION", cyc["exception_decision_count"], per_exc)
    emit_line(bank, cyc, "PER_IMAGE_RETRIEVAL", cyc["image_retrieval_fulfilled_count"], per_img)
    if breach:
        emit_line(bank, cyc, "SLA_CREDIT", -1, -sla_credit, extended=-sla_credit)

    # Confirmed incidents attached to a breaching cycle become CREDITED.
    if breach:
        for inc in incidents.values():
            if inc.get("cycle_id") == cyc["id"] and inc["status"] == "CONFIRMED":
                inc["status"] = "CREDITED"
                touch(inc)

    # Reset per-cycle accumulators and open the next cycle.
    customer["collected_balance_accumulator_cents"] = 0
    customer["days_in_cycle_elapsed"] = 0
    customer["average_collected_balance_cents"] = 0
    touch(customer)
    next_start = parse_date(cyc["cycle_end_date"]) + timedelta(days=1)
    # The fresh OPEN cycle takes no agreement reference yet (PRD §3.7: the
    # reference is to the ACTIVE agreement at close).
    open_new_cycle(bank, customer, cyc["cycle_index"] + 1, next_start, None)


# ---------------------------------------------------------------------------
# Exception decisioning
# ---------------------------------------------------------------------------

def apply_decision(bank, ex, decision, decider, decided_at, auto):
    ex["decision"] = decision
    ex["decided_by_user_id"] = decider
    ex["decided_at"] = decided_at
    ex["status"] = "AUTO_DECISIONED" if auto else "DECIDED"
    touch(ex)

    it = items[ex["item_id"]]
    b = batches[ex["batch_id"]]
    site = sites[b["site_id"]]
    if decision == "PAY":
        it["status"] = "DECISIONED_PAY"
        anchor = bank["current_business_date"]
        tier, avail = assign_availability(site, it, anchor)
        it["availability_tier"] = tier
        it["availability_date"] = avail
        b["accepted_item_count"] += 1
        b["accepted_total_cents"] += it["amount_cents"]
        if tier == "SAME_DAY":
            b["same_day_credit_cents"] += it["amount_cents"]
        cyc = open_cycle(ex["customer_id"])
        if cyc:
            cyc["accepted_item_count"] += 1
            touch(cyc)
    else:
        it["status"] = "DECISIONED_RETURN"
    touch(it)
    touch(b)

    cyc = open_cycle(ex["customer_id"])
    if cyc:
        cyc["exception_decision_count"] += 1
        touch(cyc)

    remaining = [e for e in exceptions.values()
                 if e["batch_id"] == b["id"] and e["status"] in ("PENDING", "ESCALATED")]
    if not remaining and b["capture_status"] == "CLOSED" and b["_compound"] == "OPEN":
        b["_compound"] = "READY_TO_SETTLE"
        touch(b)


def auto_decision_moment(bank, site, extra_days=2):
    base = add_business_days(parse_date(bank["current_business_date"]), extra_days)
    hh, mm = (int(x) for x in site["daily_cutoff_time_local"].split(":"))
    dt = datetime.combine(base, dtime(hh, mm), tzinfo=ZoneInfo(site["timezone"]))
    return dt, base.isoformat()


# ---------------------------------------------------------------------------
# Business-day checkpoint
# ---------------------------------------------------------------------------

def run_day_close(bank):
    cur = add_business_days(parse_date(bank["current_business_date"]), 1)
    bank["current_business_date"] = cur.isoformat()
    cur_s = bank["current_business_date"]

    # 1. Auto-decide stale exceptions.
    for ex in list(exceptions.values()):
        if (ex["bank_id"] == bank["id"] and ex["status"] in ("PENDING", "ESCALATED")
                and ex["_auto_date"] <= cur_s):
            apply_decision(bank, ex, ex["default_decision"], "system",
                           ex["auto_decision_at"], True)

    # 2. Expire stale image requests (> 30 calendar days old, still REQUESTED).
    for r in list(image_requests.values()):
        if r["bank_id"] == bank["id"] and r["status"] == "REQUESTED":
            created_d = parse_dt(r["created_at"]).date()
            if (cur - created_d).days > 30:
                r["status"] = "EXPIRED"
                touch(r)
                emit_incident(bank, r["customer_id"], "LATE_IMAGE_FULFILLMENT",
                              cur_s, request_id=r["id"])

    # 3. Settle or reject READY_TO_SETTLE batches.
    day_collected = {}
    for b in list(batches.values()):
        if b["bank_id"] != bank["id"]:
            continue
        if b["_held"] or b["_compound"] != "READY_TO_SETTLE":
            continue
        bitems = batch_items(b["id"])
        accepted = [i for i in bitems if i["status"] in ("ACCEPTED", "DECISIONED_PAY")]
        if b["transmission_status"] == "ACKED":
            b["_compound"] = "SETTLED"
            touch(b)
            for i in accepted:
                if i["availability_date"] and i["availability_date"] <= cur_s:
                    day_collected[b["customer_id"]] = (
                        day_collected.get(b["customer_id"], 0) + i["amount_cents"])
        elif bitems and all(i["status"] in ("RETURNED", "DECISIONED_RETURN")
                            for i in bitems):
            b["_compound"] = "REJECTED"
            touch(b)

    # 4. Collected-balance accumulation for every ACTIVE customer.
    for c in customers.values():
        if c["bank_id"] == bank["id"] and c["status"] == "ACTIVE":
            c["collected_balance_accumulator_cents"] += day_collected.get(c["id"], 0)
            c["days_in_cycle_elapsed"] += 1
            days = c["days_in_cycle_elapsed"]
            acc = c["collected_balance_accumulator_cents"]
            c["average_collected_balance_cents"] = (
                0 if days == 0 else rhu(Decimal(acc) / Decimal(days)))
            touch(c)

    touch(bank)
