"""Computed fields, serializers, and calculation rules (PRD §2.6, §2.8, §2.10,
§3.9 and scaffold Table 3). Money is integer cents; all rounding is
round-half-up applied at the pinned point (per pallet line for storage and
dwell, per order for handling-out).
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from core import DB, clock_now, fmt_dt, new_record

PRESENT_STATUSES = ("STORED", "IN_BLAST_FREEZE", "ALLOCATED")


# ----------------------------------------------------------------------------
# Lookups / aggregates
# ----------------------------------------------------------------------------

def active_rate_card(customer_id):
    for rc in sorted(DB["rate_cards"].values(), key=lambda r: r["_seq"]):
        if rc["customer_id"] == customer_id and rc["status"] == "ACTIVE":
            return rc
    return None


def month_bounds(dt):
    start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def create_invoice(customer_id, period_start, period_end):
    inv = new_record({
        "customer_id": customer_id,
        "period_start": period_start,
        "period_end": period_end,
        "status": "OPEN",
        "storage_cents": 0,
        "handling_in_cents": 0,
        "handling_out_cents": 0,
        "blast_freeze_cents": 0,
        "dwell_surcharge_cents": 0,
        "claim_credit_cents": 0,
        "rate_card_id": None,
    })
    DB["invoices"][inv["id"]] = inv
    return inv


def open_invoice(customer_id):
    """The single OPEN invoice a customer always has (§2.10)."""
    for inv in DB["invoices"].values():
        if inv["customer_id"] == customer_id and inv["status"] == "OPEN":
            return inv
    start, end = month_bounds(clock_now())
    return create_invoice(customer_id, start, end)


def invoice_total(inv):
    return (inv["storage_cents"] + inv["handling_in_cents"] + inv["handling_out_cents"]
            + inv["blast_freeze_cents"] + inv["dwell_surcharge_cents"] - inv["claim_credit_cents"])


def outstanding_balance(customer_id):
    total = 0
    for inv in DB["invoices"].values():
        if inv["customer_id"] != customer_id:
            continue
        if inv["status"] in ("FINALIZED", "DISPUTED"):
            total += invoice_total(inv)
        elif inv["status"] == "OPEN":
            total += (inv["handling_in_cents"] + inv["handling_out_cents"]
                      + inv["blast_freeze_cents"] - inv["claim_credit_cents"])
    return total


def active_allocations(order_id):
    return [a for a in DB["allocations"].values()
            if a["order_id"] == order_id and a["status"] == "ACTIVE"]


def find_lot(customer_id, product_code, lot_code):
    for lot in DB["lots"].values():
        if (lot["customer_id"] == customer_id and lot["product_code"] == product_code
                and lot["lot_code"] == lot_code):
            return lot
    return None


# ----------------------------------------------------------------------------
# Zone capacity accounting (§2.8)
# ----------------------------------------------------------------------------

def zone_metrics(zone):
    zid = zone["id"]
    in_use = sum(1 for p in DB["pallets"].values()
                 if p["zone_id"] == zid and p["status"] in PRESENT_STATUSES)
    reserved = sum(r["expected_pallets"] for r in DB["receipts"].values()
                   if r["zone_id"] == zid and r["status"] == "ARRIVED")
    free = zone["capacity_pallets"] - in_use - reserved
    return in_use, reserved, free


def zone_posture(zone, free):
    tight = max(1, (zone["capacity_pallets"] * 10) // 100)
    if free <= 0:
        return "FULL"
    if free <= tight:
        return "TIGHT"
    return "OPEN"


# ----------------------------------------------------------------------------
# Lot compound status (§3.3)
# ----------------------------------------------------------------------------

def lot_metrics(lot):
    pallets = [p for p in DB["pallets"].values() if p["lot_id"] == lot["id"]]
    present = [p for p in pallets if p["status"] in PRESENT_STATUSES]
    on_hand = len(present)
    if any(p["quality"] == "RECALLED" for p in present):
        status = "RECALLED"
    elif on_hand == 0 and pallets:
        status = "DEPLETED"
    elif all(p["quality"] == "QUARANTINED" for p in present):
        status = "FULL_HOLD"
    elif any(p["quality"] == "QUARANTINED" for p in present):
        status = "PARTIAL_HOLD"
    else:
        status = "AVAILABLE"
    return on_hand, status


# ----------------------------------------------------------------------------
# Calculation rules (scaffold Table 3)
# ----------------------------------------------------------------------------

def handling_out_fee(customer_id, quantity, card):
    """Volume tier: this customer's pallets SHIPPED in the calendar month of
    now plus this order's own quantity. Rounded half-up per order."""
    m_start, m_end = month_bounds(clock_now())
    shipped = sum(1 for p in DB["pallets"].values()
                  if p["customer_id"] == customer_id and p["status"] == "SHIPPED"
                  and p["out_at"] is not None and m_start <= p["out_at"] < m_end)
    volume = shipped + quantity
    if volume >= 500:
        discount = Decimal("0.20")
    elif volume >= 100:
        discount = Decimal("0.10")
    else:
        discount = Decimal("0")
    raw = Decimal(quantity * card["handling_out_cents_per_pallet"]) * (Decimal("1") - discount)
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _class_rate(card, zone):
    if zone["temp_class"] == "FROZEN":
        return card["frozen_storage_cents_per_pallet_month"]
    return card["chilled_storage_cents_per_pallet_month"]


def compute_storage_cents(customer_id, period_start, period_end, card):
    """Per-pallet presence days in [period_start, period_end); round each line
    half-up to whole cents first, then sum."""
    if card is None:
        return 0
    dates = []
    d = period_start.date()
    last = period_end.date()
    while d < last:
        dates.append(d)
        d += timedelta(days=1)
    total = 0
    for p in DB["pallets"].values():
        if p["customer_id"] != customer_id:
            continue
        rec_d = p["received_at"].date()
        out_d = p["out_at"].date() if p["out_at"] is not None else None
        days = sum(1 for D in dates if rec_d <= D and (out_d is None or out_d > D))
        if days == 0:
            continue
        rate = _class_rate(card, DB["zones"][p["zone_id"]])
        if card["storage_method"] == "DAILY_PRORATED":
            line = int((Decimal(days * rate) / Decimal(30)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        else:  # FULL_MONTH
            line = rate
        total += line
    return total


def compute_dwell_cents(customer_id, period_start, period_end, card):
    """Aged-inventory surcharge for pallets present on the period's last day.
    Anchor = max(received_at, last_blast_frozen_at); per-pallet round-half-up."""
    if card is None or card["dwell_exempt"]:
        return 0
    d_last = period_end.date() - timedelta(days=1)
    total = 0
    for p in DB["pallets"].values():
        if p["customer_id"] != customer_id:
            continue
        rec_d = p["received_at"].date()
        out_d = p["out_at"].date() if p["out_at"] is not None else None
        if not (rec_d <= d_last and (out_d is None or out_d > d_last)):
            continue
        anchor = p["received_at"]
        if p["last_blast_frozen_at"] is not None and p["last_blast_frozen_at"] > anchor:
            anchor = p["last_blast_frozen_at"]
        dwell_days = int((period_end - anchor).total_seconds() // 86400)
        if dwell_days >= 120:
            pct = Decimal("1.00")
        elif dwell_days >= 90:
            pct = Decimal("0.50")
        elif dwell_days >= 60:
            pct = Decimal("0.25")
        else:
            continue
        zone = DB["zones"][p["zone_id"]]
        mult = Decimal("1.0") if zone["temp_class"] == "FROZEN" else Decimal("1.5")
        rate = _class_rate(card, zone)
        surcharge = int((Decimal(rate) * pct * mult).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        total += surcharge
    return total


# ----------------------------------------------------------------------------
# Serializers (exact spec fields; internal "_"-prefixed keys never leak)
# ----------------------------------------------------------------------------

def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def customer_view(c):
    out = {
        "name": c["name"],
        "credit_limit_cents": c["credit_limit_cents"],
        "status": c["status"],
        "outstanding_balance_cents": outstanding_balance(c["id"]),
    }
    out.update(_common(c))
    return out


def rate_card_view(rc):
    out = {
        "customer_id": rc["customer_id"],
        "storage_method": rc["storage_method"],
        "frozen_storage_cents_per_pallet_month": rc["frozen_storage_cents_per_pallet_month"],
        "chilled_storage_cents_per_pallet_month": rc["chilled_storage_cents_per_pallet_month"],
        "handling_in_cents_per_pallet": rc["handling_in_cents_per_pallet"],
        "handling_out_cents_per_pallet": rc["handling_out_cents_per_pallet"],
        "blast_base_cents": rc["blast_base_cents"],
        "blast_per_pallet_cents": rc["blast_per_pallet_cents"],
        "liability_model": rc["liability_model"],
        "liability_per_pallet_cents": rc["liability_per_pallet_cents"],
        "dwell_exempt": rc["dwell_exempt"],
        "status": rc["status"],
    }
    out.update(_common(rc))
    return out


def zone_view(zone):
    in_use, reserved, free = zone_metrics(zone)
    out = {
        "zone_code": zone["zone_code"],
        "temp_class": zone["temp_class"],
        "capacity_pallets": zone["capacity_pallets"],
        "dock_doors": zone["dock_doors"],
        "in_use_pallets": in_use,
        "reserved_pallets": reserved,
        "free_pallets": free,
        "posture": zone_posture(zone, free),
    }
    out.update(_common(zone))
    return out


def receipt_view(r):
    out = {
        "customer_id": r["customer_id"],
        "zone_id": r["zone_id"],
        "lot_id": r["lot_id"],
        "product_code": r["product_code"],
        "lot_code": r["lot_code"],
        "production_date": r["production_date"],
        "temp_class": r["temp_class"],
        "expected_pallets": r["expected_pallets"],
        "actual_pallets": r["actual_pallets"],
        "window_start": fmt_dt(r["window_start"]),
        "window_end": fmt_dt(r["window_end"]),
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def lot_view(lot):
    on_hand, status = lot_metrics(lot)
    out = {
        "customer_id": lot["customer_id"],
        "product_code": lot["product_code"],
        "lot_code": lot["lot_code"],
        "production_date": lot["production_date"],
        "on_hand_pallets": on_hand,
        "status": status,
    }
    out.update(_common(lot))
    return out


def pallet_view(p):
    out = {
        "lot_id": p["lot_id"],
        "receipt_id": p["receipt_id"],
        "zone_id": p["zone_id"],
        "customer_id": p["customer_id"],
        "status": p["status"],
        "quality": p["quality"],
        "received_at": fmt_dt(p["received_at"]),
        "last_blast_frozen_at": fmt_dt(p["last_blast_frozen_at"]),
        "out_at": fmt_dt(p["out_at"]),
        "out_reason": p["out_reason"],
    }
    out.update(_common(p))
    return out


def order_view(o):
    out = {
        "customer_id": o["customer_id"],
        "product_code": o["product_code"],
        "lot_code": o["lot_code"],
        "requested_pallets": o["requested_pallets"],
        "allocated_pallets": len(active_allocations(o["id"])),
        "estimated_handling_out_cents": o["estimated_handling_out_cents"],
        "final_handling_out_cents": o["final_handling_out_cents"],
        "status": o["status"],
    }
    out.update(_common(o))
    return out


def allocation_view(a):
    out = {
        "order_id": a["order_id"],
        "pallet_id": a["pallet_id"],
        "lot_id": a["lot_id"],
        "status": a["status"],
    }
    out.update(_common(a))
    return out


def cell_view(c):
    out = {
        "cell_code": c["cell_code"],
        "capacity_pallets": c["capacity_pallets"],
        "turnaround_minutes": c["turnaround_minutes"],
    }
    out.update(_common(c))
    return out


def booking_view(b):
    out = {
        "cell_id": b["cell_id"],
        "lot_id": b["lot_id"],
        "customer_id": b["customer_id"],
        "pallet_count": b["pallet_count"],
        "window_start": fmt_dt(b["window_start"]),
        "window_end": fmt_dt(b["window_end"]),
        "fee_cents": b["fee_cents"],
        "status": b["status"],
    }
    out.update(_common(b))
    return out


def excursion_view(e):
    out = {
        "zone_id": e["zone_id"],
        "observed_temp_c": e["observed_temp_c"],
        "window_start": fmt_dt(e["window_start"]),
        "window_end": fmt_dt(e["window_end"]),
        "reported_by_user_id": e["reported_by_user_id"],
        "quarantined_pallet_count": e["quarantined_pallet_count"],
        "status": e["status"],
    }
    out.update(_common(e))
    return out


def recall_view(r):
    out = {
        "customer_id": r["customer_id"],
        "product_code": r["product_code"],
        "lot_code": r["lot_code"],
        "lot_id": r["lot_id"],
        "reason": r["reason"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def claim_view(c):
    out = {
        "customer_id": c["customer_id"],
        "excursion_id": c["excursion_id"],
        "affected_pallet_count": c["affected_pallet_count"],
        "declared_value_cents": c["declared_value_cents"],
        "settlement_cents": c["settlement_cents"],
        "status": c["status"],
    }
    out.update(_common(c))
    return out


def invoice_view(inv):
    out = {
        "customer_id": inv["customer_id"],
        "period_start": fmt_dt(inv["period_start"]),
        "period_end": fmt_dt(inv["period_end"]),
        "status": inv["status"],
        "storage_cents": inv["storage_cents"],
        "handling_in_cents": inv["handling_in_cents"],
        "handling_out_cents": inv["handling_out_cents"],
        "blast_freeze_cents": inv["blast_freeze_cents"],
        "dwell_surcharge_cents": inv["dwell_surcharge_cents"],
        "claim_credit_cents": inv["claim_credit_cents"],
        "total_cents": invoice_total(inv),
        "rate_card_id": inv["rate_card_id"],
    }
    out.update(_common(inv))
    return out
