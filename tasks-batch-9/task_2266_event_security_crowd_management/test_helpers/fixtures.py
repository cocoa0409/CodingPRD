"""Composite setup builders.

Every builder drives the API under test through declared endpoints only — no
database seeding, no back doors. Each returns a :class:`World`, a plain
attribute bag of the ids and versions the caller needs.

The builders form a ladder from cheapest to richest; each tier calls the tier
below it, so a test asks for the smallest world that makes its claim
observable:

  Tier 1  clock / venue / zones                        ``build_venue_world``
  Tier 2  event + draft assessment                     ``build_event_world``
  Tier 3  approved assessment + draft plan             ``build_plan_world``
  Tier 4  published plan + rostered guards             ``build_activated_plan_world``
  Tier 5  live event: doors open, incidents, closure    ``build_closed_event_world``
"""

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .factories import (
    POST_WINDOW_END,
    POST_WINDOW_START,
    action,
    brief_action,
    event_payload,
    exit_zone_payload,
    guard_payload,
    ingress_zone_payload,
    post_assignment_payload,
    post_payload,
    risk_assessment_payload,
    screening_lane_payload,
    staffing_plan_payload,
    venue_payload,
    zone_payload,
)
from .test_users import (
    AUDITOR_HEADERS,
    COMMANDER_HEADERS,
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    ANALYST_HEADERS,
    OPERATOR_HEADERS,
    make_post_supervisor_headers,
)
from .types import LaneType, PostType

PLANNING_CLOCK = "2026-09-01T00:00:00Z"
PRE_DOORS_CLOCK = "2026-09-12T16:30:00Z"
INCIDENT_CLOCK = "2026-09-12T18:00:00Z"
TRIAGE_CLOCK = "2026-09-12T18:12:00Z"
START_CLOCK = "2026-09-12T18:30:00Z"
CLOSE_CLOCK = "2026-09-12T22:30:00Z"


class World(SimpleNamespace):
    """Attribute bag of ids captured while building a scenario."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.guard_ids: List[str] = kwargs.get("guard_ids", [])
        self.assignment_ids: List[str] = kwargs.get("assignment_ids", [])


# ─── Low-level helpers ────────────────────────────────


def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock and return the checkpoint report."""
    return get_success_data(api.set_clock(to_iso8601, OPERATOR_HEADERS))


def create_verified_guard(
    api: ApiClient,
    license_number: str,
    credential_level: int = 1,
    base_hourly_rate_cents: int = 2200,
    full_name: str = "Gale One",
    **overrides: Any,
) -> str:
    """Source a guard and clear its credential in one step."""
    guard = get_success_data(
        api.create_guard(
            guard_payload(
                license_number,
                credential_level=credential_level,
                base_hourly_rate_cents=base_hourly_rate_cents,
                full_name=full_name,
                **overrides,
            ),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    get_success_data(
        api.guard_credential_verification(guard["id"], action("VERIFY"), AUDITOR_HEADERS)
    )
    return guard["id"]


def create_assignment(
    api: ApiClient,
    post_id: str,
    guard_id: str,
    window_start: str = POST_WINDOW_START,
    window_end: str = POST_WINDOW_END,
) -> str:
    data = get_success_data(
        api.create_post_assignment(
            post_assignment_payload(
                post_id, guard_id, window_start=window_start, window_end=window_end
            ),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    return data["id"]


def confirm(api: ApiClient, assignment_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.post_assignment_duty_event(assignment_id, action("CONFIRM"), COORDINATOR_HEADERS)
    )


def brief(
    api: ApiClient, assignment_id: str, supervisor_guard_id: str, radio_channel: str = "CH1"
) -> Dict[str, Any]:
    return get_success_data(
        api.post_assignment_duty_event(
            assignment_id,
            brief_action(radio_channel=radio_channel),
            make_post_supervisor_headers(supervisor_guard_id),
        )
    )


def check_in(api: ApiClient, assignment_id: str, supervisor_guard_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.post_assignment_duty_event(
            assignment_id, action("CHECK_IN"), make_post_supervisor_headers(supervisor_guard_id)
        )
    )


def read_event_version(api: ApiClient, event_id: str) -> int:
    return get_success_data(api.get_event(event_id, DIRECTOR_HEADERS))["version"]


def read_post_version(api: ApiClient, post_id: str) -> int:
    return get_success_data(api.get_post(post_id, COORDINATOR_HEADERS))["version"]


# ─── Tier 1: clock, venue, zones ──────────────────────


def build_clock_world(api: ApiClient, clock: str = PLANNING_CLOCK) -> World:
    """Pin the logical clock to a known planning instant."""
    set_clock(api, clock)
    return World(clock=clock)


def build_venue_world(api: ApiClient, clock: str = PLANNING_CLOCK, **venue_overrides: Any) -> World:
    """A single venue on a pinned clock."""
    world = build_clock_world(api, clock)
    venue = get_success_data(
        api.create_venue(venue_payload(**venue_overrides), DIRECTOR_HEADERS), expected_status=201
    )
    world.venue_id = venue["id"]
    world.venue = venue
    return world


def build_zoned_venue_world(api: ApiClient, clock: str = PLANNING_CLOCK) -> World:
    """Venue plus the three working zones: floor, ingress concourse, exit corridor."""
    world = build_venue_world(api, clock)
    zf = get_success_data(
        api.create_zone(world.venue_id, zone_payload(), DIRECTOR_HEADERS), expected_status=201
    )
    zi = get_success_data(
        api.create_zone(world.venue_id, ingress_zone_payload(), DIRECTOR_HEADERS),
        expected_status=201,
    )
    ze = get_success_data(
        api.create_zone(world.venue_id, exit_zone_payload(), DIRECTOR_HEADERS), expected_status=201
    )
    world.zf_id, world.zi_id, world.ze_id = zf["id"], zi["id"], ze["id"]
    world.zf, world.zi, world.ze = zf, zi, ze
    return world


# ─── Tier 2: event and draft assessment ───────────────


def build_event_world(api: ApiClient, clock: str = PLANNING_CLOCK, **event_overrides: Any) -> World:
    """Zoned venue plus a PLANNING event."""
    world = build_zoned_venue_world(api, clock)
    event = get_success_data(
        api.create_event(event_payload(world.venue_id, **event_overrides), DIRECTOR_HEADERS),
        expected_status=201,
    )
    world.event_id = event["id"]
    world.event = event
    return world


def build_draft_assessment_world(
    api: ApiClient, clock: str = PLANNING_CLOCK, **assessment_overrides: Any
) -> World:
    """Event plus a DRAFT risk assessment authored by analyst-1."""
    world = build_event_world(api, clock)
    assessment = get_success_data(
        api.create_risk_assessment(
            world.event_id, risk_assessment_payload(**assessment_overrides), ANALYST_HEADERS
        ),
        expected_status=201,
    )
    world.ra_id = assessment["id"]
    world.assessment = assessment
    return world


def build_submitted_assessment_world(
    api: ApiClient, clock: str = PLANNING_CLOCK, **assessment_overrides: Any
) -> World:
    """Assessment moved to SUBMITTED by its analyst author."""
    world = build_draft_assessment_world(api, clock, **assessment_overrides)
    world.assessment = get_success_data(
        api.risk_assessment_decision(world.ra_id, action("SUBMIT"), ANALYST_HEADERS)
    )
    return world


def build_approved_assessment_world(
    api: ApiClient, clock: str = PLANNING_CLOCK, **assessment_overrides: Any
) -> World:
    """Assessment APPROVED by the director, so the event reaches RISK_ASSESSED."""
    world = build_submitted_assessment_world(api, clock, **assessment_overrides)
    world.assessment = get_success_data(
        api.risk_assessment_decision(world.ra_id, action("APPROVE"), DIRECTOR_HEADERS)
    )
    world.event_v = read_event_version(api, world.event_id)
    return world


# ─── Tier 3: draft staffing plan ──────────────────────


def build_plan_world(
    api: ApiClient, budget_cents: int = 500000, clock: str = PLANNING_CLOCK
) -> World:
    """Approved assessment plus a DRAFT staffing plan with no posts yet."""
    world = build_approved_assessment_world(api, clock)
    plan = get_success_data(
        api.create_staffing_plan(
            world.event_id,
            staffing_plan_payload(world.ra_id, world.event_v, budget_cents=budget_cents),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    world.plan_id = plan["id"]
    world.plan = plan
    return world


def build_plan_with_perimeter_post_world(
    api: ApiClient, budget_cents: int = 500000, required_guard_count: int = 5
) -> World:
    """Draft plan carrying a single PERIMETER post that covers the whole requirement."""
    world = build_plan_world(api, budget_cents=budget_cents)
    post = get_success_data(
        api.create_post(
            world.plan_id,
            post_payload(
                world.zf_id,
                "P1",
                PostType.PERIMETER,
                required_guard_count=required_guard_count,
            ),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    world.p1_id = post["id"]
    world.p1 = post
    return world


def build_plan_with_supervisor_post_world(api: ApiClient, budget_cents: int = 500000) -> World:
    """Draft plan carrying only the SUPERVISOR post, min_credential_level 3."""
    world = build_plan_world(api, budget_cents=budget_cents)
    post = get_success_data(
        api.create_post(
            world.plan_id,
            post_payload(
                world.zf_id,
                "S1",
                PostType.SUPERVISOR,
                required_guard_count=1,
                min_credential_level=3,
            ),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    world.s1_id = post["id"]
    world.s1 = post
    return world


def build_plan_with_verified_guard_world(api: ApiClient) -> World:
    """Perimeter-post plan plus one VERIFIED employee guard, still unrostered."""
    world = build_plan_with_perimeter_post_world(api)
    world.g1_id = create_verified_guard(api, "GC-7001")
    world.guard_ids = [world.g1_id]
    return world


# ─── Tier 4: published / activated rosters ────────────


def build_five_post_activated_world(api: ApiClient) -> World:
    """The five-slot chain: one BAG_CHECK lane, four posts, five confirmed guards.

    required_total_staff is 5 (S1 one, I1 two, F1 one, E1 one) and every slot is
    filled, so the plan reaches READY and is then ACTIVATED. Assignments are
    CONFIRMED but not yet briefed, which leaves the event in STAFFED.
    """
    world = build_plan_world(api)

    lane1 = get_success_data(
        api.create_screening_lane(
            world.event_id,
            screening_lane_payload(
                world.zi_id, lane_type=LaneType.BAG_CHECK, nominal_throughput_pph=195,
                operator_capacity=2,
            ),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    world.lane1_id = lane1["id"]

    s1 = get_success_data(
        api.create_post(
            world.plan_id,
            post_payload(
                world.zf_id, "S1", PostType.SUPERVISOR, required_guard_count=1,
                min_credential_level=3,
            ),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    world.s1_id = s1["id"]

    i1 = get_success_data(
        api.create_post(
            world.plan_id,
            post_payload(
                world.zi_id, "I1", PostType.INGRESS_SCREENING, required_guard_count=2,
                reports_to_post_id=world.s1_id, lane_id=world.lane1_id,
            ),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    world.i1_id = i1["id"]

    f1 = get_success_data(
        api.create_post(
            world.plan_id,
            post_payload(
                world.zf_id, "F1", PostType.FLOOR, required_guard_count=1,
                reports_to_post_id=world.s1_id,
            ),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    world.f1_id = f1["id"]

    e1 = get_success_data(
        api.create_post(
            world.plan_id,
            post_payload(
                world.ze_id, "E1", PostType.EMERGENCY_EXIT, required_guard_count=1,
                reports_to_post_id=world.s1_id,
            ),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    world.e1_id = e1["id"]

    get_success_data(
        api.staffing_plan_lifecycle(world.plan_id, action("PUBLISH"), COORDINATOR_HEADERS)
    )

    world.gs_id = create_verified_guard(
        api, "GC-8001", credential_level=3, full_name="Sam Sentinel"
    )
    world.g1_id = create_verified_guard(api, "GC-8002", full_name="Gale One")
    world.g2_id = create_verified_guard(api, "GC-8003", full_name="Gale Two")
    world.g3_id = create_verified_guard(api, "GC-8004", full_name="Gale Three")
    world.g4_id = create_verified_guard(api, "GC-8005", full_name="Gale Four")
    world.guard_ids = [world.gs_id, world.g1_id, world.g2_id, world.g3_id, world.g4_id]

    world.a_s1 = create_assignment(api, world.s1_id, world.gs_id)
    world.a_i1 = create_assignment(api, world.i1_id, world.g1_id)
    world.a_i2 = create_assignment(api, world.i1_id, world.g2_id)
    world.a_f1 = create_assignment(api, world.f1_id, world.g3_id)
    world.a_e1 = create_assignment(api, world.e1_id, world.g4_id)
    world.assignment_ids = [world.a_s1, world.a_i1, world.a_i2, world.a_f1, world.a_e1]

    for assignment_id in world.assignment_ids:
        confirm(api, assignment_id)

    get_success_data(
        api.staffing_plan_lifecycle(world.plan_id, action("ACTIVATE"), DIRECTOR_HEADERS)
    )
    return world


def build_briefed_event_world(api: ApiClient) -> World:
    """Five-slot chain briefed all round, event in BRIEFED, clock just before doors."""
    world = build_five_post_activated_world(api)
    channels = {
        world.a_s1: "CH1",
        world.a_i1: "CH2",
        world.a_i2: "CH2",
        world.a_f1: "CH3",
        world.a_e1: "CH4",
    }
    for assignment_id, channel in channels.items():
        brief(api, assignment_id, world.gs_id, radio_channel=channel)
    get_success_data(api.event_lifecycle(world.event_id, action("BRIEF"), DIRECTOR_HEADERS))
    set_clock(api, PRE_DOORS_CLOCK)
    world.clock = PRE_DOORS_CLOCK
    return world


def build_six_post_briefed_world(api: ApiClient) -> World:
    """The six-slot two-lane chain: one guard per post, both lanes at capacity 1.

    required_total_staff is 6 across S1/P1/I1/I2/F1/E1, every slot filled at
    2200 cents an hour over a 7.50 hour window, so the ledger reads 99000 cents
    and 45.00 hours with the plan READY and ACTIVATED. Every assignment is then
    briefed and the event moved to BRIEFED.
    """
    world = build_plan_world(api)

    lane1 = get_success_data(
        api.create_screening_lane(
            world.event_id,
            screening_lane_payload(
                world.zi_id, lane_type=LaneType.BAG_CHECK, nominal_throughput_pph=195,
                operator_capacity=1,
            ),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    lane2 = get_success_data(
        api.create_screening_lane(
            world.event_id,
            screening_lane_payload(
                world.zi_id, lane_type=LaneType.EXPRESS_NO_BAG, nominal_throughput_pph=455,
                operator_capacity=1,
            ),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    world.lane1_id, world.lane2_id = lane1["id"], lane2["id"]

    s1 = get_success_data(
        api.create_post(
            world.plan_id,
            post_payload(
                world.zf_id, "S1", PostType.SUPERVISOR, required_guard_count=1,
                min_credential_level=3,
            ),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    world.s1_id = s1["id"]

    def _post(zone_id: str, code: str, post_type: str, **extra: Any) -> str:
        data = get_success_data(
            api.create_post(
                world.plan_id,
                post_payload(
                    zone_id, code, post_type, required_guard_count=1,
                    reports_to_post_id=world.s1_id, **extra
                ),
                COORDINATOR_HEADERS,
            ),
            expected_status=201,
        )
        return data["id"]

    world.p1_id = _post(world.zf_id, "P1", PostType.PERIMETER)
    world.i1_id = _post(world.zi_id, "I1", PostType.INGRESS_SCREENING, lane_id=world.lane1_id)
    world.i2_id = _post(world.zi_id, "I2", PostType.INGRESS_SCREENING, lane_id=world.lane2_id)
    world.f1_id = _post(world.zf_id, "F1", PostType.FLOOR)
    world.e1_id = _post(world.ze_id, "E1", PostType.EMERGENCY_EXIT)

    get_success_data(
        api.staffing_plan_lifecycle(world.plan_id, action("PUBLISH"), COORDINATOR_HEADERS)
    )

    world.gs_id = create_verified_guard(
        api, "GC-9001", credential_level=3, full_name="Sam Sentinel"
    )
    world.g1_id = create_verified_guard(api, "GC-9002", full_name="Gale One")
    world.g2_id = create_verified_guard(api, "GC-9003", full_name="Gale Two")
    world.g3_id = create_verified_guard(api, "GC-9004", full_name="Gale Three")
    world.g4_id = create_verified_guard(api, "GC-9005", full_name="Gale Four")
    world.g5_id = create_verified_guard(api, "GC-9006", full_name="Gale Five")
    world.guard_ids = [
        world.gs_id, world.g1_id, world.g2_id, world.g3_id, world.g4_id, world.g5_id
    ]

    world.a_s1 = create_assignment(api, world.s1_id, world.gs_id)
    world.a_p1 = create_assignment(api, world.p1_id, world.g1_id)
    world.a_i1 = create_assignment(api, world.i1_id, world.g2_id)
    world.a_i2 = create_assignment(api, world.i2_id, world.g3_id)
    world.a_f1 = create_assignment(api, world.f1_id, world.g4_id)
    world.a_e1 = create_assignment(api, world.e1_id, world.g5_id)
    world.assignment_ids = [
        world.a_s1, world.a_p1, world.a_i1, world.a_i2, world.a_f1, world.a_e1
    ]

    for assignment_id in world.assignment_ids:
        confirm(api, assignment_id)

    get_success_data(
        api.staffing_plan_lifecycle(world.plan_id, action("ACTIVATE"), DIRECTOR_HEADERS)
    )

    channels = {
        world.a_s1: "CH1",
        world.a_p1: "CH2",
        world.a_i1: "CH3",
        world.a_i2: "CH3",
        world.a_f1: "CH4",
        world.a_e1: "CH5",
    }
    for assignment_id, channel in channels.items():
        brief(api, assignment_id, world.gs_id, radio_channel=channel)
    get_success_data(api.event_lifecycle(world.event_id, action("BRIEF"), DIRECTOR_HEADERS))
    return world


def build_six_post_pre_doors_world(api: ApiClient) -> World:
    """Six-slot briefed chain with the clock advanced into the doors-open window."""
    world = build_six_post_briefed_world(api)
    set_clock(api, PRE_DOORS_CLOCK)
    world.clock = PRE_DOORS_CLOCK
    return world


def build_six_post_partial_checkin_world(api: ApiClient) -> World:
    """Supervisor and both ingress operators on post; the exit slot is still briefed."""
    world = build_six_post_pre_doors_world(api)
    for assignment_id in (world.a_s1, world.a_i1, world.a_i2):
        check_in(api, assignment_id, world.gs_id)
    return world


def build_doors_open_world(api: ApiClient) -> World:
    """Exit slot checked in as well, both lanes OPEN, event in DOORS_OPEN."""
    world = build_six_post_partial_checkin_world(api)
    check_in(api, world.a_e1, world.gs_id)
    get_success_data(
        api.screening_lane_status(world.lane1_id, action("OPEN"), COORDINATOR_HEADERS)
    )
    get_success_data(
        api.screening_lane_status(world.lane2_id, action("OPEN"), COORDINATOR_HEADERS)
    )
    get_success_data(api.event_lifecycle(world.event_id, action("DOORS_OPEN"), DIRECTOR_HEADERS))
    return world


# ─── Tier 5: live event through closure ───────────────


def build_closed_event_world(api: ApiClient) -> World:
    """Full show: one no-show, two density readings, three incidents, then CLOSE.

    The floor slot is marked NO_SHOW, so four rows are ON_POST when the event
    closes and each is relieved over a 6.00 hour actual span. Incident one is a
    MEDICAL/MODERATE triaged twelve minutes late, incident two a CROWD_SURGE
    triaged inside its budget, incident three a PROHIBITED_ITEM closed as
    unfounded.
    """
    world = build_doors_open_world(api)

    get_success_data(
        api.post_assignment_duty_event(
            world.a_f1, action("MARK_NO_SHOW"), make_post_supervisor_headers(world.gs_id)
        )
    )

    set_clock(api, INCIDENT_CLOCK)
    world.r_zf = get_success_data(
        api.create_density_reading(
            world.event_id,
            {"zone_id": world.zf_id, "observed_at": INCIDENT_CLOCK, "observed_occupancy": 100},
            DIRECTOR_HEADERS,
        ),
        expected_status=201,
    )["id"]
    world.r_zi = get_success_data(
        api.create_density_reading(
            world.event_id,
            {"zone_id": world.zi_id, "observed_at": INCIDENT_CLOCK, "observed_occupancy": 350},
            DIRECTOR_HEADERS,
        ),
        expected_status=201,
    )["id"]

    world.inc1 = get_success_data(
        api.create_incident(
            world.event_id,
            {
                "zone_id": world.zf_id,
                "category": "MEDICAL",
                "severity": "MODERATE",
                "description": "patron fainted at the pit rail",
            },
            COMMANDER_HEADERS,
        ),
        expected_status=201,
    )["id"]

    set_clock(api, TRIAGE_CLOCK)
    get_success_data(api.incident_action(world.inc1, action("TRIAGE"), COMMANDER_HEADERS))
    get_success_data(
        api.incident_action(
            world.inc1,
            action("MEDICAL_HANDOFF", handoff_agency_ref="EMS-4471"),
            COMMANDER_HEADERS,
        )
    )
    get_success_data(
        api.incident_action(
            world.inc1, action("RESOLVE", resolution_note="transported, stable"), COMMANDER_HEADERS
        )
    )

    world.inc2 = get_success_data(
        api.create_incident(
            world.event_id,
            {
                "zone_id": world.zi_id,
                "category": "CROWD_SURGE",
                "severity": "MINOR",
                "description": "brief push at door 1",
            },
            COMMANDER_HEADERS,
        ),
        expected_status=201,
    )["id"]
    get_success_data(api.incident_action(world.inc2, action("TRIAGE"), COMMANDER_HEADERS))
    get_success_data(
        api.incident_action(
            world.inc2, action("RESOLVE", resolution_note="line re-formed"), COMMANDER_HEADERS
        )
    )

    world.inc3 = get_success_data(
        api.create_incident(
            world.event_id,
            {
                "zone_id": world.zi_id,
                "category": "PROHIBITED_ITEM",
                "severity": "MINOR",
                "description": "reported knife, not substantiated",
            },
            COMMANDER_HEADERS,
        ),
        expected_status=201,
    )["id"]
    get_success_data(
        api.incident_action(
            world.inc3, action("CLOSE_UNFOUNDED", resolution_note="no item found"),
            COMMANDER_HEADERS,
        )
    )

    set_clock(api, START_CLOCK)
    get_success_data(api.event_lifecycle(world.event_id, action("START"), DIRECTOR_HEADERS))
    set_clock(api, CLOSE_CLOCK)
    get_success_data(api.event_lifecycle(world.event_id, action("CLOSE"), DIRECTOR_HEADERS))
    world.clock = CLOSE_CLOCK
    return world


def build_review_world(api: ApiClient, author_headers: Optional[Dict[str, str]] = None) -> World:
    """Closed event plus a DRAFT after-action review."""
    world = build_closed_event_world(api)
    review = get_success_data(
        api.create_after_action_review(
            world.event_id,
            {
                "narrative": (
                    "doors held twice, one medical handoff, one no-show on the floor post"
                ),
                "corrective_action_count": 3,
            },
            author_headers or COMMANDER_HEADERS,
        ),
        expected_status=201,
    )
    world.aar_id = review["id"]
    world.review = review
    return world


# ─── Parameterised roster scaffolds ───────────────────


def build_published_plan_with_posts_world(
    api: ApiClient,
    post_specs: List[Dict[str, Any]],
    budget_cents: int = 500000,
    publish: bool = True,
) -> World:
    """Draft plan carrying exactly ``post_specs``, optionally PUBLISHED.

    Each spec is a dict with ``code`` plus any of ``zone`` (``"zf"``, ``"zi"``
    or ``"ze"``, default ``"zf"``), ``post_type`` (default ``PERIMETER``),
    ``required_guard_count``, ``min_credential_level``, ``window_start`` and
    ``window_end``. Created ids land on ``world.posts[code]`` and are also
    exposed as ``world.<lowercased code>_id`` for convenience.
    """
    world = build_plan_world(api, budget_cents=budget_cents)
    world.posts = {}
    for spec in post_specs:
        spec = dict(spec)
        code = spec.pop("code")
        zone_key = spec.pop("zone", "zf")
        post_type = spec.pop("post_type", PostType.PERIMETER)
        zone_id = {"zf": world.zf_id, "zi": world.zi_id, "ze": world.ze_id}[zone_key]
        post = get_success_data(
            api.create_post(
                world.plan_id,
                post_payload(zone_id, code, post_type, **spec),
                COORDINATOR_HEADERS,
            ),
            expected_status=201,
        )
        world.posts[code] = post["id"]
        setattr(world, "%s_id" % code.lower(), post["id"])
    if publish:
        get_success_data(
            api.staffing_plan_lifecycle(world.plan_id, action("PUBLISH"), COORDINATOR_HEADERS)
        )
    return world


def build_canonical_five_post_activated_world(
    api: ApiClient, exit_guard_credential_expires_on: str = "2026-12-31T00:00:00Z"
) -> World:
    """Five single-guard posts, five confirmed guards, plan ACTIVATED.

    S1 supervises P1, I1, F1 and E1; each post needs exactly one guard, so
    required_total_staff is 5 and the roster fills every slot. Every shift runs
    the full 7.50 hour window at 2200 cents an hour, which puts the ledger at
    82500 committed cents and 37.50 committed guard hours. The exit guard's
    credential expiry is parameterised so a clock sweep can strand it.
    """
    world = build_published_plan_with_posts_world(
        api,
        [
            {"code": "S1", "zone": "zf", "post_type": PostType.SUPERVISOR,
             "min_credential_level": 3},
        ],
        publish=False,
    )
    world.s1_id = world.posts["S1"]
    for code, zone_key, post_type in (
        ("P1", "zf", PostType.PERIMETER),
        ("I1", "zi", PostType.INGRESS_SCREENING),
        ("F1", "zf", PostType.FLOOR),
        ("E1", "ze", PostType.EMERGENCY_EXIT),
    ):
        zone_id = {"zf": world.zf_id, "zi": world.zi_id, "ze": world.ze_id}[zone_key]
        post = get_success_data(
            api.create_post(
                world.plan_id,
                post_payload(
                    zone_id, code, post_type, required_guard_count=1,
                    reports_to_post_id=world.s1_id,
                ),
                COORDINATOR_HEADERS,
            ),
            expected_status=201,
        )
        world.posts[code] = post["id"]
        setattr(world, "%s_id" % code.lower(), post["id"])

    get_success_data(
        api.staffing_plan_lifecycle(world.plan_id, action("PUBLISH"), COORDINATOR_HEADERS)
    )

    world.gs_id = create_verified_guard(
        api, "GC-1001", credential_level=3, full_name="Sam Sentinel"
    )
    world.g1_id = create_verified_guard(api, "GC-1002", full_name="Gale One")
    world.g2_id = create_verified_guard(api, "GC-1003", full_name="Gale Two")
    world.g3_id = create_verified_guard(api, "GC-1004", full_name="Gale Three")
    world.g4_id = create_verified_guard(
        api,
        "GC-1005",
        full_name="Gale Four",
        credential_expires_on=exit_guard_credential_expires_on,
    )
    world.guard_ids = [world.gs_id, world.g1_id, world.g2_id, world.g3_id, world.g4_id]

    world.a_s1 = create_assignment(api, world.s1_id, world.gs_id)
    world.a_p1 = create_assignment(api, world.p1_id, world.g1_id)
    world.a_i1 = create_assignment(api, world.i1_id, world.g2_id)
    world.a_f1 = create_assignment(api, world.f1_id, world.g3_id)
    world.a_e1 = create_assignment(api, world.e1_id, world.g4_id)
    world.assignment_ids = [world.a_s1, world.a_p1, world.a_i1, world.a_f1, world.a_e1]
    for assignment_id in world.assignment_ids:
        confirm(api, assignment_id)

    get_success_data(
        api.staffing_plan_lifecycle(world.plan_id, action("ACTIVATE"), DIRECTOR_HEADERS)
    )
    return world
