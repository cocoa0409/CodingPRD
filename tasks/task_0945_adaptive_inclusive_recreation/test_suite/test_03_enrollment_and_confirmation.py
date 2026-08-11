"""Requesting a place, walking the six sub-gates, and coming back out again."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_one_to_one_conservation,
    assert_slot_conservation,
    charge_for,
    confirm_enrollment,
    create_active_participant,
    create_caregiver,
    create_confirmed_enrollment,
    create_fee_band,
    create_open_session,
    create_program,
    create_session,
    create_signed_consent,
    create_staff,
    deliver_session,
    lock_staffing,
    open_session,
    propose_assignment,
    read_enrollment,
    read_session,
    record_attendance,
    record_payment,
    request_enrollment,
    session_version,
    set_clock,
    set_participant_status,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_enrollment,
)
from test_helpers.fixtures import ADMIN, COORD


def _staffed_session_a():
    """Programme with two scheduled sessions; session A open, staffed and locked,
    with the participant confirmed onto it and an unpaid 4000-cent charge.

    Returns (program, session_a, participant, enrollment_a, staff_id).
    """
    create_fee_band(per_session_cents=4000)
    program = create_program(scheduled_session_count=2)
    session_a = create_session(
        program["id"], start_at="2026-06-01T09:00:00Z", end_at="2026-06-01T11:00:00Z"
    )
    open_session(session_a["id"])
    who = create_active_participant()
    enrollment_a = create_confirmed_enrollment(who["participant"]["id"], session_a["id"])
    staff_id = create_staff()["id"]
    propose_assignment(session_a["id"], staff_id)
    lock_staffing(session_a["id"], staff_id)
    return program, session_a, who["participant"], enrollment_a, staff_id


def _attend_and_deliver(session_a, enrollment_a, staff_id):
    """Mark the participant ATTENDED and deliver session A, leaving the charge unpaid."""
    set_clock("2026-06-01T10:00:00Z")
    record_attendance(enrollment_a["id"], staff_id, "ATTENDED")
    set_clock("2026-06-01T11:30:00Z")
    deliver_session(session_a["id"], staff_id)


def _delivered_session_leaving_an_outstanding_charge():
    """Session A delivered with the participant ATTENDED and the charge unpaid.

    Returns (program, session_a, participant, enrollment_a, staff_id).
    """
    program, session_a, participant, enrollment_a, staff_id = _staffed_session_a()
    _attend_and_deliver(session_a, enrollment_a, staff_id)
    return program, session_a, participant, enrollment_a, staff_id


def _outstanding_balance_and_a_locked_second_session():
    """Session A delivered with the participant ATTENDED and its charge unpaid,
    plus a session B the same participant already holds a `REQUESTED` place on,
    whose staffing has since been locked.

    The place on session B is requested *before* session A is delivered, because
    PRD §3.2 puts the family-balance rung on enrolment **creation** as well:
    "Finally, at the bottom of the ladder, the family balance rung applies here
    as well: a participant carrying an `OUTSTANDING` charge on an
    already-delivered session cannot request a new place, and is refused with
    `ERR_FAMILY_BALANCE_OUTSTANDING` (402)."  A request issued after delivery is
    therefore correctly refused and never reaches the confirmation ladder that
    these tests are about.

    Returns (session_a, enrollment_a, session_b, enrollment_b).
    """
    program, session_a, participant, enrollment_a, staff_id = _staffed_session_a()

    # The place on session B is taken while the family balance is still clean.
    session_b = create_session(
        program["id"], start_at="2026-06-17T09:00:00Z", end_at="2026-06-17T11:00:00Z"
    )
    open_session(session_b["id"])
    enrollment_b = request_enrollment(participant["id"], session_b["id"])

    _attend_and_deliver(session_a, enrollment_a, staff_id)

    # Session B leaves `OPEN`, so rung 28 is now violated as well as rung 60.
    lock_staffing(session_b["id"], staff_id)
    return session_a, enrollment_a, session_b, enrollment_b


def test_session_not_open_pre_empts_the_outstanding_family_balance_on_confirm():
    """PRD §2.10 rung 28: "On enrolment creation and enrolment confirmation, the
    enrolment's session has `status` `OPEN` — otherwise `ERR_SESSION_NOT_OPEN`
    (409)."
    PRD §2.10 rung 60: "On enrolment creation, enrolment confirmation and the
    promotion walk, the participant carries no enrolment charge whose `status` is
    `OUTSTANDING` on a session that has already been delivered — otherwise
    `ERR_FAMILY_BALANCE_OUTSTANDING` (402)."
    PRD §2.10: "**Error precedence where two rungs could both fire.** The rule is
    always the lower rung number wins, and it resolves every ambiguity in this
    document."

    Design: Difficulty/priority_pair_validation_conflict/state_rung_28_beats_fiscal_rung_60_on_confirm
    """
    _session_a, _enrollment_a, _session_b, enrollment_b = (
        _outstanding_balance_and_a_locked_second_session()
    )

    validate_error(
        api_client.confirm_enrollment(enrollment_b["id"], COORD, {}),
        ApiErrorId.ERR_SESSION_NOT_OPEN.value,
        expected_status=409,
    )
    assert read_enrollment(enrollment_b["id"])["enrollment_status"] == "REQUESTED"


def test_the_locked_session_refusal_names_the_state_rung_not_the_fiscal_rung():
    """PRD §2.10: "**Error precedence where two rungs could both fire.** The rule
    is always the lower rung number wins, and it resolves every ambiguity in this
    document."
    PRD §2.10 rung 60: "On enrolment creation, enrolment confirmation and the
    promotion walk, the participant carries no enrolment charge whose `status` is
    `OUTSTANDING` on a session that has already been delivered — otherwise
    `ERR_FAMILY_BALANCE_OUTSTANDING` (402)."
    PRD §3.3: "Otherwise it is `SETTLED` when `balance_cents` is 0. Otherwise it
    is `OUTSTANDING`."

    Design: Difficulty/priority_pair_validation_conflict/state_rung_28_beats_fiscal_rung_60_on_confirm
    """
    session_a, enrollment_a, _session_b, enrollment_b = (
        _outstanding_balance_and_a_locked_second_session()
    )

    # Both rungs are genuinely violated: session A is delivered and its charge is unpaid.
    assert read_session(session_a["id"])["status"] == "DELIVERED"
    assert charge_for(enrollment_a["id"])["status"] == "OUTSTANDING"

    error = validate_error(
        api_client.confirm_enrollment(enrollment_b["id"], COORD, {}),
        ApiErrorId.ERR_SESSION_NOT_OPEN.value,
        expected_status=409,
    )
    assert error["error_id"] != ApiErrorId.ERR_FAMILY_BALANCE_OUTSTANDING.value


def _full_session_with_an_unconsented_candidate():
    """One-slot session on a consent-requiring programme, already full, plus a
    second active participant holding no consent artifact at all."""
    create_fee_band()
    _program, session = create_open_session(
        program_overrides={
            "name": "Adaptive Aquatics",
            "activity_type": "AQUATICS",
            "required_consent_types": ["EMERGENCY_MEDICAL"],
        },
        slot_capacity=1,
    )
    holder = create_active_participant()
    caregiver = create_caregiver(holder["participant"]["id"])
    consent = create_signed_consent(
        holder["participant"]["id"], caregiver["id"],
        consent_type="EMERGENCY_MEDICAL", expires_on="2026-12-31",
    )
    create_confirmed_enrollment(holder["participant"]["id"], session["id"])

    candidate = create_active_participant(
        legal_name="Ben Osei", date_of_birth="2009-07-15", household_id="HH-2", weight_kg=45
    )
    enrollment = request_enrollment(candidate["participant"]["id"], session["id"])
    return session, consent, caregiver, enrollment


def test_missing_required_consent_pre_empts_the_full_session_on_confirm():
    """PRD §2.10 rung 34: "**Sub-gate A, head rung.** On enrolment confirmation
    and the promotion walk, every consent type in the programme's
    `required_consent_types` has a matching `SIGNED` consent artifact for the
    participant — otherwise `ERR_REQUIRED_CONSENT_MISSING` (422)."
    PRD §2.10 rung 45: "**Sub-gate C, head rung.** On enrolment confirmation and
    the promotion walk, the session's `slots_available` is at least 1 — otherwise
    `ERR_SESSION_FULL` (409), unless the confirm request asked for waitlist or
    deny routing, in which case this rung routes rather than raises."

    Design: Difficulty/priority_pair_validation_conflict/safety_rung_34_beats_capacity_rung_45_on_confirm
    """
    session, _consent, _caregiver, enrollment = _full_session_with_an_unconsented_candidate()

    validate_error(
        api_client.confirm_enrollment(enrollment["id"], COORD, {}),
        ApiErrorId.ERR_REQUIRED_CONSENT_MISSING.value,
        expected_status=422,
    )
    assert read_enrollment(enrollment["id"])["enrollment_status"] == "REQUESTED"
    assert read_session(session["id"])["slots_available"] == 0


def test_full_session_still_reports_the_consent_rung_and_records_the_guardian_signature():
    """PRD §2.10: "**Error precedence where two rungs could both fire.** The rule
    is always the lower rung number wins, and it resolves every ambiguity in this
    document."
    PRD §3.2: "A successful signature moves the artifact from
    `PENDING_SIGNATURE` to `SIGNED`, stamps `signed_on` with the logical clock's
    calendar date, stamps `signer_role` with `SELF` or `LEGAL_GUARDIAN` per the
    rule above, and stamps `signed_by_caregiver_id` with the acting caregiver's
    id — or leaves it null when the accepted role was `SELF`."

    Design: Difficulty/priority_pair_validation_conflict/safety_rung_34_beats_capacity_rung_45_on_confirm
    """
    session, consent, caregiver, enrollment = _full_session_with_an_unconsented_candidate()

    assert consent["signer_role"] == "LEGAL_GUARDIAN"
    assert consent["signed_by_caregiver_id"] == caregiver["id"]

    error = validate_error(
        api_client.confirm_enrollment(enrollment["id"], COORD, {}),
        ApiErrorId.ERR_REQUIRED_CONSENT_MISSING.value,
        expected_status=422,
    )
    assert error["error_id"] != ApiErrorId.ERR_SESSION_FULL.value
    after = read_session(session["id"])
    assert after["slots_available"] == 0, "the capacity rung was genuinely violated too"
    assert after["slots_committed"] == 1


def _three_overlapping_sessions():
    """Sessions X 09:00-11:00, Y 11:00-13:00 and W 10:00-12:00 on one day."""
    create_fee_band()
    program = create_program(scheduled_session_count=3)
    x = create_session(
        program["id"], start_at="2026-06-10T09:00:00Z", end_at="2026-06-10T11:00:00Z"
    )
    y = create_session(
        program["id"], start_at="2026-06-10T11:00:00Z", end_at="2026-06-10T13:00:00Z"
    )
    w = create_session(
        program["id"], start_at="2026-06-10T10:00:00Z", end_at="2026-06-10T12:00:00Z"
    )
    for session in (x, y, w):
        open_session(session["id"])
    return x, y, w


def test_participant_back_to_back_sessions_do_not_collide():
    """PRD §3.3: "over that participant's enrolments whose `enrollment_status` is
    `REQUESTED`, `WAITLISTED` or `CONFIRMED`, the request is rejected with
    `ERR_PARTICIPANT_TIME_CONFLICT` when the new session's `start_at` falls
    strictly before an existing session's `end_at` **and** that existing session's
    `start_at` falls strictly before the new session's `end_at`. These are
    strictly half-open intervals with no buffer whatsoever, so two sessions that
    touch exactly — the new one starting at the very instant the old one ends —
    do **not** collide for a participant."

    Design: Difficulty/resource_temporal_overlap/participant_back_to_back_sessions_do_not_collide_but_a_real_overlap_does
    """
    x, y, _w = _three_overlapping_sessions()
    who = create_active_participant()
    participant_id = who["participant"]["id"]

    first = validate_success(
        api_client.create_enrollment(
            {
                "participant_id": participant_id,
                "session_id": x["id"],
                "expected_session_version": session_version(x["id"]),
            },
            COORD,
        ),
        expected_status=201,
    )
    second = validate_success(
        api_client.create_enrollment(
            {
                "participant_id": participant_id,
                "session_id": y["id"],
                "expected_session_version": session_version(y["id"]),
            },
            COORD,
        ),
        expected_status=201,
    )

    assert first["enrollment_status"] == "REQUESTED"
    assert second["enrollment_status"] == "REQUESTED"


def test_participant_interior_overlap_is_rejected():
    """PRD §3.3: "over that participant's enrolments whose `enrollment_status` is
    `REQUESTED`, `WAITLISTED` or `CONFIRMED`, the request is rejected with
    `ERR_PARTICIPANT_TIME_CONFLICT` when the new session's `start_at` falls
    strictly before an existing session's `end_at` **and** that existing session's
    `start_at` falls strictly before the new session's `end_at`."
    PRD §2.10 rung 43: "On enrolment creation, the participant has no colliding
    live enrolment — otherwise `ERR_PARTICIPANT_TIME_CONFLICT` (409)."

    Design: Difficulty/resource_temporal_overlap/participant_back_to_back_sessions_do_not_collide_but_a_real_overlap_does
    """
    x, y, w = _three_overlapping_sessions()
    who = create_active_participant()
    participant_id = who["participant"]["id"]
    request_enrollment(participant_id, x["id"])
    request_enrollment(participant_id, y["id"])

    validate_error(
        api_client.create_enrollment(
            {
                "participant_id": participant_id,
                "session_id": w["id"],
                "expected_session_version": session_version(w["id"]),
            },
            COORD,
        ),
        ApiErrorId.ERR_PARTICIPANT_TIME_CONFLICT.value,
        expected_status=409,
    )

    _rows, meta = validate_paginated(
        api_client.list_enrollments(ADMIN, params={"participant_id": participant_id})
    )
    assert meta["total_count"] == 2, "the colliding request wrote nothing"


def _session_with_two_confirmed_participants():
    create_fee_band()
    _program, session = create_open_session(slot_capacity=2)
    first = create_active_participant()
    second = create_active_participant(
        legal_name="Ben Osei", date_of_birth="2009-07-15", household_id="HH-2", weight_kg=45
    )
    enrollment_one = create_confirmed_enrollment(first["participant"]["id"], session["id"])
    enrollment_two = create_confirmed_enrollment(second["participant"]["id"], session["id"])
    return session, enrollment_one, enrollment_two


def test_withdraw_restores_the_program_slot():
    """PRD §3.4: "Hop 2, caused by hop 1, unwinds everything that row was holding:
    `slots_committed` falls by one and `slots_available` rises by one"
    PRD §3.4: "When all six pass, confirmation runs a fixed sequence of side
    effects. `slots_committed` rises by one and `slots_available` falls by one."

    Design: Difficulty/compensating_invariant/withdraw_conserves_program_slots_on_the_session
    """
    session, enrollment_one, enrollment_two = _session_with_two_confirmed_participants()

    before = read_session(session["id"])
    assert before["slots_committed"] == 2
    assert before["slots_available"] == 0

    withdraw_enrollment(enrollment_one["id"])

    after = read_session(session["id"])
    assert after["slots_committed"] == 1
    assert after["slots_available"] == 1
    assert read_enrollment(enrollment_two["id"])["enrollment_status"] == "CONFIRMED"


def test_slot_capacity_is_conserved_across_confirm_and_withdraw():
    """PRD §2.11: "**Programme slots.** For every session, `slot_capacity` equals
    `slots_committed` plus `slots_available`, and `slots_committed` equals the
    number of enrolments on that session whose `enrollment_status` is
    `CONFIRMED`. This must hold after enrolment confirmation, after withdrawal,
    after a waitlist promotion, after a funding-driven demotion back to the
    waitlist, after a session cancellation, and after attendance is recorded."

    Design: Difficulty/compensating_invariant/withdraw_conserves_program_slots_on_the_session
    """
    session, enrollment_one, _enrollment_two = _session_with_two_confirmed_participants()

    before = read_session(session["id"])
    assert_slot_conservation(before)
    assert before["slot_capacity"] == 2

    withdraw_enrollment(enrollment_one["id"])

    after = read_session(session["id"])
    assert_slot_conservation(after)
    assert after["slot_capacity"] == 2

    _rows, meta = validate_paginated(
        api_client.list_enrollments(
            ADMIN, params={"session_id": session["id"], "enrollment_status": "CONFIRMED"}
        )
    )
    assert meta["total_count"] == 1, "slots_committed must equal the CONFIRMED count"
    assert after["slots_committed"] == meta["total_count"]


def _one_slot_session_already_full():
    create_fee_band()
    _program, session = create_open_session(slot_capacity=1)
    holder = create_active_participant()
    create_confirmed_enrollment(holder["participant"]["id"], session["id"])
    candidate = create_active_participant(
        legal_name="Ben Osei", date_of_birth="2009-07-15", household_id="HH-2", weight_kg=45
    )
    enrollment = request_enrollment(candidate["participant"]["id"], session["id"])
    return session, enrollment


def test_confirm_with_on_full_deny_terminates_the_enrollment():
    """PRD §3.4: "`on_full` accepts `ERROR`, `WAITLIST` or `DENY`, and **defaults
    to `ERROR` when omitted or sent as null**. Under `ERROR` a full session raises
    `ERR_SESSION_FULL` or `ERR_ONE_TO_ONE_POOL_EXHAUSTED` and nothing changes.
    Under `WAITLIST` the enrolment moves from `REQUESTED` to `WAITLISTED`. Under
    `DENY` it moves from `REQUESTED` to `DENIED`."
    PRD §3.3: "The charge is `VOIDED` when its enrolment's `enrollment_status` is
    `WITHDRAWN` or `DENIED`."

    Design: Corner/state_machines/confirm_with_on_full_deny_terminates_the_enrollment
    """
    session, enrollment = _one_slot_session_already_full()

    denied = validate_success(
        api_client.confirm_enrollment(enrollment["id"], COORD, {"on_full": "DENY"})
    )
    assert denied["enrollment_status"] == "DENIED"
    assert charge_for(enrollment["id"])["status"] == "VOIDED"

    after = read_session(session["id"])
    assert after["slots_committed"] == 1
    assert after["slots_available"] == 0


def test_session_full_returns_conflict_when_on_full_is_omitted():
    """PRD §3.4: "Under `ERROR` a full session raises `ERR_SESSION_FULL` or
    `ERR_ONE_TO_ONE_POOL_EXHAUSTED` and nothing changes."
    PRD §2.10 rung 45: "**Sub-gate C, head rung.** On enrolment confirmation and
    the promotion walk, the session's `slots_available` is at least 1 — otherwise
    `ERR_SESSION_FULL` (409), unless the confirm request asked for waitlist or
    deny routing, in which case this rung routes rather than raises."

    Design: Corner/validations/session_full_returns_conflict_when_on_full_is_omitted
    """
    session, enrollment = _one_slot_session_already_full()

    validate_error(
        api_client.confirm_enrollment(enrollment["id"], COORD, {}),
        ApiErrorId.ERR_SESSION_FULL.value,
        expected_status=409,
    )
    assert read_enrollment(enrollment["id"])["enrollment_status"] == "REQUESTED"
    after = read_session(session["id"])
    assert after["slots_committed"] == 1
    assert after["slots_available"] == 0


def test_enrollment_create_rejects_duplicate_inactive_and_late_requests():
    """PRD §3.3: "The participant must hold no other enrolment on this same
    session whose `enrollment_status` is `REQUESTED`, `WAITLISTED` or `CONFIRMED`,
    or the request is a duplicate; a previously withdrawn, denied, attended or
    no-showed row does not block a fresh request."
    PRD §2.10 rung 33: "On enrolment creation, on enrolment confirmation and on
    the waitlist-promotion walk, the participant's `status` is `ACTIVE` —
    otherwise `ERR_PARTICIPANT_NOT_ACTIVE` (409)."
    PRD §3.3: "The session's `start_at` must be at least 24 hours later than the
    logical clock; a session starting in exactly 24 hours is still enrollable,
    one starting in 23 hours 59 minutes is not, and the failure is
    `ERR_ENROLLMENT_CUTOFF_PASSED`."

    Design: Corner/validations/enrollment_create_rungs_reject_duplicate_inactive_and_late_requests
    """
    create_fee_band()
    _program, session = create_open_session(slot_capacity=4)
    first = create_active_participant()
    second = create_active_participant(
        legal_name="Ben Osei", date_of_birth="2009-07-15", household_id="HH-2", weight_kg=45
    )
    request_enrollment(first["participant"]["id"], session["id"])
    current_version = session_version(session["id"])

    validate_error(
        api_client.create_enrollment(
            {
                "participant_id": first["participant"]["id"],
                "session_id": session["id"],
                "expected_session_version": current_version,
            },
            COORD,
        ),
        ApiErrorId.ERR_DUPLICATE_ENROLLMENT.value,
        expected_status=409,
    )

    set_participant_status(second["participant"]["id"], "INACTIVE")
    validate_error(
        api_client.create_enrollment(
            {
                "participant_id": second["participant"]["id"],
                "session_id": session["id"],
                "expected_session_version": current_version,
            },
            COORD,
        ),
        ApiErrorId.ERR_PARTICIPANT_NOT_ACTIVE.value,
        expected_status=409,
    )

    set_participant_status(second["participant"]["id"], "ACTIVE")
    set_clock("2026-06-10T00:00:00Z")
    validate_error(
        api_client.create_enrollment(
            {
                "participant_id": second["participant"]["id"],
                "session_id": session["id"],
                "expected_session_version": current_version,
            },
            COORD,
        ),
        ApiErrorId.ERR_ENROLLMENT_CUTOFF_PASSED.value,
        expected_status=422,
    )

    _rows, meta = validate_paginated(
        api_client.list_enrollments(ADMIN, params={"session_id": session["id"]})
    )
    assert meta["total_count"] == 1, "all three refusals wrote nothing"


def test_stale_assessment_blocks_confirm():
    """PRD §2.10 rung 37: "**Sub-gate B, head rung and only rung.** On enrolment
    confirmation and the promotion walk, the participant has a `SupportAssessment`
    whose `status` is `ACTIVE` and whose `assessed_on` plus 365 days falls on or
    after the session's calendar date — otherwise `ERR_ASSESSMENT_STALE` (422)."
    PRD §3.2: "otherwise `ASSESSMENT_STALE` when there is no `ACTIVE` support
    assessment at all, or the active one's `assessed_on` plus 365 days falls
    before the check date"

    Design: Corner/validations/stale_assessment_blocks_confirm
    """
    create_fee_band()
    _program, session = create_open_session()
    who = create_active_participant(
        assessment_overrides={
            "assessed_on": "2025-05-01",
            "effective_from": "2025-05-01T00:00:00Z",
        }
    )
    participant_id = who["participant"]["id"]
    enrollment = request_enrollment(participant_id, session["id"])

    validate_error(
        api_client.confirm_enrollment(enrollment["id"], COORD, {}),
        ApiErrorId.ERR_ASSESSMENT_STALE.value,
        expected_status=422,
    )

    eligibility = validate_success(
        api_client.get_participant_eligibility(
            participant_id, COORD, params={"session_id": session["id"]}
        )
    )
    assert eligibility["enrollment_posture"] == "ASSESSMENT_STALE"
    assert eligibility["assessment_gate_ok"] is False
    assert read_enrollment(enrollment["id"])["enrollment_status"] == "REQUESTED"


def test_one_to_one_pool_exhausted_while_program_slots_remain():
    """PRD §2.10 rung 46: "**Sub-gate C, continued.** When the participant's
    effective tier at this session is `ONE_TO_ONE`, the session's
    `one_to_one_available` is at least 1 — otherwise
    `ERR_ONE_TO_ONE_POOL_EXHAUSTED` (409), with the same routing option as rung
    45. The one-to-one pool is a separate counter from the programme slots and
    the two are never interchangeable."
    PRD §3.5: "If the pooled set is empty, the requirement is exactly 0 — the
    one-staffer floor does **not** apply to an empty set, so a session attended
    only by one-to-one participants, or by nobody, needs no group staff at all."

    Design: Corner/validations/one_to_one_pool_exhausted_rejected_while_slots_remain
    """
    create_fee_band()
    _program, session = create_open_session(
        program_overrides={"name": "One-to-One Swim", "activity_type": "AQUATICS"},
        slot_capacity=3,
        one_to_one_pool_size=1,
    )
    first = create_active_participant(support_tier="ONE_TO_ONE")
    second = create_active_participant(
        support_tier="ONE_TO_ONE",
        legal_name="Ben Osei", date_of_birth="2009-07-15", household_id="HH-2", weight_kg=45,
    )
    create_confirmed_enrollment(first["participant"]["id"], session["id"])
    enrollment = request_enrollment(second["participant"]["id"], session["id"])

    validate_error(
        api_client.confirm_enrollment(enrollment["id"], COORD, {}),
        ApiErrorId.ERR_ONE_TO_ONE_POOL_EXHAUSTED.value,
        expected_status=409,
    )

    after = read_session(session["id"])
    assert after["slots_available"] == 2, "the slot counter was never the blocker"
    assert after["one_to_one_committed"] == 1
    assert after["one_to_one_available"] == 0
    assert after["required_group_staff_planned"] == 0
    assert_one_to_one_conservation(after)


def test_outstanding_balance_on_a_delivered_session_blocks_a_new_enrollment():
    """PRD §2.10 rung 60: "On enrolment creation, enrolment confirmation and the
    promotion walk, the participant carries no enrolment charge whose `status` is
    `OUTSTANDING` on a session that has already been delivered — otherwise
    `ERR_FAMILY_BALANCE_OUTSTANDING` (402)."
    PRD §3.8: "The paid amount is added to `amount_paid_cents`, then
    `balance_cents` and the settlement `status` are re-derived."

    Design: Corner/validations/outstanding_balance_on_a_delivered_session_blocks_a_new_enrollment
    """
    program, _session_a, participant, enrollment_a, _staff_id = (
        _delivered_session_leaving_an_outstanding_charge()
    )
    session_b = create_session(
        program["id"], start_at="2026-06-17T09:00:00Z", end_at="2026-06-17T11:00:00Z"
    )
    open_session(session_b["id"])

    charge = charge_for(enrollment_a["id"])
    assert charge["status"] == "OUTSTANDING"
    assert charge["balance_cents"] == 4000

    validate_error(
        api_client.create_enrollment(
            {
                "participant_id": participant["id"],
                "session_id": session_b["id"],
                "expected_session_version": session_version(session_b["id"]),
            },
            COORD,
        ),
        ApiErrorId.ERR_FAMILY_BALANCE_OUTSTANDING.value,
        expected_status=402,
    )

    settled = record_payment(charge["id"], 4000)
    assert settled["status"] == "SETTLED"

    accepted = validate_success(
        api_client.create_enrollment(
            {
                "participant_id": participant["id"],
                "session_id": session_b["id"],
                "expected_session_version": session_version(session_b["id"]),
            },
            COORD,
        ),
        expected_status=201,
    )
    assert accepted["enrollment_status"] == "REQUESTED"


def test_stale_session_version_rejects_the_second_enrollment():
    """PRD §2.9: "Creating an enrolment (`POST /recreation/enrollments`) must
    carry `expected_session_version` matching the current `version` of the
    `ProgramSession` named by `session_id`."
    PRD §2.9: "If the echoed number is not equal to the parent's current
    `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412) and
    nothing is written."
    PRD §3.3: "The session's `version` rises by one even though no counter moved,
    which is exactly what makes the next client's stale-version check
    meaningful."

    Design: Corner/cross_cutting_complexity_layers/stale_session_version_rejects_the_second_enrollment
    """
    create_fee_band()
    _program, session = create_open_session(slot_capacity=3)
    first = create_active_participant()
    second = create_active_participant(
        legal_name="Ben Osei", date_of_birth="2009-07-15", household_id="HH-2", weight_kg=45
    )
    stale_version = session_version(session["id"])

    validate_success(
        api_client.create_enrollment(
            {
                "participant_id": first["participant"]["id"],
                "session_id": session["id"],
                "expected_session_version": stale_version,
            },
            COORD,
        ),
        expected_status=201,
    )

    validate_error(
        api_client.create_enrollment(
            {
                "participant_id": second["participant"]["id"],
                "session_id": session["id"],
                "expected_session_version": stale_version,
            },
            COORD,
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
        expected_status=412,
    )

    retry = validate_success(
        api_client.create_enrollment(
            {
                "participant_id": second["participant"]["id"],
                "session_id": session["id"],
                "expected_session_version": session_version(session["id"]),
            },
            COORD,
        ),
        expected_status=201,
    )
    assert retry["enrollment_status"] == "REQUESTED"

    _rows, meta = validate_paginated(
        api_client.list_enrollments(ADMIN, params={"session_id": session["id"]})
    )
    assert meta["total_count"] == 2


def test_confirm_response_reflects_every_derived_counter_immediately():
    """PRD §2.6: "The serializer runs **after** the version bump and after every
    recomputation the request triggered, so a mutation response always shows the
    post-mutation `version` and the post-mutation values of every derived field
    on that row."
    PRD §3.4: "When all six pass, confirmation runs a fixed sequence of side
    effects. `slots_committed` rises by one and `slots_available` falls by one."
    PRD §3.3: "Otherwise it is `SETTLED` when `balance_cents` is 0. Otherwise it
    is `OUTSTANDING`."

    Design: Corner/consistency_model/confirm_response_reflects_every_derived_counter_immediately
    """
    create_fee_band(per_session_cents=4000)
    _program, session = create_open_session(slot_capacity=2)
    who = create_active_participant()
    version_before = session_version(session["id"])
    enrollment = request_enrollment(who["participant"]["id"], session["id"])

    confirmed = confirm_enrollment(enrollment["id"])
    assert confirmed["enrollment_status"] == "CONFIRMED"
    assert confirmed["effective_support_tier_at_session"] == "INDEPENDENT"

    after = read_session(session["id"])
    assert after["slots_committed"] == 1
    assert after["slots_available"] == 1
    assert after["required_group_staff_planned"] == 1
    assert after["staffing_gap"] == 1
    assert after["version"] > version_before

    charge = charge_for(enrollment["id"])
    assert charge["status"] == "OUTSTANDING"
    assert charge["family_responsibility_cents"] == 4000
