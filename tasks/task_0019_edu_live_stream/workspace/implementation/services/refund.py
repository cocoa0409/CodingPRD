"""Refund pricing — provisional and final."""
from db import store
from services.progress import _enrolled_at_unix, recompute_progress
from services.rounding import round_half_up_decimals, round_half_up_int

MATERIALS_KIT_DEDUCTION_CENTS = 5000
SERVICE_PER_LIVE_CLASS_CENTS = 1500
FULL_REFUND_DAYS = 7
FULL_REFUND_PROGRESS = 5.0
MID_REFUND_DAYS = 30
MID_REFUND_PROGRESS = 30.0
LATE_REFUND_PROGRESS = 60.0


def _ratio_for(days_elapsed: int, progress: float) -> float:
    if days_elapsed <= FULL_REFUND_DAYS and progress <= FULL_REFUND_PROGRESS:
        return 1.0
    if days_elapsed <= MID_REFUND_DAYS and progress <= MID_REFUND_PROGRESS:
        return 0.7
    if progress <= LATE_REFUND_PROGRESS:
        return 0.3
    return 0.0


def _attended_count_at(enrollment_id: str, ts_iso: str = None, ts_unix: int = None) -> int:
    """Count Attendance rows for the enrollment whose mark is ATTENDED/LATE,
    filtered (optionally) by created_at <= ts cutoff.
    """
    n = 0
    for a in store.attendances.values():
        if a["enrollment_id"] != enrollment_id:
            continue
        if a["mark"] not in ("ATTENDED", "LATE"):
            continue
        if ts_iso is not None and a["created_at"] > ts_iso:
            continue
        n += 1
    return n


def compute_refund(paid_amount_cents: int, progress: float, days_elapsed: int,
                   attended_count: int, kits: int) -> int:
    ratio = _ratio_for(days_elapsed, progress)
    gross_cents = round_half_up_int(paid_amount_cents * ratio)
    materials = kits * MATERIALS_KIT_DEDUCTION_CENTS
    services = attended_count * SERVICE_PER_LIVE_CLASS_CENTS
    return max(0, gross_cents - materials - services)


def compute_provisional(enrollment, requested_at_unix: int, kits: int):
    """Return (provisional_amount_cents, provisional_progress_percent)."""
    # Recompute progress first to ensure freshness
    recompute_progress(enrollment, run_at_risk=False)
    progress = float(enrollment["progress_percent"])
    progress_snapshot = round_half_up_decimals(progress, 1)
    enrolled_at_ts = _enrolled_at_unix(enrollment)
    days_elapsed = max(0, (requested_at_unix - enrolled_at_ts) // 86400)
    attended = _attended_count_at(enrollment["id"])
    paid = int(enrollment["paid_amount_cents"])
    return compute_refund(paid, progress, days_elapsed, attended, kits), progress_snapshot


def compute_final(enrollment, approval_ts_unix: int, approval_ts_iso: str, kits: int):
    """Return final_amount_cents — re-snapshot at approval time."""
    recompute_progress(enrollment, run_at_risk=False)
    progress = float(enrollment["progress_percent"])
    enrolled_at_ts = _enrolled_at_unix(enrollment)
    days_elapsed = max(0, (approval_ts_unix - enrolled_at_ts) // 86400)
    attended = _attended_count_at(enrollment["id"], ts_iso=approval_ts_iso)
    paid = int(enrollment["paid_amount_cents"])
    return compute_refund(paid, progress, days_elapsed, attended, kits)


def reprice_pending_refunds_for_enrollment(enrollment):
    """Re-price any PENDING refund on this enrollment after a cascade event."""
    for r in store.refund_requests.values():
        if r["enrollment_id"] == enrollment["id"] and r["status"] == "PENDING":
            # use the original requested_at as the time anchor for the provisional
            import datetime
            s = r["requested_at"]
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            try:
                req_ts = int(datetime.datetime.fromisoformat(s).timestamp())
            except ValueError:
                req_ts = store.clock_now_ts
            kits = int(r.get("materials_kit_count", 0))
            new_amount, new_prog = compute_provisional(enrollment, req_ts, kits)
            r["provisional_amount_cents"] = new_amount
            r["provisional_progress_percent"] = new_prog
            from db import bump
            bump(r)
