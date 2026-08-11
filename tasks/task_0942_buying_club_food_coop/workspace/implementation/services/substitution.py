"""Substitution offers: pricing, auto-resolution, approval and decline."""

from decimal import Decimal

from core import clock
from core.constants import SUBSTITUTION_RESPONSE_HOURS, SUBSTITUTION_TOLERANCE_PCT
from core.money import round_half_up
from core.store import DB, ordered, touch
from services import pricing, recompute


def offers_for_line(line):
    return ordered([o for o in DB.substitution_offers.values()
                    if o["order_line_id"] == line["id"]])


def create_offer(line, receipt_line, substitute_item, offered_units, substitute_case_price):
    _, _, _, offered_price = pricing.split_unit_price(
        substitute_case_price, substitute_item["case_pack_units"], line["qty_units"])
    original_price = line["unit_price_cents"]
    tolerance = round_half_up(Decimal(original_price)
                              * (Decimal("1") + Decimal(SUBSTITUTION_TOLERANCE_PCT)))
    offer = DB.insert("SubstitutionOffer", {
        "order_line_id": line["id"],
        "receipt_line_id": receipt_line["id"],
        "substitute_item_id": substitute_item["id"],
        "offered_units": offered_units,
        "original_unit_price_cents": original_price,
        "offered_unit_price_cents": offered_price,
        "within_tolerance": offered_price <= tolerance,
        "respond_by": None,
        "status": "PENDING",
    })
    offer["respond_by"] = clock.render(
        clock.parse(offer["created_at"]) + _hours(SUBSTITUTION_RESPONSE_HOURS))
    return offer


def _hours(count):
    from datetime import timedelta
    return timedelta(hours=count)


def resolve_on_creation(offer, line, status_before_allocation=None):
    """The line's substitution_pref decides; most offers never dwell."""
    pref = line["substitution_pref"]
    if pref == "ANY_SUBSTITUTE" or (pref == "APPROVAL_REQUIRED" and offer["within_tolerance"]):
        offer["status"] = "AUTO_APPROVED"
        touch(offer)
        apply_substitute(offer, line)
        return
    if pref == "NONE":
        offer["status"] = "AUTO_DECLINED"
        touch(offer)
        apply_removal(offer, line)
        return
    # APPROVAL_REQUIRED with an out-of-tolerance price: the offer waits, and the
    # line waits with it.  The member's answer is declared as a move out of
    # CONFIRMED ("Approval ... moves the line `CONFIRMED -> SUBSTITUTED`",
    # §3.6), and `FILLED` is terminal (§3.3), so the allocation's status write
    # cannot stand on a line whose offer is still PENDING: the line is left in
    # the status it held before this allocation pass.  `allocated_units` stays
    # as allocated, because a decline "removes the `offered_units` from the
    # line's `allocated_units`".
    if status_before_allocation is not None and line["status"] != status_before_allocation:
        line["status"] = status_before_allocation
        touch(line)
        _after_line_change(line)


def apply_substitute(offer, line):
    """The line moves CONFIRMED -> SUBSTITUTED at the offered price."""
    line["status"] = "SUBSTITUTED"
    line["unit_price_cents"] = offer["offered_unit_price_cents"]
    line["allocated_units"] = offer["offered_units"]
    line["short_units"] = max(0, line["confirmed_units"] - line["allocated_units"])
    line["line_gross_cents"] = line["allocated_units"] * line["unit_price_cents"]
    touch(line)
    _after_line_change(line)


def apply_removal(offer, line):
    """The offered units leave the line; it becomes SHORT_FILLED or DROPPED."""
    line["allocated_units"] = max(0, line["allocated_units"] - offer["offered_units"])
    line["short_units"] = max(0, line["confirmed_units"] - line["allocated_units"])
    if line["allocated_units"] > 0:
        line["status"] = "SHORT_FILLED"
        line["line_gross_cents"] = line["allocated_units"] * line["unit_price_cents"]
    else:
        line["status"] = "DROPPED"
        line["line_gross_cents"] = 0
    touch(line)
    _after_line_change(line)


def _after_line_change(line):
    order = DB.get("MemberOrder", line["member_order_id"])
    if order is None:
        return
    recompute.recompute_order_money(order)
    drop_run = DB.get("DropRun", order["drop_run_id"])
    if drop_run is not None:
        recompute.recompute_drop_received_subtotal(drop_run)
        route_run = DB.get("RouteRun", drop_run["route_run_id"])
        if route_run is not None:
            recompute.recompute_route_received_subtotal(route_run)
