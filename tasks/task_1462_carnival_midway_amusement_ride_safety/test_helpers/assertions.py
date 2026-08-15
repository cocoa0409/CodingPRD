"""Entity assertions and domain invariant checkers.

Each assert_* verifies the system-managed shape of a response payload against
the PRD's common-resource contract (section 2.5) plus entity-specific fields.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str, with_version: bool = True):
    assert isinstance(data, dict), f"{entity} payload must be an object"
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 timestamp"
    )
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            f"{entity}.updated_at must be an ISO 8601 timestamp"
        )
        assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_fair(data: dict):
    _assert_common(data, "Fair")
    for field in ("name", "operator_company_name", "location", "setup_start_date",
                  "opening_date", "closing_date", "teardown_end_date"):
        assert isinstance(data.get(field), str) and data[field], f"Fair.{field} required"
    assert isinstance(data.get("midway_capacity"), int)
    assert data.get("status") in ["SETUP", "PERMIT_REQUESTED", "PERMITTED", "TEARDOWN", "ARCHIVED"]


def assert_ride(data: dict):
    _assert_common(data, "Ride")
    assert isinstance(data.get("fair_id"), str)
    assert data.get("ride_class") in ["KIDDIE", "FAMILY", "THRILL", "EXTREME"]
    assert isinstance(data.get("capacity_per_cycle"), int)
    assert isinstance(data.get("min_rider_height_in"), int)
    assert isinstance(data.get("max_rider_height_in"), int)
    assert isinstance(data.get("wind_limit_mph"), int)
    assert isinstance(data.get("cycle_inspection_interval"), int)
    assert isinstance(data.get("cycles_since_inspection"), int)
    assert isinstance(data.get("minor_incidents_today"), int)
    assert data.get("setup_status") in ["INSTALLED", "SETUP_VERIFIED", "DISMANTLED"]
    assert data.get("license_status") in ["PENDING", "LICENSED", "SUSPENDED", "REVOKED"]
    assert data.get("daily_status") in ["CLOSED", "OPEN", "WEATHER_HOLD", "INCIDENT_HOLD"]


def assert_inspector(data: dict):
    _assert_common(data, "Inspector")
    assert isinstance(data.get("full_name"), str)
    assert isinstance(data.get("license_number"), str)
    assert isinstance(data.get("max_daily_inspections"), int)
    assert isinstance(data.get("active"), bool)


def assert_appointment(data: dict):
    _assert_common(data, "InspectionAppointment")
    assert isinstance(data.get("fair_id"), str)
    assert isinstance(data.get("inspector_id"), str)
    assert data.get("scope") in ["FAIR_WIDE", "RIDE_AUDIT"]
    assert isinstance(data.get("scheduled_date"), str)
    assert isinstance(data.get("start_hour"), int)
    assert isinstance(data.get("duration_hours"), int)
    assert data.get("status") in ["SCHEDULED", "COMPLETED_PASS", "COMPLETED_FAIL", "CANCELLED"]


def assert_permit(data: dict):
    _assert_common(data, "Permit")
    assert isinstance(data.get("fair_id"), str)
    assert data.get("status") in ["PENDING", "APPROVED", "DENIED"]
    assert isinstance(data.get("estimated_fee_cents"), int)


def assert_staff(data: dict):
    _assert_common(data, "StaffMember")
    assert isinstance(data.get("fair_id"), str)
    assert isinstance(data.get("full_name"), str)
    assert isinstance(data.get("functions"), list) and len(data["functions"]) > 0
    assert data.get("status") in ["ACTIVE", "RELEASED"]


def assert_certification(data: dict):
    _assert_common(data, "OperatorCertification")
    assert isinstance(data.get("staff_id"), str)
    assert data.get("ride_class") in ["KIDDIE", "FAMILY", "THRILL", "EXTREME"]
    assert data.get("status") in ["ACTIVE", "REVOKED"]


def assert_operating_day(data: dict):
    _assert_common(data, "OperatingDay")
    assert isinstance(data.get("fair_id"), str)
    assert isinstance(data.get("date"), str)
    assert isinstance(data.get("max_attendance"), int)
    assert data.get("posture") in ["SCHEDULED", "CHECKLIST_PHASE", "OPEN", "WEATHER_HOLD", "CLOSED", "RECONCILED"]
    assert isinstance(data.get("attendance_count"), int)


def assert_checklist(data: dict):
    _assert_common(data, "DailyChecklist")
    assert isinstance(data.get("ride_id"), str)
    assert isinstance(data.get("operating_day_id"), str)
    assert isinstance(data.get("performed_by_staff_id"), str)
    assert isinstance(data.get("items_total"), int)
    assert data.get("status") in ["DRAFT", "SUBMITTED", "COUNTERSIGNED"]


def assert_cycle(data: dict):
    _assert_common(data, "RideCycle")
    assert isinstance(data.get("ride_id"), str)
    assert isinstance(data.get("operating_day_id"), str)
    assert isinstance(data.get("operator_staff_id"), str)
    assert isinstance(data.get("sequence_number"), int)
    assert data.get("status") in ["LOADING", "RUNNING", "COMPLETED", "ABORTED"]
    assert isinstance(data.get("rider_count"), int)


def assert_redemption(data: dict):
    _assert_common(data, "RideRedemption")
    assert isinstance(data.get("wristband_id"), str)
    assert isinstance(data.get("ride_id"), str)
    assert isinstance(data.get("operating_day_id"), str)
    assert isinstance(data.get("queue_position"), int)
    assert data.get("status") in ["QUEUED", "REDEEMED", "VOIDED", "EXPIRED"]


def assert_product(data: dict):
    _assert_common(data, "TicketProduct")
    assert isinstance(data.get("fair_id"), str)
    assert data.get("kind") in ["RIDE_TICKET", "CREDIT_BUNDLE", "WRISTBAND"]
    assert isinstance(data.get("base_price_cents"), int)
    assert isinstance(data.get("active"), bool)


def assert_sale(data: dict):
    _assert_common(data, "TicketSale")
    assert isinstance(data.get("product_id"), str)
    assert isinstance(data.get("operating_day_id"), str)
    assert isinstance(data.get("clerk_staff_id"), str)
    assert isinstance(data.get("holder_height_in"), int)
    assert isinstance(data.get("quantity"), int)
    assert isinstance(data.get("is_unlimited"), bool)
    assert isinstance(data.get("subtotal_cents"), int)
    assert isinstance(data.get("service_fee_cents"), int)
    assert isinstance(data.get("total_charged_cents"), int)
    assert data.get("status") in ["ACTIVE", "VOIDED", "EXPIRED"]


def assert_observation(data: dict):
    """WeatherObservation is append-only: id + created_at only, no version."""
    assert isinstance(data, dict), "WeatherObservation payload must be an object"
    assert is_valid_uuid(data.get("id", "")), "WeatherObservation.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "WeatherObservation.created_at must be ISO 8601"
    )
    assert "version" not in data, "WeatherObservation must not expose version"
    assert "updated_at" not in data, "WeatherObservation must not expose updated_at"
    assert isinstance(data.get("operating_day_id"), str)
    assert isinstance(data.get("wind_speed_mph"), int)


def assert_incident(data: dict):
    _assert_common(data, "IncidentReport")
    assert isinstance(data.get("ride_id"), str)
    assert isinstance(data.get("operating_day_id"), str)
    assert isinstance(data.get("reporter_staff_id"), str)
    assert data.get("severity") in ["NEAR_MISS", "MINOR", "SERIOUS", "FATAL"]
    assert isinstance(data.get("injury_count"), int)
    assert data.get("status") in ["FILED", "CLEARED", "SHUTDOWN_ORDERED"]


def assert_shift(data: dict):
    _assert_common(data, "CrewShift")
    assert isinstance(data.get("staff_id"), str)
    assert isinstance(data.get("fair_id"), str)
    assert isinstance(data.get("work_date"), str)
    assert isinstance(data.get("start_hour"), int)
    assert isinstance(data.get("end_hour"), int)
    assert data.get("shift_role") in ["SETUP", "OPERATIONS", "TEARDOWN"]
    assert data.get("status") in ["SCHEDULED", "CONFIRMED", "COMPLETED", "NO_SHOW", "CANCELLED"]


def assert_credit_conservation(sale: dict):
    """PRD section 3.6: granted == remaining + redeemed + forfeited for
    credit-bearing sales (wristbands carry null ledgers instead)."""
    if sale.get("is_unlimited"):
        return
    granted = sale.get("credits_granted")
    remaining = sale.get("credits_remaining")
    redeemed = sale.get("credits_redeemed")
    forfeited = sale.get("credits_forfeited")
    for label, value in (("credits_granted", granted), ("credits_remaining", remaining),
                         ("credits_redeemed", redeemed), ("credits_forfeited", forfeited)):
        assert isinstance(value, int), f"TicketSale.{label} must be an integer, got {value!r}"
    assert granted == remaining + redeemed + forfeited, (
        f"Credit conservation violated: granted {granted} != remaining {remaining} "
        f"+ redeemed {redeemed} + forfeited {forfeited}"
    )
