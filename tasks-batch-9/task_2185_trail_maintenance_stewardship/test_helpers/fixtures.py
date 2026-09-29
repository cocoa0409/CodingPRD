"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only: the harness restarts the server before each test, so each test
starts against an empty database with the logical clock at its startup default.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    adoption_agreement_payload,
    briefing_payload,
    condition_report_payload,
    crew_leader_volunteer_payload,
    first_aider_volunteer_payload,
    incident_payload,
    land_manager_payload,
    material_order_payload,
    permit_issue_payload,
    sawyer_volunteer_payload,
    shift_registration_payload,
    trail_segment_payload,
    volunteer_payload,
    weather_observation_payload,
    work_party_payload,
    work_permit_payload,
    work_plan_payload,
)
from .test_users import (
    make_crew_leader_headers,
    make_grants_admin_headers,
    make_land_manager_headers,
    make_safety_officer_headers,
    make_volunteer_headers,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]


# --------------------------------------------------------------------------
# Tier 0: single-step creators and readers
# --------------------------------------------------------------------------

def create_land_manager(**overrides) -> dict:
    resp = api_client.create_land_manager(land_manager_payload(**overrides), COORD)
    return get_success_data(resp)


def create_land_manager_from(payload: dict) -> dict:
    return get_success_data(api_client.create_land_manager(payload, COORD))


def create_volunteer(**overrides) -> dict:
    return get_success_data(
        api_client.create_volunteer(volunteer_payload(**overrides), COORD)
    )


def create_crew_leader(**overrides) -> dict:
    return get_success_data(
        api_client.create_volunteer(crew_leader_volunteer_payload(**overrides), COORD)
    )


def create_sawyer(**overrides) -> dict:
    return get_success_data(
        api_client.create_volunteer(sawyer_volunteer_payload(**overrides), COORD)
    )


def create_first_aider(**overrides) -> dict:
    return get_success_data(
        api_client.create_volunteer(first_aider_volunteer_payload(**overrides), COORD)
    )


def create_trail_segment(land_manager_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_trail_segment(
            trail_segment_payload(land_manager_id, **overrides), COORD
        )
    )


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, COORD))


def observe_weather(trail_segment_id, soil_moisture_index, observed_at) -> dict:
    return get_success_data(
        api_client.record_weather_observation(
            weather_observation_payload(
                trail_segment_id, soil_moisture_index, observed_at
            ),
            COORD,
        )
    )


def read_land_manager(land_manager_id) -> dict:
    return get_success_data(api_client.get_land_manager(land_manager_id, COORD))


def read_volunteer(volunteer_id) -> dict:
    return get_success_data(api_client.get_volunteer(volunteer_id, COORD))


def read_segment(segment_id) -> dict:
    return get_success_data(api_client.get_trail_segment(segment_id, COORD))


def read_agreement(agreement_id) -> dict:
    return get_success_data(api_client.get_adoption_agreement(agreement_id, COORD))


def read_plan(plan_id) -> dict:
    return get_success_data(api_client.get_work_plan(plan_id, COORD))


def read_report(report_id) -> dict:
    return get_success_data(api_client.get_condition_report(report_id, COORD))


def read_permit(permit_id) -> dict:
    return get_success_data(api_client.get_work_permit(permit_id, COORD))


def read_party(party_id) -> dict:
    return get_success_data(api_client.get_work_party(party_id, COORD))


def read_shift(shift_id) -> dict:
    return get_success_data(api_client.get_shift(shift_id, COORD))


def read_material_order(order_id) -> dict:
    return get_success_data(api_client.get_material_order(order_id, COORD))


def read_incident(incident_id) -> dict:
    return get_success_data(api_client.get_incident(incident_id, COORD))


def party_version(party_id) -> int:
    return read_party(party_id)["version"]


def plan_version(plan_id) -> int:
    return read_plan(plan_id)["version"]


# --------------------------------------------------------------------------
# Tier 1: state progression for a single entity
# --------------------------------------------------------------------------

def create_agreement(trail_segment_id, crew_leader_volunteer_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_adoption_agreement(
            adoption_agreement_payload(
                trail_segment_id, crew_leader_volunteer_id, **overrides
            ),
            make_crew_leader_headers(crew_leader_volunteer_id),
        )
    )


def submit_agreement(agreement_id, crew_leader_volunteer_id) -> dict:
    return get_success_data(
        api_client.submit_adoption_agreement(
            agreement_id, make_crew_leader_headers(crew_leader_volunteer_id)
        )
    )


def review_agreement(agreement_id, decision="APPROVE", reason=None) -> dict:
    payload = {"decision": decision}
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(
        api_client.review_adoption_agreement(agreement_id, payload, COORD)
    )


def activate_agreement(agreement_id, land_manager_id) -> dict:
    return get_success_data(
        api_client.activate_adoption_agreement(
            agreement_id, make_land_manager_headers(land_manager_id)
        )
    )


def create_plan(agreement_id, crew_leader_volunteer_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_work_plan(
            work_plan_payload(agreement_id, **overrides),
            make_crew_leader_headers(crew_leader_volunteer_id),
        )
    )


def submit_plan(plan_id, crew_leader_volunteer_id) -> dict:
    return get_success_data(
        api_client.submit_work_plan(
            plan_id, make_crew_leader_headers(crew_leader_volunteer_id)
        )
    )


def review_plan(plan_id, decision="APPROVE", approved_budget_cents=None, reason=None) -> dict:
    payload = {"decision": decision}
    if approved_budget_cents is not None:
        payload["approved_budget_cents"] = approved_budget_cents
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(api_client.review_work_plan(plan_id, payload, COORD))


def create_permit(plan_id, segment_id, crew_leader_volunteer_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_work_permit(
            work_permit_payload(plan_id, segment_id, **overrides),
            make_crew_leader_headers(crew_leader_volunteer_id),
        )
    )


def issue_permit(permit_id, land_manager_id, **overrides) -> dict:
    return get_success_data(
        api_client.decide_work_permit(
            permit_id,
            permit_issue_payload(**overrides),
            make_land_manager_headers(land_manager_id),
        )
    )


def create_party(plan_id, segment_id, crew_leader_volunteer_id, permit_id=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_work_party(
            work_party_payload(plan_id, segment_id, permit_id, **overrides),
            make_crew_leader_headers(crew_leader_volunteer_id),
        )
    )


def brief_party(party_id, crew_leader_volunteer_id, **overrides) -> dict:
    return get_success_data(
        api_client.deliver_briefing(
            party_id,
            briefing_payload(**overrides),
            make_crew_leader_headers(crew_leader_volunteer_id),
        )
    )


def register_volunteer_on_party(party_id, crew_leader_volunteer_id, volunteer_id, expected_version=None, **overrides) -> dict:
    """Register a volunteer, reading the party's current version when not supplied."""
    if expected_version is None:
        expected_version = party_version(party_id)
    return get_success_data(
        api_client.register_shift(
            party_id,
            shift_registration_payload(volunteer_id, expected_version, **overrides),
            make_crew_leader_headers(crew_leader_volunteer_id),
        )
    )


def confirm_party(party_id, crew_leader_volunteer_id) -> dict:
    return get_success_data(
        api_client.confirm_work_party(
            party_id, make_crew_leader_headers(crew_leader_volunteer_id)
        )
    )


def start_party(party_id, crew_leader_volunteer_id) -> dict:
    return get_success_data(
        api_client.start_work_party(
            party_id, make_crew_leader_headers(crew_leader_volunteer_id)
        )
    )


def complete_party(party_id, crew_leader_volunteer_id) -> dict:
    return get_success_data(
        api_client.complete_work_party(
            party_id, make_crew_leader_headers(crew_leader_volunteer_id)
        )
    )


def check_in(shift_id, crew_leader_volunteer_id) -> dict:
    return get_success_data(
        api_client.check_in_shift(
            shift_id, make_crew_leader_headers(crew_leader_volunteer_id)
        )
    )


def check_out(shift_id, crew_leader_volunteer_id) -> dict:
    return get_success_data(
        api_client.check_out_shift(
            shift_id, make_crew_leader_headers(crew_leader_volunteer_id)
        )
    )


def verify_hours(shift_id) -> dict:
    return get_success_data(
        api_client.review_shift_hours(shift_id, {"decision": "VERIFY"}, COORD)
    )


def certify_hours(shift_id, user_id="grants-1") -> dict:
    return get_success_data(
        api_client.certify_shift_hours(shift_id, make_grants_admin_headers(user_id))
    )


def create_material_order(plan_id, crew_leader_volunteer_id, expected_version=None, **overrides) -> dict:
    if expected_version is None:
        expected_version = plan_version(plan_id)
    return get_success_data(
        api_client.create_material_order(
            material_order_payload(plan_id, expected_version, **overrides),
            make_crew_leader_headers(crew_leader_volunteer_id),
        )
    )


def create_report(segment_id, reporter_volunteer_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_condition_report(
            condition_report_payload(segment_id, reporter_volunteer_id, **overrides),
            make_volunteer_headers(reporter_volunteer_id),
        )
    )


def triage_report(report_id, exposure_class="MEDIUM", **overrides) -> dict:
    payload = {"exposure_class": exposure_class}
    payload.update(overrides)
    return get_success_data(
        api_client.triage_condition_report(report_id, payload, COORD)
    )


def disposition_report(report_id, disposition, **overrides) -> dict:
    payload = {"disposition": disposition}
    payload.update(overrides)
    return get_success_data(
        api_client.disposition_condition_report(report_id, payload, COORD)
    )


def file_incident(party_id, reporter_headers, **overrides) -> dict:
    return get_success_data(
        api_client.create_incident(incident_payload(party_id, **overrides), reporter_headers)
    )


# --------------------------------------------------------------------------
# Tier 2: the shared register - agency, volunteers and one trail segment
# --------------------------------------------------------------------------

def setup_registry(*, land_manager_overrides=None, segment_overrides=None,
                   with_first_aider=False) -> dict:
    """Agency, crew leader Rae, sawyer Milo, general volunteer Petra, Alder Creek.

    Returns a world dict that every later tier extends in place.
    """
    lm = create_land_manager(**(land_manager_overrides or {}))
    lead = create_crew_leader()
    saw = create_sawyer()
    gen = create_volunteer()
    seg = create_trail_segment(lm["id"], **(segment_overrides or {}))
    world = {
        "lm": lm,
        "lm_id": lm["id"],
        "lead": lead,
        "lead_id": lead["id"],
        "saw": saw,
        "saw_id": saw["id"],
        "gen": gen,
        "gen_id": gen["id"],
        "seg": seg,
        "seg_id": seg["id"],
        "lead_headers": make_crew_leader_headers(lead["id"]),
        "lm_headers": make_land_manager_headers(lm["id"]),
        "saw_headers": make_volunteer_headers(saw["id"]),
        "gen_headers": make_volunteer_headers(gen["id"]),
        "coordinator_headers": COORD,
        "safety_headers": make_safety_officer_headers(),
        "grants_headers": make_grants_admin_headers(),
    }
    if with_first_aider:
        aid = create_first_aider()
        world["aid"] = aid
        world["aid_id"] = aid["id"]
        world["aid_headers"] = make_volunteer_headers(aid["id"])
    return world


# --------------------------------------------------------------------------
# Tier 3: the adoption / plan / permit chain
# --------------------------------------------------------------------------

def setup_active_adoption(world=None, *, agreement_overrides=None, **registry_kwargs) -> dict:
    """Registry plus one agreement walked DRAFT -> SUBMITTED -> APPROVED -> ACTIVE."""
    world = world or setup_registry(**registry_kwargs)
    agreement = create_agreement(
        world["seg_id"], world["lead_id"], **(agreement_overrides or {})
    )
    submit_agreement(agreement["id"], world["lead_id"])
    review_agreement(agreement["id"], "APPROVE")
    agreement = activate_agreement(agreement["id"], world["lm_id"])
    world["agreement"] = agreement
    world["agreement_id"] = agreement["id"]
    return world


def setup_approved_plan(world=None, *, approved_budget_cents=None,
                        plan_overrides=None, **kwargs) -> dict:
    """Active adoption plus one work plan walked DRAFT -> SUBMITTED -> APPROVED."""
    world = world or setup_active_adoption(**kwargs)
    plan_overrides = dict(plan_overrides or {})
    plan = create_plan(world["agreement_id"], world["lead_id"], **plan_overrides)
    submit_plan(plan["id"], world["lead_id"])
    if approved_budget_cents is None:
        approved_budget_cents = plan_overrides.get(
            "requested_budget_cents", TEST_DEFAULTS["PLAN_BUDGET_CENTS"]
        )
    plan = review_plan(plan["id"], "APPROVE", approved_budget_cents=approved_budget_cents)
    world["plan"] = plan
    world["plan_id"] = plan["id"]
    world["approved_budget_cents"] = approved_budget_cents
    return world


def setup_issued_permit(world=None, *, permit_overrides=None, issue_overrides=None,
                        **kwargs) -> dict:
    """Approved plan plus one permit walked REQUESTED -> ISSUED."""
    world = world or setup_approved_plan(**kwargs)
    permit = create_permit(
        world["plan_id"], world["seg_id"], world["lead_id"], **(permit_overrides or {})
    )
    permit = issue_permit(permit["id"], world["lm_id"], **(issue_overrides or {}))
    world["permit"] = permit
    world["permit_id"] = permit["id"]
    return world


# --------------------------------------------------------------------------
# Tier 4: work parties and rosters
# --------------------------------------------------------------------------

def setup_planned_party(world=None, *, party_overrides=None, use_permit=True, **kwargs) -> dict:
    """Issued permit plus one PLANNED / PENDING work party."""
    world = world or setup_issued_permit(**kwargs)
    permit_id = world.get("permit_id") if use_permit else None
    party = create_party(
        world["plan_id"],
        world["seg_id"],
        world["lead_id"],
        permit_id,
        **(party_overrides or {}),
    )
    world["party"] = party
    world["party_id"] = party["id"]
    return world


def setup_briefed_party(world=None, *, briefing_overrides=None, **kwargs) -> dict:
    """Planned party whose briefing has landed, so the readiness axis has moved."""
    world = world or setup_planned_party(**kwargs)
    party = brief_party(
        world["party_id"], world["lead_id"], **(briefing_overrides or {})
    )
    world["party"] = party
    world["party_version_after_briefing"] = party["version"]
    return world


def setup_party_with_sawyer(world=None, *, role_on_crew="SAWYER", **kwargs) -> dict:
    """Briefed party with the certified, first-aid-carrying sawyer on the roster."""
    world = world or setup_briefed_party(**kwargs)
    shift = register_volunteer_on_party(
        world["party_id"],
        world["lead_id"],
        world["saw_id"],
        expected_version=world.get("party_version_after_briefing"),
        role_on_crew=role_on_crew,
    )
    world["shift_saw"] = shift
    world["shift_saw_id"] = shift["id"]
    return world


def setup_confirmed_party(world=None, **kwargs) -> dict:
    """Briefed, crewed party moved PLANNED -> CONFIRMED."""
    world = world or setup_party_with_sawyer(**kwargs)
    world["party"] = confirm_party(world["party_id"], world["lead_id"])
    return world


def setup_started_party(world=None, *, start_clock=None, **kwargs) -> dict:
    """Confirmed party moved CONFIRMED -> IN_PROGRESS at the party's start instant."""
    world = world or setup_confirmed_party(**kwargs)
    set_clock(start_clock or world["party"]["start_at"])
    world["party"] = start_party(world["party_id"], world["lead_id"])
    return world


def setup_checked_out_sawyer(world=None, *, check_out_at="2026-09-05T15:20:00.000Z",
                             **kwargs) -> dict:
    """Started party with the sawyer checked in at start_at and out at check_out_at."""
    world = world or setup_started_party(**kwargs)
    check_in(world["shift_saw_id"], world["lead_id"])
    set_clock(check_out_at)
    world["shift_saw"] = check_out(world["shift_saw_id"], world["lead_id"])
    return world


def setup_completed_party_with_hours(world=None, **kwargs) -> dict:
    """Sawyer checked out and the party moved IN_PROGRESS -> COMPLETED."""
    world = world or setup_checked_out_sawyer(**kwargs)
    world["party"] = complete_party(world["party_id"], world["lead_id"])
    return world


def setup_verified_sawyer_hours(world=None, **kwargs) -> dict:
    """Completed party whose sawyer shift has reached HOURS_VERIFIED."""
    world = world or setup_completed_party_with_hours(**kwargs)
    world["shift_saw"] = verify_hours(world["shift_saw_id"])
    return world


# --------------------------------------------------------------------------
# Tier 5: ledger, cascade and multi-segment scenarios
# --------------------------------------------------------------------------

SIGNAGE_LINES_205236 = [{"sku": "SIGN_POST", "unit_price_cents": 41000, "quantity": 5}]
BRIDGE_LINES_47700 = [{"sku": "BRIDGE_STRINGER", "unit_price_cents": 20000, "quantity": 2}]


def add_signage_requisition(world, **overrides) -> dict:
    """Raise the 205236-cent signage requisition against the plan."""
    return create_material_order(
        world["plan_id"],
        world["lead_id"],
        category="SIGNAGE",
        lines=list(SIGNAGE_LINES_205236),
        **overrides,
    )


def add_bridge_requisition(world, **overrides) -> dict:
    """Raise the 47700-cent bridge requisition against the plan."""
    return create_material_order(
        world["plan_id"],
        world["lead_id"],
        category="BRIDGE",
        lines=list(BRIDGE_LINES_47700),
        **overrides,
    )


def setup_over_committed_plan(world=None, **kwargs) -> dict:
    """Approved 250000-cent plan driven to OVER_COMMITTED by two requisitions.

    The bridge order (47700) is raised first and left without an engineering
    review reference; the signage order (205236) then takes committed_cents to
    252936 and available_cents to -2936.
    """
    world = world or setup_approved_plan(**kwargs)
    world["bridge_order"] = add_bridge_requisition(world)
    world["bridge_order_id"] = world["bridge_order"]["id"]
    world["signage_order"] = add_signage_requisition(world)
    world["signage_order_id"] = world["signage_order"]["id"]
    world["plan"] = read_plan(world["plan_id"])
    return world


def setup_second_adopted_segment(world, *, name="Bear Hollow",
                                 segment_overrides=None,
                                 permit_overrides=None,
                                 issue_overrides=None) -> dict:
    """A second adopted segment under the same agency with its own plan and permit."""
    overrides = {"name": name}
    overrides.update(segment_overrides or {})
    seg2 = create_trail_segment(world["lm_id"], **overrides)
    agreement2 = create_agreement(seg2["id"], world["lead_id"])
    submit_agreement(agreement2["id"], world["lead_id"])
    review_agreement(agreement2["id"], "APPROVE")
    agreement2 = activate_agreement(agreement2["id"], world["lm_id"])
    plan2 = create_plan(agreement2["id"], world["lead_id"])
    submit_plan(plan2["id"], world["lead_id"])
    plan2 = review_plan(
        plan2["id"], "APPROVE", approved_budget_cents=TEST_DEFAULTS["PLAN_BUDGET_CENTS"]
    )
    permit2 = create_permit(
        plan2["id"], seg2["id"], world["lead_id"], **(permit_overrides or {})
    )
    permit2 = issue_permit(permit2["id"], world["lm_id"], **(issue_overrides or {}))
    world["seg2"] = seg2
    world["seg2_id"] = seg2["id"]
    world["agreement2"] = agreement2
    world["agreement2_id"] = agreement2["id"]
    world["plan2"] = plan2
    world["plan2_id"] = plan2["id"]
    world["permit2"] = permit2
    world["permit2_id"] = permit2["id"]
    return world


def add_extra_party(world, *, key, start_at, end_at, plan_id=None, segment_id=None,
                    permit_id=None, brief=True, **party_overrides) -> dict:
    """Create (and optionally brief) an additional party, storing it under `key`."""
    party = create_party(
        plan_id or world["plan_id"],
        segment_id or world["seg_id"],
        world["lead_id"],
        permit_id if permit_id is not None else world.get("permit_id"),
        start_at=start_at,
        end_at=end_at,
        **party_overrides,
    )
    if brief:
        party = brief_party(party["id"], world["lead_id"])
    world[key] = party
    world[key + "_id"] = party["id"]
    return party


def setup_triaged_report(world=None, *, report_overrides=None, exposure_class="MEDIUM",
                         triage_overrides=None, **kwargs) -> dict:
    """Registry plus one condition report walked SUBMITTED -> TRIAGED."""
    world = world or setup_registry(**kwargs)
    report = create_report(
        world["seg_id"], world["gen_id"], **(report_overrides or {})
    )
    report = triage_report(report["id"], exposure_class, **(triage_overrides or {}))
    world["report"] = report
    world["report_id"] = report["id"]
    return world
