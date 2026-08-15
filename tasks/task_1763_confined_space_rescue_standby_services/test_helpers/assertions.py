"""Entity assertions and domain invariant checkers (PRD §2.4, §3).

Entity assertions check only structural properties every PRD reader agrees on:
common system fields (id/created_at/updated_at/version on regular resources;
id/created_at only on the append-only AtmosphericReading and StatementLine)
plus status-enum membership. Nullable-until-computed fields are read via
.get() by callers, never demanded here.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601 UTC"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601 UTC"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1"
    )


def _assert_append_only_fields(data: dict, entity: str):
    """PRD §2.4: append-only records carry only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601 UTC"
    )
    assert "updated_at" not in data, f"{entity} must not expose updated_at"
    assert "version" not in data, f"{entity} must not expose version"


def assert_personnel(data: dict):
    _assert_common_fields(data, "Personnel")
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert data.get("status") in ("ACTIVE", "INACTIVE")
    assert isinstance(data.get("committed_standby_minutes"), int)
    assert data["committed_standby_minutes"] >= 0


def assert_client_account(data: dict):
    _assert_common_fields(data, "ClientAccount")
    assert data.get("billing_mode") in ("HOURLY_STANDBY", "EVENT")
    assert isinstance(data.get("balance_cents"), int)
    assert isinstance(data.get("on_credit_hold"), bool)


def assert_confined_space(data: dict):
    _assert_common_fields(data, "ConfinedSpace")
    assert data.get("classification") in (
        "NON_PERMIT", "PERMIT_REQUIRED", "PERMIT_REQUIRED_HAZARDOUS")
    assert data.get("status") in ("AVAILABLE", "OUT_OF_SERVICE")
    assert data.get("exposure_standard") in ("TWA8", "PEAK_CEILING")


def assert_rescue_plan(data: dict):
    _assert_common_fields(data, "RescuePlan")
    assert data.get("status") in ("DRAFT", "APPROVED", "SUPERSEDED")
    assert isinstance(data.get("plan_revision"), int) and data["plan_revision"] >= 1


def assert_entry_permit(data: dict):
    _assert_common_fields(data, "EntryPermit")
    assert data.get("status") in (
        "DRAFT", "ISSUED", "ACTIVE", "SUSPENDED", "CLOSED", "CANCELLED")
    assert isinstance(data.get("suspension_count"), int)
    assert data["suspension_count"] >= 0
    assert isinstance(data.get("reentry_count"), int)
    assert data["reentry_count"] >= 0


def assert_isolation_verification(data: dict):
    _assert_common_fields(data, "IsolationVerification")
    assert data.get("status") in ("PENDING", "VERIFIED", "EXPIRED", "VOIDED")
    assert data.get("isolation_type") in (
        "VENTILATION", "BLIND_FLANGE", "LOCKOUT_TAGOUT")


def assert_roster_entry(data: dict):
    _assert_common_fields(data, "RosterEntry")
    assert data.get("status") in (
        "SCHEDULED", "ON_DUTY", "RELIEVED", "COMPLETED", "EVACUATED",
        "NO_SHOW", "CANCELLED")
    assert data.get("assignment_role") in ("ENTRANT", "ATTENDANT")


def assert_atmospheric_reading(data: dict):
    _assert_append_only_fields(data, "AtmosphericReading")
    assert data.get("reading_kind") in ("PRE_ENTRY", "CONTINUOUS")
    assert isinstance(data.get("within_limits"), bool)


def assert_standby_assignment(data: dict):
    _assert_common_fields(data, "StandbyAssignment")
    assert data.get("status") in (
        "SCHEDULED", "ON_STANDBY", "DEPLOYED", "RELEASED", "NO_SHOW", "CANCELLED")


def assert_incident(data: dict):
    _assert_common_fields(data, "Incident")
    assert data.get("status") in (
        "REPORTED", "TRIAGED", "ESCALATED", "RESOLVED", "REOPENED")
    assert isinstance(data.get("escalation_level"), int)
    assert data["escalation_level"] >= 0


def assert_billing_statement(data: dict):
    _assert_common_fields(data, "BillingStatement")
    assert data.get("status") in ("OPEN", "FINALIZED", "DISPUTED", "PAID", "VOID")
    assert isinstance(data.get("total_cents"), int)
    assert isinstance(data.get("line_count"), int)
    assert isinstance(data.get("billed_balance_contribution_cents"), int)


def assert_statement_line(data: dict):
    _assert_append_only_fields(data, "StatementLine")
    assert data.get("line_kind") in (
        "STANDBY_HOURLY", "EVENT_BASE", "EVENT_RESCUER", "CANCELLATION_FEE",
        "DEPLOYMENT_SURCHARGE", "CREDIT_ADJUSTMENT")
    assert isinstance(data.get("amount_cents"), int)


def assert_ledger_invariant(account: dict, statements: list):
    """PRD §2.9: balance_cents always equals the sum of each statement's
    billed_balance_contribution_cents."""
    expected = sum(s.get("billed_balance_contribution_cents", 0) for s in statements)
    assert account.get("balance_cents") == expected, (
        f"Ledger invariant violated: balance_cents {account.get('balance_cents')} "
        f"!= sum of contributions {expected}"
    )
