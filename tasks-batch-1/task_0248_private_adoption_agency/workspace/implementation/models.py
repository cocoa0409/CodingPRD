"""Entity factories, serialization, and derived-field recomputation.

The AdoptionCase is the hub. Its phase / escrow_balance_cents /
reimbursable_expense_cents / interstate are all computed projections over child
entities; they are reconciled immediately on any feeding mutation and on read.
"""
import db
from response import now_iso_ms
from timeutil import format_iso, parse_iso

# --- Calculation constants (scaffold §1.3) ---
HOME_STUDY_VALIDITY_DAYS = 365
MIN_HOURS_AFTER_BIRTH = 72
CALENDAR_WINDOW_DAYS = 10
BUSINESS_WINDOW_DAYS = 5
COUNSELING_BUFFER_MINUTES = 60
REQUIRED_VISITS_INSTATE = 3
REQUIRED_VISITS_INTERSTATE = 6
LOW_BAND_CENTS = 4000000
HIGH_BAND_CENTS = 12000000
REIMBURSABLE_CAP_CENTS = 1500000


# --------------------------------------------------------------------------
# Common system fields
# --------------------------------------------------------------------------
def base_fields(with_version=True):
    """Create the common system-managed fields. EscrowTransaction passes
    with_version=False because it is an immutable ledger row (id + created_at only).
    """
    ts = now_iso_ms()
    rec = {
        "id": db.new_id(),
        "created_at": ts,
        "_seq": db.next_seq(),
    }
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version on a mutation."""
    rec["updated_at"] = now_iso_ms()
    rec["version"] = rec.get("version", 1) + 1


# --------------------------------------------------------------------------
# Serialization — strip internal fields (those prefixed with '_')
# --------------------------------------------------------------------------
def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def serialize_agency(a):
    return {
        "id": a["id"],
        "name": a["name"],
        "licensed_state": a["licensed_state"],
        "fee_schedule_cents": a["fee_schedule_cents"],
        "current_utc": format_iso(a["_current_utc"]),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_case(c):
    reconcile_case(c)
    return {
        "id": c["id"],
        "agency_id": c["agency_id"],
        "case_label": c["case_label"],
        "child_state": c["child_state"],
        "family_state": c["family_state"],
        "phase": c["phase"],
        "escrow_balance_cents": c["escrow_balance_cents"],
        "reimbursable_expense_cents": c["reimbursable_expense_cents"],
        "interstate": c["interstate"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_family(f):
    return _public(f)


def serialize_home_study(h):
    return {
        "id": h["id"],
        "case_id": h["case_id"],
        "family_id": h["family_id"],
        "authoring_caseworker_id": h["authoring_caseworker_id"],
        "approving_supervisor_id": h["approving_supervisor_id"],
        "completed_at": format_iso(h["_completed_at"]),
        "expires_at": format_iso(h["_expires_at"]),
        "revision_count": h["revision_count"],
        "status": h["status"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
    }


def serialize_birth_parent(b):
    return _public(b)


def serialize_counseling_session(s):
    return {
        "id": s["id"],
        "birth_parent_id": s["birth_parent_id"],
        "case_id": s["case_id"],
        "counselor_id": s["counselor_id"],
        "start_at": format_iso(s["_start_at"]),
        "end_at": format_iso(s["_end_at"]),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_match(m):
    return _public(m)


def serialize_consent(c):
    return {
        "id": c["id"],
        "case_id": c["case_id"],
        "birth_parent_id": c["birth_parent_id"],
        "supersedes_consent_id": c["supersedes_consent_id"],
        "child_dob": format_iso(c["_child_dob"]),
        "signed_at": format_iso(c["_signed_at"]),
        "revocation_deadline": format_iso(c["_revocation_deadline"]),
        "revocation_basis": c["revocation_basis"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_icpc(i):
    return {
        "id": i["id"],
        "case_id": i["case_id"],
        "sending_state": i["sending_state"],
        "receiving_state": i["receiving_state"],
        "submitted_at": format_iso(i["_submitted_at"]),
        "status": i["status"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def serialize_placement(p):
    recompute_placement(p)
    return {
        "id": p["id"],
        "case_id": p["case_id"],
        "family_id": p["family_id"],
        "required_visits": p["required_visits"],
        "completed_visit_count": p["completed_visit_count"],
        "placed_at": format_iso(p["_placed_at"]),
        "finalized_at": format_iso(p["_finalized_at"]),
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_visit(v):
    return {
        "id": v["id"],
        "case_id": v["case_id"],
        "placement_id": v["placement_id"],
        "visiting_caseworker_id": v["visiting_caseworker_id"],
        "window_start": format_iso(v["_window_start"]),
        "window_end": format_iso(v["_window_end"]),
        "conducted_at": format_iso(v["_conducted_at"]),
        "status": v["status"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def serialize_expense(e):
    return _public(e)


def serialize_escrow_txn(t):
    return {
        "id": t["id"],
        "case_id": t["case_id"],
        "expense_id": t["expense_id"],
        "txn_type": t["txn_type"],
        "amount_cents": t["amount_cents"],
        "recorded_by_finance_id": t["recorded_by_finance_id"],
        "created_at": t["created_at"],
    }


def serialize_invoice(inv):
    return {
        "id": inv["id"],
        "case_id": inv["case_id"],
        "base_fee_cents": inv["base_fee_cents"],
        "sliding_scale_pct": inv["sliding_scale_pct"],
        "total_due_cents": inv["total_due_cents"],
        "status": inv["status"],
        "created_at": inv["created_at"],
        "updated_at": inv["updated_at"],
        "version": inv["version"],
    }


# --------------------------------------------------------------------------
# Child-entity lookups for a case
# --------------------------------------------------------------------------
def case_home_studies(case_id):
    return [h for h in db.home_studies.values() if h["case_id"] == case_id]


def case_matches(case_id):
    return [m for m in db.matches.values() if m["case_id"] == case_id]


def case_consents(case_id):
    return [c for c in db.consent_records.values() if c["case_id"] == case_id]


def case_icpc(case_id):
    return [i for i in db.icpc_clearances.values() if i["case_id"] == case_id]


def case_placements(case_id):
    return [p for p in db.placements.values() if p["case_id"] == case_id]


def case_expenses(case_id):
    return [e for e in db.expense_entries.values() if e["case_id"] == case_id]


def case_escrow_txns(case_id):
    return [t for t in db.escrow_transactions.values() if t["case_id"] == case_id]


def placement_visits(placement_id):
    return [v for v in db.post_placement_visits.values()
            if v["placement_id"] == placement_id]


# --------------------------------------------------------------------------
# Derived-field computations
# --------------------------------------------------------------------------
def compute_escrow_balance(case_id):
    bal = 0
    for t in case_escrow_txns(case_id):
        if t["txn_type"] == "DEPOSIT":
            bal += t["amount_cents"]
        elif t["txn_type"] == "DISBURSEMENT":
            bal -= t["amount_cents"]
        elif t["txn_type"] == "REFUND":
            bal -= t["amount_cents"]
    return bal


def compute_reimbursable(case_id):
    total = 0
    for e in case_expenses(case_id):
        if e["status"] in ("APPROVED", "DISBURSED"):
            total += e["amount_cents"]
    return total


def compute_phase(case):
    """case_phase projection (calculation case_phase). Pinned priority order;
    first matching rule wins, top to bottom.
    """
    cid = case["id"]
    placements = case_placements(cid)
    consents = case_consents(cid)

    # 1. any Placement FINALIZED -> FINALIZED
    if any(p["status"] == "FINALIZED" for p in placements):
        return "FINALIZED"
    # 2. any Placement DISRUPTED OR any ConsentRecord REVOKED -> DISRUPTED
    if any(p["status"] == "DISRUPTED" for p in placements) or \
       any(c["status"] == "REVOKED" for c in consents):
        return "DISRUPTED"
    # 3. any Placement ACTIVE -> PLACED
    if any(p["status"] == "ACTIVE" for p in placements):
        return "PLACED"
    # 4. interstate AND ICPC RECEIVING_APPROVED -> ICPC_CLEARED
    if case["interstate"] and any(i["status"] == "RECEIVING_APPROVED"
                                  for i in case_icpc(cid)):
        return "ICPC_CLEARED"
    # 5. any ConsentRecord IRREVOCABLE -> CONSENTED
    if any(c["status"] == "IRREVOCABLE" for c in consents):
        return "CONSENTED"
    # 6. any Match ACCEPTED -> MATCHED
    if any(m["status"] == "ACCEPTED" for m in case_matches(cid)):
        return "MATCHED"
    # 7. any HomeStudy APPROVED and not expired (clock < expires_at) -> HOME_STUDY
    clock = agency_clock_for_case(case)
    for h in case_home_studies(cid):
        if h["status"] == "APPROVED" and h["_expires_at"] is not None and \
           clock is not None and clock < h["_expires_at"]:
            return "HOME_STUDY"
    # 8. else INTAKE
    return "INTAKE"


def agency_clock_for_case(case):
    agency = db.agencies.get(case["agency_id"])
    if agency is None:
        return None
    return agency["_current_utc"]


def reconcile_case(case):
    """Recompute the case's derived fields in place (does NOT bump version)."""
    case["interstate"] = case["child_state"] != case["family_state"]
    case["escrow_balance_cents"] = compute_escrow_balance(case["id"])
    case["reimbursable_expense_cents"] = compute_reimbursable(case["id"])
    case["phase"] = compute_phase(case)


def reconcile_case_mut(case):
    """Reconcile derived fields AND register this as a mutation (touch).

    Used when a child transition feeds a derived case field; per PRD §2.8 the
    parent recomputation is itself a mutation that bumps version + updated_at.
    """
    reconcile_case(case)
    touch(case)


def recompute_placement(p):
    """Recompute placement derived fields in place (no version bump)."""
    case = db.cases.get(p["case_id"])
    if case is not None:
        interstate = case["child_state"] != case["family_state"]
    else:
        interstate = False
    p["required_visits"] = REQUIRED_VISITS_INTERSTATE if interstate else REQUIRED_VISITS_INSTATE
    p["completed_visit_count"] = sum(
        1 for v in placement_visits(p["id"]) if v["status"] == "COMPLETED"
    )
