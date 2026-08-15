"""Domain services: serialization, calculations, cascades, sweeps."""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from store import DB, bump, now
from timeutil import add_months, iso

# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

_AUDIT_INTERVAL_MONTHS = {"LOW": 24, "MEDIUM": 12, "HIGH": 6}
_INITIAL_AUDIT_INTERVAL_MONTHS = 12


def serialize(obj):
    out = {}
    for k, v in obj.items():
        if k.startswith("_"):
            continue
        out[k] = iso(v) if isinstance(v, datetime) else v
    return out


def serialize_supplier(s):
    out = serialize(s)
    last = s["last_audit_completed_at"]
    if last is None:
        due = add_months(s["created_at"], _INITIAL_AUDIT_INTERVAL_MONTHS)
    else:
        due = add_months(last, _AUDIT_INTERVAL_MONTHS[s["risk_tier"]])
    out["next_audit_due_at"] = iso(due)
    out["is_audit_overdue"] = bool(due <= now() and s["status"] != "DISQUALIFIED")
    return out


def serialize_for(kind, obj):
    if kind == "suppliers":
        return serialize_supplier(obj)
    return serialize(obj)


def list_data(kind, filters):
    """filters: list of (field, raw_value) with raw_value None meaning absent."""
    items = []
    for o in DB[kind].values():
        ok = True
        for field, raw in filters:
            if raw is None:
                continue
            if field == "confirmed":
                low = raw.lower()
                if low not in ("true", "false"):
                    ok = False
                    break
                if o["confirmed"] != (low == "true"):
                    ok = False
                    break
            elif o.get(field) != raw:
                ok = False
                break
        if ok:
            items.append(o)
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    return items


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def components_of_lot(lot_id):
    return [c for c in DB["components"].values() if c["lot_id"] == lot_id]


def labels_of_lot(lot_id):
    return [l for l in DB["labels"].values() if l["lot_id"] == lot_id]


def ncrs_of_lot(lot_id):
    return [n for n in DB["ncrs"].values() if n.get("lot_id") == lot_id]


def lots_containing_part(part_id):
    seen = set()
    out = []
    for comp in DB["components"].values():
        if comp["supplier_part_id"] == part_id and comp["lot_id"] not in seen:
            lot = DB["lots"].get(comp["lot_id"])
            if lot is not None:
                seen.add(comp["lot_id"])
                out.append(lot)
    return out


def active_agreement_of(supplier_id):
    for a in DB["agreements"].values():
        if a["supplier_id"] == supplier_id and a["status"] == "ACTIVE":
            return a
    return None


def approved_revision_of_family(device_code):
    for d in DB["dmrs"].values():
        if d["device_code"] == device_code and d["status"] == "APPROVED":
            return d
    return None


# ---------------------------------------------------------------------------
# Lot hold model (PRD section 2.8): a cascade hold on an already-ON_HOLD lot
# is a no-op; the existing hold_reason is retained.
# ---------------------------------------------------------------------------

def hold_lot_system(lot, reason):
    if lot["hold_status"] == "ON_HOLD":
        return
    lot["hold_status"] = "ON_HOLD"
    lot["hold_reason"] = reason
    bump(lot)


def hold_inflight_lots_with_part(part_id, reason="SUPPLIER_QUALITY"):
    for lot in lots_containing_part(part_id):
        if lot["disposition_status"] in ("IN_PRODUCTION", "COMPLETED"):
            hold_lot_system(lot, reason)


def hold_inflight_lots_of_protocol(protocol):
    for lot in DB["lots"].values():
        if lot["validation_protocol_id"] == protocol["id"] and \
                lot["disposition_status"] in ("IN_PRODUCTION", "COMPLETED"):
            hold_lot_system(lot, "REVALIDATION")


# ---------------------------------------------------------------------------
# Supplier lifecycle cascades (PRD section 3.4)
# ---------------------------------------------------------------------------

def suspend_supplier(supplier):
    supplier["status"] = "SUSPENDED"
    bump(supplier)
    for part in DB["parts"].values():
        if part["supplier_id"] == supplier["id"] and part["status"] == "QUALIFIED":
            part["status"] = "ON_HOLD"
            bump(part)
            hold_inflight_lots_with_part(part["id"])


def revalidate_protocol(protocol, reason):
    """VALIDATED -> REVALIDATION_REQUIRED with the in-flight lot hold cascade."""
    protocol["status"] = "REVALIDATION_REQUIRED"
    protocol["revalidation_reason"] = reason
    bump(protocol)
    hold_inflight_lots_of_protocol(protocol)


# ---------------------------------------------------------------------------
# Supplier quality scoring (PRD section 2.9, calculations table)
# ---------------------------------------------------------------------------

SEVERITY_PENALTY = {"MINOR": 5, "MAJOR": 15, "CRITICAL": 30}
AUTO_SUSPEND_BELOW = 50


def supplier_ids_for_ncr(ncr):
    """An NCR counts against a supplier when its supplier_part_id belongs to
    that supplier, or - when only lot_id is set - when the lot's recorded
    component genealogy includes a part of that supplier."""
    ids = set()
    part_id = ncr.get("supplier_part_id")
    if part_id:
        part = DB["parts"].get(part_id)
        if part is not None:
            ids.add(part["supplier_id"])
    lot_id = ncr.get("lot_id")
    if lot_id:
        for comp in DB["components"].values():
            if comp["lot_id"] == lot_id:
                part = DB["parts"].get(comp["supplier_part_id"])
                if part is not None:
                    ids.add(part["supplier_id"])
    return ids


def recompute_supplier_scores(supplier):
    applied = 0
    finalized = 0
    for ncr in DB["ncrs"].values():
        if ncr["fault"] != "SUPPLIER":
            continue
        if supplier["id"] not in supplier_ids_for_ncr(ncr):
            continue
        pen = SEVERITY_PENALTY[ncr["severity"]]
        if ncr["status"] in ("DISPOSITIONED", "CLOSED"):
            applied += pen
        if ncr["status"] == "CLOSED":
            finalized += pen
    for audit in DB["audits"].values():
        if audit["supplier_id"] == supplier["id"] and audit["status"] == "COMPLETED":
            pen = audit["findings_count"] * 2 + audit["major_findings_count"] * 8
            applied += pen
            finalized += pen
    new_vals = {
        "applied_penalty_points": applied,
        "applied_finalized_penalty_points": finalized,
        "quality_score": max(0, 100 - applied),
        "quality_score_finalized": max(0, 100 - finalized),
    }
    fs = new_vals["quality_score_finalized"]
    new_vals["risk_tier"] = "LOW" if fs >= 90 else ("MEDIUM" if fs >= 70 else "HIGH")
    changed = False
    for k, v in new_vals.items():
        if supplier[k] != v:
            supplier[k] = v
            changed = True
    if changed:
        bump(supplier)


def recompute_all_suppliers_with_auto_suspend():
    for supplier in list(DB["suppliers"].values()):
        recompute_supplier_scores(supplier)
    for supplier in list(DB["suppliers"].values()):
        if supplier["quality_score"] < AUTO_SUSPEND_BELOW and supplier["status"] == "QUALIFIED":
            suspend_supplier(supplier)


# ---------------------------------------------------------------------------
# Complaint rate (PRD section 3.7): pinned evaluation order.
# 1. entity mutations of the trigger already applied by the caller
# 2. denominator = sum releasable_qty over RELEASED lots of the DMR
# 3. numerator = confirmed complaints in {INVESTIGATED, CLOSED} on the DMR
# 4. rate = 0 if denominator == 0 else round_half_up(num/denom*100000, 4)
# 5. store rate; flag = rate >= 5.0
# ---------------------------------------------------------------------------

def recompute_dmr_complaint_rate(dmr):
    denom = sum(
        l["releasable_qty"]
        for l in DB["lots"].values()
        if l["dmr_id"] == dmr["id"] and l["disposition_status"] == "RELEASED"
    )
    num = 0
    for c in DB["complaints"].values():
        if not c["confirmed"] or c["status"] not in ("INVESTIGATED", "CLOSED"):
            continue
        lot = DB["lots"].get(c["lot_id"])
        if lot is not None and lot["dmr_id"] == dmr["id"]:
            num += 1
    if denom == 0:
        rate = 0
    else:
        rate = float(
            (Decimal(num) / Decimal(denom) * Decimal(100000)).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
        )
    flag = rate >= 5.0
    changed = dmr["complaint_rate_per_100k"] != rate or dmr["field_action_review_required"] != flag
    dmr["complaint_rate_per_100k"] = rate
    dmr["field_action_review_required"] = flag
    if changed:
        bump(dmr)


# ---------------------------------------------------------------------------
# Lot expiry ladder (PRD section 3.2)
# ---------------------------------------------------------------------------

def compute_lot_expiry(lot, dmr):
    confirmed = dmr["confirmed_shelf_life_months"]
    if confirmed is None:
        # PROVISIONAL: half the claim rounded up, capped at 12 months
        months = min((dmr["shelf_life_claim_months"] + 1) // 2, 12)
        basis = "PROVISIONAL"
    else:
        # FINAL: confirmed claim capped at 60 months
        months = min(confirmed, 60)
        basis = "FINAL"
    lot["expiry_date"] = add_months(lot["manufactured_at"], months)
    lot["expiry_basis"] = basis


# ---------------------------------------------------------------------------
# Sterility sampling (PRD section 3.6)
# ---------------------------------------------------------------------------

def compute_sample_qty(lot):
    prior_released = sum(
        1
        for l in DB["lots"].values()
        if l["validation_protocol_id"] == lot["validation_protocol_id"]
        and l["disposition_status"] in ("RELEASED", "RECALLED")
    )
    qty = lot["quantity"]
    if prior_released < 3:
        return qty  # process-maturity 100% inspection
    if qty <= 25:
        base = qty
    elif qty <= 150:
        base = 20
    elif qty <= 1200:
        base = 32
    elif qty <= 10000:
        base = 80
    else:
        base = 125
    critical = any(
        (DB["parts"].get(c["supplier_part_id"]) or {}).get("critical")
        for c in components_of_lot(lot["id"])
    )
    if critical:
        base = (base * 3 + 1) // 2  # ceil(base * 1.5), single ceiling, integer math
    return min(qty, base)


# ---------------------------------------------------------------------------
# GS1 UDI check digit (PRD section 3.6): over the first 13 digits, weights
# alternate 3/1 counting from the right; the rightmost of the thirteen
# carries weight 3. expected = (10 - (s mod 10)) mod 10.
# ---------------------------------------------------------------------------

def udi_check_digit_ok(udi_di):
    if not isinstance(udi_di, str) or len(udi_di) != 14 or not udi_di.isdigit():
        return None  # shape problem, caller maps to ERR_VALIDATION
    s = 0
    for i in range(13):  # i = 0-based position of d1..d13
        weight = 3 if (12 - i) % 2 == 0 else 1
        s += int(udi_di[i]) * weight
    expected = (10 - (s % 10)) % 10
    return int(udi_di[13]) == expected


# ---------------------------------------------------------------------------
# DMR family cascades (PRD section 3.1)
# ---------------------------------------------------------------------------

def invalidate_in_progress_studies(dmr_id):
    for s in DB["studies"].values():
        if s["dmr_id"] == dmr_id and s["status"] == "IN_PROGRESS":
            s["status"] = "INVALIDATED"
            bump(s)


def supersede_family_on_approve(dmr):
    for d in DB["dmrs"].values():
        if d["id"] != dmr["id"] and d["device_code"] == dmr["device_code"] and d["status"] == "APPROVED":
            d["status"] = "SUPERSEDED"
            bump(d)
            invalidate_in_progress_studies(d["id"])


# ---------------------------------------------------------------------------
# Lot scrap / recall cascades (PRD section 3.6)
# ---------------------------------------------------------------------------

def scrap_lot(lot):
    lot["disposition_status"] = "SCRAPPED"
    bump(lot)
    for comp in components_of_lot(lot["id"]):
        part = DB["parts"].get(comp["supplier_part_id"])
        if part is not None:
            part["quantity_committed"] -= comp["quantity_used"]
            part["quantity_in_scrapped_lots"] += comp["quantity_used"]
            bump(part)
    for label in labels_of_lot(lot["id"]):
        if label["status"] in ("DRAFT", "APPROVED", "PRINTED"):
            label["status"] = "VOID"
            label["void_reason"] = "LOT_SCRAPPED"
            bump(label)
    for ncr in ncrs_of_lot(lot["id"]):
        if ncr["status"] in ("OPEN", "CONTAINED"):
            ncr["status"] = "DISPOSITIONED"
            ncr["disposition"] = "SCRAP"  # fault unchanged; no supplier penalty
            bump(ncr)


def recall_lot(lot):
    lot["disposition_status"] = "RECALLED"
    bump(lot)
    for label in labels_of_lot(lot["id"]):
        if label["status"] in ("APPROVED", "PRINTED"):
            label["status"] = "VOID"
            label["void_reason"] = "LOT_RECALLED"
            bump(label)


# ---------------------------------------------------------------------------
# Logical-clock sweeps (PRD section 2.5): exactly two sweeps, in this order.
# ---------------------------------------------------------------------------

def run_clock_sweeps():
    current = now()
    # 1. Agreement expiry sweep
    for a in list(DB["agreements"].values()):
        if a["status"] == "ACTIVE" and current >= a["effective_to"]:
            a["status"] = "EXPIRED"
            bump(a)
            supplier = DB["suppliers"].get(a["supplier_id"])
            if supplier is not None and supplier["status"] == "QUALIFIED" and \
                    active_agreement_of(supplier["id"]) is None:
                suspend_supplier(supplier)
    # 2. Revalidation sweep
    for p in list(DB["protocols"].values()):
        if p["status"] == "VALIDATED" and p["revalidation_due_at"] is not None and \
                current >= p["revalidation_due_at"]:
            revalidate_protocol(p, "TIME_EXPIRY")
