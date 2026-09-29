"""Shape and invariant assertions for the contract-renewal API."""
from __future__ import annotations

from typing import Any

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

COMMON_FIELDS = ("id", "created_at", "updated_at", "version")


def assert_common_fields(data: dict[str, Any], label: str = "resource") -> None:
    """Every resource carries a bare-UUID `id`, both timestamps and an integer `version`."""
    for field in COMMON_FIELDS:
        assert field in data, f"{label} is missing common field {field}: {data}"
    assert is_valid_uuid(data["id"]), f"{label} id is not a bare UUID: {data['id']}"
    assert not str(data["id"]).count("_"), f"{label} id carries a type prefix: {data['id']}"
    assert is_iso8601_timestamp(
        data["created_at"]
    ), f"{label} created_at is not ISO 8601: {data['created_at']}"
    assert is_iso8601_timestamp(
        data["updated_at"]
    ), f"{label} updated_at is not ISO 8601: {data['updated_at']}"
    assert isinstance(data["version"], int), f"{label} version is not an integer: {data}"
    assert data["version"] >= 1, f"{label} version must start at 1, got {data['version']}"


def _assert_fields(data: dict[str, Any], fields: tuple[str, ...], label: str) -> None:
    assert_common_fields(data, label)
    for field in fields:
        assert field in data, f"{label} is missing field {field}: {sorted(data)}"


def assert_owner(data: dict[str, Any]) -> None:
    _assert_fields(
        data,
        (
            "legal_name",
            "tin",
            "contact_email",
            "portfolio_property_count",
            "compliance_flag",
        ),
        "owner",
    )
    assert data["compliance_flag"] in ("OK", "REVIEW_REQUIRED"), (
        f"compliance_flag has exactly two values, got {data['compliance_flag']}"
    )


def assert_property(data: dict[str, Any]) -> None:
    _assert_fields(
        data,
        (
            "owner_id",
            "project_name",
            "state_code",
            "total_units",
            "assisted_unit_count",
            "published_fmr_cents",
            "baseline_utility_allowance_cents",
            "current_utility_allowance_cents",
            "has_fha_insured_mortgage",
            "units_under_hap_count",
            "enhanced_voucher_unit_count",
            "released_unit_count",
            "last_applied_ua_effective_date",
        ),
        "property",
    )
    assert_unit_invariant(data)


def assert_hap_contract(data: dict[str, Any]) -> None:
    _assert_fields(
        data,
        (
            "property_id",
            "contract_type",
            "expiration_date",
            "term_months",
            "contract_rent_per_unit_cents",
            "monthly_debt_service_per_unit_cents",
            "operating_expense_per_unit_cents",
            "reserve_deposit_per_unit_cents",
            "authorized_hap_budget_cents",
            "paid_hap_total_cents",
            "paid_claims_total_cents",
            "hap_ledger_balance_cents",
            "lifecycle_status",
            "renewed_rent_per_unit_cents",
            "renewed_expiration_date",
            "renewed_option",
        ),
        "hap_contract",
    )


def assert_renewal_case(data: dict[str, Any]) -> None:
    _assert_fields(
        data,
        (
            "contract_id",
            "rent_track_status",
            "notice_track_status",
            "renewal_option",
            "adjustment_method",
            "opened_on_date",
            "days_to_expiration_at_open",
            "rcs_required",
            "comparable_market_rent_cents",
            "ocaf_rent_per_unit_cents",
            "budget_rent_per_unit_cents",
            "approved_rent_per_unit_cents",
            "challenge_reviewer_user_id",
            "rents_approver_user_id",
            "opt_out_notice_id",
        ),
        "renewal_case",
    )


def assert_study(data: dict[str, Any]) -> None:
    _assert_fields(
        data,
        (
            "renewal_case_id",
            "supersedes_study_id",
            "state",
            "appraiser_name",
            "challenge_round",
            "estimated_market_rent_cents",
            "accepted_comparable_count",
            "last_challenge_reason",
            "submitted_on_date",
        ),
        "rent_comparability_study",
    )


def assert_comparable(data: dict[str, Any]) -> None:
    _assert_fields(
        data,
        (
            "study_id",
            "address_label",
            "raw_rent_cents",
            "adjustment_total_cents",
            "utility_adjustment_cents",
            "weight",
            "adjusted_rent_cents",
            "status",
        ),
        "comparable",
    )
    assert data["adjusted_rent_cents"] % 100 == 0, (
        "adjusted_rent_cents rounds to the nearest whole dollar, so it must be a multiple "
        f"of 100 cents, got {data['adjusted_rent_cents']}"
    )


def assert_utility_allowance_analysis(data: dict[str, Any]) -> None:
    _assert_fields(
        data,
        (
            "property_id",
            "method",
            "baseline_allowance_cents",
            "utility_rate_change_pct",
            "engineering_estimate_cents",
            "proposed_allowance_cents",
            "change_pct",
            "requires_field_office_approval",
            "effective_date",
            "state",
            "approver_user_id",
            "applied_on_date",
            "recertified_tenant_count",
        ),
        "utility_allowance_analysis",
    )


def assert_tenant_household(data: dict[str, Any]) -> None:
    _assert_fields(
        data,
        (
            "property_id",
            "unit_number",
            "household_name",
            "annual_adjusted_income_cents",
            "annual_gross_income_cents",
            "family_size",
            "status",
            "move_out_date",
            "current_ttp_cents",
            "current_hap_cents",
            "ev_eligible",
        ),
        "tenant_household",
    )


def assert_tenant_certification(data: dict[str, Any]) -> None:
    _assert_fields(
        data,
        (
            "tenant_id",
            "cert_type",
            "effective_date",
            "utility_allowance_cents",
            "contract_rent_per_unit_cents",
            "gross_rent_cents",
            "ttp_cents",
            "tenant_rent_cents",
            "utility_reimbursement_cents",
            "hap_cents",
            "status",
        ),
        "tenant_certification",
    )
    assert_certification_money_consistency(data)


def assert_tenant_notice(data: dict[str, Any]) -> None:
    _assert_fields(
        data,
        (
            "renewal_case_id",
            "tenant_id",
            "notice_type",
            "issued_date",
            "effective_date",
            "lead_days",
            "required_lead_days",
            "status",
            "rescind_reason",
        ),
        "tenant_notice",
    )


def assert_restructuring_determination(data: dict[str, Any]) -> None:
    _assert_fields(
        data,
        (
            "renewal_case_id",
            "determination_state",
            "market_rent_per_unit_cents",
            "current_rent_per_unit_cents",
            "fmr_per_unit_cents",
            "eligibility_reason_code",
            "post_restructure_rent_per_unit_cents",
            "approved_by_user_id",
        ),
        "restructuring_determination",
    )


def assert_enhanced_voucher(data: dict[str, Any]) -> None:
    _assert_fields(
        data,
        (
            "tenant_id",
            "renewal_case_id",
            "state",
            "payment_standard_cents",
            "ttp_snapshot_cents",
            "entitlement_cents",
            "issuing_pha_user_id",
            "issued_on_date",
        ),
        "enhanced_voucher",
    )
    assert data["entitlement_cents"] >= 0, (
        f"entitlement_cents is floored at zero, got {data['entitlement_cents']}"
    )


def assert_voucher_submission(data: dict[str, Any]) -> None:
    _assert_fields(
        data,
        (
            "contract_id",
            "period_month",
            "state",
            "requested_hap_cents",
            "included_certification_count",
            "paid_amount_cents",
            "paid_on_date",
            "reversal_reason",
        ),
        "voucher_submission",
    )


def assert_special_claim(data: dict[str, Any]) -> None:
    _assert_fields(
        data,
        (
            "contract_id",
            "claim_type",
            "unit_number",
            "claim_period_month",
            "vacancy_days_claimed",
            "valuation_variant",
            "computed_amount_cents",
            "state",
            "decision_reason",
            "paid_amount_cents",
        ),
        "special_claim",
    )


def assert_reconciliation(data: dict[str, Any]) -> None:
    for field in (
        "requested_total_cents",
        "paid_hap_total_cents",
        "reversed_total_cents",
        "paid_claims_total_cents",
        "authorized_hap_budget_cents",
        "variance_cents",
        "hap_ledger_balance_cents",
        "paid_period_count",
    ):
        assert field in data, f"reconciliation is missing {field}: {sorted(data)}"


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------
def assert_unit_invariant(prop: dict[str, Any]) -> None:
    """`units_under_hap_count` + `enhanced_voucher_unit_count` + `released_unit_count`
    must equal `assisted_unit_count` at all times."""
    total = (
        prop["units_under_hap_count"]
        + prop["enhanced_voucher_unit_count"]
        + prop["released_unit_count"]
    )
    assert total == prop["assisted_unit_count"], (
        "unit invariant broken: "
        f"{prop['units_under_hap_count']} under HAP + "
        f"{prop['enhanced_voucher_unit_count']} enhanced-voucher + "
        f"{prop['released_unit_count']} released == {total}, "
        f"but assisted_unit_count is {prop['assisted_unit_count']}"
    )


def assert_money_invariant(contract: dict[str, Any]) -> None:
    """`hap_ledger_balance_cents` plus the paid voucher total plus the paid claim total
    must equal `authorized_hap_budget_cents`."""
    total = (
        contract["hap_ledger_balance_cents"]
        + contract["paid_hap_total_cents"]
        + contract["paid_claims_total_cents"]
    )
    assert total == contract["authorized_hap_budget_cents"], (
        "money invariant broken: "
        f"ledger {contract['hap_ledger_balance_cents']} + paid HAP "
        f"{contract['paid_hap_total_cents']} + paid claims "
        f"{contract['paid_claims_total_cents']} == {total}, but authorization is "
        f"{contract['authorized_hap_budget_cents']}"
    )


def assert_certification_money_consistency(cert: dict[str, Any]) -> None:
    """The four derived money fields follow from `ttp_cents` and the two snapshots."""
    assert cert["gross_rent_cents"] == (
        cert["contract_rent_per_unit_cents"] + cert["utility_allowance_cents"]
    ), (
        "gross_rent_cents must be contract_rent_per_unit_cents plus "
        f"utility_allowance_cents, got {cert['gross_rent_cents']}"
    )
    assert cert["tenant_rent_cents"] == max(
        0, cert["ttp_cents"] - cert["utility_allowance_cents"]
    ), (
        "tenant_rent_cents must be ttp_cents less the utility allowance floored at zero, "
        f"got {cert['tenant_rent_cents']}"
    )
    assert cert["utility_reimbursement_cents"] == max(
        0, cert["utility_allowance_cents"] - cert["ttp_cents"]
    ), (
        "utility_reimbursement_cents must be the utility allowance less ttp_cents floored "
        f"at zero, got {cert['utility_reimbursement_cents']}"
    )
    assert cert["hap_cents"] == max(0, cert["gross_rent_cents"] - cert["ttp_cents"]), (
        "hap_cents must be gross_rent_cents less ttp_cents floored at zero, got "
        f"{cert['hap_cents']}"
    )


def assert_reconciliation_matches_contract(
    projection: dict[str, Any], contract: dict[str, Any]
) -> None:
    """The projection's ledger balance must always equal the contract's stored balance."""
    assert projection["hap_ledger_balance_cents"] == contract["hap_ledger_balance_cents"], (
        "reconciliation ledger balance "
        f"{projection['hap_ledger_balance_cents']} diverges from the stored "
        f"{contract['hap_ledger_balance_cents']}"
    )
    assert projection["variance_cents"] == (
        projection["requested_total_cents"] - projection["paid_hap_total_cents"]
    ), "variance_cents must be the requested total less the paid total"


def assert_pagination_meta(
    meta: dict[str, Any], limit: int, offset: int, total_count: int, has_more: bool
) -> None:
    assert meta["limit"] == limit, f"meta.limit should echo {limit}, got {meta.get('limit')}"
    assert meta["offset"] == offset, (
        f"meta.offset should echo {offset}, got {meta.get('offset')}"
    )
    assert meta["total_count"] == total_count, (
        f"meta.total_count should be {total_count}, got {meta.get('total_count')}"
    )
    assert meta["has_more"] is has_more, (
        f"meta.has_more should be {has_more}, got {meta.get('has_more')}"
    )
