"""Composite setup helpers.

The harness restarts the API server before every individual test, so every test
begins against an empty database. Nothing here reaches behind the API: all state
is built by calling the documented endpoints in order, starting from the single
bootstrap exemption that lets the first `FacilitiesDirector` row exist at all.

The helpers are layered:

* tier 1 — identity: the bootstrap director and the rest of the staff roster
* tier 2 — inventory: fields, the logical clock, plain reads
* tier 3 — single-entity chains: maintenance tasks, assessments, bookings
* tier 4 — cascade chains: failed impact tests, played bookings, remediation
* tier 5 — document and capital chains: certification packets, budgets, plans
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import validate_paginated, validate_success

from . import factories
from .api_client import ApiClient
from .constants import DEFAULT_CLOCK_UTC
from .test_users import (
    HEADER_BUILDERS,
    TEST_USERS,
    make_bootstrap_director_headers,
    make_certification_officer_headers,
    make_facilities_director_headers,
    make_field_operations_coordinator_headers,
    make_safety_inspector_headers,
    make_turf_agronomist_headers,
)
from .types import (
    ActivityType,
    AssessmentType,
    ClosureAction,
    PacketDecision,
    PlanDecision,
    PriorityBasis,
    SurfaceType,
    TaskType,
    VerificationDecision,
    WeatherCondition,
)

# ===========================================================================
# Tier 1 — identity
# ===========================================================================


class Roster:
    """The staff roster plus a ready header set for each handle."""

    def __init__(self, client: ApiClient):
        self.client = client
        self.members: Dict[str, Dict[str, Any]] = {}
        self.headers: Dict[str, Dict[str, str]] = {}

    # -- lookups ----------------------------------------------------------
    def id_of(self, handle: str) -> str:
        return self.members[handle]["id"]

    def headers_of(self, handle: str) -> Dict[str, str]:
        return self.headers[handle]

    def __getitem__(self, handle: str) -> Dict[str, Any]:
        return self.members[handle]

    # -- convenience properties ------------------------------------------
    @property
    def director(self) -> Dict[str, Any]:
        return self.members["director"]

    @property
    def director_headers(self) -> Dict[str, str]:
        return self.headers["director"]

    @property
    def inspector(self) -> Dict[str, Any]:
        return self.members["inspector"]

    @property
    def inspector_headers(self) -> Dict[str, str]:
        return self.headers["inspector"]

    @property
    def agronomist(self) -> Dict[str, Any]:
        return self.members["agronomist"]

    @property
    def agronomist_headers(self) -> Dict[str, str]:
        return self.headers["agronomist"]

    @property
    def cert_officer(self) -> Dict[str, Any]:
        return self.members["cert_officer"]

    @property
    def cert_officer_headers(self) -> Dict[str, str]:
        return self.headers["cert_officer"]

    @property
    def coordinator(self) -> Dict[str, Any]:
        return self.members["coordinator"]

    @property
    def coordinator_headers(self) -> Dict[str, str]:
        return self.headers["coordinator"]


def bootstrap_director(client: ApiClient, handle: str = "director") -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Create the very first `FacilitiesDirector` through the bootstrap exemption.

    `POST /turf/staff-members` does not resolve the acting identity, which is
    what makes an empty database usable at all.
    """
    spec = TEST_USERS[handle]
    response = client.create_staff_member(
        factories.make_staff_member_payload(
            full_name=spec["full_name"], roles=list(spec["roles"])
        ),
        make_bootstrap_director_headers(),
    )
    director = validate_success(response, 201)
    return director, make_facilities_director_headers(director["id"])


def add_staff_member(
    client: ApiClient,
    director_headers: Dict[str, str],
    handle: str,
    roles: Optional[List[str]] = None,
    employment_status: Any = ...,
) -> Dict[str, Any]:
    """Add one roster member; the director owns the staff roster."""
    spec = TEST_USERS[handle]
    response = client.create_staff_member(
        factories.make_staff_member_payload(
            full_name=spec["full_name"],
            roles=list(roles) if roles is not None else list(spec["roles"]),
            employment_status=employment_status,
        ),
        director_headers,
    )
    return validate_success(response, 201)


def build_roster(client: ApiClient, handles: Optional[List[str]] = None) -> Roster:
    """Bootstrap the director and then create the requested roster handles."""
    roster = Roster(client)
    director, director_headers = bootstrap_director(client)
    roster.members["director"] = director
    roster.headers["director"] = director_headers

    wanted = list(handles) if handles is not None else [
        "inspector",
        "agronomist",
        "cert_officer",
        "coordinator",
    ]
    for handle in wanted:
        if handle == "director" or handle in roster.members:
            continue
        member = add_staff_member(client, director_headers, handle)
        roster.members[handle] = member
        roster.headers[handle] = HEADER_BUILDERS[TEST_USERS[handle]["role"]](member["id"])
    return roster


def build_full_roster(client: ApiClient) -> Roster:
    """A roster with a second holder of every role, for segregation-of-duties work."""
    return build_roster(
        client,
        handles=[
            "director_two",
            "inspector",
            "inspector_two",
            "agronomist",
            "agronomist_two",
            "cert_officer",
            "cert_officer_two",
            "coordinator",
            "coordinator_two",
        ],
    )


# ===========================================================================
# Tier 2 — inventory, clock and reads
# ===========================================================================


def set_clock(client: ApiClient, roster: Roster, to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock forward; only a `FacilitiesDirector` may do so."""
    response = client.set_clock(to_iso8601, roster.director_headers)
    return validate_success(response, 200)


def register_field(
    client: ApiClient, roster: Roster, payload: Dict[str, Any]
) -> Dict[str, Any]:
    """Register one field from an explicit payload."""
    response = client.create_field(payload, roster.director_headers)
    return validate_success(response, 201)


def register_grass_main_1(client: ApiClient, roster: Roster, **overrides: Any) -> Dict[str, Any]:
    """The canonical state-sanctioned natural grass field.

    Installed 2018-04-15 with a nominal life of 12 years over 80000 square feet,
    warranty running to 2026-04-15.
    """
    payload = factories.make_natural_grass_field_payload(
        name=overrides.pop("name", "Grass Main 1"),
        installed_on_date=overrides.pop("installed_on_date", "2018-04-15"),
        expected_life_years=overrides.pop("expected_life_years", 12),
        area_sq_ft=overrides.pop("area_sq_ft", 80000),
        sanctioned_level=overrides.pop("sanctioned_level", "STATE"),
        warranty_expires_on=overrides.pop("warranty_expires_on", "2026-04-15"),
        **overrides,
    )
    return register_field(client, roster, payload)


def register_synthetic_stadium_1(
    client: ApiClient, roster: Roster, **overrides: Any
) -> Dict[str, Any]:
    """The canonical regional synthetic field, infill measured at 34.0 mm."""
    payload = factories.make_synthetic_field_payload(
        name=overrides.pop("name", "Synthetic Stadium 1"),
        installed_on_date=overrides.pop("installed_on_date", "2016-06-01"),
        expected_life_years=overrides.pop("expected_life_years", 10),
        area_sq_ft=overrides.pop("area_sq_ft", 70000),
        sanctioned_level=overrides.pop("sanctioned_level", "REGIONAL"),
        warranty_expires_on=overrides.pop("warranty_expires_on", "2024-06-01"),
        infill_depth_mm=overrides.pop("infill_depth_mm", 34.0),
        **overrides,
    )
    return register_field(client, roster, payload)


def register_grass_practice_3(
    client: ApiClient, roster: Roster, **overrides: Any
) -> Dict[str, Any]:
    """A young locally sanctioned grass practice field, installed 2025-08-01."""
    payload = factories.make_natural_grass_field_payload(
        name=overrides.pop("name", "Grass Practice 3"),
        installed_on_date=overrides.pop("installed_on_date", "2025-08-01"),
        expected_life_years=overrides.pop("expected_life_years", 12),
        area_sq_ft=overrides.pop("area_sq_ft", 60000),
        sanctioned_level=overrides.pop("sanctioned_level", "LOCAL"),
        warranty_expires_on=overrides.pop("warranty_expires_on", "2030-08-01"),
        **overrides,
    )
    return register_field(client, roster, payload)


def read_field(client: ApiClient, roster: Roster, field_id: str) -> Dict[str, Any]:
    """Read one field back, including every derived posture, counter and index."""
    return validate_success(client.get_field(field_id, roster.director_headers), 200)


def read_booking(client: ApiClient, roster: Roster, booking_id: str) -> Dict[str, Any]:
    return validate_success(
        client.get_usage_booking(booking_id, roster.director_headers), 200
    )


def read_task(client: ApiClient, roster: Roster, task_id: str) -> Dict[str, Any]:
    return validate_success(
        client.get_maintenance_task(task_id, roster.director_headers), 200
    )


def read_assessment(client: ApiClient, roster: Roster, assessment_id: str) -> Dict[str, Any]:
    return validate_success(
        client.get_safety_assessment(assessment_id, roster.director_headers), 200
    )


def read_order(client: ApiClient, roster: Roster, order_id: str) -> Dict[str, Any]:
    return validate_success(
        client.get_remediation_order(order_id, roster.director_headers), 200
    )


def read_packet(client: ApiClient, roster: Roster, packet_id: str) -> Dict[str, Any]:
    return validate_success(
        client.get_certification_packet(packet_id, roster.director_headers), 200
    )


def read_budget(client: ApiClient, roster: Roster, budget_id: str) -> Dict[str, Any]:
    return validate_success(
        client.get_capital_budget(budget_id, roster.director_headers), 200
    )


def read_plan(client: ApiClient, roster: Roster, plan_id: str) -> Dict[str, Any]:
    return validate_success(
        client.get_replacement_plan(plan_id, roster.director_headers), 200
    )


def list_ledger_entries(
    client: ApiClient, roster: Roster, **filters: Any
) -> List[Dict[str, Any]]:
    """List ledger entries, which are only ever discoverable through this list."""
    params = {"limit": 100}
    params.update({k: v for k, v in filters.items() if v is not None})
    items, _meta = validate_paginated(
        client.list_usage_ledger_entries(roster.director_headers, params=params)
    )
    return items


def list_orders(client: ApiClient, roster: Roster, **filters: Any) -> List[Dict[str, Any]]:
    """List remediation orders, their sole discovery channel."""
    params = {"limit": 100}
    params.update({k: v for k, v in filters.items() if v is not None})
    items, _meta = validate_paginated(
        client.list_remediation_orders(roster.director_headers, params=params)
    )
    return items


def list_bookings(client: ApiClient, roster: Roster, **filters: Any) -> List[Dict[str, Any]]:
    params = {"limit": 100}
    params.update({k: v for k, v in filters.items() if v is not None})
    items, _meta = validate_paginated(
        client.list_usage_bookings(roster.director_headers, params=params)
    )
    return items


def list_plans(client: ApiClient, roster: Roster, **filters: Any) -> List[Dict[str, Any]]:
    params = {"limit": 100}
    params.update({k: v for k, v in filters.items() if v is not None})
    items, _meta = validate_paginated(
        client.list_replacement_plans(roster.director_headers, params=params)
    )
    return items


def close_field_administratively(
    client: ApiClient,
    roster: Roster,
    field_id: str,
    reason_code: str = "IRRIGATION_MAIN_BREAK",
) -> Dict[str, Any]:
    """Place an administrative closure, which cancels nothing."""
    response = client.place_closure_order(
        field_id,
        factories.make_closure_order_payload(ClosureAction.CLOSE_ADMIN, reason_code),
        roster.director_headers,
    )
    return validate_success(response, 200)


def reopen_field_administratively(
    client: ApiClient, roster: Roster, field_id: str, reason_code: str = "REPAIR_COMPLETE"
) -> Dict[str, Any]:
    """Lift an administrative closure."""
    response = client.place_closure_order(
        field_id,
        factories.make_closure_order_payload(ClosureAction.REOPEN_ADMIN, reason_code),
        roster.director_headers,
    )
    return validate_success(response, 200)


# ===========================================================================
# Tier 3 — single-entity chains
# ===========================================================================


def schedule_task(
    client: ApiClient,
    roster: Roster,
    field_id: str,
    task_type: str = TaskType.AERATION,
    scheduled_start_utc: str = "2026-08-10T08:00:00Z",
    scheduled_end_utc: str = "2026-08-10T10:00:00Z",
    assigned_handle: str = "agronomist",
    nitrogen_lb_per_1000_sq_ft: Any = ...,
    planned_for_certification_window: Any = ...,
) -> Dict[str, Any]:
    """Schedule one maintenance task on behalf of the agronomist."""
    payload = factories.make_maintenance_task_payload(
        field_id=field_id,
        assigned_staff_member_id=roster.id_of(assigned_handle),
        task_type=task_type,
        scheduled_start_utc=scheduled_start_utc,
        scheduled_end_utc=scheduled_end_utc,
        nitrogen_lb_per_1000_sq_ft=nitrogen_lb_per_1000_sq_ft,
        planned_for_certification_window=planned_for_certification_window,
    )
    return validate_success(
        client.create_maintenance_task(payload, roster.agronomist_headers), 201
    )


def start_task(client: ApiClient, roster: Roster, task_id: str) -> Dict[str, Any]:
    """`START` stamps `started_at_utc` from the logical clock."""
    return validate_success(
        client.transition_maintenance_task(
            task_id, factories.make_task_start_payload(), roster.agronomist_headers
        ),
        200,
    )


def complete_task(
    client: ApiClient, roster: Roster, task_id: str, completed_at_utc: str
) -> Dict[str, Any]:
    """`COMPLETE` requires a `completed_at_utc` at or after `started_at_utc`
    and at or before the current logical instant."""
    return validate_success(
        client.transition_maintenance_task(
            task_id,
            factories.make_task_complete_payload(completed_at_utc),
            roster.agronomist_headers,
        ),
        200,
    )


def start_and_complete_task(
    client: ApiClient, roster: Roster, task_id: str, completed_at_utc: str
) -> Dict[str, Any]:
    """Run a scheduled task all the way to `COMPLETED`."""
    start_task(client, roster, task_id)
    return complete_task(client, roster, task_id, completed_at_utc)


def record_impact_test(
    client: ApiClient,
    roster: Roster,
    field_id: str,
    readings: List[float],
    assessed_at_utc: str = DEFAULT_CLOCK_UTC,
    inspector_handle: str = "inspector",
) -> Dict[str, Any]:
    """Record an `IMPACT_ATTENUATION` test; the server derives the verdict."""
    payload = factories.make_impact_assessment_payload(
        field_id=field_id,
        inspector_staff_member_id=roster.id_of(inspector_handle),
        gmax_readings=readings,
        assessed_at_utc=assessed_at_utc,
    )
    return validate_success(
        client.record_safety_assessment(payload, roster.headers_of(inspector_handle)), 201
    )


def record_inspection(
    client: ApiClient,
    roster: Roster,
    field_id: str,
    assessment_type: str = AssessmentType.STRIPING_LAYOUT,
    declared_result: str = "PASS",
    assessed_at_utc: str = DEFAULT_CLOCK_UTC,
    inspector_handle: str = "inspector",
) -> Dict[str, Any]:
    """Record a `GOAL_ANCHORING` or `STRIPING_LAYOUT` inspector verdict."""
    payload = factories.make_inspection_assessment_payload(
        field_id=field_id,
        inspector_staff_member_id=roster.id_of(inspector_handle),
        assessment_type=assessment_type,
        declared_result=declared_result,
        assessed_at_utc=assessed_at_utc,
    )
    return validate_success(
        client.record_safety_assessment(payload, roster.headers_of(inspector_handle)), 201
    )


def void_assessment(
    client: ApiClient,
    roster: Roster,
    assessment_id: str,
    void_reason: str = "CALIBRATION_DEFECT",
    inspector_handle: str = "inspector",
) -> Dict[str, Any]:
    """Void a mis-recorded assessment."""
    return validate_success(
        client.void_safety_assessment(
            assessment_id,
            factories.make_void_payload(void_reason),
            roster.headers_of(inspector_handle),
        ),
        200,
    )


def request_booking(
    client: ApiClient,
    roster: Roster,
    field_id: str,
    activity_type: str = ActivityType.GAME,
    window_start_utc: str = "2026-08-02T19:00:00Z",
    window_end_utc: str = "2026-08-02T23:00:00Z",
    expected_participant_count: int = 60,
    requester_handle: str = "coordinator",
) -> Dict[str, Any]:
    """Request a field allocation; allocation is the coordinator's province."""
    payload = factories.make_usage_booking_payload(
        field_id=field_id,
        requested_by_staff_member_id=roster.id_of(requester_handle),
        activity_type=activity_type,
        window_start_utc=window_start_utc,
        window_end_utc=window_end_utc,
        expected_participant_count=expected_participant_count,
    )
    return validate_success(
        client.create_usage_booking(payload, roster.headers_of(requester_handle)), 201
    )


def confirm_booking(client: ApiClient, roster: Roster, booking_id: str) -> Dict[str, Any]:
    """Confirm a scheduled booking; confirmation re-runs every posture gate."""
    return validate_success(
        client.confirm_usage_booking(booking_id, roster.coordinator_headers), 200
    )


def close_out_booking(
    client: ApiClient,
    roster: Roster,
    booking_id: str,
    outcome: str = "PLAYED",
    actual_duration_hours: float = 4.00,
    actual_participant_count: int = 60,
    weather_condition: str = WeatherCondition.DRY,
) -> Dict[str, Any]:
    """Close out a confirmed booking under one of the three outcomes."""
    payload = factories.make_close_out_payload(
        outcome=outcome,
        actual_duration_hours=actual_duration_hours,
        actual_participant_count=actual_participant_count,
        weather_condition=weather_condition,
    )
    return validate_success(
        client.close_out_usage_booking(booking_id, payload, roster.coordinator_headers),
        200,
    )


# ===========================================================================
# Tier 4 — cascade chains
# ===========================================================================


def play_booking(
    client: ApiClient,
    roster: Roster,
    field_id: str,
    activity_type: str = ActivityType.GAME,
    window_start_utc: str = "2026-08-02T19:00:00Z",
    window_end_utc: str = "2026-08-02T23:00:00Z",
    expected_participant_count: int = 60,
    outcome: str = "PLAYED",
    actual_duration_hours: float = 4.00,
    actual_participant_count: int = 60,
    weather_condition: str = WeatherCondition.DRY,
    close_out_at_utc: Optional[str] = None,
) -> Dict[str, Any]:
    """Request, confirm, let the window elapse and close out one booking.

    Close-out requires the current logical instant to be at or after
    `window_end_utc`, so the clock is advanced to `close_out_at_utc` (defaulting
    to the window end) between confirmation and close-out.
    """
    booking = request_booking(
        client,
        roster,
        field_id,
        activity_type=activity_type,
        window_start_utc=window_start_utc,
        window_end_utc=window_end_utc,
        expected_participant_count=expected_participant_count,
    )
    confirm_booking(client, roster, booking["id"])
    set_clock(client, roster, close_out_at_utc or window_end_utc)
    return close_out_booking(
        client,
        roster,
        booking["id"],
        outcome=outcome,
        actual_duration_hours=actual_duration_hours,
        actual_participant_count=actual_participant_count,
        weather_condition=weather_condition,
    )


def fail_field_unsafe(
    client: ApiClient,
    roster: Roster,
    field_id: str,
    readings: Optional[List[float]] = None,
    assessed_at_utc: str = DEFAULT_CLOCK_UTC,
    inspector_handle: str = "inspector",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Record a failing impact test and return the assessment with the
    `MANDATORY` order the cascade opened."""
    assessment = record_impact_test(
        client,
        roster,
        field_id,
        readings if readings is not None else [210.0, 210.0, 210.0],
        assessed_at_utc=assessed_at_utc,
        inspector_handle=inspector_handle,
    )
    orders = list_orders(client, roster, field_id=field_id, source_assessment_id=assessment["id"])
    assert len(orders) == 1, f"a FAIL verdict opens exactly one order, found {len(orders)}"
    return assessment, orders[0]


def advise_field_restricted(
    client: ApiClient,
    roster: Roster,
    field_id: str,
    readings: Optional[List[float]] = None,
    assessed_at_utc: str = DEFAULT_CLOCK_UTC,
    inspector_handle: str = "inspector",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Record a marginal impact test and return the `ADVISORY` order it opened."""
    assessment = record_impact_test(
        client,
        roster,
        field_id,
        readings if readings is not None else [180.0, 180.0, 180.0],
        assessed_at_utc=assessed_at_utc,
        inspector_handle=inspector_handle,
    )
    orders = list_orders(client, roster, field_id=field_id, source_assessment_id=assessment["id"])
    assert len(orders) == 1, f"an ADVISORY verdict opens exactly one order, found {len(orders)}"
    return assessment, orders[0]


def submit_order_verification(
    client: ApiClient,
    roster: Roster,
    order_id: str,
    verification_assessment_id: str,
    submitter_handle: str = "agronomist",
    remediation_notes: str = "Root zone decompacted and re-tested at the goal mouths.",
) -> Dict[str, Any]:
    """Offer a re-test as evidence; the submitter may not be the source inspector."""
    payload = factories.make_submit_verification_payload(
        verification_assessment_id=verification_assessment_id,
        submitted_by_staff_member_id=roster.id_of(submitter_handle),
        remediation_notes=remediation_notes,
    )
    return validate_success(
        client.submit_verification(order_id, payload, roster.headers_of(submitter_handle)),
        200,
    )


def decide_order_verification(
    client: ApiClient,
    roster: Roster,
    order_id: str,
    decision: str = VerificationDecision.ACCEPT,
    decider_handle: str = "inspector",
    decision_notes: Any = ...,
) -> Dict[str, Any]:
    """Rule on a submitted verification; the decider may not be the submitter."""
    payload = factories.make_decide_verification_payload(
        decision=decision, decision_notes=decision_notes
    )
    return validate_success(
        client.decide_verification(order_id, payload, roster.headers_of(decider_handle)),
        200,
    )


# ===========================================================================
# Tier 5 — certification and capital chains
# ===========================================================================


def open_packet(
    client: ApiClient,
    roster: Roster,
    field_id: str,
    governing_assessment_id: str,
    expected_field_version: int,
    competition_season_label: str = "2026-2027 Autumn",
    officer_handle: str = "cert_officer",
) -> Dict[str, Any]:
    """Open a certification packet in `DRAFT` under optimistic concurrency."""
    payload = factories.make_certification_packet_payload(
        field_id=field_id,
        governing_assessment_id=governing_assessment_id,
        expected_field_version=expected_field_version,
        competition_season_label=competition_season_label,
    )
    return validate_success(
        client.create_certification_packet(payload, roster.headers_of(officer_handle)), 201
    )


def submit_packet(
    client: ApiClient,
    roster: Roster,
    packet_id: str,
    officer_handle: str = "cert_officer",
) -> Dict[str, Any]:
    """Submit a packet; both scores are recomputed from scratch at every submission."""
    return validate_success(
        client.submit_certification_packet(
            packet_id,
            factories.make_packet_submit_payload(roster.id_of(officer_handle)),
            roster.headers_of(officer_handle),
        ),
        200,
    )


def decide_packet(
    client: ApiClient,
    roster: Roster,
    packet_id: str,
    decision: str = PacketDecision.APPROVE,
    officer_handle: str = "cert_officer_two",
    decision_notes: Any = ...,
) -> Dict[str, Any]:
    """Decide a submitted packet; the decider may be neither the submitter nor
    the inspector behind the governing assessment."""
    payload = factories.make_packet_decide_payload(
        decision=decision,
        decided_by_staff_member_id=roster.id_of(officer_handle),
        decision_notes=decision_notes,
    )
    return validate_success(
        client.decide_certification_packet(
            packet_id, payload, roster.headers_of(officer_handle)
        ),
        200,
    )


def build_certifiable_synthetic_field(
    client: ApiClient,
    roster: Roster,
    infill_depth_mm: float = 51.0,
    name: str = "Synthetic Stadium 1",
    assessed_at_utc: str = DEFAULT_CLOCK_UTC,
    impact_readings: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """Register a synthetic field and lay down every documentary component the
    completeness score reads: a passing impact test, a passing striping-layout
    inspection and a passing goal-anchoring inspection.

    Returns a dict of the field plus the three assessments.
    """
    field = register_synthetic_stadium_1(
        client, roster, name=name, infill_depth_mm=infill_depth_mm
    )
    impact = record_impact_test(
        client,
        roster,
        field["id"],
        impact_readings if impact_readings is not None else [120.0, 120.0, 120.0],
        assessed_at_utc=assessed_at_utc,
    )
    striping = record_inspection(
        client,
        roster,
        field["id"],
        assessment_type=AssessmentType.STRIPING_LAYOUT,
        declared_result="PASS",
        assessed_at_utc=assessed_at_utc,
    )
    goals = record_inspection(
        client,
        roster,
        field["id"],
        assessment_type=AssessmentType.GOAL_ANCHORING,
        declared_result="PASS",
        assessed_at_utc=assessed_at_utc,
    )
    return {
        "field": read_field(client, roster, field["id"]),
        "impact": impact,
        "striping": striping,
        "goal_anchoring": goals,
    }


def authorize_budget(
    client: ApiClient,
    roster: Roster,
    fiscal_year: int = 2027,
    total_authorized_amount_cents: int = 5825556,
) -> Dict[str, Any]:
    """Authorise a fiscal-year capital budget and its lock threshold."""
    return validate_success(
        client.create_capital_budget(
            factories.make_capital_budget_payload(
                fiscal_year=fiscal_year,
                total_authorized_amount_cents=total_authorized_amount_cents,
            ),
            roster.director_headers,
        ),
        201,
    )


def draft_plan(
    client: ApiClient,
    roster: Roster,
    field_id: str,
    capital_budget_id: str,
    expected_field_version: int,
    target_surface_type: str = SurfaceType.SYNTHETIC_TURF,
    area_sq_ft: int = 70000,
    priority_basis: str = PriorityBasis.CONDITION_RISK,
    planned_install_year: int = 2027,
) -> Dict[str, Any]:
    """Draft a replacement plan, priced and scored at creation."""
    payload = factories.make_replacement_plan_payload(
        field_id=field_id,
        capital_budget_id=capital_budget_id,
        expected_field_version=expected_field_version,
        target_surface_type=target_surface_type,
        area_sq_ft=area_sq_ft,
        priority_basis=priority_basis,
        planned_install_year=planned_install_year,
    )
    return validate_success(
        client.create_replacement_plan(payload, roster.director_headers), 201
    )


def submit_plan(
    client: ApiClient, roster: Roster, plan_id: str, submitter_handle: str = "director"
) -> Dict[str, Any]:
    """Submit a draft plan for a funding decision."""
    return validate_success(
        client.submit_replacement_plan(
            plan_id,
            factories.make_plan_submit_payload(roster.id_of(submitter_handle)),
            roster.headers_of(submitter_handle),
        ),
        200,
    )


def decide_plan(
    client: ApiClient,
    roster: Roster,
    plan_id: str,
    decision: str = PlanDecision.APPROVE,
    decider_handle: str = "director_two",
    decision_notes: Any = ...,
) -> Dict[str, Any]:
    """Approve, reject or rescind a plan's funding; the decider may never be
    the plan's submitter."""
    payload = factories.make_plan_decide_payload(
        decision=decision,
        decided_by_staff_member_id=roster.id_of(decider_handle),
        decision_notes=decision_notes,
    )
    return validate_success(
        client.decide_replacement_plan(plan_id, payload, roster.headers_of(decider_handle)),
        200,
    )


def record_manifest(
    client: ApiClient,
    roster: Roster,
    plan_id: str,
    manifest_reference: str = "MAN-2027-0001",
    disposal_facility_name: str = "Rivergate Polymer Recovery",
    diverted_tonnage: float = 46.0,
    total_tonnage: float = 50.0,
) -> Dict[str, Any]:
    """Record the waste manifest; the funding axis is neither read nor changed."""
    payload = factories.make_disposal_manifest_payload(
        manifest_reference=manifest_reference,
        disposal_facility_name=disposal_facility_name,
        diverted_tonnage=diverted_tonnage,
        total_tonnage=total_tonnage,
    )
    return validate_success(
        client.record_disposal_manifest(plan_id, payload, roster.director_headers), 200
    )


def complete_disposal(
    client: ApiClient, roster: Roster, plan_id: str, completed_at_utc: str
) -> Dict[str, Any]:
    """Complete the disposal, which is also what retires the field."""
    return validate_success(
        client.complete_disposal(
            plan_id,
            factories.make_disposal_complete_payload(completed_at_utc),
            roster.director_headers,
        ),
        200,
    )


def retire_field_through_disposal(
    client: ApiClient,
    roster: Roster,
    field_id: str,
    completed_at_utc: str,
    fiscal_year: int = 2027,
    total_authorized_amount_cents: int = 99999999,
) -> Dict[str, Any]:
    """Drive a synthetic field all the way to `RETIRED` through the only route
    that retires anything: an approved plan whose manifested disposal completes.
    """
    budget = authorize_budget(
        client,
        roster,
        fiscal_year=fiscal_year,
        total_authorized_amount_cents=total_authorized_amount_cents,
    )
    field = read_field(client, roster, field_id)
    plan = draft_plan(
        client,
        roster,
        field_id,
        budget["id"],
        expected_field_version=field["version"],
        area_sq_ft=field["area_sq_ft"],
        priority_basis=PriorityBasis.CONDITION_RISK,
    )
    record_manifest(client, roster, plan["id"])
    submit_plan(client, roster, plan["id"])
    decide_plan(client, roster, plan["id"], decision=PlanDecision.APPROVE)
    return complete_disposal(client, roster, plan["id"], completed_at_utc)
