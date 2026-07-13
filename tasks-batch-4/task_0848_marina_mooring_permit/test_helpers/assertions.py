"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict, append_only: bool = False):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')}"
    if not append_only:
        assert "updated_at" in data, "resource must carry updated_at"
        assert isinstance(data.get("version"), int), "version must be an int"


def assert_marina(data: dict):
    _common(data)
    assert isinstance(data["name"], str) and data["name"]
    for counter in (
        "available_slip_count",
        "occupied_slip_count",
        "available_mooring_count",
        "occupied_mooring_count",
        "liveaboard_count",
        "waitlist_length",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, counter


def assert_berth(data: dict):
    _common(data)
    assert data["berth_type"] in ("SLIP", "MOORING")
    assert data["size_class"] in ("SMALL", "MEDIUM", "LARGE")
    assert data["status"] in ("AVAILABLE", "RESERVED", "OCCUPIED", "OUT_OF_SERVICE")


def assert_boater(data: dict):
    _common(data)
    assert data["residency_status"] in ("RESIDENT", "NON_RESIDENT")
    assert data["account_status"] == "ACTIVE"


def assert_vessel(data: dict):
    _common(data)
    assert data["registration_status"] in ("REGISTERED", "EXPIRED", "REVOKED")
    assert data["pumpout_status"] in ("COMPLIANT", "OVERDUE", "NA")


def assert_permit(data: dict):
    _common(data)
    assert data["status"] in (
        "WAITLISTED", "OFFERED", "ACTIVE", "SUSPENDED", "EXPIRED",
        "REVOKED", "TRANSFERRED", "CANCELLED", "DECLINED",
    )
    assert data["fee_basis"] in ("RESIDENT", "NON_RESIDENT")
    assert data["priority_tier"] in (0, 1)


def assert_pumpout_record(data: dict):
    # Append-only: no updated_at / version (PRD §2.4).
    _common(data, append_only=True)
    assert "updated_at" not in data, "pump-out record must NOT carry updated_at"
    assert "version" not in data, "pump-out record must NOT carry version"


def assert_derelict_report(data: dict):
    _common(data)
    assert data["status"] in ("OPEN", "NOTICE_SERVED", "RESOLVED", "IMPOUNDED")


def assert_ramp_pass(data: dict):
    _common(data)
    assert data["status"] in ("ACTIVE", "EXPIRED", "REVOKED")


def assert_lottery_round(data: dict):
    _common(data)
    assert data["status"] in ("OPEN", "DRAWN", "CLOSED")


def assert_lottery_entry(data: dict):
    _common(data)
    assert data["status"] in ("ENTERED", "WON", "LOST", "CLAIMED", "FORFEITED")


def assert_invoice(data: dict):
    _common(data)
    assert data["invoice_type"] in ("PERMIT", "RAMP_PASS", "DERELICT", "TRANSFER")
    assert data["status"] in (
        "UNPAID", "PAID", "PARTIALLY_REFUNDED", "REFUNDED", "VOID", "WAIVED",
    )


def assert_occupancy_conserved(marina: dict, expected_available_slip, expected_occupied_slip):
    """Berth-occupancy conservation invariant (PRD §2.7)."""
    assert marina["available_slip_count"] == expected_available_slip, (
        f"available_slip_count {marina['available_slip_count']} != {expected_available_slip}"
    )
    assert marina["occupied_slip_count"] == expected_occupied_slip, (
        f"occupied_slip_count {marina['occupied_slip_count']} != {expected_occupied_slip}"
    )
