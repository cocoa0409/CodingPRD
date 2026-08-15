"""Shared record helpers: creation, mutation stamping, serializers, ledger."""

from db import store, next_seq, take_stamp, clock
from errors import ApiError
from util import new_id, fmt_dt
import calc


def touch(rec):
    rec["version"] = rec.get("version", 0) + 1
    rec["updated_at"] = fmt_dt(take_stamp())


def new_record(coll, fields):
    rec = dict(fields)
    rec["id"] = new_id()
    ts = fmt_dt(take_stamp())
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next_seq()
    store[coll][rec["id"]] = rec
    return rec


def get_or_404(coll, rid, err_id, label):
    rec = store[coll].get(rid)
    if rec is None:
        raise ApiError(err_id, 404, f"{label} not found: {rid}")
    return rec


def bump_unit_status(unit, status):
    unit["status"] = status
    touch(unit)


# ---- dynamic part counters ----

def part_available_count(part_id):
    return sum(1 for u in store["units"].values()
               if u["part_id"] == part_id and u["status"] == "AVAILABLE")


def part_reserved_count(part_id):
    return sum(1 for u in store["units"].values()
               if u["part_id"] == part_id and u["status"] == "RESERVED")


# ---- ledger ----

def recompute_balance(customer):
    total = 0
    for e in store["ledger"].values():
        if e["customer_id"] != customer["id"]:
            continue
        if e["entry_type"] in calc.DEBIT_TYPES:
            total += e["amount_cents"]
        else:
            total -= e["amount_cents"]
    customer["outstanding_balance_cents"] = total


def post_ledger(customer_id, entry_type, amount_cents, reference_type,
                reference_id, memo=None):
    """Append a ledger entry; recompute the balance and advance the customer
    version atomically with the posting. Zero amounts are not posted."""
    if amount_cents <= 0:
        return None
    customer = store["customers"][customer_id]
    ts = fmt_dt(take_stamp())
    entry = {
        "id": new_id(),
        "customer_id": customer_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "reference_type": reference_type,
        "reference_id": reference_id,
        "memo": memo,
        "created_at": ts,
        "_seq": next_seq(),
    }
    store["ledger"][entry["id"]] = entry
    recompute_balance(customer)
    touch(customer)
    return entry


# ---- quote helpers ----

def effective_quote_status(quote):
    """Lazy expiry: an ISSUED quote past expires_at is treated as EXPIRED."""
    if quote["status"] == "ISSUED" and quote.get("_expires_dt") is not None \
            and clock.current > quote["_expires_dt"]:
        return "EXPIRED"
    return quote["status"]


def quote_core_deposits(quote):
    total = 0
    for ln in quote["lines"]:
        if ln["sale_type"] == "EXCHANGE":
            part = store["parts"][ln["part_id"]]
            total += part["core_value_cents"] * ln["quantity"]
    return total


def recompute_quote(quote):
    """Recompute all computed price fields. DRAFT uses the customer's current
    tier; ISSUED+ uses the tier_at_issue snapshot."""
    customer = store["customers"][quote["customer_id"]]
    tier = quote["tier_at_issue"] or customer["priority_tier"]
    subtotal, handling, tier_fee, total = calc.quote_pricing(quote["lines"], tier)
    quote["subtotal_cents"] = subtotal
    quote["handling_fee_cents"] = handling
    quote["tier_fee_cents"] = tier_fee
    quote["total_cents"] = total
    req = store["requests"].get(quote["aog_request_id"])
    escalated = bool(req and req["escalated"])
    hazmat = any(
        store["parts"][ln["part_id"]]["hazmat_class"] != "NONE"
        for ln in quote["lines"]
    )
    quote["freight_cost_cents"] = calc.freight_cost(
        quote["freight_mode"], quote["distance_km"],
        quote["chargeable_weight_kg"], hazmat, escalated)
    quote["max_penalty_cents"] = quote_core_deposits(quote)


# ---- order closure cascade ----

def order_lines_of(order_id):
    return [l for l in store["order_lines"].values() if l["order_id"] == order_id]


def maybe_close_order(order):
    """DELIVERED -> CLOSED once every derived CoreReturn and LoanAgreement
    is SETTLED; cascades the request FULFILLED -> CLOSED."""
    if order["fulfillment_status"] != "DELIVERED":
        return
    lines = order_lines_of(order["id"])
    line_ids = {l["id"] for l in lines}
    crs = [c for c in store["core_returns"].values()
           if c["order_line_id"] in line_ids]
    loans = [l for l in store["loans"].values()
             if l.get("order_line_id") in line_ids]
    if all(c["status"] == "SETTLED" for c in crs) and \
            all(l["status"] == "SETTLED" for l in loans):
        order["fulfillment_status"] = "CLOSED"
        touch(order)
        quote = store["quotes"].get(order["quote_id"])
        if quote:
            req = store["requests"].get(quote["aog_request_id"])
            if req and req["status"] == "FULFILLED":
                req["status"] = "CLOSED"
                touch(req)


# ---- serializers (declared fields only) ----

def _pick(rec, fields):
    return {k: rec.get(k) for k in fields}


COMMON = ["id", "created_at", "updated_at", "version"]


def ser_customer(c):
    return _pick(c, ["id", "name", "country_code", "credit_limit_cents",
                     "outstanding_balance_cents", "priority_tier",
                     "core_returns_settled_180d", "core_returns_on_time_180d",
                     "warranty_fraud_flags", "status", "created_at",
                     "updated_at", "version"])


def ser_part(p):
    out = _pick(p, ["id", "part_number", "description", "rotable",
                    "hazmat_class", "export_control_code", "list_price_cents",
                    "core_value_cents", "warranty_months", "created_at",
                    "updated_at", "version"])
    out["available_count"] = part_available_count(p["id"])
    out["reserved_count"] = part_reserved_count(p["id"])
    return out


def ser_unit(u):
    return _pick(u, ["id", "part_id", "serial_number", "condition",
                     "trace_doc_level", "warehouse_code", "status",
                     "reserved_by_request_id", "created_at", "updated_at",
                     "version"])


def ser_request(r):
    return _pick(r, ["id", "customer_id", "aircraft_tail", "airport_code",
                     "part_id", "quantity", "condition_acceptable",
                     "min_trace_doc", "needed_by_utc", "escalated", "status",
                     "reserved_unit_id", "last_search_candidate_count",
                     "created_at", "updated_at", "version"])


def ser_quote(q):
    return _pick(q, ["id", "aog_request_id", "customer_id", "lines",
                     "validity_hours", "freight_mode", "distance_km",
                     "chargeable_weight_kg", "destination_country",
                     "revision_count", "status", "tier_at_issue", "issued_at",
                     "expires_at", "subtotal_cents", "handling_fee_cents",
                     "tier_fee_cents", "freight_cost_cents", "total_cents",
                     "max_penalty_cents", "created_at", "updated_at",
                     "version"])


def ser_order(o):
    return _pick(o, ["id", "quote_id", "customer_id", "fulfillment_status",
                     "compliance_status", "payment_status", "invoiced_cents",
                     "freight_mode", "distance_km", "chargeable_weight_kg",
                     "destination_country", "created_at", "updated_at",
                     "version"])


def ser_order_line(l):
    return _pick(l, ["id", "order_id", "part_id", "quantity", "sale_type",
                     "condition_required", "unit_price_cents", "discount_pct",
                     "line_total_cents", "lease_periods", "allocated_unit_id",
                     "allocation_status", "delivered_at", "created_at",
                     "updated_at", "version"])


def ser_shipment(s):
    return _pick(s, ["id", "order_id", "hazmat_declaration_ref",
                     "export_license_ref", "depart_at", "arrive_at",
                     "charter_slot_id", "freight_cost_cents", "status",
                     "created_at", "updated_at", "version"])


def ser_charter_slot(s):
    return _pick(s, ["id", "tail_number", "home_base", "status", "created_at",
                     "updated_at", "version"])


def ser_core_return(c):
    return _pick(c, ["id", "order_line_id", "customer_id", "core_value_cents",
                     "due_at", "received_at", "days_overdue", "penalty_cents",
                     "refunded_cents", "penalty_retained_cents",
                     "forfeited_cents", "penalty_waived_cents", "status",
                     "verdict", "created_at", "updated_at", "version"])


def ser_loan(l):
    return _pick(l, ["id", "customer_id", "unit_id", "order_line_id",
                     "loan_type", "daily_rate_cents", "lease_periods",
                     "start_at", "due_at", "returned_at", "billed_cents",
                     "status", "created_at", "updated_at", "version"])


def ser_claim(c):
    return _pick(c, ["id", "customer_id", "order_line_id", "fault_category",
                     "description", "months_in_service", "coverage_pct",
                     "credit_cents", "reviewed_by", "reopen_count",
                     "fraud_flag", "status", "created_at", "updated_at",
                     "version"])


def ser_rma(r):
    return _pick(r, ["id", "customer_id", "order_line_id", "reason",
                     "days_since_delivery", "restock_fee_cents", "credit_cents",
                     "condition_grade", "status", "created_at", "updated_at",
                     "version"])


def ser_ledger(e):
    return _pick(e, ["id", "customer_id", "entry_type", "amount_cents",
                     "reference_type", "reference_id", "memo", "created_at"])


def sort_asc(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def sort_desc(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]),
                  reverse=True)


def scope_for_contact(records, role, uid, customer_of):
    """CustomerContact list scoping: only rows of their own customer."""
    if role != "CustomerContact":
        return records
    return [r for r in records if customer_of(r) == uid]
