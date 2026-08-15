"""Core domain services: record construction, serializers, the posture engine
(PRD 2.7) with gate/release cascades, spoilage risk scoring (3.2), inventory
reconciliation, contract aggregates, and the monthly assessment epoch (3.7).

All bushel math is Decimal quantized to 2dp half-up; all money is integer
cents half-up; thresholds are exact and inclusive where the PRD says so.
"""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from clock import CLOCK, format_iso

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD Table 3)
# ---------------------------------------------------------------------------

CROPS = ("CORN", "SOYBEAN", "WHEAT")
GRADES = ("GRADE_1", "GRADE_2", "GRADE_3")
PRODUCTS = ("PHOSPHINE", "SULFURYL_FLUORIDE")
VALUATION_CLAUSES = ("SPOT", "CONTRACT_AVG")
ALERT_OUTCOMES = ("RESOLVED", "CONFIRMED_LOSS")
CARRY_VARIANTS = ("CASH", "ECONOMIC")

LOT_STATUSES = ("STORED", "PARTIALLY_DRAWN", "SUSPENDED", "DEPLETED")
ALERT_STATUSES = ("OPEN", "RESOLVED", "CONFIRMED_LOSS")
FUMIGATION_STATUSES = ("ACTIVE", "CLEARED")
PERMIT_STATUSES = ("REQUESTED", "APPROVED", "VOIDED", "EXPIRED")
TRANSPORT_STATUSES = ("SCHEDULED", "HELD", "DISPATCHED", "DELIVERED", "EXPIRED")
SETTLEMENT_STATUSES = ("UNSETTLED", "SETTLED", "VOIDED")
CLAIM_STATUSES = ("SUBMITTED", "APPROVED")
SHRINK_KINDS = ("PROVISIONAL", "INVISIBLE_LOSS")

REI_HOURS = {"PHOSPHINE": 72, "SULFURYL_FLUORIDE": 24}
STANDARD_MOISTURE = {"CORN": Decimal("15.0"), "SOYBEAN": Decimal("13.0"),
                     "WHEAT": Decimal("13.5")}
SHRINK_FACTOR = Decimal("1.35")
TEMP_EXCURSION_F = Decimal("10.0")
HOTSPOT_DELTA_F = Decimal("30.0")
HOTSPOT_ABS_F = Decimal("110.0")
STALE_DAYS_FULL = Decimal("30")
SCORE_WATCH = Decimal("40")
SCORE_ALERT = Decimal("70")
TIER1_FLOOR_CENTS = 200000
TIER2_FLOOR_CENTS = 500000
FULFILL_FRACTION = Decimal("0.98")
INVISIBLE_LOSS_MONTHLY_PCT = Decimal("0.20")
ANNUAL_INTEREST_PCT = Decimal("6.0")

D0 = Decimal("1")
D1 = Decimal("0.1")
D2 = Decimal("0.01")
D4 = Decimal("0.0001")

ZERO2 = Decimal("0.00")


def q0(v):
    return int(Decimal(v).quantize(D0, rounding=ROUND_HALF_UP))


def q1(v):
    return Decimal(v).quantize(D1, rounding=ROUND_HALF_UP)


def q2(v):
    return Decimal(v).quantize(D2, rounding=ROUND_HALF_UP)


def q4(v):
    return Decimal(v).quantize(D4, rounding=ROUND_HALF_UP)


def f1(v):
    return None if v is None else float(q1(v))


def f2(v):
    return None if v is None else float(q2(v))


def f4(v):
    return None if v is None else float(q4(v))


def iso(dt):
    return None if dt is None else format_iso(dt)


def _clamp01(x):
    if x < 0:
        return Decimal("0")
    if x > 1:
        return Decimal("1")
    return x


# ---------------------------------------------------------------------------
# Record construction
# ---------------------------------------------------------------------------

def new_common():
    """System-managed fields for common_fields entities (PRD 2.5)."""
    ts = CLOCK.now_iso()
    return {"id": db.new_id(), "created_at": ts, "updated_at": ts,
            "version": 1, "seq": db.next_seq()}


def new_event():
    """Immutable event-log records carry only id + created_at (PRD 2.5)."""
    return {"id": db.new_id(), "created_at": CLOCK.now_iso(), "seq": db.next_seq()}


def touch(rec):
    rec["updated_at"] = CLOCK.now_iso()
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Selectors
# ---------------------------------------------------------------------------

def lots_of(bin_id):
    return [l for l in db.lots.values() if l["bin_id"] == bin_id]


def loadouts_of_bin(bin_id):
    return [lo for lo in db.loadouts.values() if lo["bin_id"] == bin_id]


def permits_of(bin_id):
    return [p for p in db.permits.values() if p["bin_id"] == bin_id]


def active_lockout_fumigation(bin_id):
    """An ACTIVE fumigation on the bin whose application_start is at or before now."""
    now = CLOCK.now()
    for f in db.fumigations.values():
        if (f["bin_id"] == bin_id and f["status"] == "ACTIVE"
                and f["application_start"] <= now):
            return f
    return None


def has_open_alert(bin_id):
    for a in db.alerts.values():
        if a["bin_id"] == bin_id and a["status"] == "OPEN":
            return True
    return False


# ---------------------------------------------------------------------------
# Contract aggregates (derived from loadouts per the PRD 3.5 definitions:
# committed = planned over {SCHEDULED, DISPATCHED}; delivered = settled net
# over SETTLED; settled value = settlement net cents over SETTLED)
# ---------------------------------------------------------------------------

def committed_bu(contract):
    total = ZERO2
    for lo in db.loadouts.values():
        if (lo["contract_id"] == contract["id"]
                and lo["transport_status"] in ("SCHEDULED", "DISPATCHED")):
            total += lo["planned_bu"]
    return q2(total)


def delivered_bu(contract):
    total = ZERO2
    for lo in db.loadouts.values():
        if (lo["contract_id"] == contract["id"]
                and lo["settlement_status"] == "SETTLED"
                and lo["settled_net_bu"] is not None):
            total += lo["settled_net_bu"]
    return q2(total)


def settled_value_cents(contract):
    total = 0
    for lo in db.loadouts.values():
        if (lo["contract_id"] == contract["id"]
                and lo["settlement_status"] == "SETTLED"
                and lo["settlement_net_cents"] is not None):
            total += lo["settlement_net_cents"]
    return total


def fulfillment_ratio(contract):
    return q4(delivered_bu(contract) / contract["contracted_bu"])


def is_fulfilled(contract):
    """Bushel-exact threshold: delivered >= contracted * 98% (inclusive)."""
    return delivered_bu(contract) >= q2(contract["contracted_bu"] * FULFILL_FRACTION)


# ---------------------------------------------------------------------------
# Bin inventory + posture engine (PRD 2.7)
# ---------------------------------------------------------------------------

def recompute_inventory(b):
    total = ZERO2
    for l in lots_of(b["id"]):
        total += l["current_bu"]
    b["current_inventory_bu"] = q2(total)


def recompute_risk(b):
    """Recompute the bin's spoilage risk score from the latest reading by
    recorded_at (never arrival order) and the contributing lots. Returns the
    score, or None when the bin has no readings."""
    readings = [r for r in db.readings.values() if r["bin_id"] == b["id"]]
    if not readings:
        return None
    latest = max(readings, key=lambda r: (r["recorded_at"], r["seq"]))
    contrib = [l for l in lots_of(b["id"])
               if l["status"] != "DEPLETED" and l["current_bu"] > 0]
    if contrib:
        total_bu = sum(l["current_bu"] for l in contrib)
        m = sum(l["current_bu"] * l["current_moisture_pct"] for l in contrib) / total_bu
        std = STANDARD_MOISTURE[b["crop"]]
        moisture_term = _clamp01((m - std) / Decimal("4")) * Decimal("25")
        min_fill = min(l["fill_date"] for l in contrib)
        days = math.floor((latest["recorded_at"] - min_fill).total_seconds() / 86400)
        staleness_term = _clamp01(Decimal(days) / STALE_DAYS_FULL) * Decimal("15")
    else:
        moisture_term = Decimal("0")
        staleness_term = Decimal("0")
    temp_term = _clamp01(
        (latest["max_cable_temp_f"] - latest["ambient_temp_f"] - TEMP_EXCURSION_F)
        / Decimal("20")) * Decimal("50")
    insect_term = Decimal("10") if latest["insect_activity"] else Decimal("0")
    score = q2(temp_term + moisture_term + staleness_term + insect_term)
    b["risk_score"] = score
    b["insect_activity"] = latest["insect_activity"]
    b["last_reading_at"] = latest["recorded_at"]
    return score


def derive_posture(b):
    """The strict ladder, in order (PRD 2.7)."""
    if active_lockout_fumigation(b["id"]) is not None:
        return "FUMIGATION_LOCKOUT"
    if has_open_alert(b["id"]):
        return "ALERT"
    if b["risk_score"] >= SCORE_ALERT:
        return "ALERT"
    if b["risk_score"] >= SCORE_WATCH:
        return "WATCH"
    return "SOUND"


def _gate_cascade(b, void_permits):
    """Entering ALERT or FUMIGATION_LOCKOUT from SOUND or WATCH."""
    for lot in lots_of(b["id"]):
        if lot["status"] in ("STORED", "PARTIALLY_DRAWN"):
            lot["status"] = "SUSPENDED"
            touch(lot)
    for lo in loadouts_of_bin(b["id"]):
        if lo["transport_status"] == "SCHEDULED":
            lo["transport_status"] = "HELD"
            lo["held_reason"] = "POSTURE"
            touch(lo)
            c = db.contracts.get(lo["contract_id"])
            if c is not None:
                touch(c)  # committed_bu (derived) drops by planned_bu
    if void_permits:
        _void_permits(b)


def _release_cascade(b):
    """Entering SOUND or WATCH from ALERT or FUMIGATION_LOCKOUT."""
    for lot in lots_of(b["id"]):
        if lot["status"] == "SUSPENDED":
            lot["status"] = "PARTIALLY_DRAWN" if lot["drawn_bu"] > 0 else "STORED"
            touch(lot)
    for lo in loadouts_of_bin(b["id"]):
        if lo["transport_status"] == "HELD":
            lo["transport_status"] = "SCHEDULED"
            lo["held_reason"] = None
            touch(lo)
            c = db.contracts.get(lo["contract_id"])
            if c is not None:
                touch(c)  # committed_bu (derived) regains planned_bu


def _void_permits(b):
    for p in permits_of(b["id"]):
        if p["status"] in ("REQUESTED", "APPROVED"):
            p["status"] = "VOIDED"
            touch(p)


def recompute_posture(b):
    """Recompute the bin's stored posture and fire the transition cascades.

    This function does NOT touch the bin's version/updated_at itself; callers
    bracket with bin_snap/finalize_bin so the bin bumps only when any stored
    field actually changed."""
    old = b["posture"]
    new = derive_posture(b)
    if new == old:
        return
    b["posture"] = new
    gated_old = old in ("ALERT", "FUMIGATION_LOCKOUT")
    gated_new = new in ("ALERT", "FUMIGATION_LOCKOUT")
    if gated_new and not gated_old:
        _gate_cascade(b, void_permits=(new == "FUMIGATION_LOCKOUT"))
    elif new == "FUMIGATION_LOCKOUT" and old == "ALERT":
        # Lots/loadouts are already gated and remain so; permits still void.
        _void_permits(b)
    elif not gated_new and gated_old:
        _release_cascade(b)
    # FUMIGATION_LOCKOUT -> ALERT: no release; lots stay SUSPENDED, loadouts HELD.


def bin_snap(b):
    return (b["posture"], b["risk_score"], b["current_inventory_bu"],
            b["insect_activity"], b["last_reading_at"])


def finalize_bin(b, snap):
    if bin_snap(b) != snap:
        touch(b)


# ---------------------------------------------------------------------------
# Shared calculation helpers
# ---------------------------------------------------------------------------

def storage_rate_cents(months_since_fill):
    if months_since_fill <= 3:
        return 3
    if months_since_fill <= 6:
        return 4
    return 5


def month_diff(from_dt, to_year, to_month):
    return (to_year - from_dt.year) * 12 + (to_month - from_dt.month)


def settlement_shrink_per_ticket(crop, gross_bu, moisture_pct):
    """Per-ticket settlement shrink: round the ticket, then sum (pinned order)."""
    std = STANDARD_MOISTURE[crop]
    excess = moisture_pct - std
    if excess < 0:
        excess = Decimal("0")
    return q2(gross_bu * excess * SHRINK_FACTOR / Decimal("100"))


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def bin_view(b):
    return {
        "id": b["id"],
        "name": b["name"],
        "capacity_bu": f2(b["capacity_bu"]),
        "crop": b["crop"],
        "current_inventory_bu": f2(b["current_inventory_bu"]),
        "risk_score": f2(b["risk_score"]),
        "posture": b["posture"],
        "insect_activity": b["insect_activity"],
        "last_reading_at": iso(b["last_reading_at"]),
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def lot_view(l):
    return {
        "id": l["id"],
        "bin_id": l["bin_id"],
        "crop": l["crop"],
        "grade": l["grade"],
        "fill_date": iso(l["fill_date"]),
        "original_bu": f2(l["original_bu"]),
        "fill_moisture_pct": f1(l["fill_moisture_pct"]),
        "fill_basis_cents": l["fill_basis_cents"],
        "reference_price_cents_per_bu": l["reference_price_cents_per_bu"],
        "current_moisture_pct": f1(l["current_moisture_pct"]),
        "provisional_shrink_bu": f2(l["provisional_shrink_bu"]),
        "current_bu": f2(l["current_bu"]),
        "drawn_bu": f2(l["drawn_bu"]),
        "cumulative_invisible_loss_bu": f2(l["cumulative_invisible_loss_bu"]),
        "cumulative_storage_charge_cents": l["cumulative_storage_charge_cents"],
        "months_assessed": l["months_assessed"],
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def reading_view(r):
    return {
        "id": r["id"],
        "bin_id": r["bin_id"],
        "recorded_at": iso(r["recorded_at"]),
        "ambient_temp_f": f1(r["ambient_temp_f"]),
        "cable_temps_f": [f1(t) for t in r["cable_temps_f"]],
        "insect_activity": r["insect_activity"],
        "max_cable_temp_f": f1(r["max_cable_temp_f"]),
        "temp_delta_f": f1(r["temp_delta_f"]),
        "hotspot_triggered": r["hotspot_triggered"],
        "score_after": f2(r["score_after"]),
        "created_at": r["created_at"],
    }


def alert_view(a):
    return {
        "id": a["id"],
        "bin_id": a["bin_id"],
        "reading_id": a["reading_id"],
        "source": a["source"],
        "status": a["status"],
        "loss_bu": f2(a["loss_bu"]),
        "closed_at": iso(a["closed_at"]),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def fumigation_view(f):
    return {
        "id": f["id"],
        "bin_id": f["bin_id"],
        "applicator_id": f["applicator_id"],
        "product": f["product"],
        "application_start": iso(f["application_start"]),
        "application_end": iso(f["application_end"]),
        "lockout_until": iso(f["lockout_until"]),
        "status": f["status"],
        "cleared_at": iso(f["cleared_at"]),
        "cleared_by_applicator_id": f["cleared_by_applicator_id"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def permit_view(p):
    return {
        "id": p["id"],
        "bin_id": p["bin_id"],
        "planned_start": iso(p["planned_start"]),
        "planned_end": iso(p["planned_end"]),
        "atmosphere_test_passed": p["atmosphere_test_passed"],
        "loto_confirmed": p["loto_confirmed"],
        "requester_user_id": p["requester_user_id"],
        "approver_user_id": p["approver_user_id"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def contract_view(c):
    return {
        "id": c["id"],
        "crop": c["crop"],
        "contracted_bu": f2(c["contracted_bu"]),
        "window_start": iso(c["window_start"]),
        "window_end": iso(c["window_end"]),
        "basis_cents_per_bu": c["basis_cents_per_bu"],
        "futures_ref_cents_per_bu": c["futures_ref_cents_per_bu"],
        "early_bonus_cents_per_bu": c["early_bonus_cents_per_bu"],
        "early_cutoff": iso(c["early_cutoff"]),
        "contract_unit_price_cents": c["contract_unit_price_cents"],
        "committed_bu": f2(committed_bu(c)),
        "delivered_bu": f2(delivered_bu(c)),
        "settled_value_cents": settled_value_cents(c),
        "fulfillment_ratio": f4(fulfillment_ratio(c)),
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def loadout_view(lo):
    tickets = None
    if lo["scale_tickets"] is not None:
        tickets = [{
            "ticket_no": t["ticket_no"],
            "gross_bu": f2(t["gross_bu"]),
            "moisture_pct": f1(t["moisture_pct"]),
        } for t in lo["scale_tickets"]]
    return {
        "id": lo["id"],
        "contract_id": lo["contract_id"],
        "bin_id": lo["bin_id"],
        "scheduled_start": iso(lo["scheduled_start"]),
        "scheduled_end": iso(lo["scheduled_end"]),
        "planned_bu": f2(lo["planned_bu"]),
        "transport_status": lo["transport_status"],
        "settlement_status": lo["settlement_status"],
        "scale_tickets": tickets,
        "delivered_at": iso(lo["delivered_at"]),
        "gross_bu": f2(lo["gross_bu"]),
        "ticket_shrink_bu": f2(lo["ticket_shrink_bu"]),
        "settled_net_bu": f2(lo["settled_net_bu"]),
        "grain_value_cents": lo["grain_value_cents"],
        "service_fee_cents": lo["service_fee_cents"],
        "early_bonus_cents": lo["early_bonus_cents"],
        "settlement_net_cents": lo["settlement_net_cents"],
        "draws": [{"lot_id": d["lot_id"], "bu": f2(d["bu"])} for d in lo["draws"]],
        "held_reason": lo["held_reason"],
        "created_at": lo["created_at"],
        "updated_at": lo["updated_at"],
        "version": lo["version"],
    }


def applicator_view(a):
    return {
        "id": a["id"],
        "name": a["name"],
        "license_no": a["license_no"],
        "cert_expires_at": iso(a["cert_expires_at"]),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def policy_view(p):
    return {
        "id": p["id"],
        "crop": p["crop"],
        "coverage_limit_cents": p["coverage_limit_cents"],
        "deductible_cents": p["deductible_cents"],
        "valuation_clause": p["valuation_clause"],
        "period_start": iso(p["period_start"]),
        "period_end": iso(p["period_end"]),
        "remaining_coverage_cents": p["remaining_coverage_cents"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def claim_view(c):
    return {
        "id": c["id"],
        "policy_id": c["policy_id"],
        "spoilage_alert_id": c["spoilage_alert_id"],
        "loss_bu": f2(c["loss_bu"]),
        "unit_value_cents": f2(c["unit_value_cents"]),
        "gross_indemnity_cents": c["gross_indemnity_cents"],
        "indemnity_cents": c["indemnity_cents"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def assessment_view(a):
    return {
        "id": a["id"],
        "period": a["period"],
        "lots_assessed": a["lots_assessed"],
        "total_storage_charge_cents": a["total_storage_charge_cents"],
        "total_invisible_loss_bu": f2(a["total_invisible_loss_bu"]),
        "contracts_defaulted": a["contracts_defaulted"],
        "contracts_fulfilled": a["contracts_fulfilled"],
        "permits_expired": a["permits_expired"],
        "loadouts_expired": a["loadouts_expired"],
        "policies_expired": a["policies_expired"],
        "created_at": a["created_at"],
    }


def shrink_event_view(e):
    return {
        "id": e["id"],
        "lot_id": e["lot_id"],
        "kind": e["kind"],
        "shrink_bu": f2(e["shrink_bu"]),
        "period": e["period"],
        "created_at": e["created_at"],
    }


# ---------------------------------------------------------------------------
# Monthly assessment epoch (PRD 3.7)
# ---------------------------------------------------------------------------

def run_assessment(period):
    py = int(period[0:4])
    pm = int(period[5:7])
    now = CLOCK.now()

    lots_assessed = 0
    total_charge = 0
    total_loss = ZERO2
    affected_bins = set()

    lots_sorted = sorted(db.lots.values(), key=lambda l: (l["created_at"], l["seq"]))
    for lot in lots_sorted:
        if lot["current_bu"] <= 0:
            continue
        if (lot["fill_date"].year, lot["fill_date"].month) > (py, pm):
            continue
        pre = lot["current_bu"]  # charge and loss both use the pre-loss balance
        diff = month_diff(lot["fill_date"], py, pm)
        rate = storage_rate_cents(diff)
        charge = q0(pre * rate)
        lot["cumulative_storage_charge_cents"] += charge
        lot["months_assessed"] += 1
        loss = q2(pre * INVISIBLE_LOSS_MONTHLY_PCT / Decimal("100"))
        if loss > 0:
            ev = new_event()
            ev.update({"lot_id": lot["id"], "kind": "INVISIBLE_LOSS",
                       "shrink_bu": loss, "period": period})
            db.shrink_events[ev["id"]] = ev
        lot["current_bu"] = q2(pre - loss)
        lot["cumulative_invisible_loss_bu"] = q2(lot["cumulative_invisible_loss_bu"] + loss)
        if lot["current_bu"] <= 0:
            lot["current_bu"] = ZERO2
            lot["status"] = "DEPLETED"
        touch(lot)
        lots_assessed += 1
        total_charge += charge
        total_loss = q2(total_loss + loss)
        affected_bins.add(lot["bin_id"])

    contracts_defaulted = 0
    contracts_fulfilled = 0
    for c in sorted(db.contracts.values(), key=lambda r: (r["created_at"], r["seq"])):
        if c["status"] in ("OPEN", "DELIVERING") and c["window_end"] < now:
            if is_fulfilled(c):
                c["status"] = "FULFILLED"
                contracts_fulfilled += 1
            else:
                c["status"] = "DEFAULTED"
                contracts_defaulted += 1
            touch(c)

    loadouts_expired = 0
    for lo in sorted(db.loadouts.values(), key=lambda r: (r["created_at"], r["seq"])):
        if lo["transport_status"] in ("SCHEDULED", "HELD") and lo["scheduled_end"] < now:
            was = lo["transport_status"]
            lo["transport_status"] = "EXPIRED"
            touch(lo)
            loadouts_expired += 1
            if was == "SCHEDULED":
                # SCHEDULED expiry releases committed bushels and bumps the
                # contract; HELD loadouts were already excluded (no release).
                c = db.contracts.get(lo["contract_id"])
                if c is not None:
                    touch(c)

    permits_expired = 0
    for p in sorted(db.permits.values(), key=lambda r: (r["created_at"], r["seq"])):
        if p["status"] in ("REQUESTED", "APPROVED") and p["planned_end"] < now:
            p["status"] = "EXPIRED"
            touch(p)
            permits_expired += 1

    policies_expired = 0
    for pol in sorted(db.policies.values(), key=lambda r: (r["created_at"], r["seq"])):
        if pol["status"] == "ACTIVE" and pol["period_end"] < now:
            pol["status"] = "EXPIRED"
            touch(pol)
            policies_expired += 1

    # The assessment epoch is a posture-recompute trigger for every bin;
    # inventory is recomputed for bins whose lots moved.
    for b in db.bins.values():
        snap = bin_snap(b)
        if b["id"] in affected_bins:
            recompute_inventory(b)
        recompute_posture(b)
        finalize_bin(b, snap)

    rec = new_event()
    rec.update({
        "period": period,
        "lots_assessed": lots_assessed,
        "total_storage_charge_cents": total_charge,
        "total_invisible_loss_bu": q2(total_loss),
        "contracts_defaulted": contracts_defaulted,
        "contracts_fulfilled": contracts_fulfilled,
        "permits_expired": permits_expired,
        "loadouts_expired": loadouts_expired,
        "policies_expired": policies_expired,
    })
    db.assessments[rec["id"]] = rec
    return rec
