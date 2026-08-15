"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)

JOB_STATUSES = [
    "DRAFT", "QUOTED", "BOOKED", "CLEARED", "SCHEDULED", "EN_ROUTE",
    "ON_HOLD", "DELIVERED", "CLOSED", "CANCELLED",
]
LEG_STATUSES = ["PENDING", "DETERMINED", "CLEARED", "BLOCKED", "COMPLETED", "CANCELLED"]
PERMIT_STATUSES = ["APPLIED", "ISSUED", "EXPIRED"]
SURVEY_STATUSES = ["REQUESTED", "SUBMITTED", "ACCEPTED", "REJECTED", "SUPERSEDED"]
ASSIGNMENT_STATUSES = ["OFFERED", "ACCEPTED", "DECLINED", "ACTIVE", "COMPLETED", "RELEASED"]
DELAY_STATUSES = ["OPEN", "CLOSED"]
INCIDENT_STATUSES = ["REPORTED", "ASSESSED", "DISPUTED", "SETTLED"]
INVOICE_STATUSES = ["DRAFT", "FINALIZED", "DISPUTED", "PAID", "WRITTEN_OFF"]
ESCORT_STATUSES = ["ACTIVE", "SUSPENDED"]
VERDICTS = ["UNKNOWN", "PASS", "FAIL"]


def _assert_common(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer"
    )


def assert_carrier(data: dict):
    _assert_common(data, "Carrier")
    assert isinstance(data["carrier_name"], str) and data["carrier_name"]
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] > 0
    assert isinstance(data["ytd_billed_cents"], int) and data["ytd_billed_cents"] >= 0
    assert isinstance(data["credit_available_cents"], int)


def assert_escort(data: dict):
    _assert_common(data, "Escort")
    assert isinstance(data["operator_name"], str) and data["operator_name"]
    assert isinstance(data["certified_state_codes"], list) and data["certified_state_codes"]
    assert all(c in ("TX", "OK", "KS", "LA") for c in data["certified_state_codes"])
    assert isinstance(data["has_height_pole"], bool)
    assert isinstance(data["height_pole_max_inches"], int)
    assert 0 <= data["reliability_score"] <= 100
    assert data["escort_status"] in ESCORT_STATUSES
    assert isinstance(data["active_assignment_count"], int) and data["active_assignment_count"] >= 0


def assert_job(data: dict):
    _assert_common(data, "Job")
    assert is_valid_uuid(data.get("carrier_id", "")), "Job.carrier_id must be a UUID"
    assert data["job_status"] in JOB_STATUSES
    for f in ("width_inches", "height_inches", "length_inches", "gross_weight_lbs"):
        assert isinstance(data[f], int) and data[f] > 0, f"Job.{f} must be > 0"
    assert is_iso8601_timestamp(data.get("window_start_at", ""))
    assert is_iso8601_timestamp(data.get("window_end_at", ""))
    assert isinstance(data["cancel_fee_cents"], int) and data["cancel_fee_cents"] >= 0
    assert isinstance(data["total_escort_positions"], int) and data["total_escort_positions"] >= 0


def assert_leg(data: dict):
    _assert_common(data, "RouteLeg")
    assert is_valid_uuid(data.get("job_id", "")), "RouteLeg.job_id must be a UUID"
    assert data["state_code"] in ("TX", "OK", "KS", "LA")
    assert data["leg_status"] in LEG_STATUSES
    assert data["clearance_verdict"] in VERDICTS
    assert isinstance(data["police_confirmed"], bool)
    assert isinstance(data["requires_height_pole"], bool)
    assert isinstance(data["requires_police_escort"], bool)
    assert isinstance(data["requires_route_survey"], bool)


def assert_permit(data: dict):
    _assert_common(data, "Permit")
    assert is_valid_uuid(data.get("leg_id", "")), "Permit.leg_id must be a UUID"
    assert data["permit_status"] in PERMIT_STATUSES
    assert is_iso8601_timestamp(data.get("valid_from", ""))
    assert is_iso8601_timestamp(data.get("valid_until", ""))
    assert isinstance(data["holiday_closure_dates"], list)


def assert_survey(data: dict):
    _assert_common(data, "RouteSurvey")
    assert is_valid_uuid(data.get("leg_id", "")), "RouteSurvey.leg_id must be a UUID"
    assert data["survey_status"] in SURVEY_STATUSES


def assert_obstruction(data: dict):
    # Append-only row: id + created_at only; updated_at/version must be absent.
    assert is_valid_uuid(data.get("id", "")), "Obstruction.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "Obstruction.created_at ISO 8601"
    assert "updated_at" not in data, "Obstruction must not carry updated_at"
    assert "version" not in data, "Obstruction must not carry version"
    assert is_valid_uuid(data.get("survey_id", "")), "Obstruction.survey_id must be a UUID"
    assert data["obstruction_type"] in ("BRIDGE", "WIRE", "SIGN", "OTHER")
    assert data["disposition"] in ("PASSABLE", "PASSABLE_WITH_POLE", "REQUIRES_REROUTE")
    assert data["milepost"] >= 0
    assert isinstance(data["measured_clearance_inches"], int) and data["measured_clearance_inches"] >= 0


def assert_assignment(data: dict):
    _assert_common(data, "EscortAssignment")
    assert is_valid_uuid(data.get("leg_id", "")), "EscortAssignment.leg_id must be a UUID"
    assert is_valid_uuid(data.get("escort_id", "")), "EscortAssignment.escort_id must be a UUID"
    assert data["position"] in ("FRONT", "REAR")
    assert data["assignment_status"] in ASSIGNMENT_STATUSES


def assert_delay_event(data: dict):
    _assert_common(data, "DelayEvent")
    assert is_valid_uuid(data.get("job_id", "")), "DelayEvent.job_id must be a UUID"
    assert data["cause"] in (
        "CARRIER_DELAY", "MECHANICAL_BREAKDOWN", "DOCUMENTATION_ISSUE",
        "WEATHER", "CURFEW_HOLD", "POLICE_DIRECTED", "ROAD_CLOSURE",
    )
    assert data["delay_status"] in DELAY_STATUSES
    assert is_iso8601_timestamp(data.get("started_at", ""))


def assert_incident(data: dict):
    _assert_common(data, "Incident")
    assert is_valid_uuid(data.get("job_id", "")), "Incident.job_id must be a UUID"
    assert data["incident_type"] in (
        "CARGO_DAMAGE", "PROPERTY_DAMAGE", "TRAFFIC_VIOLATION", "INJURY", "EQUIPMENT_DAMAGE",
    )
    assert isinstance(data["claimed_amount_cents"], int) and data["claimed_amount_cents"] >= 0
    assert data["incident_status"] in INCIDENT_STATUSES
    assert isinstance(data["reporter_role"], str) and data["reporter_role"]
    assert isinstance(data["reporter_user_id"], str) and data["reporter_user_id"]


def assert_invoice(data: dict):
    _assert_common(data, "Invoice")
    assert is_valid_uuid(data.get("job_id", "")), "Invoice.job_id must be a UUID"
    assert data["invoice_status"] in INVOICE_STATUSES
    for f in (
        "base_charges_cents", "equipment_charges_cents", "standby_total_cents",
        "subtotal_cents", "volume_discount_cents", "fuel_surcharge_cents",
        "cancellation_fee_cents", "incident_chargebacks_cents",
        "adjustment_delta_cents", "total_cents",
    ):
        assert isinstance(data[f], int), f"Invoice.{f} must be integer cents"
        assert_cost_precision(data[f])
    assert data["total_cents"] >= 0, "Invoice.total_cents must stay >= 0"


def assert_invoice_invariants(data: dict):
    """Domain invariants that must hold for any composed invoice."""
    assert_invoice(data)
    assert data["subtotal_cents"] == (
        data["base_charges_cents"]
        + data["equipment_charges_cents"]
        + data["standby_total_cents"]
    ), "subtotal_cents must equal base + equipment + standby"
    assert data["total_cents"] == (
        data["subtotal_cents"]
        - data["volume_discount_cents"]
        + data["fuel_surcharge_cents"]
        + data["cancellation_fee_cents"]
        - data["incident_chargebacks_cents"]
        + data["adjustment_delta_cents"]
    ), "total_cents must follow the pinned composition"
