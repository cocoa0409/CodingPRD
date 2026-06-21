"""Order pricing engine (calc: order_total, PRD §3.5 provisional / §3.6 final).

Two variants:
  provisional — written to quoted_total_cents on DRAFT. MEMBER tickets priced at
                plan.member_admission_cents even if membership not yet ACTIVE.
  final       — written to final_total_cents + per-ticket price_cents at CONFIRMED.

Per-ticket: base (by ticket_type) + surcharge (special exhibit, per-ticket).
round_half_up is applied at each per-component multiplication, NEVER on the sum.
Per-ticket prices are whole-cent before summing; admission subtotal is the plain
sum of already-rounded per-ticket prices; total = subtotal + donation_cents.
"""
import db
from services.money import discounted_cents


def _ticket_base_cents(ticket, order, plan, slot):
    ttype = ticket["ticket_type"]
    if ttype == "MEMBER":
        # plan must exist when membership_id set; provisional optimistically uses it.
        return plan["member_admission_cents"] if plan is not None else 0
    if ttype == "NON_MEMBER":
        return slot["non_member_admission_cents"]
    if ttype == "GUEST":
        return 0
    if ttype == "RECIPROCAL":
        partner = db.reciprocal_partners.get(ticket.get("reciprocal_partner_id"))
        if partner is None:
            # Unresolvable partner -> treated as 0 base in a provisional quote;
            # confirm-time eligibility check rejects this case before pricing.
            return 0
        if partner["benefit_type"] == "FREE":
            return 0
        # DISCOUNT
        return discounted_cents(slot["non_member_admission_cents"], partner["discount_pct"])
    return 0


def _ticket_surcharge_cents(ticket, order, plan, exhibit):
    if order.get("exhibit_session_id") is None or exhibit is None:
        return 0
    ttype = ticket["ticket_type"]
    if ttype == "MEMBER":
        if plan is not None and plan.get("exhibit_surcharge_waived"):
            return 0
        return discounted_cents(
            exhibit["surcharge_cents"], exhibit.get("member_surcharge_discount_pct", 0)
        )
    # GUEST / NON_MEMBER / RECIPROCAL pay the full surcharge.
    return exhibit["surcharge_cents"]


def _resolve_context(order):
    slot = db.timed_entry_slots.get(order["slot_id"])
    plan = None
    if order.get("membership_id"):
        membership = db.memberships.get(order["membership_id"])
        if membership is not None:
            plan = db.membership_plans.get(membership["plan_id"])
    exhibit = None
    if order.get("exhibit_session_id"):
        session = db.exhibit_sessions.get(order["exhibit_session_id"])
        if session is not None:
            exhibit = db.special_exhibits.get(session["exhibit_id"])
    return slot, plan, exhibit


def _order_tickets(order):
    """Tickets on the order that are not VOIDED, sorted by creation order."""
    tickets = [
        t for t in db.admission_tickets.values()
        if t["order_id"] == order["id"] and t.get("state") != "VOIDED"
    ]
    tickets.sort(key=lambda t: (t.get("created_at"), t.get("_seq", 0)))
    return tickets


def compute_provisional(order):
    """Recompute quoted_total_cents from current published rates. Returns total."""
    slot, plan, exhibit = _resolve_context(order)
    subtotal = 0
    for t in _order_tickets(order):
        base = _ticket_base_cents(t, order, plan, slot)
        sur = _ticket_surcharge_cents(t, order, plan, exhibit)
        subtotal += base + sur
    return subtotal + order.get("donation_cents", 0)


def compute_final(order):
    """Lock per-ticket price_cents and return final_total_cents.

    Caller must have already passed all confirm-time guards (membership ACTIVE,
    eligibility, etc.). Mutates each ticket's price_cents.
    """
    slot, plan, exhibit = _resolve_context(order)
    subtotal = 0
    for t in _order_tickets(order):
        base = _ticket_base_cents(t, order, plan, slot)
        sur = _ticket_surcharge_cents(t, order, plan, exhibit)
        price = base + sur
        t["price_cents"] = price
        db.touch(t)
        subtotal += price
    return subtotal + order.get("donation_cents", 0)
