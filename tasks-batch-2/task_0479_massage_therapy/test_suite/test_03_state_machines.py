"""Parallel scheduling/settlement axes, the SOAP-note amendment loop, and other transitions.

Covers difficulty queue A instances on the appointment's parallel axes and the SOAP-note
revision cycle, plus corner queue B state-machine claims.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    bookable_scenario,
    book_appointment,
    book_with_finalized_note,
    drive_to_completed,
    create_draft_note,
    drive_to_paid,
    create_plan,
    create_package,
    make_therapist_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
FRONT = TEST_USERS["front_desk_headers"]


def test_appointment_parallel_axes_independent(api):
    """PRD §3.5: "A successful check-in advances scheduling_status from SCHEDULED to
    CHECKED_IN." PRD §3.5: "Completion advances scheduling_status from CHECKED_IN to
    COMPLETED." PRD §3.8: "Pricing concludes by setting settlement_status to PRICED."

    After check-in -> complete -> price, scheduling_status is COMPLETED while settlement_status
    has moved UNSETTLED -> PRICED on its own axis.

    Design: Difficulty/non_linear_state_machine/appointment_parallel_axes_independent
    """
    from test_helpers import set_clock
    set_clock("2026-03-02T08:00:00Z")
    scn = bookable_scenario()
    appt, _ = drive_to_completed(scn, start_at="2026-03-02T09:00:00Z", duration_minutes=60, payer="CASH")
    priced = validate_success(api.price_appointment(appt["id"], FRONT))
    assert priced["scheduling_status"] == "COMPLETED"
    assert priced["settlement_status"] == "PRICED"
    assert priced["service_charge_cents"] == 12000


def test_settlement_stays_unsettled_through_scheduling_advance(api):
    """PRD §3.4: "A booked appointment begins with scheduling_status SCHEDULED and
    settlement_status UNSETTLED." PRD §3.8: "Pricing is allowed only while settlement_status is
    UNSETTLED and only while scheduling_status is COMPLETED."

    Scheduling advances SCHEDULED -> CHECKED_IN -> COMPLETED while settlement_status remains
    UNSETTLED until pricing — the two axes are independent.

    Design: Difficulty/non_linear_state_machine/appointment_parallel_axes_independent
    """
    from test_helpers import set_clock
    set_clock("2026-03-02T08:00:00Z")
    scn = bookable_scenario()
    appt, _ = drive_to_completed(scn, start_at="2026-03-02T09:00:00Z", duration_minutes=60, payer="CASH")
    fetched = validate_success(api.get_appointment(appt["id"], FRONT))
    assert fetched["scheduling_status"] == "COMPLETED"
    assert fetched["settlement_status"] == "UNSETTLED"


def test_soap_note_amendment_loop_to_amended(api):
    """PRD §3.5: "The first finalize of a never-before-finalized note moves it to FINALIZED;
    finalizing a note that had previously been finalized and then reopened moves it instead to
    AMENDED." PRD §3.5: "A finalized note may be reopened by the therapist back to DRAFT for
    amendment, but only while its linked appointment's settlement_status is not yet PAID."

    DRAFT -> FINALIZED -> reopen(DRAFT) -> finalize(AMENDED): each transition bumps version,
    landing version 4 at AMENDED.

    Design: Difficulty/non_linear_state_machine/soap_note_amendment_loop_cycle
    """
    from test_helpers import set_clock
    set_clock("2026-03-02T08:00:00Z")
    scn = bookable_scenario()
    appt = book_appointment(scn, start_at="2026-03-02T09:00:00Z", duration_minutes=60, payer="CASH")
    t_id = scn["therapist"]["id"]
    th = make_therapist_headers(t_id)
    note = create_draft_note(appt["id"], t_id)
    validate_success(api.finalize_soap_note(note["id"], th))
    validate_success(api.reopen_soap_note(note["id"], th))
    amended = validate_success(api.finalize_soap_note(note["id"], th))
    assert amended["note_status"] == "AMENDED", \
        f"re-finalize after reopen should be AMENDED, got {amended['note_status']}"
    assert amended["version"] == 4, f"version should be 4 after the loop, got {amended['version']}"


def test_reopen_returns_finalized_note_to_draft(api):
    """PRD §3.5: "A finalized note may be reopened by the therapist back to DRAFT for
    amendment." PRD §3.5: "When the note is re-finalized from that reopened DRAFT state — the
    AMENDED outcome."

    Reopening a FINALIZED note returns it to DRAFT (the prior state in the cycle) before
    re-finalizing.

    Design: Difficulty/non_linear_state_machine/soap_note_amendment_loop_cycle
    """
    from test_helpers import set_clock
    set_clock("2026-03-02T08:00:00Z")
    scn = bookable_scenario()
    appt = book_appointment(scn, start_at="2026-03-02T09:00:00Z", duration_minutes=60, payer="CASH")
    t_id = scn["therapist"]["id"]
    th = make_therapist_headers(t_id)
    note = create_draft_note(appt["id"], t_id)
    finalized = validate_success(api.finalize_soap_note(note["id"], th))
    assert finalized["note_status"] == "FINALIZED"
    reopened = validate_success(api.reopen_soap_note(note["id"], th))
    assert reopened["note_status"] == "DRAFT", \
        f"reopen should return the note to DRAFT, got {reopened['note_status']}"


# ---------------------------------------------------------------------------
# Corner queue B — state_machines
# ---------------------------------------------------------------------------
def test_cancel_already_cancelled_invalid_state(api):
    """PRD §3.6: "A cancellation ... is allowed while the session is either SCHEDULED or
    CHECKED_IN." PRD §2.10: "then the state-machine precondition that the target is in a state
    from which the transition is legal (ERR_INVALID_STATE)."

    A second cancel on an already-CANCELLED appointment returns ERR_INVALID_STATE.

    Design: Corner/state_machines/cancel_already_cancelled_invalid_state
    """
    scn = bookable_scenario()
    appt = book_appointment(scn, start_at="2026-01-05T09:00:00Z", duration_minutes=60, payer="CASH")
    validate_success(api.cancel_appointment(appt["id"], {"cancel_reason": "CLIENT_REQUEST"}, FRONT))
    validate_error(api.cancel_appointment(appt["id"], {"cancel_reason": "CLIENT_REQUEST"}, FRONT),
                   ApiErrorId.ERR_INVALID_STATE.value)
    fetched = validate_success(api.get_appointment(appt["id"], FRONT))
    assert fetched["scheduling_status"] == "CANCELLED"


def test_appointment_initial_states(api):
    """PRD §3.4: "A booked appointment begins with scheduling_status SCHEDULED and
    settlement_status UNSETTLED."

    Design: Corner/state_machines/appointment_initial_states
    """
    scn = bookable_scenario()
    appt = book_appointment(scn, start_at="2026-01-05T09:00:00Z", duration_minutes=60, payer="CASH")
    assert appt["scheduling_status"] == "SCHEDULED"
    assert appt["settlement_status"] == "UNSETTLED"


def test_terminal_completed_cannot_cancel(api):
    """PRD §3.6: "A cancellation ... is allowed while the session is either SCHEDULED or
    CHECKED_IN." PRD §2.10: "a wrong-state transition is reported before the booking's safety
    and fiscal gates are even consulted."

    A COMPLETED appointment is terminal on the scheduling axis; cancel returns ERR_INVALID_STATE.

    Design: Corner/state_machines/terminal_completed_cannot_cancel
    """
    from test_helpers import set_clock
    set_clock("2026-01-05T07:00:00Z")
    scn = bookable_scenario()
    appt, _ = drive_to_completed(scn, start_at="2026-01-05T09:00:00Z", duration_minutes=60, payer="CASH")
    validate_error(api.cancel_appointment(appt["id"], {"cancel_reason": "CLIENT_REQUEST"}, FRONT),
                   ApiErrorId.ERR_INVALID_STATE.value)
    fetched = validate_success(api.get_appointment(appt["id"], FRONT))
    assert fetched["scheduling_status"] == "COMPLETED"


def test_package_resume_from_active_invalid(api):
    """PRD §3.10: "A suspended package may be resumed back to ACTIVE." PRD §2.10: "the
    state-machine precondition that the target is in a state from which the transition is legal
    (ERR_INVALID_STATE)."

    Resume on an ACTIVE (not SUSPENDED) package returns ERR_INVALID_STATE.

    Design: Corner/state_machines/package_resume_from_active_invalid
    """
    plan = create_plan(name="ResPlan", monthly_fee_cents=9000, included_sessions=1)
    client = validate_success(api.create_client(
        {"full_name": "Res Cli", "email": "rescli@example.com"}, FRONT), expected_status=201)
    pkg = create_package(client["id"], plan["id"])
    validate_error(api.resume_package(pkg["id"], ADMIN), ApiErrorId.ERR_INVALID_STATE.value)
    fetched = validate_success(api.get_package(pkg["id"], ADMIN))
    assert fetched["package_status"] == "ACTIVE"


def test_package_suspend_resume_cycle(api):
    """PRD §3.10: "A package may be suspended by a PracticeAdmin while ACTIVE, freezing its
    credits without forfeiting them; a suspended package keeps its credit_balance_sessions but
    cannot be redeemed and is skipped by renewal. A suspended package may be resumed back to
    ACTIVE."

    Suspend then resume returns the package to ACTIVE with credit_balance_sessions unchanged.

    Design: Corner/state_machines/package_suspend_resume_cycle
    """
    plan = create_plan(name="CycPlan", monthly_fee_cents=9000, included_sessions=1)
    client = validate_success(api.create_client(
        {"full_name": "Cyc Cli", "email": "cyccli@example.com"}, FRONT), expected_status=201)
    pkg = create_package(client["id"], plan["id"])
    assert pkg["credit_balance_sessions"] == 1
    validate_success(api.suspend_package(pkg["id"], ADMIN))
    resumed = validate_success(api.resume_package(pkg["id"], ADMIN))
    assert resumed["package_status"] == "ACTIVE"
    assert resumed["credit_balance_sessions"] == 1


def test_intake_sign_supersedes_prior(api):
    """PRD §3.2: "Signing a new intake supersedes any prior intake the client already had in
    ACTIVE status: that earlier intake transitions to SUPERSEDED."

    Design: Corner/state_machines/intake_sign_supersedes_prior
    """
    from test_helpers import create_intake_payload
    client = validate_success(api.create_client(
        {"full_name": "Sup Cli", "email": "supcli@example.com"}, FRONT), expected_status=201)
    itk1 = validate_success(api.create_intake(create_intake_payload(client["id"]), FRONT), expected_status=201)
    validate_success(api.sign_intake(itk1["id"], FRONT))
    itk2 = validate_success(api.create_intake(
        create_intake_payload(client["id"], expires_at="2027-12-31T00:00:00Z"), FRONT), expected_status=201)
    validate_success(api.sign_intake(itk2["id"], FRONT))
    fetched1 = validate_success(api.get_intake(itk1["id"], FRONT))
    fetched2 = validate_success(api.get_intake(itk2["id"], FRONT))
    assert fetched1["intake_status"] == "SUPERSEDED"
    assert fetched2["intake_status"] == "ACTIVE"


def test_superbill_void_transition(api):
    """PRD §3.11: "A superbill may later be voided for claim correction or rebill — permitted
    only while it is ISSUED — which moves superbill_status to VOID."

    Design: Corner/state_machines/superbill_void_transition
    """
    from test_helpers import set_clock, create_superbill_payload
    set_clock("2026-01-05T07:00:00Z")
    scn = bookable_scenario(client_overrides={"hsa_balance_cents": 0})
    appt, _ = drive_to_paid(scn, gratuity_cents=0,
                            start_at="2026-01-05T09:00:00Z", duration_minutes=60, payer="CASH")
    sb = validate_success(api.create_superbill(create_superbill_payload(appt["id"], cpt_code="97140"), FRONT), expected_status=201)
    voided = validate_success(api.void_superbill(sb["id"], FRONT))
    assert voided["superbill_status"] == "VOID"
    assert voided["version"] == 2
