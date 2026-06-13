"""Monetary / scheduling calculations (scaffold §1.3, PRD §3.3-§3.6).

All money is integer cents; rounding is round_half_up at the cents level with
the per-calculation evaluation order pinned exactly as the contract states.
"""
import db
from util import round_half_up


def active_membership_for_client(client_id):
    """Return the single ACTIVE membership for a client, else None.

    PAST_DUE and CANCELLED memberships are ignored for discount purposes
    (calc appointment_service_quote / retail_line_total).
    """
    for m in db.memberships.values():
        if m["client_id"] == client_id and m["status"] == "ACTIVE":
            return m
    return None


def appointment_service_quote(service, client_id, has_package):
    """calc appointment_service_quote — snapshots (quote, deposit) at booking.

    Package-covered appointment: quote 0, deposit 0 (session prepaid).
    Otherwise: base price reduced by an ACTIVE member's service_discount_pct
    (round half up), then deposit = round_half_up(quote * deposit_pct).
    """
    if has_package:
        return 0, 0

    base = service["base_price_cents"]
    membership = active_membership_for_client(client_id)
    if membership is not None:
        plan = db.membership_plans[membership["plan_id"]]
        disc = plan["service_discount_pct"]
        quote = round_half_up(base * (1 - disc))
    else:
        quote = base

    deposit = round_half_up(quote * service["deposit_pct"])
    return quote, deposit


def package_session_value(package):
    """calc package_session_value — per-session prepaid value.

    Division performed first, quotient rounded half up ONCE.
    """
    return round_half_up(package["price_cents"] / package["session_count"])


def service_revenue_recognized(appointment):
    """calc service_revenue_recognized — never re-priced against current membership.

    Package-redeemed -> package per-session value; else frozen quote snapshot.
    """
    if appointment.get("package_purchase_id"):
        purchase = db.package_purchases[appointment["package_purchase_id"]]
        package = db.packages[purchase["package_id"]]
        return package_session_value(package)
    return appointment["quoted_service_price_cents"]


def stylist_service_split(stylist, revenue):
    """calc stylist_service_earning — (stylist_share, salon_share).

    COMMISSION: stylist = round_half_up(rev * commission_pct); salon = rev - stylist.
    BOOTH_RENT: salon = min(booth_rent_per_appt_cents, rev); stylist = rev - salon.
    """
    if stylist["compensation_model"] == "COMMISSION":
        stylist_share = round_half_up(revenue * stylist["commission_pct"])
        salon_share = revenue - stylist_share
    else:  # BOOTH_RENT
        booth = min(stylist["booth_rent_per_appt_cents"], revenue)
        salon_share = booth
        stylist_share = revenue - booth
    return stylist_share, salon_share


def tip_distribution(salon, serving_stylist, tip_cents):
    """calc tip_distribution — this checkout's serving stylist's tip share.

    DIRECT: full tip to the serving stylist.
    POOLED: floor share to every ACTIVE stylist in the salon (incl. server);
            remainder cents handed out one-by-one to stylists ranked by
            created_at ASC (id never used as tiebreaker). The serving stylist
            gets a remainder cent iff its created_at rank < remainder.
    """
    if salon["tip_split_policy"] == "DIRECT":
        return tip_cents

    # POOLED
    active = [
        s for s in db.stylists.values()
        if s["salon_id"] == salon["id"] and s["status"] == "ACTIVE"
    ]
    n = len(active)
    if n == 0:
        return 0
    base_share = tip_cents // n
    remainder = tip_cents - base_share * n
    # Rank by created_at ASC; _seq is the deterministic intra-millisecond
    # tiebreaker (id is NEVER used).
    ranked = sorted(active, key=lambda s: (s["created_at"], s["_seq"]))
    serving_rank = next(
        i for i, s in enumerate(ranked) if s["id"] == serving_stylist["id"]
    )
    return base_share + (1 if serving_rank < remainder else 0)


def retail_line_total(unit_price_cents, quantity, member_retail_disc_pct):
    """calc retail_line_total — per-line effective unit price, rounded once, then * qty.

    member_retail_disc_pct is None when no ACTIVE membership applies.
    """
    if member_retail_disc_pct is not None:
        eff_unit = round_half_up(unit_price_cents * (1 - member_retail_disc_pct))
    else:
        eff_unit = unit_price_cents
    return eff_unit * quantity


def no_show_forfeit(quoted_price_cents, deposit_held_cents, no_show_fee_pct):
    """Forfeit = min(round_half_up(quote * fee_pct), deposit_held); refund the rest.

    Returns (forfeited_cents, refund_cents). (PRD §3.4)
    """
    fee = round_half_up(quoted_price_cents * no_show_fee_pct)
    forfeited = min(fee, deposit_held_cents)
    refund = deposit_held_cents - forfeited
    return forfeited, refund
