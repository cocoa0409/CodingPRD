"""In-memory store. Every collection is a plain dict keyed by id.

The store starts completely empty on every boot: nothing here seeds, preloads or
hardcodes any entity. All rows are created by the declared API surface.
"""

import threading
import uuid

from flask import g

from timeutil import fmt_ms, parse_iso_ms, as_number

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00.000Z"

# Domain constants (SCAFFOLD 1.3 / PRD 2.6, 2.7, 3.5, 3.6, 3.8)
SMALL_TICKET_MAX_CENTS = 1500
CROSS_BORDER_RATE_BPS = 40
CROSS_BORDER_MIN_CENTS = 15
ASSESSMENT_CAP_BPS = 350
ASSESSMENT_FLOOR_CENTS = 8
DOWNGRADE_AUDIT_TRIGGER = 3
MAX_REVIEW_ROUNDS = 3
AUTH_VALIDITY_HOURS = 720
MISREPRESENTATION_PENALTY_BPS = 2500
MIN_PENALTY_CENTS = 5000
TIER_DISCOUNT_BPS = {"TIER_0": 0, "TIER_1": 25, "TIER_2": 60, "TIER_3": 100}
TIER_1_FLOOR_CENTS = 5000000
TIER_2_FLOOR_CENTS = 20000000
TIER_3_FLOOR_CENTS = 50000000

DATA_ELEMENT_VOCAB = (
    "AUTH_CODE",
    "TERMINAL_ID",
    "TRANSACTION_DATE",
    "CARDHOLDER_ZIP",
    "CUSTOMER_ACCOUNT_REF",
    "TAX_AMOUNT",
)
PROGRAM_ELIGIBILITY_VOCAB = ("SMALL_TICKET", "UTILITY", "GOVERNMENT", "CHARITY")
REGION_CODES = ("NA", "EU", "AP", "LAC", "CEMEA")
RATE_PROGRAM_CATEGORIES = (
    "CPS_RETAIL",
    "SMALL_TICKET",
    "UTILITY",
    "GOVERNMENT",
    "CHARITY",
    "STANDARD",
)
ROLES = (
    "NetworkAdmin",
    "AcquirerOps",
    "CategoryAnalyst",
    "CategoryApprover",
    "ComplianceAuditor",
)

COLLECTIONS = (
    "platforms",
    "acquirers",
    "mcc_definitions",
    "merchants",
    "reclass_requests",
    "rate_programs",
    "rate_versions",
    "windows",
    "batches",
    "records",
    "incentive_programs",
    "enrollments",
    "audits",
    "fx_rates",
)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock_ms = parse_iso_ms(DEFAULT_CLOCK_UTC)
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq

    def now_ms(self):
        return self.clock_ms


store = Store()


# ---------------------------------------------------------------------------
# Row lifecycle
# ---------------------------------------------------------------------------

def new_row(fields):
    """Mint a row with id, version 1 and logical-clock audit stamps."""
    row = dict(fields)
    row["id"] = str(uuid.uuid4())
    row["version"] = 1
    row["_seq"] = store.next_seq()
    row["_created_ms"] = store.now_ms()
    row["_updated_ms"] = store.now_ms()
    return row


def touch(row):
    """Record a mutation: refresh updated_at and advance version by exactly 1.

    Dedup is per-request: a row changed several times inside one request (for
    instance by two chained cascade hops) advances its version once.
    """
    try:
        seen = g._touched
    except (AttributeError, RuntimeError):
        seen = None
    key = row.get("id")
    if seen is not None:
        if key in seen:
            row["_updated_ms"] = store.now_ms()
            return row
        seen.add(key)
    row["version"] = int(row.get("version", 1)) + 1
    row["_updated_ms"] = store.now_ms()
    return row


def sort_key(row):
    """Canonical ordering: created_at ascending, insertion sequence as the
    deterministic tiebreak. The row id is never consulted."""
    return (row["_created_ms"], row["_seq"])


def sorted_rows(rows):
    return sorted(rows, key=sort_key)


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

DT_FIELDS = frozenset((
    "effective_from",
    "effective_to",
    "implementation_deadline",
    "published_at",
    "window_start",
    "window_end",
    "started_at",
    "auth_timestamp",
    "clearing_timestamp",
    "finalized_at",
    "enrolled_at",
    "fieldwork_start",
    "fieldwork_end",
))

NUMBER_FIELDS = frozenset(("performance_threshold_pct", "performance_score_pct", "rate"))

FIELD_ORDER = {
    "ProcessingPlatform": (
        "name", "region_code", "max_concurrent_windows", "blackout_buffer_days",
    ),
    "Acquirer": (
        "name", "bin_prefix", "platform_id", "country_code", "settlement_currency",
        "compliance_status", "missed_window_count",
    ),
    "MccDefinition": (
        "mcc_code", "description", "business_type_key", "program_eligibility",
        "requires_documentation", "high_risk",
    ),
    "Merchant": (
        "legal_name", "business_type_key", "acquirer_id", "home_country_code",
        "assigned_mcc", "mcc_status", "mcc_status_before_review", "documentation_ref",
        "verified_by_user_id", "downgrade_count_current_quarter",
        "lifetime_net_assessed_cents",
    ),
    "ReclassificationRequest": (
        "merchant_id", "requested_mcc", "justification", "supporting_doc_ref",
        "status", "review_round", "reviewer_user_id", "decider_user_id",
        "info_request_note", "decision_note", "decided_mcc",
        "prior_status_before_suspension",
    ),
    "RateProgram": (
        "program_code", "name", "category", "eligible_mcc_codes", "base_rate_bps",
        "per_item_fee_cents", "requires_data_elements", "max_clearing_delay_hours",
    ),
    "RateProgramVersion": (
        "rate_program_id", "publication_quarter", "effective_from", "effective_to",
        "base_rate_bps", "per_item_fee_cents", "implementation_deadline", "status",
        "published_at",
    ),
    "AcquirerImplementationWindow": (
        "acquirer_id", "rate_program_version_id", "platform_id", "window_start",
        "window_end", "status", "started_at", "completion_note",
    ),
    "SettlementBatch": (
        "acquirer_id", "batch_date", "currency_code", "status", "record_count",
        "total_assessed_cents", "finalized_at",
    ),
    "TransactionRecord": (
        "settlement_batch_id", "merchant_id", "amount_cents", "transaction_currency",
        "auth_code", "auth_timestamp", "clearing_timestamp", "data_elements",
        "authorization_status", "qualification_status", "clearing_delay_hours",
        "cross_border", "provisional_rate_program_id", "qualified_rate_program_id",
        "provisional_assessed_cents", "assessed_interchange_cents",
        "cross_border_surcharge_cents", "fx_markup_cents", "downgrade_reason",
        "mcc_at_qualification", "reversal_type", "reversal_reason",
    ),
    "IncentiveProgram": (
        "program_name", "eligible_mcc_codes", "total_capacity_cents",
        "min_commitment_cents", "reopen_threshold_cents", "performance_threshold_pct",
        "uncommitted_capacity_cents", "enrolled_count", "enrollment_state",
    ),
    "IncentiveEnrollment": (
        "incentive_program_id", "merchant_id", "committed_volume_cents", "status",
        "waitlist_requested", "enrolled_at", "last_evaluated_basis",
        "achieved_volume_cents", "performance_score_pct", "gross_assessed_volume_cents",
        "tier_code", "incentive_credit_cents", "net_assessed_volume_cents",
        "probation_count", "withdrawal_reason",
    ),
    "MerchantCategoryAudit": (
        "merchant_id", "trigger_reason", "status", "auditor_user_id",
        "fieldwork_start", "fieldwork_end", "correct_mcc", "findings_note",
        "penalty_assessed_cents", "mcc_at_audit_open", "closed_by_user_id",
    ),
    "FxRate": (
        "base_currency", "quote_currency", "rate", "markup_bps", "effective_from",
    ),
}


def serialize(kind, row):
    out = {"id": row["id"]}
    for field in FIELD_ORDER[kind]:
        value = row.get(field)
        if field in DT_FIELDS:
            out[field] = fmt_ms(value) if value is not None else None
        elif field in NUMBER_FIELDS:
            out[field] = as_number(value)
        elif isinstance(value, list):
            out[field] = list(value)
        else:
            out[field] = value
    out["created_at"] = fmt_ms(row["_created_ms"])
    out["updated_at"] = fmt_ms(row["_updated_ms"])
    out["version"] = row["version"]
    return out


def serialize_many(kind, rows):
    return [serialize(kind, r) for r in rows]
