"""Composite setup helpers built exclusively out of published API calls.

The server is restarted with an empty store before every individual test, so
each helper here constructs the state it needs from scratch: opening a
production, clearing its pre-production gates to activate it, materializing
shots and stage tasks, calibrating rooms, registering pools, onboarding
partners and walking packages and deliverables to a requested state.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import (
    BUILD_LADDER_TO_PUBLISHED,
    GATE_APPROVED,
    PACKAGE_QC_PASSED,
    PHASE_DELIVERY,
    STAGES_IN_ORDER,
)
from .test_users import (
    ARTIST_HEADERS,
    ARTIST_USER_ID,
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    DIRECTOR_ALT_HEADERS,
    PRODUCTION_MANAGER_HEADERS,
    SUPERVISOR_HEADERS,
    SUPERVISOR_ALT_HEADERS,
    make_partner_representative_headers,
)

JsonDict = Dict[str, Any]


# ----------------------------------------------------------------------
# Logical clock
# ----------------------------------------------------------------------
def move_clock(client: ApiClient, to_iso8601: str) -> JsonDict:
    """Set the logical studio clock and return the reported reading."""
    return get_success_data(client.set_clock(to_iso8601, PRODUCTION_MANAGER_HEADERS))


# ----------------------------------------------------------------------
# Productions and gates
# ----------------------------------------------------------------------
def open_production(client: ApiClient, **overrides: Any) -> JsonDict:
    """Open a production in PRE_PRODUCTION with its gate set materialized."""
    payload = f.production_payload(**overrides)
    return get_success_data(client.create_production(payload, PRODUCTION_MANAGER_HEADERS))


def read_production(client: ApiClient, production_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(
        client.get_production(production_id, headers or PRODUCTION_MANAGER_HEADERS)
    )


def gates_of(client: ApiClient, production_id: str) -> List[JsonDict]:
    """Discover a production's gate rows through the gate collection read."""
    response = client.list_gates(
        PRODUCTION_MANAGER_HEADERS, {"production_id": production_id, "limit": 100}
    )
    return get_success_data(response)


def gate_for_type(client: ApiClient, production_id: str, gate_type: str) -> JsonDict:
    return f.find_by(gates_of(client, production_id), gate_type=gate_type)


def clear_gate(
    client: ApiClient,
    gate_id: str,
    package_url: str = "https://studio.example/gate/v1.pdf",
) -> JsonDict:
    """Submit a gate as the production manager and approve it as the director."""
    get_success_data(
        client.submit_gate(
            gate_id, f.gate_submit_payload(package_url), PRODUCTION_MANAGER_HEADERS
        )
    )
    return get_success_data(
        client.decide_gate(
            gate_id, f.gate_decision_payload(GATE_APPROVED), DIRECTOR_HEADERS
        )
    )


def activate_production(client: ApiClient, production_id: str) -> JsonDict:
    """Clear every outstanding gate in sequence so the show becomes active."""
    for gate in sorted(gates_of(client, production_id), key=lambda g: g["sequence_index"]):
        if gate["status"] != "LOCKED":
            clear_gate(client, gate["id"])
    return read_production(client, production_id)


def active_production(client: ApiClient, **overrides: Any) -> JsonDict:
    """Open a production and drive it to PRODUCTION_ACTIVE."""
    production = open_production(client, **overrides)
    return activate_production(client, production["id"])


# ----------------------------------------------------------------------
# Shots and stage tasks
# ----------------------------------------------------------------------
def create_shot(client: ApiClient, production_id: str, **overrides: Any) -> JsonDict:
    payload = f.shot_payload(production_id, **overrides)
    return get_success_data(client.create_shot(payload, PRODUCTION_MANAGER_HEADERS))


def tasks_of(client: ApiClient, shot_id: str) -> List[JsonDict]:
    """Discover a shot's five stage tasks through the stage-task collection read."""
    response = client.list_stage_tasks(
        PRODUCTION_MANAGER_HEADERS, {"shot_id": shot_id, "limit": 100}
    )
    return get_success_data(response)


def task_for_stage(client: ApiClient, shot_id: str, stage: str) -> JsonDict:
    return f.find_by(tasks_of(client, shot_id), stage=stage)


def read_task(client: ApiClient, task_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(
        client.get_stage_task(task_id, headers or PRODUCTION_MANAGER_HEADERS)
    )


def read_shot(client: ApiClient, shot_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(client.get_shot(shot_id, headers or PRODUCTION_MANAGER_HEADERS))


def shot_with_tasks(
    client: ApiClient, production_id: str, **overrides: Any
) -> Tuple[JsonDict, List[JsonDict]]:
    shot = create_shot(client, production_id, **overrides)
    return shot, tasks_of(client, shot["id"])


def assign_task(
    client: ApiClient, task_id: str, artist_user_id: str = ARTIST_USER_ID, **payload_overrides: Any
) -> JsonDict:
    payload = f.assign_payload(artist_user_id, **payload_overrides)
    return get_success_data(
        client.assign_stage_task(task_id, payload, PRODUCTION_MANAGER_HEADERS)
    )


def submit_task(
    client: ApiClient,
    task_id: str,
    headers: Optional[JsonDict] = None,
    **payload_overrides: Any,
) -> JsonDict:
    payload = f.task_submit_payload(**payload_overrides)
    return get_success_data(
        client.submit_stage_task(task_id, payload, headers or ARTIST_HEADERS)
    )


def approve_task(
    client: ApiClient, task_id: str, headers: Optional[JsonDict] = None
) -> JsonDict:
    payload = f.task_decision_payload("APPROVED")
    return get_success_data(
        client.decide_stage_task(task_id, payload, headers or SUPERVISOR_HEADERS)
    )


def walk_stage_to_approved(
    client: ApiClient, shot_id: str, stage: str, hours: Optional[float] = None
) -> JsonDict:
    """Assign, optionally log hours, submit and approve one stage of a shot."""
    task = task_for_stage(client, shot_id, stage)
    assign_task(client, task["id"])
    if hours is not None:
        get_success_data(
            client.log_hours(task["id"], f.log_hours_payload(hours), ARTIST_HEADERS)
        )
    submit_task(client, task["id"])
    return approve_task(client, task["id"])


def approve_stages_through(client: ApiClient, shot_id: str, stage: str) -> None:
    """Approve every stage of the shot up to and including the named one."""
    for candidate in STAGES_IN_ORDER:
        walk_stage_to_approved(client, shot_id, candidate)
        if candidate == stage:
            return


def task_in_progress(client: ApiClient, production_id: str) -> Tuple[JsonDict, JsonDict]:
    """A shot with its LAYOUT task assigned and therefore IN_PROGRESS."""
    shot = create_shot(client, production_id)
    task = task_for_stage(client, shot["id"], STAGES_IN_ORDER[0])
    assign_task(client, task["id"])
    return shot, read_task(client, task["id"])


# ----------------------------------------------------------------------
# Assets
# ----------------------------------------------------------------------
def create_asset(client: ApiClient, production_id: str, **overrides: Any) -> JsonDict:
    payload = f.asset_payload(production_id, **overrides)
    return get_success_data(client.create_asset(payload, PRODUCTION_MANAGER_HEADERS))


def publish_asset(client: ApiClient, asset_id: str) -> JsonDict:
    """Walk an asset up the build ladder to PUBLISHED."""
    result = None
    for step in BUILD_LADDER_TO_PUBLISHED:
        result = get_success_data(
            client.advance_asset_build(asset_id, f.advance_build_payload(step), ARTIST_HEADERS)
        )
    return result


def library_approve_asset(client: ApiClient, asset_id: str) -> JsonDict:
    """Nominate a published asset and approve it into the reuse library."""
    get_success_data(client.library_submit_asset(asset_id, {}, ARTIST_HEADERS))
    return get_success_data(
        client.library_decide_asset(
            asset_id, f.library_decision_payload("APPROVED"), SUPERVISOR_HEADERS
        )
    )


def library_source_asset(client: ApiClient, production_id: str, **overrides: Any) -> JsonDict:
    """An asset published and approved into the reuse library."""
    asset = create_asset(client, production_id, **overrides)
    publish_asset(client, asset["id"])
    return library_approve_asset(client, asset["id"])


def read_asset(client: ApiClient, asset_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(client.get_asset(asset_id, headers or PRODUCTION_MANAGER_HEADERS))


# ----------------------------------------------------------------------
# Screening rooms and review sessions
# ----------------------------------------------------------------------
def create_room(client: ApiClient, **overrides: Any) -> JsonDict:
    payload = f.screening_room_payload(**overrides)
    return get_success_data(client.create_screening_room(payload, PRODUCTION_MANAGER_HEADERS))


def calibrated_room(client: ApiClient, **overrides: Any) -> JsonDict:
    """A registered room with a calibration recorded at the current clock."""
    room = create_room(client, **overrides)
    return get_success_data(
        client.calibrate_screening_room(room["id"], {}, PRODUCTION_MANAGER_HEADERS)
    )


def read_room(client: ApiClient, room_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(
        client.get_screening_room(room_id, headers or PRODUCTION_MANAGER_HEADERS)
    )


def book_session(
    client: ApiClient, production_id: str, room_id: str, **overrides: Any
) -> JsonDict:
    payload = f.review_session_payload(production_id, room_id, **overrides)
    return get_success_data(client.create_review_session(payload, DIRECTOR_HEADERS))


def open_session(client: ApiClient, session_id: str) -> JsonDict:
    return get_success_data(client.start_review_session(session_id, {}, DIRECTOR_HEADERS))


def running_session(
    client: ApiClient, production_id: str, room_id: str, **overrides: Any
) -> JsonDict:
    """A session booked and opened so notes can be raised against it."""
    session = book_session(client, production_id, room_id, **overrides)
    return open_session(client, session["id"])


def raise_note(
    client: ApiClient, session_id: str, task_id: str, severity: str, **overrides: Any
) -> JsonDict:
    payload = f.director_note_payload(session_id, task_id, severity, **overrides)
    return get_success_data(client.create_director_note(payload, DIRECTOR_HEADERS))


def close_session(client: ApiClient, session_id: str) -> JsonDict:
    return get_success_data(client.close_review_session(session_id, {}, DIRECTOR_HEADERS))


def closed_client_review(client: ApiClient, production_id: str, room_id: str, **overrides: Any) -> JsonDict:
    """A CLIENT_REVIEW session driven all the way to CLOSED."""
    session = running_session(
        client, production_id, room_id, session_type="CLIENT_REVIEW", **overrides
    )
    return close_session(client, session["id"])


# ----------------------------------------------------------------------
# Render pools and jobs
# ----------------------------------------------------------------------
def create_pool(client: ApiClient, **overrides: Any) -> JsonDict:
    payload = f.render_pool_payload(**overrides)
    return get_success_data(client.create_render_pool(payload, PRODUCTION_MANAGER_HEADERS))


def read_pool(client: ApiClient, pool_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(client.get_render_pool(pool_id, headers or PRODUCTION_MANAGER_HEADERS))


def reserve_job(
    client: ApiClient, pool_id: str, task_id: str, expected_version: Optional[int] = None, **overrides: Any
) -> JsonDict:
    version = (
        expected_version
        if expected_version is not None
        else read_pool(client, pool_id)["version"]
    )
    payload = f.render_job_payload(pool_id, task_id, version, **overrides)
    return get_success_data(client.create_render_job(payload, PRODUCTION_MANAGER_HEADERS))


def read_job(client: ApiClient, job_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(client.get_render_job(job_id, headers or PRODUCTION_MANAGER_HEADERS))


# ----------------------------------------------------------------------
# Partners and packages
# ----------------------------------------------------------------------
def onboard_partner(client: ApiClient, **overrides: Any) -> JsonDict:
    payload = f.partner_payload(**overrides)
    return get_success_data(client.create_outsource_partner(payload, COORDINATOR_HEADERS))


def approved_partner(client: ApiClient, **overrides: Any) -> JsonDict:
    """A partner onboarded with a certification and moved to APPROVED."""
    overrides.setdefault("security_certification_level", "TIER1")
    partner = onboard_partner(client, **overrides)
    return get_success_data(
        client.set_partner_status(
            partner["id"], f.partner_status_payload("APPROVED"), COORDINATOR_HEADERS
        )
    )


def read_partner(client: ApiClient, partner_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(
        client.get_outsource_partner(partner_id, headers or COORDINATOR_HEADERS)
    )


def draft_package(
    client: ApiClient, production_id: str, partner_id: str, **overrides: Any
) -> JsonDict:
    payload = f.package_payload(production_id, partner_id, **overrides)
    return get_success_data(client.create_outsource_package(payload, COORDINATOR_HEADERS))


def issue_package(client: ApiClient, package_id: str) -> JsonDict:
    return get_success_data(client.issue_package(package_id, {}, COORDINATOR_HEADERS))


def issued_package(
    client: ApiClient, production_id: str, partner_id: str, **overrides: Any
) -> JsonDict:
    package = draft_package(client, production_id, partner_id, **overrides)
    return issue_package(client, package["id"])


def accept_package(client: ApiClient, package_id: str, partner_id: str) -> JsonDict:
    return get_success_data(
        client.accept_package(package_id, {}, make_partner_representative_headers(partner_id))
    )


def accepted_package(
    client: ApiClient, production_id: str, partner_id: str, **overrides: Any
) -> JsonDict:
    package = issued_package(client, production_id, partner_id, **overrides)
    return accept_package(client, package["id"], partner_id)


def deliver_package(
    client: ApiClient, package_id: str, partner_id: str, watermark_applied: bool = True
) -> JsonDict:
    return get_success_data(
        client.deliver_package(
            package_id,
            f.package_deliver_payload(watermark_applied),
            make_partner_representative_headers(partner_id),
        )
    )


def delivered_package(
    client: ApiClient, production_id: str, partner_id: str, **overrides: Any
) -> JsonDict:
    package = accepted_package(client, production_id, partner_id, **overrides)
    return deliver_package(client, package["id"], partner_id)


def qc_package(client: ApiClient, package_id: str, decision: str, qc_score: int) -> JsonDict:
    return get_success_data(
        client.qc_decide_package(
            package_id, f.package_qc_payload(decision, qc_score), SUPERVISOR_HEADERS
        )
    )


def read_package(client: ApiClient, package_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(
        client.get_outsource_package(package_id, headers or COORDINATOR_HEADERS)
    )


# ----------------------------------------------------------------------
# Deliverables
# ----------------------------------------------------------------------
def create_deliverable(
    client: ApiClient, production_id: str, expected_version: Optional[int] = None, **overrides: Any
) -> JsonDict:
    version = (
        expected_version
        if expected_version is not None
        else read_production(client, production_id)["version"]
    )
    payload = f.deliverable_payload(production_id, version, **overrides)
    return get_success_data(client.create_deliverable(payload, PRODUCTION_MANAGER_HEADERS))


def submit_deliverable(client: ApiClient, deliverable_id: str) -> JsonDict:
    return get_success_data(
        client.submit_deliverable(deliverable_id, {}, PRODUCTION_MANAGER_HEADERS)
    )


def qc_pass_deliverable(client: ApiClient, deliverable_id: str, qc_note: Optional[str] = None) -> JsonDict:
    payload = f.deliverable_qc_payload("PASS")
    if qc_note is not None:
        payload["qc_note"] = qc_note
    return get_success_data(
        client.qc_decide_deliverable(deliverable_id, payload, SUPERVISOR_HEADERS)
    )


def qc_passed_deliverable(
    client: ApiClient, production_id: str, qc_note: Optional[str] = None, **overrides: Any
) -> JsonDict:
    """A deliverable created, submitted and passed through QC."""
    deliverable = create_deliverable(client, production_id, **overrides)
    submit_deliverable(client, deliverable["id"])
    return qc_pass_deliverable(client, deliverable["id"], qc_note)


def advance_to_delivery(client: ApiClient, production_id: str) -> JsonDict:
    return get_success_data(
        client.advance_production_phase(
            production_id, f.advance_phase_payload(PHASE_DELIVERY), PRODUCTION_MANAGER_HEADERS
        )
    )


def read_deliverable(client: ApiClient, deliverable_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(
        client.get_deliverable(deliverable_id, headers or PRODUCTION_MANAGER_HEADERS)
    )
