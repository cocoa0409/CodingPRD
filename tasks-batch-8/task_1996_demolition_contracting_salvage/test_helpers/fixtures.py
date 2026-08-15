"""Composite setup helpers (PRD §3 workflows).

The release gate (PRD §3.7) requires: all surveys COMPLETE, every abatement
CLEARANCE_CERTIFIED, >= 1 confirmed utility disconnect, an ACTIVE unexpired
permit, a pinned CERTIFIED engineering survey, >= 1 DELIVERED notification,
and the 72-hour wait window elapsed. Most test claims need a project deep in
the phase pipeline, so the fixtures below build that chain once per test.

All setup calls use get_success_data() so failures surface as setup errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_project_payload,
    create_structure_survey_payload,
    complete_survey_payload,
    create_abatement_payload,
    create_utility_disconnect_payload,
    create_permit_payload,
    create_engineering_survey_payload,
    create_neighbor_notification_payload,
    create_dust_noise_log_payload,
    create_debris_ticket_payload,
    create_backfill_plan_payload,
    create_final_inspection_payload,
)
from .test_users import (
    TEST_USERS,
    make_utility_coordinator_headers,
    make_structural_engineer_headers,
    make_peer_review_engineer_headers,
    make_abatement_supervisor_headers,
    make_clearance_officer_headers,
)

ADMIN = TEST_USERS["contractor_admin_headers"]
SUPERVISOR = TEST_USERS["site_supervisor_headers"]
SURVEYOR = TEST_USERS["surveyor_headers"]
PERMIT = TEST_USERS["permit_coordinator_headers"]
AUTHORITY = TEST_USERS["authority_reviewer_headers"]
MONITOR = TEST_USERS["environmental_monitor_headers"]
HAULER = TEST_USERS["hauling_dispatcher_headers"]
INSPECTOR = TEST_USERS["municipal_inspector_headers"]
ENGINEER = TEST_USERS["structural_engineer_headers"]
ESTIMATOR = TEST_USERS["salvage_estimator_headers"]

# A unique-id counter so SoD-anchored operator ids never collide across fixtures.
_uid_counter = {"n": 0}


def _uid(prefix: str) -> str:
    _uid_counter["n"] += 1
    return f"{prefix}-{_uid_counter['n']}"


# ---------------------------------------------------------------------------
# Tier 1: atomic entity creation
# ---------------------------------------------------------------------------

def create_project(**overrides):
    """Create a bare DRAFT project. Returns the project dict."""
    resp = api_client.create_project(create_project_payload(**overrides), ADMIN)
    return get_success_data(resp)


def set_clock(to_iso8601: str):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(resp)


def create_and_complete_survey(project_id, label="Main", hazmat_found=False):
    """Create a survey under the project and COMPLETE it. Returns survey dict."""
    survey = get_success_data(
        api_client.create_structure_survey(
            project_id, create_structure_survey_payload(structure_label=label), SURVEYOR
        )
    )
    return get_success_data(
        api_client.transition_structure_survey(
            survey["id"],
            complete_survey_payload(hazmat_found=hazmat_found),
            SURVEYOR,
        )
    )


def create_confirmed_disconnect(project_id, utility_type="ELECTRIC"):
    """Schedule a disconnect and walk it to REPORTED_DISCONNECTED x CONFIRMED.

    Uses three distinct operator ids so the SoD rule (PRD §2.8) holds.
    Returns the disconnect dict.
    """
    ud = get_success_data(
        api_client.create_utility_disconnect(
            project_id,
            create_utility_disconnect_payload(utility_type=utility_type),
            TEST_USERS["utility_coordinator_headers"],
        )
    )
    uc = TEST_USERS["utility_coordinator_headers"]
    get_success_data(
        api_client.transition_utility_disconnect(
            ud["id"], {"action": "REPORT_DISCONNECTED"},
            make_utility_coordinator_headers(_uid("uc-rep")),
        )
    )
    get_success_data(
        api_client.transition_utility_disconnect(
            ud["id"], {"action": "VERIFY"},
            make_utility_coordinator_headers(_uid("uc-ver")),
        )
    )
    return get_success_data(
        api_client.transition_utility_disconnect(
            ud["id"], {"action": "CONFIRM"},
            make_utility_coordinator_headers(_uid("uc-conf")),
        )
    )


def create_active_permit(project_id, area_sqft=None):
    """Create a permit and walk DRAFT -> UNDER_REVIEW -> APPROVED -> ACTIVE.

    PRD §3.3: ACTIVATE requires every disconnect REPORTED_DISCONNECTED and
    CONFIRMED, so run create_confirmed_disconnect() first. Returns permit dict.
    """
    payload = create_permit_payload()
    if area_sqft is not None:
        payload["gross_floor_area_sqft"] = area_sqft
    pm = get_success_data(api_client.create_permit(project_id, payload, PERMIT))
    get_success_data(api_client.transition_permit(pm["id"], {"action": "SUBMIT"}, PERMIT))
    get_success_data(api_client.transition_permit(pm["id"], {"action": "APPROVE"}, AUTHORITY))
    return get_success_data(api_client.transition_permit(pm["id"], {"action": "ACTIVATE"}, PERMIT))


def create_certified_engineering_survey(project_id):
    """Author an engineering survey and walk DRAFT -> SUBMITTED -> CERTIFIED.

    Author and certifier are distinct operator ids (PRD §2.8). Returns survey.
    """
    es = get_success_data(
        api_client.create_engineering_survey(
            project_id,
            create_engineering_survey_payload(),
            make_structural_engineer_headers(_uid("es-author")),
        )
    )
    author_id = es["author_user_id"]
    get_success_data(
        api_client.transition_engineering_survey(
            es["id"], {"action": "SUBMIT"}, make_structural_engineer_headers(author_id)
        )
    )
    return get_success_data(
        api_client.transition_engineering_survey(
            es["id"], {"action": "CERTIFY"}, make_peer_review_engineer_headers(_uid("es-peer"))
        )
    )


def pin_engineering_survey(project_id, survey_id):
    """Pin a CERTIFIED engineering survey with the current project version (OCC)."""
    project = get_success_data(api_client.get_project(project_id, SUPERVISOR))
    return get_success_data(
        api_client.pin_engineering_survey(
            project_id,
            {"engineering_survey_id": survey_id, "expected_project_version": project["version"]},
            SUPERVISOR,
        )
    )


def create_and_deliver_notification(project_id, address="1 Neighbor Ave"):
    """Create a notification and DELIVER it at the current logical clock.

    Caller must position the clock outside quiet hours [19:00, 07:00) UTC
    and outside blackout dates first. Returns the delivered notification.
    """
    nn = get_success_data(
        api_client.create_neighbor_notification(
            project_id, create_neighbor_notification_payload(address=address), SUPERVISOR
        )
    )
    return get_success_data(
        api_client.transition_neighbor_notification(nn["id"], {"action": "DELIVER"}, SUPERVISOR)
    )


# ---------------------------------------------------------------------------
# Tier 2: preconditions assembly (project in PRECONDITIONS_PENDING, gate-ready)
# ---------------------------------------------------------------------------

def setup_preconditions_pending(name="Gate Lot", address="1 Elm St", **project_overrides):
    """Project in PRECONDITIONS_PENDING with: clean COMPLETE survey, one
    CONFIRMED disconnect, an ACTIVE permit, and a CERTIFIED engineering survey
    (not yet pinned, no notifications yet).

    Clock is left at CLOCK_INIT (2026-08-01T09:00:00Z).
    Returns dict with keys: project, survey, disconnect, permit, engineering.
    """
    set_clock(TEST_DEFAULTS["CLOCK_INIT"])
    project = create_project(name=name, address=address, **project_overrides)
    pid = project["id"]
    survey = create_and_complete_survey(pid)
    disconnect = create_confirmed_disconnect(pid)
    permit = create_active_permit(pid)
    engineering = create_certified_engineering_survey(pid)
    return {
        "project": get_success_data(api_client.get_project(pid, SUPERVISOR)),
        "survey": survey,
        "disconnect": disconnect,
        "permit": permit,
        "engineering": engineering,
    }


def setup_release_ready(name="Ready Lot", address="2 Elm St", **project_overrides):
    """Fully gate-satisfied project still in PRECONDITIONS_PENDING.

    Like setup_preconditions_pending plus: engineering pin set, one
    notification DELIVERED at CLOCK_DELIVER (2026-08-02T09:00:00Z), and the
    clock advanced to CLOCK_RELEASE (2026-08-05T09:00:00Z = delivered + 72h).
    Returns the setup dict plus 'notification'.
    """
    ctx = setup_preconditions_pending(name=name, address=address, **project_overrides)
    pid = ctx["project"]["id"]
    pin_engineering_survey(pid, ctx["engineering"]["id"])
    nn = get_success_data(
        api_client.create_neighbor_notification(
            pid, create_neighbor_notification_payload(address=f"{address} neighbor"), SUPERVISOR
        )
    )
    set_clock(TEST_DEFAULTS["CLOCK_DELIVER"])
    nn = get_success_data(
        api_client.transition_neighbor_notification(nn["id"], {"action": "DELIVER"}, SUPERVISOR)
    )
    set_clock(TEST_DEFAULTS["CLOCK_RELEASE"])
    ctx["notification"] = nn
    ctx["project"] = get_success_data(api_client.get_project(pid, SUPERVISOR))
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: phase-pipeline shortcuts
# ---------------------------------------------------------------------------

def setup_released_project(name="Released Lot", address="3 Elm St", **project_overrides):
    """Project driven through the release gate to RELEASED."""
    ctx = setup_release_ready(name=name, address=address, **project_overrides)
    pid = ctx["project"]["id"]
    project = get_success_data(api_client.release_project(pid, {}, SUPERVISOR))
    ctx["project"] = project
    return ctx


def setup_demolition_active(name="Demo Lot", address="4 Elm St", **project_overrides):
    """Project in DEMOLITION_ACTIVE: released, then START_DEMOLITION."""
    ctx = setup_released_project(name=name, address=address, **project_overrides)
    pid = ctx["project"]["id"]
    project = get_success_data(
        api_client.transition_project(pid, {"action": "START_DEMOLITION"}, SUPERVISOR)
    )
    ctx["project"] = project
    return ctx


def setup_debris_clearance(name="Debris Lot", address="5 Elm St", tickets=None,
                           **project_overrides):
    """Project in DEBRIS_CLEARANCE with optional received tickets.

    tickets: list of (gross_tons, diverted_tons) tuples; each ticket is
    manifested then RECEIVEd with the given diverted tonnage. Returns ctx
    with 'tickets' (list of ticket dicts after RECEIVE).
    """
    ctx = setup_demolition_active(name=name, address=address, **project_overrides)
    pid = ctx["project"]["id"]
    received = []
    for i, (gross, diverted) in enumerate(tickets or []):
        tk = get_success_data(
            api_client.create_debris_ticket(
                pid,
                create_debris_ticket_payload(
                    ticket_number=f"T-{i + 1}", gross_tons=gross,
                    facility_type="RECYCLING" if i % 2 == 0 else "LANDFILL",
                    material_class="CONCRETE" if i % 2 == 0 else "WOOD",
                ),
                HAULER,
            )
        )
        received.append(
            get_success_data(
                api_client.transition_debris_ticket(
                    tk["id"], {"action": "RECEIVE", "diverted_tons": diverted}, HAULER
                )
            )
        )
    ctx["tickets"] = received
    ctx["project"] = get_success_data(
        api_client.transition_project(pid, {"action": "COMPLETE_STRUCTURE_REMOVAL"}, SUPERVISOR)
    )
    return ctx


def setup_backfill_phase(name="Backfill Lot", address="6 Elm St", tickets=None,
                         plan_overrides=None, complete_plan=False, **project_overrides):
    """Project in BACKFILL_PHASE with an APPROVED (or COMPLETE) backfill plan.

    When complete_plan is True the plan is walked APPROVE -> RECORD_COMPACTION
    (96.0 >= 95.0) -> VERIFY_EROSION (9180/10200 = 0.9000) -> COMPLETE.
    Returns ctx with 'tickets' and 'backfill_plan'.
    """
    ctx = setup_debris_clearance(
        name=name, address=address, tickets=tickets, **project_overrides
    )
    pid = ctx["project"]["id"]
    plan = get_success_data(
        api_client.create_backfill_plan(
            pid, create_backfill_plan_payload(**(plan_overrides or {})), SUPERVISOR
        )
    )
    plan = get_success_data(
        api_client.transition_backfill_plan(
            plan["id"], {"action": "APPROVE"},
            make_structural_engineer_headers(_uid("bp-eng")),
        )
    )
    ctx["backfill_plan"] = plan
    ctx["project"] = get_success_data(
        api_client.transition_project(pid, {"action": "START_BACKFILL"}, SUPERVISOR)
    )
    if complete_plan:
        plan = get_success_data(
            api_client.transition_backfill_plan(
                plan["id"], {"action": "RECORD_COMPACTION", "compaction_pct": 96.0}, SUPERVISOR
            )
        )
        plan = get_success_data(
            api_client.transition_backfill_plan(
                plan["id"],
                {
                    "action": "VERIFY_EROSION",
                    "measured_protected_area_sqft": 9180,
                    "measured_disturbed_area_sqft": 10200,
                },
                INSPECTOR,
            )
        )
        plan = get_success_data(
            api_client.transition_backfill_plan(plan["id"], {"action": "COMPLETE"}, SUPERVISOR)
        )
        ctx["backfill_plan"] = plan
    return ctx


def setup_final_review(name="Final Lot", address="7 Elm St", tickets=None,
                       schedule_inspection=True, **project_overrides):
    """Project in FINAL_REVIEW with a COMPLETE backfill plan and (optionally)
    a SCHEDULED final inspection.

    Default tickets [(8.0, 4.0), (4.0, 2.0)] give diversion_rate 0.5000,
    exactly the default required_diversion_rate 0.5 (PRD §3.9).
    Returns ctx with 'tickets', 'backfill_plan', 'inspection'.
    """
    if tickets is None:
        tickets = [(8.0, 4.0), (4.0, 2.0)]
    ctx = setup_backfill_phase(
        name=name, address=address, tickets=tickets, complete_plan=True, **project_overrides
    )
    pid = ctx["project"]["id"]
    ctx["project"] = get_success_data(
        api_client.transition_project(pid, {"action": "SUBMIT_FINAL_REVIEW"}, SUPERVISOR)
    )
    if schedule_inspection:
        ctx["inspection"] = get_success_data(
            api_client.create_final_inspection(
                pid, create_final_inspection_payload(), INSPECTOR
            )
        )
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: posture / exceedance helpers
# ---------------------------------------------------------------------------

def append_dust_log(project_id, measured_value=100, wind_speed_mph=10,
                    duration_hours=5, reading_type="PM25"):
    """Append one dust/noise event. Returns the created log dict."""
    return get_success_data(
        api_client.create_dust_noise_log(
            project_id,
            create_dust_noise_log_payload(
                reading_type=reading_type,
                measured_value=measured_value,
                wind_speed_mph=wind_speed_mph,
                duration_hours=duration_hours,
            ),
            MONITOR,
        )
    )


def stop_project_with_exceedance(project_id):
    """Flip the project to STOPPED via a dust exceedance (score 80.0 >= 75.0).

    measured 100 x wind factor 1.6 (15 mph tier) x 5h / 10 = 80.0.
    Returns the exceedance log dict.
    """
    return append_dust_log(project_id, measured_value=100, wind_speed_mph=15, duration_hours=5)
