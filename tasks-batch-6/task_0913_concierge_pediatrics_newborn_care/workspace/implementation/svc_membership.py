"""Membership enrolment, the sibling ladder and CASCADE A (PRD 3.2 / 3.4)."""
from flask import g

import calc
import constants as C
import svc_booking
import svc_entitlement
import svc_invoice
import svc_line
from store import by_seq, db, new_row, touch


# --------------------------------------------------- (1) sibling ladder ----
def _discount_for(sequence):
    if sequence == 1:
        return C.SIBLING_DISCOUNT_TIER_1_PCT
    if sequence == 2:
        return C.SIBLING_DISCOUNT_TIER_2_PCT
    return C.SIBLING_DISCOUNT_TIER_3_PLUS_PCT


def recompute_ladder(family):
    """Build the occupancy set AFTER the mutation, order by start_date ASC then
    created_at ASC, assign the 1-based sequence, derive the discount, then the
    rate.  A CANCELLED membership keeps its frozen values."""
    members = [
        m
        for m in db.memberships.values()
        if m["family_id"] == family["id"] and m["status"] in C.MEMBERSHIP_OCCUPYING_STATUSES
    ]
    members.sort(key=lambda m: (m["start_date"], m["_seq"]))
    for index, membership in enumerate(members, start=1):
        discount = _discount_for(index)
        plan = db.plans.get(membership["plan_id"])
        base = plan["monthly_rate_cents"] if plan else 0
        rate = calc.discounted_rate_cents(base, discount)
        changed = (
            membership["enrollment_sequence"] != index
            or membership["discount_pct"] != float(discount)
            or membership["monthly_rate_cents"] != rate
        )
        membership["enrollment_sequence"] = index
        membership["discount_pct"] = float(discount)
        membership["monthly_rate_cents"] = rate
        if changed:
            touch(membership, g.touched)


# --------------------------------------- (8) well-visit schedule generation -
def generate_well_visits(membership, child):
    for spec in calc.well_visit_rows_for(child["date_of_birth"], membership["start_date"]):
        new_row(
            db.well_visits,
            {
                "membership_id": membership["id"],
                "child_id": child["id"],
                "milestone_code": spec["milestone_code"],
                "target_date": spec["target_date"],
                "window_open_date": spec["window_open_date"],
                "window_close_date": spec["window_close_date"],
                "scheduled_date": None,
                "completed_date": None,
                "punctuality": None,
                "status": "DUE",
            },
        )


# ------------------------------------------------------- enrolment ---------
def create_membership(child, plan, physician, start_date, family):
    membership = new_row(
        db.memberships,
        {
            "child_id": child["id"],
            "family_id": family["id"],
            "plan_id": plan["id"],
            "physician_id": physician["id"],
            "start_date": start_date,
            "cancellation_effective_date": None,
            "status": "PENDING_ACTIVATION",
            "enrollment_sequence": 1,
            "discount_pct": 0.0,
            "monthly_rate_cents": plan["monthly_rate_cents"],
            "suspension_reason": None,
        },
    )
    recompute_ladder(family)
    svc_entitlement.create_initial_grants(membership, plan)
    generate_well_visits(membership, child)
    svc_invoice.open_cycle_invoice_and_recompute(family, start_date)
    touch(family, g.touched)  # Family.version increments by 1
    return membership


def has_past_due_issued_invoice(family_id):
    today = db.today()
    for invoice in db.invoices.values():
        if invoice["family_id"] != family_id:
            continue
        if invoice["status"] != "ISSUED":
            continue
        if invoice["due_date"] is not None and invoice["due_date"] < today:
            return True
    return False


# ----------------------------------------------------------- CASCADE A -----
def cancel_membership(membership, effective_date):
    family = db.families[membership["family_id"]]

    # ---- hop 0: the direct write -------------------------------------------
    membership["status"] = "CANCELLED"
    membership["cancellation_effective_date"] = effective_date
    touch(membership, g.touched)
    touch(family, g.touched)  # Family.version increments by 1

    # ---- direct fan-out legs (NOT part of the causal chain) -----------------
    recompute_ladder(family)
    svc_invoice.recompute_draft_invoices(family)

    # grants expire BEFORE the held bookings release, so a release can never
    # flip an EXPIRED pool back to OPEN.
    svc_entitlement.expire_grants_of(membership)

    for booking in by_seq(
        [
            b
            for b in db.bookings.values()
            if b["membership_id"] == membership["id"] and b["status"] == "SCHEDULED"
        ]
    ):
        svc_booking.cancel_booking(booking)

    for visit in by_seq(
        [
            w
            for w in db.well_visits.values()
            if w["membership_id"] == membership["id"] and w["status"] in ("DUE", "SCHEDULED")
        ]
    ):
        visit["status"] = "CANCELLED"
        touch(visit, g.touched)

    for form in by_seq(
        [
            f
            for f in db.form_requests.values()
            if f["membership_id"] == membership["id"] and f["status"] == "PENDING"
        ]
    ):
        form["status"] = "BLOCKED"
        form["blocked_reason"] = "MEMBERSHIP_NOT_ACTIVE"
        touch(form, g.touched)

    for encounter in by_seq(
        [
            e
            for e in db.encounters.values()
            if e["membership_id"] == membership["id"] and e["clinical_status"] == "SCHEDULED"
        ]
    ):
        encounter["clinical_status"] = "CANCELLED"
        encounter["billing_status"] = "BILLING_VOID"
        touch(encounter, g.touched)
        svc_line.void_encounter_lines(encounter)

    # ---- hop 1: the panel loosens (weighted_occupancy is computed live) -----
    physician = db.physicians.get(membership["physician_id"])
    # ---- hops 2-4 ----------------------------------------------------------
    promote_from_waitlist(physician)


def promote_from_waitlist(physician):
    """CASCADE A hop 2 -> hop 4.  Exactly one entry is promoted per cancellation;
    earlier entries that do not fit are skipped and stay WAITING.  When nothing
    fits, hops 3 and 4 do not fire at all — an ordinary outcome, not an error."""
    if physician is None:
        return
    _occupancy, available = calc.physician_occupancy(physician)
    available_t = calc.tenths(available)

    entries = by_seq(
        [
            e
            for e in db.waitlist_entries.values()
            if e["physician_id"] == physician["id"] and e["status"] == "WAITING"
        ]
    )
    for entry in entries:
        child = db.children.get(entry["child_id"])
        if child is None:
            continue
        if calc.tenths(calc.child_slot_weight(child)) > available_t:
            continue  # skipped, stays WAITING
        plan = db.plans.get(entry["requested_plan_id"])
        family = db.families.get(child["family_id"])
        if plan is None or family is None:
            return
        # hop 3
        entry["status"] = "PROMOTED"
        new_membership = create_membership(child, plan, physician, db.today(), family)
        entry["promoted_membership_id"] = new_membership["id"]
        touch(entry, g.touched)
        return
