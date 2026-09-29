"""Entity to JSON projections.

Every resource carries the common set id / created_at / updated_at / version
(PRD 2.4). The adjudication event is deliberately leaner: id and created_at
only, because it is append-only and never mutated.
"""

COMMON = ("id", "created_at", "updated_at", "version")

FIELDS = {
    "benefit_plan": (
        "plan_code",
        "name",
        "plan_year_start_date",
        "deductible_individual_cents",
        "oop_max_individual_cents",
        "coinsurance_member_pct",
        "copay_office_visit_cents",
        "out_of_network_penalty_pct",
        "timely_filing_days",
        "cob_method",
    ),
    "fee_schedule_rate": (
        "plan_id",
        "procedure_code",
        "allowed_amount_cents",
        "effective_date",
    ),
    "member": (
        "member_number",
        "plan_id",
        "first_name",
        "last_name",
        "date_of_birth",
        "status",
    ),
    "member_coverage": (
        "member_id",
        "effective_date",
        "term_date",
        "cob_order",
        "other_payer_name",
        "coverage_tier",
        "status",
    ),
    "benefit_accumulator": (
        "member_id",
        "plan_year",
        "deductible_applied_cents",
        "oop_applied_cents",
        "remitted_claim_count",
    ),
    "provider": ("npi", "name", "network_status", "specialty_code"),
    "provider_contract": (
        "provider_id",
        "plan_id",
        "effective_date",
        "term_date",
        "pricing_method",
        "contract_pct",
        "case_rate_cents",
        "status",
    ),
    "edit_rule": (
        "rule_code",
        "edit_type",
        "primary_code",
        "secondary_code",
        "max_units",
        "severity",
        "precedence_rank",
        "reason_code",
    ),
    "authorization": (
        "member_id",
        "provider_id",
        "procedure_code",
        "authorized_units",
        "units_consumed",
        "valid_from",
        "valid_to",
        "status",
    ),
    "claim": (
        "claim_number",
        "member_id",
        "provider_id",
        "coverage_id",
        "original_claim_id",
        "duplicate_of_claim_id",
        "claim_type",
        "statement_from_date",
        "statement_to_date",
        "received_at",
        "other_payer_paid_cents",
        "cob_role",
        "pricing_variant",
        "total_billed_cents",
        "total_allowed_cents",
        "total_deductible_applied_cents",
        "total_member_liability_cents",
        "total_plan_paid_cents",
        "pend_reason_code",
        "deny_reason_code",
        "adjudication_pass",
        "last_adjudicated_by_user_id",
        "status",
        "payment_status",
    ),
    "claim_line": (
        "claim_id",
        "line_number",
        "procedure_code",
        "modifier_code",
        "units",
        "billed_amount_cents",
        "service_date",
        "allowed_amount_cents",
        "deductible_applied_cents",
        "copay_cents",
        "coinsurance_cents",
        "member_liability_cents",
        "plan_paid_cents",
        "authorization_id",
        "bundled_into_line_number",
        "edit_reason_code",
        "line_status",
    ),
    "remittance_advice": (
        "claim_id",
        "remit_number",
        "total_allowed_cents",
        "total_plan_paid_cents",
        "total_member_liability_cents",
        "total_other_payer_paid_cents",
        "issued_at",
        "status",
    ),
    "adjudication_event": (
        "claim_id",
        "pass_number",
        "event_type",
        "from_status",
        "to_status",
        "reason_code",
        "actor_role",
        "actor_user_id",
        "occurred_at",
    ),
}


def dump(kind, row):
    out = {"id": row["id"], "created_at": row["created_at"]}
    if kind != "adjudication_event":
        out["updated_at"] = row["updated_at"]
        out["version"] = row["version"]
    for field in FIELDS[kind]:
        out[field] = row.get(field)
    return out


def dump_many(kind, rows):
    return [dump(kind, row) for row in rows]
