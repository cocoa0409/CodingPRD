"""Domain logic: lookups, computed fields, serializers, calculations, cascades, sweeps."""
import math
from datetime import timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from core import DB, ApiError, clock, iso, now_iso, stamp_new, touch

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD calculations table)
# ---------------------------------------------------------------------------

FUEL_WEIGHT = {"GRASS": 20, "BRUSH": 35, "TIMBER": 50}
SLOPE_WEIGHT = {"FLAT": 0, "MODERATE": 10, "STEEP": 20}
WUI_BONUS = 20

FUEL_FACTOR = {"GRASS": Decimal("1.0"), "BRUSH": Decimal("1.5"), "TIMBER": Decimal("2.0")}

RATE_CENTS = {"GRASS": 15327, "BRUSH": 28750, "TIMBER": 46000}
SHARE_PCT = {"STANDARD": Decimal("0.50"), "PRIORITY": Decimal("0.75"), "LEGACY": Decimal("0.65")}
CATEGORY_WEIGHT = {"BROADCAST": Decimal("1.0"), "UNDERSTORY": Decimal("0.8"), "PILE_BURN": Decimal("0.6")}

PER_ACRE_CENTS = 25000
NEGLIGENCE_MULTIPLIER = Decimal("1.5")
FUND_PAYOUT_FRACTION = Decimal("0.5")
FUND_LOW_THRESHOLD_CENTS = 200000
FRESHNESS_LIMIT_MINUTES = 60
LEAD_TIME_HOURS = 48

EXECUTION_TERMINAL = {"CLOSED", "STOOD_DOWN", "CANCELLED", "LAPSED", "WILDFIRE_RESPONSE"}
REQUIRED_CHECKLIST_ITEMS = {
    "permit_verified",
    "crew_briefed",
    "communications_check",
    "escape_routes_reviewed",
    "weather_within_prescription",
    "holding_resources_ready",
}


def round_half_up_cents(d):
    return int(Decimal(d).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Lookups (resource-specific 404s, validated left-to-right by callers)
# ---------------------------------------------------------------------------


def _get(coll, eid, err):
    e = DB[coll].get(eid)
    if e is None:
        raise ApiError(err, 404, f"Resource {eid} not found")
    return e


def get_association(aid):
    return _get("associations", aid, "ERR_ASSOCIATION_NOT_FOUND")


def get_landowner(lid):
    return _get("landowners", lid, "ERR_LANDOWNER_NOT_FOUND")


def get_parcel(pid):
    return _get("parcels", pid, "ERR_PARCEL_NOT_FOUND")


def get_boss(bid):
    return _get("bosses", bid, "ERR_BOSS_NOT_FOUND")


def get_contractor(cid):
    return _get("contractors", cid, "ERR_CONTRACTOR_NOT_FOUND")


def get_plan(pid):
    return _get("plans", pid, "ERR_PLAN_NOT_FOUND")


def get_permit(pid):
    return _get("permits", pid, "ERR_PERMIT_NOT_FOUND")


def get_notification(nid):
    return _get("notifications", nid, "ERR_NOTIFICATION_NOT_FOUND")


def get_smoke(sid):
    return _get("smoke_approvals", sid, "ERR_SMOKE_APPROVAL_NOT_FOUND")


def get_contingency(cid):
    return _get("contingencies", cid, "ERR_CONTINGENCY_NOT_FOUND")


def get_ignition(iid):
    return _get("ignition_plans", iid, "ERR_IGNITION_PLAN_NOT_FOUND")


def get_order(oid):
    return _get("orders", oid, "ERR_ORDER_NOT_FOUND")


def get_assignment(aid):
    return _get("assignments", aid, "ERR_ASSIGNMENT_NOT_FOUND")


def get_execution(eid):
    return _get("executions", eid, "ERR_EXECUTION_NOT_FOUND")


def get_incident(iid):
    return _get("incidents", iid, "ERR_INCIDENT_NOT_FOUND")


def get_report(rid):
    return _get("reports", rid, "ERR_REPORT_NOT_FOUND")


def get_agreement(aid):
    return _get("agreements", aid, "ERR_AGREEMENT_NOT_FOUND")


def get_claim(cid):
    return _get("claims", cid, "ERR_CLAIM_NOT_FOUND")


def the_association():
    """The program's fund/policy association (singleton per program)."""
    if not DB["associations"]:
        return None
    return sorted(DB["associations"].values(), key=lambda e: e["_seq"])[0]


# ---------------------------------------------------------------------------
# Derived / computed fields
# ---------------------------------------------------------------------------


def fund_posture(assoc):
    return "FUND_RESTRICTED" if assoc["fund_balance_cents"] < FUND_LOW_THRESHOLD_CENTS else "FUND_NORMAL"


def contractor_available_units(contractor):
    used = sum(
        a["units"]
        for a in DB["assignments"].values()
        if a["contractor_id"] == contractor["id"] and a["status"] in ("ASSIGNED", "CONFIRMED")
    )
    return contractor["capacity_units"] - used


def contractor_standing(contractor):
    return "SUSPENDED" if contractor["no_show_count"] >= 2 else "GOOD_STANDING"


def landowner_of_incident(incident):
    execution = DB["executions"].get(incident["burn_execution_id"])
    if not execution:
        return None
    plan = DB["plans"].get(execution["burn_plan_id"])
    if not plan:
        return None
    parcel = DB["parcels"].get(plan["parcel_id"])
    if not parcel:
        return None
    return DB["landowners"].get(parcel["landowner_id"])


def landowner_standing(landowner):
    """SUSPENDED while any LANDOWNER_LIABLE claim against them has an
    outstanding balance and adjudicated_at + 30 days < current clock."""
    now = clock()
    for claim in DB["claims"].values():
        if claim["outcome"] != "LANDOWNER_LIABLE":
            continue
        if (claim.get("landowner_share_cents") or 0) <= 0:
            continue
        if landowner_of_incident(DB["incidents"][claim["incident_id"]]) is not landowner:
            continue
        adjudicated_at = claim.get("adjudicated_at")
        if adjudicated_at and now > adjudicated_at + timedelta(days=30):
            return "SUSPENDED"
    return "GOOD_STANDING"


def permit_rollups(permit):
    notes = [
        n
        for n in DB["notifications"].values()
        if n["burn_permit_id"] == permit["id"] and n["status"] == "CONFIRMED"
    ]
    completed = len(notes)
    latest = max((n["confirmed_at"] for n in notes), default=None)
    return completed, latest


def order_confirmed(order):
    """confirmed_<type> = sum of units over CONFIRMED assignments by resource type."""
    out = {"ENGINE": 0, "HAND_CREW": 0, "DOZER": 0, "WATER_TENDER": 0}
    for a in DB["assignments"].values():
        if a["resource_order_id"] != order["id"] or a["status"] != "CONFIRMED":
            continue
        contractor = DB["contractors"].get(a["contractor_id"])
        if contractor:
            out[contractor["resource_type"]] += a["units"]
    return out


def order_is_filled(order):
    c = order_confirmed(order)
    return (
        c["ENGINE"] >= order["required_engines"]
        and c["HAND_CREW"] >= order["required_hand_crews"]
        and c["DOZER"] >= order["required_dozers"]
        and c["WATER_TENDER"] >= order["required_water_tenders"]
    )


def recompute_order_fill(order):
    """System fill-level moves: version-silent bookkeeping."""
    if order["status"] in ("DRAFT", "CANCELLED"):
        return
    c = order_confirmed(order)
    if (
        c["ENGINE"] >= order["required_engines"]
        and c["HAND_CREW"] >= order["required_hand_crews"]
        and c["DOZER"] >= order["required_dozers"]
        and c["WATER_TENDER"] >= order["required_water_tenders"]
    ):
        order["status"] = "FILLED"
    elif any(v > 0 for v in c.values()):
        order["status"] = "PARTIALLY_FILLED"
    else:
        order["status"] = "SUBMITTED"


def plan_orders(plan_id):
    return [o for o in DB["orders"].values() if o["burn_plan_id"] == plan_id]


def active_order(plan):
    """The plan's current resource order: latest created, non-CANCELLED."""
    orders = [o for o in plan_orders(plan["id"]) if o["status"] != "CANCELLED"]
    if not orders:
        return None
    return sorted(orders, key=lambda e: e["_seq"])[-1]


def plan_permit(plan_id):
    permits = [p for p in DB["permits"].values() if p["burn_plan_id"] == plan_id]
    if not permits:
        return None
    return sorted(permits, key=lambda e: e["_seq"])[-1]


def accepted_contingency(plan_id):
    for c in DB["contingencies"].values():
        if c["burn_plan_id"] == plan_id and c["status"] == "ACCEPTED":
            return c
    return None


def accepted_ignition(plan_id):
    for i in DB["ignition_plans"].values():
        if i["burn_plan_id"] == plan_id and i["status"] == "ACCEPTED":
            return i
    return None


def valid_smoke_for(plan_id, scheduled_date):
    for s in DB["smoke_approvals"].values():
        if (
            s["burn_plan_id"] == plan_id
            and s["status"] in ("APPROVED", "CONDITIONALLY_APPROVED")
            and s["requested_burn_date"] == scheduled_date
        ):
            return s
    return None


def latest_observation(execution_id):
    obs = [o for o in DB["observations"].values() if o["burn_execution_id"] == execution_id]
    if not obs:
        return None
    # greatest observed_at; tie-break: later-created row wins
    return max(obs, key=lambda o: (o["observed_at"], o["_seq"]))


def open_incidents(execution_id):
    return [
        i
        for i in DB["incidents"].values()
        if i["burn_execution_id"] == execution_id
        and i["response_status"] in ("REPORTED", "CONFIRMED")
    ]


def non_terminal_execution_on_plan(plan_id):
    for e in DB["executions"].values():
        if e["burn_plan_id"] == plan_id and e["phase"] not in EXECUTION_TERMINAL:
            return e
    return None


def non_terminal_execution_on_parcel(parcel_id, exclude_plan_id=None):
    for e in DB["executions"].values():
        plan = DB["plans"].get(e["burn_plan_id"])
        if not plan or plan["parcel_id"] != parcel_id:
            continue
        if exclude_plan_id and plan["id"] == exclude_plan_id:
            continue
        if e["phase"] not in EXECUTION_TERMINAL:
            return e
    return None


def closed_executions_on_parcel(parcel_id):
    out = []
    for e in DB["executions"].values():
        plan = DB["plans"].get(e["burn_plan_id"])
        if plan and plan["parcel_id"] == parcel_id and e["phase"] == "CLOSED":
            out.append(e)
    return out


def live_agreement_for_plan(plan_id):
    """The plan's relevant cost-share agreement (non-DENIED/CANCELLED, latest)."""
    cands = [
        a
        for a in DB["agreements"].values()
        if a["burn_plan_id"] == plan_id and a["status"] not in ("DENIED", "CANCELLED")
    ]
    if not cands:
        return None
    return sorted(cands, key=lambda e: e["_seq"])[-1]


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------


def hazard_score(parcel):
    return (
        FUEL_WEIGHT[parcel["fuel_model"]]
        + SLOPE_WEIGHT[parcel["slope_class"]]
        + (WUI_BONUS if parcel["wui_adjacent"] else 0)
        + parcel["drought_index"]
    )


def certification_allows(tier, planned_acres, score):
    if tier == "RXB1":
        return planned_acres <= 40 and score <= 40
    if tier == "RXB2":
        return planned_acres <= 200 and score <= 70
    return True  # RXB3


def required_holding_force(plan, parcel):
    acres = plan["planned_acres"]
    engines_raw = (Decimal(acres) / Decimal(40)) * FUEL_FACTOR[parcel["fuel_model"]]
    required_engines = int(engines_raw.to_integral_value(rounding=ROUND_CEILING)) + (
        2 if parcel["wui_adjacent"] else 0
    )
    crews_base = max(1, math.ceil(acres / 80))
    required_hand_crews = crews_base * (2 if parcel["slope_class"] == "STEEP" else 1)
    required_dozers = 1 if (parcel["fuel_model"] == "TIMBER" and acres > 100) else 0
    required_water_tenders = max(1, acres // 60)
    return {
        "required_engines": required_engines,
        "required_hand_crews": required_hand_crews,
        "required_dozers": required_dozers,
        "required_water_tenders": required_water_tenders,
    }


def in_prescription(plan, obs):
    return (
        obs["wind_mph"] <= plan["max_wind_mph"]
        and plan["min_fuel_moisture_pct"] <= obs["fuel_moisture_pct"] <= plan["max_fuel_moisture_pct"]
        and obs["rh_pct"] >= plan["min_rh_pct"]
        and plan["min_temp_f"] <= obs["temp_f"] <= plan["max_temp_f"]
        and obs["mixing_height_ft"] >= plan["min_mixing_height_ft"]
    )


def observation_fresh(obs):
    return (clock() - obs["observed_at"]) <= timedelta(minutes=FRESHNESS_LIMIT_MINUTES)


def window_conflicts(contractor_id, window_start, window_end, exclude_assignment_id=None):
    """1-day rest buffer rule. window_start inclusive, window_end exclusive (dates)."""
    for a in DB["assignments"].values():
        if a["contractor_id"] != contractor_id or a["status"] not in ("ASSIGNED", "CONFIRMED"):
            continue
        if exclude_assignment_id and a["id"] == exclude_assignment_id:
            continue
        separated = (window_start >= a["window_end"] + timedelta(days=1)) or (
            window_end <= a["window_start"] - timedelta(days=1)
        )
        if not separated:
            return True
    return False


def provisional_estimate(agreement):
    share = SHARE_PCT[agreement["funding_tier"]]
    total = 0
    for line in agreement["treatment_lines"]:
        amount = Decimal(line["acres"]) * Decimal(RATE_CENTS[line["rate_class"]]) * share
        total += round_half_up_cents(amount)
    return total


def effectiveness_score(planned_lines, actual_lines):
    planned_w = sum(
        Decimal(l["acres"]) * CATEGORY_WEIGHT[l["category"]] for l in planned_lines
    )
    actual_w = sum(
        Decimal(l["acres"]) * CATEGORY_WEIGHT[l["category"]] for l in actual_lines
    )
    if planned_w == 0:
        return 0
    return round_half_up_cents(Decimal(100) * actual_w / planned_w)


def effectiveness_factor(score):
    if score >= 80:
        return Decimal("1.00")
    if score >= 50:
        return Decimal("0.75")
    return Decimal("0.00")


def final_reimbursement(agreement, report):
    """Per-line round_half_up(actual_acres * rate * share * factor), then sum.
    Actual acres per line are the report's actual_treatment_lines matched by category."""
    score = report["effectiveness_score"] or 0
    factor = effectiveness_factor(score)
    share = SHARE_PCT[agreement["funding_tier"]]
    actuals_by_category = {}
    for l in report.get("actual_treatment_lines") or []:
        actuals_by_category[l["category"]] = actuals_by_category.get(l["category"], 0) + l["acres"]
    total = 0
    for line in agreement["treatment_lines"]:
        actual_acres = actuals_by_category.get(line["category"], 0)
        amount = (
            Decimal(actual_acres)
            * Decimal(RATE_CENTS[line["rate_class"]])
            * share
            * factor
        )
        total += round_half_up_cents(amount)
    return total


def suppression_allocation(claim, assoc, negligence_found):
    incident = DB["incidents"][claim["incident_id"]]
    escaped = incident["escaped_acres"]
    if negligence_found:
        landowner_share = round_half_up_cents(
            Decimal(escaped) * Decimal(PER_ACRE_CENTS) * NEGLIGENCE_MULTIPLIER
        )
    else:
        landowner_share = min(
            escaped * PER_ACRE_CENTS, assoc["landowner_liability_cap_cents"]
        )
    association_share = claim["total_suppression_cost_cents"] - landowner_share
    return landowner_share, association_share


def fund_payout_with_cap(assoc, association_share_cents):
    """Pinned evaluation order: pre-debit balance B; cap = min(floor(B*0.5),
    single_claim_cap); payout = min(share, cap)."""
    balance_before = assoc["fund_balance_cents"]
    half_floor = int(
        (Decimal(balance_before) * FUND_PAYOUT_FRACTION).to_integral_value(rounding=ROUND_FLOOR)
    )
    cap = min(half_floor, assoc["single_claim_cap_cents"])
    return min(association_share_cents, cap)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def _common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_association(a):
    d = _common(a)
    d.update(
        {
            "name": a["name"],
            "airshed_daily_acres_cap": a["airshed_daily_acres_cap"],
            "single_claim_cap_cents": a["single_claim_cap_cents"],
            "landowner_liability_cap_cents": a["landowner_liability_cap_cents"],
            "fund_balance_cents": a["fund_balance_cents"],
            "fund_posture": fund_posture(a),
        }
    )
    return d


def ser_landowner(l):
    d = _common(l)
    d.update(
        {
            "name": l["name"],
            "contact_email": l["contact_email"],
            "liability_waiver_signed": l["liability_waiver_signed"],
            "standing": landowner_standing(l),
            "outstanding_liability_cents": l["outstanding_liability_cents"],
        }
    )
    return d


def ser_parcel(p):
    d = _common(p)
    d.update(
        {
            "landowner_id": p["landowner_id"],
            "name": p["name"],
            "acreage": p["acreage"],
            "fuel_model": p["fuel_model"],
            "slope_class": p["slope_class"],
            "wui_adjacent": p["wui_adjacent"],
            "airshed_id": p["airshed_id"],
            "drought_index": p["drought_index"],
            "hazard_score": p["hazard_score"],
        }
    )
    return d


def ser_boss(b):
    d = _common(b)
    d.update({"name": b["name"], "certification_tier": b["certification_tier"]})
    return d


def ser_contractor(c):
    d = _common(c)
    d.update(
        {
            "name": c["name"],
            "resource_type": c["resource_type"],
            "capacity_units": c["capacity_units"],
            "personnel_per_unit": c["personnel_per_unit"],
            "day_rate_cents_per_unit": c["day_rate_cents_per_unit"],
            "no_show_count": c["no_show_count"],
            "standing": contractor_standing(c),
            "available_units": contractor_available_units(c),
        }
    )
    return d


def ser_plan(p):
    d = _common(p)
    d.update(
        {
            "parcel_id": p["parcel_id"],
            "author_boss_id": p["author_boss_id"],
            "supersedes_plan_id": p["supersedes_plan_id"],
            "planned_acres": p["planned_acres"],
            "planned_window_start": p["planned_window_start"].isoformat(),
            "planned_window_end": p["planned_window_end"].isoformat(),
            "max_wind_mph": p["max_wind_mph"],
            "min_fuel_moisture_pct": p["min_fuel_moisture_pct"],
            "max_fuel_moisture_pct": p["max_fuel_moisture_pct"],
            "min_rh_pct": p["min_rh_pct"],
            "min_temp_f": p["min_temp_f"],
            "max_temp_f": p["max_temp_f"],
            "min_mixing_height_ft": p["min_mixing_height_ft"],
            "treatment_lines": p["treatment_lines"],
            "approved_by_boss_id": p["approved_by_boss_id"],
            "status": p["status"],
        }
    )
    return d


def ser_permit(p):
    completed, latest = permit_rollups(p)
    d = _common(p)
    d.update(
        {
            "burn_plan_id": p["burn_plan_id"],
            "notifications_required": p["notifications_required"],
            "notifications_completed": completed,
            "notified_completed_at": iso(latest) if latest else None,
            "issued_by_boss_id": p["issued_by_boss_id"],
            "status": p["status"],
        }
    )
    return d


def ser_notification(n):
    d = _common(n)
    d.update(
        {
            "burn_permit_id": n["burn_permit_id"],
            "recipient_name": n["recipient_name"],
            "channel": n["channel"],
            "confirmed_at": iso(n["confirmed_at"]) if n["confirmed_at"] else None,
            "status": n["status"],
        }
    )
    return d


def ser_smoke(s):
    d = _common(s)
    d.update(
        {
            "burn_plan_id": s["burn_plan_id"],
            "airshed_id": s["airshed_id"],
            "requested_burn_date": s["requested_burn_date"].isoformat(),
            "requested_acres": s["requested_acres"],
            "decision_note": s["decision_note"],
            "status": s["status"],
        }
    )
    return d


def ser_contingency(c):
    d = _common(c)
    d.update(
        {
            "burn_plan_id": c["burn_plan_id"],
            "escape_trigger_points": c["escape_trigger_points"],
            "min_holding_personnel": c["min_holding_personnel"],
            "water_supply_description": c["water_supply_description"],
            "evacuation_route_description": c["evacuation_route_description"],
            "status": c["status"],
        }
    )
    return d


def ser_ignition(i):
    d = _common(i)
    d.update(
        {
            "burn_plan_id": i["burn_plan_id"],
            "ignition_method": i["ignition_method"],
            "test_fire_required": i["test_fire_required"],
            "steps": i["steps"],
            "status": i["status"],
        }
    )
    return d


def ser_order(o):
    c = order_confirmed(o)
    d = _common(o)
    d.update(
        {
            "burn_plan_id": o["burn_plan_id"],
            "required_engines": o["required_engines"],
            "required_hand_crews": o["required_hand_crews"],
            "required_dozers": o["required_dozers"],
            "required_water_tenders": o["required_water_tenders"],
            "confirmed_engines": c["ENGINE"],
            "confirmed_hand_crews": c["HAND_CREW"],
            "confirmed_dozers": c["DOZER"],
            "confirmed_water_tenders": c["WATER_TENDER"],
            "status": o["status"],
        }
    )
    return d


def ser_assignment(a):
    d = _common(a)
    d.update(
        {
            "resource_order_id": a["resource_order_id"],
            "contractor_id": a["contractor_id"],
            "units": a["units"],
            "window_start": a["window_start"].isoformat(),
            "window_end": a["window_end"].isoformat(),
            "status": a["status"],
        }
    )
    return d


def ser_execution(e):
    d = _common(e)
    d.update(
        {
            "burn_plan_id": e["burn_plan_id"],
            "scheduled_date": e["scheduled_date"].isoformat(),
            "plan_version_at_schedule": e["plan_version_at_schedule"],
            "acres_blackened": e["acres_blackened"],
            "actual_treatment_lines": e["actual_treatment_lines"],
            "closed_at": iso(e["closed_at"]) if e["closed_at"] else None,
            "phase": e["phase"],
        }
    )
    return d


def ser_observation(o):
    # WeatherObservation carries only id + created_at (no updated_at/version)
    return {
        "id": o["id"],
        "created_at": o["created_at"],
        "burn_execution_id": o["burn_execution_id"],
        "observed_at": iso(o["observed_at"]),
        "wind_mph": o["wind_mph"],
        "fuel_moisture_pct": o["fuel_moisture_pct"],
        "rh_pct": o["rh_pct"],
        "temp_f": o["temp_f"],
        "mixing_height_ft": o["mixing_height_ft"],
        "in_prescription": o["in_prescription"],
    }


def ser_checklist(c):
    # GoNoGoChecklist carries only id + created_at (no updated_at/version)
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "burn_execution_id": c["burn_execution_id"],
        "weather_observation_id": c["weather_observation_id"],
        "answers": c["answers"],
        "verdict": c["verdict"],
        "evaluated_at": iso(c["evaluated_at"]),
    }


def ser_incident(i):
    d = _common(i)
    d.update(
        {
            "burn_execution_id": i["burn_execution_id"],
            "incident_type": i["incident_type"],
            "response_status": i["response_status"],
            "billing_status": i["billing_status"],
            "suppression_cost_cents": i["suppression_cost_cents"],
            "escaped_acres": i["escaped_acres"],
        }
    )
    return d


def ser_report(r):
    d = _common(r)
    d.update(
        {
            "burn_execution_id": r["burn_execution_id"],
            "report_type": r["report_type"],
            "due_at": iso(r["due_at"]),
            "actual_treatment_lines": r["actual_treatment_lines"],
            "effectiveness_score": r["effectiveness_score"],
            "deficiency_reason": r["deficiency_reason"],
            "status": r["status"],
        }
    )
    return d


def ser_agreement(a):
    d = _common(a)
    d.update(
        {
            "landowner_id": a["landowner_id"],
            "burn_plan_id": a["burn_plan_id"],
            "funding_tier": a["funding_tier"],
            "treatment_lines": a["treatment_lines"],
            "provisional_estimate_cents": a["provisional_estimate_cents"],
            "final_reimbursement_cents": a["final_reimbursement_cents"],
            "disbursed_cents": a["disbursed_cents"],
            "approved_at": iso(a["approved_at"]) if a["approved_at"] else None,
            "expires_at": iso(a["expires_at"]) if a["expires_at"] else None,
            "status": a["status"],
        }
    )
    return d


def ser_claim(c):
    d = _common(c)
    d.update(
        {
            "incident_id": c["incident_id"],
            "total_suppression_cost_cents": c["total_suppression_cost_cents"],
            "negligence_found": c["negligence_found"],
            "landowner_share_cents": c["landowner_share_cents"],
            "association_share_cents": c["association_share_cents"],
            "fund_payout_cents": c["fund_payout_cents"],
            "outcome": c["outcome"],
            "adjudicated_at": iso(c["adjudicated_at"]) if c["adjudicated_at"] else None,
            "status": c["status"],
        }
    )
    return d


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------


def suspend_permit_cascade(permit):
    """ISSUED -> SUSPENDED; drags the plan's live agreements down with it."""
    if permit["status"] == "ISSUED":
        permit["status"] = "SUSPENDED"
        touch(permit)
    for ag in DB["agreements"].values():
        if ag["burn_plan_id"] == permit["burn_plan_id"] and ag["status"] in (
            "APPROVED",
            "PARTIALLY_DISBURSED",
        ):
            ag["status"] = "SUSPENDED"
            touch(ag)


def plan_superseded_cascade(prior_plan):
    """prior APPROVED -> SUPERSEDED; its ISSUED permit -> SUSPENDED (+agreements)."""
    prior_plan["status"] = "SUPERSEDED"
    touch(prior_plan)
    permit = plan_permit(prior_plan["id"])
    if permit is not None and permit["status"] == "ISSUED":
        suspend_permit_cascade(permit)


def plan_cancel_cascade(plan):
    for order in plan_orders(plan["id"]):
        if order["status"] in ("DRAFT", "SUBMITTED", "PARTIALLY_FILLED"):
            order["status"] = "CANCELLED"  # version-silent bookkeeping
            for a in DB["assignments"].values():
                if a["resource_order_id"] == order["id"] and a["status"] in (
                    "ASSIGNED",
                    "CONFIRMED",
                ):
                    a["status"] = "RELEASED"
                    touch(a)
    for e in DB["executions"].values():
        if e["burn_plan_id"] == plan["id"] and e["phase"] in ("SCHEDULED", "BRIEFED"):
            e["phase"] = "CANCELLED"
            touch(e)


def wildfire_cascade(incident):
    """execution ESCAPED -> WILDFIRE_RESPONSE -> permit SUSPENDED -> agreements."""
    execution = DB["executions"].get(incident["burn_execution_id"])
    if execution is None or execution["phase"] != "ESCAPED":
        return
    execution["phase"] = "WILDFIRE_RESPONSE"
    touch(execution)
    permit = plan_permit(execution["burn_plan_id"])
    if permit is not None and permit["status"] == "ISSUED":
        suspend_permit_cascade(permit)


# ---------------------------------------------------------------------------
# Clock sweeps (POST /_clock/set_current_utc)
# ---------------------------------------------------------------------------


def run_sweeps():
    today = clock().date()
    now = clock()
    # 1. APPROVED plans whose window passed with no CLOSED/WILDFIRE_RESPONSE execution
    for plan in list(DB["plans"].values()):
        if plan["status"] != "APPROVED":
            continue
        if not (plan["planned_window_end"] < today):
            continue
        execs = [e for e in DB["executions"].values() if e["burn_plan_id"] == plan["id"]]
        if any(e["phase"] in ("CLOSED", "WILDFIRE_RESPONSE") for e in execs):
            continue
        plan["status"] = "EXPIRED"
        touch(plan)
        permit = plan_permit(plan["id"])
        if permit is not None and permit["status"] == "ISSUED":
            permit["status"] = "EXPIRED"
            touch(permit)
    # 2. ISSUED permits whose plan window passed with no non-terminal execution
    for permit in list(DB["permits"].values()):
        if permit["status"] != "ISSUED":
            continue
        plan = DB["plans"].get(permit["burn_plan_id"])
        if plan is None:
            continue
        if not (plan["planned_window_end"] < today):
            continue
        if non_terminal_execution_on_plan(plan["id"]) is not None:
            continue
        permit["status"] = "EXPIRED"
        touch(permit)
    # 3. SCHEDULED executions whose scheduled_date passed
    for e in list(DB["executions"].values()):
        if e["phase"] == "SCHEDULED" and e["scheduled_date"] < today:
            e["phase"] = "LAPSED"
            touch(e)
    # 4. DUE monitoring reports whose due_at passed (version-silent)
    for r in list(DB["reports"].values()):
        if r["status"] == "DUE" and r["due_at"] < now:
            r["status"] = "OVERDUE"
