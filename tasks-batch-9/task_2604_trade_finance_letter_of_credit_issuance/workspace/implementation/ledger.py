"""Pure-aggregation ledgers and the multi-hop cascades they drive.

Every ledger figure in this file is recomputed from the rows that own it -- no
incremental patching anywhere -- which is what keeps the conservation invariant
exact after refusals, cancellations and amendment forks.
"""

from db import add_days, by_created, clock_date, clock_instant, db, touch
import calc

LIVE_SETTLEMENT_STATUSES = ("UNSETTLED", "CLAIM_LODGED", "ACCEPTED", "MATURED")
LIVE_EXAMINATION_STATUSES = (
    "UNDER_EXAMINATION",
    "COMPLYING",
    "DISCREPANT",
    "WAIVER_REQUESTED",
    "PRECLUDED",
)
SETTLED_SETTLEMENT_STATUSES = ("PAID", "NEGOTIATED", "REIMBURSED")
OPEN_EXAMINATION_STATUSES = ("RECEIVED", "UNDER_EXAMINATION", "DISCREPANT", "WAIVER_REQUESTED")

CREDIT_TERMINAL_STATUSES = ("UTILISED", "EXPIRED", "CANCELLED")


# --------------------------------------------------------------------------
# row lookups
# --------------------------------------------------------------------------

def facility_allocations(facility_id):
    return by_created([a for a in db.allocations.values() if a["facility_id"] == facility_id])


def credit_allocations(credit_id):
    return by_created([a for a in db.allocations.values() if a["credit_id"] == credit_id])


def open_allocation_of_credit(credit_id):
    for row in credit_allocations(credit_id):
        if row["status"] == "OPEN":
            return row
    return None


def credits_of_facility(facility_id):
    return by_created([c for c in db.credits.values() if c.get("facility_id") == facility_id])


def presentations_of_credit(credit_id):
    return by_created([p for p in db.presentations.values() if p["credit_id"] == credit_id])


def documents_of_presentation(presentation_id):
    return by_created([d for d in db.documents.values() if d["presentation_id"] == presentation_id])


def discrepancies_of_presentation(presentation_id):
    return by_created([d for d in db.discrepancies.values() if d["presentation_id"] == presentation_id])


def waivers_of_presentation(presentation_id):
    return by_created([w for w in db.waivers.values() if w["presentation_id"] == presentation_id])


def claims_of_presentation(presentation_id):
    return by_created([c for c in db.claims.values() if c["presentation_id"] == presentation_id])


def amendments_of_credit(credit_id):
    return by_created([a for a in db.amendments.values() if a["credit_id"] == credit_id])


def screenings_of_credit(credit_id):
    return by_created([s for s in db.screenings.values() if s["credit_id"] == credit_id])


def newest_document_screening(presentation_id):
    rows = [s for s in db.screenings.values()
            if s.get("presentation_id") == presentation_id and s.get("scope") == "PRESENTED_DOCUMENTS"]
    if not rows:
        return None
    return max(rows, key=lambda s: s["_seq"])


def requirements_of_credit(credit_id):
    return by_created([r for r in db.requirements.values() if r["credit_id"] == credit_id])


# --------------------------------------------------------------------------
# facility_exposure_ledger (+ cascade hops 3 and 4)
# --------------------------------------------------------------------------

def hold_approved_siblings(facility_id, exclude_credit_id=None):
    """Cascade hop 4 (suspension direction): APPROVED -> ON_HOLD, created_at ASC."""
    for credit in credits_of_facility(facility_id):
        if exclude_credit_id is not None and credit["id"] == exclude_credit_id:
            continue
        if credit["status"] == "APPROVED":
            credit["status"] = "ON_HOLD"
            touch(credit)


def release_held_siblings(facility_id):
    """Cascade hop 4 (reinstatement direction): ON_HOLD -> APPROVED, created_at ASC."""
    for credit in credits_of_facility(facility_id):
        if credit["status"] == "ON_HOLD":
            credit["status"] = "APPROVED"
            touch(credit)


def recompute_facility(facility, allow_reactivate=True, exclude_credit_id=None):
    """facility_exposure_ledger, then hops 3 and 4 in that order.

    ``allow_reactivate`` is False when the caller wants to own the
    SUSPENDED -> ACTIVE flip itself (the operational sweep does, so that the
    reactivation is counted exactly once).
    """
    allocated = 0
    for row in facility_allocations(facility["id"]):
        if row["status"] == "OPEN":
            allocated += int(row["allocated_cents"]) + int(row["charge_cents"])

    facility["allocated_cents"] = allocated
    facility["available_cents"] = int(facility["limit_cents"]) - allocated
    facility["restrict_threshold_cents"] = calc.fdiv(
        int(facility["limit_cents"]) * calc.FACILITY_RESTRICT_PCT, 100)

    threshold = facility["restrict_threshold_cents"]

    # hop 3 -- the recomputed allocated_cents itself flips the facility status
    if facility["status"] == "ACTIVE" and allocated >= threshold:
        facility["status"] = "SUSPENDED"
        facility["suspended_reason"] = "RESTRICT_THRESHOLD_BREACH"
        _set_posture(facility)
        touch(facility)
        hold_approved_siblings(facility["id"], exclude_credit_id=exclude_credit_id)
        return facility

    if (allow_reactivate
            and facility["status"] == "SUSPENDED"
            and facility.get("suspended_reason") == "RESTRICT_THRESHOLD_BREACH"
            and allocated < threshold):
        facility["status"] = "ACTIVE"
        facility["suspended_reason"] = None
        _set_posture(facility)
        touch(facility)
        release_held_siblings(facility["id"])
        return facility

    _set_posture(facility)
    touch(facility)
    return facility


def _set_posture(facility):
    if facility["status"] == "CLOSED":
        facility["utilisation_posture"] = "FROZEN"
    elif int(facility["allocated_cents"]) >= int(facility["restrict_threshold_cents"]):
        facility["utilisation_posture"] = "RESTRICTED"
    else:
        facility["utilisation_posture"] = "OPEN"


def collateral_credited_to_open_allocations(facility_id):
    """SUM(collateral_credit_cents) already granted to OPEN allocations.

    The credit granted to one allocation is the gap between the credit's gross
    exposure and the net amount actually reserved on the facility.
    """
    total = 0
    for row in facility_allocations(facility_id):
        if row["status"] != "OPEN":
            continue
        credit = db.credits.get(row["credit_id"])
        if credit is None:
            continue
        total += int(credit.get("gross_exposure_cents") or 0) - int(row["allocated_cents"])
    return total


def release_open_allocation(credit, allow_reactivate=True):
    """FacilityAllocation OPEN -> RELEASED plus the facility recompute cascade."""
    row = open_allocation_of_credit(credit["id"])
    if row is None:
        return None
    row["status"] = "RELEASED"
    row["released_cents"] = int(row["allocated_cents"]) + int(row["charge_cents"])
    row["released_at"] = clock_instant()
    touch(row)
    facility = db.facilities.get(credit.get("facility_id"))
    if facility is not None:
        recompute_facility(facility, allow_reactivate=allow_reactivate)
    return row


# --------------------------------------------------------------------------
# credit_drawable_ledger
# --------------------------------------------------------------------------

def recompute_credit_drawable(credit):
    reserved = 0
    settled = 0
    for presentation in presentations_of_credit(credit["id"]):
        settlement_status = presentation["settlement_status"]
        examination_status = presentation["examination_status"]
        if (settlement_status in LIVE_SETTLEMENT_STATUSES
                and examination_status in LIVE_EXAMINATION_STATUSES):
            reserved += int(presentation["drawn_amount_cents"])
        elif settlement_status in SETTLED_SETTLEMENT_STATUSES:
            settled += int(presentation["drawn_amount_cents"])

    credit["reserved_cents"] = reserved
    credit["drawn_settled_cents"] = settled
    credit["available_cents"] = int(credit.get("max_drawable_cents") or 0) - reserved - settled
    touch(credit)
    return credit


def has_open_presentation(credit_id):
    for presentation in presentations_of_credit(credit_id):
        if presentation["examination_status"] in OPEN_EXAMINATION_STATUSES:
            return True
    return False


def maybe_utilise(credit):
    """ISSUED -> UTILISED when the credit is fully drawn and nothing is live."""
    if credit["status"] != "ISSUED":
        return False
    if int(credit.get("available_cents") or 0) != 0:
        return False
    if has_open_presentation(credit["id"]):
        return False
    credit["status"] = "UTILISED"
    touch(credit)
    return True


def recompute_discrepancy_count(presentation):
    count = 0
    for row in discrepancies_of_presentation(presentation["id"]):
        if row["status"] != "WAIVED":
            count += 1
    presentation["discrepancy_count"] = count
    return count


# --------------------------------------------------------------------------
# confirming line
# --------------------------------------------------------------------------

def recompute_bank_line(bank):
    if bank is None:
        return None
    bank["confirming_line_used_cents"] = calc.confirming_line_peak_occupancy(
        list(db.credits.values()), bank["id"])
    touch(bank)
    return bank


def refresh_bank_score(bank):
    bank["eligibility_score"] = calc.eligibility_score(bank)
    return bank


def declined_bank_ids(credit_id):
    """Banks that already returned DECLINE on this credit are excluded on retry."""
    return set(db.credits.get(credit_id, {}).get("_declined_bank_ids") or [])


# --------------------------------------------------------------------------
# amendment helpers
# --------------------------------------------------------------------------

def supersede_draft_amendments(credit_id):
    for row in amendments_of_credit(credit_id):
        if row["status"] == "DRAFT":
            row["status"] = "SUPERSEDED"
            row["resolved_at"] = clock_instant()
            row["window_end_effective"] = clock_date().isoformat()
            touch(row)


def other_pending_consent(credit_id, amendment_id):
    for row in amendments_of_credit(credit_id):
        if row["id"] == amendment_id:
            continue
        if row["status"] == "PENDING_CONSENT":
            return True
    return False


def apply_change_set(credit, change_set):
    """Apply an accepted change_set and re-derive every dependent credit field."""
    for key, value in change_set.items():
        credit[key] = value
    credit["max_drawable_cents"] = calc.nominal_max_drawable(credit)
    window = calc.presentation_window(credit)
    credit["presentation_deadline_date"] = window["presentation_deadline_date"]
    credit["confirmation_window_end"] = window["confirmation_window_end"]
    return credit


def rebase_allocation(credit, facility, exposure_delta_cents, amendment_fee_cents):
    """Amendment cascade hop 1: release the prior OPEN row and open a fresh one.

    The prior row's charges are retained and the amendment fee is added, so the
    ledger never sees a partial write.
    """
    prior = open_allocation_of_credit(credit["id"])
    retained_charges = int(prior["charge_cents"]) if prior is not None else 0
    if prior is not None:
        prior["status"] = "RELEASED"
        prior["released_cents"] = int(prior["allocated_cents"]) + int(prior["charge_cents"])
        prior["released_at"] = clock_instant()
        touch(prior)

    basis = "AMENDED_INCREASE" if exposure_delta_cents > 0 else "AMENDED_DECREASE"
    charge_cents = retained_charges + int(amendment_fee_cents)
    from db import new_row  # local import keeps db/ledger import order simple
    row = new_row(
        facility_id=facility["id"],
        credit_id=credit["id"],
        allocated_cents=int(credit["committed_allocation_cents"]),
        charge_cents=charge_cents,
        released_cents=0,
        basis=basis,
        status="OPEN",
        released_at=None,
    )
    db.allocations[row["id"]] = row
    # PRD 3.5: `total_charge_cents` is explicitly NOT re-priced by an amendment, and the
    # credit's `chargeable_utilisation_cents` "remains `committed_allocation_cents` plus
    # `total_charge_cents` under the pinned charge order and therefore excludes amendment
    # fees altogether". The fee occupies the facility only via the allocation's charge_cents.
    credit["chargeable_utilisation_cents"] = (
        int(credit["committed_allocation_cents"]) + int(credit["total_charge_cents"])
    )
    recompute_facility(facility)
    return row


def accept_amendment_effects(amendment, credit, facility):
    """Shared side-effect set of both ACCEPTED edges (consent-free and consented)."""
    change_set = amendment["change_set"]
    apply_change_set(credit, change_set)
    exposure = calc.credit_allocation_exposure(credit, facility, "committed_issuance")
    credit["gross_exposure_cents"] = exposure["gross_exposure_cents"]
    credit["committed_allocation_cents"] = exposure["committed_allocation_cents"]
    credit["amendment_seq"] = int(amendment["seq"])
    rebase_allocation(credit, facility, int(amendment["exposure_delta_cents"]),
                      int(amendment["amendment_fee_cents"]))
    recompute_credit_drawable(credit)
    if credit.get("confirming_bank_id"):
        recompute_bank_line(db.banks.get(credit["confirming_bank_id"]))
    touch(credit)
    return credit


def maturity_date_for(credit, received_date_str):
    tenor_days = int(credit.get("tenor_days") or 0)
    if tenor_days == 0:
        return None
    received = calc.parse_date(received_date_str)
    if received is None:
        return None
    return add_days(received, tenor_days).isoformat()
