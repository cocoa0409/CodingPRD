"""Entity assertions and domain invariant checkers for the Public Funds Collateral API."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import HAIRCUT_BPS_BY_TYPE


# ─── Shared helpers ───────────────────────────────────


def assert_identity_stamps(data: dict):
    """`id` is a UUID and `created_at` is an ISO 8601 UTC timestamp (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"


def assert_mutable_audit_stamps(data: dict):
    """A mutable resource also carries `updated_at` and an integer `version` (PRD §2.4)."""
    assert_identity_stamps(data)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_cents(data: dict, *field_names):
    """Every `_cents` figure is an integer number of whole cents (PRD §2.5)."""
    for name in field_names:
        assert isinstance(
            data.get(name), int
        ), f"{name} must be an integer number of cents, got {data.get(name)!r}"


def assert_bps(data: dict, *field_names):
    """Every `_bps` figure is an integer number of basis points (PRD §2.5)."""
    for name in field_names:
        assert isinstance(
            data.get(name), int
        ), f"{name} must be an integer number of basis points, got {data.get(name)!r}"


# ─── Per-entity assertions ────────────────────────────


def assert_custodian(data: dict):
    assert_mutable_audit_stamps(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["custodian_type"] in ["FEDERAL_RESERVE", "FHLB", "TRUST_BANK"]
    assert isinstance(data["tri_party_capable"], bool)
    assert_bps(data, "concentration_limit_bps")
    assert 1000 <= data["concentration_limit_bps"] <= 10000
    assert data["approval_status"] in ["PENDING_APPROVAL", "APPROVED", "REVOKED"]


def assert_pooled_program(data: dict):
    assert_mutable_audit_stamps(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["administrator_state"], str)
    assert_bps(data, "minimum_pool_pct_bps")
    assert_cents(
        data,
        "aggregate_required_collateral_cents",
        "aggregate_collateral_value_cents",
        "unallocated_collateral_cents",
    )
    assert isinstance(data["participant_account_count"], int)
    assert data["pool_posture"] in ["ADEQUATE", "SHORTFALL"]


def assert_public_unit(data: dict):
    assert_mutable_audit_stamps(data)
    assert data["unit_type"] in [
        "SCHOOL_DISTRICT",
        "COUNTY",
        "MUNICIPALITY",
        "STATE_AGENCY",
    ]
    assert data["collateral_program_preference"] in ["DEDICATED", "POOLED"]
    assert data["reporting_frequency"] in ["DAILY", "MONTHLY"]
    assert_cents(
        data,
        "statutory_max_deposit_cents",
        "total_deposit_balance_cents",
        "total_uninsured_cents",
    )
    assert data["exposure_status"] in ["NORMAL", "WATCH", "ESCALATED"]


def assert_depository(data: dict):
    assert_mutable_audit_stamps(data)
    assert data["charter_type"] in ["STATE_CHARTERED", "NATIONAL"]
    assert_bps(data, "capital_ratio_bps")
    assert data["capital_tier"] in [
        "WELL_CAPITALIZED",
        "ADEQUATELY_CAPITALIZED",
        "UNDERCAPITALIZED",
    ]
    assert data["insurance_determination_basis"] in [
        "AGGREGATED_BY_UNIT",
        "PER_ACCOUNT",
    ]
    assert data["approval_status"] in [
        "DRAFT",
        "UNDER_REVIEW",
        "APPROVED",
        "DENIED",
        "SUSPENDED",
    ]
    assert data["collateral_posture"] in ["COMPLIANT", "MARGIN_DEFICIENT", "FROZEN"]
    assert data["risk_grade"] in ["A", "B", "C", "D"]
    assert_bps(data, "risk_score_bps")
    assert isinstance(data["consecutive_deficiency_runs"], int)
    assert isinstance(data["open_margin_call_count"], int)
    assert_cents(
        data,
        "approved_pledge_capacity_cents",
        "total_required_collateral_cents",
        "total_pledged_collateral_value_cents",
        "total_pledged_par_cents",
    )
    assert isinstance(data["mtm_run_index"], int)


def assert_capital_tier_matches_ratio(data: dict):
    """`capital_tier` follows `capital_ratio_bps` on inclusive lower bounds (PRD §3.1)."""
    ratio = data["capital_ratio_bps"]
    if ratio >= 1000:
        expected = "WELL_CAPITALIZED"
    elif ratio >= 800:
        expected = "ADEQUATELY_CAPITALIZED"
    else:
        expected = "UNDERCAPITALIZED"
    assert data["capital_tier"] == expected, (
        f"capital_ratio_bps {ratio} must derive capital_tier {expected}, "
        f"got {data['capital_tier']}"
    )


def assert_qualification_review(data: dict):
    assert_mutable_audit_stamps(data)
    assert is_valid_uuid(data["depository_id"])
    assert_cents(data, "requested_pledge_capacity_cents")
    assert data["status"] in [
        "SUBMITTED",
        "ATTESTED",
        "UNDER_REVIEW",
        "RETURNED_FOR_INFO",
        "APPROVED",
        "DENIED",
    ]
    assert isinstance(data["round_count"], int) and data["round_count"] >= 1


def assert_deposit_account(data: dict):
    assert_mutable_audit_stamps(data)
    assert is_valid_uuid(data["depository_id"])
    assert is_valid_uuid(data["public_unit_id"])
    assert data["deposit_class"] in ["DEMAND", "TIME_AND_SAVINGS"]
    assert data["pledging_mode"] in ["DEDICATED", "POOLED"]
    assert isinstance(data["group_sequence"], int) and data["group_sequence"] >= 1
    assert data["funding_status"] in ["PENDING_FUNDING", "FUNDED", "RESTRICTED"]
    assert data["collateral_status"] in ["UNSECURED", "SECURED", "DEFICIENT"]
    assert_cents(
        data,
        "ledger_balance_cents",
        "insured_amount_cents",
        "uninsured_amount_cents",
        "required_collateral_cents",
        "assigned_collateral_value_cents",
        "pooled_allocated_collateral_cents",
    )
    assert_bps(data, "required_collateral_pct_bps", "coverage_ratio_bps")
    assert data["pool_priority_rank"] in [1, 2, 3, 4]


def assert_insured_plus_uninsured_reconciles(data: dict):
    """The two parts sum back to the ledger balance exactly (PRD §3.2)."""
    assert (
        data["insured_amount_cents"] + data["uninsured_amount_cents"]
        == data["ledger_balance_cents"]
    ), (
        f"insured {data['insured_amount_cents']} + uninsured "
        f"{data['uninsured_amount_cents']} must equal ledger balance "
        f"{data['ledger_balance_cents']}"
    )


def assert_coverage_ratio_floored(data: dict):
    """`coverage_ratio_bps` is the floored ratio, or 10000 with no requirement (PRD §3.2)."""
    required = data["required_collateral_cents"]
    if required == 0:
        expected = 10000
    else:
        expected = (data["assigned_collateral_value_cents"] * 10000) // required
    assert data["coverage_ratio_bps"] == expected, (
        f"coverage_ratio_bps must be {expected}, got {data['coverage_ratio_bps']}"
    )


def assert_pledge_agreement(data: dict):
    assert_mutable_audit_stamps(data)
    assert is_valid_uuid(data["depository_id"])
    assert is_valid_uuid(data["custodian_id"])
    assert data["beneficiary_type"] in ["DEPOSIT_ACCOUNT", "POOLED_PROGRAM"]
    assert isinstance(data["agreement_number"], str)
    assert data["status"] in [
        "DRAFT",
        "PENDING_SIGNATURES",
        "AMENDMENT_REQUESTED",
        "EXECUTED",
        "TERMINATED",
    ]
    assert isinstance(data["signature_count"], int) and 0 <= data["signature_count"] <= 3
    assert isinstance(data["amendment_round"], int)
    assert_cents(data, "total_pledged_par_cents", "total_collateral_value_cents")
    assert isinstance(data["active_allocation_count"], int)


def assert_signature_count_matches_stamps(data: dict):
    """`signature_count` is the number of non-null party stamps (PRD §3.3)."""
    stamps = [
        data.get("depository_signed_at"),
        data.get("public_unit_signed_at"),
        data.get("custodian_signed_at"),
    ]
    expected = len([stamp for stamp in stamps if stamp])
    assert data["signature_count"] == expected, (
        f"signature_count must be {expected}, got {data['signature_count']}"
    )


def assert_collateral_asset(data: dict):
    assert_mutable_audit_stamps(data)
    assert is_valid_uuid(data["depository_id"])
    assert is_valid_uuid(data["custodian_id"])
    assert isinstance(data["cusip"], str)
    assert data["asset_type"] in list(HAIRCUT_BPS_BY_TYPE)
    assert_cents(
        data,
        "par_value_cents",
        "market_value_cents",
        "collateral_value_cents",
        "pledged_par_cents",
        "available_par_cents",
    )
    assert_bps(data, "market_price_bps", "haircut_bps")
    assert is_iso8601_timestamp(data["priced_at"])
    assert data["eligibility_status"] in ["ELIGIBLE", "INELIGIBLE"]
    assert data["pledge_status"] in ["UNPLEDGED", "PARTIALLY_PLEDGED", "FULLY_PLEDGED"]


def assert_haircut_matches_asset_type(data: dict):
    """`haircut_bps` is derived from the asset type (PRD §3.4)."""
    expected = HAIRCUT_BPS_BY_TYPE[data["asset_type"]]
    assert data["haircut_bps"] == expected, (
        f"{data['asset_type']} must carry haircut_bps {expected}, got {data['haircut_bps']}"
    )


def assert_asset_par_conservation(data: dict):
    """`pledged_par_cents` plus `available_par_cents` is the asset's par (PRD §3.4)."""
    assert (
        data["pledged_par_cents"] + data["available_par_cents"] == data["par_value_cents"]
    ), (
        f"pledged {data['pledged_par_cents']} + available {data['available_par_cents']} "
        f"must equal par {data['par_value_cents']}"
    )
    assert data["available_par_cents"] >= 0, "available_par_cents can never go negative"


def assert_pledge_status_matches_pledged_par(data: dict):
    """`pledge_status` follows `pledged_par_cents` (PRD §3.4)."""
    pledged, par = data["pledged_par_cents"], data["par_value_cents"]
    if pledged == 0:
        expected = "UNPLEDGED"
    elif pledged == par:
        expected = "FULLY_PLEDGED"
    else:
        expected = "PARTIALLY_PLEDGED"
    assert data["pledge_status"] == expected, (
        f"pledge_status must be {expected} at pledged_par_cents {pledged}, "
        f"got {data['pledge_status']}"
    )


def assert_pledge_allocation(data: dict):
    assert_mutable_audit_stamps(data)
    assert is_valid_uuid(data["pledge_agreement_id"])
    assert is_valid_uuid(data["collateral_asset_id"])
    assert_cents(data, "allocated_par_cents", "allocated_collateral_value_cents")
    assert is_iso8601_timestamp(data["effective_from"])
    assert data["status"] in ["ACTIVE", "RELEASED", "SUBSTITUTED"]
    if data.get("release_reason") is not None:
        assert data["release_reason"] in [
            "OFFICER_RELEASE",
            "AGREEMENT_TERMINATED",
            "ASSET_INELIGIBLE",
            "SUBSTITUTION_SETTLED",
        ]


def assert_substitution_request(data: dict):
    assert_mutable_audit_stamps(data)
    assert is_valid_uuid(data["pledge_agreement_id"])
    assert is_valid_uuid(data["outgoing_allocation_id"])
    assert is_valid_uuid(data["incoming_asset_id"])
    assert_cents(data, "incoming_par_cents")
    assert data["status"] in [
        "SUBMITTED",
        "COMPLIANCE_APPROVED",
        "CUSTODIAN_ACKED",
        "READY_TO_SETTLE",
        "SETTLED",
        "REJECTED",
        "WITHDRAWN",
    ]


def assert_mtm_run(data: dict):
    """A run is immutable: it carries `id` and `created_at` but no `updated_at`
    and no `version` (PRD §2.4)."""
    assert_identity_stamps(data)
    assert "updated_at" not in data, "a mark-to-market run has no updated_at field"
    assert "version" not in data, "a mark-to-market run has no version field"
    assert data["basis"] in ["SUPERVISORY", "INTERNAL"]
    assert data["outcome"] in ["SUFFICIENT", "DEFICIENT"]
    assert isinstance(data["run_index"], int) and data["run_index"] >= 1
    assert_cents(
        data,
        "total_required_collateral_cents",
        "total_collateral_value_cents",
        "deficiency_cents",
    )
    assert_bps(data, "deficiency_ratio_bps", "deficiency_surcharge_bps_applied")
    assert data["risk_grade_assigned"] in ["A", "B", "C", "D"]


def assert_margin_call(data: dict):
    assert_mutable_audit_stamps(data)
    assert is_valid_uuid(data["depository_id"])
    assert is_valid_uuid(data["mtm_run_id"])
    assert_cents(data, "required_cure_cents", "cured_cents", "outstanding_cents")
    assert data["status"] in [
        "ISSUED",
        "PARTIALLY_CURED",
        "ESCALATED",
        "CURED",
        "BREACHED",
    ]
    assert is_iso8601_timestamp(data["cure_deadline_at"])
    assert is_iso8601_timestamp(data["breach_deadline_at"])


def assert_outstanding_is_required_less_cured(data: dict):
    """`outstanding_cents` is `required_cure_cents` less `cured_cents`, floored at zero
    (PRD §3.8)."""
    expected = max(0, data["required_cure_cents"] - data["cured_cents"])
    assert data["outstanding_cents"] == expected, (
        f"outstanding_cents must be {expected}, got {data['outstanding_cents']}"
    )


def assert_safekeeping_receipt(data: dict):
    assert_mutable_audit_stamps(data)
    assert is_valid_uuid(data["pledge_agreement_id"])
    assert isinstance(data["receipt_number"], str)
    assert_cents(
        data,
        "reported_par_cents",
        "ledger_par_cents",
        "discrepancy_par_cents",
    )
    assert isinstance(data["reported_asset_count"], int)
    assert isinstance(data["ledger_asset_count"], int)
    assert data["confirmation_status"] in ["ISSUED", "CONFIRMED", "EXCEPTION"]
    assert is_iso8601_timestamp(data["as_of"])


def assert_discrepancy_is_signed(data: dict):
    """`discrepancy_par_cents` is `reported_par_cents` less `ledger_par_cents` (PRD §3.9)."""
    expected = data["reported_par_cents"] - data["ledger_par_cents"]
    assert data["discrepancy_par_cents"] == expected, (
        f"discrepancy_par_cents must be the signed {expected}, "
        f"got {data['discrepancy_par_cents']}"
    )


def assert_runoff_forecast(data: dict):
    assert_mutable_audit_stamps(data)
    assert is_valid_uuid(data["deposit_account_id"])
    assert data["cycle_label"] in ["TAX_COLLECTION", "DISBURSEMENT", "DEBT_SERVICE"]
    assert data["basis"] in ["PEAK_WINDOW", "PERIOD_END"]
    assert_cents(
        data,
        "projected_peak_balance_cents",
        "projected_required_collateral_cents",
        "unpledged_capacity_cents",
        "pledge_capacity_gap_cents",
    )
    assert data["status"] in ["OPEN", "STALE", "SUPERSEDED"]
    assert isinstance(data["requires_reforecast"], bool)


def assert_coverage_report(data: dict):
    """The coverage report returns exactly the ten values named by PRD §3.2."""
    expected_keys = {
        "insured_amount_cents",
        "uninsured_amount_cents",
        "required_collateral_pct_bps",
        "required_collateral_cents",
        "assigned_collateral_value_cents",
        "coverage_ratio_bps",
        "collateral_status",
        "pledging_mode",
        "insurance_determination_basis",
        "report_as_of",
    }
    missing = expected_keys - set(data)
    assert not missing, f"coverage report is missing {sorted(missing)}"
    assert is_iso8601_timestamp(data["report_as_of"])


def assert_envelope_meta(body: dict):
    """`api_request_id` starts with `req_` and the timestamp is ISO 8601 (PRD §2.2)."""
    meta = body["meta"]
    assert meta["api_request_id"].startswith(
        "req_"
    ), f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    assert is_iso8601_timestamp(meta["api_request_timestamp"])
