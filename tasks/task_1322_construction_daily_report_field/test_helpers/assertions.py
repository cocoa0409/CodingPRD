"""Entity assertions and domain invariant checkers.

Per PRD section 2.4, primary resources carry id/created_at/updated_at/version.
WeatherObservation is the deliberate exception: it carries id and created_at
only, and both updated_at and version are absent from it.
"""
from datetime import datetime, timezone

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value: str) -> datetime:
    assert isinstance(value, str), f"expected ISO 8601 string, got {value!r}"
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_instant_equal(actual, expected, msg: str = ""):
    """Compare two ISO 8601 UTC timestamps by the instant they denote.

    PRD pins the instant of computed/stamped timestamps (e.g. section 3.5: the
    osha_notification_deadline "falls eight hours after occurrence"; section
    2.5: the clock "answers with the resulting current_utc") but never pins the
    string serialization of these non-audit fields, so any ISO 8601 UTC
    rendering of the same instant must compare equal.
    """
    assert _parse_instant(actual) == _parse_instant(expected), (
        msg or f"instant mismatch: {actual!r} != {expected!r}")


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def _assert_append_only_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity} must not carry updated_at"
    assert "version" not in data, f"{entity} must not carry version"


def assert_project(data: dict):
    _assert_common_fields(data, "Project")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contract_number"], str) and data["contract_number"]
    assert data["status"] in ("MOBILIZING", "ACTIVE", "SUSPENDED", "CLOSED")


def assert_work_area(data: dict):
    _assert_common_fields(data, "WorkArea")
    assert is_valid_uuid(data.get("project_id", "")), "WorkArea.project_id must be a UUID"
    assert isinstance(data["code"], str) and data["code"]
    assert data["status"] in ("OPEN", "CLOSED")


def assert_delivery_zone(data: dict):
    _assert_common_fields(data, "DeliveryZone")
    assert is_valid_uuid(data.get("project_id", "")), "DeliveryZone.project_id must be a UUID"
    assert isinstance(data["zone_code"], str) and data["zone_code"]
    assert isinstance(data["buffer_minutes"], int)
    assert data["buffer_minutes"] >= 0
    assert data["status"] in ("OPEN", "CLOSED")


def assert_work_item(data: dict):
    _assert_common_fields(data, "WorkItem")
    assert is_valid_uuid(data.get("project_id", "")), "WorkItem.project_id must be a UUID"
    assert isinstance(data["cost_code"], str) and data["cost_code"]
    assert data["unit"] in ("LF", "SF", "CY", "EA", "TON", "GAL")
    assert isinstance(data["unit_cost_cents"], int)
    assert data["status"] in ("NOT_STARTED", "IN_PROGRESS", "COMPLETE")
    assert data["installed_to_date"] == pytest.approx(
        data.get("installed_to_date", 0), abs=1e-9)


def assert_daily_report(data: dict):
    _assert_common_fields(data, "DailyReport")
    assert is_valid_uuid(data.get("project_id", "")), "DailyReport.project_id must be a UUID"
    assert isinstance(data["report_date"], str) and len(data["report_date"]) == 10
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED", "REVISION_REQUESTED", "LOCKED")
    assert data["content_posture"] in ("EDITABLE", "SEALED")
    # PRD section 2.6: posture is EDITABLE iff status is DRAFT or REVISION_REQUESTED.
    if data["status"] in ("DRAFT", "REVISION_REQUESTED"):
        assert data["content_posture"] == "EDITABLE"
    else:
        assert data["content_posture"] == "SEALED"
    assert isinstance(data["revision_count"], int)
    assert isinstance(data["has_open_incident"], bool)
    assert isinstance(data["distribution_hold"], bool)
    assert data["retention_class"] in ("STANDARD", "CLAIMS_HOLD")
    assert isinstance(data["total_workers"], int)


def assert_crew_entry(data: dict):
    _assert_common_fields(data, "CrewEntry")
    assert is_valid_uuid(data.get("report_id", "")), "CrewEntry.report_id must be a UUID"
    assert is_valid_uuid(data.get("work_area_id", "")), "CrewEntry.work_area_id must be a UUID"
    assert isinstance(data["worker_count"], int) and data["worker_count"] >= 1
    assert 0 <= data["hours_per_worker"] <= 24
    assert data["status"] in ("ACTIVE", "VOIDED")
    for f in ("regular_hours", "ot_hours", "dt_hours"):
        assert isinstance(data[f], (int, float)), f"CrewEntry.{f} must be numeric"


def assert_equipment_entry(data: dict):
    _assert_common_fields(data, "EquipmentEntry")
    assert is_valid_uuid(data.get("report_id", "")), "EquipmentEntry.report_id must be a UUID"
    assert is_valid_uuid(data.get("work_area_id", "")), "EquipmentEntry.work_area_id must be a UUID"
    assert isinstance(data["unit_count"], int) and data["unit_count"] >= 1
    assert data["status"] in ("ACTIVE", "VOIDED")


def assert_weather_observation(data: dict):
    """Append-only log row: id + created_at only (PRD section 2.4)."""
    _assert_append_only_fields(data, "WeatherObservation")
    assert is_valid_uuid(data.get("report_id", "")), "WeatherObservation.report_id must be a UUID"
    assert data["condition"] in (
        "CLEAR", "CLOUDY", "RAIN", "SNOW", "WIND", "EXTREME_HEAT", "EXTREME_COLD")
    assert data["work_impact"] in ("NONE", "PARTIAL", "STOPPAGE")


def assert_delay_event(data: dict):
    _assert_common_fields(data, "DelayEvent")
    assert is_valid_uuid(data.get("report_id", "")), "DelayEvent.report_id must be a UUID"
    assert is_valid_uuid(data.get("work_area_id", "")), "DelayEvent.work_area_id must be a UUID"
    assert data["cause"] in ("WEATHER", "OWNER", "MATERIAL", "LABOR", "EQUIPMENT", "OTHER")
    assert data["status"] in ("RECORDED", "CLASSIFIED", "DISPUTED", "FINAL")
    if data["status"] in ("CLASSIFIED", "FINAL"):
        assert data["classification"] in (
            "EXCUSABLE_COMPENSABLE", "EXCUSABLE_NON_COMPENSABLE",
            "NON_EXCUSABLE", "CONCURRENT")


def assert_safety_observation(data: dict):
    _assert_common_fields(data, "SafetyObservation")
    assert is_valid_uuid(data.get("report_id", "")), "SafetyObservation.report_id must be a UUID"
    assert is_valid_uuid(data.get("work_area_id", "")), \
        "SafetyObservation.work_area_id must be a UUID"
    assert data["risk_level"] in ("LOW", "MEDIUM", "HIGH")
    assert data["status"] in ("OPEN", "MITIGATED", "VERIFIED_CLOSED", "ESCALATED")


def assert_incident(data: dict):
    _assert_common_fields(data, "Incident")
    assert is_valid_uuid(data.get("report_id", "")), "Incident.report_id must be a UUID"
    assert is_valid_uuid(data.get("work_area_id", "")), "Incident.work_area_id must be a UUID"
    assert data["severity"] in (
        "FIRST_AID", "NEAR_MISS", "PROPERTY_DAMAGE",
        "MEDICAL_TREATMENT", "LOST_TIME", "FATALITY")
    assert data["status"] in (
        "REPORTED", "UNDER_INVESTIGATION", "OSHA_NOTIFIED",
        "CLOSED_RECORDABLE", "CLOSED_NOT_RECORDABLE")
    assert isinstance(data["recordable"], bool)
    # PRD section 3.5: recordable iff severity in the recordable trio.
    assert data["recordable"] == (
        data["severity"] in ("MEDICAL_TREATMENT", "LOST_TIME", "FATALITY"))


def assert_media_attachment(data: dict):
    _assert_common_fields(data, "MediaAttachment")
    assert is_valid_uuid(data.get("report_id", "")), "MediaAttachment.report_id must be a UUID"
    assert is_valid_uuid(data.get("work_area_id", "")), \
        "MediaAttachment.work_area_id must be a UUID"
    assert data["media_type"] in ("PHOTO", "VIDEO")
    assert data["status"] in ("ACTIVE", "PURGED")
    # PRD section 3.6: at most one evidentiary link.
    assert not (data.get("linked_incident_id") and data.get("linked_delivery_id"))


def assert_material_delivery(data: dict):
    _assert_common_fields(data, "MaterialDelivery")
    assert is_valid_uuid(data.get("report_id", "")), "MaterialDelivery.report_id must be a UUID"
    assert is_valid_uuid(data.get("delivery_zone_id", "")), \
        "MaterialDelivery.delivery_zone_id must be a UUID"
    assert data["unit"] in ("LF", "SF", "CY", "EA", "TON", "GAL")
    assert data["status"] in ("DELIVERED", "PARTIAL", "INSPECTED")


def assert_tm_ticket(data: dict):
    _assert_common_fields(data, "TmTicket")
    assert is_valid_uuid(data.get("report_id", "")), "TmTicket.report_id must be a UUID"
    assert is_valid_uuid(data.get("work_item_id", "")), "TmTicket.work_item_id must be a UUID"
    assert data["status"] in (
        "DRAFT", "PENDING_SIGNATURES", "PARTIALLY_SIGNED", "FULLY_SIGNED",
        "APPROVED", "REJECTED", "VOID")
    assert isinstance(data["revision_count"], int)
    for f in ("labor_cost_cents", "equipment_cost_cents", "materials_subtotal_cents",
              "materials_markup_cents", "materials_cost_cents", "total_cents"):
        assert isinstance(data[f], int), f"TmTicket.{f} must be integer cents"


def assert_quantity_entry(data: dict):
    _assert_common_fields(data, "QuantityEntry")
    assert is_valid_uuid(data.get("report_id", "")), "QuantityEntry.report_id must be a UUID"
    assert is_valid_uuid(data.get("work_item_id", "")), "QuantityEntry.work_item_id must be a UUID"
    assert is_valid_uuid(data.get("work_area_id", "")), \
        "QuantityEntry.work_area_id must be a UUID"
    assert data["status"] in ("ACTIVE", "VOIDED")
    assert isinstance(data["rounded_quantity"], (int, float))


def assert_distribution_record(data: dict):
    _assert_common_fields(data, "DistributionRecord")
    assert is_valid_uuid(data.get("report_id", "")), \
        "DistributionRecord.report_id must be a UUID"
    assert isinstance(data["recipient_email"], str) and data["recipient_email"]
    assert data["recipient_role"] in (
        "OWNER", "ARCHITECT", "INSPECTOR", "SUBCONTRACTOR", "INTERNAL")
    assert data["status"] in ("PENDING", "BLOCKED", "SENT", "ACKNOWLEDGED")


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_delivery_partition(delivery: dict):
    """PRD section 3.6: accepted + rejected + pending_recount == delivered_qty."""
    total = delivery["accepted_qty"] + delivery["rejected_qty"] \
        + delivery["pending_recount_qty"]
    assert total == pytest.approx(delivery["delivered_qty"], abs=1e-9), (
        f"Delivery partition broken: {delivery['accepted_qty']} + "
        f"{delivery['rejected_qty']} + {delivery['pending_recount_qty']} != "
        f"{delivery['delivered_qty']}"
    )


def assert_report_manpower_consistent(report: dict):
    """Non-negative manpower figures (PRD section 3.3)."""
    assert report["total_workers"] >= 0
    for f in ("manhours_regular", "manhours_ot", "manhours_dt"):
        assert report[f] >= 0, f"DailyReport.{f} must be non-negative"
