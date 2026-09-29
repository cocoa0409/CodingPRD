"""Append-only credit ledger, its projections and the sales-posture ladder."""
from decimal import Decimal

import calc
import store
from util import dec, new_id, now, next_seq

ZERO = Decimal("0.00")

NON_TERMINAL_REMEDIAL = ("OPEN", "WORK_SUBMITTED", "REINSPECTION", "FAILED")
OPEN_SALE_STATUSES = ("QUOTED", "RESERVED")
SETTLED_SALE_STATUSES = ("EXECUTED", "ASSIGNED")
FROZEN_BANK_STATUSES = ("DRAFT", "PROSPECTUS_REVIEW", "SUSPENDED", "CLOSED")


# ------------------------------------------------------------- child selectors
def bank_sales(bank_id):
    return store.ordered([s for s in store.credit_sales.values()
                          if s["bank_id"] == bank_id])


def bank_reports(bank_id):
    return store.ordered([r for r in store.monitoring_reports.values()
                          if r["bank_id"] == bank_id])


def bank_milestones(bank_id):
    return store.ordered([m for m in store.milestones.values()
                          if m["bank_id"] == bank_id])


def bank_standards(bank_id):
    return store.ordered([p for p in store.performance_standards.values()
                          if p["bank_id"] == bank_id])


def bank_remedial_actions(bank_id):
    report_ids = {r["id"] for r in store.monitoring_reports.values()
                  if r["bank_id"] == bank_id}
    return store.ordered([a for a in store.remedial_actions.values()
                          if a["monitoring_report_id"] in report_ids])


def remedial_bank(action):
    report = store.monitoring_reports.get(action["monitoring_report_id"])
    if report is None:
        return None
    return store.banks.get(report["bank_id"])


# ----------------------------------------------------------------- projections
def aggregates(bank_id):
    released = ZERO
    sold = ZERO
    on_hold = ZERO
    for entry in store.bank_ledger(bank_id):
        delta = entry["delta_credits"]
        kind = entry["entry_type"]
        if kind == "RELEASED":
            released += delta
        elif kind in ("SOLD", "SALE_REVERSED"):
            sold += delta
        elif kind in ("HOLD_PLACED", "HOLD_RELEASED"):
            on_hold += delta
    sold = -sold
    on_hold = -on_hold
    return {
        "credits_released": released,
        "credits_sold": sold,
        "credits_on_hold": on_hold,
        "credits_available": released - sold - on_hold,
    }


def credits_available(bank_id):
    return aggregates(bank_id)["credits_available"]


def open_quote_count(bank_id):
    return sum(1 for s in store.credit_sales.values()
               if s["bank_id"] == bank_id and s["status"] in OPEN_SALE_STATUSES)


def sales_posture(bank):
    if bank["status"] in FROZEN_BANK_STATUSES:
        return "FROZEN"
    if not bank["easement_recorded"]:
        return "RESTRICTED"
    for action in bank_remedial_actions(bank["id"]):
        if action["status"] in NON_TERMINAL_REMEDIAL:
            return "RESTRICTED"
    if credits_available(bank["id"]) == 0:
        return "SOLD_OUT"
    return "OPEN"


# ---------------------------------------------------------------------- append
def append_entry(bank_id, entry_type, delta, source_entity_type, source_id, memo):
    entries = store.bank_ledger(bank_id)
    previous = entries[-1]["balance_after"] if entries else ZERO
    delta = dec(delta).quantize(Decimal("0.01"))
    entry = {
        "id": new_id(),
        "_seq": next_seq(),
        "created_at": now(),
        "bank_id": bank_id,
        "sequence_number": len(entries) + 1,
        "entry_type": entry_type,
        "delta_credits": delta,
        "balance_after": previous + delta,
        "source_entity_type": source_entity_type,
        "source_id": source_id,
        "memo": memo,
    }
    entries.append(entry)
    return entry


# ------------------------------------------------------------ sponsor rollups
def sponsor_banks(sponsor_id):
    return [b for b in store.banks.values() if b["sponsor_id"] == sponsor_id]


def sponsor_banks_count(sponsor_id):
    return len(sponsor_banks(sponsor_id))


def sponsor_good_standing(sponsor_id):
    return not any(b["status"] == "SUSPENDED" for b in sponsor_banks(sponsor_id))


# ----------------------------------------------------------- permittee rollups
def permittee_sales(permittee_id):
    return store.ordered([s for s in store.credit_sales.values()
                          if s["permittee_id"] == permittee_id])


def permittee_rollup(permittee):
    deposited = permittee["deposited_cents"]
    spent = 0
    assigned = ZERO
    for sale in permittee_sales(permittee["id"]):
        if sale["status"] in SETTLED_SALE_STATUSES:
            spent += sale["executed_price_cents"] or 0
        if sale["status"] == "ASSIGNED":
            assigned += dec(sale["credits_requested"])
    unmet = dec(permittee["required_credits"]) - assigned
    if unmet < 0:
        unmet = ZERO
    return {
        "deposited_cents": deposited,
        "escrow_balance_cents": deposited - spent,
        "assigned_credits": assigned.quantize(Decimal("0.01")),
        "unmet_requirement_credits": unmet.quantize(Decimal("0.01")),
    }


def escrow_balance(permittee):
    return permittee_rollup(permittee)["escrow_balance_cents"]


def unmet_requirement(permittee):
    return permittee_rollup(permittee)["unmet_requirement_credits"]


# -------------------------------------------------------------------- cascades
def sweep_expired_holds(bank):
    """Lazy expiry sweep: releases holds whose expiry lies STRICTLY in the past."""
    clock = now()
    for sale in bank_sales(bank["id"]):
        if sale["status"] != "RESERVED":
            continue
        if sale["hold_expires_at"] is not None and sale["hold_expires_at"] < clock:
            sale["status"] = "EXPIRED"
            sale["cancelled_reason"] = "HOLD_EXPIRED"
            sale["cancelled_at"] = clock
            append_entry(bank["id"], "HOLD_RELEASED", dec(sale["credits_requested"]),
                         "CREDIT_SALE", sale["id"],
                         "HOLD EXPIRED credits=%s" % sale["credits_requested"])
            store.touch(sale)


def cancel_open_sales(bank, reason):
    """Cancel every QUOTED/RESERVED sale of the bank; reserved ones release holds."""
    for sale in bank_sales(bank["id"]):
        if sale["status"] not in OPEN_SALE_STATUSES:
            continue
        was_reserved = sale["status"] == "RESERVED"
        sale["status"] = "CANCELLED"
        sale["cancelled_reason"] = reason
        sale["cancelled_at"] = now()
        if was_reserved:
            append_entry(bank["id"], "HOLD_RELEASED", dec(sale["credits_requested"]),
                         "CREDIT_SALE", sale["id"],
                         "HOLD RELEASED reason=%s" % reason)
        store.touch(sale)


def earliest_deferrable_milestone(bank_id):
    candidates = [m for m in bank_milestones(bank_id)
                  if m["status"] in ("PENDING", "CLAIMED")]
    if not candidates:
        return None
    candidates.sort(key=lambda m: (m["window_start"], m["created_at"], m["_seq"]))
    return candidates[0]


def governing_report(bank_id):
    accepted = [r for r in bank_reports(bank_id) if r["review_status"] == "ACCEPTED"]
    if not accepted:
        return None
    accepted.sort(key=lambda r: (r["monitoring_year"], r["created_at"], r["_seq"]))
    return accepted[-1]


def effective_standards(bank_id, monitoring_year):
    return sorted([s for s in bank_standards(bank_id)
                   if s["effective_from_year"] <= monitoring_year],
                  key=lambda s: s["standard_code"])


def demand_index(bank_id):
    return calc.service_area_demand_index(bank_sales(bank_id), now())


def stewardship_underfunded(bank):
    return bank["stewardship_funded_cents"] < bank["stewardship_required_cents"]
