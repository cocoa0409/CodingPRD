"""Validation precedence conflicts and cross-entity state dependencies.

Difficulty queue (A): priority_pair_validation_conflict (consent>age,
invalid_state>insufficient_points), cross_entity_state_dependency (screen-in
needs FIELDING, mark_attended needs COMPLETED).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    create_fielding_study_with_cell, create_panelist, create_consent,
    create_screening_participation, create_facility,
    create_focus_group_payload, create_focus_group_booking_payload,
    get_panelist_version, make_panelist_headers,
)

RM = TEST_USERS["research_manager_headers"]
OPS = TEST_USERS["panel_ops_headers"]
FC = TEST_USERS["field_coordinator_headers"]


def test_consent_required_beats_age_fail_on_screen(api):
    """PRD §3.2: "An accepted consent must already exist: there must be a `Consent`
    for this `(panelist_id, study_id)` pair whose `decision` is `ACCEPTED` at a
    `consent_version` of at least the study's `required_consent_version`; absent
    that, the screen is rejected with `ERR_CONSENT_REQUIRED` (HTTP 422). The
    panelist's `age` must be at least the study's `screener_min_age`; a younger
    panelist is rejected with `ERR_SCREENER_AGE_FAIL` (HTTP 422)."

    The consent precondition is stated before the age precondition in the same
    enumerated gate sequence, so when both fail the consent error surfaces.

    Design: Difficulty/priority_pair_validation_conflict/consent_beats_age_on_screen
    """
    study, cell = create_fielding_study_with_cell(
        target_n=2, study_overrides={"screener_min_age": 21}, segment_key="SEG_P1")
    # Age 18 fails the age gate; no consent recorded fails the consent gate.
    panelist = create_panelist(age=18, segment_key="SEG_P1")
    part = create_screening_participation(study["id"], panelist["id"], cell["id"])

    validate_error(api.screen_participation(part["id"], "IN", FC),
                   ApiErrorId.ERR_CONSENT_REQUIRED.value)
    part_after = validate_success(api.get_participation(part["id"], OPS))
    assert part_after["screening_status"] == "SCREENING", \
        f"no transition on rejected screen, got {part_after['screening_status']}"


def test_invalid_state_beats_insufficient_points_on_approve(api):
    """PRD §2.6: "a state-transition request which targets an axis already past the
    required source state is rejected with `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.7: "A `PanelOps` operator approves a request, moving it `REQUESTED →
    APPROVED`, but only if the panelist's current `points_balance` is at least the
    `points_requested` at approval time; an underfunded request is rejected with
    `ERR_INSUFFICIENT_POINTS` (HTTP 422)."

    The standard state check (§2.6) is evaluated before the fiscal balance check
    (§3.7's "at approval time"); a REJECTED request can never be approved, so the
    state error pre-empts the points check.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_insufficient_points_on_approve
    """
    panelist = create_panelist(segment_key="SEG_P2")  # balance 0
    v0 = get_panelist_version(panelist["id"])
    ph = make_panelist_headers(panelist["id"])
    # points_requested 100 == MIN_PAYOUT, so the create itself is accepted.
    req = validate_success(api.create_payout_request(
        {"panelist_id": panelist["id"], "payout_method": "CASH", "points_requested": 100,
         "expected_panelist_version": v0}, OPS), expected_status=201)
    # Move the request to a terminal state.
    validate_success(api.reject_payout_request(req["id"], OPS))

    # Approving a REJECTED request: state check fires before the (failing) balance check.
    validate_error(api.approve_payout_request(req["id"], OPS),
                   ApiErrorId.ERR_INVALID_STATE.value)
    req_after = validate_success(api.get_payout_request(req["id"], OPS))
    assert req_after["status"] == "REJECTED", \
        f"REJECTED request unchanged, got {req_after['status']}"


def test_screen_in_requires_study_fielding(api):
    """PRD §3.2: "The parent study must be in `FIELDING` — screening while the
    study is paused or not yet launched is rejected with `ERR_STUDY_NOT_FIELDING`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/screen_in_requires_study_fielding
    """
    study, cell = create_fielding_study_with_cell(target_n=2, segment_key="SEG_X1")
    panelist = create_panelist(segment_key="SEG_X1")
    create_consent(panelist["id"], study["id"])
    part = create_screening_participation(study["id"], panelist["id"], cell["id"])
    # Pause the parent study; screen-in must now be blocked by the parent state.
    validate_success(api.pause_study(study["id"], RM))

    validate_error(api.screen_participation(part["id"], "IN", FC),
                   ApiErrorId.ERR_STUDY_NOT_FIELDING.value)
    part_after = validate_success(api.get_participation(part["id"], OPS))
    assert part_after["screening_status"] == "SCREENING", \
        f"transition blocked by parent state, got {part_after['screening_status']}"


def test_mark_attended_requires_focus_group_completed(api):
    """PRD §3.8: "After the session is `COMPLETED`, a `FieldCoordinator` marks each
    booking as either `CONFIRMED → ATTENDED` or `CONFIRMED → NO_SHOW`; both require
    the parent session to be `COMPLETED`."
    PRD §2.6: "a state-transition request which targets an axis already past the
    required source state is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/mark_attended_requires_focus_group_completed
    """
    study = get_success_data(api.create_study(
        {"title": "FGStudy", "irb_protocol_number": "IRB-X2", "estimated_minutes": 10,
         "base_incentive_points": 100, "screener_min_age": 0}, RM))
    facility = create_facility(capacity=10)
    fg = get_success_data(api.create_focus_group(
        create_focus_group_payload(study["id"], facility["id"],
                                   starts_at="2026-04-01T10:00:00Z",
                                   ends_at="2026-04-01T11:00:00Z", seats=5), FC))
    panelist = create_panelist(segment_key="SEG_X2")
    booking = get_success_data(api.create_focus_group_booking(
        create_focus_group_booking_payload(fg["id"], panelist["id"], fg["version"]), FC))

    # Session still SCHEDULED -> mark_attended is invalid.
    validate_error(api.mark_attended_booking(booking["id"], FC),
                   ApiErrorId.ERR_INVALID_STATE.value)
    bk_after = validate_success(api.get_focus_group_booking(booking["id"], FC))
    assert bk_after["status"] == "CONFIRMED", \
        f"booking unchanged while session SCHEDULED, got {bk_after['status']}"
