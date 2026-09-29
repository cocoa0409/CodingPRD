"""Entity assertions and domain invariant checkers.

Every assertion here checks only properties the PRD states explicitly: the four
common resource properties of §2.5, the declared status enumerations, and the
two conserved ledgers of §2.11.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import INSTALL_TRAVEL_BUFFER_MINUTES


def _as_instant(value):
    if value is None:
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def assert_instant(actual, expected, label="instant"):
    """Compare a stamped instant as an instant, not as a string.

    PRD §2.5 pins "three fractional digits" for `created_at` and `updated_at`
    and §2.2 pins the same for `api_request_timestamp`, but §2.4 says only that
    every other persisted instant — `qualified_at`, `released_at`,
    `sunset_announced_at`, `withdrawn_at`, `certified_at`, `quoted_at`,
    `completed_at`, `warranty_starts_at`, `last_revised_at` "and every derived
    horizon" — is "stamped from the logical clock, in UTC". The fractional-digit
    rendering of those instants is therefore not specified, so the assertion is
    on the instant the PRD's arithmetic produces.
    """
    assert _as_instant(actual) == _as_instant(expected), (
        f"{label}: expected instant {expected}, got {actual}"
    )


def expected_listing_order(rows):
    """The ids of `rows` in the order PRD §2.3 requires a listing to return them.

    PRD §2.3: "Every list endpoint returns rows ordered by `created_at`
    ascending, with the row `id` ascending as the tie-break when two rows share
    a creation timestamp." Because the logical clock of §2.4 "never advances on
    its own", rows created inside one test normally do share a creation
    timestamp, and the `id` tie-break — not insertion order — decides.
    """
    return [
        row["id"]
        for row in sorted(rows, key=lambda row: (row["created_at"], row["id"]))
    ]


def assert_common_properties(data: dict, expect_version=None):
    """Every persisted resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"
    if expect_version is not None:
        assert data["version"] == expect_version, (
            f"Expected version {expect_version}, got {data['version']}"
        )


def assert_equipment_model(data: dict):
    assert_common_properties(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert data["category"] in ("CARDIO", "STRENGTH", "CONNECTED")
    assert data["duty_class"] in ("LIGHT_COMMERCIAL", "FULL_COMMERCIAL", "INSTITUTIONAL")
    assert isinstance(data["unit_list_price_cents"], int)
    assert data["unit_list_price_cents"] > 0
    assert float(data["shipping_weight_kg"]) > 0
    assert isinstance(data["allowed_finish_codes"], list)
    assert len(data["allowed_finish_codes"]) >= 1
    assert data["connected"] is (data["category"] == "CONNECTED")
    if data["connected"]:
        assert data["console_platform"] in ("CONSOLE_T1", "CONSOLE_T2", "CONSOLE_X")
    else:
        assert data["console_platform"] is None
    assert data["lifecycle_status"] in ("PRE_RELEASE", "ACTIVE", "SUNSET", "OBSOLETE")
    assert isinstance(data["released_revision_count"], int)
    assert data["released_revision_count"] >= 0


def assert_model_revision(data: dict):
    assert_common_properties(data)
    assert isinstance(data["revision_code"], str) and 1 <= len(data["revision_code"]) <= 40
    assert data["target_cycle_count"] >= 1000
    assert data["status"] in (
        "DRAFT", "IN_TESTING", "TEST_FAILED", "QUALIFIED",
        "RELEASED", "SUNSET_ANNOUNCED", "OBSOLETE", "SUPERSEDED",
    )
    assert data["min_required_cycles"] in (250_000, 500_000, 900_000)
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0
    assert isinstance(data["verified_cycle_count"], int)
    assert isinstance(data["projected_cycle_count"], int)
    assert data["verified_cycle_count"] >= 0
    assert data["projected_cycle_count"] >= 0


def assert_test_rig(data: dict):
    assert_common_properties(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 80
    assert 1 <= data["parallel_station_count"] <= 8
    assert len(data["supported_duty_classes"]) >= 1
    assert 0 <= data["occupied_station_count"] <= data["parallel_station_count"]


def assert_test_run(data: dict):
    assert_common_properties(data)
    assert data["status"] in ("RESERVED", "RUNNING", "COMPLETED", "ABORTED")
    assert data["outcome"] in ("PENDING", "PASSED", "FAILED")
    assert data["target_cycles"] >= 1000
    assert isinstance(data["superseded_by_rework"], bool)


def assert_firmware_release(data: dict):
    assert_common_properties(data)
    assert isinstance(data["version_string"], str)
    assert 1 <= len(data["version_string"]) <= 40
    assert data["console_platform"] in ("CONSOLE_T1", "CONSOLE_T2", "CONSOLE_X")
    assert isinstance(data["mandatory_security"], bool)
    assert data["status"] in ("ACTIVE", "WITHDRAWN")
    assert data["certified_revision_count"] >= 0


def assert_firmware_certification(data: dict):
    assert_common_properties(data)
    assert data["cert_status"] in ("SUBMITTED", "CERTIFIED", "REJECTED", "REVOKED")
    assert isinstance(data["test_report_ref"], str)
    assert 1 <= len(data["test_report_ref"]) <= 80
    assert isinstance(data["submitted_by_user_id"], str)
    assert len(data["submitted_by_user_id"]) > 0


def assert_facility(data: dict):
    assert_common_properties(data)
    assert isinstance(data["account_name"], str) and 1 <= len(data["account_name"]) <= 120
    assert data["freight_zone"] in ("Z1", "Z2", "Z3", "Z4")
    assert data["credit_limit_cents"] >= 0
    assert isinstance(data["install_blackout_weekdays"], list)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert data["open_order_exposure_cents"] >= 0
    assert_tradein_ledger_conserved(data)


def assert_order(data: dict):
    assert_common_properties(data)
    assert data["config_status"] in ("CONFIGURING", "CONFIRMED")
    assert data["fulfillment_status"] in (
        "PENDING", "IN_PRODUCTION", "STAGED", "INSTALLING", "INSTALLED"
    )
    assert data["billing_status"] in ("UNQUOTED", "QUOTED", "INVOICED", "SETTLED")
    assert data["price_variant_applied"] in ("NONE", "PROVISIONAL", "FINAL")
    assert isinstance(data["line_subtotal_cents"], int)
    assert data["line_subtotal_cents"] >= 0
    assert isinstance(data["quoted_total_cents"], int)


def assert_order_line(data: dict):
    assert_common_properties(data)
    assert data["status"] in ("ACTIVE", "VOIDED")
    assert 1 <= data["quantity"] <= 500
    assert isinstance(data["finish_codes"], list)
    assert len(data["finish_codes"]) == len(set(data["finish_codes"])), (
        "finish_codes must contain no duplicates"
    )
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0
    assert isinstance(data["extended_price_cents"], int)
    assert data["assets_minted_count"] >= 0


def assert_service_partner(data: dict):
    assert_common_properties(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert data["region"] in ("R_NORTH", "R_SOUTH", "R_EAST", "R_WEST")
    assert len(data["certified_categories"]) >= 1
    assert data["certified_technician_count"] >= 1
    assert float(data["certified_hours_capacity"]) > 0
    assert data["coverage_status"] in ("ACTIVE", "OVER_COMMITTED")
    expected_coverage = (
        "OVER_COMMITTED"
        if float(data["committed_hours"]) > float(data["certified_hours_capacity"])
        else "ACTIVE"
    )
    assert data["coverage_status"] == expected_coverage, (
        f"coverage_status {data['coverage_status']} disagrees with "
        f"committed_hours {data['committed_hours']} vs capacity "
        f"{data['certified_hours_capacity']}"
    )
    assert_spare_stock_conserved(data)


def assert_install_job(data: dict):
    assert_common_properties(data)
    assert data["status"] in ("SCHEDULED", "ON_SITE", "PUNCH_LIST", "COMPLETED", "ABORTED")
    assert 0 < float(data["estimated_labor_hours"]) <= 400
    assert data["travel_buffer_minutes"] == INSTALL_TRAVEL_BUFFER_MINUTES, (
        f"travel_buffer_minutes is fixed at {INSTALL_TRAVEL_BUFFER_MINUTES}, "
        f"got {data['travel_buffer_minutes']}"
    )
    assert data["punch_list_open_count"] >= 0


def assert_serialized_asset(data: dict):
    assert_common_properties(data)
    assert data["status"] in (
        "BUILT", "IN_SERVICE", "TRADE_IN_RETURNED", "REFURB_INTAKE",
        "REFURB_CERTIFIED", "RESOLD", "SCRAPPED",
    )
    assert data["connectivity_support_status"] in (
        "NOT_APPLICABLE", "SUPPORTED", "SUNSET_TRACKED", "SUPPORT_GAP", "FIRMWARE_REVOKED"
    )
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert data["support_gap_days"] >= 0, "support_gap_days is floored at zero"
    assert data["service_history_count"] >= 0
    assert float(data["accrued_service_labor_hours"]) >= 0


def assert_pm_program(data: dict):
    assert_common_properties(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "NEEDS_REVISION", "TERMINATED")
    assert data["tier"] in ("BASIC", "PRO", "PLATINUM")
    assert 30 <= data["visit_interval_days"] <= 365
    assert data["covered_asset_count"] >= 0
    assert float(data["annual_labor_hours_committed"]) >= 0


def assert_maintenance_visit(data: dict):
    assert_common_properties(data)
    assert data["status"] in ("SCHEDULED", "ON_HOLD", "COMPLETED", "CANCELLED")
    assert 0 <= data["reserved_units"] <= 50


# ─── Domain invariants ─────────────────────────────────────────────────────

def assert_tradein_ledger_conserved(facility: dict):
    """PRD §2.11: granted must equal applied plus balance, and the balance may
    never go negative."""
    granted = facility["tradein_credit_granted_cents"]
    applied = facility["tradein_credit_applied_cents"]
    balance = facility["tradein_credit_balance_cents"]
    assert balance >= 0, f"trade-in credit balance went negative: {balance}"
    assert granted == applied + balance, (
        f"trade-in ledger broken: granted {granted} != applied {applied} + "
        f"balance {balance}"
    )


def assert_spare_stock_conserved(partner: dict):
    """PRD §2.11: received must equal on-hand plus reserved plus consumed, and
    on-hand may never go negative."""
    received = partner["spare_stock_received_units"]
    reserved = partner["spare_stock_reserved_units"]
    consumed = partner["spare_stock_consumed_units"]
    on_hand = partner["spare_stock_on_hand_units"]
    assert on_hand >= 0, f"spare stock on hand went negative: {on_hand}"
    assert received == on_hand + reserved + consumed, (
        f"spare stock ledger broken: received {received} != on_hand {on_hand} + "
        f"reserved {reserved} + consumed {consumed}"
    )


def assert_serial_number(asset: dict, revision_code: str):
    """PRD §2.5: revision_code + '-' + sequence_no padded to five digits."""
    expected = f"{revision_code}-{asset['sequence_no']:05d}"
    assert asset["serial_number"] == expected, (
        f"Expected serial_number {expected}, got {asset['serial_number']}"
    )


def assert_success_envelope(body: dict, expected_response_type="object"):
    """PRD §2.2: every 2xx body carries meta.api_request_id, a request timestamp
    and a response_type."""
    assert body["response_type"] == expected_response_type, (
        f"Expected response_type {expected_response_type}, got {body['response_type']}"
    )
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    assert isinstance(meta.get("api_request_timestamp"), str)


def assert_error_envelope(body: dict):
    """PRD §2.2: every 4xx body carries response_type 'error' and a non-empty
    human-readable message."""
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["error_id"], str)
    assert isinstance(body["data"]["message"], str)
    assert len(body["data"]["message"].strip()) > 0
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert isinstance(meta.get("api_request_timestamp"), str)


def assert_ordered_by_created_at(rows: list):
    """PRD §2.3: list rows come back ordered by created_at ascending."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows not ordered by created_at ascending: {stamps}"
