"""Lookups, shared guards and the multi-entity cascades of PRD 2.11."""

import calc
import serialize
import store
from errors import ApiError
from validate import rhu

NON_OPERATIVE = ("TERMINATED", "EXPIRED", "REVERTED")

_NOT_FOUND = {
    "lessee": "ERR_LESSEE_NOT_FOUND",
    "lease": "ERR_LEASE_NOT_FOUND",
    "mortgage": "ERR_MORTGAGE_NOT_FOUND",
    "revaluation": "ERR_REVALUATION_NOT_FOUND",
    "appraisal": "ERR_APPRAISAL_NOT_FOUND",
    "arbitration": "ERR_ARBITRATION_NOT_FOUND",
    "statement": "ERR_STATEMENT_NOT_FOUND",
    "alteration": "ERR_ALTERATION_NOT_FOUND",
    "transfer": "ERR_TRANSFER_NOT_FOUND",
    "notice": "ERR_NOTICE_NOT_FOUND",
    "loss_event": "ERR_LOSS_EVENT_NOT_FOUND",
    "assessment": "ERR_ASSESSMENT_NOT_FOUND",
    "certificate": "ERR_CERTIFICATE_NOT_FOUND",
}


def fetch(kind, identifier):
    """Resolve a row of the given kind or raise that parent's not-found code."""
    collection = store.COLLECTIONS[kind]
    row = collection.get(identifier) if isinstance(identifier, str) else None
    if row is None:
        raise ApiError(_NOT_FOUND[kind])
    return row


def require_operative(lease):
    """Priority 7: six creates are unavailable on a wound-up lease."""
    if lease["lease_status"] in NON_OPERATIVE:
        raise ApiError(
            "ERR_LEASE_NOT_OPERATIVE",
            "The lease is in %s and accepts no new records of this kind."
            % lease["lease_status"],
        )


def invalid_state(message):
    return ApiError("ERR_INVALID_STATE", message)


# ---------------------------------------------------------------------------
# Lease derived quantities.
# ---------------------------------------------------------------------------
def rederive_envelope(lease):
    """gfa_allocated + gfa_unallocated == total_permitted_gfa_sqft, always."""
    lease["gfa_unallocated_sqft"] = (
        lease["total_permitted_gfa_sqft"] - lease["gfa_allocated_sqft"]
    )


def active_subleases(lease_id):
    rows = [
        t for t in store.transfers.values()
        if t["lease_id"] == lease_id
        and t["transfer_type"] == "SUBLEASE"
        and t["status"] == "ACTIVE"
    ]
    return store.sort_rows(rows)


def recompute_sublease_base(lease):
    """Recomputed from the current active member set, never adjusted."""
    lease["percentage_rent_sublease_base_cents"] = calc.sublease_inclusion_base(
        active_subleases(lease["id"])
    )


def lease_mortgages(lease_id):
    rows = [m for m in store.mortgages.values() if m["lease_id"] == lease_id]
    return store.sort_rows(rows)


def mortgages_by_priority(rows):
    return sorted(rows, key=lambda m: (m["priority_rank"], m["created_at"],
                                       m.get("_seq", 0)))


def open_mortgage_principal(lease_id):
    total = 0
    for m in lease_mortgages(lease_id):
        if m["status"] not in ("EXTINGUISHED", "NEW_LEASE_ELECTED"):
            total += m["outstanding_principal_cents"]
    return total


def refresh_submitted_statement_credits(lease):
    """A reset base rent re-prices the offset credit of every open statement."""
    for statement in store.by_lease(store.statements, lease["id"]):
        if statement["status"] == "SUBMITTED":
            statement["base_rent_offset_credit_cents"] = (
                calc.base_rent_offset_credit(
                    lease["current_annual_base_rent_cents"]
                )
            )
            store.touch(statement)


def freeze_rent_axis(lease):
    """The single coupling: tenancy TERMINATED/EXPIRED drives rent to FROZEN."""
    if lease["rent_status"] in ("BASE_ONLY", "REVALUATION_DUE",
                               "REVALUATION_OPEN", "IN_ARBITRATION",
                               "RESET_APPLIED"):
        lease["rent_status"] = "FROZEN"


# ---------------------------------------------------------------------------
# The termination cascade, shared by the default route and the casualty
# TERMINATE election (PRD 3.7 / 3.8).
# ---------------------------------------------------------------------------
def terminate_lease(lease, effective_at):
    lease["lease_status"] = "TERMINATED"
    freeze_rent_axis(lease)

    # Active transfers lapse with the estate; the sublease base is recomputed
    # over whatever remains active, which for an emptied set is zero.
    for transfer in store.by_lease(store.transfers, lease["id"]):
        if transfer["status"] == "ACTIVE":
            transfer["status"] = "TERMINATED_BY_REVERSION"
            store.touch(transfer)
    recompute_sublease_base(lease)

    # Engaged mortgagees acquire the replacement-lease right.
    for mortgage in lease_mortgages(lease["id"]):
        if mortgage["status"] in ("NOTICE_SERVED", "CURING"):
            mortgage["status"] = "NEW_LEASE_ELIGIBLE"
            mortgage["new_lease_election_deadline"] = store.add_days(
                effective_at, calc.NEW_LEASE_ELECTION_DAYS
            )
            store.touch(mortgage)

    for certificate in store.by_lease(store.certificates, lease["id"]):
        if certificate["status"] == "ISSUED":
            certificate["status"] = "REVOKED"
            store.touch(certificate)

    # Provisional amounts already posted to arrears are left standing.
    for statement in store.by_lease(store.statements, lease["id"]):
        if statement["status"] in ("SUBMITTED", "PROVISIONAL_ASSESSED"):
            statement["status"] = "VOID"
            store.touch(statement)

    store.touch(lease)


def expire_lease(lease):
    """Phase-five expiry: the mirror of termination, with no lender window."""
    lease["lease_status"] = "EXPIRED"
    freeze_rent_axis(lease)

    for transfer in store.by_lease(store.transfers, lease["id"]):
        if transfer["status"] == "ACTIVE":
            transfer["status"] = "TERMINATED_BY_REVERSION"
            store.touch(transfer)
    recompute_sublease_base(lease)

    for mortgage in lease_mortgages(lease["id"]):
        if mortgage["status"] in ("RECORDED", "NOTICE_SERVED", "CURING"):
            mortgage["status"] = "EXTINGUISHED"
            store.touch(mortgage)

    store.touch(lease)


def open_assessment(lease):
    """Create the reversion assessment; one per lease at most."""
    record = {
        "lease_id": lease["id"],
        "required_standard_code": lease["reversion_standard_code"],
        "structural_condition_score": None,
        "envelope_condition_score": None,
        "systems_condition_score": None,
        "inspected_by_user_id": None,
        "weighted_score_bps": None,
        "deficiency_bps": None,
        "holdback_cents": None,
        "deposit_released_cents": None,
        "status": "PENDING_INSPECTION",
    }
    store.stamp(record)
    store.assessments[record["id"]] = record
    return record


def assessment_for_lease(lease_id):
    for row in store.assessments.values():
        if row["lease_id"] == lease_id:
            return row
    return None


# ---------------------------------------------------------------------------
# Interval helpers (half-open, PRD 2.9).
# ---------------------------------------------------------------------------
def overlaps(a_start, a_end, b_start, b_end):
    """Half-open intersection: touching endpoints do not overlap."""
    return a_start < b_end and b_start < a_end


def closed_overlaps(a_start, a_end, b_start, b_end):
    """Closed intersection, used only for statement-period inclusion sets."""
    return a_start <= b_end and b_start <= a_end


# ---------------------------------------------------------------------------
# The rent summary computed read (PRD 3.1).
# ---------------------------------------------------------------------------
def rent_summary(lease):
    return {
        "lease_id": lease["id"],
        "current_annual_base_rent_cents": lease["current_annual_base_rent_cents"],
        "percentage_rent_sublease_base_cents":
            lease["percentage_rent_sublease_base_cents"],
        "arrears_balance_cents": lease["arrears_balance_cents"],
        "gfa_allocated_sqft": lease["gfa_allocated_sqft"],
        "gfa_unallocated_sqft": lease["gfa_unallocated_sqft"],
        "deposit_held_cents": lease["deposit_held_cents"],
        "deposit_applied_cents": lease["deposit_applied_cents"],
        "deposit_refunded_cents": lease["deposit_refunded_cents"],
        "active_sublease_count": len(active_subleases(lease["id"])),
        "open_mortgage_principal_cents": open_mortgage_principal(lease["id"]),
    }
