"""Cascade side effects: holder suspension/offboarding, fraud strikes,
enrollment activation/cancellation, term lifecycle sweeps.

Version bookkeeping rule: each resource mutated by a request is bumped once
per logical mutation step; post_entry already bumps the account, so field
changes that ride along with a ledger posting are applied without an extra
touch."""

from db import store
from response import now_iso
from services.core import (
    new_row, touch, get_or_create_dining_account, find_dining_account,
    mint_card_number,
)
from services.ledger import post_entry
from services.pricing import (
    activation_pricing, cancellation_credit, MIN_REFUND_CENTS,
    FRAUD_SUSPENSION_THRESHOLD,
)


def revoke_card_grants(card, from_states=("ACTIVE", "SUSPENDED")):
    for gr in store.grants.values():
        if gr["card_id"] == card["id"] and gr["status"] in from_states:
            gr["status"] = "REVOKED"
            touch(gr)


def suspend_card_grants(card):
    for gr in store.grants.values():
        if gr["card_id"] == card["id"] and gr["status"] == "ACTIVE":
            gr["status"] = "SUSPENDED"
            gr["suspended_reason"] = "CARD_FROZEN"
            touch(gr)


def suspension_cascade(holder, exclude_card_id=None):
    """Freeze every OPEN account (HOLDER_SUSPENDED); deactivate the holder's
    non-terminal cards, revoking each such card's non-terminal grants."""
    for acct in store.accounts.values():
        if acct["holder_id"] == holder["id"] and acct["status"] == "OPEN":
            acct["status"] = "FROZEN"
            acct["frozen_reason"] = "HOLDER_SUSPENDED"
            touch(acct)
    for card in store.cards.values():
        if (card["holder_id"] == holder["id"] and card["id"] != exclude_card_id
                and card["lifecycle_status"] in ("ACTIVE", "LOST_FROZEN", "STOLEN_FROZEN")):
            card["lifecycle_status"] = "DEACTIVATED"
            touch(card)
            revoke_card_grants(card)


def add_fraud_strike(holder, exclude_card_id=None):
    """fraud_strike_escalation: the inclusive threshold of 3 suspends."""
    holder["fraud_strike_count"] += 1
    if (holder["fraud_strike_count"] >= FRAUD_SUSPENSION_THRESHOLD
            and holder["status"] == "ACTIVE"):
        holder["status"] = "SUSPENDED"
        holder["fraud_flag"] = True
        suspension_cascade(holder, exclude_card_id=exclude_card_id)
    touch(holder)


def unfreeze_holder_suspended_accounts(holder):
    for acct in store.accounts.values():
        if (acct["holder_id"] == holder["id"] and acct["status"] == "FROZEN"
                and acct.get("frozen_reason") == "HOLDER_SUSPENDED"):
            acct["status"] = "OPEN"
            acct["frozen_reason"] = None
            touch(acct)


def activate_enrollment(enrollment, plan, term):
    """MealPlanEnrollment ASSIGNED -> ACTIVE with enrollment_activation_pricing."""
    charge, grant = activation_pricing(plan, term)
    enrollment["status"] = "ACTIVE"
    enrollment["charge_cents"] = charge
    enrollment["weekly_swipe_allowance"] = plan["weekly_swipe_allowance"]
    enrollment["is_unlimited_swipes"] = plan["is_unlimited_swipes"]
    enrollment["enrolled_week_index"] = term["current_week_index"]
    enrollment["activated_at"] = now_iso()
    touch(enrollment)
    acct = get_or_create_dining_account(enrollment["holder_id"], term["id"])
    if grant > 0:
        post_entry(acct, "ALLOCATION_GRANT", grant,
                   f"Meal plan allocation grant for enrollment {enrollment['id']}")


def cancel_enrollment(enrollment):
    """MealPlanEnrollment -> CANCELLED; ACTIVE cancellation posts the
    proration credit to the enrollment-linked DINING_DOLLARS account."""
    term = store.terms[enrollment["term_id"]]
    plan = store.plans[enrollment["plan_id"]]
    if enrollment["status"] == "ACTIVE":
        credit = cancellation_credit(enrollment, plan, term)
        enrollment["credit_cents"] = credit
        enrollment["status"] = "CANCELLED"
        touch(enrollment)
        if credit > 0:
            acct = get_or_create_dining_account(enrollment["holder_id"], term["id"])
            post_entry(acct, "PRORATION_CREDIT", credit,
                       f"Enrollment cancellation credit for enrollment {enrollment['id']}")
    else:
        enrollment["status"] = "CANCELLED"
        touch(enrollment)
    for cr in store.change_requests.values():
        if (cr["enrollment_id"] == enrollment["id"]
                and cr["status"] in ("SUBMITTED", "APPROVED")):
            cr["status"] = "VOID"
            cr["void_reason"] = "ENROLLMENT_CANCELLED"
            touch(cr)


def offboard_holder_cascade(holder):
    """Withdraw/graduate cascade (PRD 3.2): enrollments cancel with credit,
    accounts -> CLOSE_PENDING, pending change requests VOID."""
    for enr in sorted(
            (e for e in store.enrollments.values() if e["holder_id"] == holder["id"]),
            key=lambda e: (e["created_at"], e["_seq"])):
        if enr["status"] in ("ASSIGNED", "ACTIVE"):
            cancel_enrollment(enr)
    for acct in store.accounts.values():
        if acct["holder_id"] == holder["id"] and acct["status"] in ("OPEN", "FROZEN"):
            acct["status"] = "CLOSE_PENDING"
            acct["frozen_reason"] = None
            touch(acct)


def term_close_cascade(term):
    """PRD 3.7: ACTIVE enrollments -> CLOSED, ASSIGNED -> CANCELLED;
    enrollment-linked DINING_DOLLARS accounts -> CLOSE_PENDING with immediate
    forfeiture-threshold evaluation; pending change requests -> EXPIRED."""
    swept_account_ids = set()
    for enr in sorted(
            (e for e in store.enrollments.values() if e["term_id"] == term["id"]),
            key=lambda e: (e["created_at"], e["_seq"])):
        if enr["status"] == "ACTIVE":
            enr["status"] = "CLOSED"
            touch(enr)
            acct = find_dining_account(enr["holder_id"], term["id"])
            if acct is not None and acct["id"] not in swept_account_ids:
                swept_account_ids.add(acct["id"])
                if acct["status"] in ("OPEN", "FROZEN"):
                    acct["frozen_reason"] = None
                    if acct["balance_cents"] < MIN_REFUND_CENTS:
                        # Enters CLOSE_PENDING and continues straight to FORFEITED.
                        acct["status"] = "FORFEITED"
                        if acct["balance_cents"] > 0:
                            post_entry(acct, "FORFEIT", acct["balance_cents"],
                                       "Forfeiture of residual balance below refund minimum")
                        else:
                            touch(acct)
                    else:
                        acct["status"] = "CLOSE_PENDING"
                        touch(acct)
        elif enr["status"] == "ASSIGNED":
            enr["status"] = "CANCELLED"
            touch(enr)
    term_enrollment_ids = {e["id"] for e in store.enrollments.values()
                           if e["term_id"] == term["id"]}
    for cr in store.change_requests.values():
        if (cr["enrollment_id"] in term_enrollment_ids
                and cr["status"] in ("SUBMITTED", "APPROVED")):
            cr["status"] = "EXPIRED"
            touch(cr)


def term_settle_cascade(term):
    for acct in store.accounts.values():
        if (acct["account_type"] == "DINING_DOLLARS"
                and acct.get("term_id") == term["id"]
                and acct["status"] == "CLOSE_PENDING"):
            acct["status"] = "FORFEITED"
            if acct["balance_cents"] > 0:
                post_entry(acct, "FORFEIT", acct["balance_cents"],
                           "Forfeiture of residual balance at term settlement")
            else:
                touch(acct)


def create_card_for_holder(holder, expires_at_iso, lifecycle, photo_status,
                           is_provisional, replacement_fee_cents=0):
    card = new_row()
    card.update({
        "holder_id": holder["id"],
        "card_number": mint_card_number(),
        "lifecycle_status": lifecycle,
        "photo_status": photo_status,
        "is_provisional": is_provisional,
        "replaced_by_card_id": None,
        "replacement_fee_cents": replacement_fee_cents,
        "stolen_police_report_number": None,
        "expires_at": expires_at_iso,
        "lost_or_stolen_report_count": 0,
    })
    store.cards[card["id"]] = card
    return card
