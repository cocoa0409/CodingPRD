"""Payload factories -- one per entity, input fields only (per PRD section 4).

Unique-keyed fields (contract_number, area codes, zone codes, cost codes) get
monotonically increasing suffixes so that tests creating several entities in
one scenario never collide on the uniqueness rules of PRD section 3.1/3.2.
"""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _next(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_project_payload(**overrides) -> dict:
    defaults = {
        "name": _next("Project"),
        "contract_number": _next("C"),
    }
    defaults.update(overrides)
    return defaults


def create_work_area_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "code": _next("A"),
    }
    defaults.update(overrides)
    return defaults


def create_delivery_zone_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "zone_code": _next("Z"),
    }
    defaults.update(overrides)
    return defaults


def create_work_item_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "cost_code": _next("03"),
        "description": "Budget line",
        "budgeted_quantity": TEST_DEFAULTS["BUDGETED_QUANTITY"],
        "unit": "LF",
        "unit_cost_cents": TEST_DEFAULTS["UNIT_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_daily_report_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "report_date": TEST_DEFAULTS["REPORT_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_crew_entry_payload(report_id, work_area_id, **overrides) -> dict:
    defaults = {
        "report_id": report_id,
        "work_area_id": work_area_id,
        "subcontractor": "SubCo",
        "trade": "Labor",
        "worker_count": TEST_DEFAULTS["WORKER_COUNT"],
        "hours_per_worker": TEST_DEFAULTS["HOURS_PER_WORKER"],
        "work_performed": "general work",
    }
    defaults.update(overrides)
    return defaults


def create_equipment_entry_payload(report_id, work_area_id, **overrides) -> dict:
    defaults = {
        "report_id": report_id,
        "work_area_id": work_area_id,
        "equipment_type": "Crane",
        "unit_count": 1,
        "hours_used": 8,
        "hours_idle": 0,
    }
    defaults.update(overrides)
    return defaults


def create_weather_observation_payload(report_id, **overrides) -> dict:
    defaults = {
        "report_id": report_id,
        "observed_at": "2026-08-05T08:00:00Z",
        "condition": "CLEAR",
        "work_impact": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_delay_event_payload(report_id, work_area_id, **overrides) -> dict:
    defaults = {
        "report_id": report_id,
        "work_area_id": work_area_id,
        "start_at": "2026-08-05T09:00:00Z",
        "end_at": "2026-08-05T10:00:00Z",
        "cause": "OWNER",
    }
    defaults.update(overrides)
    return defaults


def create_safety_observation_payload(report_id, work_area_id, **overrides) -> dict:
    defaults = {
        "report_id": report_id,
        "work_area_id": work_area_id,
        "description": "Housekeeping debris observed along the main access route",
        "risk_level": "LOW",
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(report_id, work_area_id, **overrides) -> dict:
    defaults = {
        "report_id": report_id,
        "work_area_id": work_area_id,
        "occurred_at": "2026-08-05T09:00:00Z",
        "severity": "FIRST_AID",
        "narrative": "Minor scrape treated on site.",
    }
    defaults.update(overrides)
    return defaults


def create_media_attachment_payload(report_id, work_area_id, **overrides) -> dict:
    defaults = {
        "report_id": report_id,
        "work_area_id": work_area_id,
        "media_type": "PHOTO",
        "file_url": _next_url(),
        "captured_at": "2026-08-05T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def _next_url() -> str:
    return f"s3://evidence/{next(_counter)}.jpg"


def create_delivery_payload(report_id, delivery_zone_id, **overrides) -> dict:
    defaults = {
        "report_id": report_id,
        "delivery_zone_id": delivery_zone_id,
        "po_number": _next("PO"),
        "material_description": "Rebar",
        "delivered_qty": TEST_DEFAULTS["DELIVERED_QTY"],
        "unit": "TON",
        "scheduled_window_start": "2026-08-05T09:00:00Z",
        "scheduled_window_end": "2026-08-05T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_quantity_entry_payload(report_id, work_item_id, work_area_id,
                                  expected_report_version, **overrides) -> dict:
    defaults = {
        "report_id": report_id,
        "work_item_id": work_item_id,
        "work_area_id": work_area_id,
        "quantity_installed": 10,
        "expected_report_version": expected_report_version,
    }
    defaults.update(overrides)
    return defaults


def create_tm_ticket_payload(report_id, work_item_id, **overrides) -> dict:
    defaults = {
        "report_id": report_id,
        "work_item_id": work_item_id,
        "description": "Extra work ticket",
        "labor_lines": [
            {
                "trade": "Labor",
                "worker_count": 1,
                "regular_hours": 1,
                "ot_hours": 0,
                "dt_hours": 0,
                "rate_cents": 100,
            }
        ],
    }
    defaults.update(overrides)
    return defaults


def create_distribution_record_payload(report_id, **overrides) -> dict:
    defaults = {
        "report_id": report_id,
        "recipient_email": _next_email(),
        "recipient_role": "OWNER",
    }
    defaults.update(overrides)
    return defaults


def _next_email() -> str:
    return f"recipient-{next(_counter)}@example.com"
