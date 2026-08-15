"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

from .types import (
    AdvisorySeverity,
    BookingStatus,
    CancellationReason,
    CertificateStatus,
    ChargeLineType,
    ChargeStatus,
    CleaningTurnStatus,
    DepositStatus,
    IncidentResolution,
    IncidentStatus,
    IncidentType,
    IssuingAuthority,
    ItineraryStatus,
    MaintenanceWindowSource,
    MaintenanceWindowStatus,
    OrientationStatus,
    QualificationStatus,
    Season,
    SettlementStatus,
    Severity,
    SizeClass,
    VesselStatus,
    WeatherAdvisoryStatus,
)


def _assert_common_fields(data: dict):
    """Every resource carries the four system-managed fields (PRD common
    resource properties): a prefix-less UUID id, ISO 8601 UTC timestamps with
    three fractional digits, and an integer version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_vessel(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["size_class"] in {c.value for c in SizeClass}
    assert isinstance(data["berth_count"], int) and data["berth_count"] >= 1
    assert isinstance(data["home_marina"], str)
    assert isinstance(data["fuel_tank_capacity_gallons"], int) \
        and data["fuel_tank_capacity_gallons"] > 0
    assert data["status"] in {s.value for s in VesselStatus}


def assert_season_rate(data: dict):
    _assert_common_fields(data)
    assert data["size_class"] in {c.value for c in SizeClass}
    assert data["season"] in {s.value for s in Season}
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["nightly_rate_cents"], int) and data["nightly_rate_cents"] > 0
    assert isinstance(data["weekly_discount_pct"], int) \
        and 0 <= data["weekly_discount_pct"] <= 50


def assert_geo_zone(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["zone_code"], str) and data["zone_code"]
    assert isinstance(data["name"], str)
    assert isinstance(data["max_vessels_per_night"], int) \
        and data["max_vessels_per_night"] >= 1
    assert isinstance(data["allowed_size_classes"], list)
    assert all(c in {sc.value for sc in SizeClass} for c in data["allowed_size_classes"])


def assert_renter(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str)
    assert isinstance(data["date_of_birth"], str)
    assert data["qualification_status"] in {s.value for s in QualificationStatus}
    assert isinstance(data["risk_score_lifetime"], int) and data["risk_score_lifetime"] >= 0
    assert isinstance(data["risk_score_rolling_24m"], int) \
        and data["risk_score_rolling_24m"] >= 0
    assert data["deposit_multiplier"] in (1.0, 1.5, 2.0)


def assert_certificate(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["renter_id"], str)
    assert isinstance(data["cert_number"], str)
    assert data["issuing_authority"] in {a.value for a in IssuingAuthority}
    assert isinstance(data["issued_on"], str)
    assert isinstance(data["expires_on"], str)
    assert data["status"] in {s.value for s in CertificateStatus}


def assert_booking(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vessel_id"], str)
    assert isinstance(data["renter_id"], str)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    # Four parallel state dimensions
    assert data["status"] in {s.value for s in BookingStatus}
    assert data["settlement_status"] in {s.value for s in SettlementStatus}
    assert data["deposit_status"] in {s.value for s in DepositStatus}
    assert data["orientation_status"] in {s.value for s in OrientationStatus}
    # Ledger-derived money fields are integer cents
    for field in ("quoted_total_cents", "deposit_required_cents", "deposit_held_cents",
                  "deposit_applied_cents", "deposit_released_cents",
                  "refund_issued_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert isinstance(data["total_nights"], int) and data["total_nights"] >= 1
    assert isinstance(data["hold_expires_at"], str)
    reason = data.get("cancellation_reason")
    assert reason is None or reason in {r.value for r in CancellationReason}


def assert_itinerary(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["booking_id"], str)
    assert isinstance(data["waypoints"], list)
    for wp in data["waypoints"]:
        assert isinstance(wp.get("zone_id"), str)
        assert isinstance(wp.get("night_date"), str)
    assert data["status"] in {s.value for s in ItineraryStatus}


def assert_charge(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["booking_id"], str)
    assert data["line_type"] in {t.value for t in ChargeLineType}
    assert isinstance(data["amount_cents"], int), "amount_cents must be integer cents"
    assert data["amount_cents"] != 0, "zero-amount lines are never posted"
    assert data["status"] in {s.value for s in ChargeStatus}


def assert_incident(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["booking_id"], str)
    assert data["incident_type"] in {t.value for t in IncidentType}
    assert isinstance(data["occurred_at"], str)
    assert data["status"] in {s.value for s in IncidentStatus}
    if data["status"] == IncidentStatus.RESOLVED.value:
        assert data["severity"] in {s.value for s in Severity}
        assert data["resolution"] in {r.value for r in IncidentResolution
                                      if r != IncidentResolution.REJECTED}
    if data["status"] == IncidentStatus.REPORTED.value:
        assert data.get("severity") is None
        assert data.get("resolution") is None


def assert_maintenance_window(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vessel_id"], str)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["source"] in {s.value for s in MaintenanceWindowSource}
    assert data["status"] in {s.value for s in MaintenanceWindowStatus}


def assert_cleaning_turn(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["booking_id"], str)
    assert isinstance(data["scheduled_date"], str)
    assert data["status"] in {s.value for s in CleaningTurnStatus}
    assert isinstance(data["re_clean_count"], int) and data["re_clean_count"] >= 0


def assert_weather_advisory(data: dict):
    _assert_common_fields(data)
    assert data["severity"] in {s.value for s in AdvisorySeverity}
    assert isinstance(data["zone_ids"], list) and len(data["zone_ids"]) >= 1
    assert isinstance(data["window_start"], str)
    assert isinstance(data["window_end"], str)
    assert data["status"] in {s.value for s in WeatherAdvisoryStatus}


def assert_deposit_invariants(booking: dict):
    """Deposit conservation: at any terminal deposit state, applied plus
    released always equals the held amount (PRD hard invariant)."""
    if booking["deposit_status"] in (
        DepositStatus.RELEASED.value,
        DepositStatus.PARTIALLY_APPLIED.value,
        DepositStatus.FULLY_APPLIED.value,
    ):
        applied = booking["deposit_applied_cents"]
        released = booking["deposit_released_cents"]
        held = booking["deposit_held_cents"]
        assert applied + released == held, (
            f"deposit conservation violated: applied {applied} + released {released} "
            f"!= held {held}"
        )


def find_charge(charges: list, line_type: str) -> dict:
    """Return the single charge of the given line_type (fails if absent)."""
    matches = [c for c in charges if c.get("line_type") == line_type]
    assert matches, f"expected a {line_type} charge line, got {charges!r}"
    return matches[0]


def charge_amounts(charges: list, line_type: str) -> list:
    return [c["amount_cents"] for c in charges if c.get("line_type") == line_type]
