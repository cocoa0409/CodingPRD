"""Calculation rules (SCAFFOLD §1.3 / PRD §3). All money in integer cents."""
from decimal import Decimal, ROUND_HALF_UP

from db import db
from validation import clock_now, parse_iso


def round_half_up(value):
    """Round a Decimal/number half-up to a whole integer."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# compute_install_fee — round per line AFTER discount, then sum.
# ---------------------------------------------------------------------------
def compute_install_fee(accepted_proposal):
    lines = [li for li in db.proposal_line_items.values()
             if li["proposal_id"] == accepted_proposal["id"]]
    total_units = sum(li["quantity"] for li in lines)
    if total_units < 50:
        bundle_pct = Decimal("0.00")
    elif total_units < 100:
        bundle_pct = Decimal("0.05")
    elif total_units < 200:
        bundle_pct = Decimal("0.10")
    else:
        bundle_pct = Decimal("0.15")

    fee = 0
    for li in lines:
        line_raw = Decimal(li["unit_install_cents"]) * Decimal(li["quantity"]) * (Decimal(1) - bundle_pct)
        fee += round_half_up(line_raw)
    return fee


# ---------------------------------------------------------------------------
# compute_storage_fee — threshold over STORED lots only.
# ---------------------------------------------------------------------------
def compute_storage_fee(contract):
    stored_units = sum(
        lot["unit_count"] for lot in db.storage_lots.values()
        if lot["contract_id"] == contract["id"] and lot["status"] == "STORED"
    )
    if stored_units <= 20:
        return 15000
    return 15000 + (stored_units - 20) * 600


# ---------------------------------------------------------------------------
# compute_contract_total — pinned evaluation order.
# Returns (install, storage, early_bird_discount, total).
# ---------------------------------------------------------------------------
def compute_contract_total(contract, accepted_proposal):
    install = compute_install_fee(accepted_proposal)
    storage = compute_storage_fee(contract)
    surcharge = contract.get("custom_design_surcharge_cents") or 0

    ctype = contract["contract_type"]
    deadline = parse_iso(contract["early_bird_deadline"])
    now = clock_now()
    qualifies = now is not None and deadline is not None and now <= deadline
    if qualifies and ctype == "COMMERCIAL":
        eb_pct = Decimal("0.10")
    elif qualifies and ctype == "HOA":
        eb_pct = Decimal("0.12")
    else:
        eb_pct = Decimal("0.00")

    early_bird_discount = round_half_up(Decimal(install + storage) * eb_pct)
    total = install + storage + surcharge - early_bird_discount
    return install, storage, early_bird_discount, total


# ---------------------------------------------------------------------------
# compute_route_minutes — round per leg, then sum.
# ---------------------------------------------------------------------------
AVG_SPEED_KMH = 40


def _ordered_visits(work_order_id):
    visits = [v for v in db.visits.values() if v["work_order_id"] == work_order_id]
    return sorted(visits, key=lambda v: (v["stop_sequence"], v.get("created_at", ""), v.get("_seq", 0)))


def compute_route_minutes(work_order):
    visits = _ordered_visits(work_order["id"])
    drive_minutes = 0
    for v in visits:
        leg_raw = Decimal(str(v["leg_distance_km"])) / Decimal(AVG_SPEED_KMH) * Decimal(60)
        drive_minutes += round_half_up(leg_raw)
    onsite_minutes = sum(v["on_site_minutes"] for v in visits)
    return drive_minutes + onsite_minutes


# ---------------------------------------------------------------------------
# compute_damage_settlement — pinned order; loyalty waiver cross-entity.
# Returns (replacement_cost, settlement_total).
# ---------------------------------------------------------------------------
def _contract_in_renewal_posture(contract):
    if contract is None:
        return False
    if contract["status"] == "RENEWAL_OFFERED":
        return True
    for offer in db.renewal_offers.values():
        if offer["contract_id"] == contract["id"] and offer["status"] == "SENT":
            return True
    return False


def compute_damage_settlement(damage_report, inventory_item, contract):
    replacement_cost = damage_report["damaged_qty"] * inventory_item["unit_replacement_cents"]
    if replacement_cost < 50000:
        base_pct = Decimal("0.20")
    elif replacement_cost < 150000:
        base_pct = Decimal("0.15")
    else:
        base_pct = Decimal("0.10")

    if _contract_in_renewal_posture(contract):
        effective_pct = base_pct - Decimal("0.05")
        if effective_pct < Decimal("0.05"):
            effective_pct = Decimal("0.05")
    else:
        effective_pct = base_pct

    labor_fee = round_half_up(Decimal(replacement_cost) * effective_pct)
    settlement_total = replacement_cost + labor_fee
    return replacement_cost, settlement_total


# ---------------------------------------------------------------------------
# compute_renewal_price — PROVISIONAL vs FINAL.
# ---------------------------------------------------------------------------
def _escalated_base(contract):
    base = contract.get("total_amount_cents") or 0
    ctype = contract["contract_type"]
    escalation_pct = Decimal("0.05") if ctype in ("COMMERCIAL", "HOA") else Decimal("0.00")
    return round_half_up(Decimal(base) * (Decimal(1) + escalation_pct))


def compute_renewal_price_provisional(contract):
    return _escalated_base(contract)


def compute_renewal_price_final(contract):
    escalated = _escalated_base(contract)
    # unsettled damage carry-forward: DamageReports in ASSESSED for this
    # contract's work orders.
    wo_ids = {wo["id"] for wo in db.work_orders.values()
              if wo["contract_id"] == contract["id"]}
    unsettled = sum(
        dr["settlement_total_cents"] for dr in db.damage_reports.values()
        if dr["work_order_id"] in wo_ids and dr["status"] == "ASSESSED"
        and dr.get("settlement_total_cents") is not None
    )
    return escalated + unsettled


# ---------------------------------------------------------------------------
# compute_crew_utilization — PLANNED and ACTUAL.
# ---------------------------------------------------------------------------
def compute_crew_utilization_planned(crew):
    work_orders = [wo for wo in db.work_orders.values()
                   if wo.get("crew_id") == crew["id"]
                   and wo["schedule_status"] in ("SCHEDULED", "DISPATCHED")]
    if not work_orders:
        return 0
    # group by scheduled_date
    by_date = {}
    for wo in work_orders:
        d = wo.get("scheduled_date")
        if d is None:
            continue
        by_date.setdefault(d, 0)
        by_date[d] += wo.get("route_total_minutes") or 0
    if not by_date:
        return 0
    # busiest date: greatest summed minutes, ties broken by earliest date ASC
    busiest_date = max(by_date.items(), key=lambda kv: (kv[1], _neg_date_key(kv[0])))[0]
    planned_minutes = by_date[busiest_date]
    cap = crew["daily_capacity_minutes"]
    return round_half_up(Decimal(planned_minutes) / Decimal(cap) * Decimal(100))


def _neg_date_key(date_str):
    # for tie-break "earliest date ASC" when selecting max: we want smaller date
    # to win ties. max() picks the largest tuple, so invert via parse + sentinel.
    dt = parse_iso(date_str)
    if dt is None:
        return 0
    # negative timestamp so earlier date yields larger value under max()
    return -dt.timestamp()


def compute_crew_utilization_actual(crew):
    completed_wos = [wo for wo in db.work_orders.values()
                     if wo.get("crew_id") == crew["id"]
                     and wo["schedule_status"] == "COMPLETED"]
    if not completed_wos:
        return 0
    by_date = {}
    for wo in completed_wos:
        d = wo.get("scheduled_date")
        if d is None:
            continue
        by_date.setdefault(d, 0)
        by_date[d] += wo.get("route_total_minutes") or 0
    if not by_date:
        return 0
    busiest_date = max(by_date.items(), key=lambda kv: (kv[1], _neg_date_key(kv[0])))[0]
    # sum actual_minutes of COMPLETED visits on COMPLETED WorkOrders on busiest date
    actual_minutes = 0
    for wo in completed_wos:
        if wo.get("scheduled_date") != busiest_date:
            continue
        for v in db.visits.values():
            if v["work_order_id"] == wo["id"] and v["visit_status"] == "COMPLETED":
                actual_minutes += v.get("actual_minutes") or 0
    cap = crew["daily_capacity_minutes"]
    return round_half_up(Decimal(actual_minutes) / Decimal(cap) * Decimal(100))
