"""Derived-field recomputation, slot conservation and the multi-hop cascades."""
from flask import g

import calculations as calc
import clock
import db
from errors import ApiError

POSTURE_BY_MEMBERSHIP = {
    "APPLICANT": "FROZEN",
    "PENDING_AGREEMENT": "FROZEN",
    "ACTIVE": "OPEN",
    "PROBATION": "RESTRICTED",
    "EXITING": "FROZEN",
    "EXITED": "FROZEN",
}

OPEN_REVIEW_STATUSES = ("OPEN", "CAP_SUBMITTED", "CAP_REJECTED")


# --- version bookkeeping ---------------------------------------------------

def _touched():
    if not hasattr(g, "touched_ids"):
        g.touched_ids = set()
    return g.touched_ids


def register_new(row):
    """A row created by this request stays at version 1 no matter how many
    cascade hops also write to it."""
    _touched().add(row["id"])
    return row


def touch(row):
    """Bump version / updated_at at most once per request per row (PRD 2.4)."""
    seen = _touched()
    if row["id"] in seen:
        return row
    seen.add(row["id"])
    row["version"] += 1
    row["updated_at"] = db.now_iso()
    return row


# --- lookups ---------------------------------------------------------------

def provider_or_404(provider_id):
    row = db.providers.get(provider_id)
    if row is None:
        raise ApiError("ERR_PROVIDER_NOT_FOUND", "No provider with id %s." % provider_id)
    return row


def contract_or_404(contract_id):
    row = db.contracts.get(contract_id)
    if row is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND", "No subsidy contract with id %s." % contract_id)
    return row


def enrollment_or_404(enrollment_id):
    row = db.enrollments.get(enrollment_id)
    if row is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND", "No enrollment with id %s." % enrollment_id)
    return row


def substitute_or_404(substitute_id):
    row = db.substitutes.get(substitute_id)
    if row is None:
        raise ApiError("ERR_SUBSTITUTE_NOT_FOUND", "No substitute with id %s." % substitute_id)
    return row


def find_or_404(collection, row_id, error_id, label):
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id, "No %s with id %s." % (label, row_id))
    return row


def provider_children(collection, provider_id):
    return [r for r in collection.values() if r["provider_id"] == provider_id]


def contract_children(collection, contract_id):
    return [r for r in collection.values() if r["contract_id"] == contract_id]


# --- posture --------------------------------------------------------------

def set_membership_status(provider, status):
    """Membership status and its derived posture always move together."""
    provider["membership_status"] = status
    provider["network_posture"] = POSTURE_BY_MEMBERSHIP[status]
    touch(provider)


def check_posture(provider, restricted_blocks):
    """PRD 2.6 / ladder step 11."""
    posture = provider["network_posture"]
    if posture == "FROZEN":
        raise ApiError(
            "ERR_PROVIDER_POSTURE_BLOCKED",
            "The provider's network posture is FROZEN, which blocks every provider-initiated write.",
        )
    if posture == "RESTRICTED" and restricted_blocks:
        raise ApiError(
            "ERR_PROVIDER_POSTURE_BLOCKED",
            "The provider's network posture is RESTRICTED, which blocks this write.",
        )


def check_license_current(provider):
    """PRD 2.8 step 12: license_expires_on on or after the logical clock date."""
    expires = clock.date_of(provider.get("license_expires_on"))
    if expires is None or expires < clock.today():
        raise ApiError("ERR_LICENSE_EXPIRED", "The provider's license is not current.")


# --- derived provider fields ----------------------------------------------

def recompute_open_finding_count(provider):
    """By definition the count of reviews in OPEN / CAP_SUBMITTED / CAP_REJECTED."""
    count = len([
        r for r in db.reviews.values()
        if r["provider_id"] == provider["id"] and r["status"] in OPEN_REVIEW_STATUSES
    ])
    if provider["open_finding_count"] != count:
        provider["open_finding_count"] = count
        touch(provider)
    return count


def recompute_revenue(provider):
    """Refresh the denormalized projected_monthly_revenue_cents."""
    model = calc.revenue_model(provider)
    provider["projected_monthly_revenue_cents"] = model["monthly_revenue_cents"]
    touch(provider)
    return model


def rescore_quality(provider, variant):
    """Write quality_score / quality_tier / quality_variant_applied."""
    if variant == "COACHING_WEIGHTED":
        raw = calc.coaching_weighted_score(provider["id"])
    else:
        raw = calc.compliance_anchored_score(provider["id"])
    if raw is None:
        provider["quality_score"] = 0.00
        provider["quality_tier"] = "UNRATED"
    else:
        score, tier = calc.quality_tail(raw, provider["open_finding_count"])
        provider["quality_score"] = score
        provider["quality_tier"] = tier
    provider["quality_variant_applied"] = variant
    touch(provider)


# --- subsidy slot conservation --------------------------------------------

def active_contract(provider_id):
    """Earliest-created ACTIVE subsidy contract of the provider, or None."""
    rows = [
        c for c in db.contracts.values()
        if c["provider_id"] == provider_id and c["status"] == "ACTIVE"
    ]
    return db.by_created_at(rows)[0] if rows else None


def commit_slot(enrollment, contract):
    contract["committed_slots"] += 1
    contract["available_slots"] -= 1
    touch(contract)
    enrollment["slot_committed"] = True
    enrollment["_slot_contract_id"] = contract["id"]


def release_slot(enrollment):
    """Only ever runs when slot_committed was actually true."""
    if not enrollment.get("slot_committed"):
        return
    contract = db.contracts.get(enrollment.get("_slot_contract_id"))
    if contract is not None:
        contract["committed_slots"] -= 1
        contract["available_slots"] += 1
        touch(contract)
    enrollment["slot_committed"] = False
    enrollment["_slot_contract_id"] = None


# --- quality escalation cascade (4 hops) ----------------------------------

def escalation_cascade(provider):
    # hop 1: provider ACTIVE -> PROBATION, posture RESTRICTED
    set_membership_status(provider, "PROBATION")
    # hop 2: every ACTIVE contract -> SUSPENDED_FOR_QUALITY
    suspended = []
    for contract in db.by_created_at(provider_children(db.contracts, provider["id"])):
        if contract["status"] == "ACTIVE":
            contract["status"] = "SUSPENDED_FOR_QUALITY"
            touch(contract)
            suspended.append(contract)
    # hop 3: every DRAFT / SUBMITTED claim of those contracts -> HELD
    for contract in suspended:
        for claim in db.by_created_at(contract_children(db.claims, contract["id"])):
            if claim["status"] not in ("DRAFT", "SUBMITTED"):
                continue
            claim["held_from_status"] = claim["status"]
            claim["hold_reason"] = "CONTRACT_SUSPENDED_FOR_QUALITY"
            if claim["status"] == "SUBMITTED":
                contract["claimed_amount_cents"] -= claim["provisional_amount_cents"]
                touch(contract)
            claim["status"] = "HELD"
            touch(claim)
    # hop 4: projected revenue
    recompute_revenue(provider)


def reinstatement_cascade(provider):
    # hop 1: provider PROBATION -> ACTIVE, posture OPEN
    set_membership_status(provider, "ACTIVE")
    # hop 2: every SUSPENDED_FOR_QUALITY contract -> ACTIVE
    resumed = []
    for contract in db.by_created_at(provider_children(db.contracts, provider["id"])):
        if contract["status"] == "SUSPENDED_FOR_QUALITY":
            contract["status"] = "ACTIVE"
            touch(contract)
            resumed.append(contract)
    # hop 3: every HELD claim back to held_from_status, with zero authorization drift
    for contract in resumed:
        for claim in db.by_created_at(contract_children(db.claims, contract["id"])):
            if claim["status"] != "HELD":
                continue
            restored = claim["held_from_status"] or "DRAFT"
            claim["status"] = restored
            claim["held_from_status"] = None
            claim["hold_reason"] = None
            if restored == "SUBMITTED":
                contract["claimed_amount_cents"] += claim["provisional_amount_cents"]
                touch(contract)
            touch(claim)
    # hop 4: projected revenue
    recompute_revenue(provider)


# --- network exit cascade -------------------------------------------------

def exit_cascade(provider):
    # hop 1: ENROLLED enrollments -> TRANSITION_PENDING
    for enrollment in db.by_created_at(provider_children(db.enrollments, provider["id"])):
        if enrollment["status"] != "ENROLLED":
            continue
        enrollment["status"] = "TRANSITION_PENDING"
        # hop 2: each one holding a contracted slot releases it
        release_slot(enrollment)
        touch(enrollment)
    # hop 3: projected revenue
    recompute_revenue(provider)


def terminate_contracts(provider):
    for contract in db.by_created_at(provider_children(db.contracts, provider["id"])):
        if contract["status"] in ("ACTIVE", "SUSPENDED_FOR_QUALITY"):
            contract["status"] = "TERMINATED"
            touch(contract)
