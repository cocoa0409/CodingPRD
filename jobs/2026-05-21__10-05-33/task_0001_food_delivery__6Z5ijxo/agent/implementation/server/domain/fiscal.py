from datetime import datetime, timezone

from ..store import store
from ..repository import touch, now_iso
from ..clock import iso
from .pricing import (
    solo_delivery_fee_cents,
    route_merge_discount_cents,
    commission_cents,
    late_fine_cents,
)
from .rider_metrics import (
    recompute_on_time_rate,
    recompute_acceptance_rate,
    recompute_bonus_tier,
)
from .fines import create_fine
from .route_merge import complete_routegroup_if_done


def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def deliver_cascade(assignment, order):
    """Atomic fiscal cascade on assignment delivery."""
    from ..app import logical_clock
    now = logical_clock.now()

    # 1. Mark delivered
    assignment["status"] = "DELIVERED"
    assignment["delivered_at"] = iso(now)
    order["status"] = "DELIVERED"
    order["actual_delivery_time"] = iso(now)

    promised = _parse_iso(order["promised_delivery_time"])
    delta_seconds = (now - promised).total_seconds()
    minutes_late = max(0, int(delta_seconds // 60)) if delta_seconds > 0 else 0
    order["minutes_late"] = minutes_late

    # 2. Reconcile final delivery fee
    solo_fee = solo_delivery_fee_cents(order["distance_km"], order["is_peak"])
    rg_id = assignment.get("route_group_id")
    final_fee = solo_fee
    if rg_id:
        rg = store.route_groups.get(rg_id)
        if rg and len(rg["assignment_ids"]) >= 2:
            discount = route_merge_discount_cents(solo_fee)
            final_fee = solo_fee - discount
    order["final_delivery_fee_cents"] = final_fee
    assignment["final_delivery_fee_cents"] = final_fee

    # 3. Reconcile final commission
    restaurant = store.restaurants[order["restaurant_id"]]
    rate_override = restaurant.get("commission_rate_override")
    order["final_commission_cents"] = commission_cents(order["subtotal_cents"], rate_override)

    # 4. Payment status to CAPTURED
    order["payment_status"] = "CAPTURED"

    # 5. Late fine
    rider = store.riders[assignment["rider_id"]]
    if minutes_late > 0:
        amt = late_fine_cents(minutes_late, final_fee)
        create_fine(
            subject_type="RIDER",
            subject_id=rider["id"],
            reason="LATE_DELIVERY",
            amount_cents=amt,
            related_order_id=order["id"],
            related_assignment_id=assignment["id"],
        )
    # (create_fine debits wallet and recomputes tier as part of its own cascade)

    # 6. Restaurant pending settlement increment
    restaurant["pending_settlement_cents"] += order["subtotal_cents"] - order["final_commission_cents"]
    touch(restaurant)

    # 7. Rider wallet credit + final tier recompute
    rider["wallet_balance_cents"] = rider.get("wallet_balance_cents", 0) + final_fee
    recompute_on_time_rate(rider)
    recompute_bonus_tier(rider)

    # 8. Route group completion
    complete_routegroup_if_done(rg_id)

    # 9. Rider status reconciliation
    has_live = any(x for x in store.assignments.values()
                   if x["rider_id"] == rider["id"]
                   and x["status"] in ("ACCEPTED", "PICKED_UP"))
    if not has_live and rider["status"] == "ON_DELIVERY":
        rider["status"] = "AVAILABLE"
    touch(rider)

    # Order is mutated once
    touch(order)
