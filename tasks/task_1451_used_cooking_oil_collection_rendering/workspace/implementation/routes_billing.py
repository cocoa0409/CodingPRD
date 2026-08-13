"""Routes: market index quotes and settlements (PRD 3.7, 2.10)."""

from flask import Blueprint, request

import calc
import serialize
from db import parse_date, store
from errors import err
from helpers import (
    CONTRACT_ACTIVE_ERA,
    cc_check,
    fk_exists,
    get_quote,
    get_settlement,
    get_body,
    paginate,
    req_date,
    req_num,
    req_str,
    require_roles,
    sorted_items,
)
from response import success

bp = Blueprint("billing", __name__)

QUOTE_STATUSES = {"DRAFT", "PUBLISHED", "SUPERSEDED"}


# ---------------------------------------------------------------------------
# Market index quotes (PRD 3.7)
# ---------------------------------------------------------------------------
@bp.route("/api/market-index-quotes", methods=["POST"])
@require_roles("BillingAnalyst")
def create_quote():
    body = get_body()
    rec = {
        "id": store.new_id(),
        "index_code": req_str(body, "index_code"),
        "week_start": req_date(body, "week_start"),
        "price_cents_per_gal": req_num(body, "price_cents_per_gal"),
        "status": "DRAFT",
        "published_at": None,
    }
    store.stamp(rec)
    store.quotes[rec["id"]] = rec
    return success(serialize.quote(rec), code=201)


@bp.route("/api/market-index-quotes/<qid>/publish", methods=["POST"])
@require_roles("BillingAnalyst")
def publish_quote(qid):
    rec = get_quote(qid)
    if rec["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Quote %s is %s; only DRAFT can publish" % (qid, rec["status"]))
    # Supersede any other PUBLISHED quote of the same index and week.
    for other in store.quotes.values():
        if (
            other["id"] != qid
            and other["status"] == "PUBLISHED"
            and other["index_code"] == rec["index_code"]
            and other["week_start"] == rec["week_start"]
        ):
            other["status"] = "SUPERSEDED"
            store.bump(other)
    rec["status"] = "PUBLISHED"
    rec["published_at"] = store.now_iso()
    store.bump(rec)
    # Cascade: recompute PROVISIONAL settlements priced against this index.
    for settlement in sorted_items(store.settlements.values()):
        if settlement["status"] != "PROVISIONAL":
            continue
        contract = calc.pricing_contract_for(settlement["customer_id"], settlement["period_start"])
        if contract is None or contract["index_code"] != rec["index_code"]:
            continue
        _recompute_provisional_lines(settlement, contract)
    return success(serialize.quote(rec))


def _recompute_provisional_lines(settlement, contract):
    lines = [
        l for l in sorted_items(store.lines.values())
        if l["settlement_id"] == settlement["id"]
    ]
    for line in lines:
        visit = store.visits[line["pickup_visit_id"]]
        price = calc.provisional_index_price(contract["index_code"], visit["scheduled_date"])
        grade = calc.moisture_dim(visit["field_moisture_pct"])
        rate, amount = calc.line_amount(contract, price, grade, line["gallons_billed"])
        line["rate_cents_per_gal"] = rate
        line["line_amount_cents"] = amount
        store.bump(line)
    settlement["provisional_total_cents"] = sum(l["line_amount_cents"] for l in lines)
    store.bump(settlement)


@bp.route("/api/market-index-quotes", methods=["GET"])
@require_roles("SystemAdmin", "FieldOpsManager", "BillingAnalyst")
def list_quotes():
    items = sorted_items(store.quotes.values())
    index_code = request.args.get("index_code")
    if index_code is not None:
        items = [q for q in items if q["index_code"] == index_code]
    week_start = request.args.get("week_start")
    if week_start is not None:
        try:
            week_start = parse_date(week_start).isoformat()
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION", "Query parameter 'week_start' must be an ISO date")
        items = [q for q in items if q["week_start"] == week_start]
    status = request.args.get("status")
    if status is not None:
        if status not in QUOTE_STATUSES:
            raise err("ERR_VALIDATION", "Query parameter 'status' must be one of %s" % sorted(QUOTE_STATUSES))
        items = [q for q in items if q["status"] == status]
    page, meta = paginate(items)
    return success([serialize.quote(q) for q in page], response_type="array", pagination=meta)


# ---------------------------------------------------------------------------
# Settlements (PRD 3.7)
# ---------------------------------------------------------------------------
def _eligible_visits(customer_id, period_start, period_end):
    container_ids = {
        c["id"] for c in store.containers.values() if c["customer_id"] == customer_id
    }
    return [
        v for v in sorted_items(store.visits.values())
        if v["container_id"] in container_ids
        and v["status"] == "COMPLETED"
        and period_start <= v["scheduled_date"] < period_end
    ]


@bp.route("/api/settlements/generate", methods=["POST"])
@require_roles("BillingAnalyst")
def generate_settlement():
    body = get_body()
    customer_id = req_str(body, "customer_id")
    period_start = req_date(body, "period_start")
    period_end = req_date(body, "period_end")
    fk_exists(store.customers, customer_id, "customer_id")
    for other in store.settlements.values():
        if (
            other["customer_id"] == customer_id
            and other["status"] != "VOID"
            and other["period_start"] < period_end
            and period_start < other["period_end"]
        ):
            raise err("ERR_DUPLICATE_PERIOD", "A non-VOID settlement already overlaps the period")
    if store.clock_date() < parse_date(period_end):
        raise err("ERR_PERIOD_NOT_CLOSED", "Billing period [%s, %s) is not closed" % (period_start, period_end))
    visits = _eligible_visits(customer_id, period_start, period_end)
    contract = calc.pricing_contract_for(customer_id, period_start)
    if contract is None and visits:
        raise err("ERR_CONTRACT_NOT_ACTIVE", "Customer %s has no pricing contract" % customer_id)
    # Resolve every line before persisting anything: quote coverage is
    # all-or-nothing for the generation request (ERR_QUOTE_NOT_PUBLISHED).
    planned = []
    for visit in visits:
        price = calc.provisional_index_price(contract["index_code"], visit["scheduled_date"])
        grade = calc.moisture_dim(visit["field_moisture_pct"])
        gallons = visit["net_gallons_provisional"]
        rate, amount = calc.line_amount(contract, price, grade, gallons)
        planned.append((visit, gallons, rate, amount))
    settlement = {
        "id": store.new_id(),
        "customer_id": customer_id,
        "period_start": period_start,
        "period_end": period_end,
        "status": "PROVISIONAL",
        "provisional_total_cents": sum(p[3] for p in planned),
        "final_total_cents": 0,
        "paid_at": None,
    }
    store.stamp(settlement)
    store.settlements[settlement["id"]] = settlement
    for visit, gallons, rate, amount in planned:
        line = {
            "id": store.new_id(),
            "settlement_id": settlement["id"],
            "pickup_visit_id": visit["id"],
            "variant": "PROVISIONAL",
            "pricing_mode": contract["pricing_mode"],
            "gallons_billed": gallons,
            "rate_cents_per_gal": rate,
            "line_amount_cents": amount,
        }
        store.stamp(line)
        store.lines[line["id"]] = line
    return success(serialize.settlement(settlement), code=201)


@bp.route("/api/settlements/<sid>", methods=["GET"])
@require_roles("SystemAdmin", "BillingAnalyst", "CustomerContact")
def get_one_settlement(sid):
    rec = get_settlement(sid)
    cc_check(rec["customer_id"])
    return success(serialize.settlement(rec))


@bp.route("/api/settlements/<sid>/lines", methods=["GET"])
@require_roles("SystemAdmin", "BillingAnalyst", "CustomerContact")
def list_settlement_lines(sid):
    rec = get_settlement(sid)
    cc_check(rec["customer_id"])
    items = [l for l in sorted_items(store.lines.values()) if l["settlement_id"] == sid]
    page, meta = paginate(items)
    return success([serialize.line(l) for l in page], response_type="array", pagination=meta)


@bp.route("/api/settlements/<sid>/finalize", methods=["POST"])
@require_roles("BillingAnalyst")
def finalize_settlement(sid):
    rec = get_settlement(sid)
    if rec["status"] != "PROVISIONAL":
        raise err("ERR_INVALID_STATE", "Settlement %s is %s; only PROVISIONAL can finalize" % (sid, rec["status"]))
    contract = calc.pricing_contract_for(rec["customer_id"], rec["period_start"])
    if contract is None or contract["status"] not in CONTRACT_ACTIVE_ERA:
        raise err(
            "ERR_CONTRACT_NOT_ACTIVE",
            "Pricing contract is %s; finalize requires ACTIVE, AT_RISK or RENEWAL_OFFERED"
            % (contract["status"] if contract else "missing"),
        )
    if store.clock_date() < parse_date(rec["period_end"]):
        raise err("ERR_PERIOD_NOT_CLOSED", "Billing period [%s, %s) is not closed" % (rec["period_start"], rec["period_end"]))
    lines = [l for l in sorted_items(store.lines.values()) if l["settlement_id"] == sid]
    samples = {}
    for line in lines:
        sample = calc.graded_sample_for(line["pickup_visit_id"])
        if sample is None:
            raise err("ERR_GRADE_PENDING", "Pickup %s has no GRADED quality sample" % line["pickup_visit_id"])
        samples[line["pickup_visit_id"]] = sample
    final_price = calc.final_index_price(contract["index_code"], rec["period_start"], rec["period_end"])
    for line in lines:
        visit = store.visits[line["pickup_visit_id"]]
        sample = samples[line["pickup_visit_id"]]
        gallons = calc.net_final(visit["pump_gallons"], sample["lab_moisture_pct"])
        rate, amount = calc.line_amount(contract, final_price, sample["grade"], gallons)
        line["variant"] = "FINAL"
        line["gallons_billed"] = gallons
        line["rate_cents_per_gal"] = rate
        line["line_amount_cents"] = amount
        store.bump(line)
    rec["final_total_cents"] = sum(l["line_amount_cents"] for l in lines)
    rec["status"] = "FINALIZED"
    store.bump(rec)
    return success(serialize.settlement(rec))


@bp.route("/api/settlements/<sid>/pay", methods=["POST"])
@require_roles("BillingAnalyst")
def pay_settlement(sid):
    rec = get_settlement(sid)
    if rec["status"] != "FINALIZED":
        raise err("ERR_INVALID_STATE", "Settlement %s is %s; only FINALIZED can be paid" % (sid, rec["status"]))
    if rec["final_total_cents"] < calc.MIN_PAYOUT_CENTS:
        raise err(
            "ERR_PAYOUT_BELOW_MINIMUM",
            "final_total_cents %s is below the 100-cent payout floor" % rec["final_total_cents"],
        )
    rec["paid_at"] = store.now_iso()
    rec["status"] = "PAID"
    store.bump(rec)
    return success(serialize.settlement(rec))


@bp.route("/api/settlements/<sid>/void", methods=["POST"])
@require_roles("BillingAnalyst")
def void_settlement(sid):
    rec = get_settlement(sid)
    body = get_body()
    req_str(body, "reason")
    if rec["status"] not in ("PROVISIONAL", "FINALIZED"):
        raise err("ERR_INVALID_STATE", "Settlement %s is %s; void requires PROVISIONAL or FINALIZED" % (sid, rec["status"]))
    # The ledger is derived: VOID drops final_total_cents from the balance
    # automatically, so a FINALIZED void is the exact reversal (PRD 2.10).
    rec["status"] = "VOID"
    store.bump(rec)
    return success(serialize.settlement(rec))
