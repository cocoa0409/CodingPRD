"""Entity assertions, timestamp comparison and domain invariant checkers."""
from datetime import datetime, timezone
from typing import Optional

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# --------------------------------------------------------------------------
# Timestamp handling
# --------------------------------------------------------------------------

def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware datetime.

    Accepts a trailing 'Z' and any number of fractional digits, so that
    '2026-05-01T00:00:00Z' and '2026-05-01T00:00:00.000Z' both parse.
    """
    assert isinstance(value, str) and value, f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual, expected, label: str = "timestamp") -> None:
    """Compare two timestamps as instants, never as strings.

    Both sides are parsed to aware datetimes before comparison, so a server
    that renders '...Z' where the fixture wrote '....000Z' (or vice versa)
    is never penalised for a formatting difference.
    """
    assert actual is not None, f"{label} must not be null (expected {expected})"
    a = parse_instant(actual)
    b = parse_instant(expected)
    assert a == b, f"{label}: expected instant {expected} ({b.isoformat()}), got {actual} ({a.isoformat()})"


def assert_instant_before(earlier, later, label: str = "ordering") -> None:
    assert parse_instant(earlier) < parse_instant(later), (
        f"{label}: expected {earlier} to be strictly before {later}"
    )


# --------------------------------------------------------------------------
# Generic shape helpers
# --------------------------------------------------------------------------

def assert_common_fields(data: dict, entity: str) -> None:
    """id + created_at + updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: dict, entity: str) -> None:
    """id + created_at only — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity} is append-only and must not expose updated_at"
    assert "version" not in data, f"{entity} is append-only and must not expose version"


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------

def assert_plan(data: dict) -> None:
    assert_common_fields(data, "plan")
    assert data["tier"] in ("SOLO", "FAMILY", "FAMILY_PLUS")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 80
    for field in ("monthly_fee_cents", "max_members", "profile_quota_per_cycle",
                  "scan_quota_per_cycle", "removal_quota_per_cycle",
                  "per_member_removal_subcap"):
        assert isinstance(data[field], int), f"plan.{field} must be an integer"


def assert_account(data: dict) -> None:
    assert_common_fields(data, "account")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CANCELLED")
    assert isinstance(data["legal_hold"], bool)
    assert is_valid_uuid(data.get("plan_id", ""))
    assert is_valid_uuid(data.get("primary_member_id", ""))
    for resource in ("profile", "scan", "removal"):
        for suffix in ("granted", "consumed", "released", "remaining"):
            field = f"{resource}_units_{suffix}"
            assert isinstance(data[field], int), f"account.{field} must be an integer"


def assert_entitlement_arithmetic(account: dict) -> None:
    """granted - consumed + released == remaining, for all three pools."""
    for resource in ("profile", "scan", "removal"):
        granted = account[f"{resource}_units_granted"]
        consumed = account[f"{resource}_units_consumed"]
        released = account[f"{resource}_units_released"]
        remaining = account[f"{resource}_units_remaining"]
        assert granted - consumed + released == remaining, (
            f"{resource}: {granted} - {consumed} + {released} != {remaining}"
        )


def assert_statement_arithmetic(statement: dict) -> None:
    for resource in ("profile", "scan", "removal"):
        granted = statement[f"{resource}_granted"]
        consumed = statement[f"{resource}_consumed"]
        released = statement[f"{resource}_released"]
        remaining = statement[f"{resource}_remaining"]
        assert granted - consumed + released == remaining, (
            f"{resource}: {granted} - {consumed} + {released} != {remaining}"
        )


def assert_member(data: dict) -> None:
    assert_common_fields(data, "member")
    assert data["status"] in ("INVITED", "ACTIVE", "REMOVED")
    assert data["authorization_status"] in ("GRANTED", "REVOKED")
    assert data["role_in_family"] in ("PRIMARY", "ADULT", "MINOR")
    assert isinstance(data["is_primary"], bool)
    assert "@" in data["email"]


def assert_monitored_profile(data: dict) -> None:
    assert_common_fields(data, "monitored profile")
    assert data["status"] in ("DRAFT", "ACTIVE", "PAUSED", "RETIRED")
    assert isinstance(data["two_factor_attested"], bool)
    assert 7 <= data["rescan_cadence_days"] <= 180
    assert data["hygiene_band"] in ("STRONG", "MODERATE", "WEAK", "CRITICAL")
    assert isinstance(data["hygiene_score"], (int, float))


def assert_identifier(data: dict) -> None:
    assert_append_only_fields(data, "identifier")
    assert data["identifier_type"] in ("EMAIL", "PHONE", "USERNAME", "SSN_LAST4", "ADDRESS")
    assert 1 <= len(data["identifier_value"]) <= 120


def assert_broker(data: dict) -> None:
    assert_common_fields(data, "broker")
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert data["opt_out_method"] in ("WEB_FORM", "EMAIL", "POSTAL", "PHONE")
    assert data["jurisdiction"] in ("US_CA", "US_VA", "EU", "OTHER")
    assert 5 <= data["response_window_days"] <= 90
    assert 0 <= data["compliance_score"] <= 100


def assert_identity_document(data: dict) -> None:
    assert_common_fields(data, "identity document")
    assert data["status"] in ("PENDING", "VERIFIED", "REJECTED", "EXPIRED")
    assert data["effective_status"] in ("VALID", "INVALID")
    assert data["document_type"] in ("PASSPORT", "DRIVERS_LICENSE", "STATE_ID", "UTILITY_BILL")


def assert_scan_run(data: dict) -> None:
    assert_common_fields(data, "scan run")
    assert data["status"] in ("QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED")
    assert data["kind"] in ("INITIAL", "RECURRING")
    assert 0 <= data["retry_count"] <= 2
    assert data["entitlement_units_held"] in (0, 1)


def assert_exposure_record(data: dict) -> None:
    assert_common_fields(data, "exposure")
    assert data["status"] in ("FOUND", "SUPPRESSED", "REAPPEARED", "RE_SUPPRESSED")
    assert data["exposure_kind"] in ("PEOPLE_SEARCH", "MARKETING_LIST",
                                     "CREDIT_HEADER", "PUBLIC_RECORD")
    assert isinstance(data["suppression_count"], int) and data["suppression_count"] >= 0
    assert isinstance(data["reappearance_count"], int) and data["reappearance_count"] >= 0
    assert isinstance(data["fee_exempt"], bool)
    # fee_exempt is true exactly while the status is REAPPEARED.
    assert data["fee_exempt"] == (data["status"] == "REAPPEARED"), (
        f"fee_exempt {data['fee_exempt']} disagrees with status {data['status']}"
    )


def assert_removal_request(data: dict) -> None:
    assert_common_fields(data, "removal request")
    assert data["status"] in ("DRAFTED", "SUBMITTED", "ACKNOWLEDGED", "COMPLETED",
                              "REJECTED", "EXPIRED", "ESCALATED", "VOIDED")
    assert data["entitlement_units_consumed"] in (0, 1)
    assert data["entitlement_units_released"] in (0, 1)
    assert 0 <= data["escalation_count"] <= 2
    if data["status"] != "COMPLETED":
        assert data["on_time"] is None, (
            f"on_time must be null outside COMPLETED, got {data['on_time']!r}"
        )


def assert_breach_alert(data: dict) -> None:
    assert_common_fields(data, "breach alert")
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert data["status"] in ("NEW", "ACKNOWLEDGED", "RESOLVED")
    assert isinstance(data["severity_points"], int)
    assert isinstance(data["escalation_count"], int)


def assert_credential_finding(data: dict) -> None:
    assert_common_fields(data, "credential finding")
    assert data["status"] in ("OPEN", "REMEDIATED")
    assert data["finding_type"] in ("BREACHED_PASSWORD", "WEAK_PASSWORD",
                                   "REUSED_PASSWORD", "STALE_PASSWORD")


def assert_addon(data: dict) -> None:
    assert_common_fields(data, "add-on")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CANCELLED")
    assert data["addon_type"] in ("VPN", "DEVICE_PROTECTION")
    assert 1 <= data["seats_total"] <= 20


def assert_seat_conservation(addon: dict) -> None:
    """seats_bound + seats_available == seats_total, always."""
    assert addon["seats_bound"] + addon["seats_available"] == addon["seats_total"], (
        f"seat pool broken: {addon['seats_bound']} + {addon['seats_available']}"
        f" != {addon['seats_total']}"
    )


def assert_device_seat(data: dict) -> None:
    assert_common_fields(data, "device seat")
    assert data["status"] in ("BOUND", "RELEASED", "VOIDED")
    assert isinstance(data["bind_count"], int) and data["bind_count"] >= 1


def assert_billing_cycle(data: dict) -> None:
    assert_common_fields(data, "billing cycle")
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["cycle_seq"], int) and data["cycle_seq"] >= 1


def assert_cycle_money_arithmetic(cycle: dict) -> None:
    """pre-discount total and the post-discount total agree with their inputs."""
    expected_pre = max(0,
                       cycle["base_charge_cents"]
                       + cycle["proration_charge_cents"]
                       + cycle["addon_charge_cents"]
                       - cycle["proration_credit_cents"]
                       - cycle["addon_credit_cents"])
    assert cycle["pre_discount_total_cents"] == expected_pre, (
        f"pre_discount_total_cents {cycle['pre_discount_total_cents']} != {expected_pre}"
    )
    assert cycle["total_charged_cents"] == (
        cycle["pre_discount_total_cents"] - cycle["loyalty_discount_cents"]
    ), "total_charged_cents must be the pre-discount total minus the loyalty discount"


def assert_ledger_entry(data: dict) -> None:
    assert_append_only_fields(data, "entitlement ledger entry")
    assert data["resource_type"] in ("PROFILE", "SCAN", "REMOVAL")
    assert data["entry_type"] in ("GRANT", "CONSUME", "RELEASE")
    assert isinstance(data["amount"], int) and data["amount"] >= 1
    expected_signed = -data["amount"] if data["entry_type"] == "CONSUME" else data["amount"]
    assert data["signed_amount"] == expected_signed, (
        f"signed_amount {data['signed_amount']} != {expected_signed} for {data['entry_type']}"
    )
    assert data["reason_code"] in (
        "CYCLE_GRANT", "PROFILE_ACTIVATED", "PROFILE_RETIRED", "SCAN_QUEUED",
        "SCAN_CANCELLED", "SCAN_ABANDONED", "REMOVAL_DRAFTED", "REMOVAL_VOIDED",
        "AUTHORIZATION_REVOKED",
    )


# --------------------------------------------------------------------------
# Tolerant readers for shapes the PRD describes without naming every key
# --------------------------------------------------------------------------

def breakdown_member_id(entry: dict) -> Optional[str]:
    """Read the member identity out of an entitlement-statement breakdown row.

    The statement narrative pins the ordering of `member_breakdown` but does
    not name the keys inside each row, so both `member_id` and `id` are
    accepted here; the assertion that uses this reader therefore holds under
    either faithful reading.
    """
    for key in ("member_id", "id"):
        if key in entry:
            return entry[key]
    return None
