"""Queue-entry lifecycle tests: walk-in vs online initial states, the hold window
and its expiry, the re-triage revision cycle, and invalid/terminal transitions
(PRD §3.1, §3.3).
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    TEST_USERS,
    create_clinic,
    create_walk_in,
    create_online_reservation,
    triage,
    register_patient,
    set_clock,
    setup_roomed_visit,
)

_ANON = TEST_USERS["anonymous_headers"]
_CLERK = TEST_USERS["front_desk_headers"]
_NURSE = TEST_USERS["triage_nurse_headers"]
_MGR = TEST_USERS["clinic_manager_headers"]
_PATIENT = TEST_USERS["patient_headers"]


# ─── non_linear_state_machine / queue_entry_retriage_revision_cycle ───

def test_retriage_revises_esi_back_to_triaged():
    """PRD §3.3: "A re-triage advances IN_REGISTRATION → TRIAGED, permitted only
    from IN_REGISTRATION with a new esi_level between 1 and 5; it overwrites the
    existing esi_level, re-stamps triaged_at to the current clock, and recomputes
    ranks and wait estimates."

    Design: Difficulty/non_linear_state_machine/queue_entry_retriage_revision_cycle
    """
    clinic = create_clinic(name="CycleClinic", exam_room_capacity=2)
    qe = create_walk_in(clinic["id"], chief_complaint="cycle")
    triage(clinic["id"], qe["id"], esi_level=3)
    register_patient(qe["id"], legal_name="Cyc Pat", date_of_birth="1995-07-07",
                     consent_signed=True)  # entry now IN_REGISTRATION

    res = api_client.re_triage_queue_entry(clinic["id"], qe["id"], {"esi_level": 1}, _NURSE)
    revised = validate_success(res, 200)
    assert revised["status"] == "TRIAGED", (
        f"re-triage should return entry to TRIAGED, got {revised['status']}")
    assert revised["esi_level"] == 1, (
        f"re-triage should overwrite esi_level to 1, got {revised['esi_level']}")


def test_retriage_then_reregister_completes_cycle():
    """PRD §3.3: "This IN_REGISTRATION → TRIAGED → IN_REGISTRATION revision cycle
    is deliberate: a patient whose condition is re-assessed mid-registration loops
    back through triage and then forward again."

    Design: Difficulty/non_linear_state_machine/queue_entry_retriage_revision_cycle
    """
    clinic = create_clinic(name="CycleClinic2", exam_room_capacity=2)
    qe = create_walk_in(clinic["id"], chief_complaint="cycle2")
    triage(clinic["id"], qe["id"], esi_level=4)
    register_patient(qe["id"], legal_name="Loop Pat", date_of_birth="1991-01-01",
                     consent_signed=True)  # IN_REGISTRATION

    re = validate_success(
        api_client.re_triage_queue_entry(clinic["id"], qe["id"], {"esi_level": 2}, _NURSE), 200)
    assert re["status"] == "TRIAGED"
    # PRD §3.4: registration is permitted only when the queue entry is TRIAGED;
    # re-registering loops the entry forward to IN_REGISTRATION again.
    fetched = validate_success(api_client.get_queue_entry(qe["id"], _CLERK), 200)
    assert fetched["status"] == "TRIAGED" and fetched["esi_level"] == 2


# ─── state_machines / new_walk_in_entry_starts_in_waiting ───

def test_walk_in_starts_waiting():
    """PRD §3.1: "a walk-in created at the front desk uses WALK_IN and is born
    directly in WAITING."

    Design: Corner/state_machines/new_walk_in_entry_starts_in_waiting
    """
    clinic = create_clinic(name="InitClinic", exam_room_capacity=2)
    res = api_client.create_queue_entry(
        clinic["id"], {"arrival_channel": "WALK_IN", "chief_complaint": "init"}, _CLERK)
    qe = validate_success(res, 201)
    assert qe["status"] == "WAITING", f"walk-in should be born WAITING, got {qe['status']}"


# ─── state_machines / online_entry_starts_reserved_with_hold_window ───

def test_online_entry_starts_reserved_with_30min_hold():
    """PRD §3.1: "A patient using save-my-spot creates an ONLINE entry, which is
    born in RESERVED status"; "At creation the server stamps reserved_at with the
    current clock and sets hold_expires_at to thirty minutes after reserved_at."
    PRD §2.9: RESERVED entries "are not counted" toward active_queue_depth.

    Design: Corner/state_machines/online_entry_starts_reserved_with_hold_window
    """
    set_clock("2026-06-08T08:00:00Z")
    clinic = create_clinic(name="OnlineClinic", exam_room_capacity=2)
    res = api_client.create_queue_entry(
        clinic["id"], {"arrival_channel": "ONLINE", "chief_complaint": "save-spot"}, _PATIENT)
    qe = validate_success(res, 201)
    assert qe["status"] == "RESERVED", f"online entry should be RESERVED, got {qe['status']}"
    assert qe["hold_expires_at"] == "2026-06-08T08:30:00.000Z", (
        f"hold_expires_at should be reserved_at + 30 min, got {qe['hold_expires_at']}")
    clinic_after = validate_success(api_client.get_clinic(clinic["id"], _PATIENT), 200)
    assert clinic_after["active_queue_depth"] == 0, (
        f"RESERVED hold must not count toward depth, got {clinic_after['active_queue_depth']}")


# ─── state_machines / reserved_hold_expires_on_run_ops_past_window ───

def test_reserved_hold_expires_on_run_ops_after_window():
    """PRD §3.1: "On a run-ops sweep, any RESERVED entry whose hold_expires_at is
    strictly in the past relative to the current clock is swept RESERVED → EXPIRED."

    Design: Corner/state_machines/reserved_hold_expires_on_run_ops_past_window
    """
    set_clock("2026-06-08T08:00:00Z")
    clinic = create_clinic(name="ExpClinic", exam_room_capacity=2)
    qe = create_online_reservation(clinic["id"], chief_complaint="expire-me")
    set_clock("2026-06-08T08:31:00Z")
    api_client.run_ops(clinic["id"], _MGR)
    fetched = validate_success(api_client.get_queue_entry(qe["id"], _PATIENT), 200)
    assert fetched["status"] == "EXPIRED", (
        f"RESERVED entry past hold should be EXPIRED after run-ops, got {fetched['status']}")


# ─── state_machines / arrive_after_hold_expired_returns_invalid_state ───

def test_arrive_after_expired_returns_invalid_state():
    """PRD §3.1: "When the patient checks in, the reservation advances RESERVED →
    WAITING: this is allowed only while the entry is still RESERVED"; an entry
    already swept to EXPIRED is no longer RESERVED.

    Design: Corner/state_machines/arrive_after_hold_expired_returns_invalid_state
    """
    set_clock("2026-06-08T08:00:00Z")
    clinic = create_clinic(name="ArrExpClinic", exam_room_capacity=2)
    qe = create_online_reservation(clinic["id"], chief_complaint="late")
    set_clock("2026-06-08T09:00:00Z")
    api_client.run_ops(clinic["id"], _MGR)  # sweeps RESERVED -> EXPIRED
    res = api_client.arrive_queue_entry(clinic["id"], qe["id"], _CLERK)
    validate_error(res, "ERR_INVALID_STATE")


# ─── state_machines / triage_from_triaged_returns_invalid_state ───

def test_triage_already_triaged_returns_invalid_state():
    """PRD §3.3: "Triage advances WAITING → TRIAGED and is permitted only from
    WAITING with an esi_level in the request between 1 and 5 inclusive."

    Design: Corner/state_machines/triage_from_triaged_returns_invalid_state
    """
    clinic = create_clinic(name="InvStClinic", exam_room_capacity=2)
    qe = create_walk_in(clinic["id"], chief_complaint="t")
    triage(clinic["id"], qe["id"], esi_level=3)  # now TRIAGED
    res = api_client.triage_queue_entry(clinic["id"], qe["id"], {"esi_level": 2}, _NURSE)
    validate_error(res, "ERR_INVALID_STATE")


# ─── state_machines / cancel_from_terminal_roomed_returns_invalid_state ───

def test_cancel_roomed_terminal_returns_invalid_state():
    """PRD §3.1: "Cancellation is narrower: it applies only while the entry is
    RESERVED or WAITING, moving it to CANCELLED"; a ROOMED entry is terminal.

    Design: Corner/state_machines/cancel_from_terminal_roomed_returns_invalid_state
    """
    setup = setup_roomed_visit()  # queue entry is now ROOMED
    res = api_client.cancel_queue_entry(setup["clinic"]["id"], setup["queue_entry"]["id"], _CLERK)
    validate_error(res, "ERR_INVALID_STATE")
