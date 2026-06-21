"""Core domain services: entity records, computed fields, postures, calculations.

Every behaviour traces to a PRD sentence; section references are inline.
"""
from datetime import timedelta
from decimal import Decimal

import db
import util


# ---------------------------------------------------------------------------
# Common system-managed fields (PRD §2.4)
# ---------------------------------------------------------------------------
def _stamp_new(record, with_version=True):
    """Attach id / created_at / updated_at / version on create.

    IdentifiedProperty carries only id + created_at (with_version=False, PRD §2.4).
    """
    now = db.now_logical()
    record["id"] = util.new_id()
    record["created_at"] = now
    record["_seq"] = db.next_seq()
    if with_version:
        record["updated_at"] = now
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and bump version on every mutation (PRD §2.4, §2.9)."""
    record["updated_at"] = db.now_logical()
    record["version"] = record.get("version", 1) + 1


# ---------------------------------------------------------------------------
# 45/180-day deadlines (PRD §3.3): closing instant + N calendar days, same
# time of day.
# ---------------------------------------------------------------------------
def add_calendar_days(dt, days):
    return dt + timedelta(days=days)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def relinquished_for(exchange_id):
    rows = [r for r in db.relinquished_properties.values() if r["exchange_id"] == exchange_id]
    return rows[0] if rows else None


def trust_for(exchange_id):
    rows = [t for t in db.qualified_trusts.values() if t["exchange_id"] == exchange_id]
    return rows[0] if rows else None


def identifications_for(exchange_id):
    return [i for i in db.identifications.values() if i["exchange_id"] == exchange_id]


def finalized_identification_for(exchange_id):
    for i in identifications_for(exchange_id):
        if i["status"] == "FINALIZED":
            return i
    return None


def candidates_for(identification_id):
    return [c for c in db.identified_properties.values() if c["identification_id"] == identification_id]


def candidate_rows(identification_id):
    """CANDIDATE-status candidates only (the input set for aggregate_identified_fmv)."""
    return [c for c in candidates_for(identification_id) if c["status"] == "CANDIDATE"]


def replacements_for(exchange_id):
    return [r for r in db.replacement_properties.values() if r["exchange_id"] == exchange_id]


def disbursements_for(exchange_id):
    return [d for d in db.disbursements.values() if d["exchange_id"] == exchange_id]


# ---------------------------------------------------------------------------
# Calculations (SCAFFOLD §1.3 / PRD §3.3, §3.5)
# ---------------------------------------------------------------------------
def compute_net_proceeds(rel):
    # net_proceeds = fair_market_value - selling_expenses - mortgage_payoff (PRD §3.3)
    return util.money(rel["fair_market_value"] - rel["selling_expenses"] - rel["mortgage_payoff"])


def compute_realized_gain(rel):
    # amount_realized = fair_market_value - selling_expenses
    # realized_gain   = amount_realized - adjusted_basis (PRD §3.3)
    amount_realized = util.money(rel["fair_market_value"] - rel["selling_expenses"])
    return util.money(amount_realized - rel["adjusted_basis"])


def aggregate_identified_fmv(identification_id):
    # Sum of estimated_fmv over CANDIDATE rows (PRD §3.4 / calc aggregate_identified_fmv).
    total = Decimal("0")
    for c in candidate_rows(identification_id):
        total += util.money(c["estimated_fmv"])
    return util.money(total)


def candidate_count(identification_id):
    return len(candidate_rows(identification_id))


def trust_available_balance(exchange_id, trust):
    # available_balance = deposited_amount - sum(SETTLED disbursement.amount) (PRD §3.6)
    settled = Decimal("0")
    for d in disbursements_for(exchange_id):
        if d["settlement_status"] == "SETTLED":
            settled += util.money(d["amount"])
    return util.money(trust["deposited_amount"] - settled)


def compute_boot_and_gain(exchange, rel, trust, rp):
    """Boot/recognized/deferred per pinned order (PRD §3.5 / calc boot_and_recognized_gain).

    Returns (cash_applied, recognized_gain, deferred_gain) as Decimals.
    """
    purchase_price = util.money(rp["purchase_price"])
    replacement_debt = util.money(rp["replacement_debt"])
    improvement_value = util.money(rp.get("improvement_value", 0))

    # 1. replacement_value depends on exchange type. IMPROVEMENT adds improvement_value;
    #    FORWARD/REVERSE ignore it entirely.
    if exchange["exchange_type"] == "IMPROVEMENT":
        replacement_value = util.money(purchase_price + improvement_value)
    else:
        replacement_value = purchase_price

    # 2. cash_applied = replacement_value - replacement_debt
    cash_applied = util.money(replacement_value - replacement_debt)

    # 3. cash_boot = max(0, deposited_amount - cash_applied)
    deposited = util.money(trust["deposited_amount"])
    cash_boot = max(util.money(0), util.money(deposited - cash_applied))

    # 4. mortgage_boot = max(0, mortgage_payoff - replacement_debt)
    mortgage_payoff = util.money(rel["mortgage_payoff"])
    mortgage_boot = max(util.money(0), util.money(mortgage_payoff - replacement_debt))

    # 5. total_boot = cash_boot + mortgage_boot
    total_boot = util.money(cash_boot + mortgage_boot)

    # 6. recognized_gain = min(realized_gain, total_boot)
    realized = util.money(exchange["realized_gain"])
    recognized = min(realized, total_boot)

    # 7. deferred_gain = realized_gain - recognized_gain
    deferred = util.money(realized - recognized)

    return cash_applied, util.money(recognized), deferred


# ---------------------------------------------------------------------------
# Compliance posture (PRD §2.8, §3.3 / SCAFFOLD Exchange state machine)
# ---------------------------------------------------------------------------
def recompute_posture(exchange):
    """Recompute compliance_posture against the current logical clock.

    Terminal postures (COMPLETED, FAILED) are sticky — they are only ever set by the
    explicit complete/fail transitions. For an ACTIVE exchange this derives
    OPEN / IDENTIFIED / AT_RISK from the clock position and child state.
    """
    status = exchange["status"]
    if status == "COMPLETED":
        return "COMPLETED"
    if status == "FAILED":
        return "FAILED"
    if status in ("DRAFT", "TERMINATED"):
        # Posture is not yet meaningful before close (PRD §3.1); keep current value.
        return exchange.get("compliance_posture")

    # status == ACTIVE
    clock = db.now_logical()
    finalized = finalized_identification_for(exchange["id"])
    id_deadline = exchange.get("id_deadline_at")
    exch_deadline = exchange.get("exchange_deadline_at")

    if finalized is not None:
        # IDENTIFIED once a finalized identification exists (PRD §2.8) — but if the
        # 180-day deadline passes before completion the exchange is AT_RISK (PRD §2.8).
        if exch_deadline is not None and clock > exch_deadline:
            return "AT_RISK"
        return "IDENTIFIED"

    # No finalized identification.
    if exch_deadline is not None and clock > exch_deadline:
        return "AT_RISK"
    if id_deadline is not None and clock > id_deadline:
        # 45-day deadline passed with no finalized identification (PRD §2.8, §3.3).
        return "AT_RISK"
    return "OPEN"


def apply_posture(exchange):
    """Recompute posture lazily; if it changed, re-stamp the exchange.

    Lazy recompute on read/mutation must not spuriously bump version on a pure read;
    we only touch the record when the derived posture value actually changes.
    """
    new_posture = recompute_posture(exchange)
    if new_posture != exchange.get("compliance_posture"):
        exchange["compliance_posture"] = new_posture
        touch(exchange)
    return new_posture


# ---------------------------------------------------------------------------
# Serialization (PRD §2.4, entity field tables §1.1)
# ---------------------------------------------------------------------------
def _common(record):
    return {
        "id": record["id"],
        "created_at": util.iso_z(record["created_at"]),
        "updated_at": util.iso_z(record["updated_at"]),
        "version": record["version"],
    }


def serialize_exchanger(r):
    out = _common(r)
    out.update({
        "legal_name": r["legal_name"],
        "taxpayer_id": r["taxpayer_id"],
        "email": r["email"],
    })
    return out


def serialize_exchange(r):
    out = _common(r)
    out.update({
        "exchanger_id": r["exchanger_id"],
        "exchange_type": r["exchange_type"],
        "coordinator_user_id": r["coordinator_user_id"],
        "compliance_posture": r["compliance_posture"],
        "status": r["status"],
        "relinquished_closing_at": util.iso_z(r["relinquished_closing_at"]),
        "id_deadline_at": util.iso_z(r["id_deadline_at"]),
        "exchange_deadline_at": util.iso_z(r["exchange_deadline_at"]),
        "realized_gain": util.money_out(r["realized_gain"]) if r["realized_gain"] is not None else None,
        "recognized_gain": util.money_out(r["recognized_gain"]) if r["recognized_gain"] is not None else None,
        "deferred_gain": util.money_out(r["deferred_gain"]) if r["deferred_gain"] is not None else None,
    })
    return out


def serialize_relinquished(r):
    out = _common(r)
    out.update({
        "exchange_id": r["exchange_id"],
        "address": r["address"],
        "fair_market_value": util.money_out(r["fair_market_value"]),
        "selling_expenses": util.money_out(r["selling_expenses"]),
        "mortgage_payoff": util.money_out(r["mortgage_payoff"]),
        "adjusted_basis": util.money_out(r["adjusted_basis"]),
        "net_proceeds": util.money_out(r["net_proceeds"]),
    })
    return out


def serialize_trust(r):
    out = _common(r)
    # available_balance is computed (PRD §3.6); surface the conserved live value.
    available = trust_available_balance(r["exchange_id"], r)
    out.update({
        "exchange_id": r["exchange_id"],
        "deposited_amount": util.money_out(r["deposited_amount"]),
        "available_balance": util.money_out(available),
        "is_locked": r["is_locked"],
    })
    return out


def serialize_identification(r):
    out = _common(r)
    out.update({
        "exchange_id": r["exchange_id"],
        "method": r["method"],
        "status": r["status"],
        "aggregate_identified_fmv": util.money_out(aggregate_identified_fmv(r["id"])),
        "finalized_at": util.iso_z(r["finalized_at"]),
    })
    return out


def serialize_candidate(r):
    # IdentifiedProperty carries only id + created_at (PRD §2.4) — no updated_at/version.
    return {
        "id": r["id"],
        "created_at": util.iso_z(r["created_at"]),
        "identification_id": r["identification_id"],
        "description": r["description"],
        "estimated_fmv": util.money_out(r["estimated_fmv"]),
        "status": r["status"],
    }


def serialize_replacement(r):
    out = _common(r)
    out.update({
        "exchange_id": r["exchange_id"],
        "identified_property_id": r["identified_property_id"],
        "purchase_price": util.money_out(r["purchase_price"]),
        "replacement_debt": util.money_out(r["replacement_debt"]),
        "improvement_value": util.money_out(r["improvement_value"]),
        "cash_applied": util.money_out(r["cash_applied"]),
        "acquired_at": util.iso_z(r["acquired_at"]),
    })
    return out


def serialize_disbursement(r):
    out = _common(r)
    out.update({
        "exchange_id": r["exchange_id"],
        "replacement_property_id": r["replacement_property_id"],
        "purpose": r["purpose"],
        "priority": r["priority"],
        "amount": util.money_out(r["amount"]),
        "settlement_status": r["settlement_status"],
        "settlement_officer_user_id": r["settlement_officer_user_id"],
    })
    return out
