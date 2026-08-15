"""Assignment lifecycle: accept/decline/confirm/cancel, capacity, committed
hours, check-in window and gate documents, no-show timing, request status."""
from test_helpers import (
    validate_success, validate_error,
    create_active_incident, vet_volunteer, create_published_request,
    create_open_shift, propose_assignment, propose_accept_assignment,
    propose_accept_confirm_assignment, issue_ppe, refresh_briefing, set_clock,
    create_clearance_payload, make_volunteer_headers, TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]
INTAKE = TEST_USERS["intake_headers"]
SITE = TEST_USERS["supervisor_headers"]
RISK = TEST_USERS["risk_headers"]


def _ready_volunteer_with_open_shift(api, name, ppe=None, capacity=2, headcount=1):
    incident = create_active_incident(
        name=name, ppe_stock=ppe or {"GLOVES": 3, "MASK": 3, "HARD_HAT": 3,
                                     "VEST": 3, "GOGGLES": 3})
    volunteer = vet_volunteer(incident["id"])["volunteer"]
    request = create_published_request(incident["id"], headcount_needed=headcount)
    shift = create_open_shift(incident["id"], capacity=capacity)
    return incident, volunteer, request, shift


def test_accept_declined_assignment_returns_invalid_state(api):
    """PRD section 3.3: "The volunteer then answers: accepting moves `PROPOSED`
    to `ACCEPTED`, and declining moves it to terminal `DECLINED`, which can
    empty a `MATCHING` request back to `OPEN` when no fills and no `PROPOSED`
    or `ACCEPTED` assignments remain; both actions are ownership-checked per
    section 2.8."

    Design: Corner/state_machines/accept_declined_assignment_returns_invalid_state
    """
    _, volunteer, request, shift = _ready_volunteer_with_open_shift(api, "Flood A2")
    assignment = propose_assignment(volunteer, request, shift)
    declined = validate_success(api.decline_assignment(
        assignment["id"], make_volunteer_headers(volunteer["id"])))
    assert declined["status"] == "DECLINED"
    res = api.accept_assignment(assignment["id"], make_volunteer_headers(volunteer["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_second_confirm_of_confirmed_assignment_returns_invalid_state(api):
    """PRD section 3.3: "It requires the assignment `ACCEPTED`, the posture not
    `FROZEN`, the shift in `OPEN_FOR_ROSTER` — a `LOCKED` shift fails with
    `ERR_SHIFT_CAPACITY_REACHED`, a `SCHEDULED` or `CANCELLED` shift with
    `ERR_INVALID_STATE` — with `rostered_count` still below `capacity`"
    PRD section 3.3: "The confirm and cancel pair is compensating: confirming
    and then cancelling the same assignment returns `committed_hours` to
    exactly its pre-confirm value."

    Design: Corner/state_machines/second_confirm_of_confirmed_assignment_returns_invalid_state
    """
    _, volunteer, request, shift = _ready_volunteer_with_open_shift(
        api, "Flood D2", ppe={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1, "VEST": 1,
                              "GOGGLES": 1})
    assignment = propose_accept_confirm_assignment(volunteer, request, shift)
    assert assignment["status"] == "CONFIRMED"
    res = api.confirm_assignment(assignment["id"], INTAKE)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_volunteer(volunteer["id"], MGR))
    assert after["committed_hours"] == 8.0, (
        f"committed hours must be debited exactly once, got {after['committed_hours']}")


def test_cancel_completed_assignment_returns_invalid_state(api):
    """PRD section 3.4: "Plain cancellation — by an `IntakeCoordinator` or a
    `VRCManager`, or arriving by cascade — applies from `PROPOSED`, `ACCEPTED`,
    or `CONFIRMED` (otherwise `ERR_INVALID_STATE`)"

    Design: Corner/state_machines/cancel_completed_assignment_returns_invalid_state
    """
    _, volunteer, request, shift = _ready_volunteer_with_open_shift(api, "Flood B2")
    assignment = propose_accept_confirm_assignment(volunteer, request, shift)
    issue_ppe(volunteer["id"])
    set_clock("2026-08-09T12:00:00Z")
    refresh_briefing(volunteer["id"])
    set_clock("2026-08-10T08:00:00Z")
    validate_success(api.check_in_assignment(assignment["id"], SITE))
    completed = validate_success(api.complete_assignment(assignment["id"], SITE))
    assert completed["status"] == "COMPLETED"
    res = api.cancel_assignment(assignment["id"], INTAKE)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_volunteer(volunteer["id"], MGR))
    assert after["committed_hours"] == 0.0, (
        "completion released the hours exactly once; the rejected cancel must not re-release")


def test_request_promotes_to_matching_on_first_proposal(api):
    """PRD section 2.6: "A support request promotes from `OPEN` or `MATCHING`
    to `FILLED` the moment `filled_count` reaches `headcount_needed`, slides
    from `OPEN` to `MATCHING` when proposal activity leaves it at least one
    non-terminal assignment, regresses from `MATCHING` to `OPEN` when its
    `filled_count` is zero and no `PROPOSED` or `ACCEPTED` assignments remain,
    and falls back from `FILLED` to `MATCHING` when fills are lost below the
    needed headcount."

    Design: Corner/state_machines/request_fills_then_drains_back_to_open_on_cancel
    """
    _, volunteer, request, shift = _ready_volunteer_with_open_shift(api, "Flood F2")
    propose_assignment(volunteer, request, shift)
    after_propose = validate_success(api.get_support_request(request["id"], MGR))
    assert after_propose["status"] == "MATCHING"


def test_request_fills_on_confirm_then_drains_back_to_open_on_cancel(api):
    """PRD section 2.6: "A support request promotes from `OPEN` or `MATCHING`
    to `FILLED` the moment `filled_count` reaches `headcount_needed`, slides
    from `OPEN` to `MATCHING` when proposal activity leaves it at least one
    non-terminal assignment, regresses from `MATCHING` to `OPEN` when its
    `filled_count` is zero and no `PROPOSED` or `ACCEPTED` assignments remain,
    and falls back from `FILLED` to `MATCHING` when fills are lost below the
    needed headcount."

    Design: Corner/state_machines/request_fills_then_drains_back_to_open_on_cancel
    """
    _, volunteer, request, shift = _ready_volunteer_with_open_shift(api, "Flood F2")
    assignment = propose_accept_confirm_assignment(volunteer, request, shift)
    after_confirm = validate_success(api.get_support_request(request["id"], MGR))
    assert after_confirm["status"] == "FILLED"
    assert after_confirm["filled_count"] == 1
    validate_success(api.cancel_assignment(assignment["id"], INTAKE))
    after_cancel = validate_success(api.get_support_request(request["id"], MGR))
    assert after_cancel["status"] == "OPEN"


def test_confirm_effects_immediately_visible_on_all_touched_entities(api):
    """PRD section 3.3: "Confirming adds the shift's `duration_hours` to the
    volunteer's `committed_hours`, increments the shift's `rostered_count`
    (locking it the moment the roster reaches `capacity`), increments the
    request's `filled_count` (promoting the request to `FILLED` the moment it
    reaches `headcount_needed`, or from `OPEN` to `MATCHING` below it), and
    re-derives posture."

    Design: Corner/consistency_model/confirm_effects_immediately_visible_on_all_touched_entities
    """
    _, volunteer, request, shift = _ready_volunteer_with_open_shift(api, "Flood A4")
    assignment = propose_accept_assignment(volunteer, request, shift)
    confirmed = validate_success(api.confirm_assignment(assignment["id"], INTAKE))
    assert confirmed["status"] == "CONFIRMED"
    vol_after = validate_success(api.get_volunteer(volunteer["id"], MGR))
    assert vol_after["committed_hours"] == 8.0
    shift_after = validate_success(api.get_shift(shift["id"], MGR))
    assert shift_after["rostered_count"] == 1
    request_after = validate_success(api.get_support_request(request["id"], MGR))
    assert request_after["filled_count"] == 1
    assert request_after["status"] == "FILLED"


def test_second_confirm_at_full_shift_returns_shift_capacity_reached(api):
    """PRD section 2.6: "A shift whose `rostered_count` reaches `capacity`
    locks itself, moving from `OPEN_FOR_ROSTER` to `LOCKED`, and reopens the
    moment the roster falls back below capacity."
    PRD section 3.3: "a `LOCKED` shift fails with `ERR_SHIFT_CAPACITY_REACHED`"

    Design: Corner/errors/second_confirm_at_full_shift_returns_shift_capacity_reached
    """
    incident = create_active_incident(
        name="Fire Q3", ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                   "VEST": 1, "GOGGLES": 1})
    v1 = vet_volunteer(incident["id"], full_name="Hyo Han")["volunteer"]
    v2 = vet_volunteer(incident["id"], full_name="Ina Ihn")["volunteer"]
    request = create_published_request(incident["id"], headcount_needed=2)
    shift = create_open_shift(incident["id"], capacity=1)
    a1 = propose_accept_assignment(v1, request, shift)
    a2 = propose_accept_assignment(v2, request, shift)
    confirmed = validate_success(api.confirm_assignment(a1["id"], INTAKE))
    assert confirmed["status"] == "CONFIRMED"
    shift_after = validate_success(api.get_shift(shift["id"], MGR))
    assert shift_after["rostered_count"] == 1
    assert shift_after["status"] == "LOCKED"
    res = api.confirm_assignment(a2["id"], INTAKE)
    validate_error(res, "ERR_SHIFT_CAPACITY_REACHED")


def _setup_forty_hour_boundary(api):
    """Volunteer with 32.00 committed hours (four 8h days) plus ACCEPTED
    assignments on an 8h day and a 0.25h day. Returns (volunteer, a5, a6)."""
    incident = create_active_incident(name="Flood Lambda")
    volunteer = vet_volunteer(incident["id"], full_name="Kurt Kell")["volunteer"]
    request = create_published_request(
        incident["id"], site_name="Levee North", headcount_needed=6,
        window_start="2026-08-10T06:00:00Z", window_end="2026-08-15T20:00:00Z")
    shifts = []
    for day in ("2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14"):
        shifts.append(create_open_shift(incident["id"], site_name="Levee North",
                                        start_at=f"{day}T08:00:00Z",
                                        end_at=f"{day}T16:00:00Z", capacity=5))
    shifts.append(create_open_shift(incident["id"], site_name="Levee North",
                                    start_at="2026-08-15T08:00:00Z",
                                    end_at="2026-08-15T08:15:00Z", capacity=5))
    assignments = []
    for shift in shifts[:4]:
        assignment = propose_assignment(volunteer, request, shift)
        validate_success(api.accept_assignment(
            assignment["id"], make_volunteer_headers(volunteer["id"])))
        validate_success(api.confirm_assignment(assignment["id"], INTAKE))
        assignments.append(assignment)
    a5 = propose_accept_assignment(volunteer, request, shifts[4])
    a6 = propose_accept_assignment(volunteer, request, shifts[5])
    return volunteer, a5, a6


def test_committed_hours_exactly_40_allowed(api):
    """PRD section 3.3: "the volunteer's `committed_hours` plus the shift's
    `duration_hours` must not exceed 40.00 hours, with a projection of exactly
    40.00 allowed and anything strictly above rejected with
    `ERR_WEEKLY_HOUR_CAP`."

    Design: Difficulty/boundary_precision_check/committed_hours_exactly_40_allowed_40_25_rejected
    """
    volunteer, a5, _ = _setup_forty_hour_boundary(api)
    confirmed = validate_success(api.confirm_assignment(a5["id"], INTAKE))
    assert confirmed["status"] == "CONFIRMED"
    after = validate_success(api.get_volunteer(volunteer["id"], MGR))
    assert after["committed_hours"] == 40.0


def test_committed_hours_40_25_rejected(api):
    """PRD section 3.3: "the volunteer's `committed_hours` plus the shift's
    `duration_hours` must not exceed 40.00 hours, with a projection of exactly
    40.00 allowed and anything strictly above rejected with
    `ERR_WEEKLY_HOUR_CAP`."

    Design: Difficulty/boundary_precision_check/committed_hours_exactly_40_allowed_40_25_rejected
    """
    volunteer, a5, a6 = _setup_forty_hour_boundary(api)
    validate_success(api.confirm_assignment(a5["id"], INTAKE))
    res = api.confirm_assignment(a6["id"], INTAKE)
    validate_error(res, "ERR_WEEKLY_HOUR_CAP")


def test_accepted_assignment_contributes_nothing_and_confirm_debits(api):
    """PRD section 2.6: "a volunteer's `committed_hours` (the summed
    `duration_hours` of the shifts behind their `CONFIRMED` or `CHECKED_IN`
    assignments, held at two decimal places)"

    Design: Difficulty/compensating_invariant/confirm_then_cancel_restores_committed_hours_ledger
    """
    _, volunteer, request, shift = _ready_volunteer_with_open_shift(
        api, "Fire Sigma", ppe={"GLOVES": 5, "MASK": 5, "HARD_HAT": 5,
                                "VEST": 5, "GOGGLES": 5})
    assignment = propose_accept_assignment(volunteer, request, shift)
    after_accept = validate_success(api.get_volunteer(volunteer["id"], MGR))
    assert after_accept["committed_hours"] == 0.0
    validate_success(api.confirm_assignment(assignment["id"], INTAKE))
    after_confirm = validate_success(api.get_volunteer(volunteer["id"], MGR))
    assert after_confirm["committed_hours"] == 8.0


def test_cancel_compensates_committed_hours_exactly(api):
    """PRD section 3.3: "The confirm and cancel pair is compensating:
    confirming and then cancelling the same assignment returns
    `committed_hours` to exactly its pre-confirm value."

    Design: Difficulty/compensating_invariant/confirm_then_cancel_restores_committed_hours_ledger
    """
    _, volunteer, request, shift = _ready_volunteer_with_open_shift(
        api, "Fire Sigma", ppe={"GLOVES": 5, "MASK": 5, "HARD_HAT": 5,
                                "VEST": 5, "GOGGLES": 5})
    assignment = propose_accept_confirm_assignment(volunteer, request, shift)
    validate_success(api.cancel_assignment(assignment["id"], INTAKE))
    after_cancel = validate_success(api.get_volunteer(volunteer["id"], MGR))
    assert after_cancel["committed_hours"] == 0.0


def test_checkin_before_window_returns_outside_checkin_window(api):
    """PRD section 3.4: "Check-in requires the assignment `CONFIRMED`
    (otherwise `ERR_INVALID_STATE`), the posture not `FROZEN`, the shift in
    `OPEN_FOR_ROSTER` or `LOCKED`, and the logical now inside the check-in
    window, which opens 30 minutes before the shift's `start_at` and closes at
    its `end_at`; outside that window the call fails with
    `ERR_OUTSIDE_CHECKIN_WINDOW`."

    Design: Corner/endpoints/checkin_before_window_returns_outside_checkin_window
    """
    _, volunteer, request, shift = _ready_volunteer_with_open_shift(
        api, "Flood H3", ppe={"GLOVES": 2, "MASK": 2, "HARD_HAT": 2,
                              "VEST": 2, "GOGGLES": 2})
    assignment = propose_accept_confirm_assignment(volunteer, request, shift)
    issue_ppe(volunteer["id"])
    set_clock("2026-08-09T12:00:00Z")
    refresh_briefing(volunteer["id"])
    set_clock("2026-08-10T07:00:00Z")  # 60 minutes before the 08:00 start
    res = api.check_in_assignment(assignment["id"], SITE)
    validate_error(res, "ERR_OUTSIDE_CHECKIN_WINDOW")


def test_checkin_at_window_opening_boundary_is_admitted(api):
    """PRD section 3.4: "the logical now inside the check-in window, which
    opens 30 minutes before the shift's `start_at` and closes at its `end_at`"

    Design: Corner/endpoints/checkin_before_window_returns_outside_checkin_window
    """
    _, volunteer, request, shift = _ready_volunteer_with_open_shift(
        api, "Flood H3", ppe={"GLOVES": 2, "MASK": 2, "HARD_HAT": 2,
                              "VEST": 2, "GOGGLES": 2})
    assignment = propose_accept_confirm_assignment(volunteer, request, shift)
    issue_ppe(volunteer["id"])
    set_clock("2026-08-09T12:00:00Z")
    refresh_briefing(volunteer["id"])
    set_clock("2026-08-10T07:30:00Z")  # exactly 30 minutes before the 08:00 start
    checked_in = validate_success(api.check_in_assignment(assignment["id"], SITE))
    assert checked_in["status"] == "CHECKED_IN"


def test_no_show_before_shift_end_returns_too_early(api):
    """PRD section 3.4: "A no-show may be recorded only at or after the shift's
    `end_at` — earlier attempts fail with `ERR_TOO_EARLY_FOR_NO_SHOW`"

    Design: Corner/state_machines/no_show_before_shift_end_returns_too_early
    """
    _, volunteer, request, shift = _ready_volunteer_with_open_shift(
        api, "Fire I2", ppe={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                             "VEST": 1, "GOGGLES": 1})
    assignment = propose_accept_confirm_assignment(volunteer, request, shift)
    set_clock("2026-08-10T12:00:00Z")  # shift ends 16:00
    res = api.no_show_assignment(assignment["id"], SITE)
    validate_error(res, "ERR_TOO_EARLY_FOR_NO_SHOW")
    after = validate_success(api.get_assignment(assignment["id"], MGR))
    assert after["status"] == "CONFIRMED"


def test_checkin_rejected_when_briefing_clearance_expired(api):
    """PRD section 3.4: "Three gate documents must also hold: a current
    briefing (`ERR_BRIEFING_NOT_CURRENT`), an active waiver
    (`ERR_WAIVER_NOT_SIGNED`), and at least one PPE issuance still `ISSUED` for
    the volunteer (`ERR_PPE_NOT_ISSUED`)."

    Design: Difficulty/cross_entity_state_dependency/checkin_rejected_when_briefing_clearance_expired
    """
    _, volunteer, request, shift = _ready_volunteer_with_open_shift(api, "Flood Nu")
    assignment = propose_accept_confirm_assignment(volunteer, request, shift)
    issue_ppe(volunteer["id"], item_type="MASK")
    # Briefing from 2026-08-01 expires at 2026-08-04T00:00:00Z; jump past it.
    set_clock("2026-08-10T08:00:00Z")
    res = api.check_in_assignment(assignment["id"], SITE)
    validate_error(res, "ERR_BRIEFING_NOT_CURRENT")
    after = validate_success(api.get_assignment(assignment["id"], MGR))
    assert after["status"] == "CONFIRMED"


def test_checkin_succeeds_after_briefing_refreshed(api):
    """PRD section 3.4: "A successful check-in stamps `checked_in_at` and, when
    the volunteer was `READY`, promotes them to `DEPLOYED`."

    Design: Difficulty/cross_entity_state_dependency/checkin_rejected_when_briefing_clearance_expired
    """
    _, volunteer, request, shift = _ready_volunteer_with_open_shift(api, "Flood Nu")
    assignment = propose_accept_confirm_assignment(volunteer, request, shift)
    issue_ppe(volunteer["id"], item_type="MASK")
    set_clock("2026-08-09T12:00:00Z")
    refresh_briefing(volunteer["id"])  # valid until 2026-08-12T12:00:00Z
    set_clock("2026-08-10T08:00:00Z")
    checked_in = validate_success(api.check_in_assignment(assignment["id"], SITE))
    assert checked_in["status"] == "CHECKED_IN"
    after = validate_success(api.get_volunteer(volunteer["id"], MGR))
    assert after["status"] == "DEPLOYED"


def test_checkin_on_cancelled_assignment_with_expired_briefing_state_wins(api):
    """PRD section 2.11: "7. Resource state preconditions for the requested
    transition or creation (`ERR_INVALID_STATE`), including the OCC version
    match of §2.9 (`ERR_STALE_VERSION`)."
    PRD section 2.11: "10. Gate-document checks: briefing currency, waiver
    presence, and PPE issuance (§3.4)."

    Design: Difficulty/priority_pair_validation_conflict/checkin_on_cancelled_assignment_with_expired_briefing_state_wins
    """
    _, volunteer, request, shift = _ready_volunteer_with_open_shift(api, "Flood Iota")
    assignment = propose_accept_confirm_assignment(volunteer, request, shift)
    validate_success(api.cancel_assignment(assignment["id"], INTAKE))
    # The 2026-08-01 briefing expires 2026-08-04T00:00:00Z; jump past it so the
    # gate-document rule would ALSO fail if the pipeline reached it.
    set_clock("2026-08-04T01:00:00Z")
    res = api.check_in_assignment(assignment["id"], SITE)
    validate_error(res, "ERR_INVALID_STATE")


def test_expired_briefing_alone_yields_briefing_not_current(api):
    """PRD section 3.4: "Three gate documents must also hold: a current
    briefing (`ERR_BRIEFING_NOT_CURRENT`), an active waiver
    (`ERR_WAIVER_NOT_SIGNED`), and at least one PPE issuance still `ISSUED` for
    the volunteer (`ERR_PPE_NOT_ISSUED`)."

    Design: Difficulty/priority_pair_validation_conflict/checkin_on_cancelled_assignment_with_expired_briefing_state_wins
    """
    _, volunteer, request, shift = _ready_volunteer_with_open_shift(api, "Flood Iota")
    assignment = propose_accept_confirm_assignment(volunteer, request, shift)
    issue_ppe(volunteer["id"])
    # Briefing from 2026-08-01 expired at 2026-08-04; at the shift window with
    # the assignment still CONFIRMED, only the gate-document rule can fail.
    set_clock("2026-08-10T08:00:00Z")
    res = api.check_in_assignment(assignment["id"], SITE)
    validate_error(res, "ERR_BRIEFING_NOT_CURRENT")


def test_checkin_after_waiver_revocation_returns_waiver_not_signed(api):
    """PRD section 3.6: "revoking a liability waiver while the volunteer is
    `READY` regresses them to `CLEARED`, while revoking it during `DEPLOYED`
    suspends them with the full cascade above, and revoking a briefing carries
    no volunteer-level consequence."
    PRD section 3.4: "Three gate documents must also hold: a current briefing
    (`ERR_BRIEFING_NOT_CURRENT`), an active waiver (`ERR_WAIVER_NOT_SIGNED`),
    and at least one PPE issuance still `ISSUED` for the volunteer
    (`ERR_PPE_NOT_ISSUED`)."

    Design: Corner/errors/checkin_after_waiver_revocation_returns_waiver_not_signed
    """
    _, volunteer, request, shift = _ready_volunteer_with_open_shift(
        api, "Flood L3", ppe={"GLOVES": 2, "MASK": 2, "HARD_HAT": 2,
                              "VEST": 2, "GOGGLES": 2})
    assignment = propose_accept_confirm_assignment(volunteer, request, shift)
    issue_ppe(volunteer["id"])
    # Locate the waiver clearance via the volunteer's clearance list.
    from test_helpers import validate_paginated
    clearances, _ = validate_paginated(
        api.list_volunteer_clearances(volunteer["id"], MGR,
                                      params={"clearance_type": "LIABILITY_WAIVER"}))
    waiver_id = clearances[0]["id"]
    validate_success(api.revoke_clearance(waiver_id, {"reason": "signature disputed"}, RISK))
    set_clock("2026-08-09T12:00:00Z")
    refresh_briefing(volunteer["id"])
    set_clock("2026-08-10T08:00:00Z")
    res = api.check_in_assignment(assignment["id"], SITE)
    validate_error(res, "ERR_WAIVER_NOT_SIGNED")


def test_checkin_without_ppe_returns_ppe_not_issued(api):
    """PRD section 3.4: "Three gate documents must also hold: a current
    briefing (`ERR_BRIEFING_NOT_CURRENT`), an active waiver
    (`ERR_WAIVER_NOT_SIGNED`), and at least one PPE issuance still `ISSUED` for
    the volunteer (`ERR_PPE_NOT_ISSUED`)."

    Design: Corner/errors/checkin_without_ppe_returns_ppe_not_issued
    """
    _, volunteer, request, shift = _ready_volunteer_with_open_shift(
        api, "Fire M3", ppe={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                             "VEST": 1, "GOGGLES": 1})
    assignment = propose_accept_confirm_assignment(volunteer, request, shift)
    set_clock("2026-08-09T12:00:00Z")
    refresh_briefing(volunteer["id"])
    set_clock("2026-08-10T08:00:00Z")
    res = api.check_in_assignment(assignment["id"], SITE)
    validate_error(res, "ERR_PPE_NOT_ISSUED")


def test_briefing_expired_at_exactly_valid_until_blocks_checkin(api):
    """PRD section 3.2: "A briefing remains valid strictly before its
    `valid_until`, set 72 hours after completion, and is expired at or past
    that instant; a waiver's `valid_until` is null because it never expires."

    Design: Corner/calculations/briefing_expired_at_exactly_valid_until_blocks_checkin
    """
    incident = create_active_incident(
        name="Fire M2", ppe_stock={"GLOVES": 2, "MASK": 2, "HARD_HAT": 2,
                                   "VEST": 2, "GOGGLES": 2})
    # Briefing completed 2026-08-07T08:00:00Z -> valid_until 2026-08-10T08:00:00Z.
    volunteer = vet_volunteer(incident["id"], with_clearances=False, mark_ready=False,
                              full_name="Eli Eder")["volunteer"]
    set_clock("2026-08-07T08:00:00Z")
    validate_success(api.create_clearance(
        create_clearance_payload(volunteer["id"], "SAFETY_BRIEFING"), INTAKE), 201)
    validate_success(api.create_clearance(
        create_clearance_payload(volunteer["id"], "LIABILITY_WAIVER"), INTAKE), 201)
    validate_success(api.mark_ready(volunteer["id"], INTAKE))
    request = create_published_request(incident["id"])
    shift = create_open_shift(incident["id"])
    assignment = propose_accept_confirm_assignment(
        validate_success(api.get_volunteer(volunteer["id"], MGR)), request, shift)
    issue_ppe(volunteer["id"], item_type="MASK")
    set_clock("2026-08-10T08:00:00Z")  # exactly valid_until: strictly-before fails
    res = api.check_in_assignment(assignment["id"], SITE)
    validate_error(res, "ERR_BRIEFING_NOT_CURRENT")


def test_open_roster_after_shift_end_returns_shift_window_passed(api):
    """PRD section 3.3: "A new shift is `SCHEDULED` with `rostered_count` zero,
    and opening the roster — permitted only before `end_at`, at or after which
    the call fails with `ERR_SHIFT_WINDOW_PASSED` — moves it to
    `OPEN_FOR_ROSTER` and re-derives posture."

    Design: Corner/errors/open_roster_after_shift_end_returns_shift_window_passed
    """
    from test_helpers import create_shift_payload
    incident = create_active_incident(name="Flood P3",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    shift = validate_success(api.create_shift(
        create_shift_payload(incident["id"], site_name="Old Mill",
                             start_at="2026-08-05T08:00:00Z",
                             end_at="2026-08-05T16:00:00Z"),
        TEST_USERS["logistics_headers"]), 201)
    set_clock("2026-08-06T00:00:00Z")
    res = api.open_roster(shift["id"], TEST_USERS["logistics_headers"])
    validate_error(res, "ERR_SHIFT_WINDOW_PASSED")
