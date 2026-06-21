"""Entity assertions and domain invariant checkers for the Bail Bond API.

Each assert_<entity>() validates the system-managed shape of a returned resource
(UUID id, ISO 8601 timestamps, status in its declared set). Append-only records
(Notification, CheckIn, LedgerEntry) carry only id + created_at — they are checked
without updated_at / version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_RISK_TIERS = {"LOW", "MEDIUM", "HIGH"}
_DEFENDANT_STATUS = {"ACTIVE", "CLEARED"}
_BAIL_ORDER_STATUS = {"OPEN", "BONDED", "RESOLVED"}
_BOND_TYPE = {"CASH", "SURETY", "PR"}
_COVERAGE_STATUS = {"DRAFT", "ACTIVE", "FORFEITED", "EXONERATED", "REVOKED"}
_SETTLEMENT_STATUS = {"UNSETTLED", "PREMIUM_COLLECTED", "COLLATERAL_REFUNDED", "JUDGMENT_ENTERED"}
_IA_STATUS = {"PENDING", "BINDING", "DISCHARGED", "CALLED"}
_COLLATERAL_KIND = {"CASH", "PROPERTY_LIEN", "VEHICLE_TITLE"}
_COLLATERAL_STATUS = {"HELD", "RELEASED", "LIQUIDATED"}
_COURT_DATE_STATUS = {"SCHEDULED", "NOTIFIED", "APPEARED", "FAILED_TO_APPEAR", "CONTINUED"}
_HEARING_TYPE = {"ARRAIGNMENT", "PRETRIAL", "TRIAL", "SENTENCING"}
_CHANNEL = {"SMS", "VOICE", "EMAIL"}
_CONDITION_CODE = {"GPS", "CURFEW", "DRUG_TEST", "NO_CONTACT"}
_CHECK_IN_RESULT = {"PASS", "FAIL", "MISSED"}
_GPS_STATUS = {"UNASSIGNED", "ASSIGNED", "ACTIVE", "TAMPER", "RETURNED"}
_FORFEITURE_STATUS = {"FORFEITED", "RECOVERY_OPEN", "REINSTATED", "JUDGMENT", "REMITTED"}
_LEDGER_TYPE = {"PREMIUM_COLLECTED", "COLLATERAL_REFUND", "FORFEITURE_JUDGMENT", "REMISSION_CREDIT"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must NOT carry updated_at"
    assert "version" not in data, "append-only record must NOT carry version"


def assert_defendant(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["risk_tier"] in _RISK_TIERS, f"risk_tier {data['risk_tier']!r} not in {_RISK_TIERS}"
    assert data["status"] in _DEFENDANT_STATUS, f"status {data['status']!r} not in {_DEFENDANT_STATUS}"
    assert isinstance(data["total_active_exposure_cents"], int)
    assert data["total_active_exposure_cents"] >= 0


def assert_bail_order(data: dict):
    _assert_common(data)
    assert isinstance(data["case_number"], str) and data["case_number"]
    assert isinstance(data["bail_amount_cents"], int) and data["bail_amount_cents"] > 0
    assert data["bond_type_allowed"] in (_BOND_TYPE | {"ANY"})
    assert data["status"] in _BAIL_ORDER_STATUS
    assert isinstance(data["condition_codes"], list)
    assert isinstance(data["gps_required"], bool)


def assert_bond(data: dict):
    _assert_common(data)
    assert data["bond_type"] in _BOND_TYPE
    assert isinstance(data["bail_amount_cents"], int) and data["bail_amount_cents"] > 0
    assert data["coverage_status"] in _COVERAGE_STATUS
    assert data["settlement_status"] in _SETTLEMENT_STATUS
    for f in ("premium_cents", "premium_earned_cents", "required_collateral_cents", "collateral_held_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"
        assert data[f] >= 0, f"{f} must be non-negative"


def assert_indemnitor(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] > 0
    assert isinstance(data["total_exposure_cents"], int) and data["total_exposure_cents"] >= 0


def assert_indemnity_agreement(data: dict):
    _assert_common(data)
    assert isinstance(data["liability_share_cents"], int) and data["liability_share_cents"] > 0
    assert data["status"] in _IA_STATUS


def assert_collateral_item(data: dict):
    _assert_common(data)
    assert data["kind"] in _COLLATERAL_KIND
    assert isinstance(data["pledged_value_cents"], int) and data["pledged_value_cents"] > 0
    assert data["status"] in _COLLATERAL_STATUS


def assert_court_date(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data["scheduled_utc"]), "scheduled_utc must be ISO 8601"
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] > 0
    assert data["hearing_type"] in _HEARING_TYPE
    assert data["status"] in _COURT_DATE_STATUS


def assert_gps_device(data: dict):
    _assert_common(data)
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert isinstance(data["violation_count"], int) and data["violation_count"] >= 0
    assert data["status"] in _GPS_STATUS


def assert_forfeiture_proceeding(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data["forfeited_utc"]), "forfeited_utc must be ISO 8601"
    assert is_iso8601_timestamp(data["grace_deadline_utc"]), "grace_deadline_utc must be ISO 8601"
    assert isinstance(data["judgment_amount_cents"], int) and data["judgment_amount_cents"] >= 0
    assert data["status"] in _FORFEITURE_STATUS


def assert_notification(data: dict):
    _assert_append_only(data)
    assert data["channel"] in _CHANNEL
    assert isinstance(data["lead_hours"], int)
    assert isinstance(data["destination"], str) and data["destination"]


def assert_check_in(data: dict):
    _assert_append_only(data)
    assert data["condition_code"] in _CONDITION_CODE
    assert data["result"] in _CHECK_IN_RESULT
    assert isinstance(data["weight"], int) and data["weight"] >= 0
    assert is_iso8601_timestamp(data["occurred_utc"]), "occurred_utc must be ISO 8601"


def assert_ledger_entry(data: dict):
    _assert_append_only(data)
    assert data["entry_type"] in _LEDGER_TYPE
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["memo"], str)


# ---------------------------------------------------------------------------
# Domain invariant helpers
# ---------------------------------------------------------------------------
def find_ledger_entries(entries: list, entry_type: str) -> list:
    """Return ledger entries of a given entry_type from a list response."""
    return [e for e in entries if e.get("entry_type") == entry_type]


def total_ledger_amount(entries: list, entry_type: str = None) -> int:
    """Sum signed amount_cents over entries (optionally of one entry_type)."""
    return sum(
        e["amount_cents"]
        for e in entries
        if entry_type is None or e.get("entry_type") == entry_type
    )
