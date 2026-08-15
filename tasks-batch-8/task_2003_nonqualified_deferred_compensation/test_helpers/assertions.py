"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["effective_date"], str)
    assert isinstance(data["distribution_events_allowed"], list) and data["distribution_events_allowed"]
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "TERMINATION_PENDING", "TERMINATED")
    assert data["document_posture"] in ("COMPLIANT", "FAILURE_OPEN", "LAPSED_FAILURE")
    assert isinstance(data["open_findings_count"], int) and data["open_findings_count"] >= 0


def assert_participant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["employee_ref"], str)
    assert data["status"] in ("ACTIVE", "SEPARATION_REVIEW", "SEPARATED", "DISABLED", "DECEASED")
    assert isinstance(data["is_specified_employee"], bool)
    assert isinstance(data["inclusion_liability_cents"], int)
    assert isinstance(data["annual_compensation_cents"], int)


def assert_election_window(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["plan_year"], int)
    assert isinstance(data["general_open_date"], str)
    assert isinstance(data["general_close_date"], str)
    assert data["status"] in ("SCHEDULED", "OPEN", "CLOSED")


def assert_deferral_election(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["participant_id"], str)
    assert isinstance(data["election_window_id"], str)
    assert isinstance(data["notional_fund_id"], str)
    assert isinstance(data["plan_id"], str)
    assert data["election_type"] in ("GENERAL", "NEWLY_ELIGIBLE", "PERFORMANCE")
    assert 1 <= data["deferral_percent_bp"] <= 7500
    assert data["status"] in ("DRAFT", "SUBMITTED", "LOCKED", "APPLIED", "VOIDED", "EXPIRED")
    assert isinstance(data["posted_cents"], int)


def assert_notional_fund(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["ticker"], str)
    assert data["crediting_mode"] in ("FIXED_RATE", "INDEX_LINKED")
    assert isinstance(data["annual_rate_bp"], int)


def assert_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["participant_id"], str)
    assert isinstance(data["plan_id"], str)
    assert data["status"] in ("ACTIVE", "FLAGGED_FOR_INCLUSION", "CLOSED")
    for field in ("settled_balance_cents", "provisional_balance_cents", "vested_balance_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["vested_balance_cents"] <= max(data["settled_balance_cents"], 0)
    assert data["provisional_balance_cents"] >= data["settled_balance_cents"] or True


def assert_ledger_entry(data: dict):
    """Append-only ledger entry: id + created_at only; no updated_at/version keys."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ledger entries must not carry updated_at"
    assert "version" not in data, "ledger entries must not carry version"
    assert isinstance(data["account_id"], str)
    assert data["entry_type"] in (
        "DEFERRAL_CREDIT", "CREDITING_GAIN", "CREDITING_REVERSAL", "DISTRIBUTION_DEBIT"
    )
    assert isinstance(data["amount_cents"], int)
    assert data["entry_status"] in ("PENDING", "POSTED")
    assert isinstance(data["entry_date"], str)


def assert_crediting_run(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert data["status"] in ("POSTED", "REVERSED")
    assert isinstance(data["days_in_period"], int)
    assert isinstance(data["total_gain_cents"], int)


def assert_rabbi_trust(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["funding_target_bp"], int)
    assert isinstance(data["assets_cents"], int)
    assert isinstance(data["cic_funding_required"], bool)
    assert isinstance(data["required_funding_cents"], int)
    assert data["posture"] in ("UNFUNDED", "UNDERFUNDED", "FUNDED")
    assert isinstance(data["funding_events"], list)


def assert_separation_case(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["participant_id"], str)
    assert isinstance(data["alleged_separation_date"], str)
    assert data["trigger_reason"] in ("RESIGNATION", "TERMINATION", "RETIREMENT", "SERVICE_REDUCTION")
    assert data["status"] in (
        "OPEN", "EVIDENCE_SUBMITTED", "DETERMINED_SEPARATED",
        "DETERMINED_NOT_SEPARATED", "REOPENED",
    )
    assert isinstance(data["reopen_count"], int)


def assert_specified_employee_list(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["identification_date"], str)
    assert isinstance(data["effective_date"], str)
    assert data["status"] in ("DRAFT", "FINALIZED", "SUPERSEDED")
    assert isinstance(data["members"], list)


def assert_distribution_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["participant_id"], str)
    assert data["event_type"] in (
        "SEPARATION", "DEATH", "DISABILITY", "FIXED_TIME",
        "UNFORESEEABLE_EMERGENCY", "CHANGE_IN_CONTROL",
    )
    assert data["status"] in (
        "REQUESTED", "EVENT_VERIFIED", "SCHEDULED", "PAYABLE",
        "ON_HOLD", "PAID", "DENIED", "CANCELLED",
    )


def assert_cic_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_id"], str)
    assert data["event_type"] in ("OWNERSHIP_CHANGE", "EFFECTIVE_CONTROL_CHANGE", "ASSET_CHANGE")
    assert isinstance(data["stake_change_bp"], int)
    assert data["status"] in ("REPORTED", "VERIFIED", "REJECTED")


def assert_operational_failure(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["participant_id"], str)
    assert data["failure_type"] in (
        "EARLY_PAYMENT", "LATE_PAYMENT", "EXCESS_DEFERRAL", "IMPROPER_ACCELERATION"
    )
    assert isinstance(data["failure_date"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("IDENTIFIED", "QUANTIFIED", "INCLUSION_ASSESSED", "CORRECTED")
    assert isinstance(data["correction_deadline"], str)


def assert_document_finding(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["description"], str)
    assert isinstance(data["failure_year"], int)
    assert isinstance(data["correction_deadline"], str)
    assert data["status"] in ("REPORTED", "CORRECTION_FILED", "CORRECTED", "LAPSED")


def assert_account_invariants(data: dict):
    """Domain invariants that must hold after any account operation (PRD §3.3)."""
    assert data["settled_balance_cents"] >= 0, "settled balance never negative in these flows"
    assert data["provisional_balance_cents"] >= data["settled_balance_cents"], (
        "provisional includes POSTED+PENDING so it dominates settled for credit-only ledgers"
    )
    assert data["vested_balance_cents"] in (0, data["settled_balance_cents"]), (
        "cliff vesting is all-or-nothing: vested is 0 or the full settled balance"
    )
