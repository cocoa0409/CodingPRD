"""Shared helpers: entity construction, 404 lookups, calculations, cascades."""
import uuid
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import (
    store,
    next_seq,
    next_cert_number,
    now_iso,
    fmt_dt,
    parse_dt,
    clock_now,
    current_date,
)
from errors import ApiError
from response import ok_list
from middleware import pagination_params

# ---------------------------------------------------------------------------
# Entity field scaffolding
# ---------------------------------------------------------------------------


def base_fields():
    ts = now_iso()
    return {"id": str(uuid.uuid4()), "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq()}


def ledger_fields():
    """Immutable ledgers (DirectiveRecord, ReleaseCertificate, TraceabilityRecord):
    id + created_at only; no updated_at / version."""
    return {"id": str(uuid.uuid4()), "created_at": now_iso(), "_seq": next_seq()}


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def pub(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def sort_items(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def list_response(items, filters=None):
    """filters: {query_param: entity_field} exact-match filters."""
    from flask import request

    result = list(items)
    if filters:
        for param, field in filters.items():
            v = request.args.get(param)
            if v is not None:
                result = [e for e in result if e.get(field) is not None and str(e.get(field)) == v]
    result = sort_items(result)
    limit, offset = pagination_params()
    page = result[offset : offset + limit]
    return ok_list([pub(e) for e in page], limit, offset, len(result))


# ---------------------------------------------------------------------------
# 404 lookups (family-specific error ids)
# ---------------------------------------------------------------------------


def get_customer_or_404(cid):
    c = store.customers.get(cid)
    if c is None:
        raise ApiError("ERR_CUSTOMER_NOT_FOUND", 404, "Customer id does not exist")
    return c


def get_part_or_404(pid):
    p = store.parts.get(pid)
    if p is None:
        raise ApiError("ERR_PART_NOT_FOUND", 404, "PartCatalogEntry id does not exist")
    return p


def get_unit_or_404(uid):
    u = store.units.get(uid)
    if u is None:
        raise ApiError("ERR_UNIT_NOT_FOUND", 404, "ComponentUnit id does not exist")
    return u


def get_wo_or_404(wid):
    w = store.work_orders.get(wid)
    if w is None:
        raise ApiError("ERR_WORK_ORDER_NOT_FOUND", 404, "WorkOrder id does not exist")
    return w


def get_req_or_404(rid):
    r = store.requisitions.get(rid)
    if r is None:
        raise ApiError("ERR_REQUISITION_NOT_FOUND", 404, "PartsRequisition id does not exist")
    return r


def get_cell_or_404(tid):
    t = store.test_cells.get(tid)
    if t is None:
        raise ApiError("ERR_TEST_CELL_NOT_FOUND", 404, "TestCell id does not exist")
    return t


def get_exchange_or_404(aid):
    a = store.exchanges.get(aid)
    if a is None:
        raise ApiError("ERR_EXCHANGE_NOT_FOUND", 404, "ExchangeAgreement id does not exist")
    return a


def get_lease_or_404(aid):
    a = store.leases.get(aid)
    if a is None:
        raise ApiError("ERR_LEASE_NOT_FOUND", 404, "LeaseAgreement id does not exist")
    return a


def get_invoice_or_404(iid):
    i = store.invoices.get(iid)
    if i is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Invoice id does not exist")
    return i


def get_claim_or_404(cid):
    c = store.claims.get(cid)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", 404, "WarrantyClaim id does not exist")
    return c


def get_disc_or_404(did):
    d = store.discrepancies.get(did)
    if d is None:
        raise ApiError("ERR_NOT_FOUND", 404, "DiscrepancyCard id does not exist")
    return d


def get_booking_or_404(bid):
    b = store.bookings.get(bid)
    if b is None:
        raise ApiError("ERR_NOT_FOUND", 404, "TestCellBooking id does not exist")
    return b


# ---------------------------------------------------------------------------
# Calculations (all money integer cents, round-half-up; hours at 2dp)
# ---------------------------------------------------------------------------


def q_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def hours_between(from_iso, to_dt):
    d = to_dt - parse_dt(from_iso)
    micro = Decimal(d.days * 86400 + d.seconds) * Decimal(10**6) + Decimal(d.microseconds)
    return (micro / Decimal(3600 * 10**6)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def add_delay_hours(wo, hours):
    total = (Decimal(str(wo["accumulated_delay_hours"])) + hours).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    wo["accumulated_delay_hours"] = float(total)


def ber_threshold_cents(part):
    return q_cents(
        Decimal(part["ber_threshold_pct"]) / Decimal(100) * Decimal(part["replacement_value_cents"])
    )


def credit_held(customer):
    # Inclusive boundary: hold when exposure >= limit.
    return customer["current_exposure_cents"] >= customer["credit_limit_cents"]


def pub_customer(c):
    d = pub(c)
    d["credit_hold"] = credit_held(c)
    return d


# ---------------------------------------------------------------------------
# Cross-entity writers
# ---------------------------------------------------------------------------


def add_trace(unit_id, event_type, work_order_id=None, notes=None):
    rec = dict(ledger_fields())
    rec.update(
        {
            "unit_id": unit_id,
            "event_type": event_type,
            "event_at": now_iso(),
            "work_order_id": work_order_id,
            "notes": notes,
        }
    )
    store.traces[rec["id"]] = rec
    return rec


def create_invoice(
    source_type,
    customer_id,
    work_order_id=None,
    exchange_agreement_id=None,
    lease_agreement_id=None,
    labor_cents=0,
    parts_cents=0,
    test_fee_cents=0,
    penalty_credit_cents=0,
    other_charge_cents=0,
    total_cents=0,
    warranty_credit_applied_cents=0,
    penalty_variant="NONE",
):
    inv = dict(base_fields())
    inv.update(
        {
            "source_type": source_type,
            "work_order_id": work_order_id,
            "exchange_agreement_id": exchange_agreement_id,
            "lease_agreement_id": lease_agreement_id,
            "customer_id": customer_id,
            "labor_cents": labor_cents,
            "parts_cents": parts_cents,
            "test_fee_cents": test_fee_cents,
            "penalty_credit_cents": penalty_credit_cents,
            "other_charge_cents": other_charge_cents,
            "total_cents": total_cents,
            "warranty_credit_applied_cents": warranty_credit_applied_cents,
            "penalty_variant": penalty_variant,
            "status": "ISSUED",
            "issued_at": now_iso(),
            "paid_at": None,
        }
    )
    store.invoices[inv["id"]] = inv
    cust = store.customers.get(customer_id)
    if cust is not None:
        cust["current_exposure_cents"] += total_cents
        touch(cust)
    return inv


def create_compliance_records(wo_id, part_id):
    for d in sort_items([x for x in store.directives.values() if x["part_id"] == part_id]):
        dc = dict(base_fields())
        dc.update(
            {
                "work_order_id": wo_id,
                "directive_number": d["directive_number"],
                "directive_type": d["directive_type"],
                "mandatory": d["mandatory"],
                "status": "PENDING",
                "compliance_note": None,
            }
        )
        store.compliances[dc["id"]] = dc


def settle_exchange_default(agreement):
    """Clock-sweep default of a FULFILLED exchange agreement."""
    part = store.parts[agreement["part_id"]]
    replacement = part["replacement_value_cents"]
    core_charge = replacement
    late_fee = 0
    settlement = 25000 + core_charge + late_fee
    agreement["core_charge_cents"] = core_charge
    agreement["late_fee_cents"] = late_fee
    agreement["admin_fee_cents"] = 25000
    agreement["settlement_total_cents"] = settlement
    agreement["status"] = "DEFAULTED"
    touch(agreement)
    create_invoice(
        "EXCHANGE",
        agreement["customer_id"],
        exchange_agreement_id=agreement["id"],
        other_charge_cents=settlement,
        total_cents=settlement,
    )
    pool_unit_id = agreement.get("pool_unit_id")
    if pool_unit_id and pool_unit_id in store.units:
        unit = store.units[pool_unit_id]
        unit["ownership"] = "CUSTOMER"
        unit["owner_customer_id"] = agreement["customer_id"]
        touch(unit)


def sweep_exchange_defaults():
    """Every FULFILLED agreement whose core_due_date + 5 grace days falls before
    the current date moves to DEFAULTED."""
    cur = current_date()
    defaulted = []
    for ag in sort_items(list(store.exchanges.values())):
        if ag["status"] != "FULFILLED":
            continue
        due = date.fromisoformat(ag["core_due_date"])
        if due + timedelta(days=5) < cur:
            settle_exchange_default(ag)
            defaulted.append(ag["id"])
    return defaulted
