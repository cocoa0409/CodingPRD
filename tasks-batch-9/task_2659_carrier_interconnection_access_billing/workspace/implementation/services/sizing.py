"""trunk_sizing_and_blocking and augment_install_window (PRD calculations)."""
from datetime import timedelta
from decimal import Decimal

from constants import (AUGMENT_BUFFER_HOURS, BLOCKING_THRESHOLD_PCT,
                       CCS_PER_TRUNK_ONE_WAY, CCS_PER_TRUNK_TWO_WAY, DS1_TRUNKS,
                       GROWTH_FACTOR, INSTALL_WINDOW_DAYS)
from dec import ceil_div, q2
from store import db, ordered

ZERO2 = Decimal("0.00")
HUNDRED = Decimal("100")


def ccs_per_trunk(direction):
    return CCS_PER_TRUNK_TWO_WAY if direction == "TWO_WAY" else CCS_PER_TRUNK_ONE_WAY


def blocking_pct(offered_calls, blocked_calls):
    if offered_calls == 0:
        return ZERO2
    return q2(Decimal(blocked_calls) * HUNDRED / Decimal(offered_calls))


def sizing_ccs(busy_hour_ccs, forecast_busy_hour_ccs):
    grown = q2(forecast_busy_hour_ccs * GROWTH_FACTOR)
    return busy_hour_ccs if busy_hour_ccs > grown else grown


def required_trunks_for(trunk_group, busy_hour_ccs):
    ccs = sizing_ccs(busy_hour_ccs, trunk_group["forecast_busy_hour_ccs"])
    return ceil_div(ccs, ccs_per_trunk(trunk_group["direction"]))


def sibling_trunk_groups(agreement_id, poi_clli_code):
    return ordered([tg for tg in db.trunk_groups.values()
                    if tg["agreement_id"] == agreement_id
                    and tg["poi_clli_code"] == poi_clli_code])


def poi_provisioned_trunks(agreement_id, poi_clli_code, exclude_id=None):
    total = 0
    for tg in sibling_trunk_groups(agreement_id, poi_clli_code):
        if exclude_id is not None and tg["id"] == exclude_id:
            continue
        if tg["service_status"] in ("PROVISIONED", "IN_SERVICE"):
            total += tg["provisioned_trunks"]
    return total


def poi_committed_trunks(agreement_id, poi_clli_code):
    """Provisioned trunks at the POI plus every trunk already committed by a
    PENDING or ACCEPTED augment order at the same POI."""
    total = poi_provisioned_trunks(agreement_id, poi_clli_code)
    sibling_ids = {tg["id"] for tg in sibling_trunk_groups(agreement_id, poi_clli_code)}
    for order in db.augment_orders.values():
        if order["trunk_group_id"] in sibling_ids and order["status"] in ("PENDING", "ACCEPTED"):
            total += order["requested_additional_trunks"]
    return total


def evaluate_measurement(trunk_group, agreement, offered_calls, blocked_calls,
                         busy_hour_ccs):
    """Returns (blocking_pct, required_trunks, outcome, requested_trunks).

    outcome is one of NO_ACTION, GROOMING_REVIEW, AUGMENT_ORDERED, AUGMENT_BLOCKED.
    """
    pct = blocking_pct(offered_calls, blocked_calls)
    required = required_trunks_for(trunk_group, busy_hour_ccs)

    if pct < BLOCKING_THRESHOLD_PCT:
        return pct, required, "NO_ACTION", 0

    shortfall = required - trunk_group["provisioned_trunks"]
    if shortfall <= 0:
        return pct, required, "GROOMING_REVIEW", 0

    requested = ceil_div(shortfall, DS1_TRUNKS) * DS1_TRUNKS
    committed = poi_committed_trunks(agreement["id"], trunk_group["poi_clli_code"])
    if committed + requested > agreement["poi_facility_capacity_trunks"]:
        return pct, required, "AUGMENT_BLOCKED", 0
    return pct, required, "AUGMENT_ORDERED", requested


def install_window(committed_due_date):
    return (committed_due_date - timedelta(days=INSTALL_WINDOW_DAYS),
            committed_due_date)


def _buffered(start, end):
    delta = timedelta(hours=AUGMENT_BUFFER_HOURS)
    return start - delta, end + delta


def window_collides(order, agreement_id, poi_clli_code, start, end):
    """Buffered windows collide when they touch or overlap (both comparisons
    inclusive)."""
    cand_start, cand_end = _buffered(start, end)
    sibling_ids = {tg["id"] for tg in sibling_trunk_groups(agreement_id, poi_clli_code)}
    for peer in ordered(db.augment_orders):
        if peer["id"] == order["id"]:
            continue
        if peer["status"] != "ACCEPTED":
            continue
        if peer["trunk_group_id"] not in sibling_ids:
            continue
        if peer["install_window_start"] is None or peer["install_window_end"] is None:
            continue
        peer_start, peer_end = _buffered(peer["install_window_start"],
                                         peer["install_window_end"])
        if peer_start <= cand_end and cand_start <= peer_end:
            return True
    return False


def recompute_posture(agreement):
    """BLOCKED wins over CONSTRAINED, which wins over NORMAL."""
    blocked = any(tg["augment_status"] == "AUGMENT_BLOCKED"
                  for tg in db.trunk_groups.values()
                  if tg["agreement_id"] == agreement["id"])
    if blocked:
        posture = "BLOCKED"
    elif agreement["poi_augment_pending_count"] > 0:
        posture = "CONSTRAINED"
    else:
        posture = "NORMAL"
    changed = agreement["capacity_posture"] != posture
    agreement["capacity_posture"] = posture
    return changed
