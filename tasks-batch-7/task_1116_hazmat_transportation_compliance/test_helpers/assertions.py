"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _parse_instant(value: str) -> datetime:
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str):
    """Compare two ISO 8601 datetimes as instants at one-second granularity.

    PRD §2.4 fixes the three-fractional-digit serialization only for
    `created_at`, `updated_at`, and `api_request_timestamp`; the serialization
    of computed datetime fields (e.g. `phone_deadline`,
    `written_report_deadline`, `expires_at`) is unspecified, and PRD §2.4
    states datetimes are "compared at one-second granularity". Value
    assertions on computed datetimes therefore compare parsed instants, not
    raw strings."""
    a = _parse_instant(actual).replace(microsecond=0)
    e = _parse_instant(expected).replace(microsecond=0)
    assert a == e, f"instants differ: {actual!r} != {expected!r}"

_CARRIER_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED_ACTIVE", "SUSPENDED", "EXPIRED"]
_PLAN_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "UNDER_REVISION", "REJECTED", "EXPIRED"]
_SPEC_STATUSES = ["ACTIVE", "RETIRED"]
_DRIVER_STATUSES = ["ACTIVE", "SUSPENDED"]
_POSTURES = ["SUSPENDED", "ENDORSEMENT_EXPIRED", "TRAINING_LAPSED", "QUALIFIED"]
_VEHICLE_STATUSES = ["AVAILABLE", "LOADING", "DISPATCHED"]
_SHIPMENT_STATUSES = [
    "DRAFT", "CLASSIFIED", "PACKAGING_VERIFIED", "DOCUMENTED", "REJECTED",
    "TENDERED", "IN_TRANSIT", "DELIVERED", "CANCELLED",
]
_PAPER_STATUSES = ["DRAFT", "CERTIFIED", "UNDER_AMENDMENT", "LOCKED_IN_TRANSIT", "VOIDED"]
_LOAD_STATUSES = ["STAGING", "SEALED", "DISPATCHED", "ARRIVED", "VOIDED"]
_INCIDENT_STATUSES = ["DRAFT", "PHONE_REPORTED", "WRITTEN_FILED", "CLOSED"]
_INVOICE_STATUSES = ["OPEN", "PAID", "VOID"]
_INVOICE_KINDS = ["INITIAL", "RENEWAL", "REINSTATEMENT"]
_TIERS = ["SMALL", "MEDIUM", "LARGE"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_common(data: dict):
    # TrainingRecord / LoadItem carry only id + created_at (PRD §2.5).
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_carrier(data: dict):
    _assert_common(data)
    assert data["registration_status"] in _CARRIER_STATUSES
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["usdot_number"], str) and data["usdot_number"]
    assert isinstance(data["fleet_size_declared"], int) and data["fleet_size_declared"] >= 0
    assert isinstance(data["hazmat_categories"], list)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["safety_rating"], int)


def assert_security_plan(data: dict):
    _assert_common(data)
    assert data["status"] in _PLAN_STATUSES
    assert isinstance(data["plan_name"], str) and data["plan_name"]
    assert isinstance(data["coverage_categories"], list)


def assert_material(data: dict):
    _assert_common(data)
    assert isinstance(data["un_na_number"], str) and data["un_na_number"]
    assert isinstance(data["proper_shipping_name"], str) and data["proper_shipping_name"]
    assert data["placard_table"] in ("TABLE_1", "TABLE_2")
    assert isinstance(data["requires_security_plan"], bool)


def assert_packaging_spec(data: dict):
    _assert_common(data)
    assert isinstance(data["spec_code"], str) and data["spec_code"]
    assert isinstance(data["authorized_hazard_classes"], list)
    assert data["status"] in _SPEC_STATUSES


def assert_driver(data: dict):
    _assert_common(data)
    assert data["status"] in _DRIVER_STATUSES
    assert data["qualification_posture"] in _POSTURES
    assert isinstance(data["cdl_number"], str) and data["cdl_number"]


def assert_training_record(data: dict):
    _assert_append_only_common(data)
    assert data["training_type"] in ("INITIAL", "RECURRENT")
    assert is_iso8601_timestamp(data.get("expires_at", "")), "expires_at must be ISO 8601"
    assert "updated_at" not in data, "append-only TrainingRecord must not expose updated_at"
    assert "version" not in data, "append-only TrainingRecord must not expose version"


def assert_vehicle(data: dict):
    _assert_common(data)
    assert data["status"] in _VEHICLE_STATUSES
    assert isinstance(data["plate_number"], str) and data["plate_number"]
    assert data["vehicle_class"] in ("VAN", "FLATBED", "TANKER")


def assert_shipment(data: dict):
    _assert_common(data)
    assert data["status"] in _SHIPMENT_STATUSES
    assert isinstance(data["quantity_kg"], (int, float)) and data["quantity_kg"] > 0
    assert isinstance(data["declared_value_cents"], int) and data["declared_value_cents"] >= 0


def assert_shipping_paper(data: dict):
    _assert_common(data)
    assert data["status"] in _PAPER_STATUSES
    assert isinstance(data["emergency_contact_phone"], str) and data["emergency_contact_phone"]
    assert isinstance(data["amendment_count"], int) and data["amendment_count"] >= 0


def assert_vehicle_load(data: dict):
    _assert_common(data)
    assert data["status"] in _LOAD_STATUSES
    assert isinstance(data["total_table2_weight_kg"], (int, float))
    assert isinstance(data["required_placards"], list)
    assert isinstance(data["handling_fee_cents"], int)


def assert_load_item(data: dict):
    _assert_append_only_common(data)
    assert "updated_at" not in data, "append-only LoadItem must not expose updated_at"
    assert "version" not in data, "append-only LoadItem must not expose version"


def assert_route(data: dict):
    _assert_common(data)
    assert isinstance(data["route_code"], str) and data["route_code"]
    assert isinstance(data["allowed_hazard_classes"], list)


def assert_incident_report(data: dict):
    _assert_common(data)
    assert data["status"] in _INCIDENT_STATUSES
    assert data["severity"] in ("MINOR", "MAJOR", "CATASTROPHIC")
    assert isinstance(data["phone_report_required"], bool)
    assert isinstance(data["penalty_cents"], int)


def assert_registration_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in _INVOICE_STATUSES
    assert data["kind"] in _INVOICE_KINDS
    assert isinstance(data["assessment_year"], int)
    assert isinstance(data["total_due_cents"], int)
    assert isinstance(data["paid_cents"], int)


def assert_carrier_balance_invariants(carrier: dict):
    """Domain invariants that must hold on any carrier read (PRD §3.1/§3.2)."""
    assert carrier["outstanding_balance_cents"] >= 0, "outstanding balance never negative"
    assert carrier["credit_balance_cents"] >= 0, "credit balance never negative"
    assert carrier["safety_rating"] >= 0, "safety rating floored at 0"
    assert carrier["safety_rating"] <= 100, "safety rating starts at 100 and only decrements"
