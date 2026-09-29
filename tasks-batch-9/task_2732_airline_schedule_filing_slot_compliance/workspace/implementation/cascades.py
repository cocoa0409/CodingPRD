"""Cascade side effects shared by several endpoints."""
import calc
import db
from db import mark, now, store
from util import add_hours, dt_of, fmt_dt


def booked_total(leg):
    return leg["booked_first"] + leg["booked_business"] + leg["booked_economy"]


def raise_obligation(leg, trigger_kind, magnitude, prev_dep=None, prev_arr=None):
    """No row exists unless the leg carries bookings and the magnitude reaches 30."""
    total = booked_total(leg)
    if total <= 0 or magnitude < calc.MIN_MAGNITUDE_MINUTES:
        return None
    tier = calc.obligation_tier(magnitude)
    row = {
        "flight_leg_id": leg["id"],
        "trigger_kind": trigger_kind,
        "change_magnitude_minutes": magnitude,
        "booked_first": leg["booked_first"],
        "booked_business": leg["booked_business"],
        "booked_economy": leg["booked_economy"],
        "booked_total": total,
        "obligation_tier": tier,
        "compensation_cents": calc.compensation_cents(
            tier, leg["booked_first"], leg["booked_business"], leg["booked_economy"]
        ),
        "notify_deadline_utc": fmt_dt(add_hours(now(), calc.NOTIFY_WINDOW_HOURS)),
        "status": "PENDING",
        "dispatched_channel": None,
        "regulator_reference": None,
        "late_dispatch": False,
        "waiver_reason": None,
        # The pre-change times the waiver test compares against; never serialised.
        "_prev_dep_utc": prev_dep if prev_dep is not None else leg["dep_utc"],
        "_prev_arr_utc": prev_arr if prev_arr is not None else leg["arr_utc"],
    }
    return store.insert("notification_obligations", row)


def pending_obligations(leg_id):
    return [
        o for o in store.values("notification_obligations")
        if o["flight_leg_id"] == leg_id and o["status"] == "PENDING"
    ]


def waive(obligation):
    obligation["status"] = "WAIVED"
    obligation["waiver_reason"] = "CHANGE_REVERTED"
    mark(obligation)


def waive_if_reverted(leg):
    """A PENDING obligation is waived once the leg's times are back where they were."""
    for obligation in pending_obligations(leg["id"]):
        if (
            leg["dep_utc"] == obligation["_prev_dep_utc"]
            and leg["arr_utc"] == obligation["_prev_arr_utc"]
        ):
            waive(obligation)


def detach_leg_slots(leg):
    """A retimed or cancelled leg loses both slot backings outright."""
    for field in ("departure_slot_holding_id", "arrival_slot_holding_id"):
        if leg[field] is not None:
            leg[field] = None
    mark(leg)


def detach_holding_from_legs(holding):
    """Legs backed by a series that has left HELD fall to REFILE_REQUIRED."""
    for leg in store.values("flight_legs"):
        if leg["status"] not in ("SLOT_BACKED", "FILED"):
            continue
        touched = False
        for field in ("departure_slot_holding_id", "arrival_slot_holding_id"):
            if leg[field] == holding["id"]:
                leg[field] = None
                touched = True
        if touched:
            leg["status"] = "REFILE_REQUIRED"
            mark(leg)


def cancel_leg(leg, reason, raise_notice=True):
    """Identical effects from every starting status; CANCELLED is terminal."""
    leg["status"] = "CANCELLED"
    leg["cancellation_reason"] = reason
    detach_leg_slots(leg)
    mark(leg)
    if raise_notice:
        raise_obligation(leg, "CANCELLATION", calc.CANCELLATION_EQUIVALENT_MINUTES)


def withdraw_version(version):
    """The cascade shared by a voluntary withdrawal and a carrier suspension."""
    version["filing_status"] = "WITHDRAWN"
    mark(version)
    for leg in store.values("flight_legs"):
        if leg["schedule_version_id"] != version["id"] or leg["status"] == "CANCELLED":
            continue
        cancel_leg(leg, "SCHEDULE_WITHDRAWN", raise_notice=False)
        for obligation in pending_obligations(leg["id"]):
            waive(obligation)


def lose_holding(holding):
    """The audit verdict: the series is taken and every backed leg must refile."""
    holding["holding_status"] = "LOST"
    holding["historic_precedence"] = False
    holding["retains_historic_precedence"] = False
    mark(holding)
    affected = []
    for leg in store.values("flight_legs"):
        if leg["status"] not in ("SLOT_BACKED", "FILED"):
            continue
        if holding["id"] in (leg["departure_slot_holding_id"], leg["arrival_slot_holding_id"]):
            affected.append(leg)
    for leg in affected:
        for field in ("departure_slot_holding_id", "arrival_slot_holding_id"):
            if leg[field] == holding["id"]:
                leg[field] = None
        leg["status"] = "REFILE_REQUIRED"
        mark(leg)
        raise_obligation(leg, "SLOT_LOSS", calc.CANCELLATION_EQUIVALENT_MINUTES)


def release_encumbrance(holding_ids):
    for holding_id in holding_ids:
        holding = store.get("slot_holdings", holding_id)
        if holding is not None and holding["pending_transaction_id"] is not None:
            holding["pending_transaction_id"] = None
            mark(holding)
