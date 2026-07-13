"""Cross-aggregate business logic: cascades, penalty recompute, settlement sweep,
FIFO renumbering. Computed operator fields are derived live in `serializers`;
here 'recompute' side effects are realized as a `touch` (version + updated_at
bump) on the affected operator, per PRD 2.4."""
from datetime import datetime, timezone

import calc
import serializers
from store import db, touch, now


# --------------------------------------------------------------------------- #
# Curb release helper
# --------------------------------------------------------------------------- #
def release_curb_for_trip(trip):
    for ca in db.curb_assignments.values():
        if ca["trip_id"] == trip["id"] and ca["status"] == "ACTIVE":
            ca["status"] = "RELEASED"
            touch(ca)


# --------------------------------------------------------------------------- #
# Suspension cascade (PRD 2.6)
# --------------------------------------------------------------------------- #
def _suspend_vehicle(v):
    v["status"] = "SUSPENDED"
    touch(v)
    for p in db.permits.values():
        if p["vehicle_id"] == v["id"] and p["permit_status"] == "ACTIVE":
            p["permit_status"] = "SUSPENDED"
            p["suspended_reason"] = "OPERATOR_SUSPENDED"
            touch(p)
    for t in db.trips.values():
        if t["vehicle_id"] == v["id"] and t["status"] in ("DISPATCHED", "PICKED_UP"):
            t["status"] = "CANCELLED"
            touch(t)
            release_curb_for_trip(t)


def cascade_suspend_operator(op):
    for v in list(db.vehicles.values()):
        if v["operator_id"] == op["id"] and v["status"] == "ACTIVE":
            _suspend_vehicle(v)


def cascade_reinstate_operator(op):
    for v in db.vehicles.values():
        if v["operator_id"] == op["id"] and v["status"] == "SUSPENDED":
            v["status"] = "ACTIVE"
            touch(v)
            for p in db.permits.values():
                if (
                    p["vehicle_id"] == v["id"]
                    and p["permit_status"] == "SUSPENDED"
                    and p.get("suspended_reason") == "OPERATOR_SUSPENDED"
                ):
                    p["permit_status"] = "ACTIVE"
                    p["suspended_reason"] = None
                    touch(p)


# --------------------------------------------------------------------------- #
# Penalty recompute + auto-suspension (PRD 3.1 / 3.7)
# --------------------------------------------------------------------------- #
def recompute_operator_points(op):
    """Penalty totals are derived live; recomputation is itself a mutation."""
    touch(op)


def auto_suspend_if_threshold(op):
    """After ASSESS / UPHOLD drives rolling points to the threshold, an ACTIVE
    operator is suspended on the spot with the same downward cascade."""
    if op["status"] == "ACTIVE" and serializers.compute_rolling(op) >= calc.SUSPENSION_THRESHOLD_POINTS:
        op["status"] = "SUSPENDED"
        op["suspended_reason"] = "PENALTY_THRESHOLD"
        touch(op)
        cascade_suspend_operator(op)


# --------------------------------------------------------------------------- #
# FIFO queue helpers (PRD 3.3 / SCAFFOLD fifo_position_assignment)
# --------------------------------------------------------------------------- #
def waiting_count(lot_id):
    return sum(
        1
        for q in db.queue_entries.values()
        if q["staging_lot_id"] == lot_id and q["status"] == "WAITING"
    )


def renumber_after_removal(lot_id, departed_position):
    for q in db.queue_entries.values():
        if (
            q["staging_lot_id"] == lot_id
            and q["status"] == "WAITING"
            and q["position"] > departed_position
        ):
            q["position"] -= 1
            touch(q)


def leave_waiting(entry, new_status):
    """Move a WAITING entry out of the queue, stamp exit_ts, renumber the tail."""
    departed_position = entry["position"]
    entry["status"] = new_status
    entry["exit_ts"] = now()
    touch(entry)
    renumber_after_removal(entry["staging_lot_id"], departed_position)


# --------------------------------------------------------------------------- #
# Settlement sweep + WAV mandate (PRD 3.8 / SCAFFOLD settlement_statement_totals)
# --------------------------------------------------------------------------- #
def _period_bounds(year, month):
    start = datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    return start, end


def close_settlement(stmt, op):
    start, end = _period_bounds(stmt["period_year"], stmt["period_month"])
    swept = []
    for t in db.trips.values():
        if (
            t["operator_id"] == op["id"]
            and t["status"] == "COMPLETED"
            and t["settlement_statement_id"] is None
            and t["complete_ts"] is not None
            and start <= t["complete_ts"] < end
        ):
            swept.append(t)

    total_trip_count = len(swept)
    wav_trip_count = sum(1 for t in swept if t["is_wheelchair_trip"])
    gross = sum(t["final_fee_cents"] for t in swept)
    admin_fee = calc.round_half_up(gross * calc.ADMIN_RATE)
    wav_credit = calc.WAV_INCENTIVE_CENTS * wav_trip_count
    net_due = gross + admin_fee - wav_credit

    stmt["gross_fees_cents"] = gross
    stmt["admin_fee_cents"] = admin_fee
    stmt["wav_incentive_credit_cents"] = wav_credit
    stmt["net_due_cents"] = net_due
    stmt["total_trip_count"] = total_trip_count
    stmt["wav_trip_count"] = wav_trip_count
    stmt["status"] = "CLOSED"
    stmt["closed_at"] = now()
    touch(stmt)

    for t in swept:
        t["settlement_statement_id"] = stmt["id"]
        touch(t)

    # WAV mandate (PRD 3.8): strict '<' ; empty period cannot breach.
    if total_trip_count > 0 and (wav_trip_count / total_trip_count) < op["wheelchair_pledge_pct"]:
        issue_wav_shortfall(op)


def issue_wav_shortfall(op):
    from store import base_record

    rec = base_record()
    rec.update(
        {
            "operator_id": op["id"],
            "trip_id": None,
            "violation_type": "WAV_SHORTFALL",
            "source": "SYSTEM",
            "penalty_points": calc.PENALTY_POINTS_BY_TYPE["WAV_SHORTFALL"],
            "fine_cents": calc.FINE_CENTS_BY_TYPE["WAV_SHORTFALL"],
            "status": "OPEN",
            "assessed_at": None,
        }
    )
    db.violations[rec["id"]] = rec
    return rec
