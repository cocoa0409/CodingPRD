"""Trip accept / void cascades (PRD §3.5, §3.8)."""
import calculations as calc
import clock
import db
from common import new_record, touch
from services import ledger


def accepted_policy_trips(policy_id, exclude_trip_id=None):
    out = []
    for t in db.trips.values():
        if t.get("policy_id") == policy_id and t["status"] == "ACCEPTED":
            if exclude_trip_id is not None and t["id"] == exclude_trip_id:
                continue
            out.append(t)
    return out


def recompute_policy_score(policy):
    """Recompute the operational score + multiplier over ACCEPTED policy trips."""
    plan = db.rate_plans[policy["rate_plan_id"]]
    trips = accepted_policy_trips(policy["id"])
    policy["current_risk_score"] = calc.operational_risk_score(trips, plan)
    policy["current_risk_multiplier"] = calc.risk_multiplier(policy["current_risk_score"])


def accept_cascade(trip):
    """Run the L1->L4 accept cascade (PRD §3.5, §3.8). Mutates in place."""
    # (L1) per-type counts are already maintained as events attach; freeze is a
    # no-op for our representation. Stamp billed_period_index for policy trips.
    if trip.get("policy_id"):
        policy = db.policies[trip["policy_id"]]
        trip["billed_period_index"] = policy["period_index"]

    trip["status"] = "ACCEPTED"
    touch(trip)

    if trip.get("enrollment_id"):
        # (L2) enrollment captured_trip_count += 1
        enr = db.enrollments[trip["enrollment_id"]]
        enr["captured_trip_count"] += 1
        touch(enr)
        return

    # policy-bound trip
    policy = db.policies[trip["policy_id"]]
    driver = db.drivers[policy["driver_id"]]

    # (L2) lifetime_safe_miles += distance; recompute operational score
    driver["lifetime_safe_miles"] += trip["distance_miles"]
    touch(driver)

    recompute_policy_score(policy)
    touch(policy)

    # (L3) snapshot TRIP_ACCEPTED
    ledger.append_snapshot(policy, "TRIP_ACCEPTED")

    # (L3) safe-trip discount
    if calc.safe_trip_earns(trip):
        bank = ledger.bank_for_driver(driver["id"])
        ledger.earn(bank, calc.SAFE_TRIP_DISCOUNT_CENTS, "SAFE_TRIP")
        trip["_safe_trip_earned"] = True

    # (L4) crash FNOL
    if trip["crash_detected"]:
        _auto_fnol(trip, policy)


def _auto_fnol(trip, policy):
    """Auto-create a FNOL claim from a crash trip (PRD §3.8)."""
    reported_severity = trip.get("_crash_severity")
    claim = new_record(
        {
            "policy_id": policy["id"],
            "trip_id": trip["id"],
            "origin": "AUTO_FNOL",
            "reported_severity": reported_severity,
            "reserve_cents": 0,
            "reopen_count": 0,
            "status": "FNOL",
        }
    )
    db.claims[claim["id"]] = claim
    return claim


def void_cascade(trip):
    """Run the C1->C3 compensating void cascade (PRD §3.5). Mutates in place."""
    if trip.get("policy_id"):
        policy = db.policies[trip["policy_id"]]
        driver = db.drivers[policy["driver_id"]]

        # (C1) restore lifetime_safe_miles
        driver["lifetime_safe_miles"] -= trip["distance_miles"]
        touch(driver)

        trip["status"] = "VOIDED"
        touch(trip)

        # (C2) recompute score over remaining accepted trips (trip now VOIDED so
        # it is excluded automatically)
        recompute_policy_score(policy)
        touch(policy)
        ledger.append_snapshot(policy, "TRIP_VOIDED")

        # (C3) reverse a safe-trip grant if this trip earned one
        if trip.get("_safe_trip_earned"):
            bank = ledger.bank_for_driver(driver["id"])
            ledger.reverse(bank, calc.SAFE_TRIP_DISCOUNT_CENTS, "TRIP_VOID_REVERSAL")
    else:
        # An enrollment trip cannot be ACCEPTED then VOIDED in normal flow, but
        # guard defensively: simply mark it voided.
        trip["status"] = "VOIDED"
        touch(trip)
