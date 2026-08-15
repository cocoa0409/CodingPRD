"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    """PRD §2.5: every resource carries id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_int(data, field):
    assert isinstance(data.get(field), int), f"{field} must be int, got {data.get(field)!r}"


def _assert_iso_date(data, field):
    value = data.get(field)
    assert isinstance(value, str) and len(value) == 10, (
        f"{field} must be an ISO date string, got {value!r}"
    )


def assert_borrower(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["sector"] in [
        "INDUSTRIAL", "ENERGY", "REAL_ESTATE", "HEALTHCARE",
        "TECHNOLOGY", "FINANCIAL", "OTHER",
    ]
    assert data["risk_rating"] in [
        "INVESTMENT_GRADE", "CROSSOVER", "SPECULATIVE", "DISTRESSED",
    ]
    assert data["status"] in ["ACTIVE", "DELINQUENT", "INSOLVENT"]


def assert_facility(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["borrower_id"])
    assert isinstance(data["facility_name"], str) and data["facility_name"]
    for f in (
        "total_commitment_cents", "interest_rate_bps", "servicing_fee_bps",
        "default_interest_addon_bps", "majority_threshold_bps",
        "supermajority_threshold_bps", "quorum_bps", "voting_window_days",
        "min_transfer_cents", "committed_cents", "funded_principal_cents",
        "outstanding_principal_cents", "accrued_interest_cents",
        "undistributed_cash_cents",
    ):
        _assert_int(data, f)
    assert data["day_count_basis"] in ["ACT_360", "ACT_365", "BASIS_30_360"]
    _assert_iso_date(data, "maturity_date")
    assert data["status"] in [
        "STRUCTURING", "SYNDICATING", "COMMITTED", "FUNDING", "ACTIVE",
        "IN_DEFAULT", "ACCELERATED", "CLOSED", "TERMINATED",
    ]
    assert data["last_distribution_value_date"] is None or isinstance(
        data["last_distribution_value_date"], str
    )


def assert_participant(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["participant_name"], str) and data["participant_name"]
    for f in (
        "commitment_cents", "share_bps", "funded_cents",
        "cumulative_interest_cents", "cumulative_principal_cents",
    ):
        _assert_int(data, f)
    assert data["status"] in ["PROPOSED", "COMMITTED", "FUNDED", "EXITED", "WITHDRAWN"]


def assert_draw(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    _assert_int(data, "draw_amount_cents")
    _assert_int(data, "outstanding_cents")
    _assert_int(data, "accrued_unpaid_interest_cents")
    _assert_iso_date(data, "accrual_start_date")
    _assert_iso_date(data, "accrual_end_date")
    _assert_iso_date(data, "accrual_as_of_date")
    assert data["status"] in ["FUNDING", "SETTLED", "CANCELLED"]
    assert data["settled_at"] is None or is_iso8601_timestamp(data["settled_at"])


def assert_funding_settlement(data: dict):
    _assert_common(data)
    for f in ("draw_id", "participant_id", "facility_id"):
        assert is_valid_uuid(data[f]), f"{f} must be a UUID"
    _assert_int(data, "due_cents")
    _assert_int(data, "received_cents")
    _assert_int(data, "penalty_interest_cents")
    _assert_iso_date(data, "funding_due_date")
    assert data["status"] in [
        "PENDING", "WIRED", "CONFIRMED", "LATE_CONFIRMED", "DEFAULTED", "VOID",
    ]
    assert data["wired_at"] is None or is_iso8601_timestamp(data["wired_at"])


def assert_payment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["borrower_id"])
    assert data["payment_type"] in ["REGULAR", "PREPAYMENT"]
    _assert_int(data, "amount_cents")
    _assert_iso_date(data, "value_date")
    assert data["status"] in ["RECEIVED", "ALLOCATED", "REMITTED", "REVERSED"]
    assert data["reversed_at"] is None or is_iso8601_timestamp(data["reversed_at"])


def assert_distribution_run(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["payment_id"])
    assert is_valid_uuid(data["facility_id"])
    for f in (
        "run_number", "servicing_fee_cents", "interest_pool_cents",
        "principal_pool_cents", "agent_retained_cents",
    ):
        _assert_int(data, f)
    assert data["status"] in ["COMPUTED", "SUPERSEDED", "REMITTED", "VOIDED"]
    assert data["superseded_by_run_id"] is None or isinstance(
        data["superseded_by_run_id"], str
    )
    assert data["remitted_at"] is None or is_iso8601_timestamp(data["remitted_at"])


def assert_distribution_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["run_id"])
    assert is_valid_uuid(data["participant_id"])
    for f in ("interest_cents", "principal_cents", "total_cents"):
        _assert_int(data, f)
    assert data["total_cents"] == data["interest_cents"] + data["principal_cents"], (
        "line total must equal interest + principal"
    )
    assert data["status"] in ["PENDING", "REMITTED", "CLAWED_BACK", "VOID"]


def assert_modification_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["requested_by_borrower_id"])
    assert data["modification_type"] in [
        "RATE_CHANGE", "MATURITY_EXTENSION", "COMMITMENT_INCREASE",
        "COVENANT_WAIVER", "PRINCIPAL_WRITE_DOWN", "BORROWER_SUBSTITUTION",
    ]
    assert data["required_consent_class"] in ["MAJORITY", "SUPERMAJORITY", "UNANIMOUS"]
    _assert_int(data, "required_threshold_bps")
    _assert_int(data, "approving_commitment_cents")
    _assert_int(data, "cast_commitment_cents")
    _assert_int(data, "approving_share_bps")
    _assert_int(data, "cast_share_bps")
    assert data["status"] in [
        "DRAFT", "SOLICITING", "PASSED", "FAILED", "EXPIRED",
        "IMPLEMENTED", "WITHDRAWN",
    ]


def assert_consent_vote(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["modification_id"])
    assert is_valid_uuid(data["participant_id"])
    assert data["vote"] in ["APPROVE", "REJECT", "ABSTAIN"]
    _assert_int(data, "voted_share_bps")
    _assert_int(data, "recast_count")
    assert data["status"] in ["CAST", "RECAST", "VOIDED"]


def assert_default_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert data["default_type"] in [
        "PAYMENT_DEFAULT", "COVENANT_DEFAULT", "INSOLVENCY", "REPRESENTATION_BREACH",
    ]
    _assert_int(data, "voting_base_cents")
    _assert_int(data, "accelerate_commitment_cents")
    _assert_int(data, "waive_commitment_cents")
    _assert_int(data, "accelerate_share_bps")
    _assert_int(data, "waive_share_bps")
    assert data["status"] in ["DECLARED", "CURED", "WAIVED", "ACCELERATED"]
    assert data["resolved_at"] is None or is_iso8601_timestamp(data["resolved_at"])


def assert_default_vote(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["default_case_id"])
    assert is_valid_uuid(data["participant_id"])
    assert data["vote"] in ["ACCELERATE", "WAIVE", "REJECT"]
    _assert_int(data, "voted_share_bps")
    _assert_int(data, "recast_count")
    assert data["status"] in ["CAST", "RECAST", "VOIDED"]


def assert_financial_statement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["borrower_id"])
    assert data["statement_type"] in ["QUARTERLY", "ANNUAL_AUDITED"]
    _assert_iso_date(data, "period_end_date")
    _assert_iso_date(data, "due_date")
    assert isinstance(data["document_ref"], str) and data["document_ref"]
    assert data["status"] in ["EXPECTED", "RECEIVED", "LATE_RECEIVED", "WAIVED"]


def assert_reporting_package(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["period_label"], str) and data["period_label"]
    _assert_iso_date(data, "period_start_date")
    _assert_iso_date(data, "period_end_date")
    _assert_iso_date(data, "due_date")
    assert data["financial_statement_id"] is None or isinstance(
        data["financial_statement_id"], str
    )
    assert data["status"] in ["OPEN", "ASSEMBLED", "DELIVERED", "LATE_DELIVERED"]


def assert_transfer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["from_participant_id"])
    _assert_int(data, "transfer_amount_cents")
    _assert_iso_date(data, "settlement_date")
    assert data["status"] in [
        "PROPOSED", "AGENT_APPROVED", "SETTLED", "REJECTED", "CANCELLED",
    ]


def assert_buyback_demand(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["participant_id"])
    assert data["breach_type"] in [
        "MISREPRESENTATION", "SERVICING_BREACH", "DOCUMENTATION_DEFECT",
    ]
    assert data["status"] in [
        "DEMANDED", "ACKNOWLEDGED", "DISPUTED", "SETTLED", "RESCINDED",
    ]


def assert_waterfall_conservation(run: dict, payment_amount_cents: int):
    """PRD §3.5: fee + interest pool + principal pool == payment amount; and
    line totals plus agent retention equal the two pools."""
    fee = run["servicing_fee_cents"]
    interest = run["interest_pool_cents"]
    principal = run["principal_pool_cents"]
    assert fee + interest + principal == payment_amount_cents, (
        f"Conservation broken: {fee} + {interest} + {principal} != {payment_amount_cents}"
    )


def assert_pools_cover_lines(run: dict, lines: list):
    """PRD §3.5: sum(line totals) + agent_retained_cents == interest + principal pools."""
    line_total = sum(line["total_cents"] for line in lines)
    pools = run["interest_pool_cents"] + run["principal_pool_cents"]
    assert line_total + run["agent_retained_cents"] == pools, (
        f"Line/pool reconciliation broken: {line_total} + "
        f"{run['agent_retained_cents']} != {pools}"
    )
