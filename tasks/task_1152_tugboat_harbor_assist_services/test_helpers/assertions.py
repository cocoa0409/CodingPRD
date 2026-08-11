"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ─── Helpers ──────────────────────────────────────────


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(
            data.get("updated_at", "")
        ), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1


# ─── Entity assertions ────────────────────────────────


def assert_vessel(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["imo_number"], str) and len(data["imo_number"]) > 0
    assert isinstance(data["deadweight_tonnage"], int) and data["deadweight_tonnage"] > 0
    assert isinstance(data["loa_meters"], (int, float)) and data["loa_meters"] > 0
    assert isinstance(data["outstanding_billed_cents"], int)
    assert data["outstanding_billed_cents"] >= 0


def assert_tug(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["bollard_pull_tons"], (int, float))
    assert data["bollard_pull_tons"] > 0
    assert isinstance(data["horsepower"], int) and data["horsepower"] > 0
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 0
    assert isinstance(data["insured_value_cents"], int)
    assert data["operational_status"] in ("AVAILABLE", "RESTRICTED", "OUT_OF_SERVICE")


def assert_pilot(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["license_class"] in ("CLASS_I", "CLASS_II", "CLASS_III")
    assert isinstance(data["active"], bool)


def assert_crew_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["crew_role"] in ("CAPTAIN", "MATE", "ENGINEER", "DECKHAND")
    assert isinstance(data["max_watch_hours"], int)


def assert_tariff_rate(data: dict):
    _assert_common(data)
    assert isinstance(data["tariff_code"], str) and len(data["tariff_code"]) > 0
    assert data["maneuver_type"] in (
        "DOCKING",
        "UNDOCKING",
        "SHIFTING",
        "ESCORT",
        "TOWAGE",
    )
    assert isinstance(data["base_fee_cents"], int) and data["base_fee_cents"] >= 0
    assert isinstance(data["free_standby_minutes"], int)
    assert isinstance(data["standby_block_minutes"], int)
    assert isinstance(data["standby_block_rate_cents"], int)
    assert isinstance(data["weather_surcharge_pct"], (int, float))
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])


def assert_job_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["vessel_id"])
    assert is_valid_uuid(data["tariff_rate_id"])
    assert data["maneuver_type"] in (
        "DOCKING",
        "UNDOCKING",
        "SHIFTING",
        "ESCORT",
        "TOWAGE",
    )
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert isinstance(data["required_bollard_pull_tons"], (int, float))
    assert data["status"] in (
        "REQUESTED",
        "CONFIRMED",
        "DISPATCHED",
        "ON_HOLD",
        "IN_PROGRESS",
        "COMPLETED",
        "INVOICED",
        "CANCELLED",
    )
    assert isinstance(data["had_weather_hold"], bool)
    assert isinstance(data["needs_reassignment"], bool)


def assert_tug_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["job_order_id"])
    assert is_valid_uuid(data["tug_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["participated"], bool)
    assert data["status"] in (
        "PROPOSED",
        "CONFIRMED",
        "ACTIVE",
        "RELEASED",
        "SUPERSEDED",
    )


def assert_pilot_booking(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["job_order_id"])
    assert is_valid_uuid(data["pilot_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in (
        "REQUESTED",
        "CONFIRMED",
        "BOARDED",
        "COMPLETED",
        "NO_SHOW",
        "CANCELLED",
        "SUPERSEDED",
    )


def assert_watch_rotation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["tug_assignment_id"])
    assert is_valid_uuid(data["crew_member_id"])
    assert is_iso8601_timestamp(data["watch_start"])
    assert is_iso8601_timestamp(data["watch_end"])


def assert_gear_inspection(data: dict):
    # Append-only log: id + created_at, NO updated_at, NO version.
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "GearInspection must not carry a version field"
    assert "updated_at" not in data, "GearInspection must not carry an updated_at field"
    assert is_valid_uuid(data["tug_id"])
    assert data["inspection_item"] in ("TOWING_HOOK", "TOW_LINE", "WINCH", "BITTS")
    assert data["outcome"] in ("PASSED", "FAILED")
    assert is_iso8601_timestamp(data["inspected_at"])
    assert is_iso8601_timestamp(data["next_due_at"])


def assert_incident(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["tug_id"])
    assert data["incident_type"] in (
        "GEAR_FAILURE",
        "CONTACT_DAMAGE",
        "POLLUTION",
        "PERSONAL_INJURY",
    )
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL")
    assert is_iso8601_timestamp(data["occurred_at"])
    assert isinstance(data["description"], str)
    assert data["status"] in ("REPORTED", "UNDER_INVESTIGATION", "RESOLVED")


def assert_weather_restriction(data: dict):
    _assert_common(data)
    assert data["restriction_type"] in ("WIND", "CURRENT", "VISIBILITY")
    assert isinstance(data["threshold_value"], (int, float))
    assert isinstance(data["port_area"], str)
    assert is_iso8601_timestamp(data["effective_start"])
    assert is_iso8601_timestamp(data["effective_end"])
    assert data["status"] in ("ACTIVE", "LIFTED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["job_order_id"])
    assert data["status"] in ("PROVISIONAL", "FINALIZED", "VOID")
    assert data["variant_basis"] in ("SCHEDULED", "ACTUAL")
    assert isinstance(data["base_fee_cents"], int)
    assert isinstance(data["tug_hire_cents"], int)
    assert isinstance(data["standby_minutes"], int)
    assert isinstance(data["standby_cents"], int)
    assert isinstance(data["weather_surcharge_cents"], int)
    assert isinstance(data["total_cents"], int)


def assert_damage_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["incident_id"])
    assert is_valid_uuid(data["vessel_id"])
    assert isinstance(data["claimed_amount_cents"], int)
    assert data["liability_variant"] in ("PER_INCIDENT", "PER_VOYAGE")
    assert isinstance(data["liability_cap_cents"], int)
    assert isinstance(data["deductible_cents"], int)
    assert isinstance(data["payout_cents"], int)
    assert data["status"] in ("FILED", "UNDER_REVIEW", "ACCEPTED", "DENIED", "SETTLED")


# ─── Domain invariants ────────────────────────────────


def assert_vessel_outstanding_nonnegative(vessel: dict):
    """Vessel.outstanding_billed_cents is floored at zero per the billing ledger rule."""
    assert vessel["outstanding_billed_cents"] >= 0


def assert_invoice_lines_consistent(invoice: dict):
    """total_cents == base_fee + tug_hire + standby + weather_surcharge."""
    expected = (
        invoice["base_fee_cents"]
        + invoice["tug_hire_cents"]
        + invoice["standby_cents"]
        + invoice["weather_surcharge_cents"]
    )
    assert invoice["total_cents"] == expected, (
        f"Invoice total {invoice['total_cents']} does not equal sum of lines {expected}"
    )


def assert_claim_payout_consistent(claim: dict):
    """payout == min(claimed, cap) - deductible per the pinned evaluation order."""
    capped = min(claim["claimed_amount_cents"], claim["liability_cap_cents"])
    assert claim["payout_cents"] == capped - claim["deductible_cents"]
