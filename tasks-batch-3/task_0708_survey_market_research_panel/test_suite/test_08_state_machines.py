"""State-machine corner cases: initial states, invalid/terminal transitions,
side effects, cascades, preconditions.

Corner queue (B): section state_machines.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    create_study, create_quota_cell, create_panelist, create_consent,
    create_fielding_study_with_cell, create_screening_participation,
    setup_panelist_with_consent, setup_started_participation,
    create_facility, create_focus_group_payload, create_focus_group_booking_payload,
    create_data_delivery_payload, submit_payload, get_panelist_version,
    make_panelist_headers,
)

RM = TEST_USERS["research_manager_headers"]
OPS = TEST_USERS["panel_ops_headers"]
FC = TEST_USERS["field_coordinator_headers"]


def test_participation_initial_states_screening_notstarted(api):
    """PRD §3.2: "The new participation begins with screening_status of SCREENING,
    completion_status of NOT_STARTED, and rescreen_count of 0."

    Design: Corner/state_machines/participation_initial_states_screening_notstarted
    """
    study, cell = create_fielding_study_with_cell(target_n=2, segment_key="SEG_IS")
    panelist = create_panelist(segment_key="SEG_IS")
    data = validate_success(api.create_participation(
        {"study_id": study["id"], "panelist_id": panelist["id"],
         "quota_cell_id": cell["id"]}, FC), expected_status=201)
    assert data["screening_status"] == "SCREENING"
    assert data["completion_status"] == "NOT_STARTED"
    assert data["rescreen_count"] == 0


def test_launch_already_fielding_study_returns_invalid_state(api):
    """PRD §3.1: "Launching the study moves it from DRAFT to FIELDING".
    PRD §2.6: a transition that targets a state from which it is not defined is
    rejected with ERR_INVALID_STATE (HTTP 409).

    Design: Corner/state_machines/launch_already_fielding_study_returns_invalid_state
    """
    study, cell = create_fielding_study_with_cell(target_n=2, segment_key="SEG_IL")
    validate_error(api.launch_study(study["id"], RM), ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_already_cancelled_payout_returns_invalid_state(api):
    """PRD §3.7: "the owning Panelist may cancel it (REQUESTED -> CANCELLED) ...
    PAID, REJECTED, and CANCELLED are terminal."
    PRD §2.6: a transition targeting a state from which it is not defined is
    rejected with ERR_INVALID_STATE (HTTP 409).

    Design: Corner/state_machines/cancel_already_cancelled_payout_returns_invalid_state
    """
    panelist = create_panelist(segment_key="SEG_TC")
    v0 = get_panelist_version(panelist["id"])
    ph = make_panelist_headers(panelist["id"])
    req = validate_success(api.create_payout_request(
        {"panelist_id": panelist["id"], "payout_method": "CASH", "points_requested": 100,
         "expected_panelist_version": v0}, ph), expected_status=201)
    validate_success(api.cancel_payout_request(req["id"], ph))

    validate_error(api.cancel_payout_request(req["id"], ph), ApiErrorId.ERR_INVALID_STATE.value)


def test_pause_study_then_create_participation_blocked(api):
    """PRD §3.4: "A study may also be paused (FIELDING -> PAUSED), which freezes
    recruitment so that no new participations are accepted while paused".
    PRD §3.2 names ERR_STUDY_NOT_FIELDING as the rejection when the parent study
    is not FIELDING; here recruitment is frozen by the pause.

    Design: Corner/state_machines/pause_study_then_create_participation_blocked
    """
    study, cell = create_fielding_study_with_cell(target_n=2, segment_key="SEG_PF")
    validate_success(api.pause_study(study["id"], RM))
    panelist = create_panelist(segment_key="SEG_PF")

    validate_error(api.create_participation(
        {"study_id": study["id"], "panelist_id": panelist["id"],
         "quota_cell_id": cell["id"]}, FC), ApiErrorId.ERR_STUDY_NOT_FIELDING.value)


def test_qualify_flips_quota_cell_fill_status_filled(api):
    """PRD §3.3: "the reserved seat becomes a committed seat (the cell's
    committed_n recomputes and its fill_status may flip from OPEN to FILLED)".
    PRD §2.7: "A cell's fill_status is FILLED when committed_n is greater than or
    equal to target_n, and OPEN otherwise."

    Design: Corner/state_machines/qualify_flips_quota_cell_fill_status_filled
    """
    study, cell, panelist, participation = setup_started_participation(
        target_n=1, study_overrides={"base_incentive_points": 100, "estimated_minutes": 10},
        segment_key="SEG_FILL")
    ph = make_panelist_headers(panelist["id"])
    submitted = validate_success(api.submit_participation(
        participation["id"], submit_payload(completion_seconds=600, straightline_run=0), ph))
    assert submitted["screening_status"] == "QUALIFIED"

    cell_after = validate_success(api.get_quota_cell(cell["id"], OPS))
    assert cell_after["committed_n"] == 1, f"committed_n should be 1, got {cell_after['committed_n']}"
    assert cell_after["fill_status"] == "FILLED", \
        f"committed_n 1 >= target 1 must flip to FILLED, got {cell_after['fill_status']}"


def test_cancel_focus_group_cascades_bookings_cancelled(api):
    """PRD §3.8: "Cancelling the whole focus group (SCHEDULED -> CANCELLED)
    cascades down: every CONFIRMED booking on it is moved to CANCELLED."
    PRD §3.8: "booked_n is the live count of its CONFIRMED bookings."

    Design: Corner/state_machines/cancel_focus_group_cascades_bookings_cancelled
    """
    study = create_study(base_incentive_points=50, estimated_minutes=10, screener_min_age=0)
    facility = create_facility(capacity=10)
    fg = get_success_data(api.create_focus_group(
        create_focus_group_payload(study["id"], facility["id"],
                                   starts_at="2026-05-01T10:00:00Z",
                                   ends_at="2026-05-01T11:00:00Z", seats=5), FC))
    panelist = create_panelist(segment_key="SEG_FGC")
    booking = get_success_data(api.create_focus_group_booking(
        create_focus_group_booking_payload(fg["id"], panelist["id"], fg["version"]), FC))

    cancelled = validate_success(api.cancel_focus_group(fg["id"], FC))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["booked_n"] == 0, f"booked_n should recompute to 0, got {cancelled['booked_n']}"

    bk_after = validate_success(api.get_focus_group_booking(booking["id"], FC))
    assert bk_after["status"] == "CANCELLED", \
        f"booking must cascade to CANCELLED, got {bk_after['status']}"


def test_screen_in_twice_returns_invalid_state(api):
    """PRD §2.6: "a state-transition request which targets an axis already past the
    required source state is rejected with ERR_INVALID_STATE (HTTP 409)."
    PRD §3.2: "An outcome of IN advances the screening axis SCREENING ->
    SCREENED_IN".

    Design: Corner/state_machines/screen_in_twice_returns_invalid_state
    """
    study, cell = create_fielding_study_with_cell(target_n=2, segment_key="SEG_IDP")
    panelist = setup_panelist_with_consent(study["id"], segment_key="SEG_IDP")
    part = create_screening_participation(study["id"], panelist["id"], cell["id"])
    validate_success(api.screen_participation(part["id"], "IN", FC))

    validate_error(api.screen_participation(part["id"], "IN", FC),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_deliver_without_ready_delivery_returns_delivery_not_ready(api):
    """PRD §3.9: "A ResearchManager delivers a CLOSED study, moving it CLOSED ->
    DELIVERED, but only when a DataDelivery for that study exists in READY status;
    without one the deliver is rejected with ERR_DELIVERY_NOT_READY (HTTP 409)."

    Design: Corner/state_machines/deliver_without_ready_delivery_returns_delivery_not_ready
    """
    study, cell = create_fielding_study_with_cell(target_n=2, segment_key="SEG_DL")
    validate_success(api.close_study(study["id"], RM))
    validate_error(api.deliver_study(study["id"], RM), ApiErrorId.ERR_DELIVERY_NOT_READY.value)


def test_build_delivery_while_study_fielding_returns_not_closed(api):
    """PRD §3.9: "Building the delivery moves it BUILDING -> READY, which requires
    the parent study to be CLOSED — building against a study that is not closed is
    rejected with ERR_STUDY_NOT_CLOSED (HTTP 409)."

    Design: Corner/state_machines/build_delivery_while_study_fielding_returns_not_closed
    """
    study, cell = create_fielding_study_with_cell(target_n=2, segment_key="SEG_BD")
    delivery = get_success_data(api.create_data_delivery(
        create_data_delivery_payload(study["id"], report_format="CSV"), RM))
    validate_error(api.build_data_delivery(delivery["id"], RM),
                   ApiErrorId.ERR_STUDY_NOT_CLOSED.value)


def test_abandon_in_progress_voids_screening_axis(api):
    """PRD §3.3: "A panelist may instead abandon an in-progress survey, moving
    completion IN_PROGRESS -> ABANDONED. Abandonment has a cross-axis consequence:
    if at that moment the screening axis is still SCREENING or SCREENED_IN, it is
    forced to VOIDED, which releases the reserved seat (the cell's reserved_n
    recomputes) and flips any held provisional accrual to VOID."

    Design: Corner/state_machines/abandon_in_progress_voids_screening_axis
    """
    study, cell, panelist, participation = setup_started_participation(
        target_n=2, study_overrides={"base_incentive_points": 100, "estimated_minutes": 10},
        segment_key="SEG_AB")
    ph = make_panelist_headers(panelist["id"])

    abandoned = validate_success(api.abandon_participation(participation["id"], ph))
    assert abandoned["completion_status"] == "ABANDONED"
    assert abandoned["screening_status"] == "VOIDED", \
        f"cross-axis cascade must VOID screening, got {abandoned['screening_status']}"

    cell_after = validate_success(api.get_quota_cell(cell["id"], OPS))
    assert cell_after["reserved_n"] == 0, f"reserved_n should be 0, got {cell_after['reserved_n']}"
    assert cell_after["available_n"] == 2, f"available_n should be 2, got {cell_after['available_n']}"
