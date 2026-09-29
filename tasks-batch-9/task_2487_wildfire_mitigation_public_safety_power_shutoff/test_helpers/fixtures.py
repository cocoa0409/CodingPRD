"""Composable state builders and pytest fixtures.

The API server is restarted before every individual test, so every builder here
starts from an empty database and from the default logical clock reading of
`2026-08-01T00:00:00Z` (PRD §2.5) and drives the state it needs entirely through
the endpoints the PRD declares.

The builders are layered:

* tier 1 — single rows: circuits, stations, observations, indices, accounts;
* tier 2 — the feeder chain and its scored forecast index;
* tier 3 — event lifecycle shortcuts: scoped, armed, active, restoring;
* tier 4 — accumulation targets: patrolled circuits, recorded hardening mileage,
  dispatched notification batches;
* tier 5 — terminal states: fully restored and closed events, withdrawn projects.
"""

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import api_client
from .test_users import (
    ANALYST_HEADERS,
    ENGINEER_HEADERS,
    INSPECTOR_HEADERS,
    LIAISON_HEADERS,
    OFFICER_HEADERS,
    PLANNER_HEADERS,
    REVIEWER_HEADERS,
    SUPERVISOR_HEADERS,
    make_duty_officer_headers,
)
from .types import (
    Channel,
    ComputationVariant,
    CustomerClass,
    HftdTier,
    Language,
    NotificationStage,
    PatrolMode,
    ProgramType,
    ReviewDecision,
    TelemetryStatus,
)

# --------------------------------------------------------------------------
# The instants the standard chain runs against.
# --------------------------------------------------------------------------
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
FORECAST_DATE = "2026-08-15"
ONSET_AT = "2026-08-15T18:00:00Z"
ALL_CLEAR_AT = "2026-08-16T18:00:00Z"
ADVANCE_SEND_AT = "2026-08-13T18:00:00Z"
IMMINENT_SEND_AT = "2026-08-15T17:00:00Z"
DE_ENERGIZED_AT = "2026-08-15T19:00:00Z"
PATROL_START_AT = "2026-08-16T20:00:00Z"
PATROL_CLOCK_AT = "2026-08-16T21:00:00Z"
PATROL_DONE_AT = "2026-08-17T01:00:00Z"
RESTORE_ALPHA_AT = "2026-08-17T02:00:00Z"
RESTORE_BRAVO_AT = "2026-08-17T03:00:00Z"
RESTORE_CHARLIE_AT = "2026-08-17T04:30:00Z"


# ==========================================================================
# Tier 1 — single-row builders and reads
# ==========================================================================
def move_clock(to_iso8601, headers=None):
    """Position the logical clock (PRD §2.5)."""
    return get_success_data(api_client.set_clock(to_iso8601, headers or OFFICER_HEADERS))


def register_circuit(headers=None, **overrides):
    return get_success_data(
        api_client.create_circuit(f.circuit_payload(**overrides), headers or PLANNER_HEADERS)
    )


def read_circuit(circuit_id, headers=None):
    return get_success_data(
        api_client.get_circuit(circuit_id, headers or PLANNER_HEADERS)
    )


def list_circuits(headers=None, **params):
    response = api_client.list_circuits(headers or PLANNER_HEADERS, params=params or None)
    rows, meta = validate_paginated(response)
    return rows, meta


def register_station(circuit_id, headers=None, **overrides):
    return get_success_data(
        api_client.create_weather_station(
            f.weather_station_payload(circuit_id, **overrides), headers or ANALYST_HEADERS
        )
    )


def file_observation(station_id, observed_at, headers=None, **overrides):
    return get_success_data(
        api_client.create_weather_observation(
            f.observation_payload(station_id, observed_at, **overrides),
            headers or ANALYST_HEADERS,
        )
    )


def compute_index(
    circuit_id,
    forecast_date=FORECAST_DATE,
    computation_variant=ComputationVariant.FORECAST.value,
    headers=None,
):
    return get_success_data(
        api_client.create_fire_potential_index(
            f.fpi_payload(circuit_id, forecast_date, computation_variant),
            headers or ANALYST_HEADERS,
        )
    )


def register_customer(circuit_id, headers=None, **overrides):
    return get_success_data(
        api_client.create_customer(
            f.customer_payload(circuit_id, **overrides), headers or PLANNER_HEADERS
        )
    )


def read_event(event_id, headers=None):
    return get_success_data(
        api_client.get_psps_event(event_id, headers or OFFICER_HEADERS)
    )


def read_scope_rows(event_id, headers=None, **params):
    response = api_client.list_event_scopes(
        event_id, headers or OFFICER_HEADERS, params=params or None
    )
    rows, _ = validate_paginated(response)
    return rows


def read_project(project_id, headers=None):
    return get_success_data(
        api_client.get_mitigation_project(project_id, headers or PLANNER_HEADERS)
    )


def read_patrol(assignment_id, headers=None):
    return get_success_data(
        api_client.get_patrol_assignment(assignment_id, headers or SUPERVISOR_HEADERS)
    )


def read_batch(batch_id, headers=None):
    return get_success_data(
        api_client.get_notification_batch(batch_id, headers or LIAISON_HEADERS)
    )


def read_records(headers=None, **params):
    response = api_client.list_notification_records(
        headers or LIAISON_HEADERS, params=params or None
    )
    rows, meta = validate_paginated(response)
    return rows, meta


def read_center(center_id, headers=None):
    return get_success_data(
        api_client.get_resource_center(center_id, headers or LIAISON_HEADERS)
    )


def read_filing(filing_id, headers=None):
    return get_success_data(
        api_client.get_plan_filing(filing_id, headers or PLANNER_HEADERS)
    )


# ==========================================================================
# Tier 2 — the feeder chain, its station network and its scored index
# ==========================================================================
#: The four observations that give ALPHA effective inputs 56.5 / 23.6 / 8.4 under
#: `FORECAST` and 57.0-based inputs under `VALIDATED`.
ALPHA_OBSERVATIONS = [
    ("ws_a1", "2026-08-14T18:00:00Z", 62.0, 22.0, 104.0, 8.0),
    ("ws_a1", "2026-08-15T15:00:00Z", 57.0, 28.0, 99.0, 9.5),
    ("ws_a2", "2026-08-14T17:00:00Z", 48.0, 26.0, 101.0, 9.0),
    ("ws_a2", "2026-08-15T16:00:00Z", 44.0, 31.0, 96.0, 10.0),
]


def build_alpha_station_network(alpha_id):
    """Two ONLINE stations of weight 0.70 and 0.45 with two observations each."""
    stations = {
        "ws_a1": register_station(
            alpha_id,
            station_code="WS-A1",
            elevation_ft=3200,
            representativeness_weight=0.70,
            telemetry_status=TelemetryStatus.ONLINE.value,
        ),
        "ws_a2": register_station(
            alpha_id,
            station_code="WS-A2",
            elevation_ft=2600,
            representativeness_weight=0.45,
            telemetry_status=TelemetryStatus.ONLINE.value,
        ),
    }
    for key, observed_at, gust, humidity, temp, fuel in ALPHA_OBSERVATIONS:
        file_observation(
            stations[key]["id"],
            observed_at,
            wind_gust_mph=gust,
            relative_humidity_pct=humidity,
            temperature_f=temp,
            dead_fuel_moisture_pct=fuel,
        )
    return stations


def build_feeder_chain(with_customers=True, with_index=True):
    """ALPHA (TIER_3, 7.0 mi) feeding BRAVO (TIER_2, 6.0 mi) feeding CHARLIE
    (TIER_2, 5.0 mi), the two-station observation set, an R5 `FORECAST` index on
    ALPHA for 2026-08-15, and five accounts across the chain."""
    alpha = register_circuit(
        circuit_code="ALPHA",
        district_code="D-NORTH",
        hftd_tier=HftdTier.TIER_3.value,
        overhead_miles=7.0,
        equipment_condition_index=55,
        inspection_cycle_months=36,
        last_inspection_completed_at="2026-05-01T00:00:00Z",
        fast_trip_enabled=False,
    )
    bravo = register_circuit(
        circuit_code="BRAVO",
        district_code="D-NORTH",
        hftd_tier=HftdTier.TIER_2.value,
        overhead_miles=6.0,
        equipment_condition_index=70,
        inspection_cycle_months=36,
        last_inspection_completed_at="2026-05-01T00:00:00Z",
        upstream_circuit_id=alpha["id"],
        fast_trip_enabled=False,
    )
    charlie = register_circuit(
        circuit_code="CHARLIE",
        district_code="D-NORTH",
        hftd_tier=HftdTier.TIER_2.value,
        overhead_miles=5.0,
        equipment_condition_index=80,
        inspection_cycle_months=36,
        last_inspection_completed_at="2026-05-01T00:00:00Z",
        upstream_circuit_id=bravo["id"],
        fast_trip_enabled=False,
    )
    ctx = {"alpha": alpha, "bravo": bravo, "charlie": charlie}
    ctx.update(build_alpha_station_network(alpha["id"]))

    if with_index:
        ctx["fpi_forecast"] = compute_index(alpha["id"], FORECAST_DATE)

    if with_customers:
        ctx["cust_a1"] = register_customer(
            alpha["id"],
            account_number="ACC-A1",
            customer_class=CustomerClass.RESIDENTIAL.value,
            medical_baseline=True,
            preferred_language=Language.ES.value,
            notification_channels=[Channel.SMS.value, Channel.VOICE.value],
            accessibility_needs=[],
            address_zone_code="Z1",
        )
        ctx["cust_a2"] = register_customer(
            alpha["id"],
            account_number="ACC-A2",
            customer_class=CustomerClass.CRITICAL_FACILITY.value,
            medical_baseline=False,
            preferred_language=Language.EN.value,
            notification_channels=[Channel.VOICE.value, Channel.EMAIL.value],
            accessibility_needs=[],
            address_zone_code="Z1",
        )
        ctx["cust_a3"] = register_customer(
            alpha["id"],
            account_number="ACC-A3",
            customer_class=CustomerClass.RESIDENTIAL.value,
            medical_baseline=False,
            preferred_language=Language.ZH.value,
            notification_channels=[Channel.SMS.value],
            accessibility_needs=["AUDIO", "TTY"],
            address_zone_code="Z2",
        )
        ctx["cust_b1"] = register_customer(
            bravo["id"],
            account_number="ACC-B1",
            preferred_language=Language.EN.value,
            notification_channels=[Channel.SMS.value],
            address_zone_code="Z3",
        )
        ctx["cust_c1"] = register_customer(
            charlie["id"],
            account_number="ACC-C1",
            preferred_language=Language.EN.value,
            notification_channels=[Channel.EMAIL.value],
            address_zone_code="Z4",
        )
    return ctx


# ==========================================================================
# Tier 3 — event lifecycle shortcuts
# ==========================================================================
def open_event(
    trigger_index_id,
    onset_at=ONSET_AT,
    all_clear_at=ALL_CLEAR_AT,
    event_code="EV-1",
    headers=None,
):
    return get_success_data(
        api_client.create_psps_event(
            f.psps_event_payload(
                trigger_index_id, onset_at, all_clear_at, event_code=event_code
            ),
            headers or OFFICER_HEADERS,
        )
    )


def scope_event(event_id, expected_version, headers=None):
    return get_success_data(
        api_client.scope_psps_event(
            event_id, f.scope_payload(expected_version), headers or OFFICER_HEADERS
        )
    )


def plan_batch(event_id, stage, scheduled_send_at, headers=None):
    return get_success_data(
        api_client.create_notification_batch(
            f.notification_batch_payload(event_id, scheduled_send_at, stage=stage),
            headers or LIAISON_HEADERS,
        )
    )


def dispatch_batch(batch_id, headers=None):
    return get_success_data(
        api_client.dispatch_notification_batch(batch_id, headers or LIAISON_HEADERS)
    )


def arm_event(event_id, headers=None):
    return get_success_data(api_client.arm_psps_event(event_id, headers or OFFICER_HEADERS))


def de_energize_event(event_id, headers=None):
    return get_success_data(
        api_client.de_energize_psps_event(event_id, headers or OFFICER_HEADERS)
    )


def declare_all_clear(event_id, headers=None):
    return get_success_data(
        api_client.all_clear_psps_event(event_id, headers or ANALYST_HEADERS)
    )


def close_event(event_id, headers=None):
    return get_success_data(
        api_client.close_psps_event(event_id, headers or OFFICER_HEADERS)
    )


def cancel_event(event_id, cancellation_reason="forecast downgraded", headers=None):
    return get_success_data(
        api_client.cancel_psps_event(
            event_id, f.cancel_payload(cancellation_reason), headers or OFFICER_HEADERS
        )
    )


def exclude_scope_row(scope_id, justification="held out for switching constraints", headers=None):
    return get_success_data(
        api_client.exclude_event_scope(
            scope_id, f.exclude_payload(justification), headers or ENGINEER_HEADERS
        )
    )


# The `scope_status` ladder EV-1 climbs, in order. Used by the lifecycle builders
# below to decide whether a stage has already been reached on the supplied context.
_SCOPE_STATUS_RANK = {
    "DRAFT": 0,
    "SCOPED": 1,
    "ARMED": 2,
    "ACTIVE": 3,
    "RESTORING": 4,
    "CLOSED": 5,
}


def _event_reached(ctx, scope_status):
    """True when EV-1 has already climbed to (or past) `scope_status`.

    The event is re-read from the server rather than taken from `ctx["event"]`, because a
    caller that drove the event forward by other means (activating a resource center,
    excluding a scope row) leaves the cached copy stale.
    """
    live = read_event(ctx["event_id"])["scope_status"]
    if live not in _SCOPE_STATUS_RANK:  # CANCELLED — off the ladder entirely
        return True
    return _SCOPE_STATUS_RANK[live] >= _SCOPE_STATUS_RANK[scope_status]


# Each lifecycle builder below drives EV-1 one stage further and is *idempotent*: it first
# asks its predecessor to guarantee the preceding stage, then returns untouched if the
# stage it owns has already landed. That lets a caller either walk the ladder explicitly
# (`build_scoped_event(ctx)` then `build_advance_dispatched_event(ctx)` then ...) or jump
# straight to the stage it wants (`build_closed_event(feeder_chain_ctx)`) and get the same
# world either way.
def build_scoped_event(ctx=None):
    """The feeder chain with EV-1 opened and scoped: three CONFIRMED rows."""
    ctx = ctx if ctx is not None else build_feeder_chain()
    if "event_id" in ctx:
        return ctx
    event = open_event(ctx["fpi_forecast"]["id"])
    ctx["event"] = scope_event(event["id"], event["version"])
    ctx["event_id"] = event["id"]
    return ctx


def build_advance_dispatched_event(ctx=None):
    """A scoped EV-1 whose `ADVANCE_48H` batch has been dispatched at exactly the
    2,880-minute lead-time floor."""
    ctx = build_scoped_event(ctx)
    if "batch_advance" in ctx:
        return ctx
    ctx["batch_advance"] = plan_batch(
        ctx["event_id"], NotificationStage.ADVANCE_48H.value, ADVANCE_SEND_AT
    )
    move_clock(ADVANCE_SEND_AT)
    ctx["batch_advance"] = dispatch_batch(ctx["batch_advance"]["id"])
    return ctx


def build_armed_event(ctx=None):
    ctx = build_advance_dispatched_event(ctx)
    if _event_reached(ctx, "ARMED"):
        return ctx
    ctx["event"] = arm_event(ctx["event_id"])
    return ctx


def build_imminent_dispatched_event(ctx=None):
    """An armed EV-1 whose `IMMINENT_1H` batch has been dispatched at exactly the
    60-minute lead-time floor."""
    ctx = build_armed_event(ctx)
    if "batch_imminent" in ctx:
        return ctx
    ctx["batch_imminent"] = plan_batch(
        ctx["event_id"], NotificationStage.IMMINENT_1H.value, IMMINENT_SEND_AT
    )
    move_clock(IMMINENT_SEND_AT)
    ctx["batch_imminent"] = dispatch_batch(ctx["batch_imminent"]["id"])
    return ctx


def build_active_event(ctx=None):
    """EV-1 executed: every confirmed circuit is DE_ENERGIZED at 19:00Z."""
    ctx = build_imminent_dispatched_event(ctx)
    if _event_reached(ctx, "ACTIVE"):
        return ctx
    move_clock(DE_ENERGIZED_AT)
    ctx["event"] = de_energize_event(ctx["event_id"])
    return ctx


def build_restoring_event(ctx=None):
    """EV-1 after meteorology declared the damaging-weather window over."""
    ctx = build_active_event(ctx)
    if _event_reached(ctx, "RESTORING"):
        return ctx
    ctx["event"] = declare_all_clear(ctx["event_id"])
    return ctx


# ==========================================================================
# Tier 4 — accumulation and threshold targets
# ==========================================================================
def schedule_patrol(
    event_id,
    circuit_id,
    window_start_at=PATROL_START_AT,
    window_end_at=PATROL_DONE_AT,
    patrol_lead_user_id="crew_lead_1",
    patrol_mode=PatrolMode.GROUND.value,
    headers=None,
):
    return get_success_data(
        api_client.create_patrol_assignment(
            f.patrol_assignment_payload(
                event_id,
                circuit_id,
                window_start_at,
                window_end_at,
                patrol_lead_user_id=patrol_lead_user_id,
                patrol_mode=patrol_mode,
            ),
            headers or SUPERVISOR_HEADERS,
        )
    )


def start_patrol(assignment_id, headers=None):
    return get_success_data(
        api_client.start_patrol(assignment_id, headers or SUPERVISOR_HEADERS)
    )


def complete_patrol(assignment_id, miles_patrolled=0.0, headers=None):
    return get_success_data(
        api_client.complete_patrol(
            assignment_id,
            f.complete_patrol_payload(miles_patrolled),
            headers or SUPERVISOR_HEADERS,
        )
    )


def file_finding(assignment_id, severity, headers=None, **overrides):
    return get_success_data(
        api_client.create_damage_finding(
            f.damage_finding_payload(assignment_id, severity, **overrides),
            headers or SUPERVISOR_HEADERS,
        )
    )


def build_patrolled_event(ctx=None):
    """EV-1 in restoration with all three circuits patrolled and CLEARED_FOR_RESTORE.

    Each circuit's crew lead is distinct so the re-energization segregation gate
    can be exercised per circuit.
    """
    ctx = build_restoring_event(ctx)
    if "patrol_alpha" in ctx:
        return ctx
    ctx["patrol_alpha"] = schedule_patrol(
        ctx["event_id"],
        ctx["alpha"]["id"],
        PATROL_START_AT,
        "2026-08-17T01:00:00Z",
        patrol_lead_user_id="crew_lead_1",
    )
    ctx["patrol_bravo"] = schedule_patrol(
        ctx["event_id"],
        ctx["bravo"]["id"],
        PATROL_START_AT,
        "2026-08-17T02:00:00Z",
        patrol_lead_user_id="crew_lead_2",
    )
    ctx["patrol_charlie"] = schedule_patrol(
        ctx["event_id"],
        ctx["charlie"]["id"],
        PATROL_START_AT,
        "2026-08-17T03:30:00Z",
        patrol_lead_user_id="crew_lead_3",
        patrol_mode=PatrolMode.AERIAL.value,
    )
    move_clock(PATROL_CLOCK_AT)
    for key in ("patrol_alpha", "patrol_bravo", "patrol_charlie"):
        ctx[key] = start_patrol(ctx[key]["id"])
    move_clock(PATROL_DONE_AT)
    ctx["patrol_alpha"] = complete_patrol(ctx["patrol_alpha"]["id"], 7.0)
    ctx["patrol_bravo"] = complete_patrol(ctx["patrol_bravo"]["id"], 6.0)
    ctx["patrol_charlie"] = complete_patrol(ctx["patrol_charlie"]["id"], 5.0)
    return ctx


def re_energize(circuit_id, headers=None, user_id=None):
    headers = headers or (
        make_duty_officer_headers(user_id) if user_id else OFFICER_HEADERS
    )
    return get_success_data(api_client.re_energize_circuit(circuit_id, headers))


def build_restored_event(ctx=None):
    """Every circuit of EV-1 back in service, the last one at 04:30Z, so the event
    carries its realised `POST_EVENT` accounting."""
    ctx = build_patrolled_event(ctx)
    if read_event(ctx["event_id"])["actual_restored_at"] is not None:
        ctx["event"] = read_event(ctx["event_id"])
        return ctx
    move_clock(RESTORE_ALPHA_AT)
    re_energize(ctx["alpha"]["id"])
    move_clock(RESTORE_BRAVO_AT)
    re_energize(ctx["bravo"]["id"])
    move_clock(RESTORE_CHARLIE_AT)
    re_energize(ctx["charlie"]["id"])
    ctx["event"] = read_event(ctx["event_id"])
    return ctx


def build_closed_event(ctx=None):
    ctx = build_restored_event(ctx)
    if _event_reached(ctx, "CLOSED"):
        ctx["event"] = read_event(ctx["event_id"])
        return ctx
    ctx["event"] = close_event(ctx["event_id"])
    return ctx


# --------------------------------------------------------------------------
# Mitigation portfolio builders
# --------------------------------------------------------------------------
def book_project(circuit_id, headers=None, **overrides):
    return get_success_data(
        api_client.create_mitigation_project(
            f.mitigation_project_payload(circuit_id, **overrides),
            headers or PLANNER_HEADERS,
        )
    )


def submit_project(project_id, headers=None):
    return get_success_data(
        api_client.submit_mitigation_project(project_id, headers or PLANNER_HEADERS)
    )


def review_project(project_id, decision, review_note=None, headers=None):
    return get_success_data(
        api_client.review_mitigation_project(
            project_id,
            f.project_review_payload(decision, review_note),
            headers or REVIEWER_HEADERS,
        )
    )


def record_completion(
    project_id, completed_miles_delta, completion_date, expected_circuit_version, headers=None
):
    return get_success_data(
        api_client.record_project_completion(
            project_id,
            f.record_completion_payload(
                completed_miles_delta, completion_date, expected_circuit_version
            ),
            headers or INSPECTOR_HEADERS,
        )
    )


def build_approved_project(circuit_id, headers=None, **overrides):
    """A booked, submitted and approved work package."""
    project = book_project(circuit_id, headers=headers, **overrides)
    submit_project(project["id"], headers=headers)
    return review_project(
        project["id"], ReviewDecision.APPROVE.value, "hardening plan accepted"
    )


def build_completed_hardening(
    circuit_id,
    program_type=ProgramType.COVERED_CONDUCTOR.value,
    planned_miles=4.0,
    completion_date="2026-07-01T00:00:00Z",
    **overrides
):
    """An approved project executed to its full `planned_miles`, so the circuit's
    hardened-mileage ledger and `hardened_fraction` have moved."""
    project = build_approved_project(
        circuit_id, program_type=program_type, planned_miles=planned_miles, **overrides
    )
    circuit = read_circuit(circuit_id, INSPECTOR_HEADERS)
    project = record_completion(
        project["id"], planned_miles, completion_date, circuit["version"]
    )
    return project


# --------------------------------------------------------------------------
# Resource centers
# --------------------------------------------------------------------------
def register_center(headers=None, **overrides):
    return get_success_data(
        api_client.create_resource_center(
            f.resource_center_payload(**overrides), headers or LIAISON_HEADERS
        )
    )


def activate_centers(event_id, requested_resource_center_ids=None, headers=None):
    return get_success_data(
        api_client.activate_resource_centers(
            event_id,
            f.activation_payload(requested_resource_center_ids),
            headers or OFFICER_HEADERS,
        )
    )


# --------------------------------------------------------------------------
# Plan filings
# --------------------------------------------------------------------------
def open_filing(headers=None, **overrides):
    return get_success_data(
        api_client.create_plan_filing(
            f.plan_filing_payload(**overrides), headers or PLANNER_HEADERS
        )
    )


def submit_filing(filing_id, headers=None):
    return get_success_data(
        api_client.submit_plan_filing(filing_id, headers or PLANNER_HEADERS)
    )


def review_filing(filing_id, review_track, decision, deficiency_note=None, headers=None):
    return get_success_data(
        api_client.review_plan_filing(
            filing_id,
            f.filing_review_payload(review_track, decision, deficiency_note),
            headers or REVIEWER_HEADERS,
        )
    )


# ==========================================================================
# Tier 5 — pytest fixtures over the builders above
# ==========================================================================
@pytest.fixture
def client():
    return api_client


@pytest.fixture
def clock():
    """Hand back a clock mover so a test can step the logical clock."""

    def _move(to_iso8601, headers=None):
        return move_clock(to_iso8601, headers)

    return _move


@pytest.fixture
def circuit():
    """One registered TIER_3 circuit with no dependants."""
    return register_circuit()


@pytest.fixture
def feeder_chain():
    return build_feeder_chain()


@pytest.fixture
def scoped_event():
    return build_scoped_event()


@pytest.fixture
def advance_dispatched_event():
    return build_advance_dispatched_event()


@pytest.fixture
def armed_event():
    return build_armed_event()


@pytest.fixture
def imminent_dispatched_event():
    return build_imminent_dispatched_event()


@pytest.fixture
def active_event():
    return build_active_event()


@pytest.fixture
def restoring_event():
    return build_restoring_event()


@pytest.fixture
def patrolled_event():
    return build_patrolled_event()


@pytest.fixture
def restored_event():
    return build_restored_event()


@pytest.fixture
def closed_event():
    return build_closed_event()
