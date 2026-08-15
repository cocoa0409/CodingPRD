"""Cross-entity services: serialization, lookups, recomputes, bubble-ups and
the order-cancellation compensating cascade (PRD 2.10, 3.4)."""

from datetime import timedelta

from db import bump, create_record, new_id, next_seq, now, store
from errors import fail
from response import fmt_dt
import calc

ACTIVE_JOB_STATUSES = ("SCHEDULED", "DELAYED", "EN_ROUTE")
NON_TERMINAL_ORDER_STATUSES = None  # computed inline: not in {CLOSED, CANCELLED}


def ser(rec):
    """Serialize a record: drop internal keys, format datetimes."""
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        out[k] = fmt_dt(v) if hasattr(v, "astimezone") else v
    return out


def ser_crew(crew):
    out = ser(crew)
    out["booked_dates"] = crew_booked_dates(crew["id"])
    return out


def get_or_404(table, rid, error_id, label):
    rec = table.get(rid) if isinstance(rid, str) else None
    if rec is None:
        fail(error_id, f"{label} not found")
    return rec


def order_is_live(order):
    return order["deal_status"] not in ("CLOSED", "CANCELLED")


def bump_order(order):
    bump(order)


# ---------------------------------------------------------------- pricing --

def recompute_order_pricing(order):
    """calc order_line_pricing + doc_fee on any pricing mutation."""
    active = [o for o in store.order_options.values()
              if o["sales_order_id"] == order["id"] and o["status"] == "ACTIVE"]
    r = calc.price_order(order["agreed_home_price_cents"],
                         [o["line_total_cents"] for o in active])
    order["options_total_cents"] = r["options_total_cents"]
    order["discount_cents"] = r["discount_cents"]
    order["doc_fee_cents"] = r["doc_fee_cents"]
    order["total_price_cents"] = r["total_price_cents"]
    order["amount_financed_cents"] = max(
        0, r["total_price_cents"] - order["deposit_cents"] - order["trade_in_credit_cents"])


def recompute_amount_financed(order):
    order["amount_financed_cents"] = max(
        0, order["total_price_cents"] - order["deposit_cents"] - order["trade_in_credit_cents"])


def recompute_delay_compensation(order):
    """Sum compensation over notices linked directly to the order or via its
    transport jobs (calc delay_compensation aggregate)."""
    job_ids = {j["id"] for j in store.transport_jobs.values()
               if j["sales_order_id"] == order["id"]}
    order["delay_compensation_cents"] = sum(
        n["compensation_cents"] for n in store.delay_notices.values()
        if n["sales_order_id"] == order["id"]
        or (n["transport_job_id"] is not None and n["transport_job_id"] in job_ids))


def recompute_transport_charge(order):
    """Quoted cost of the latest non-CANCELLED TransportJob; 0 before booking."""
    jobs = [j for j in store.transport_jobs.values()
            if j["sales_order_id"] == order["id"] and j["status"] != "CANCELLED"]
    jobs.sort(key=lambda j: j["_seq"])
    order["transport_charge_cents"] = jobs[-1]["quoted_cost_cents"] if jobs else 0


# ------------------------------------------------------------------ crews --

def crew_booked_dates(crew_id):
    dates = set()
    for j in store.transport_jobs.values():
        if j["crew_id"] == crew_id and j["status"] in ACTIVE_JOB_STATUSES:
            for d in calc.window_dates(j["scheduled_start_date"], j["sections_count"]):
                dates.add(d.isoformat())
    return sorted(dates)


def crew_window_has_capacity(crew, start_dt, sections_count, exclude_job_id=None):
    """calc crew_day_capacity: half-open windows, per-date section loads."""
    wanted = calc.window_dates(start_dt, sections_count)
    for d in wanted:
        load = 0
        for j in store.transport_jobs.values():
            if (j["crew_id"] != crew["id"] or j["id"] == exclude_job_id
                    or j["status"] not in ACTIVE_JOB_STATUSES):
                continue
            if d in calc.window_dates(j["scheduled_start_date"], j["sections_count"]):
                load += j["sections_count"]
        if load + sections_count > crew["max_sections_per_window"]:
            return False
    return True


# -------------------------------------------------------- evaluation/financing

def latest_open_evaluation(order_id):
    evs = [e for e in store.site_evaluations.values()
           if e["sales_order_id"] == order_id and e["status"] != "SUPERSEDED"]
    if not evs:
        return None
    return max(evs, key=lambda e: e["_seq"])


def bubble_evaluation_approved(ev):
    order = store.sales_orders.get(ev["sales_order_id"])
    if order is None:
        return
    if latest_open_evaluation(order["id"]) is ev and order["deal_status"] == "PENDING_SITE_EVAL":
        order["deal_status"] = "SITE_APPROVED"
        bump_order(order)


def bubble_evaluation_rejected(ev):
    order = store.sales_orders.get(ev["sales_order_id"])
    if order is None:
        return
    if (latest_open_evaluation(order["id"]) is ev
            and order["deal_status"] in ("PENDING_SITE_EVAL", "SITE_APPROVED")):
        order["deal_status"] = "DRAFT"
        bump_order(order)


def bubble_financing_approved(app):
    order = store.sales_orders.get(app["sales_order_id"])
    if order is not None and order["deal_status"] == "PENDING_FINANCING":
        order["deal_status"] = "FINANCING_APPROVED"
        bump_order(order)


def bubble_financing_funded(app):
    order = store.sales_orders.get(app["sales_order_id"])
    if order is not None and order["deal_status"] == "FINANCING_APPROVED":
        order["deal_status"] = "AWAITING_DELIVERY"
        order["payment_status"] = "FINANCED"
        bump_order(order)


# ------------------------------------------------------------------ titles --

def find_issued_title(unit_id, title_type=None):
    matches = [t for t in store.title_records.values()
               if t["home_unit_id"] == unit_id and t["status"] == "ISSUED"
               and (title_type is None or t["title_type"] == title_type)]
    matches.sort(key=lambda t: t["_seq"])
    return matches[-1] if matches else None


def order_for_unit(unit):
    if unit.get("sales_order_id"):
        return store.sales_orders.get(unit["sales_order_id"])
    return None


def bubble_title_event(unit):
    """A qualifying title event lifts a SET_COMPLETE order to TITLED."""
    order = order_for_unit(unit)
    if order is not None and order["deal_status"] == "SET_COMPLETE":
        order["deal_status"] = "TITLED"
        bump_order(order)


def maybe_chain_titled_on_set_complete(order):
    """Chained auto-transition: when set completion lands the order in
    SET_COMPLETE and a qualifying ISSUED title already exists for a CHATTEL
    deal, the order advances immediately to TITLED in the same request."""
    if order["deal_status"] == "SET_COMPLETE" and order["financing_type"] == "CHATTEL":
        if find_issued_title(order["home_unit_id"], "MANUFACTURED_CERTIFICATE") is not None:
            order["deal_status"] = "TITLED"


# ------------------------------------------------------------ cancellation --

def cancel_order_cascade(order):
    """Compensating cascade (PRD 3.4): unit release, lot release, job
    cancellation (restoring crew capacity), evaluation/application
    supersession, deposit refund."""
    unit = store.home_units.get(order["home_unit_id"])
    if unit is not None and unit["status"] == "RESERVED" and unit["sales_order_id"] == order["id"]:
        unit["status"] = "AT_DEALER"
        unit["sales_order_id"] = None
        bump(unit)
    if order["placement_type"] == "COMMUNITY_LOT" and order.get("lot_id"):
        lot = store.lots.get(order["lot_id"])
        if lot is not None and lot["status"] == "RESERVED":
            lot["status"] = "AVAILABLE"
            bump(lot)
    for j in store.transport_jobs.values():
        if j["sales_order_id"] == order["id"] and j["status"] in ("SCHEDULED", "DELAYED"):
            j["status"] = "CANCELLED"
            bump(j)
    recompute_transport_charge(order)
    for e in store.site_evaluations.values():
        if e["sales_order_id"] == order["id"] and e["status"] in ("SCHEDULED", "FINDINGS_RECORDED"):
            e["status"] = "SUPERSEDED"
            bump(e)
    for a in store.financing_applications.values():
        if (a["sales_order_id"] == order["id"]
                and a["status"] in ("DRAFT", "SUBMITTED", "CONDITIONALLY_APPROVED", "APPROVED")):
            a["status"] = "SUPERSEDED"
            bump(a)
    if order["payment_status"] == "DEPOSIT_PAID" and order["deposit_cents"] > 0:
        order["payment_status"] = "REFUNDED"
    order["deal_status"] = "CANCELLED"
    bump_order(order)


# ---------------------------------------------------------------- trade-in --

def mint_trade_in_serial():
    while True:
        serial = "TI-" + new_id().replace("-", "").upper()[:16]
        if all(u["serial_number"] != serial for u in store.home_units.values()):
            return serial


def accept_trade_in(appraisal):
    """Three-deep cascade (PRD 3.9): create the trade-in unit, set the order's
    credit and recompute amount financed, then recompute the order's active
    DRAFT/SUBMITTED financing application."""
    order = store.sales_orders[appraisal["sales_order_id"]]
    unit = create_record(store.home_units, {
        "model_id": appraisal["model_id"],
        "serial_number": mint_trade_in_serial(),
        "unit_kind": "TRADE_IN",
        "condition_grade": appraisal["condition_grade"],
        "status": "AT_DEALER",
        "lot_id": None,
        "sales_order_id": None,
        "delivered_at": None,
        "set_completed_at": None,
    })
    appraisal["trade_in_unit_id"] = unit["id"]
    appraisal["status"] = "ACCEPTED"
    bump(appraisal)
    order["trade_in_credit_cents"] = appraisal["final_credit_cents"]
    recompute_amount_financed(order)
    bump_order(order)
    for a in store.financing_applications.values():
        if a["sales_order_id"] == order["id"] and a["status"] in ("DRAFT", "SUBMITTED"):
            a["requested_amount_cents"] = order["amount_financed_cents"]
            a["estimated_payment_cents"] = calc.annuity_payment_cents(
                a["requested_amount_cents"], calc.rate_floor_bps(a["financing_type"]),
                a["term_months"])
            bump(a)
    return unit


def record_delay_notice(transport_job_id, sales_order_id, reason, original_dt, new_dt, buyer_notified):
    days = calc.whole_delay_days(original_dt, new_dt)
    rec = {
        "id": new_id(),
        "created_at": now(),
        "_seq": next_seq(),
        "transport_job_id": transport_job_id,
        "sales_order_id": sales_order_id,
        "reason": reason,
        "original_date": original_dt,
        "new_date": new_dt,
        "buyer_notified": buyer_notified,
        "delay_days": days,
        "compensation_cents": calc.delay_compensation_cents(days),
    }
    store.delay_notices[rec["id"]] = rec
    return rec


def unit_open_title_exists(unit_id):
    return any(t["home_unit_id"] == unit_id and t["status"] in ("APPLIED", "ISSUED")
               for t in store.title_records.values())


def lead_time_elapsed(unit, model):
    return now() >= unit["created_at"] + timedelta(days=model["factory_lead_time_days"])
