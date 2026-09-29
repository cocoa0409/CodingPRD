"""Entity serializers.  Each emits exactly the declared fields."""

COMMON = ("id", "created_at", "updated_at", "version")

ELECTION_FIELDS = (
    "id", "name", "jurisdiction", "election_date", "rotation_policy",
    "candidate_order_method", "la_notice_hours", "status",
    "certified_contest_count", "committed_print_cents", "deployment_readiness",
    "open_seal_count", "total_ballots_received", "total_ballots_issued",
    "ballot_accountability_status", "net_ballot_variance", "reconciliation_basis",
    "last_reconciled_at", "created_at", "updated_at", "version",
)

CONTEST_FIELDS = (
    "id", "election_id", "title", "contest_type", "district_code", "seats_open",
    "rotation_required", "ballot_order_index", "status",
    "certified_candidate_count", "certified_at", "withdrawn_reason",
    "created_at", "updated_at", "version",
)

CANDIDATE_FIELDS = (
    "id", "contest_id", "full_name", "ballot_name", "party_code",
    "filing_received_at", "status", "base_order_index", "disqualified_reason",
    "created_at", "updated_at", "version",
)

PRECINCT_FIELDS = (
    "id", "election_id", "precinct_code", "district_codes",
    "registered_voter_count", "polling_place", "assigned_style_id",
    "required_ballot_quantity", "ballots_received", "deployment_status",
    "created_at", "updated_at", "version",
)

STYLE_FIELDS = (
    "id", "election_id", "style_code", "district_codes", "language_set",
    "required_formats", "supersedes_style_id", "revision", "status",
    "proof_cycle_count", "proof_requested_by_user_id", "proof_decided_by_user_id",
    "translated_languages", "certified_formats", "rotation_seed_index",
    "contest_count", "precinct_count", "created_at", "updated_at", "version",
)

VENDOR_FIELDS = (
    "id", "name", "press_line_count", "certified_secure", "status",
    "quality_defect_rate_bp", "active_job_count",
    "created_at", "updated_at", "version",
)

JOB_FIELDS = (
    "id", "election_id", "vendor_id", "style_id", "quantity_ordered",
    "unit_cost_cents_per_thousand", "press_window_start", "press_window_end",
    "style_version_at_creation", "status", "approved_by_user_id", "sample_size",
    "defect_count", "defect_rate_bp", "inspection_count", "delivered_quantity",
    "invoice_basis", "invoice_subtotal_cents", "defect_credit_cents",
    "freight_cents", "invoice_total_cents", "created_at", "updated_at", "version",
)

LOT_FIELDS = (
    "id", "election_id", "print_job_id", "precinct_id", "lot_code",
    "quantity_shipped", "seal_number", "custody_state", "quantity_received",
    "issued_quantity", "voted_quantity", "spoiled_quantity", "unused_quantity",
    "returned_unused_quantity", "accounted_quantity", "lot_variance",
    "issued_by_user_id", "created_at", "updated_at", "version",
)

UNIT_FIELDS = (
    "id", "election_id", "precinct_id", "programmed_style_id", "asset_tag",
    "firmware_version", "program_status", "custody_status", "seal_number",
    "programmed_by_user_id", "la_session_count", "retention_until",
    "created_at", "updated_at", "version",
)

DECK_FIELDS = (
    "id", "style_id", "deck_code", "ballot_count", "blank_count",
    "overvote_count", "expected_marks", "expected_total_marks", "status",
    "created_by_user_id", "created_at", "updated_at", "version",
)

SESSION_FIELDS = (
    "id", "tabulator_id", "deck_id", "session_type", "scheduled_start",
    "scheduled_end", "public_notice_posted_at", "status", "notice_lead_minutes",
    "observer_count", "observer_names", "reported_marks", "reported_blank_count",
    "reported_overvote_count", "discrepancy_count", "conducted_by_user_id",
    "started_at", "completed_at", "created_at", "updated_at", "version",
)

EVENT_FIELDS = (
    "id", "election_id", "subject_type", "subject_id", "event_type",
    "from_state", "to_state", "seal_number", "actor_role", "actor_user_id",
    "occurred_at", "sequence_index", "created_at",
)


def _pick(row, fields):
    return {name: row.get(name) for name in fields}


def election(row):
    return _pick(row, ELECTION_FIELDS)


def contest(row):
    return _pick(row, CONTEST_FIELDS)


def candidate(row):
    return _pick(row, CANDIDATE_FIELDS)


def precinct(row):
    return _pick(row, PRECINCT_FIELDS)


def style(row):
    return _pick(row, STYLE_FIELDS)


def vendor(row):
    return _pick(row, VENDOR_FIELDS)


def job(row):
    return _pick(row, JOB_FIELDS)


def lot(row):
    return _pick(row, LOT_FIELDS)


def unit(row):
    return _pick(row, UNIT_FIELDS)


def deck(row):
    return _pick(row, DECK_FIELDS)


def session(row):
    return _pick(row, SESSION_FIELDS)


def event(row):
    return _pick(row, EVENT_FIELDS)
