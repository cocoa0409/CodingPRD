"""Application/appointment lifecycles, the denial-appeal-revetting cycle, and
multi-record cascades.

Covers PRD §3.4-§3.8 workflow narratives. Translates difficulty queue A
instances for non_linear_state_machine, transitive_cascade,
cross_entity_state_dependency, and compensating_invariant, plus corner queue B
state_machine instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_applicant_headers, make_vetting_officer_headers, make_appeals_officer_headers,
    TEST_USERS, ApiErrorId,
    pay_payload, background_check_payload, biometric_payload,
    appointment_payload, appeal_payload, decide_payload, withdraw_payload,
    setup_submitted_application, setup_vetting_application,
    setup_confirmed_appointment, setup_denied_application, setup_appeal_pending,
    setup_approved_application, get_application, app_version,
    create_program, create_applicant, create_center, create_slot,
    create_draft_application, set_clock,
)

ADMIN = TEST_USERS["scheduling_admin_headers"]
VETTING = TEST_USERS["vetting_officer_headers"]
APPEALS = TEST_USERS["appeals_officer_headers"]
ENROLLMENT = TEST_USERS["enrollment_officer_headers"]


# ---------------------------------------------------------------------------
# Queue A — non_linear_state_machine
# ---------------------------------------------------------------------------

def test_denial_appeal_overturn_reopens_vetting_cycle(api):
    """PRD §3.7: "An `OVERTURNED` outcome reinstates the applicant: the application
    returns from `APPEAL_PENDING` to `VETTING`, and the background check is reset
    from `ADVERSE` back to `PENDING` with its `adverse_reason` cleared, reopening
    the vetting loop so the application can proceed again."

    Design: Difficulty/non_linear_state_machine/application_denial_appeal_revetting_cycle
    """
    program, applicant, app, bc, appeal = setup_appeal_pending(
        vetting_user_id="vetting-officer-1"
    )
    decider = make_appeals_officer_headers("appeals-officer-9")
    decided = get_success_data(
        api.decide_appeal(appeal["id"], decide_payload("OVERTURNED"), decider)
    )
    assert decided["status"] == "DECIDED"
    assert decided["outcome"] == "OVERTURNED"
    final_app = get_application(app["id"])
    assert final_app["status"] == "VETTING", "overturn returns application to VETTING"
    final_bc = get_success_data(api.get_background_check(bc["id"], VETTING))
    assert final_bc["status"] == "PENDING", "background check reset ADVERSE -> PENDING"


def test_confirmed_appointment_can_be_cancelled_to_terminal(api):
    """PRD §3.5: "An `Applicant` may cancel a `CONFIRMED` appointment, moving it to
    `CANCELLED`; this frees the slot back to `AVAILABLE`, clears its
    `held_by_appointment_id`, and - if the application was in
    `INTERVIEW_SCHEDULED` - reverts it to `VETTING`."

    Design: Difficulty/non_linear_state_machine/appointment_confirmed_branches_to_three_terminals
    """
    program, applicant, app, center, slot, appt = setup_confirmed_appointment()
    headers = make_applicant_headers(applicant["id"])
    cancelled = get_success_data(api.cancel_appointment(appt["id"], headers))
    assert cancelled["status"] == "CANCELLED"
    final_slot = get_success_data(api.get_slot(slot["id"], ADMIN))
    assert final_slot["status"] == "AVAILABLE"
    final_app = get_application(app["id"])
    assert final_app["status"] == "VETTING", (
        "INTERVIEW_SCHEDULED reverts to VETTING on cancel"
    )


def test_confirmed_appointment_completes_to_terminal(api):
    """PRD §3.5: "Completing the appointment moves it from `CONFIRMED` to
    `COMPLETED`, leaves its slot `BOOKED`, carries the application from
    `INTERVIEW_SCHEDULED` to `INTERVIEW_COMPLETE`, advances the application's
    `version`, and writes an audit record."

    Design: Difficulty/non_linear_state_machine/appointment_confirmed_branches_to_three_terminals
    """
    program, applicant, app, center, slot, appt = setup_confirmed_appointment()
    get_success_data(
        api.create_biometric_capture(biometric_payload(appt["id"]), ENROLLMENT)
    )
    completed = get_success_data(api.complete_appointment(appt["id"], ENROLLMENT))
    assert completed["status"] == "COMPLETED"
    final_slot = get_success_data(api.get_slot(slot["id"], ADMIN))
    assert final_slot["status"] == "BOOKED", "completing leaves the slot BOOKED"
    final_app = get_application(app["id"])
    assert final_app["status"] == "INTERVIEW_COMPLETE"


def test_denial_then_appeal_filing_moves_to_appeal_pending(api):
    """PRD §3.7: "An appeal names a `filed_reason` and is created in `OPEN`; filing
    moves the application from `DENIED` to `APPEAL_PENDING`, increments
    `appeal_count` by one, advances the application's `version`, and writes an audit
    record (event type `APPEAL_FILED`)."

    Design: Difficulty/non_linear_state_machine/application_denial_appeal_revetting_cycle
    """
    program, applicant, app, bc = setup_denied_application(
        vetting_user_id="vetting-officer-1"
    )
    assert app["status"] == "DENIED", "ADVERSE adjudication denied the application"
    headers = make_applicant_headers(applicant["id"])
    appeal = validate_success(
        api.file_appeal(app["id"], appeal_payload(filed_reason="cycle"), headers),
        expected_status=201,
    )
    assert appeal["status"] == "OPEN"
    moved = get_application(app["id"])
    assert moved["status"] == "APPEAL_PENDING", "filing moves DENIED -> APPEAL_PENDING"
    assert moved["appeal_count"] == 1


# ---------------------------------------------------------------------------
# Queue A — transitive_cascade
# ---------------------------------------------------------------------------

def test_overturn_cascade_resets_application_and_background_check(api):
    """PRD §3.7: "An `OVERTURNED` outcome reinstates the applicant: the application
    returns from `APPEAL_PENDING` to `VETTING`, and the background check is reset
    from `ADVERSE` back to `PENDING` with its `adverse_reason` cleared, reopening
    the vetting loop so the application can proceed again."

    Design: Difficulty/transitive_cascade/overturn_appeal_cascade_app_then_background_check
    """
    program, applicant, app, bc, appeal = setup_appeal_pending(
        vetting_user_id="vetting-officer-1"
    )
    # Pre-condition sanity: adverse_reason was populated on the denial.
    decider = make_appeals_officer_headers("appeals-officer-9")
    decided = get_success_data(
        api.decide_appeal(appeal["id"], decide_payload("OVERTURNED"), decider)
    )
    assert decided["status"] == "DECIDED"
    final_app = get_application(app["id"])
    assert final_app["status"] == "VETTING"
    assert final_app["adverse_reason"] is None, "adverse_reason cleared on overturn"
    final_bc = get_success_data(api.get_background_check(bc["id"], VETTING))
    assert final_bc["status"] == "PENDING"


def test_withdraw_cascade_cancels_appointment_and_frees_slot(api):
    """PRD §3.8: "Any `CONFIRMED` appointment is moved to `CANCELLED` and its slot
    freed to `AVAILABLE`; any `OPEN` appeal is moved to `DECIDED` with an `UPHELD`
    outcome. The application itself moves to the terminal `WITHDRAWN` state, its
    `version` advances, and an audit record is written."

    Design: Difficulty/transitive_cascade/withdraw_cascade_appointment_then_slot
    """
    program, applicant, app, center, slot, appt = setup_confirmed_appointment()
    headers = make_applicant_headers(applicant["id"])
    version = app_version(app["id"])
    withdrawn = get_success_data(
        api.withdraw_application(app["id"], withdraw_payload(version), headers)
    )
    assert withdrawn["status"] == "WITHDRAWN"
    final_appt = get_success_data(api.get_appointment(appt["id"], ADMIN))
    assert final_appt["status"] == "CANCELLED", "withdraw cancels CONFIRMED appointment"
    final_slot = get_success_data(api.get_slot(slot["id"], ADMIN))
    assert final_slot["status"] == "AVAILABLE", "cancelled appointment frees the slot"


def test_overturn_decision_is_made_by_segregated_officer(api):
    """PRD §3.7: "The decision moves the appeal from `OPEN` to `DECIDED` and records
    the deciding officer as `decided_by_user_id` along with the chosen `outcome`."

    Design: Difficulty/transitive_cascade/overturn_appeal_cascade_app_then_background_check
    """
    program, applicant, app, bc, appeal = setup_appeal_pending(
        vetting_user_id="vetting-officer-1"
    )
    decider = make_appeals_officer_headers("appeals-officer-9")
    decided = get_success_data(
        api.decide_appeal(appeal["id"], decide_payload("OVERTURNED"), decider)
    )
    assert decided["status"] == "DECIDED"
    assert decided["outcome"] == "OVERTURNED"
    assert decided["decided_by_user_id"] == "appeals-officer-9", (
        "deciding officer's X-User-ID recorded as decided_by_user_id"
    )


def test_withdraw_from_appeal_pending_upholds_open_appeal(api):
    """PRD §3.8: "Any `CONFIRMED` appointment is moved to `CANCELLED` and its slot
    freed to `AVAILABLE`; any `OPEN` appeal is moved to `DECIDED` with an `UPHELD`
    outcome."

    Design: Difficulty/transitive_cascade/withdraw_cascade_appointment_then_slot
    """
    program, applicant, app, bc, appeal = setup_appeal_pending(
        vetting_user_id="vetting-officer-1"
    )
    headers = make_applicant_headers(applicant["id"])
    version = app_version(app["id"])
    withdrawn = get_success_data(
        api.withdraw_application(app["id"], withdraw_payload(version), headers)
    )
    assert withdrawn["status"] == "WITHDRAWN"
    final_appeal = get_success_data(api.get_appeal(appeal["id"], APPEALS))
    assert final_appeal["status"] == "DECIDED", "withdraw decides the OPEN appeal"
    assert final_appeal["outcome"] == "UPHELD", "the withdraw-driven decision is UPHELD"


# ---------------------------------------------------------------------------
# Queue A — cross_entity_state_dependency
# ---------------------------------------------------------------------------

def test_booking_with_pending_check_keeps_application_in_vetting(api):
    """PRD §3.5: "If the application's background check is already `CLEARED`, the
    booking carries the application from `VETTING` forward to
    `INTERVIEW_SCHEDULED`."

    Design: Difficulty/cross_entity_state_dependency/application_advance_requires_background_check_cleared
    """
    set_clock()
    program = create_program()
    center = create_center()
    slot = create_slot(center["id"], starts_at="2026-06-24T09:00:00Z",
                       ends_at="2026-06-24T09:30:00Z")
    applicant = create_applicant(full_name="Omar Pend")
    headers = make_applicant_headers(applicant["id"])
    app = create_draft_application(applicant["id"])
    get_success_data(api.pay_application(app["id"], pay_payload(7800), headers))
    get_success_data(api.submit_application(app["id"], headers))
    bc = get_success_data(
        api.create_background_check(
            app["id"], background_check_payload(criminal_hits=1), VETTING
        )
    )
    assert bc["status"] == "PENDING", "check is not adjudicated"
    version = app_version(app["id"])
    appt = validate_success(
        api.create_appointment(
            appointment_payload(app["id"], slot["id"], version), headers
        ),
        expected_status=201,
    )
    assert appt["status"] == "CONFIRMED"
    final_app = get_application(app["id"])
    assert final_app["status"] == "VETTING", (
        "booking with a PENDING check does NOT advance to INTERVIEW_SCHEDULED"
    )


def test_complete_requires_accepted_biometrics(api):
    """PRD §3.5: "An `EnrollmentOfficer` completes the interview on a `CONFIRMED`
    appointment, which requires a `BiometricCapture` with status `ACCEPTED` for
    that appointment - absent which the completion is rejected with
    `ERR_BIOMETRICS_NOT_ACCEPTED`."

    Design: Difficulty/cross_entity_state_dependency/interview_complete_requires_accepted_biometrics
    """
    program, applicant, app, center, slot, appt = setup_confirmed_appointment()
    # fingerprint_quality 5 -> REJECTED.
    bio = get_success_data(
        api.create_biometric_capture(
            biometric_payload(appt["id"], fingerprint_quality=5), ENROLLMENT
        )
    )
    assert bio["status"] == "REJECTED"
    resp = api.complete_appointment(appt["id"], ENROLLMENT)
    validate_error(resp, ApiErrorId.ERR_BIOMETRICS_NOT_ACCEPTED.value)
    final_appt = get_success_data(api.get_appointment(appt["id"], ADMIN))
    assert final_appt["status"] == "CONFIRMED", "appointment stays CONFIRMED on rejected biometrics"


def test_booking_with_cleared_check_advances_to_interview_scheduled(api):
    """PRD §3.5: "If the application's background check is already `CLEARED`, the
    booking carries the application from `VETTING` forward to
    `INTERVIEW_SCHEDULED`."

    Design: Difficulty/cross_entity_state_dependency/application_advance_requires_background_check_cleared
    """
    # setup_confirmed_appointment clears the check, books a slot, and asserts the
    # application advanced. Re-confirm the cross-entity coupling: CLEARED -> advance.
    program, applicant, app, center, slot, appt = setup_confirmed_appointment()
    assert appt["status"] == "CONFIRMED"
    final_app = get_application(app["id"])
    assert final_app["status"] == "INTERVIEW_SCHEDULED", (
        "booking with a CLEARED check advances VETTING -> INTERVIEW_SCHEDULED"
    )


def test_complete_succeeds_with_accepted_biometrics(api):
    """PRD §3.5: "Completing the appointment moves it from `CONFIRMED` to
    `COMPLETED`, leaves its slot `BOOKED`, carries the application from
    `INTERVIEW_SCHEDULED` to `INTERVIEW_COMPLETE`."

    Design: Difficulty/cross_entity_state_dependency/interview_complete_requires_accepted_biometrics
    """
    program, applicant, app, center, slot, appt = setup_confirmed_appointment()
    # fingerprint_quality 2 + photo -> ACCEPTED; completion then succeeds.
    bio = get_success_data(
        api.create_biometric_capture(
            biometric_payload(appt["id"], fingerprint_quality=2, photo_captured=True),
            ENROLLMENT,
        )
    )
    assert bio["status"] == "ACCEPTED"
    completed = get_success_data(api.complete_appointment(appt["id"], ENROLLMENT))
    assert completed["status"] == "COMPLETED"
    final_app = get_application(app["id"])
    assert final_app["status"] == "INTERVIEW_COMPLETE"


# ---------------------------------------------------------------------------
# Queue A — compensating_invariant
# ---------------------------------------------------------------------------

def test_full_refund_on_withdraw_returns_fee_paid_to_zero(api):
    """PRD §3.8: "While it is still in `DRAFT` or `SUBMITTED` - before vetting has
    begun - the full `fee_paid_cents` is refunded."

    Design: Difficulty/compensating_invariant/payment_refund_conserves_fee_paid_ledger
    """
    program, applicant, app = setup_submitted_application(pay_amount=7800)
    headers = make_applicant_headers(applicant["id"])
    version = app_version(app["id"])
    withdrawn = get_success_data(
        api.withdraw_application(app["id"], withdraw_payload(version), headers)
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["fee_paid_cents"] == 0, (
        f"full refund of 7800 returns fee_paid_cents to 0, got {withdrawn['fee_paid_cents']}"
    )


def test_book_then_cancel_conserves_slot_occupancy(api):
    """PRD §3.1: "When a booking takes the slot, its `status` becomes `BOOKED` and
    `held_by_appointment_id` records the occupying appointment; when the holding
    appointment is later cancelled or marked a no-show, the slot returns to
    `AVAILABLE` and `held_by_appointment_id` is cleared again."

    Design: Difficulty/compensating_invariant/book_cancel_conserves_slot_occupancy_count
    """
    program, applicant, app, center, slot, appt = setup_confirmed_appointment()
    booked_slot = get_success_data(api.get_slot(slot["id"], ADMIN))
    assert booked_slot["status"] == "BOOKED"
    headers = make_applicant_headers(applicant["id"])
    cancelled = get_success_data(api.cancel_appointment(appt["id"], headers))
    assert cancelled["status"] == "CANCELLED"
    final_slot = get_success_data(api.get_slot(slot["id"], ADMIN))
    assert final_slot["status"] == "AVAILABLE", (
        "cancel compensates the booking; slot returns to AVAILABLE"
    )


def test_refund_writes_fee_transaction_and_decrements_paid(api):
    """PRD §3.8: "When the computed refund is positive, the system writes a
    `FeeTransaction` whose `kind` is `REFUND` for the refundable portion and
    decrements the application's `fee_paid_cents` accordingly."

    Design: Difficulty/compensating_invariant/payment_refund_conserves_fee_paid_ledger
    """
    program, applicant, app = setup_submitted_application(pay_amount=7800)
    headers = make_applicant_headers(applicant["id"])
    version = app_version(app["id"])
    get_success_data(
        api.withdraw_application(app["id"], withdraw_payload(version), headers)
    )
    # Ledger: one PAYMENT 7800 and one REFUND 7800; fee_paid_cents conserved to 0.
    resp = api.list_fee_transactions(app["id"], ADMIN)
    body = resp.json()
    txns = body["data"]
    kinds = sorted(t["kind"] for t in txns)
    assert kinds == ["PAYMENT", "REFUND"], f"expected one PAYMENT + one REFUND, got {kinds}"
    refund = next(t for t in txns if t["kind"] == "REFUND")
    assert refund["amount_cents"] == 7800, "full refund of the 7800 payment"


def test_no_show_compensates_booking_freeing_slot(api):
    """PRD §3.1: "when the holding appointment is later cancelled or marked a
    no-show, the slot returns to `AVAILABLE` and `held_by_appointment_id` is cleared
    again."

    Design: Difficulty/compensating_invariant/book_cancel_conserves_slot_occupancy_count
    """
    program, applicant, app, center, slot, appt = setup_confirmed_appointment(
        slot_overrides={"starts_at": "2026-06-20T09:00:00Z",
                        "ends_at": "2026-06-20T09:30:00Z"}
    )
    booked = get_success_data(api.get_slot(slot["id"], ADMIN))
    assert booked["status"] == "BOOKED"
    # Advance past ends_at, then no-show: the compensating action frees the slot.
    set_clock("2026-06-20T10:00:00Z")
    no_show = get_success_data(api.no_show_appointment(appt["id"], ENROLLMENT))
    assert no_show["status"] == "NO_SHOW"
    final_slot = get_success_data(api.get_slot(slot["id"], ADMIN))
    assert final_slot["status"] == "AVAILABLE", "no-show returns slot to AVAILABLE"


# ---------------------------------------------------------------------------
# Queue B — state_machines section
# ---------------------------------------------------------------------------

def test_submit_already_submitted_rejected(api):
    """PRD §3.2: "Submitting moves the application from `DRAFT` to `SUBMITTED`...
    The application must be in `DRAFT`, or the transition is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/submit_application_already_submitted_invalid_state
    """
    program, applicant, app = setup_submitted_application(pay_amount=7800)
    headers = make_applicant_headers(applicant["id"])
    resp = api.submit_application(app["id"], headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_revoke_expired_ktn_rejected(api):
    """PRD §3.6: "Either operation requires the credential to be `ACTIVE`,
    otherwise `ERR_INVALID_STATE`."

    Design: Corner/state_machines/revoke_superseded_ktn_terminal_lockdown
    """
    program, applicant, app, _center, _slot, _appt, ktn = setup_approved_application()
    # Advance past expiry and expire-sweep.
    set_clock("2031-06-10T00:00:00Z")
    swept = get_success_data(api.expire_sweep_ktn(ktn["id"], ADMIN))
    assert swept["status"] == "EXPIRED"
    resp = api.revoke_ktn(ktn["id"], VETTING)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_no_show_before_window_elapsed_rejected(api):
    """PRD §3.5: "An `EnrollmentOfficer` may mark a `CONFIRMED` appointment as a
    no-show, moving it to `NO_SHOW`, but only once the appointment window has
    elapsed: the logical clock must be at or after the appointment's `ends_at`,
    otherwise the request is rejected with `ERR_APPOINTMENT_NOT_ELAPSED`."

    Design: Corner/state_machines/no_show_before_appointment_elapsed_rejected
    """
    # Clock stays at 2026-06-09, before slot ends_at 2026-06-20T09:30.
    program, applicant, app, center, slot, appt = setup_confirmed_appointment()
    resp = api.no_show_appointment(appt["id"], ENROLLMENT)
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_NOT_ELAPSED.value)


def test_new_application_starts_in_draft(api):
    """PRD §3.2: "A new application is born in `DRAFT` with `fee_due_cents` and
    `fee_paid_cents` both at 0, `adverse_reason` null, and `appeal_count` at 0."

    Design: Corner/state_machines/new_application_starts_in_draft
    """
    program = create_program()
    applicant = create_applicant(full_name="Kim Init")
    headers = make_applicant_headers(applicant["id"])
    app = validate_success(
        api.create_application(
            {"applicant_id": applicant["id"], "program_code": "PRECHECK"}, headers
        ),
        expected_status=201,
    )
    assert app["status"] == "DRAFT"


def test_second_appeal_after_upheld_rejected(api):
    """PRD §3.7: "Filing requires the application to be in `DENIED` (otherwise
    `ERR_INVALID_STATE`) and that no appeal has yet been filed against this denial
    - the `appeal_count` must be below 1, or the filing is rejected with
    `ERR_APPEAL_LIMIT_REACHED`."

    Design: Corner/state_machines/appeal_limit_second_appeal_rejected
    """
    program, applicant, app, bc, appeal = setup_appeal_pending(
        vetting_user_id="vetting-officer-1"
    )
    decider = make_appeals_officer_headers("appeals-officer-9")
    # UPHELD returns application to DENIED, appeal_count stays 1.
    get_success_data(api.decide_appeal(appeal["id"], decide_payload("UPHELD"), decider))
    headers = make_applicant_headers(applicant["id"])
    resp = api.file_appeal(app["id"], appeal_payload(filed_reason="second appeal"), headers)
    validate_error(resp, ApiErrorId.ERR_APPEAL_LIMIT_REACHED.value)


def test_book_released_slot_rejected(api):
    """PRD §3.1: "releasing a slot that is `AVAILABLE` moves it to the terminal
    `RELEASED` state, permanently removing it from the booking pool."
    PRD §3.5: "The target slot must be `AVAILABLE`, or the booking is rejected with
    `ERR_SLOT_NOT_AVAILABLE`."

    Design: Corner/state_machines/slot_release_then_book_invalid_state
    """
    set_clock()
    program = create_program()
    center = create_center()
    slot = create_slot(center["id"])
    get_success_data(api.release_slot(slot["id"], ADMIN))
    applicant = create_applicant(full_name="Moe Rel")
    headers = make_applicant_headers(applicant["id"])
    app = create_draft_application(applicant["id"])
    get_success_data(api.pay_application(app["id"], pay_payload(7800), headers))
    get_success_data(api.submit_application(app["id"], headers))
    get_success_data(
        api.create_background_check(
            app["id"], background_check_payload(criminal_hits=1), VETTING
        )
    )
    get_success_data(api.adjudicate(app["id"], VETTING))
    version = app_version(app["id"])
    resp = api.create_appointment(
        appointment_payload(app["id"], slot["id"], version), headers
    )
    validate_error(resp, ApiErrorId.ERR_SLOT_NOT_AVAILABLE.value)
