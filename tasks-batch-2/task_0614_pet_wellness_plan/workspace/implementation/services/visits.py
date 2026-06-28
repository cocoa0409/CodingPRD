"""Visit recording (chronological consumption + à-la-carte) and voiding
(compensation). PRD §3.5, §3.7."""
from db import db, clock_now, parse_iso
from common import touch, stamp_new
from errors import (
    err, ERR_REFERENCE_NOT_FOUND, ERR_PET_NOT_IN_MEMBERSHIP, ERR_CLINIC_CLOSED,
    ERR_PET_NOT_ACTIVE, ERR_NO_ACTIVE_TERM, ERR_VISIT_OUTSIDE_TERM,
    ERR_VISIT_NOT_VOIDABLE, ERR_TERM_NOT_ACTIVE_FOR_VOID,
)
from services.terms import (
    active_term_for_membership, reconcile_term_balance, term_credits,
)
from services.calculations import (
    compute_alacarte_price, CATALOG_DEFAULT_UNIT_CENTS,
)


def record_visit(membership, enrolled_pet_id, clinic_id, service_code):
    """Record a preventive-service visit (PRD §3.5).

    Validation order (PRD §2.9): body FK existence -> pet-in-membership ->
    clinic open -> pet active -> active-term -> visit-in-window.
    """
    # Body FK existence (ERR_REFERENCE_NOT_FOUND).
    pet = db.enrolled_pets.get(enrolled_pet_id)
    if pet is None:
        raise err(ERR_REFERENCE_NOT_FOUND, "Referenced pet does not exist")
    clinic = db.clinics.get(clinic_id)
    if clinic is None:
        raise err(ERR_REFERENCE_NOT_FOUND, "Referenced clinic does not exist")

    # Business rules in pinned order (PRD §2.9).
    if pet["membership_id"] != membership["id"]:
        raise err(ERR_PET_NOT_IN_MEMBERSHIP, "Pet not in this membership")
    if clinic["status"] != "OPEN":
        raise err(ERR_CLINIC_CLOSED, "Clinic is CLOSED")
    if pet["status"] != "ENROLLED":
        raise err(ERR_PET_NOT_ACTIVE, "Pet is not ENROLLED")

    # Resolve the ACTIVE contract term to debit.
    term = active_term_for_membership(membership["id"])
    if term is None:
        raise err(ERR_NO_ACTIVE_TERM, "No ACTIVE contract term to debit")

    # Visit instant must fall inside [starts_at, ends_at) (PRD §3.5).
    now = clock_now()
    starts_at = parse_iso(term["starts_at"])
    ends_at = parse_iso(term["ends_at"])
    if now < starts_at or now >= ends_at:
        raise err(ERR_VISIT_OUTSIDE_TERM, "Visit dated outside the term window")

    # Build the visit record.
    visit = {
        "membership_id": membership["id"],
        "enrolled_pet_id": enrolled_pet_id,
        "clinic_id": clinic_id,
        "contract_term_id": term["id"],
        "service_code": service_code,
        "visited_at": _iso(now),
        "covered_by_credit": False,
        "charged_cents": 0,
        "status": "COMPLETED",
    }

    # Chronological consumption: consume one matching credit unit iff the bucket
    # for this service_code in the active term still has remaining capacity.
    bucket = _bucket_for(term["id"], service_code)
    remaining = 0
    if bucket is not None:
        remaining = bucket["granted_quantity"] - bucket["consumed_quantity"]

    if bucket is not None and remaining > 0:
        bucket["consumed_quantity"] += 1
        if bucket["consumed_quantity"] == bucket["granted_quantity"]:
            bucket["status"] = "EXHAUSTED"
        touch(bucket)
        visit["covered_by_credit"] = True
        visit["charged_cents"] = 0
    else:
        # No capacity -> à-la-carte pricing; debit wallet.
        visit["covered_by_credit"] = False
        base_cents = _alacarte_base(membership["plan_id"], service_code)
        plan = db.plans[membership["plan_id"]]
        charged = compute_alacarte_price(
            service_code, base_cents, pet["weight_kg"],
            plan["alacarte_discount_pct"])
        visit["charged_cents"] = charged
        account = db.member_accounts[membership["member_account_id"]]
        account["wallet_credit_cents"] -= charged
        touch(account)

    stamp_new(visit)
    db.service_visits[visit["id"]] = visit

    # Reconcile term balances after applying the visit.
    reconcile_term_balance(term)
    touch(term)
    return visit


def void_visit(visit):
    """Void a recorded visit; compensating action (PRD §3.5)."""
    if visit["status"] != "COMPLETED":
        raise err(ERR_VISIT_NOT_VOIDABLE, "Visit is not COMPLETED")
    term = db.contract_terms.get(visit["contract_term_id"])
    if term is None or term["status"] != "ACTIVE":
        raise err(ERR_TERM_NOT_ACTIVE_FOR_VOID,
                  "Owning contract term is not ACTIVE")

    visit["status"] = "VOIDED"
    if visit["covered_by_credit"]:
        # Restore one unit to the bucket it consumed; EXHAUSTED -> OPEN if full.
        bucket = _bucket_for(term["id"], visit["service_code"])
        if bucket is not None and bucket["consumed_quantity"] > 0:
            was_full = bucket["consumed_quantity"] == bucket["granted_quantity"]
            bucket["consumed_quantity"] -= 1
            if was_full and bucket["status"] == "EXHAUSTED":
                bucket["status"] = "OPEN"
            touch(bucket)
    else:
        # Refund charged_cents to the member's wallet.
        account = db.member_accounts[term_membership_account(visit)]
        account["wallet_credit_cents"] += visit["charged_cents"]
        touch(account)

    reconcile_term_balance(term)
    touch(term)
    touch(visit)
    return visit


def term_membership_account(visit):
    membership = db.memberships[visit["membership_id"]]
    return membership["member_account_id"]


def _bucket_for(term_id, service_code):
    for c in term_credits(term_id):
        if c["service_code"] == service_code:
            return c
    return None


def _alacarte_base(plan_id, service_code):
    """Base à-la-carte unit value (PRD §3.5): the unit_value_cents of the plan's
    inclusion line for that service code; if the plan has no inclusion line for
    that code, the catalogue default. An ACTIVE line is preferred; a retired
    line still counts as the plan having a line for that code."""
    lines = [ps for ps in db.plan_services.values()
             if ps["plan_id"] == plan_id and ps["service_code"] == service_code]
    if not lines:
        return CATALOG_DEFAULT_UNIT_CENTS[service_code]
    active = [ps for ps in lines if ps["status"] == "ACTIVE"]
    chosen = active[0] if active else lines[0]
    return chosen["unit_value_cents"]


def _iso(dt):
    from db import iso
    return iso(dt)
