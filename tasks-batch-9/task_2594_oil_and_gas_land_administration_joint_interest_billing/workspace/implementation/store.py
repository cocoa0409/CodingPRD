"""In-memory store. Starts completely empty on every boot; nothing is seeded."""
import uuid

from common import now_ts, serialize

TABLES = (
    "leases",
    "allocations",
    "wells",
    "owners",
    "interests",
    "afes",
    "elections",
    "cost_entries",
    "statements",
    "line_items",
    "disputes",
    "revenues",
    "disbursements",
    "transfers",
)


class Store(object):
    def __init__(self):
        for name in TABLES:
            setattr(self, name, {})
        # transfer_id -> {owner_id: "EXERCISE"|"WAIVE"}
        self.ppr_elections = {}
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def insert(table, record):
    record["id"] = record.get("id") or new_id()
    stamp = now_ts()
    record.setdefault("created_at", stamp)
    if record.get("_versioned", True):
        record.setdefault("updated_at", stamp)
        record.setdefault("version", 1)
    record.pop("_versioned", None)
    record["_seq"] = db.next_seq()
    getattr(db, table)[record["id"]] = record
    return record


def rows(table):
    return list(getattr(db, table).values())


def order_key(record):
    return (record["created_at"], record["_seq"])


def by_created(records, descending=False):
    return sorted(records, key=order_key, reverse=descending)


# ---------------------------------------------------------------- field maps

LEASE_FIELDS = [
    "id", "lease_number", "lessor_name", "gross_acres", "royalty_rate",
    "primary_term_end_date", "extension_option_months",
    "extension_bonus_per_acre_cents", "extension_exercised",
    "extension_bonus_paid_cents", "shut_in_royalty_per_acre_cents",
    "shut_in_start_date", "shut_in_payments_made", "shut_in_next_due_date",
    "continuous_dev_window_days", "last_operation_end_date",
    "continuous_dev_deadline", "tenure_status", "obligation_status",
    "committed_acres_total", "held_acres", "created_at", "updated_at", "version",
]

ALLOCATION_FIELDS = [
    "id", "well_id", "lease_id", "committed_acres", "allocation_factor",
    "allocation_status", "withdrawn_reason", "created_at", "updated_at", "version",
]

WELL_FIELDS = [
    "id", "well_name", "api_number", "product_type", "total_depth_ft",
    "spud_date", "first_production_date", "shut_in_since", "well_status",
    "pooling_status", "allocation_factor_total", "consent_working_interest_pct",
    "plugging_liability_cents", "billed_to_date_cents",
    "created_at", "updated_at", "version",
]

OWNER_FIELDS = [
    "id", "owner_name", "owner_type", "contact_email", "tax_id_on_file",
    "bond_posted_cents", "required_bond_cents", "suspense_balance_cents",
    "audit_window_days", "created_at", "updated_at", "version",
]

INTEREST_FIELDS = [
    "id", "well_id", "owner_id", "working_interest_pct",
    "net_revenue_interest_pct", "effective_from", "effective_to", "is_operator",
    "preferential_right", "interest_status", "non_consent_flag",
    "non_consent_recoverable_balance_cents",
    "created_at", "updated_at", "version",
]

AFE_FIELDS = [
    "id", "well_id", "afe_number", "operation_type", "estimated_cost_cents",
    "cost_class", "election_deadline_date", "non_consent_penalty_multiple",
    "minimum_consent_pct", "afe_status", "consent_working_interest_pct",
    "non_consent_working_interest_pct", "elections_closed_at",
    "created_at", "updated_at", "version",
]

ELECTION_FIELDS = [
    "id", "afe_id", "owner_id", "election_type", "election_status",
    "wi_pct_snapshot", "estimated_penalty_cents", "submitted_at",
    "created_at", "updated_at", "version",
]

COST_FIELDS = [
    "id", "well_id", "afe_id", "cost_category", "cost_class", "amount_cents",
    "incurred_date", "paid_date", "cost_status",
    "created_at", "updated_at", "version",
]

STATEMENT_FIELDS = [
    "id", "well_id", "superseded_statement_id", "statement_number",
    "billing_period_start", "billing_period_end", "cost_basis",
    "activity_class", "overhead_rate_class", "capital_direct_cents",
    "operating_direct_cents", "direct_cost_cents", "billable_months",
    "overhead_cents", "total_billed_cents", "prepared_by_user_id", "issued_at",
    "payment_due_date", "statement_status", "created_at", "updated_at", "version",
]

LINE_ITEM_FIELDS = [
    "id", "statement_id", "owner_id", "wi_pct_snapshot",
    "consent_normalized_wi_pct", "direct_capital_cents",
    "direct_operating_cents", "overhead_cents", "non_consent_reallocated_cents",
    "non_consent_withheld_cents", "penalty_accrued_cents",
    "rounding_residual_cents", "total_billed_cents", "created_at",
]

DISPUTE_FIELDS = [
    "id", "statement_id", "owner_id", "dispute_kind", "disputed_amount_cents",
    "basis_note", "filed_at", "response_due_date", "rebuttal_due_date",
    "operator_responded_at", "round_count", "dispute_status",
    "adjustment_amount_cents", "resolved_by_user_id",
    "deemed_in_favor_of_partner", "created_at", "updated_at", "version",
]

REVENUE_FIELDS = [
    "id", "well_id", "production_month", "gross_revenue_cents", "volume_units",
    "sale_date", "severance_tax_cents", "net_proceeds_cents",
    "total_royalty_cents", "total_disbursed_cents", "statutory_due_date",
    "released_at", "distribution_status", "created_at", "updated_at", "version",
]

DISBURSEMENT_FIELDS = [
    "id", "revenue_id", "owner_id", "lease_id", "gross_share_cents",
    "withheld_recovery_cents", "net_amount_cents", "late_interest_cents",
    "interest_basis", "paid_at", "suspense_reason", "disbursement_status",
    "created_at", "updated_at", "version",
]

TRANSFER_FIELDS = [
    "id", "well_id", "assignor_owner_id", "assignee_owner_id",
    "ppr_holder_owner_id", "transfer_wi_pct", "transfer_nri_pct",
    "sale_price_cents", "notice_date", "effective_date", "ppr_deadline_date",
    "ppr_eligible_count", "ppr_waiver_count", "bond_check_required_cents",
    "transfer_status", "created_at", "updated_at", "version",
]


def out_lease(r):
    return serialize(r, LEASE_FIELDS)


def out_allocation(r):
    return serialize(r, ALLOCATION_FIELDS)


def out_well(r):
    return serialize(r, WELL_FIELDS)


def out_owner(r):
    return serialize(r, OWNER_FIELDS)


def out_interest(r):
    return serialize(r, INTEREST_FIELDS)


def out_afe(r):
    return serialize(r, AFE_FIELDS)


def out_election(r):
    return serialize(r, ELECTION_FIELDS)


def out_cost(r):
    return serialize(r, COST_FIELDS)


def out_statement(r):
    return serialize(r, STATEMENT_FIELDS)


def out_line_item(r):
    return serialize(r, LINE_ITEM_FIELDS)


def out_dispute(r):
    return serialize(r, DISPUTE_FIELDS)


def out_revenue(r):
    return serialize(r, REVENUE_FIELDS)


def out_disbursement(r):
    return serialize(r, DISBURSEMENT_FIELDS)


def out_transfer(r):
    return serialize(r, TRANSFER_FIELDS)
