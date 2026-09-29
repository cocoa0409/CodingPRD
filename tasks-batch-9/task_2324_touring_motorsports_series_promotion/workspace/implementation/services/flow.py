"""Readiness posture, derived-state reconciliation, cascades and shared guards."""
from db import clock_raw, db, touch
from errors import fail
from services import calc, derive


# --------------------------------------------------------------------------- #
# readiness posture (PRD 2.8)
# --------------------------------------------------------------------------- #
def posture(stop):
    if stop["safety_state"] == "SAFETY_SUSPENDED" or stop["sales_state"] == "CANCELLED":
        return "FROZEN"
    if stop["safety_state"] != "SAFETY_CERTIFIED":
        return "RESTRICTED"
    if derive.stop_competition_segment_count(stop) == 0:
        return "RESTRICTED"
    for entry in derive.live_entries_of_stop(stop["id"]):
        if entry["tech_status"] == "TECH_HELD":
            return "RESTRICTED"
    if derive.stop_marketing_committed(stop) == 0:
        return "RESTRICTED"
    if stop["show_start_utc"] is None:
        return "RESTRICTED"
    return "OPEN"


def void_pending_orders(stop, reason):
    """Move every PENDING order of the stop to VOID, releasing its reserved seats."""
    voided = 0
    for order in derive.orders_of_stop(stop["id"]):
        if order["status"] != "PENDING":
            continue
        order["status"] = "VOID"
        order["void_reason"] = reason
        touch(order)
        tier = db.tiers.get(order["ticket_tier_id"])
        if tier is not None:
            touch(tier)
        voided += 1
    return voided


def apply_posture(stop):
    """Recompute the posture and drive the automatic halt when it leaves OPEN."""
    if stop["sales_state"] == "ON_SALE" and posture(stop) != "OPEN":
        stop["sales_state"] = "SALES_HALTED"
        void_pending_orders(stop, "SALES_HALTED")
        touch(stop)


# --------------------------------------------------------------------------- #
# safety requirement floors (PRD 3.5)
# --------------------------------------------------------------------------- #
def stop_requirement_inputs(stop):
    attendance = derive.stop_expected_attendance(stop)
    live = derive.live_entries_of_stop(stop["id"])
    heavy = any(e["vehicle_weight_lbs"] >= calc.HEAVY_RIG_WEIGHT_LBS for e in live)
    venue = derive.venue_of_stop(stop)
    return attendance, len(live), heavy, venue["floor_type"]


def refresh_plan_requirements(stop, plan=None, bump=True):
    """Recompute the six floors and safety_cost_cents; returns the plan (or None)."""
    if plan is None:
        plan = derive.plan_of_stop(stop["id"])
    if plan is None:
        return None
    attendance, live_count, heavy, floor_type = stop_requirement_inputs(stop)
    floors = calc.required_safety_provisioning(attendance, live_count, heavy, floor_type)
    cost = calc.safety_cost_cents(plan)
    changed = False
    for key, value in floors.items():
        if plan.get(key) != value:
            plan[key] = value
            changed = True
    if plan.get("safety_cost_cents") != cost:
        plan["safety_cost_cents"] = cost
        changed = True
    if changed and bump:
        touch(plan)
    return plan


def plan_shortfall(plan):
    """True when provisioning sits below any recomputed floor."""
    pairs = (
        ("medical_als_staff_count", "required_als_staff_count"),
        ("medical_bls_staff_count", "required_bls_staff_count"),
        ("ambulance_count", "required_ambulance_count"),
        ("emergency_access_lanes", "required_emergency_access_lanes"),
        ("barrier_linear_feet", "required_barrier_linear_feet"),
        ("catch_fence_height_ft", "required_catch_fence_height_ft"),
    )
    for provisioned, required in pairs:
        if plan[provisioned] < plan[required]:
            return True
    return False


def check_provisioning(plan, venue):
    """The four provisioning gates, in ladder order 16-20."""
    if (
        plan["medical_als_staff_count"] < plan["required_als_staff_count"]
        or plan["medical_bls_staff_count"] < plan["required_bls_staff_count"]
    ):
        fail("ERR_MEDICAL_STAFFING_SHORTFALL")
    if plan["ambulance_count"] < plan["required_ambulance_count"]:
        fail("ERR_AMBULANCE_SHORTFALL")
    if (
        plan["catch_fence_height_ft"] < plan["required_catch_fence_height_ft"]
        or plan["catch_fence_height_ft"] > venue["catch_fence_max_height_ft"]
    ):
        fail("ERR_CATCH_FENCE_INSUFFICIENT")
    if plan["emergency_access_lanes"] < plan["required_emergency_access_lanes"]:
        fail("ERR_EMERGENCY_ACCESS_INSUFFICIENT")
    if plan["barrier_linear_feet"] < plan["required_barrier_linear_feet"]:
        fail("ERR_BARRIER_INSUFFICIENT")


# --------------------------------------------------------------------------- #
# shared guards (ladder steps 11 and 13)
# --------------------------------------------------------------------------- #
def ensure_season_open(season):
    if season["status"] == "CLOSED":
        fail("ERR_INVALID_STATE_TRANSITION", "the owning season is CLOSED")


def ensure_stop_writable(stop):
    ensure_season_open(derive.season_of_stop(stop))
    if stop["sales_state"] in ("CANCELLED", "SETTLED"):
        fail(
            "ERR_INVALID_STATE_TRANSITION",
            "the owning tour stop is %s" % stop["sales_state"],
        )


def ensure_not_frozen(stop):
    if posture(stop) == "FROZEN":
        fail("ERR_STOP_FROZEN")


# --------------------------------------------------------------------------- #
# Cascade A — booking withdrawal (PRD 2.9)
# --------------------------------------------------------------------------- #
def cascade_a(booking, reason):
    season = db.seasons[booking["season_id"]]
    stop = derive.stop_of_booking(booking["id"])

    booking["state"] = "WITHDRAWN"
    booking["withdraw_reason"] = reason
    touch(booking)
    # the season's booking_count falls by one
    touch(season)

    if stop is None:
        return

    if stop["sales_state"] in ("SALES_PENDING", "ON_SALE", "SALES_HALTED", "SALES_CLOSED"):
        stop["sales_state"] = "CANCELLED"
    if stop["safety_state"] in ("SAFETY_CERTIFIED", "SAFETY_DRAFT", "SAFETY_REVIEW"):
        stop["safety_state"] = "SAFETY_SUSPENDED"
    stop["cancel_reason"] = reason
    touch(stop)

    for order in derive.orders_of_stop(stop["id"]):
        if order["status"] == "PENDING":
            order["status"] = "VOID"
            order["void_reason"] = "STOP_CANCELLED"
            touch(order)
            tier = db.tiers.get(order["ticket_tier_id"])
            if tier is not None:
                touch(tier)
        elif order["status"] == "PAID":
            order["status"] = "REFUNDED"
            order["refunded_at"] = clock_raw()
            touch(order)
            tier = db.tiers.get(order["ticket_tier_id"])
            if tier is not None:
                touch(tier)

    released_any = False
    for allocation in derive.allocations_of_stop(stop["id"]):
        if allocation["state"] == "COMMITTED":
            allocation["state"] = "RELEASED"
            allocation["released_at"] = clock_raw()
            touch(allocation)
            released_any = True
    if released_any:
        touch(season)

    for entry in derive.entries_of_stop(stop["id"]):
        if entry["logistics_state"] in ("ENTERED", "STAGED"):
            entry["logistics_state"] = "WITHDRAWN"
            entry["staging_bay_index"] = None
            touch(entry)
            competitor = db.competitors.get(entry["competitor_id"])
            if competitor is not None:
                touch(competitor)


# --------------------------------------------------------------------------- #
# Cascade B — a new tier outruns a certified plan (PRD 2.9)
# --------------------------------------------------------------------------- #
def cascade_b(stop, plan):
    plan["state"] = "RETURNED"
    plan["certified_by_user_id"] = None
    plan["return_count"] = plan["return_count"] + 1
    plan["return_reason"] = "AUTO_REQUIREMENT_INCREASE"
    touch(plan)
    stop["safety_state"] = "SAFETY_DRAFT"
    touch(stop)
    apply_posture(stop)


# --------------------------------------------------------------------------- #
# Cascade C — settlement approval bubbles up to the season (PRD 2.9)
# --------------------------------------------------------------------------- #
def cascade_c(settlement, stop):
    season = derive.season_of_stop(stop)
    stop["sales_state"] = "SETTLED"
    touch(stop)
    # settled_stop_count, season_net_cents
    touch(season)
    stops = derive.stops_of_season(season["id"])
    if stops and all(s["sales_state"] in ("SETTLED", "CANCELLED") for s in stops):
        if any(s["sales_state"] == "SETTLED" for s in stops):
            if season["status"] == "PLANNING":
                season["status"] = "CLOSED"
                touch(season)


# --------------------------------------------------------------------------- #
# settlement money assembly
# --------------------------------------------------------------------------- #
def settlement_figures(stop, variant):
    booking = derive.booking_of_stop(stop)
    included_orders = [o for o in derive.orders_of_stop(stop["id"]) if o["status"] == "PAID"]
    activations = [
        a
        for a in derive.activations_of_stop(stop["id"])
        if a["state"] in ("ACTIVATED", "FULFILLED")
    ]
    marketing_committed = derive.stop_marketing_committed(stop)
    plan = derive.plan_of_stop(stop["id"])
    plan_cost = plan["safety_cost_cents"] if plan is not None else 0
    staged = len(
        [e for e in derive.entries_of_stop(stop["id"]) if e["logistics_state"] == "STAGED"]
    )
    return calc.compute_settlement_figures(
        variant,
        included_orders,
        activations,
        marketing_committed,
        plan_cost,
        staged,
        booking,
        marketing_committed,
    )
