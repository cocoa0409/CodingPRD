"""Entity -> public JSON serialization.

Common fields (PRD §2.4): id, created_at, updated_at, version on all entities
EXCEPT ClaimDocument which is append-only (id + created_at only).
Internal bookkeeping keys (prefixed with '_') are stripped.
"""

PLAN_FIELDS = [
    "code", "tier", "base_rate_bps", "cancellation_limit_pct", "medical_limit_cents",
    "delay_block_cap_cents", "delay_limit_cents", "baggage_item_sublimit_cents",
    "baggage_limit_cents", "baggage_depreciation_bps", "waiver_window_days",
    "free_look_days", "claim_filing_window_days", "cfar_loading_bps",
    "cfar_reimbursement_pct", "senior_age_threshold", "senior_loading_bps", "status",
]

TRAVELER_FIELDS = ["email", "full_name", "date_of_birth"]

POLICY_FIELDS = [
    "plan_id", "owner_traveler_id", "trip_cost_cents", "initial_deposit_at",
    "trip_start_at", "trip_end_at", "cfar_opted", "base_premium_cents",
    "premium_cents", "aggregate_limit_cents", "amount_reimbursed_cents",
    "remaining_aggregate_cents", "net_premium_collected_cents",
    "preexisting_waiver_granted", "issued_at", "free_look_ends_at",
    "payment_status", "coverage_status",
]

INSURED_FIELDS = [
    "policy_id", "traveler_id", "age_at_departure", "has_preexisting_condition",
    "covered_trip_cost_cents", "status",
]

NAMED_STORM_FIELDS = ["name", "basin", "named_at", "status"]

CLAIM_FIELDS = [
    "policy_id", "insured_traveler_id", "named_storm_id", "peril",
    "cancellation_reason", "incident_at", "delay_hours", "involves_preexisting",
    "provisional_amount_cents", "approved_amount_cents", "denial_reason", "status",
]

CLAIM_EXPENSE_FIELDS = [
    "claim_id", "category", "description", "documented_amount_cents",
    "prepaid_nonrefundable_cents", "supplier_refund_received_cents", "item_value_cents",
]

CLAIM_DOCUMENT_FIELDS = ["claim_id", "doc_type", "file_ref", "uploaded_by_traveler_id"]

PAYOUT_FIELDS = ["claim_id", "policy_id", "amount_cents", "status"]

REFUND_FIELDS = ["policy_id", "refund_type", "amount_cents", "status"]


def _base(record, with_version=True):
    out = {
        "id": record["id"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
    }
    if with_version:
        out["version"] = record["version"]
    return out


def _pick(record, fields):
    return {f: record.get(f) for f in fields}


def plan_out(r):
    out = _base(r)
    out.update(_pick(r, PLAN_FIELDS))
    return out


def traveler_out(r):
    out = _base(r)
    out.update(_pick(r, TRAVELER_FIELDS))
    return out


def policy_out(r):
    out = _base(r)
    out.update(_pick(r, POLICY_FIELDS))
    return out


def insured_out(r):
    out = _base(r)
    out.update(_pick(r, INSURED_FIELDS))
    return out


def named_storm_out(r):
    out = _base(r)
    out.update(_pick(r, NAMED_STORM_FIELDS))
    return out


def claim_out(r):
    out = _base(r)
    out.update(_pick(r, CLAIM_FIELDS))
    return out


def claim_expense_out(r):
    out = _base(r)
    out.update(_pick(r, CLAIM_EXPENSE_FIELDS))
    return out


def claim_document_out(r):
    # Append-only: id + created_at only (no updated_at, no version)
    out = {"id": r["id"], "created_at": r["created_at"]}
    out.update(_pick(r, CLAIM_DOCUMENT_FIELDS))
    return out


def payout_out(r):
    out = _base(r)
    out.update(_pick(r, PAYOUT_FIELDS))
    return out


def refund_out(r):
    out = _base(r)
    out.update(_pick(r, REFUND_FIELDS))
    return out
