"""Resource serializers. Field sets follow SCAFFOLD.yaml Table 1."""

from store import db

COMMON = ("id", "created_at", "updated_at", "version")


def _pick(row, fields):
    out = {}
    for name in fields:
        out[name] = row.get(name)
    return out


FACILITY_FIELDS = (
    "id", "code", "name", "cfc_rate_per_transaction_day_cents",
    "ds_reserve_requirement_cents", "om_reserve_requirement_cents",
    "capital_fund_cap_cents", "overflow_lot_stalls", "overflow_daily_surcharge_cents",
    "remittance_grace_days", "trust_lifetime_received_cents",
    "trust_debt_service_reserve_cents", "trust_debt_service_funded_cents",
    "trust_om_reserve_cents", "trust_capital_fund_cents", "trust_unallocated_cents",
    "trust_encumbered_cents", "trust_disbursed_cents", "bond_coverage_status",
    "funded_obligation_count", "overflow_stalls_allocated",
) + COMMON[1:]


def facility(row):
    out = _pick(row, FACILITY_FIELDS)
    out["overflow_stalls_available"] = row["overflow_lot_stalls"] - row["overflow_stalls_allocated"]
    out["current_utc"] = db.clock
    return out


CONCESSIONAIRE_FIELDS = (
    "id", "facility_id", "legal_name", "brand_code", "contact_email",
    "agreement_count") + COMMON[1:]


def concessionaire(row):
    return _pick(row, CONCESSIONAIRE_FIELDS)


AGREEMENT_FIELDS = (
    "id", "facility_id", "concessionaire_id", "contract_year_index",
    "term_start_date", "term_end_date", "mag_annual_cents",
    "percentage_rent_rate_bps", "rent_settlement_basis", "contract_status",
    "compliance_status", "gross_revenue_ytd_cents", "transaction_days_ytd",
    "accepted_report_count", "percentage_rent_accrued_cents",
    "rent_billed_to_date_cents", "last_installment_cents", "rent_tier",
    "mag_shortfall_cents", "counter_units_assigned", "fleet_stalls_allocated",
) + COMMON[1:]


def agreement(row):
    return _pick(row, AGREEMENT_FIELDS)


COUNTER_SPACE_FIELDS = (
    "id", "facility_id", "terminal_code", "space_label", "space_class",
    "active_assignment_id", "assignment_count") + COMMON[1:]


def counter_space(row):
    return _pick(row, COUNTER_SPACE_FIELDS)


COUNTER_ASSIGNMENT_FIELDS = (
    "id", "agreement_id", "counter_space_id", "effective_start_date",
    "effective_end_date", "status", "released_on_date") + COMMON[1:]


def counter_assignment(row):
    return _pick(row, COUNTER_ASSIGNMENT_FIELDS)


ZONE_FIELDS = (
    "id", "facility_id", "zone_label", "stall_capacity", "stalls_allocated",
) + COMMON[1:]


def zone(row):
    out = _pick(row, ZONE_FIELDS)
    out["stalls_available"] = row["stall_capacity"] - row["stalls_allocated"]
    return out


FLEET_ALLOCATION_FIELDS = (
    "id", "agreement_id", "zone_id", "start_date", "end_date", "stalls_requested",
    "allow_overflow", "zone_stalls_granted", "overflow_stalls_granted",
    "inclusive_days", "overflow_surcharge_cents", "status") + COMMON[1:]


def fleet_allocation(row):
    return _pick(row, FLEET_ALLOCATION_FIELDS)


REPORT_FIELDS = (
    "id", "agreement_id", "period_year", "period_month",
    "reported_gross_revenue_cents", "reported_on_airport_transaction_days",
    "audited_gross_revenue_cents", "audited_on_airport_transaction_days",
    "revenue_variance_cents", "variance_assessment_cents",
    "period_rent_installment_cents", "status", "audited_by_user_id",
    "rejection_reason", "submission_count") + COMMON[1:]


def report(row):
    return _pick(row, REPORT_FIELDS)


REMITTANCE_FIELDS = (
    "id", "agreement_id", "report_id", "remittance_basis", "expected_amount_cents",
    "amount_received_cents", "shortfall_cents", "due_date", "status",
    "allocated_to_debt_service_cents", "allocated_to_om_cents",
    "allocated_to_capital_cents", "allocated_to_unallocated_cents") + COMMON[1:]


def remittance(row):
    return _pick(row, REMITTANCE_FIELDS)


OBLIGATION_FIELDS = (
    "id", "facility_id", "series_label", "due_date", "amount_due_cents",
    "coverage_requirement_bps", "coverage_ratio_at_funding",
    "funded_from_reserve_cents", "auto_funded", "status") + COMMON[1:]


def obligation(row):
    return _pick(row, OBLIGATION_FIELDS)


SHUTTLE_PERIOD_FIELDS = (
    "id", "facility_id", "period_year", "period_month", "total_cost_cents",
    "allocation_basis", "total_basis_value", "allocated_total_cents",
    "line_count", "status") + COMMON[1:]


def shuttle_period(row):
    return _pick(row, SHUTTLE_PERIOD_FIELDS)


SHUTTLE_ALLOCATION_FIELDS = (
    "id", "shuttle_period_id", "agreement_id", "basis_value", "share_bps",
    "floor_cents", "remainder_rank", "amount_cents", "created_at")


def shuttle_allocation(row):
    return _pick(row, SHUTTLE_ALLOCATION_FIELDS)


PROJECT_FIELDS = (
    "id", "facility_id", "predecessor_project_id", "project_name", "budget_cents",
    "disbursed_cents", "encumbered_cents", "draw_request_count",
    "rejected_draw_count", "funding_hold", "status") + COMMON[1:]


def project(row):
    return _pick(row, PROJECT_FIELDS)


DISBURSEMENT_FIELDS = (
    "id", "project_id", "amount_cents", "memo", "requested_by_user_id",
    "authorized_by_user_id", "status") + COMMON[1:]


def disbursement(row):
    return _pick(row, DISBURSEMENT_FIELDS)


SETTLEMENT_FIELDS = (
    "id", "agreement_id", "contract_year_index", "final_percentage_rent_cents",
    "mag_cents", "rent_billed_cents", "audit_assessment_cents",
    "base_true_up_cents", "credit_bps", "shuttle_credit_cents",
    "net_true_up_cents", "amount_paid_cents", "issued_by_user_id", "status",
) + COMMON[1:]


def settlement(row):
    return _pick(row, SETTLEMENT_FIELDS)
