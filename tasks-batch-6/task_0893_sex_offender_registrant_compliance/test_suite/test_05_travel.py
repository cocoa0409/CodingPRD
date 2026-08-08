"""Travel notices: decision fork, hold-count conservation, window overlap,
destination gating, and validation precedence."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    setup_active_registrant, setup_submitted_travel, setup_approved_travel,
    open_flag, submit_travel, get_jurisdiction, get_registrant,
    create_travel_notice_payload, TEST_USERS,
)

OFFICER = TEST_USERS["registration_officer_headers"]
NON_EXISTENT = "00000000-0000-0000-0000-000000000000"


def test_approve_travel_notice_moves_to_approved(api):
    """PRD 3.6: "on approval the notice moves `SUBMITTED → APPROVED` and the
    destination jurisdiction's `active_travel_hold_count` is incremented by one."

    Design: Difficulty/non_linear_state_machine/travel_notice_submitted_fork_approve
    """
    home, dest, reg, tn = setup_submitted_travel()
    resp = api.decide_travel_notice(tn["id"], {"decision": "APPROVE"}, OFFICER)
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "APPROVED"


def test_approve_travel_increments_destination_hold_count(api):
    """PRD 3.6: "on approval the notice moves `SUBMITTED → APPROVED` and the
    destination jurisdiction's `active_travel_hold_count` is incremented by one."

    Design: Difficulty/non_linear_state_machine/travel_notice_submitted_fork_approve
    """
    home, dest, reg, tn = setup_submitted_travel()
    api.decide_travel_notice(tn["id"], {"decision": "APPROVE"}, OFFICER)
    dest_after = get_jurisdiction(dest["id"])
    assert dest_after["active_travel_hold_count"] == 1


def test_cancel_approved_travel_moves_to_cancelled(api):
    """PRD 3.6: "a `RegistrationOfficer` or the owning `Registrant` may cancel it:
    the notice moves to `CANCELLED` and, because the approval had raised the
    destination's hold, the destination jurisdiction's `active_travel_hold_count`
    is decremented by one to restore the pre-approval value."

    Design: Difficulty/compensating_invariant/travel_approve_cancel_conserves_hold_count
    """
    home, dest, reg, tn = setup_approved_travel()
    resp = api.cancel_travel_notice(tn["id"], OFFICER)
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "CANCELLED"


def test_cancel_approved_travel_restores_hold_count(api):
    """PRD 3.6: "the destination jurisdiction's `active_travel_hold_count` is
    decremented by one to restore the pre-approval value."

    Design: Difficulty/compensating_invariant/travel_approve_cancel_conserves_hold_count
    """
    home, dest, reg, tn = setup_approved_travel()
    api.cancel_travel_notice(tn["id"], OFFICER)
    dest_after = get_jurisdiction(dest["id"])
    assert dest_after["active_travel_hold_count"] == 0


def test_approve_travel_to_inactive_destination_rejected(api):
    """PRD 3.6: "An approval requires the owning registrant to still be `ACTIVE`
    (otherwise `ERR_REGISTRANT_NOT_ACTIVE`) and the destination jurisdiction to be
    `ACTIVE` (otherwise `ERR_JURISDICTION_INACTIVE`)".

    Design: Difficulty/cross_entity_state_dependency/travel_approve_requires_destination_active
    """
    home, dest, reg, tn = setup_submitted_travel(dest_status="INACTIVE")
    resp = api.decide_travel_notice(tn["id"], {"decision": "APPROVE"}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_JURISDICTION_INACTIVE)


def test_approve_to_inactive_destination_leaves_notice_submitted(api):
    """PRD 3.6: "An approval requires the owning registrant to still be `ACTIVE`
    (otherwise `ERR_REGISTRANT_NOT_ACTIVE`) and the destination jurisdiction to be
    `ACTIVE` (otherwise `ERR_JURISDICTION_INACTIVE`); on approval the notice moves
    `SUBMITTED → APPROVED`".

    Design: Difficulty/cross_entity_state_dependency/travel_approve_requires_destination_active
    """
    home, dest, reg, tn = setup_submitted_travel(dest_status="INACTIVE")
    api.decide_travel_notice(tn["id"], {"decision": "APPROVE"}, OFFICER)
    got = get_success_data(api.list_travel_notices(reg["id"], OFFICER))
    current = [t for t in got if t["id"] == tn["id"]][0]
    assert current["status"] == "SUBMITTED"


def test_overlapping_travel_window_rejected(api):
    """PRD 3.6: "The overlap test treats each window as half-open — spanning from
    its departure date up to but not including its return date — and a new window
    that overlaps any existing non-terminal window is rejected with
    `ERR_TRAVEL_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/travel_window_half_open_overlap_rejected
    """
    jur, reg = setup_active_registrant(full_name="Win W")
    submit_travel(reg["id"], jur["id"], departure_date="2026-06-01T00:00:00Z",
                  return_date="2026-06-10T00:00:00Z")
    # [2026-06-05, 2026-06-15) overlaps the interior of [2026-06-01, 2026-06-10).
    resp = api.create_travel_notice(
        reg["id"],
        create_travel_notice_payload(jur["id"], departure_date="2026-06-05T00:00:00Z",
                                     return_date="2026-06-15T00:00:00Z"),
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_TRAVEL_WINDOW_CONFLICT)


def test_adjacent_travel_window_touching_prior_return_allowed(api):
    """PRD 3.6: "The overlap test treats each window as half-open — spanning from
    its departure date up to but not including its return date — and a new window
    that overlaps any existing non-terminal window is rejected with
    `ERR_TRAVEL_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/travel_window_half_open_overlap_rejected
    """
    jur, reg = setup_active_registrant(full_name="Win W")
    submit_travel(reg["id"], jur["id"], departure_date="2026-06-01T00:00:00Z",
                  return_date="2026-06-10T00:00:00Z")
    # [2026-06-10, 2026-06-20) starts exactly at the prior return -> half-open, no overlap.
    resp = api.create_travel_notice(
        reg["id"],
        create_travel_notice_payload(jur["id"], departure_date="2026-06-10T00:00:00Z",
                                     return_date="2026-06-20T00:00:00Z"),
        OFFICER,
    )
    validate_success(resp, expected_status=201)


def test_state_check_precedes_referential_check_on_travel(api):
    """PRD 2.7: "4. State — the target resource is in a state that permits the
    requested transition ... 5. Referential body checks — foreign keys supplied in
    the body resolve; specifically the `destination_jurisdiction_id` on a travel
    notice must resolve, otherwise `ERR_JURISDICTION_NOT_FOUND`."
    PRD 3.6: "The submitting registrant must be `ACTIVE`; a travel action on a
    registrant that is not `ACTIVE` is rejected with `ERR_REGISTRANT_NOT_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/travel_state_beats_referential
    """
    jur, reg = setup_active_registrant(full_name="Delq D")
    open_flag(reg["id"], flag_type="UNREPORTED_MOVE")  # -> DELINQUENT
    # DELINQUENT (state, prio 4) + non-existent destination (referential, prio 5).
    resp = api.create_travel_notice(
        reg["id"],
        create_travel_notice_payload(NON_EXISTENT, departure_date="2026-06-01T00:00:00Z",
                                     return_date="2026-06-10T00:00:00Z"),
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_REGISTRANT_NOT_ACTIVE)


def test_delinquent_registrant_cannot_submit_travel(api):
    """PRD 3.6: "The submitting registrant must be `ACTIVE`; a travel action on a
    registrant that is not `ACTIVE` is rejected with `ERR_REGISTRANT_NOT_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/travel_state_beats_referential
    """
    jur, reg = setup_active_registrant(full_name="Delq D")
    open_flag(reg["id"], flag_type="UNREPORTED_MOVE")  # -> DELINQUENT
    # Valid destination this time: isolates the state check firing regardless.
    resp = api.create_travel_notice(
        reg["id"],
        create_travel_notice_payload(jur["id"], departure_date="2026-06-01T00:00:00Z",
                                     return_date="2026-06-10T00:00:00Z"),
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_REGISTRANT_NOT_ACTIVE)


def test_temporal_check_precedes_constraint_check_on_travel(api):
    """PRD 2.7: "6. Temporal checks — date ordering and not-in-past rules on travel
    and address windows, otherwise `ERR_INVALID_TRAVEL_DATES` ... 8. Constraint —
    window-overlap and duplicate-record conflicts, otherwise the matching 409
    conflict error."
    PRD 3.6: "it must be strictly later than the `departure_date`, while the
    `departure_date` must not be in the past (the clock must be at or before it); a
    violation of either date rule is rejected with `ERR_INVALID_TRAVEL_DATES`."

    Design: Difficulty/priority_pair_validation_conflict/travel_temporal_beats_constraint
    """
    jur, reg = setup_active_registrant(full_name="Over O")
    submit_travel(reg["id"], jur["id"], departure_date="2026-06-01T00:00:00Z",
                  return_date="2026-06-10T00:00:00Z")
    # Past departure (2026-04-01 < clock 2026-05-01, temporal prio 6) AND the window
    # [2026-04-01, 2026-06-05) overlaps the existing one (constraint prio 8).
    resp = api.create_travel_notice(
        reg["id"],
        create_travel_notice_payload(jur["id"], departure_date="2026-04-01T00:00:00Z",
                                     return_date="2026-06-05T00:00:00Z"),
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TRAVEL_DATES)


def test_past_departure_alone_rejected_with_invalid_dates(api):
    """PRD 3.6: "the `departure_date` must not be in the past (the clock must be at
    or before it); a violation of either date rule is rejected with
    `ERR_INVALID_TRAVEL_DATES`."

    Design: Difficulty/priority_pair_validation_conflict/travel_temporal_beats_constraint
    """
    jur, reg = setup_active_registrant(full_name="Over O")
    # No pre-existing window: isolates the temporal (past-departure) rule.
    resp = api.create_travel_notice(
        reg["id"],
        create_travel_notice_payload(jur["id"], departure_date="2026-04-01T00:00:00Z",
                                     return_date="2026-06-05T00:00:00Z"),
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TRAVEL_DATES)


def test_deny_travel_leaves_hold_count_zero(api):
    """PRD 3.6: "A denial moves the notice `SUBMITTED → DENIED`, recording the
    `decision_note` and leaving hold counts unchanged; denial is terminal."

    Design: Corner/state_machines/deny_travel_leaves_hold_count_zero
    """
    home, dest, reg, tn = setup_submitted_travel()
    resp = api.decide_travel_notice(
        tn["id"], {"decision": "DENY", "decision_note": "not approved"}, OFFICER)
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "DENIED"
    dest_after = get_jurisdiction(dest["id"])
    assert dest_after["active_travel_hold_count"] == 0


def test_temporary_travel_without_return_rejected(api):
    """PRD 3.6: "For `TEMPORARY` travel the `return_date` is required — its absence
    is rejected with `ERR_MISSING_TRAVEL_RETURN`".

    Design: Corner/validations/temporary_travel_missing_return_rejected
    """
    jur, reg = setup_active_registrant(full_name="Miss M")
    resp = api.create_travel_notice(
        reg["id"],
        {"destination_jurisdiction_id": jur["id"], "travel_type": "TEMPORARY",
         "departure_date": "2026-06-01T00:00:00Z"},
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_TRAVEL_RETURN)


def test_abscond_flag_cancels_approved_travel_and_decrements_hold(api):
    """PRD 3.5: "Opening a flag of type `ABSCONDED` moves the registrant into
    `ABSCONDER` (whether it was `ACTIVE` or `DELINQUENT`): a `CRITICAL` `ABSCONDED`
    flag is opened, the score is recomputed, and every travel notice of that
    registrant still in `SUBMITTED`, `APPROVED`, or `ACTIVE` is cancelled, with the
    destination jurisdiction's `active_travel_hold_count` decremented by one for
    each notice that had been `APPROVED` or `ACTIVE` at the time."

    Design: Corner/state_machines/abscond_flag_cancels_travel_and_decrements_hold
    """
    home, dest, reg, tn = setup_approved_travel()
    open_flag(reg["id"], flag_type="ABSCONDED")
    reg_after = get_registrant(reg["id"])
    assert reg_after["status"] == "ABSCONDER"
    got = get_success_data(api.list_travel_notices(reg["id"], OFFICER))
    current = [t for t in got if t["id"] == tn["id"]][0]
    assert current["status"] == "CANCELLED"
    dest_after = get_jurisdiction(dest["id"])
    assert dest_after["active_travel_hold_count"] == 0
