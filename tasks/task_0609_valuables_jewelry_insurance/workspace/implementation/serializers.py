"""Convert internal records into API output shapes.

Internal records keep a few private fields (prefixed with '_') that must not be
exposed. Each serializer whitelists the public fields per entity (SCAFFOLD §1.1).
"""

_COMMON = ["id", "created_at", "updated_at", "version"]


def _pick(record, fields):
    return {k: record.get(k) for k in fields}


def policyholder(r):
    return _pick(r, _COMMON + ["email", "full_name", "residence_zip", "status"])


def risk_zone(r):
    # RiskZone is immutable: only id + created_at (PRD §2.4), no updated_at/version.
    return _pick(r, ["id", "created_at", "zip_prefix", "risk_band",
                     "rate_per_thousand_cents", "catastrophe_loaded"])


def repair_shop(r):
    return _pick(r, _COMMON + ["name", "service_zip", "in_network", "status"])


def policy(r):
    return _pick(r, _COMMON + [
        "policyholder_id", "coverage_type", "valuation_basis", "deductible_option",
        "worldwide_coverage", "listed_perils", "inflation_guard_mode",
        "inflation_guard_pct", "deductible_cents", "total_insured_value_cents",
        "annual_premium_cents", "coverage_status", "billing_status",
        "past_due_since", "bound_at_iso",
    ])


def scheduled_item(r):
    return _pick(r, _COMMON + [
        "policy_id", "description", "category", "location_zip",
        "scheduled_value_cents", "current_value_cents", "revaluation_epoch",
        "appraisal_id", "item_status",
    ])


def appraisal(r):
    return _pick(r, _COMMON + [
        "policyholder_id", "appraiser_id", "appraised_value_cents",
        "effective_date_iso", "valid_months", "status",
    ])


def endorsement(r):
    return _pick(r, _COMMON + [
        "policy_id", "endorsement_type", "target_item_id",
        "new_deductible_option", "premium_delta_cents", "status",
    ])


def claim(r):
    return _pick(r, _COMMON + [
        "policy_id", "scheduled_item_id", "peril", "loss_type", "loss_zip",
        "occurred_outside_country", "claimed_amount_cents", "settlement_cents",
        "deductible_applied_cents", "info_request_count", "status",
    ])


def repair_order(r):
    return _pick(r, _COMMON + [
        "claim_id", "repair_shop_id", "authorized_amount_cents",
        "actual_cost_cents", "status",
    ])


def premium_payment(r):
    return _pick(r, _COMMON + ["policy_id", "amount_cents", "status"])
