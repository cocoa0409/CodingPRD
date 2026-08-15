"""Domain core: record factory, computed aggregates, serializers, cascades,
and the calculation rules of PRD §3 / SCAFFOLD §1.3.

All money is integer cents; all 2-decimal performance metrics round half-up via
Decimal; occupancy intervals are half-open [placement_date, target_market_date).
"""

from datetime import timedelta
from decimal import Decimal

from db import store, new_id, fmt_ts
from errors import conflict, ERR_INVALID_STATE_TRANSITION
from util import round2, round_half_up_int

# --- calculation constants (SCAFFOLD §1.3) ---
SQFT_PER_HEAD = 8
ADG_PROJECTION_LBS_PER_DAY = Decimal("1.85")
PROJ_FCR = Decimal("2.70")
WASH_VALIDITY_HOURS = 48
BARN_DOWNTIME_HOURS = 72
REJECT_PENALTY_CENTS_PER_HEAD = 1500
TICKET_APPROVAL_THRESHOLD_CENTS = 50000
PHASE_PLAN_PCT = {
    "STARTER": Decimal("0.15"),
    "GROWER": Decimal("0.30"),
    "FINISHER_1": Decimal("0.30"),
    "FINISHER_2": Decimal("0.25"),
}
PHASE_ORDER = ["STARTER", "GROWER", "FINISHER_1", "FINISHER_2"]

# statuses that keep a feed order's quantity in the committed drawdown
FEED_COMMITTED_STATUSES = ("REQUESTED", "SCHEDULED")
FEED_DELIVERED_STATUSES = ("DELIVERED", "SHORTED")
# statuses that keep a load in its slot's reserved set
LOAD_RESERVED_STATUSES = ("SCHEDULED", "DISPATCHED", "DELIVERED", "REJECTED_AT_PLANT")
# groups that block barn occupancy / contract exits / site decommission
GROUP_ACTIVE_STATUSES = ("SCHEDULED", "PLACED", "MARKETING")
# settlement statuses that keep absorption of new deductions live
SETTLEMENT_DEDUCTION_LIVE_STATUSES = ("FINALIZED", "DISPUTED")
SETTLEMENT_PENDING_STATUSES = ("FINALIZED", "DISPUTED", "APPROVED")
# ticket statuses that block a barn's return to service
TICKET_OPEN_STATUSES = ("OPEN", "QUOTED", "APPROVED", "IN_PROGRESS")


# ---------------------------------------------------------------------------
# record plumbing
# ---------------------------------------------------------------------------

def new_record():
    """Common fields (PRD §2.5): id, created_at, updated_at, version."""
    now = store.now_str()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }


def touch(rec):
    """Every mutation refreshes updated_at and increments version (§2.5),
    including mutations caused by cascades originating on other resources (§2.8)."""
    rec["updated_at"] = store.now_str()
    rec["version"] += 1


# ---------------------------------------------------------------------------
# computed aggregates
# ---------------------------------------------------------------------------

def site_total_capacity_head(site_id):
    """Sum of capacity_head over barns with barn_status != OUT_OF_SERVICE."""
    total = 0
    for b in store.barns.values():
        if b["site_id"] == site_id and b["barn_status"] != "OUT_OF_SERVICE":
            total += b["capacity_head"]
    return total


def reconcile_site_capacity(site_id):
    """Recompute a site's total_capacity_head; bump the site when it moved (§2.8)."""
    site = store.sites.get(site_id)
    if site is None:
        return
    new_total = site_total_capacity_head(site_id)
    if site.get("total_capacity_head") != new_total:
        site["total_capacity_head"] = new_total
        touch(site)


def group_reports(group_id):
    return [r for r in store.mortality_reports.values() if r["group_id"] == group_id]


def group_orders(group_id):
    return [o for o in store.feed_orders.values() if o["group_id"] == group_id]


def group_loads(group_id):
    return [l for l in store.market_loads.values() if l["group_id"] == group_id]


def group_mortality_total(group_id):
    return sum(r["mortality_count"] for r in group_reports(group_id))


def group_cull_total(group_id):
    return sum(r["cull_count"] for r in group_reports(group_id))


def group_head_marketed(group_id):
    return sum(l["head_count"] for l in group_loads(group_id)
               if l["load_status"] == "DELIVERED")


def group_live_weight(group_id):
    return sum(l["live_weight_lbs_total"] for l in group_loads(group_id)
               if l["load_status"] == "DELIVERED")


def group_cumulative_feed(group_id):
    return sum(o["delivered_lbs"] for o in group_orders(group_id)
               if o["order_status"] in FEED_DELIVERED_STATUSES)


def group_committed_feed(group_id):
    return sum(o["quantity_lbs"] for o in group_orders(group_id)
               if o["order_status"] in FEED_COMMITTED_STATUSES)


def group_phase_committed_feed(group_id, phase):
    return sum(o["quantity_lbs"] for o in group_orders(group_id)
               if o["order_status"] in FEED_COMMITTED_STATUSES and o["phase"] == phase)


def group_phase_delivered_feed(group_id, phase):
    return sum(o["delivered_lbs"] for o in group_orders(group_id)
               if o["order_status"] in FEED_DELIVERED_STATUSES and o["phase"] == phase)


def group_head_current(group):
    """head_placed - mortality - culls - marketed (pre-close); 0 after close."""
    if group["group_status"] == "CLOSED":
        return 0
    return (group["head_placed"] - group_mortality_total(group["id"])
            - group_cull_total(group["id"]) - group_head_marketed(group["id"]))


def group_mortality_pct(group):
    """round_half_up(100 * mortality_total / head_placed, 2)."""
    return round2(Decimal(100 * group_mortality_total(group["id"]))
                  / Decimal(group["head_placed"]))


def slot_reserved_head(slot_id):
    return sum(l["head_count"] for l in store.market_loads.values()
               if l["slot_id"] == slot_id and l["load_status"] in LOAD_RESERVED_STATUSES)


def slot_refresh_after_booking_change(slot):
    """Recompute reserved_head, flip OPEN<->FULL, bump slot version once (§3.5)."""
    slot["reserved_head"] = slot_reserved_head(slot["id"])
    if slot["slot_status"] == "OPEN" and slot["reserved_head"] == slot["capacity_head"]:
        slot["slot_status"] = "FULL"
    elif slot["slot_status"] == "FULL" and slot["reserved_head"] < slot["capacity_head"]:
        slot["slot_status"] = "OPEN"
    touch(slot)


def plan_applications(plan_id):
    return [a for a in store.manure_applications.values() if a["plan_id"] == plan_id]


def plan_active_applications(plan_id):
    return [a for a in plan_applications(plan_id)
            if a["application_status"] in ("RECORDED", "CONFIRMED")]


def plan_n_applied(plan_id):
    return sum(a["n_lbs"] for a in plan_active_applications(plan_id))


def plan_p_applied(plan_id):
    return sum(a["p_lbs"] for a in plan_active_applications(plan_id))


def plan_lagoon_available(plan):
    return plan["lagoon_start_gal"] - sum(a["gallons"]
                                          for a in plan_active_applications(plan["id"]))


def active_contract_on_site(site_id):
    for c in store.contracts.values():
        if c["site_id"] == site_id and c["contract_status"] == "ACTIVE":
            return c
    return None


# ---------------------------------------------------------------------------
# serializers (strip internal bookkeeping keys)
# ---------------------------------------------------------------------------

def _fnum(d):
    """Serialize a Decimal performance metric as a JSON number."""
    if d is None:
        return None
    return float(d)


def ser_site(s):
    return {
        "id": s["id"], "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"],
        "name": s["name"], "state_code": s["state_code"], "county": s["county"],
        "site_status": s["site_status"],
        "total_capacity_head": s["total_capacity_head"],
    }


def ser_grower(g):
    return {
        "id": g["id"], "created_at": g["created_at"], "updated_at": g["updated_at"],
        "version": g["version"],
        "legal_name": g["legal_name"], "grower_code": g["grower_code"],
        "email": g["email"], "grower_status": g["grower_status"],
        "balance_due_cents": g["balance_due_cents"],
        "lifetime_paid_cents": g["lifetime_paid_cents"],
    }


def ser_contract(c):
    return {
        "id": c["id"], "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
        "grower_id": c["grower_id"], "site_id": c["site_id"],
        "base_pay_cents_per_head": c["base_pay_cents_per_head"],
        "bonus_cap_cents_per_head": c["bonus_cap_cents_per_head"],
        "fcr_target": _fnum(c["fcr_target"]),
        "adg_target_lbs": _fnum(c["adg_target_lbs"]),
        "mortality_threshold_pct": _fnum(c["mortality_threshold_pct"]),
        "feed_budget_lbs_per_head": c["feed_budget_lbs_per_head"],
        "structural_owner_pct": c["structural_owner_pct"],
        "equipment_owner_pct": c["equipment_owner_pct"],
        "routine_owner_pct": c["routine_owner_pct"],
        "effective_date": c["effective_date"].isoformat(),
        "expiry_date": c["expiry_date"].isoformat(),
        "contract_status": c["contract_status"],
    }


def ser_barn(b):
    return {
        "id": b["id"], "created_at": b["created_at"], "updated_at": b["updated_at"],
        "version": b["version"],
        "site_id": b["site_id"], "barn_code": b["barn_code"],
        "capacity_head": b["capacity_head"], "floor_space_sqft": b["floor_space_sqft"],
        "barn_status": b["barn_status"], "wash_required": b["wash_required"],
        "downtime_until": fmt_ts(b["downtime_until"]) if b["downtime_until"] else None,
        "current_group_id": b["current_group_id"],
    }


def ser_pig_group(g):
    gid = g["id"]
    return {
        "id": gid, "created_at": g["created_at"], "updated_at": g["updated_at"],
        "version": g["version"],
        "barn_id": g["barn_id"], "contract_id": g["contract_id"],
        "placement_date": g["placement_date"].isoformat(),
        "target_market_date": g["target_market_date"].isoformat(),
        "head_placed": g["head_placed"],
        "avg_start_weight_lbs": _fnum(g["avg_start_weight_lbs"]),
        "group_status": g["group_status"],
        "current_phase": g["current_phase"],
        "placed_at": fmt_ts(g["placed_at"]) if g["placed_at"] else None,
        "closed_at": fmt_ts(g["closed_at"]) if g["closed_at"] else None,
        "mortality_total": group_mortality_total(gid),
        "cull_total": group_cull_total(gid),
        "head_marketed": group_head_marketed(gid),
        "head_unaccounted": g["head_unaccounted"],
        "head_current": group_head_current(g),
        "total_live_weight_lbs": group_live_weight(gid),
        "cumulative_feed_lbs": group_cumulative_feed(gid),
        "mortality_pct": _fnum(group_mortality_pct(g)),
        "pending_deductions_cents": g["pending_deductions_cents"],
    }


def ser_feed_order(o):
    return {
        "id": o["id"], "created_at": o["created_at"], "updated_at": o["updated_at"],
        "version": o["version"],
        "group_id": o["group_id"], "phase": o["phase"], "diet_code": o["diet_code"],
        "quantity_lbs": o["quantity_lbs"],
        "requested_delivery_date": o["requested_delivery_date"].isoformat(),
        "scheduled_delivery_date": (o["scheduled_delivery_date"].isoformat()
                                    if o["scheduled_delivery_date"] else None),
        "delivered_lbs": o["delivered_lbs"],
        "over_phase_plan": o["over_phase_plan"],
        "order_status": o["order_status"],
    }


def ser_mortality_report(r):
    # append-only event: id + created_at only (no updated_at / version, §2.5)
    return {
        "id": r["id"], "created_at": r["created_at"],
        "group_id": r["group_id"], "report_date": r["report_date"].isoformat(),
        "mortality_count": r["mortality_count"], "cull_count": r["cull_count"],
        "reason_code": r["reason_code"],
    }


def ser_packer_slot(s):
    return {
        "id": s["id"], "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"],
        "plant_code": s["plant_code"], "slot_date": s["slot_date"].isoformat(),
        "shift": s["shift"], "capacity_head": s["capacity_head"],
        "min_weight_lbs": s["min_weight_lbs"], "max_weight_lbs": s["max_weight_lbs"],
        "reserved_head": s["reserved_head"], "slot_status": s["slot_status"],
    }


def ser_truck_wash(w):
    return {
        "id": w["id"], "created_at": w["created_at"], "updated_at": w["updated_at"],
        "version": w["version"],
        "truck_code": w["truck_code"], "washed_at": fmt_ts(w["washed_at"]),
        "wash_type": w["wash_type"], "recorded_by": w["recorded_by"],
        "verified_by": w["verified_by"], "wash_status": w["wash_status"],
    }


def ser_market_load(l):
    return {
        "id": l["id"], "created_at": l["created_at"], "updated_at": l["updated_at"],
        "version": l["version"],
        "group_id": l["group_id"], "slot_id": l["slot_id"],
        "head_count": l["head_count"],
        "truck_wash_id": l["truck_wash_id"],
        "live_weight_lbs_total": l["live_weight_lbs_total"],
        "avg_weight_lbs": _fnum(l["avg_weight_lbs"]),
        "load_status": l["load_status"],
    }


def ser_barn_wash(w):
    return {
        "id": w["id"], "created_at": w["created_at"], "updated_at": w["updated_at"],
        "version": w["version"],
        "barn_id": w["barn_id"], "wash_type": w["wash_type"],
        "completed_at": fmt_ts(w["completed_at"]),
        "recorded_by": w["recorded_by"], "verified_by": w["verified_by"],
        "wash_status": w["wash_status"],
    }


def ser_manure_plan(p):
    return {
        "id": p["id"], "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
        "site_id": p["site_id"], "plan_year": p["plan_year"],
        "lagoon_capacity_gal": p["lagoon_capacity_gal"],
        "lagoon_start_gal": p["lagoon_start_gal"],
        "n_budget_lbs": p["n_budget_lbs"], "p_budget_lbs": p["p_budget_lbs"],
        "submitted_by": p["submitted_by"], "plan_status": p["plan_status"],
        "n_applied_lbs": plan_n_applied(p["id"]),
        "p_applied_lbs": plan_p_applied(p["id"]),
        "lagoon_available_gal": plan_lagoon_available(p),
    }


def ser_manure_application(a):
    return {
        "id": a["id"], "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"],
        "plan_id": a["plan_id"], "field_code": a["field_code"],
        "applied_at": fmt_ts(a["applied_at"]),
        "gallons": a["gallons"], "n_lbs": a["n_lbs"], "p_lbs": a["p_lbs"],
        "application_status": a["application_status"],
    }


def ser_maintenance_ticket(t):
    return {
        "id": t["id"], "created_at": t["created_at"], "updated_at": t["updated_at"],
        "version": t["version"],
        "barn_id": t["barn_id"], "contract_id": t["contract_id"],
        "grower_id": t["grower_id"], "category": t["category"],
        "description": t["description"],
        "cause": t["cause"], "cost_cents": t["cost_cents"],
        "quoted_by": t["quoted_by"], "approved_by": t["approved_by"],
        "approved_flag": t["approved_flag"],
        "owner_share_cents": t["owner_share_cents"],
        "grower_share_cents": t["grower_share_cents"],
        "completed_at": fmt_ts(t["completed_at"]) if t["completed_at"] else None,
        "ticket_status": t["ticket_status"],
    }


def ser_settlement(s):
    return {
        "id": s["id"], "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"],
        "group_id": s["group_id"], "contract_id": s["contract_id"],
        "head_marketed": s["head_marketed"],
        "total_live_weight_lbs": s["total_live_weight_lbs"],
        "days_on_feed": s["days_on_feed"],
        "fcr": _fnum(s["fcr"]), "adg_lbs": _fnum(s["adg_lbs"]),
        "mortality_pct": _fnum(s["mortality_pct"]),
        "base_pay_cents": s["base_pay_cents"], "bonus_cents": s["bonus_cents"],
        "deductions_cents": s["deductions_cents"],
        "adjustment_cents": s["adjustment_cents"],
        "total_pay_cents": s["total_pay_cents"],
        "approved_by": s["approved_by"], "paid_by": s["paid_by"],
        "settlement_status": s["settlement_status"],
    }


# ---------------------------------------------------------------------------
# calculations
# ---------------------------------------------------------------------------

def performance_bonus_cents(contract, head_placed, head_unaccounted,
                            mortality_pct, fcr, adg_lbs):
    """PRD §3.8 performance bonus: two gates, four FCR tiers, ADG growth factor,
    single final half-up rounding of the whole chain (no intermediate rounding)."""
    if head_unaccounted > 0:
        return 0
    if mortality_pct > contract["mortality_threshold_pct"]:
        return 0
    if fcr is None or adg_lbs is None:
        return 0
    target = contract["fcr_target"]
    if fcr <= round2(target - Decimal("0.10")):
        tier = Decimal("1.00")
    elif fcr <= target:
        tier = Decimal("0.60")
    elif fcr <= round2(target + Decimal("0.10")):
        tier = Decimal("0.30")
    else:
        tier = Decimal("0.00")
    adg_factor = Decimal("1.0") if adg_lbs >= contract["adg_target_lbs"] else Decimal("0.5")
    return round_half_up_int(Decimal(contract["bonus_cap_cents_per_head"])
                             * Decimal(head_placed) * tier * adg_factor)


def mint_settlement(group):
    """Create the group's 1:1 Settlement in FINALIZED (settlement_pay FINAL variant)."""
    contract = store.contracts[group["contract_id"]]
    gid = group["id"]
    head_marketed = group_head_marketed(gid)
    total_live = group_live_weight(gid)
    cumulative_feed = group_cumulative_feed(gid)
    days_on_feed = (group["closed_at"].date() - group["placement_date"]).days
    # weight gain = live weight out minus start weight of the marketed head
    weight_gain = Decimal(total_live) - Decimal(head_marketed) * group["avg_start_weight_lbs"]
    if head_marketed >= 1 and weight_gain > 0 and days_on_feed > 0:
        fcr = round2(Decimal(cumulative_feed) / weight_gain)
        adg = round2(weight_gain / (Decimal(head_marketed) * Decimal(days_on_feed)))
    else:
        fcr = None
        adg = None
    mort_pct = group_mortality_pct(group)
    base_pay = group["head_placed"] * contract["base_pay_cents_per_head"]
    bonus = performance_bonus_cents(contract, group["head_placed"],
                                    group["head_unaccounted"], mort_pct, fcr, adg)
    deductions = group["pending_deductions_cents"]
    adjustment = 0
    rec = new_record()
    rec.update({
        "group_id": gid,
        "contract_id": group["contract_id"],
        "head_marketed": head_marketed,
        "total_live_weight_lbs": total_live,
        "days_on_feed": days_on_feed,
        "fcr": fcr,
        "adg_lbs": adg,
        "mortality_pct": mort_pct,
        "base_pay_cents": base_pay,
        "bonus_cents": bonus,
        "deductions_cents": deductions,
        "adjustment_cents": adjustment,
        "total_pay_cents": base_pay + bonus + adjustment - deductions,
        "approved_by": None,
        "paid_by": None,
        "settlement_status": "FINALIZED",
    })
    store.settlements[rec["id"]] = rec
    return rec


def settlement_for_group(group_id):
    for s in store.settlements.values():
        if s["group_id"] == group_id:
            return s
    return None


def recompute_settlement_deductions(group):
    """While a settlement sits in FINALIZED or DISPUTED, new penalties/negligence
    charges recompute deductions_cents and total_pay_cents (§3.5, §3.7, §3.8)."""
    stl = settlement_for_group(group["id"])
    if stl is not None and stl["settlement_status"] in SETTLEMENT_DEDUCTION_LIVE_STATUSES:
        stl["deductions_cents"] = group["pending_deductions_cents"]
        stl["total_pay_cents"] = (stl["base_pay_cents"] + stl["bonus_cents"]
                                  + stl["adjustment_cents"] - stl["deductions_cents"])
        touch(stl)


def close_group(group, force):
    """PigGroup -> CLOSED cascade (§3.8): unaccounted head on the force path,
    occupying barn -> WASH_REQUIRED, settlement minted FINALIZED."""
    now = store.now()
    if force:
        group["head_unaccounted"] = group_head_current(group)
    group["group_status"] = "CLOSED"
    group["closed_at"] = now
    touch(group)
    barn = store.barns.get(group["barn_id"])
    if barn is not None and barn["current_group_id"] == group["id"]:
        barn["barn_status"] = "WASH_REQUIRED"
        barn["current_group_id"] = None
        barn["wash_required"] = True
        touch(barn)
    mint_settlement(group)


def maybe_auto_close(group):
    """Natural close: head_current reached 0 after a report or a delivery."""
    if group["group_status"] in ("PLACED", "MARKETING") and group_head_current(group) == 0:
        close_group(group, force=False)
        return True
    return False


def maintenance_cost_split(contract, category, cause, cost_cents):
    """PRD §3.7: pinned owner-first rounding; grower takes the remainder.
    NEGLIGENCE bypasses the split entirely (owner 0, grower all)."""
    if cause == "NEGLIGENCE":
        return 0, cost_cents
    if category == "STRUCTURAL":
        pct = contract["structural_owner_pct"]
    elif category == "EQUIPMENT":
        pct = contract["equipment_owner_pct"]
    else:  # ROUTINE or EMERGENCY
        pct = contract["routine_owner_pct"]
    owner = round_half_up_int(Decimal(cost_cents) * Decimal(pct) / Decimal(100))
    return owner, cost_cents - owner


def occupancy_overlaps(barn_id, placement_date, target_market_date):
    """Half-open [placement_date, target_market_date) collision against any other
    SCHEDULED/PLACED/MARKETING group on the same barn (touching is legal)."""
    for g in store.pig_groups.values():
        if g["barn_id"] != barn_id or g["group_status"] not in GROUP_ACTIVE_STATUSES:
            continue
        if placement_date < g["target_market_date"] and g["placement_date"] < target_market_date:
            return True
    return False


def projected_avg_weight(group, slot):
    """round_half_up(avg_start + 1.85 * days(placement -> slot_date), 2)."""
    days = (slot["slot_date"] - group["placement_date"]).days
    if days < 0:
        days = 0
    return round2(group["avg_start_weight_lbs"]
                  + ADG_PROJECTION_LBS_PER_DAY * Decimal(days))


def wash_in_use_by_other_load(wash_id, exclude_load_id=None):
    for l in store.market_loads.values():
        if l["id"] == exclude_load_id:
            continue
        if l.get("truck_wash_id") == wash_id and l["load_status"] in (
                "DISPATCHED", "DELIVERED", "REJECTED_AT_PLANT"):
            return True
    return False


def charge_negligence_share(ticket, grower_share_cents):
    """PRD §3.7: a completed NEGLIGENCE ticket charges its grower share to the pig
    group on the barn whose [placement_date, closed_at] contains the completion
    instant (recomputing its FINALIZED/DISPUTED settlement), else to the grower's
    balance_due_cents (no such group, or settlement already APPROVED/PAID)."""
    now = store.now()
    target = None
    for g in store.pig_groups.values():
        if g["barn_id"] != ticket["barn_id"]:
            continue
        # only groups that actually occupied the barn have a "stay" to contain the
        # completion instant (a SCHEDULED group's stay has not begun; a CANCELLED
        # group never had one)
        if g["group_status"] not in ("PLACED", "MARKETING", "CLOSED"):
            continue
        if g["placement_date"] > now.date():
            continue
        if g["closed_at"] is not None and g["closed_at"] < now:
            continue
        if target is None or (g["closed_at"] is None and target["closed_at"] is not None):
            target = g
    if target is not None:
        stl = settlement_for_group(target["id"])
        if stl is None or stl["settlement_status"] in SETTLEMENT_DEDUCTION_LIVE_STATUSES:
            target["pending_deductions_cents"] += grower_share_cents
            touch(target)
            recompute_settlement_deductions(target)
            return
    grower = store.growers.get(ticket["grower_id"])
    if grower is not None:
        grower["balance_due_cents"] += grower_share_cents
        touch(grower)


def settlement_preview(group):
    """settlement_pay PROVISIONAL variant (§3.8): blend actuals with projection for
    the head_current pigs not yet marketed. Requires PLACED/MARKETING (checked by
    the route), head_current >= 1 and positive provisional weight gain."""
    contract = store.contracts[group["contract_id"]]
    gid = group["id"]
    head_marketed = group_head_marketed(gid)
    total_live = group_live_weight(gid)
    cumulative_feed = group_cumulative_feed(gid)
    head_current = group_head_current(group)
    clock_date = store.now().date()
    rem_days = (group["target_market_date"] - clock_date).days
    if rem_days < 0:
        rem_days = 0
    proj_gain_per_head = ADG_PROJECTION_LBS_PER_DAY * Decimal(rem_days)
    proj_feed_per_head = proj_gain_per_head * PROJ_FCR
    actual_weight_gain = (Decimal(total_live)
                          - Decimal(head_marketed) * group["avg_start_weight_lbs"])
    prov_weight_gain = actual_weight_gain + Decimal(head_current) * proj_gain_per_head
    if head_current < 1 or prov_weight_gain <= 0:
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       "Preview requires head on feed and positive provisional weight gain")
    total_days = (group["target_market_date"] - group["placement_date"]).days
    prov_fcr = round2((Decimal(cumulative_feed)
                       + Decimal(head_current) * proj_feed_per_head) / prov_weight_gain)
    prov_adg = round2(prov_weight_gain
                      / (Decimal(head_marketed + head_current) * Decimal(total_days)))
    prov_mort = group_mortality_pct(group)
    bonus = performance_bonus_cents(contract, group["head_placed"], 0,
                                    prov_mort, prov_fcr, prov_adg)
    base_pay = group["head_placed"] * contract["base_pay_cents_per_head"]
    deductions = group["pending_deductions_cents"]
    adjustment = 0
    return {
        "variant": "PROVISIONAL",
        "base_pay_cents": base_pay,
        "bonus_cents": bonus,
        "deductions_cents": deductions,
        "adjustment_cents": adjustment,
        "total_pay_cents": base_pay + bonus + adjustment - deductions,
        "fcr": float(prov_fcr),
        "adg_lbs": float(prov_adg),
        "mortality_pct": float(prov_mort),
        "head_projected_marketed": head_marketed + head_current,
    }
