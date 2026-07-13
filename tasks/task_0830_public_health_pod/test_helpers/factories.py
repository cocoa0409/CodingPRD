"""Payload factories — one per entity, `source: input` fields only."""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


DEFAULTS = {
    "TITLE": "County Preparedness Plan",
    "JURISDICTION_CODE": "CTY00",
    "TARGET_POPULATION": 10_000,
    "SITE_NAME": "Community POD",
    "ADDRESS": "1 Main St",
    "STAFFING_CAPACITY_LANES": 5,
    "LANE_THROUGHPUT_RATE_PER_HOUR": 20,
    "FULL_NAME": "Test Volunteer",
    "MRC_UNIT": "UnitDefault",
    "COUNTERMEASURE_NAME": "Test Vaccine",
    "DOSES_REQUIRED": 1,
    "UNIT_COST_CENTS": 1000,
    "REORDER_POINT_QUANTITY": 10,
    "LOT_NUMBER": "LOT-DEFAULT",
    "ON_HAND_QUANTITY": 100,
    "EXPIRATION_DATE": "2027-01-01T00:00:00Z",
    "REGISTRANT_FULL_NAME": "Jane Registrant",
    "SCHEDULED_AT": "2026-04-01T09:00:00Z",
    "REPORT_PERIOD_LABEL": "OPS_PERIOD_1",
}


def create_hazard_plan_payload(**overrides) -> dict:
    defaults = {
        "hazard_type": "OUTBREAK_OTHER",
        "title": f"{DEFAULTS['TITLE']} {_seq()}",
        "jurisdiction_code": DEFAULTS["JURISDICTION_CODE"],
        "target_population": DEFAULTS["TARGET_POPULATION"],
    }
    defaults.update(overrides)
    return defaults


def create_pod_payload(hazard_plan_id: str, **overrides) -> dict:
    defaults = {
        "hazard_plan_id": hazard_plan_id,
        "site_name": f"{DEFAULTS['SITE_NAME']} {_seq()}",
        "site_type": "FIXED_POD",
        "address": DEFAULTS["ADDRESS"],
        "staffing_capacity_lanes": DEFAULTS["STAFFING_CAPACITY_LANES"],
        "lane_throughput_rate_per_hour": DEFAULTS["LANE_THROUGHPUT_RATE_PER_HOUR"],
    }
    defaults.update(overrides)
    return defaults


def create_staff_member_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "full_name": f"{DEFAULTS['FULL_NAME']} {n}",
        "email": f"volunteer{n}@example.org",
        "primary_role": "VACCINATOR",
        "mrc_unit": DEFAULTS["MRC_UNIT"],
        "credential_type": "EMT_CERT",
        "credential_expires_at": DEFAULTS["EXPIRATION_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_shift_assignment_payload(pod_id: str, staff_member_id: str, **overrides) -> dict:
    defaults = {
        "pod_id": pod_id,
        "staff_member_id": staff_member_id,
        "assigned_role": "VACCINATOR",
        "start_time": "2026-03-05T08:00:00Z",
        "end_time": "2026-03-05T16:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_countermeasure_payload(**overrides) -> dict:
    defaults = {
        "name": f"{DEFAULTS['COUNTERMEASURE_NAME']} {_seq()}",
        "countermeasure_type": "VACCINE",
        "doses_required": DEFAULTS["DOSES_REQUIRED"],
        "unit_cost_cents": DEFAULTS["UNIT_COST_CENTS"],
        "reorder_point_quantity": DEFAULTS["REORDER_POINT_QUANTITY"],
    }
    defaults.update(overrides)
    return defaults


def create_inventory_lot_payload(countermeasure_id: str, pod_id=None, **overrides) -> dict:
    defaults = {
        "countermeasure_id": countermeasure_id,
        "lot_number": f"{DEFAULTS['LOT_NUMBER']}-{_seq()}",
        "on_hand_quantity": DEFAULTS["ON_HAND_QUANTITY"],
        "expiration_date": DEFAULTS["EXPIRATION_DATE"],
    }
    if pod_id is not None:
        defaults["pod_id"] = pod_id
    defaults.update(overrides)
    return defaults


def create_allocation_request_payload(
    pod_id: str, countermeasure_id: str, expected_pod_version: int, **overrides
) -> dict:
    defaults = {
        "pod_id": pod_id,
        "countermeasure_id": countermeasure_id,
        "source_type": "SNS_CACHE",
        "requested_quantity": 10,
        "expected_pod_version": expected_pod_version,
    }
    defaults.update(overrides)
    return defaults


def create_dispensing_event_payload(pod_id: str, countermeasure_id: str, **overrides) -> dict:
    defaults = {
        "pod_id": pod_id,
        "countermeasure_id": countermeasure_id,
        "registrant_full_name": f"{DEFAULTS['REGISTRANT_FULL_NAME']} {_seq()}",
        "registrant_risk_group": "GENERAL_PUBLIC",
        "dose_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_drill_payload(hazard_plan_id: str, **overrides) -> dict:
    defaults = {
        "hazard_plan_id": hazard_plan_id,
        "drill_type": "TABLETOP",
        "scheduled_at": DEFAULTS["SCHEDULED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_situation_report_payload(hazard_plan_id: str, **overrides) -> dict:
    defaults = {
        "hazard_plan_id": hazard_plan_id,
        "report_period_label": f"{DEFAULTS['REPORT_PERIOD_LABEL']}-{_seq()}",
    }
    defaults.update(overrides)
    return defaults
