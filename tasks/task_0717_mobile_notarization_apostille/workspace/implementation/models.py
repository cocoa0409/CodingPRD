"""Entity record construction and serialization.

Records are plain dicts stored in db. We keep an internal '_seq' for stable
created_at tie-breaking and a '_kind' marker. Serialization strips internals.

common_fields=True entities carry: id, created_at, updated_at, version.
common_fields=False entities carry only: id, created_at (+ their own fields).
"""
import db

# Public fields, in declaration order, per entity kind.
PUBLIC_FIELDS = {
    "FeeSchedule": ["id", "state_code", "per_stamp_cents", "travel_base_cents",
                    "travel_per_mile_cents", "ron_surcharge_cents", "state_cap_cents",
                    "enhanced_trust_required", "created_at"],
    "Account": ["id", "org_name", "default_state_code", "retention_years",
                "created_at", "updated_at", "version"],
    "Notary": ["id", "account_id", "full_name", "commission_state",
               "commission_expires_at", "ron_authorized", "nsa_certified",
               "status", "active_session_count", "created_at", "updated_at", "version"],
    "Signer": ["id", "account_id", "full_name", "email", "id_doc_type",
               "created_at", "updated_at", "version"],
    "SigningRequest": ["id", "account_id", "signer_id", "state_code", "doc_category",
                       "delivery_mode", "expected_stamp_count", "estimated_travel_miles",
                       "assigned_notary_id", "status", "estimate_fee_cents",
                       "final_fee_cents", "actual_travel_miles",
                       "created_at", "updated_at", "version"],
    "RequestDocument": ["id", "request_id", "title", "doc_type", "requires_apostille",
                        "signing_fee_cents", "created_at", "updated_at", "version"],
    "Assignment": ["id", "request_id", "notary_id", "status",
                   "created_at", "updated_at", "version"],
    "RonSession": ["id", "request_id", "notary_id", "scheduled_start", "scheduled_end",
                   "session_status", "recording_status",
                   "created_at", "updated_at", "version"],
    "IdVerification": ["id", "request_id", "signer_id", "kba_score", "credential_score",
                       "biometric_score", "trust_variant", "trust_score", "outcome",
                       "created_at", "updated_at", "version"],
    "JournalEntry": ["id", "request_id", "document_id", "notary_id", "act_type",
                     "entry_status", "created_at"],
    "ApostilleOrder": ["id", "document_id", "destination_country", "authentication_type",
                       "sos_office_state", "fee_cents", "status", "resubmit_count",
                       "created_at", "updated_at", "version"],
    "LoanPackage": ["id", "request_id", "lender_ref", "package_discount_pct",
                    "scrub_passed", "package_fee_cents", "status",
                    "created_at", "updated_at", "version"],
    "RetentionRecord": ["id", "request_id", "journal_entry_count", "retain_until",
                        "hold_status", "created_at"],
}

COMMON_FIELDS = {
    "FeeSchedule": False,
    "Account": True,
    "Notary": True,
    "Signer": True,
    "SigningRequest": True,
    "RequestDocument": True,
    "Assignment": True,
    "RonSession": True,
    "IdVerification": True,
    "JournalEntry": False,
    "ApostilleOrder": True,
    "LoanPackage": True,
    "RetentionRecord": False,
}


def new_record(kind, fields):
    """Create a record dict with system-managed common fields."""
    rec = dict(fields)
    rec["_kind"] = kind
    rec["_seq"] = db.next_seq()
    rec["id"] = db.new_id()
    ts = db.now_iso()
    rec["created_at"] = ts
    if COMMON_FIELDS[kind]:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Bump version + updated_at for a mutation (common_fields entities only)."""
    if COMMON_FIELDS.get(rec["_kind"]):
        rec["updated_at"] = db.now_iso()
        rec["version"] = rec.get("version", 1) + 1


def serialize(rec):
    fields = PUBLIC_FIELDS[rec["_kind"]]
    return {f: rec[f] for f in fields if f in rec}
