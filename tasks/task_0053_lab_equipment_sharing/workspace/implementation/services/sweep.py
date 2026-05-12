"""Time-gated transitions driven by /_clock/advance.

Order:
  1) MaintenanceWindow SCHEDULED -> IN_PROGRESS
  2) MaintenanceWindow IN_PROGRESS -> AWAITING_ACCEPTANCE
  3) Authorization APPROVED -> EXPIRED
  4) Reservation BOOKED -> NO_SHOW
"""
import db
from clock import now, iso, parse_iso
from services import audit, reservation_ops


def run_due_transitions():
    """Run all due transitions to fixed point in the documented order."""
    # We loop because a maintenance window entering IN_PROGRESS may cancel
    # reservations that would otherwise be eligible for NO_SHOW.
    iterations = 0
    while iterations < 100:
        iterations += 1
        progress = False
        # 1) MaintenanceWindow SCHEDULED -> IN_PROGRESS
        for mw in list(db.maintenance_windows.values()):
            if mw["status"] != "SCHEDULED":
                continue
            start = parse_iso(mw["start_at"])
            if now() >= start:
                eq = db.equipment.get(mw["equipment_id"])
                if eq is None:
                    continue
                if eq["status"] == "AVAILABLE":
                    mw["status"] = "IN_PROGRESS"
                    db.stamp_update(mw)
                    eq["status"] = "MAINTENANCE"
                    db.stamp_update(eq)
                    # Cancel overlapping BOOKED reservations with full refund
                    end = parse_iso(mw["end_at"])
                    overlapping = reservation_ops.find_overlapping_reservations(
                        eq["id"], start, end, statuses=("BOOKED",))
                    for r in overlapping:
                        reservation_ops.cancel_reservation(
                            r, actor_role="system", actor_user_id="system",
                            refund_bps=10000, reason="maintenance_in_progress")
                    progress = True
        # 2) MaintenanceWindow IN_PROGRESS -> AWAITING_ACCEPTANCE
        for mw in list(db.maintenance_windows.values()):
            if mw["status"] != "IN_PROGRESS":
                continue
            end = parse_iso(mw["end_at"])
            if now() >= end:
                mw["status"] = "AWAITING_ACCEPTANCE"
                db.stamp_update(mw)
                progress = True
        # 3) Authorization APPROVED -> EXPIRED
        for auth in list(db.authorizations.values()):
            if auth["status"] != "APPROVED":
                continue
            exp = auth.get("expires_at")
            if exp is None:
                continue
            if now() >= parse_iso(exp):
                prev = auth["status"]
                auth["status"] = "EXPIRED"
                db.stamp_update(auth)
                # Cancel future-dated BOOKED reservations bound to this auth
                for r in list(db.reservations.values()):
                    if r.get("authorization_id") != auth["id"]:
                        continue
                    if r["status"] != "BOOKED":
                        continue
                    if parse_iso(r["start_at"]) <= now():
                        # not future-dated; skip
                        continue
                    reservation_ops.cancel_reservation(
                        r, actor_role="system", actor_user_id="system",
                        refund_bps=10000, reason="authorization_expired")
                audit.record(
                    subject_type="AUTHORIZATION",
                    subject_id=auth["id"],
                    actor_role="system",
                    actor_user_id="system",
                    action="EXPIRE",
                    from_state=prev,
                    to_state="EXPIRED",
                    payload_json={"reason": "ttl_elapsed"},
                )
                progress = True
        # 4) Reservation BOOKED -> NO_SHOW
        for r in list(db.reservations.values()):
            if r["status"] != "BOOKED":
                continue
            end = parse_iso(r["end_at"])
            if now() >= end:
                # Check there's no UsageLog with check_in_at
                has_check_in = any(
                    u["reservation_id"] == r["id"] and u.get("check_in_at")
                    for u in db.usage_logs.values()
                )
                if has_check_in:
                    continue
                prev = r["status"]
                r["status"] = "NO_SHOW"
                db.stamp_update(r)
                audit.record(
                    subject_type="RESERVATION",
                    subject_id=r["id"],
                    actor_role="system",
                    actor_user_id="system",
                    action="EXPIRE",
                    from_state=prev,
                    to_state="NO_SHOW",
                    payload_json={"reason": "no_show_sweep"},
                )
                progress = True
        if not progress:
            break
