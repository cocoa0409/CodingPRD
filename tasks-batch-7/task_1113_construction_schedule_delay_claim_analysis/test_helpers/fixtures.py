"""Composite setup helpers.

Every fixture builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before each test, so each test
starts against an empty database). Setup calls use the lenient
`get_success_data()` validator so failures surface as clear setup errors.

All roles in this PRD use opaque identity headers (PRD §2.1), so the shared
`TEST_USERS` constants are the canonical headers for every call.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_STARTUP_CLOCK, TEST_DEFAULTS
from .factories import (
    create_project_payload,
    create_schedule_version_payload,
    create_activity_payload,
    create_relationship_payload,
    create_progress_update_payload,
    create_delay_event_payload,
    create_eot_request_payload,
    create_acceleration_directive_payload,
    create_ld_assessment_payload,
    accept_schedule_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["system_admin_headers"]
PCE = TEST_USERS["project_controls_engineer_headers"]
CONTRACTOR = TEST_USERS["contractor_scheduler_headers"]
OWNER = TEST_USERS["owner_representative_headers"]
CLAIMS = TEST_USERS["claims_consultant_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_STARTUP_CLOCK):
    """Pin the server logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------

def create_project(**overrides):
    """Create a project (status PRECONSTRUCTION). Returns the project dict."""
    set_clock()
    return get_success_data(api_client.create_project(create_project_payload(**overrides), PCE))


def get_project(pid):
    return get_success_data(api_client.get_project(pid, PCE))


def get_project_version(pid):
    return get_project(pid)["version"]


# ---------------------------------------------------------------------------
# Schedule versions, activities, relationships
# ---------------------------------------------------------------------------

def create_schedule_version(pid, kind="BASELINE", data_date=None, supersedes_version_id=None):
    payload = create_schedule_version_payload(
        kind=kind,
        data_date=data_date or TEST_DEFAULTS["BASELINE_DATA_DATE"],
    )
    if supersedes_version_id is not None:
        payload["supersedes_version_id"] = supersedes_version_id
    return get_success_data(api_client.create_schedule_version(pid, payload, CONTRACTOR))


def add_activity(pid, vid, activity_code, original_duration_days, **overrides):
    payload = create_activity_payload(
        activity_code=activity_code,
        original_duration_days=original_duration_days,
        **overrides,
    )
    return get_success_data(api_client.create_activity(pid, vid, payload, CONTRACTOR))


def add_relationship(pid, vid, predecessor_activity_id, successor_activity_id, **overrides):
    payload = create_relationship_payload(
        predecessor_activity_id, successor_activity_id, **overrides
    )
    return get_success_data(api_client.create_relationship(pid, vid, payload, CONTRACTOR))


def submit_schedule(pid, vid):
    return get_success_data(api_client.submit_schedule_version(pid, vid, CONTRACTOR))


def accept_schedule(pid, vid, expected_project_version=None):
    if expected_project_version is None:
        expected_project_version = get_project_version(pid)
    return get_success_data(
        api_client.accept_schedule_version(
            pid, vid, accept_schedule_payload(expected_project_version), PCE
        )
    )


def reject_schedule(pid, vid):
    return get_success_data(api_client.reject_schedule_version(pid, vid, PCE))


def revise_schedule(pid, vid):
    return get_success_data(api_client.revise_schedule_version(pid, vid, CONTRACTOR))


def get_activity(pid, vid, aid):
    return get_success_data(api_client.get_activity(pid, vid, aid, PCE))


def get_schedule_version(pid, vid):
    return get_success_data(api_client.get_schedule_version(pid, vid, PCE))


# ---------------------------------------------------------------------------
# Composite schedule fixtures
# ---------------------------------------------------------------------------

def create_draft_schedule_with_activities(pid, kind="BASELINE", data_date=None,
                                          activity_durations=None, relationships=None):
    """Create a DRAFT schedule version with activities and FS logic ties.

    activity_durations: list of (activity_code, duration_days) tuples.
    relationships: list of (pred_index, succ_index, type, lag) tuples indexing
                   into activity_durations.
    Returns (version, activity_ids list).
    """
    version = create_schedule_version(pid, kind=kind, data_date=data_date)
    activity_ids = []
    for code, duration in (activity_durations or []):
        act = add_activity(pid, version["id"], code, duration)
        activity_ids.append(act["id"])
    for pred_idx, succ_idx, rel_type, lag in (relationships or []):
        add_relationship(
            pid,
            version["id"],
            activity_ids[pred_idx],
            activity_ids[succ_idx],
            relationship_type=rel_type,
            lag_days=lag,
        )
    return version, activity_ids


def setup_accepted_baseline(**project_overrides):
    """Project + ACCEPTED one-activity BASELINE (project auto-activates, PRD §3.1/§3.3).

    Returns dict(project, baseline, activity_ids).
    """
    project = create_project(**project_overrides)
    baseline, activity_ids = create_draft_schedule_with_activities(
        project["id"],
        kind="BASELINE",
        data_date=TEST_DEFAULTS["BASELINE_DATA_DATE"],
        activity_durations=[("A", TEST_DEFAULTS["ACTIVITY_DURATION_DAYS"])],
    )
    submit_schedule(project["id"], baseline["id"])
    accepted = accept_schedule(project["id"], baseline["id"])
    return {"project": get_project(project["id"]), "baseline": accepted,
            "activity_ids": activity_ids}


def setup_accepted_update(baseline_activity_durations=None,
                          update_activity_durations=None,
                          update_data_date="2026-05-08T00:00:00Z",
                          **project_overrides):
    """Project with ACCEPTED BASELINE and ACCEPTED UPDATE (PRD §3.3).

    Returns dict(project, baseline, baseline_activity_ids, update, update_activity_ids).
    """
    ctx = setup_accepted_baseline(**project_overrides)
    pid = ctx["project"]["id"]
    update, update_activity_ids = create_draft_schedule_with_activities(
        pid,
        kind="UPDATE",
        data_date=update_data_date,
        activity_durations=update_activity_durations
        or [("A", TEST_DEFAULTS["ACTIVITY_DURATION_DAYS"])],
    )
    submit_schedule(pid, update["id"])
    accepted_update = accept_schedule(pid, update["id"])
    return {
        "project": get_project(pid),
        "baseline": ctx["baseline"],
        "baseline_activity_ids": ctx["activity_ids"],
        "update": accepted_update,
        "update_activity_ids": update_activity_ids,
    }


# ---------------------------------------------------------------------------
# Progress reporting
# ---------------------------------------------------------------------------

def create_progress_update(pid, vid, **overrides):
    payload = create_progress_update_payload(**overrides)
    return get_success_data(api_client.create_progress_update(pid, vid, payload, CONTRACTOR))


def add_progress_entry(pid, vid, puid, payload):
    return get_success_data(api_client.create_progress_entry(pid, vid, puid, payload, CONTRACTOR))


def submit_progress_update(pid, vid, puid):
    return get_success_data(api_client.submit_progress_update(pid, vid, puid, CONTRACTOR))


def approve_progress_update(pid, vid, puid):
    return get_success_data(api_client.approve_progress_update(pid, vid, puid, PCE))


# ---------------------------------------------------------------------------
# Delay events / TIA
# ---------------------------------------------------------------------------

def create_delay_event(pid, **overrides):
    payload = create_delay_event_payload(**overrides)
    return get_success_data(api_client.create_delay_event(pid, payload, CONTRACTOR))


def notice_delay_event(pid, did):
    return get_success_data(api_client.notice_delay_event(pid, did, CONTRACTOR))


def setup_tia_accepted_event(pid, update_version_id, fragnet_activity_id,
                             causation="FORCE_MAJEURE",
                             event_start_date="2026-05-10T00:00:00Z",
                             event_end_date="2026-05-15T00:00:00Z"):
    """Drive a delay event DRAFT → NOTICED → TIA_SUBMITTED → TIA_ACCEPTED.

    The event carries a valid fragnet (a member activity of the accepted
    UPDATE) so the TIA submission satisfies the fragnet requirements of
    PRD §3.5 under any faithful reading.
    """
    event = create_delay_event(
        pid,
        causation=causation,
        event_start_date=event_start_date,
        event_end_date=event_end_date,
        fragnet_activity_ids=[fragnet_activity_id],
        fragnet_inserted_into_version_id=update_version_id,
    )
    notice_delay_event(pid, event["id"])
    get_success_data(api_client.submit_tia(pid, event["id"], CONTRACTOR))
    accepted = get_success_data(api_client.accept_tia(pid, event["id"], CLAIMS))
    return accepted


# ---------------------------------------------------------------------------
# EOT requests
# ---------------------------------------------------------------------------

def create_eot_request(pid, delay_event_id, **overrides):
    payload = create_eot_request_payload(delay_event_id, **overrides)
    return get_success_data(api_client.create_eot_request(pid, payload, CONTRACTOR))


# ---------------------------------------------------------------------------
# Acceleration directives
# ---------------------------------------------------------------------------

def create_acceleration_directive(pid, **overrides):
    payload = create_acceleration_directive_payload(**overrides)
    return get_success_data(api_client.create_acceleration_directive(pid, payload, OWNER))


def setup_performing_directive(pid, **overrides):
    """Directive walked ISSUED → ACKNOWLEDGED → PERFORMING. Returns dict(directive, acknowledged)."""
    directive = create_acceleration_directive(pid, **overrides)
    acknowledged = get_success_data(
        api_client.acknowledge_acceleration_directive(pid, directive["id"], CONTRACTOR)
    )
    get_success_data(
        api_client.begin_performance_acceleration_directive(pid, directive["id"], CONTRACTOR)
    )
    return {"directive": directive, "acknowledged": acknowledged}


# ---------------------------------------------------------------------------
# LD assessments
# ---------------------------------------------------------------------------

def create_ld_assessment(pid, **overrides):
    payload = create_ld_assessment_payload(**overrides)
    return get_success_data(api_client.create_ld_assessment(pid, payload, OWNER))
