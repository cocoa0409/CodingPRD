"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PLAN_NAME": "Acme Health Plan",
    "SPONSOR_TAX_ID": "12-3456789",
    "SPECIFIC_DEDUCTIBLE_CENTS": 10_000_000,
    "AGGREGATE_DEDUCTIBLE_CENTS": 1_000_000_000,
    "FILING_DEADLINE_DAYS": 90,
    "NOTICE_THRESHOLD_PCT": 0.50,
    "RUN_IN_DAYS": 0,
    "RUN_OUT_DAYS": 0,
    "POLICY_YEAR_START": "2026-01-01T00:00:00Z",
    "POLICY_YEAR_END": "2027-01-01T00:00:00Z",
    "DATE_OF_BIRTH": "1980-01-01",
    "COVERAGE_START": "2025-01-01T00:00:00Z",
    "SERVICE_DATE": "2026-02-01T00:00:00Z",
    "PAID_DATE": "2026-02-02T00:00:00Z",
    "BILLED_AMOUNT_CENTS": 15_000_000,
    "CLAIM_TYPE": "MEDICAL",
    "RECEIVED_AT": "2026-06-01T00:00:00Z",
    "NEXT_YEAR_SPECIFIC_DEDUCTIBLE_CENTS": 10_000_000,
    "AUDIT_REASON": "eligibility review",
}


def create_plan_payload(**overrides) -> dict:
    defaults = {
        "plan_name": DEFAULTS["PLAN_NAME"],
        "sponsor_tax_id": DEFAULTS["SPONSOR_TAX_ID"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(plan_id, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "policy_year_start": DEFAULTS["POLICY_YEAR_START"],
        "policy_year_end": DEFAULTS["POLICY_YEAR_END"],
        "contract_basis": "POLICY_YEAR",
        "specific_deductible_cents": DEFAULTS["SPECIFIC_DEDUCTIBLE_CENTS"],
        "aggregate_deductible_cents": DEFAULTS["AGGREGATE_DEDUCTIBLE_CENTS"],
        "filing_deadline_days": DEFAULTS["FILING_DEADLINE_DAYS"],
        "notice_threshold_pct": DEFAULTS["NOTICE_THRESHOLD_PCT"],
        "run_in_days": DEFAULTS["RUN_IN_DAYS"],
        "run_out_days": DEFAULTS["RUN_OUT_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def renew_contract_payload(new_policy_year_start, new_policy_year_end,
                           **overrides) -> dict:
    defaults = {
        "new_policy_year_start": new_policy_year_start,
        "new_policy_year_end": new_policy_year_end,
        "specific_deductible_cents": DEFAULTS["SPECIFIC_DEDUCTIBLE_CENTS"],
        "aggregate_deductible_cents": DEFAULTS["AGGREGATE_DEDUCTIBLE_CENTS"],
        "filing_deadline_days": DEFAULTS["FILING_DEADLINE_DAYS"],
        "notice_threshold_pct": DEFAULTS["NOTICE_THRESHOLD_PCT"],
        "run_in_days": DEFAULTS["RUN_IN_DAYS"],
        "run_out_days": DEFAULTS["RUN_OUT_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(plan_id, member_external_id="M001", **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "member_external_id": member_external_id,
        "date_of_birth": DEFAULTS["DATE_OF_BIRTH"],
        "coverage_start": DEFAULTS["COVERAGE_START"],
    }
    defaults.update(overrides)
    return defaults


def terminate_member_payload(coverage_end, **overrides) -> dict:
    defaults = {"coverage_end": coverage_end}
    defaults.update(overrides)
    return defaults


def create_lasered_term_payload(contract_id, member_id,
                                lasered_specific_deductible_cents,
                                effective_from, effective_to,
                                expected_contract_version, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "member_id": member_id,
        "lasered_specific_deductible_cents": lasered_specific_deductible_cents,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "expected_contract_version": expected_contract_version,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(plan_id, member_id, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "member_id": member_id,
        "service_date": DEFAULTS["SERVICE_DATE"],
        "billed_amount_cents": DEFAULTS["BILLED_AMOUNT_CENTS"],
        "claim_type": DEFAULTS["CLAIM_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def adjudicate_claim_payload(allowed_amount_cents, **overrides) -> dict:
    defaults = {"allowed_amount_cents": allowed_amount_cents}
    defaults.update(overrides)
    return defaults


def pay_claim_payload(paid_amount_cents, paid_date, **overrides) -> dict:
    defaults = {
        "paid_amount_cents": paid_amount_cents,
        "paid_date": paid_date,
    }
    defaults.update(overrides)
    return defaults


def create_filing_payload(contract_id, filing_scope, claim_ids,
                          expected_contract_version, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "filing_scope": filing_scope,
        "claim_ids": list(claim_ids),
        "expected_contract_version": expected_contract_version,
    }
    defaults.update(overrides)
    return defaults


def dispute_filing_payload(disputed_line_item_ids, **overrides) -> dict:
    defaults = {"disputed_line_item_ids": list(disputed_line_item_ids)}
    defaults.update(overrides)
    return defaults


def approve_filing_payload(approved_amount_cents, **overrides) -> dict:
    defaults = {"approved_amount_cents": approved_amount_cents}
    defaults.update(overrides)
    return defaults


def create_reimbursement_payload(filing_id, received_amount_cents,
                                 **overrides) -> dict:
    defaults = {
        "filing_id": filing_id,
        "received_amount_cents": received_amount_cents,
        "received_at": DEFAULTS["RECEIVED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_forecast_payload(plan_id, forecast_basis="PURE_EXPERIENCE",
                            **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "forecast_basis": forecast_basis,
        "next_year_specific_deductible_cents":
            DEFAULTS["NEXT_YEAR_SPECIFIC_DEDUCTIBLE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(filing_id, **overrides) -> dict:
    defaults = {
        "filing_id": filing_id,
        "reason": DEFAULTS["AUDIT_REASON"],
    }
    defaults.update(overrides)
    return defaults


def resolve_audit_payload(adjustment_cents, **overrides) -> dict:
    defaults = {"adjustment_cents": adjustment_cents}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
