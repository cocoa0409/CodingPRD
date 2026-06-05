"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the shape of a single resource object against
the field set the PRD declares for it. Append-only records (ShareIssuance,
Form3921, WaterfallDistribution) are checked WITHOUT updated_at/version, per
PRD §2.4.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_CAP_TABLE_STATUSES = {"OPEN", "LOCKED", "DISSOLVED"}
_VALUATION_STATUSES = {"DRAFT", "EFFECTIVE", "SUPERSEDED"}
_POOL_STATUSES = {"ACTIVE", "EXHAUSTED", "CLOSED"}
_GRANT_STATUSES = {"DRAFT", "ACTIVE", "EXERCISED", "CANCELLED", "EXPIRED"}
_EXERCISE_STATUSES = {"PENDING", "SETTLED", "REVERSED"}
_ELECTION_STATUSES = {"PENDING", "ACCEPTED", "REJECTED_LATE"}
_NOTE_STATUSES = {"DRAFT", "NEGOTIATING", "OUTSTANDING", "CONVERTED", "REPAID"}
_EVENT_STATUSES = {"DRAFT", "COMPUTED", "FINALIZED"}
_WINDOW_STATUSES = {"SCHEDULED", "LIFTED"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _assert_append_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_cap_table(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert isinstance(data["authorized_shares"], int) and data["authorized_shares"] > 0
    assert data["status"] in _CAP_TABLE_STATUSES, f"bad status {data['status']}"
    assert isinstance(data["issued_shares"], int) and data["issued_shares"] >= 0
    assert isinstance(data["fully_diluted_shares"], int) and data["fully_diluted_shares"] >= 0


def assert_security_class(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["cap_table_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["class_type"] in {"COMMON", "PREFERRED"}
    assert isinstance(data["shares_outstanding"], int) and data["shares_outstanding"] >= 0
    assert isinstance(data["original_issue_price_cents"], int) and data["original_issue_price_cents"] >= 0


def assert_shareholder(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["cap_table_id"])
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["holder_type"] in {"FOUNDER", "EMPLOYEE", "INVESTOR", "ENTITY"}
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["is_us_taxpayer"], bool)


def assert_share_issuance(data: dict):
    _assert_append_only(data)
    assert is_valid_uuid(data["cap_table_id"])
    assert is_valid_uuid(data["security_class_id"])
    assert is_valid_uuid(data["shareholder_id"])
    assert isinstance(data["share_count"], int) and data["share_count"] > 0
    assert isinstance(data["price_paid_cents"], int) and data["price_paid_cents"] >= 0
    assert is_iso8601_timestamp(data.get("issued_at", "")), "issued_at must be ISO 8601"
    # Append-only: must NOT carry updated_at / version.
    assert "updated_at" not in data, "ShareIssuance must not carry updated_at"
    assert "version" not in data, "ShareIssuance must not carry version"


def assert_valuation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["cap_table_id"])
    assert isinstance(data["fmv_per_share_cents"], int) and data["fmv_per_share_cents"] > 0
    assert data["status"] in _VALUATION_STATUSES, f"bad status {data['status']}"


def assert_option_pool(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["cap_table_id"])
    assert isinstance(data["authorized_shares"], int) and data["authorized_shares"] > 0
    assert isinstance(data["allocated_shares"], int) and data["allocated_shares"] >= 0
    assert isinstance(data["available_shares"], int) and data["available_shares"] >= 0
    assert data["status"] in _POOL_STATUSES, f"bad status {data['status']}"


def assert_option_grant(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["cap_table_id"])
    assert is_valid_uuid(data["option_pool_id"])
    assert is_valid_uuid(data["shareholder_id"])
    assert is_valid_uuid(data["security_class_id"])
    assert is_valid_uuid(data["valuation_id"])
    assert isinstance(data["share_count"], int) and data["share_count"] > 0
    assert isinstance(data["strike_price_cents"], int) and data["strike_price_cents"] > 0
    assert isinstance(data["vested_shares"], int) and data["vested_shares"] >= 0
    assert isinstance(data["exercised_shares"], int) and data["exercised_shares"] >= 0
    assert data["status"] in _GRANT_STATUSES, f"bad status {data['status']}"
    assert data["vesting_style"] in {"GRADED", "CLIFF_ONLY"}


def assert_exercise(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["cap_table_id"])
    assert is_valid_uuid(data["option_grant_id"])
    assert isinstance(data["share_count"], int) and data["share_count"] > 0
    assert isinstance(data["is_early_exercise"], bool)
    assert isinstance(data["spread_cents"], int) and data["spread_cents"] >= 0
    assert data["status"] in _EXERCISE_STATUSES, f"bad status {data['status']}"


def assert_section_83b_election(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["cap_table_id"])
    assert is_valid_uuid(data["exercise_id"])
    assert data["status"] in _ELECTION_STATUSES, f"bad status {data['status']}"


def assert_safe_note(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["cap_table_id"])
    assert is_valid_uuid(data["shareholder_id"])
    assert data["instrument_type"] in {"SAFE", "NOTE"}
    assert isinstance(data["principal_cents"], int) and data["principal_cents"] > 0
    assert isinstance(data["converted_share_count"], int) and data["converted_share_count"] >= 0
    assert data["status"] in _NOTE_STATUSES, f"bad status {data['status']}"


def assert_form_3921(data: dict):
    _assert_append_only(data)
    assert is_valid_uuid(data["cap_table_id"])
    assert is_valid_uuid(data["exercise_id"])
    assert is_valid_uuid(data["shareholder_id"])
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["exercise_fmv_cents"], int)
    assert isinstance(data["strike_price_cents"], int)
    assert isinstance(data["shares_transferred"], int) and data["shares_transferred"] >= 0
    assert "updated_at" not in data, "Form3921 must not carry updated_at"
    assert "version" not in data, "Form3921 must not carry version"


def assert_liquidation_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["cap_table_id"])
    assert isinstance(data["total_proceeds_cents"], int) and data["total_proceeds_cents"] >= 0
    assert data["status"] in _EVENT_STATUSES, f"bad status {data['status']}"


def assert_waterfall_distribution(data: dict):
    _assert_append_only(data)
    assert is_valid_uuid(data["cap_table_id"])
    assert is_valid_uuid(data["liquidation_event_id"])
    assert is_valid_uuid(data["security_class_id"])
    assert isinstance(data["preference_paid_cents"], int)
    assert isinstance(data["participation_paid_cents"], int)
    assert isinstance(data["total_paid_cents"], int)
    assert data["total_paid_cents"] == data["preference_paid_cents"] + data["participation_paid_cents"], (
        "total_paid_cents must equal preference + participation"
    )
    assert "updated_at" not in data, "WaterfallDistribution must not carry updated_at"
    assert "version" not in data, "WaterfallDistribution must not carry version"


def assert_blackout_window(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["cap_table_id"])
    assert isinstance(data["reason"], str) and len(data["reason"]) > 0
    assert data["status"] in _WINDOW_STATUSES, f"bad status {data['status']}"


def assert_pool_conservation(data: dict):
    """OptionPool invariant: authorized == allocated + available (PRD §3.5)."""
    assert data["allocated_shares"] + data["available_shares"] == data["authorized_shares"], (
        f"pool conservation broken: {data['allocated_shares']} + {data['available_shares']} "
        f"!= {data['authorized_shares']}"
    )
