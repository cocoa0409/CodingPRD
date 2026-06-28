"""Corner coverage of state-machine claims: radon-test initial state and first
placement posture, invalid/locked transitions, void side effect, permit lock
after install, and the retest-schedule pause/resume round trip.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_inspector, create_property, get_property,
    create_radon_test_payload, setup_installed_job,
    setup_cleared_job_with_warranty, issue_permit,
    make_inspector_headers, make_client_contact_headers,
    COMPLIANCE, ApiErrorId,
)


def test_radon_test_starts_placed_at_current_clock(api):
    """PRD §3.2: "On a successful placement the device starts in `PLACED`, its
    `placement_start_utc` is stamped from the logical clock, the property's
    `open_test_count` is incremented, and a property still at `OPEN` advances to
    `TESTING`."

    Design: Corner/state_machines/sm_radon_test_initial_state_placed
    """
    inspector = create_inspector()
    insp = make_inspector_headers(inspector["id"])
    prop = create_property()
    test = validate_success(api.create_radon_test(
        create_radon_test_payload(prop["id"], inspector["id"],
                                  test_kind="SHORT_TERM_48HR", purpose="INITIAL",
                                  placement_window_hours=48),
        insp), 201)
    assert test["status"] == "PLACED"
    assert test["placement_start_utc"].startswith("2026-04-01T00:00:00")
    prop_now = get_property(prop["id"])
    assert prop_now["open_test_count"] == 1
    assert prop_now["posture"] == "TESTING"


def test_record_result_on_placed_test_invalid_state(api):
    """PRD §3.3: "Recording the result moves a test from `RETRIEVED` to
    `RESULT_READY`."
    PRD §2.5: "the target resource must be in a state from which the requested
    transition is legal, otherwise `ERR_INVALID_STATE`."

    Design: Corner/state_machines/sm_radon_test_record_result_from_placed_invalid
    """
    inspector = create_inspector()
    insp = make_inspector_headers(inspector["id"])
    prop = create_property()
    test = get_success_data(api.create_radon_test(
        create_radon_test_payload(prop["id"], inspector["id"],
                                  test_kind="SHORT_TERM_48HR", purpose="INITIAL",
                                  placement_window_hours=48),
        insp))
    res = api.record_result(test["id"], insp)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_void_voided_test_terminal_locked(api):
    """PRD §3.2: "Both `RESULT_READY` and `VOIDED` are terminal; a test cannot
    leave either state, and re-testing means placing a fresh device."
    PRD §2.5: "the target resource must be in a state from which the requested
    transition is legal, otherwise `ERR_INVALID_STATE`."

    Design: Corner/state_machines/sm_radon_test_void_from_voided_terminal_locked
    """
    inspector = create_inspector()
    insp = make_inspector_headers(inspector["id"])
    prop = create_property()
    test = get_success_data(api.create_radon_test(
        create_radon_test_payload(prop["id"], inspector["id"],
                                  test_kind="SHORT_TERM_48HR", purpose="INITIAL",
                                  placement_window_hours=48),
        insp))
    validate_success(api.void_radon_test(test["id"], insp), 200)
    res = api.void_radon_test(test["id"], insp)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    prop_now = get_property(prop["id"])
    assert prop_now["open_test_count"] == 0


def test_void_only_placed_test_decrements_open_count(api):
    """PRD §3.2: "Voiding decrements the property's `open_test_count` and recompute
    the property posture."

    Design: Corner/state_machines/sm_void_bubbles_property_back_toward_open
    """
    inspector = create_inspector()
    insp = make_inspector_headers(inspector["id"])
    prop = create_property()
    test = get_success_data(api.create_radon_test(
        create_radon_test_payload(prop["id"], inspector["id"],
                                  test_kind="SHORT_TERM_48HR", purpose="INITIAL",
                                  placement_window_hours=48),
        insp))
    # After placement open_test_count == 1.
    assert get_property(prop["id"])["open_test_count"] == 1
    validate_success(api.void_radon_test(test["id"], insp), 200)
    assert get_property(prop["id"])["open_test_count"] == 0


def test_revoke_permit_after_install_locked(api):
    """PRD §3.5: "A `ComplianceOfficer` or `PlatformAdmin` may revoke an `ISSUED`
    permit, moving it to `REVOKED`, but only while the parent job is neither
    `INSTALLED` nor `CLEARED`; revoking after the install is complete is rejected
    with `ERR_PERMIT_LOCKED`."

    Design: Corner/state_machines/sm_permit_revoke_after_install_locked
    """
    _, _, _, job, crew, permit = setup_installed_job(
        foundation_type="SLAB", floor_area_sqft=1400,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    assert job["status"] == "INSTALLED"
    res = api.revoke_permit(permit["id"], COMPLIANCE)
    validate_error(res, ApiErrorId.ERR_PERMIT_LOCKED.value)


def test_retest_schedule_pause_resume_round_trip(api):
    """PRD §3.7: "A `ClientContact` or `ComplianceOfficer` may pause an `ARMED`
    schedule, moving it to `PAUSED`, and resume a `PAUSED` schedule back to
    `ARMED`."

    Design: Corner/state_machines/sm_retest_schedule_pause_resume_cycle
    """
    _, prop, _, _, schedule, _ = setup_cleared_job_with_warranty(
        foundation_type="SLAB", floor_area_sqft=1400,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    client = make_client_contact_headers(prop["id"])
    paused = validate_success(api.pause_schedule(schedule["id"], client), 200)
    assert paused["status"] == "PAUSED"
    resumed = validate_success(api.resume_schedule(schedule["id"], client), 200)
    assert resumed["status"] == "ARMED"
