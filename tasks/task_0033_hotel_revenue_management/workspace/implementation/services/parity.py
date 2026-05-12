"""Rate-parity check across enabled OTA/GDS channel mappings."""
from db import (
    rate_plans,
    channels,
    channel_rate_plan_mappings,
)
from services.pricing import applicable_nightly_rate_for
from services.audit import emit
from clock import parse_date


def run_parity_check(room_type_id: str, stay_date_iso: str):
    """Check parity across enabled OTA/GDS channels for the (room_type_id, stay_date).
    Emits RATE_PARITY_VIOLATION_DETECTED audit event if max/min ratio exceeds 1%.
    """
    sd = parse_date(stay_date_iso)
    effective_rate = applicable_nightly_rate_for(room_type_id, sd)

    observed = []
    for m in channel_rate_plan_mappings.values():
        if not m.get("enabled", True):
            continue
        rp = rate_plans.get(m["rate_plan_id"])
        if rp is None or rp.get("room_type_id") != room_type_id:
            continue
        ch = channels.get(m["channel_id"])
        if ch is None:
            continue
        if ch.get("channel_type") not in ("OTA", "GDS"):
            continue
        gross = (effective_rate * (10000 + ch["commission_basis_points"])) // 10000
        observed.append(gross)

    if len(observed) < 2:
        return
    mx = max(observed)
    mn = min(observed)
    if mn <= 0:
        return
    # tolerance 100 bp = 1%
    # condition: (mx - mn) / mn > 0.01  ==>  100 * (mx - mn) > mn   (integer math; but use Decimal to be safe)
    if (mx - mn) * 100 > mn:
        emit(
            event_type="RATE_PARITY_VIOLATION_DETECTED",
            actor_role="system",
            actor_id="system",
            subject_entity="RoomType",
            subject_id=room_type_id,
            payload={
                "room_type_id": room_type_id,
                "stay_date": stay_date_iso,
                "max": mx,
                "min": mn,
            },
        )
