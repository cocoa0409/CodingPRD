"""Rollups, cascades, lazy permit expiry and forecast resolution."""

from decimal import Decimal

import calc
from db import (add_days, db, get_dt, now, set_dt, sort_key, sorted_records,
                touch, whole_days)
from errors import ApiError

LIVE_LEASE_STATUSES = ("DRAFT", "SUBMITTED", "COUNTERED", "REVISED")
TERMINAL_ZONING_STATUSES = ("APPROVED", "DENIED", "DEEMED_GRANTED", "WITHDRAWN")
OPEN_ORDER_STATUSES = ("REQUESTED", "SCHEDULED")


def apply(rec, updates):
    """Write fields, bumping version/updated_at exactly once if anything changed."""
    changed = False
    for key, value in updates.items():
        if rec.get(key) != value:
            rec[key] = value
            changed = True
    if changed:
        touch(rec)
    return changed


# ---------------------------------------------------------------------------
# collection helpers (always in created_at order)
# ---------------------------------------------------------------------------

def _by(collection, field, value):
    return [r for r in sorted_records(collection) if r[field] == value]


def candidates_of_ring(ring_id):
    return _by(db.candidates, "search_ring_id", ring_id)


def leases_of_candidate(candidate_id):
    return _by(db.leases, "candidate_id", candidate_id)


def leases_of_landlord(landlord_id):
    return _by(db.leases, "landlord_id", landlord_id)


def zoning_apps_of_candidate(candidate_id):
    return _by(db.zoning_applications, "candidate_id", candidate_id)


def analyses_of_candidate(candidate_id):
    return _by(db.structural_analyses, "candidate_id", candidate_id)


def designs_of_analysis(analysis_id):
    return _by(db.modification_designs, "structural_analysis_id", analysis_id)


def reviews_of_candidate(candidate_id):
    return _by(db.environmental_reviews, "candidate_id", candidate_id)


def permits_of_candidate(candidate_id):
    return _by(db.construction_permits, "candidate_id", candidate_id)


def orders_of_candidate(candidate_id):
    return _by(db.backhaul_orders, "candidate_id", candidate_id)


def orders_of_provider(provider_id):
    return _by(db.backhaul_orders, "provider_id", provider_id)


def ring_of_candidate(candidate):
    return db.search_rings.get(candidate["search_ring_id"])


def candidate_of_analysis(analysis):
    return db.candidates.get(analysis["candidate_id"])


def executed_lease_of_candidate(candidate):
    for lease in leases_of_candidate(candidate["id"]):
        if lease["status"] == "EXECUTED":
            return lease
    return None


def live_zoning_app_of_candidate(candidate_id):
    """The candidate's application whose status is neither WITHDRAWN nor DENIED."""
    for app in zoning_apps_of_candidate(candidate_id):
        if app["status"] not in ("WITHDRAWN", "DENIED"):
            return app
    return None


# ---------------------------------------------------------------------------
# rollups -- always recomputed from the underlying rows
# ---------------------------------------------------------------------------

def ring_candidate_count(ring_id):
    return sum(1 for c in candidates_of_ring(ring_id)
               if c["acquisition_status"] != "RELINQUISHED")


def ring_committed_capex(ring_id, extra_design_id=None):
    total = Decimal("0")
    for design in sorted_records(db.modification_designs):
        certified = design["status"] == "CERTIFIED" or design["id"] == extra_design_id
        if not certified:
            continue
        analysis = db.structural_analyses.get(design["structural_analysis_id"])
        if analysis is None or analysis["status"] != "COMPLETED":
            continue
        candidate = db.candidates.get(analysis["candidate_id"])
        if candidate is None or candidate["search_ring_id"] != ring_id:
            continue
        if candidate["acquisition_status"] == "RELINQUISHED":
            continue
        if candidate["feasibility_status"] == "DISQUALIFIED":
            continue
        total += calc.dec(design["estimated_cost_usd"])
    return calc.round2(total)


def refresh_ring_rollups(ring, clear_candidate_id=None):
    updates = {
        "candidate_count": ring_candidate_count(ring["id"]),
        "committed_capex_usd": ring_committed_capex(ring["id"]),
    }
    if (clear_candidate_id is not None
            and ring["selected_candidate_id"] == clear_candidate_id
            and ring["status"] == "SITE_SELECTED"):
        updates["selected_candidate_id"] = None
        updates["status"] = "OPEN"
    return apply(ring, updates)


def refresh_landlord_lease_count(landlord, defer_touch=False):
    count = sum(1 for l in leases_of_landlord(landlord["id"]) if l["status"] == "EXECUTED")
    if defer_touch:
        changed = landlord["executed_lease_count"] != count
        landlord["executed_lease_count"] = count
        return changed
    return apply(landlord, {"executed_lease_count": count})


def refresh_provider_crew_days(provider):
    total = 0
    for order in orders_of_provider(provider["id"]):
        if order["status"] in OPEN_ORDER_STATUSES:
            total += int(order["crew_days"] or 0)
    return apply(provider, {"committed_crew_days": total})


def refresh_providers(provider_ids):
    for provider_id in provider_ids:
        provider = db.utility_providers.get(provider_id)
        if provider is not None:
            refresh_provider_crew_days(provider)


# ---------------------------------------------------------------------------
# cascades
# ---------------------------------------------------------------------------

def cancel_open_orders(candidate_id):
    providers = []
    for order in orders_of_candidate(candidate_id):
        if order["status"] in OPEN_ORDER_STATUSES:
            apply(order, {"status": "CANCELLED"})
            if order["provider_id"] not in providers:
                providers.append(order["provider_id"])
    refresh_providers(providers)


def withdraw_live_zoning_apps(candidate_id):
    """Withdraw every non-terminal application; a withdrawal cancels open orders."""
    withdrew = False
    for app in zoning_apps_of_candidate(candidate_id):
        if app["status"] not in TERMINAL_ZONING_STATUSES:
            apply(app, {"status": "WITHDRAWN"})
            withdrew = True
    if withdrew:
        cancel_open_orders(candidate_id)
    return withdrew


def withdraw_open_leases(candidate_id):
    for lease in leases_of_candidate(candidate_id):
        if lease["status"] in LIVE_LEASE_STATUSES:
            apply(lease, {"status": "WITHDRAWN"})


def relinquish_candidate(candidate, extra_updates=None):
    """The acquisition dimension reaches its terminal state."""
    updates = {"acquisition_status": "RELINQUISHED"}
    if extra_updates:
        updates.update(extra_updates)
    apply(candidate, updates)
    withdraw_open_leases(candidate["id"])
    withdraw_live_zoning_apps(candidate["id"])
    ring = ring_of_candidate(candidate)
    if ring is not None:
        refresh_ring_rollups(ring, clear_candidate_id=candidate["id"])


def disqualify_candidate(candidate, extra_updates=None):
    """The feasibility cascade of PRD 2.10."""
    updates = {"feasibility_status": "DISQUALIFIED"}
    if extra_updates:
        updates.update(extra_updates)
    apply(candidate, updates)
    withdraw_live_zoning_apps(candidate["id"])
    ring = ring_of_candidate(candidate)
    if ring is not None:
        refresh_ring_rollups(ring, clear_candidate_id=candidate["id"])


def blacklist_cascade(landlord):
    """Every EXECUTED lease terminates and drags its candidate to RELINQUISHED."""
    for lease in leases_of_landlord(landlord["id"]):
        if lease["status"] == "EXECUTED":
            apply(lease, {"status": "TERMINATED"})
            candidate = db.candidates.get(lease["candidate_id"])
            if candidate is not None:
                relinquish_candidate(candidate)


# ---------------------------------------------------------------------------
# permits: lazy expiry
# ---------------------------------------------------------------------------

def permit_left_issued(permit):
    candidate = db.candidates.get(permit["candidate_id"])
    if candidate is None:
        return
    updates = {"permit_issued": False}
    reverted = candidate["feasibility_status"] == "BUILD_READY"
    if reverted:
        updates["feasibility_status"] = "ENTITLED"
    apply(candidate, updates)
    if reverted:
        ring = ring_of_candidate(candidate)
        if (ring is not None and ring["status"] == "SITE_SELECTED"
                and ring["selected_candidate_id"] == candidate["id"]):
            apply(ring, {"selected_candidate_id": None, "status": "OPEN"})


def refresh_permit(permit):
    if permit["status"] != "ISSUED":
        return permit
    expiry = get_dt(permit, "expiry_date")
    if expiry is not None and now() > expiry:
        apply(permit, {"status": "EXPIRED"})
        permit_left_issued(permit)
    return permit


def refresh_candidate_permits(candidate_id):
    for permit in permits_of_candidate(candidate_id):
        refresh_permit(permit)


def candidate_issued_permits(candidate_id):
    refresh_candidate_permits(candidate_id)
    return [p for p in permits_of_candidate(candidate_id) if p["status"] == "ISSUED"]


# ---------------------------------------------------------------------------
# backhaul helpers
# ---------------------------------------------------------------------------

def has_delivered_power_and_fiber(candidate_id):
    orders = orders_of_candidate(candidate_id)
    power = any(o["status"] == "DELIVERED" and o["order_type"] == "POWER" for o in orders)
    fiber = any(o["status"] == "DELIVERED" and o["order_type"] == "FIBER" for o in orders)
    return power and fiber


# ---------------------------------------------------------------------------
# on-air forecast
# ---------------------------------------------------------------------------

def _driver_sort_key(candidate):
    score = candidate["rf_qualification_score"]
    if score is None:
        return (1, Decimal("0"), sort_key(candidate))
    return (0, -calc.dec(score), sort_key(candidate))


def resolve_driver(ring, plan=None, strict=True):
    selected = ring.get("selected_candidate_id")
    if selected is not None and selected in db.candidates:
        return db.candidates[selected]
    pool = [c for c in candidates_of_ring(ring["id"])
            if c["acquisition_status"] != "RELINQUISHED"
            and c["feasibility_status"] != "DISQUALIFIED"]
    if pool:
        pool.sort(key=_driver_sort_key)
        return pool[0]
    if not strict and plan is not None:
        previous = plan.get("driver_candidate_id")
        if previous is not None and previous in db.candidates:
            return db.candidates[previous]
    raise ApiError("ERR_NO_ELIGIBLE_CANDIDATE", 409)


def compute_forecast(ring, target_dt, plan=None, strict=True):
    driver = resolve_driver(ring, plan=plan, strict=strict)
    refresh_candidate_permits(driver["id"])
    jurisdiction = db.jurisdictions.get(driver["jurisdiction_id"])
    app = live_zoning_app_of_candidate(driver["id"])
    clock = now()

    structural_days = (calc.STRUCTURAL_DAYS
                       if driver["feasibility_status"] in ("UNSCREENED", "RF_QUALIFIED", "STRUCTURAL_HOLD")
                       else 0)
    env_days = 0 if driver["environmental_cleared"] else calc.ENV_DAYS

    if app is not None and app["status"] in ("APPROVED", "DEEMED_GRANTED"):
        zoning_days = 0
    elif app is not None:
        zoning_days = calc.review_days_for(app["application_type"], jurisdiction)
    else:
        zoning_days = int(jurisdiction["conditional_use_review_days"])

    permit_days = 0 if driver["permit_issued"] else calc.PERMIT_DAYS

    orders = orders_of_candidate(driver["id"])
    if has_delivered_power_and_fiber(driver["id"]):
        backhaul_days = 0
    elif not orders:
        backhaul_days = calc.BACKHAUL_DEFAULT_DAYS
    else:
        open_ends = [get_dt(o, "window_end") for o in orders
                     if o["status"] in OPEN_ORDER_STATUSES]
        if open_ends:
            latest = max(open_ends)
            backhaul_days = max(0, whole_days(latest, clock))
        else:
            backhaul_days = 0

    remaining_days = (structural_days + env_days + zoning_days
                      + permit_days + backhaul_days)
    continuance_count = int(app["continuance_count"]) if app is not None else 0

    baseline_date = add_days(clock, remaining_days)
    risk_days = calc.risk_days(remaining_days,
                               jurisdiction["historical_delay_factor"],
                               continuance_count,
                               jurisdiction["hearing_cadence_days"])
    risk_date = add_days(clock, risk_days)
    slip_days = whole_days(risk_date, target_dt)
    score = calc.schedule_risk_score(
        slip_days, continuance_count,
        driver["feasibility_status"] == "STRUCTURAL_HOLD")
    band = calc.risk_band(score)

    return {
        "driver_candidate_id": driver["id"],
        "remaining_days": remaining_days,
        "risk_days": risk_days,
        "baseline_date": baseline_date,
        "risk_date": risk_date,
        "slip_days": slip_days,
        "schedule_risk_score": score,
        "risk_band": band,
    }


def write_forecast(plan, forecast, extra=None):
    """Store the forecast fields on the plan (single version bump with extra)."""
    updates = {
        "schedule_risk_score": forecast["schedule_risk_score"],
        "risk_band": forecast["risk_band"],
        "driver_candidate_id": forecast["driver_candidate_id"],
    }
    if extra:
        updates.update(extra)
    changed = apply(plan, updates)
    for field, value in (("baseline_forecast_date", forecast["baseline_date"]),
                         ("risk_adjusted_forecast_date", forecast["risk_date"])):
        if get_dt(plan, field) != value:
            set_dt(plan, field, value)
            if not changed:
                touch(plan)
                changed = True
    return changed
