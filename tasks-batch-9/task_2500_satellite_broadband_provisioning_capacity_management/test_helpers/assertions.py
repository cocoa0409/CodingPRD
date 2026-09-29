"""Entity assertions and domain invariant checkers for the Satellite Broadband API."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# ─────────────────────── shared structural helpers ───────────────────

def assert_common_fields(data: dict) -> None:
    """Most records expose id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def assert_append_only_fields(data: dict) -> None:
    """Append-only event records expose only id and created_at from the common set."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "append-only records have no updated_at"
    assert "version" not in data, "append-only records have no version"


def assert_millisecond_timestamp(value: str) -> None:
    """Every emitted instant is ISO 8601 UTC with exactly three fractional digits."""
    assert isinstance(value, str), f"expected a timestamp string, got {value!r}"
    assert is_iso8601_timestamp(value), f"not a valid ISO 8601 UTC instant: {value!r}"
    assert value.endswith("Z"), f"timestamp must end in Z: {value!r}"
    assert len(value) == 24 and value[19] == ".", (
        f"timestamp must carry exactly three fractional digits: {value!r}"
    )


# ─────────────────────────── entity shapes ───────────────────────────

def assert_spectrum_license(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["license_code"], str) and 1 <= len(data["license_code"]) <= 40
    assert isinstance(data["jurisdiction_code"], str)
    assert data["frequency_band"] in ("KA_FORWARD", "KU_FORWARD", "KA_RETURN")
    assert float(data["max_eirp_dbw"]) > 0
    assert is_iso8601_timestamp(data["expires_at"])
    assert isinstance(data["consumer_disclosure_version"], str)
    assert isinstance(data["in_motion_permitted"], bool)
    assert data["license_state"] in (
        "PENDING_COORDINATION", "ACTIVE", "SUSPENDED", "REFUSED", "EXPIRED",
    )
    assert data["coordination_state"] in ("UNCOORDINATED", "COORDINATED", "REFUSED")


def assert_beam(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["beam_code"], str) and 1 <= len(data["beam_code"]) <= 40
    assert isinstance(data["satellite_code"], str)
    assert is_valid_uuid(data["spectrum_license_id"])
    assert float(data["forward_capacity_mbps"]) > 0
    assert 1.0 <= float(data["oversubscription_limit"]) <= 20.0
    assert int(data["deprioritization_grace_gb"]) >= 0
    assert float(data["weighted_sold_mbps"]) >= 0
    assert float(data["oversubscription_ratio"]) >= 0
    assert data["capacity_state"] in ("NORMAL", "CONSTRAINED", "SATURATED")
    assert data["beam_state"] in ("ACTIVE", "SUSPENDED")
    assert int(data["billing_cycle_index"]) >= 0


def assert_service_cell(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["cell_code"], str) and 1 <= len(data["cell_code"]) <= 40
    assert is_valid_uuid(data["beam_id"])
    assert isinstance(data["jurisdiction_code"], str)
    assert int(data["max_active_terminals"]) >= 0
    assert_cell_ledger_invariants(data)
    assert data["availability_state"] in ("AVAILABLE", "WAITLIST_ONLY", "CLOSED")


def assert_service_plan(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["plan_code"], str) and 1 <= len(data["plan_code"]) <= 40
    assert float(data["committed_rate_mbps"]) > 0
    assert data["priority_tier"] in ("PRIORITY_1", "PRIORITY_2", "BEST_EFFORT")
    assert int(data["monthly_fee_cents"]) > 0
    assert int(data["priority_data_gb"]) >= 0
    assert float(data["deprioritized_rate_mbps"]) > 0
    assert int(data["overage_rate_cents_per_gb"]) >= 0
    assert isinstance(data["roaming_allowed"], bool)
    assert isinstance(data["in_motion_allowed"], bool)


def assert_subscriber(data: dict) -> None:
    assert_common_fields(data)
    assert "@" in data["email"]
    assert isinstance(data["full_name"], str)
    assert isinstance(data["jurisdiction_code"], str)
    assert data["account_state"] in (
        "PROSPECT", "WAITLISTED", "ACTIVE", "SUSPENDED", "CLOSED",
    )
    assert_subscriber_ledger_invariants(data)


def assert_service_order(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["subscriber_id"])
    assert is_valid_uuid(data["service_cell_id"])
    assert is_valid_uuid(data["requested_plan_id"])
    assert data["order_state"] in (
        "PENDING_DETERMINATION", "RESERVED", "WAITLISTED",
        "ACTIVATED", "EXPIRED", "CANCELLED",
    )


def assert_terminal(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["serial_number"], str) and 1 <= len(data["serial_number"]) <= 40
    assert is_valid_uuid(data["subscriber_id"])
    assert is_iso8601_timestamp(data["warranty_expires_at"])
    assert data["terminal_state"] in (
        "SHIPPED", "DELIVERED", "INSTALLED", "TRANSFER_PENDING",
        "RMA_PENDING", "RETURN_INITIATED", "RETURNED", "REPLACED",
    )
    if data.get("last_scan_verdict"):
        assert data["last_scan_verdict"] in ("PASS", "MARGINAL", "FAIL")
    if data.get("return_condition"):
        assert data["return_condition"] in ("GOOD", "DAMAGED")


def assert_obstruction_scan(data: dict) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(data["terminal_id"])
    assert int(data["obstructed_sample_count"]) >= 0
    assert int(data["total_sample_count"]) > 0
    assert int(data["obstructed_sample_count"]) <= int(data["total_sample_count"])
    assert data["scan_verdict"] in ("PASS", "MARGINAL", "FAIL")
    assert is_iso8601_timestamp(data["scanned_at"])


def assert_subscription(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["subscriber_id"])
    assert is_valid_uuid(data["service_order_id"])
    assert is_valid_uuid(data["service_cell_id"])
    assert is_valid_uuid(data["service_plan_id"])
    assert is_valid_uuid(data["terminal_id"])
    assert data["service_state"] in (
        "PENDING_ACTIVATION", "ACTIVE", "SUSPENDED", "TERMINATED",
    )
    assert data["authorization_state"] in (
        "UNAUTHORIZED", "AUTHORIZED_FIXED", "AUTHORIZED_IN_MOTION", "DEAUTHORIZED",
    )
    assert data["priority_state"] in ("PRIORITY", "DEPRIORITIZED")
    assert data["disclosure_ack_state"] in ("PENDING_ACK", "ACKNOWLEDGED", "EXPIRED")
    assert float(data["cycle_priority_gb_used"]) >= 0
    assert int(data["cycle_billing_index"]) >= 0
    assert int(data["cycle_charge_cents"]) >= 0
    assert float(data["effective_rate_mbps"]) > 0


def assert_usage_record(data: dict) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(data["subscription_id"])
    assert int(data["billing_cycle_index"]) >= 0
    assert float(data["gb_used"]) >= 0
    assert isinstance(data["counted"], bool)
    assert is_iso8601_timestamp(data["recorded_at"])


def assert_roaming_authorization(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["subscription_id"])
    assert data["mode"] in ("PORTABILITY_MOVE", "ROAM_TEMPORARY", "IN_MOTION")
    assert isinstance(data["target_jurisdiction_code"], str)
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_until"])
    assert data["auth_state"] in (
        "REQUESTED", "NEEDS_INFO", "APPROVED", "DENIED", "REVOKED",
    )
    assert 0 <= int(data["info_round_count"]) <= 3


def assert_outage_event(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["beam_id"])
    assert data["cause"] in (
        "WEATHER_RAIN_FADE", "EQUIPMENT_FAILURE",
        "SPECTRUM_INTERFERENCE", "PLANNED_MAINTENANCE",
    )
    assert data["severity"] in ("FULL_OUTAGE", "DEGRADATION")
    assert is_iso8601_timestamp(data["started_at"])
    assert data["event_state"] in ("OPEN", "RESOLVED")
    assert int(data["generated_credit_count"]) >= 0


def assert_outage_credit(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["subscription_id"])
    assert is_valid_uuid(data["outage_event_id"])
    assert int(data["provisional_credit_cents"]) >= 0
    assert data["credit_state"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")


# ───────────────────── domain invariant checkers ─────────────────────

def assert_cell_ledger_invariants(cell: dict) -> None:
    """The free slot figure is the ceiling less commitments less holds, floored at 0
    so it is never negative.

    A cell that has never been written past creation is exempt from the derivation:
    the contract says all four counters start at 0 on a brand-new cell, and only
    states that the figure is recomputed when a later write moves the ledger.
    """
    for field in (
        "committed_terminal_count", "reserved_slot_count",
        "free_slot_count", "waitlist_depth",
    ):
        assert isinstance(cell[field], int), f"{field} must be an integer"
        assert cell[field] >= 0, f"{field} must never be negative, got {cell[field]}"
    untouched_since_creation = (
        cell.get("version") == 1
        and cell["committed_terminal_count"] == 0
        and cell["reserved_slot_count"] == 0
        and cell["waitlist_depth"] == 0
    )
    if untouched_since_creation:
        assert cell["free_slot_count"] in (0, max(0, cell["max_active_terminals"])), (
            "a brand-new cell reports its free slot figure either as 0 or as its "
            f"full ceiling, got {cell['free_slot_count']}"
        )
        return
    expected_free = max(
        0,
        cell["max_active_terminals"]
        - cell["committed_terminal_count"]
        - cell["reserved_slot_count"],
    )
    assert cell["free_slot_count"] == expected_free, (
        f"free_slot_count should be max(0, {cell['max_active_terminals']} - "
        f"{cell['committed_terminal_count']} - {cell['reserved_slot_count']}) = "
        f"{expected_free}, got {cell['free_slot_count']}"
    )


def assert_beam_congestion_band(beam: dict) -> None:
    """capacity_state is the congestion band read off the ratio against the limit:
    NORMAL at or below three quarters of the limit, CONSTRAINED above that but at
    or below the limit, SATURATED strictly above the limit."""
    ratio = float(beam["oversubscription_ratio"])
    limit = float(beam["oversubscription_limit"])
    if ratio <= 0.75 * limit:
        expected = "NORMAL"
    elif ratio <= limit:
        expected = "CONSTRAINED"
    else:
        expected = "SATURATED"
    assert beam["capacity_state"] == expected, (
        f"ratio {ratio} against limit {limit} should band as {expected}, "
        f"got {beam['capacity_state']}"
    )


def assert_subscriber_ledger_invariants(subscriber: dict) -> None:
    """All three account ledgers are integer cents and never negative."""
    for field in ("credit_balance_cents", "pending_credit_cents", "pending_charge_cents"):
        assert isinstance(subscriber[field], int), f"{field} must be integer cents"
        assert subscriber[field] >= 0, f"{field} must never be negative, got {subscriber[field]}"


def assert_availability_projection(data: dict) -> None:
    """Shape of an availability determination response."""
    assert is_valid_uuid(data["service_cell_id"])
    assert data["availability_state"] in ("AVAILABLE", "WAITLIST_ONLY", "CLOSED")
    for field in (
        "advertised_free_slot_count", "committed_terminal_count",
        "reserved_slot_count", "waitlist_depth", "waitlist_cap",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0, f"{field} must never be negative"
    assert data["beam_capacity_state"] in ("NORMAL", "CONSTRAINED", "SATURATED")
    assert data["beam_state"] in ("ACTIVE", "SUSPENDED")


def assert_cycle_close_report(data: dict) -> None:
    """Shape of the billing-cycle-close ops-run report."""
    assert is_valid_uuid(data["beam_id"])
    assert isinstance(data["billing_cycle_index"], int)
    assert isinstance(data["license_expired"], bool)
    for field in (
        "disclosure_expired_count", "expired_order_count",
        "charged_subscription_count", "restored_subscription_count",
        "promoted_order_count",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0, f"{field} must never be negative"
    assert data["capacity_state"] in ("NORMAL", "CONSTRAINED", "SATURATED")
