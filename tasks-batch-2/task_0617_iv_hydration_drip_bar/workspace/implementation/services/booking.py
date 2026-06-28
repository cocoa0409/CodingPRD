"""Shared booking (schedule / md-approve) precondition battery and commit.

PRD §2.6 business-rule precedence for the scheduling & approval endpoints:
  ERR_SCREENING_BLOCKED -> ERR_CONSENT_MISSING -> ERR_SEGREGATION_OF_DUTIES
  -> ERR_NO_STANDING_ORDER -> ERR_SLOT_CONFLICT -> ERR_SUPPLY_UNAVAILABLE
  -> ERR_CREDIT_INSUFFICIENT

(The SoD check in this battery only applies to md-approve: approver !=
screening author. The schedule path has no SoD check at this stage.)
"""
import db
from errors import (
    err,
    ERR_SCREENING_BLOCKED,
    ERR_CONSENT_MISSING,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_NO_STANDING_ORDER,
    ERR_SLOT_CONFLICT,
    ERR_SUPPLY_UNAVAILABLE,
    ERR_CREDIT_INSUFFICIENT,
)
from helpers import get_or_404
import serialize  # noqa: F401  (kept for parity with route modules)
from services import charge, slots, supply
from services import standing_order as so_service


def latest_submitted_screening(appointment_id):
    matches = [s for s in db.intake_screenings.values()
               if s["appointment_id"] == appointment_id and s["status"] == "SUBMITTED"]
    if not matches:
        return None
    matches.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return matches[-1]


def has_signed_consent(appointment_id):
    for c in db.consents.values():
        if c["appointment_id"] == appointment_id and c["status"] == "SIGNED":
            return True
    return False


def resolve_membership(appt):
    if appt["membership_id"] is None:
        return None
    return db.memberships.get(appt["membership_id"])


def perform_booking(appt, *, caller_user_id, is_md_approve):
    """Run the business-rule battery in PRD §2.6 order, then commit the booking
    (pin standing order, reserve supply FEFO, compute charge, decrement
    credits). Mutates appt to SCHEDULED. Does NOT bump version (caller does).

    Preconditions on auth/role/existence/state/OCC are handled by the caller
    BEFORE this function is invoked.
    """
    screening = latest_submitted_screening(appt["id"])

    # 1. ERR_SCREENING_BLOCKED
    if screening is not None and screening["outcome"] == "BLOCKED":
        raise err(ERR_SCREENING_BLOCKED, "Screening outcome is BLOCKED.")

    # 2. ERR_CONSENT_MISSING
    if not has_signed_consent(appt["id"]):
        raise err(ERR_CONSENT_MISSING, "No SIGNED consent exists for the appointment.")

    # 3. ERR_SEGREGATION_OF_DUTIES (md-approve only: approver != screening author)
    if is_md_approve:
        if screening is not None and caller_user_id == screening["author_user_id"]:
            raise err(ERR_SEGREGATION_OF_DUTIES,
                      "MD approver must not be the screening author.")

    # menu item + add-ons
    menu_item = db.menu_items.get(appt["menu_item_id"])
    addon_records = [db.add_ons[aid] for aid in appt["addon_ids"]]

    # 4. ERR_NO_STANDING_ORDER
    pinned_order_id = None
    if menu_item["requires_standing_order"]:
        order = so_service.find_active_for(menu_item["tier"], appt["start_at"])
        if order is None:
            raise err(ERR_NO_STANDING_ORDER,
                      "No ACTIVE standing order in force for the drip tier at start_at.")
        pinned_order_id = order["id"]

    # 5. ERR_SLOT_CONFLICT (lounge capacity + window for LOUNGE appts)
    if appt["location_type"] == "LOUNGE":
        lounge = db.lounges.get(appt["lounge_id"])
        if not slots.lounge_ok(appt, lounge):
            raise err(ERR_SLOT_CONFLICT, "Lounge slot conflicts with capacity or window.")

    # 6. ERR_SUPPLY_UNAVAILABLE (plan reservations via FEFO; nothing applied yet)
    lines = supply.build_lines(menu_item, addon_records)
    chosen_lot_ids = supply.plan_reservations(lines, appt["start_at"])

    # 7. ERR_CREDIT_INSUFFICIENT (membership must be ACTIVE to redeem; never
    #    overdraw). The waterfall is self-limiting, so a violation only arises
    #    when a membership is present but not ACTIVE while credits were expected
    #    — that is treated as a non-redeeming cash visit by §3.11, so no error.
    membership = resolve_membership(appt)
    charge_result = charge.compute(appt, menu_item, addon_records, membership)

    # Defensive guard: redemption must never drive a balance below zero.
    if membership is not None and membership["status"] == "ACTIVE":
        if (membership["drip_credits_remaining"] - charge_result["drip_credit_used"] < 0
                or membership["addon_credits_remaining"] - charge_result["addon_credits_used"] < 0):
            raise err(ERR_CREDIT_INSUFFICIENT, "Credit redemption would overdraw the pool.")

    # ---- COMMIT (all preconditions passed) ----
    supply.apply_reservations(chosen_lot_ids)

    if membership is not None and membership["status"] == "ACTIVE":
        if charge_result["drip_credit_used"] or charge_result["addon_credits_used"]:
            membership["drip_credits_remaining"] -= charge_result["drip_credit_used"]
            membership["addon_credits_remaining"] -= charge_result["addon_credits_used"]
            # Drawing down credits advances the membership version (PRD §2.5):
            # a later MD-approve that pinned the earlier version is then stale.
            db.touch(membership)

    appt["standing_order_id"] = pinned_order_id
    appt["amount_charged_cents"] = charge_result["amount_charged_cents"]
    appt["drip_credit_used"] = charge_result["drip_credit_used"]
    appt["addon_credits_used"] = charge_result["addon_credits_used"]
    appt["status"] = "SCHEDULED"
