"""State-machine behaviors: the session's parallel clinical/billing axes, the
order revision cycle, lab lifecycle, machine maintenance, idempotency rejection,
and cross-entity state gating on check-in and transport completion.

Difficulty queue (A): non_linear_state_machine, cross_entity_state_dependency.
Corner queue (B): state_machines section.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_bookable_scenario, book_session, book_and_check_in, book_and_complete,
    book_with_confirmed_transport,
    create_order_payload, create_lab_order_payload, create_transport_trip_payload,
    TEST_USERS,
)

SCHED = TEST_USERS["scheduler_headers"]
NEPH = TEST_USERS["nephrologist_headers"]
ADMIN = TEST_USERS["clinic_admin_headers"]
BILL = TEST_USERS["billing_clerk_headers"]


# ─── non_linear_state_machine / session_parallel_clinical_and_billing ─────
def test_completed_session_starts_unbilled(api):
    """PRD §3.6: "The session's `billing_status` is unaffected by completion and
    remains `UNBILLED`, because the billing axis evolves independently."

    Design: Difficulty/non_linear_state_machine/session_parallel_clinical_and_billing_axes
    """
    scenario = setup_bookable_scenario(dialyzer_reuse_limit=99, coinsurance_pct=0.0)
    completed = book_and_complete(scenario)
    assert completed["clinical_status"] == "COMPLETED"
    assert completed["billing_status"] == "UNBILLED"


def test_billing_advances_without_touching_clinical_axis(api):
    """PRD §3.10: "Billing a session moves it `UNBILLED → BILLED`, permitted only
    when the session's `clinical_status` is `COMPLETED`"
    PRD §3.10: "The billing axis of a treatment session evolves independently of
    its clinical axis"

    Design: Difficulty/non_linear_state_machine/session_parallel_clinical_and_billing_axes
    """
    scenario = setup_bookable_scenario(dialyzer_reuse_limit=99, coinsurance_pct=0.0)
    completed = book_and_complete(scenario)
    billed = validate_success(api.bill_session(completed["id"], BILL), 200)
    assert billed["billing_status"] == "BILLED"
    assert billed["clinical_status"] == "COMPLETED"


# ─── non_linear_state_machine / order_cyclic_active_revision_loop ─────────
def test_order_revision_first_loop_increments_revision_no(api):
    """PRD §3.4: "On activation the order's `revision_no` is initialized to 1."
    PRD §3.4: "Committing a revision applies any submitted changes to `modality`,
    `epo_units`, `iron_ordered`, and `sessions_per_week`, and increments
    `revision_no` by 1."

    Design: Difficulty/non_linear_state_machine/order_cyclic_active_revision_loop
    """
    clinic = get_success_data(api.create_clinic({"name": "CycClinic"}, ADMIN))
    patient = get_success_data(api.create_patient(
        {"clinic_id": clinic["id"], "mrn": "CY", "full_name": "Cyc Patient"}, SCHED))
    order = get_success_data(api.create_order(
        create_order_payload(patient["id"]), NEPH))
    activated = get_success_data(api.activate_order(order["id"], NEPH))
    assert activated["revision_no"] == 1
    api.open_revision(order["id"], NEPH)
    committed = validate_success(api.commit_revision(order["id"], NEPH, {"epo_units": 1000}), 200)
    assert committed["revision_no"] == 2
    assert committed["status"] == "ACTIVE"


def test_order_revision_second_loop_increments_again(api):
    """PRD §3.4: "From `ACTIVE`, the nephrologist may open a revision, moving it
    `ACTIVE → UNDER_REVISION`, and then commit that revision, moving it
    `UNDER_REVISION → ACTIVE`. ... This open-then-commit cycle may repeat."

    Design: Difficulty/non_linear_state_machine/order_cyclic_active_revision_loop
    """
    clinic = get_success_data(api.create_clinic({"name": "CycClinic2"}, ADMIN))
    patient = get_success_data(api.create_patient(
        {"clinic_id": clinic["id"], "mrn": "CY2", "full_name": "Cyc Two"}, SCHED))
    order = get_success_data(api.create_order(
        create_order_payload(patient["id"]), NEPH))
    api.activate_order(order["id"], NEPH)
    api.open_revision(order["id"], NEPH)
    api.commit_revision(order["id"], NEPH, {"epo_units": 1000})  # rev 2
    api.open_revision(order["id"], NEPH)
    committed = validate_success(api.commit_revision(order["id"], NEPH, {"iron_ordered": True}), 200)
    assert committed["revision_no"] == 3
    assert committed["status"] == "ACTIVE"


# ─── cross_entity_state_dependency / session_checkin_requires_machine ─────
def test_check_in_blocked_when_machine_in_maintenance(api):
    """PRD §3.6: "Checking in moves the session `BOOKED → CHECKED_IN`, but only
    when the station's bound machine is `AVAILABLE` (else `ERR_MACHINE_UNAVAILABLE`)"

    Design: Difficulty/cross_entity_state_dependency/session_checkin_requires_machine_available
    """
    scenario = setup_bookable_scenario(dialyzer_reuse_limit=99, coinsurance_pct=0.0)
    session = book_session(scenario)
    api.start_maintenance(scenario["machine"]["id"], ADMIN)
    res = api.check_in_session(session["id"], SCHED)
    validate_error(res, "ERR_MACHINE_UNAVAILABLE")
    after = validate_success(api.get_session(session["id"], SCHED), 200)
    assert after["clinical_status"] == "BOOKED"


def test_check_in_succeeds_when_machine_available(api):
    """PRD §3.6: "Checking in moves the session `BOOKED → CHECKED_IN`, but only
    when the station's bound machine is `AVAILABLE` ... and the station itself is
    `ACTIVE` (else `ERR_STATION_OFFLINE`)."

    Design: Difficulty/cross_entity_state_dependency/session_checkin_requires_machine_available
    """
    scenario = setup_bookable_scenario(dialyzer_reuse_limit=99, coinsurance_pct=0.0)
    session = book_session(scenario)
    checked = validate_success(api.check_in_session(session["id"], SCHED), 200)
    assert checked["clinical_status"] == "CHECKED_IN"


# ─── cross_entity_state_dependency / transport_complete_requires_session ──
def test_transport_complete_blocked_while_session_not_completed(api):
    """PRD §3.8: "Completing a trip moves it `CONFIRMED → COMPLETED` (terminal),
    permitted only when the owning session's `clinical_status` is `COMPLETED`,
    else `ERR_SESSION_NOT_COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/transport_complete_requires_session_completed
    """
    scenario = setup_bookable_scenario(dialyzer_reuse_limit=99, coinsurance_pct=0.0)
    session, trip = book_with_confirmed_transport(scenario, miles=5, direction="OUTBOUND")
    api.check_in_session(session["id"], SCHED)  # CHECKED_IN, not COMPLETED
    res = api.complete_transport_trip(trip["id"], SCHED)
    validate_error(res, "ERR_SESSION_NOT_COMPLETED")
    after = validate_success(api.get_transport_trip(trip["id"], SCHED), 200)
    assert after["status"] == "CONFIRMED"


def test_transport_complete_succeeds_after_session_completed(api):
    """PRD §3.8: "Completing a trip moves it `CONFIRMED → COMPLETED` (terminal),
    permitted only when the owning session's `clinical_status` is `COMPLETED`"

    Design: Difficulty/cross_entity_state_dependency/transport_complete_requires_session_completed
    """
    scenario = setup_bookable_scenario(dialyzer_reuse_limit=99, coinsurance_pct=0.0)
    session, trip = book_with_confirmed_transport(scenario, miles=5, direction="OUTBOUND")
    api.check_in_session(session["id"], SCHED)
    api.complete_session(session["id"], SCHED)
    completed = validate_success(api.complete_transport_trip(trip["id"], SCHED), 200)
    assert completed["status"] == "COMPLETED"


# ─── Corner: state_machines / cancel_session_from_cancelled_invalid_state ─
def test_cancel_already_cancelled_session_rejected(api):
    """PRD §2.9: "the target resource being in the correct state for the requested
    transition, else the relevant state error such as `ERR_INVALID_STATE`"
    PRD §3.6: "A booked session may instead be cancelled outright, moving it
    `BOOKED → CANCELLED` (terminal)"

    Design: Corner/state_machines/cancel_session_from_cancelled_invalid_state
    """
    scenario = setup_bookable_scenario(dialyzer_reuse_limit=99, coinsurance_pct=0.0)
    session = book_session(scenario)
    api.cancel_session(session["id"], SCHED)
    res = api.cancel_session(session["id"], SCHED)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner: state_machines / complete_session_from_booked_requires_checkin ─
def test_complete_session_from_booked_rejected(api):
    """PRD §3.6: "Completing the session moves it `CHECKED_IN → COMPLETED`, which
    is terminal on the clinical axis."

    Design: Corner/state_machines/complete_session_from_booked_requires_checked_in
    """
    scenario = setup_bookable_scenario(dialyzer_reuse_limit=99, coinsurance_pct=0.0)
    session = book_session(scenario)
    res = api.complete_session(session["id"], SCHED)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner: state_machines / activate_second_order_blocked ───────────────
def test_activating_second_order_blocked_by_active_one(api):
    """PRD §3.4: "Activating an order moves it `DRAFT → ACTIVE`, but is rejected
    with `ERR_ACTIVE_ORDER_EXISTS` if the patient already has another order in
    `ACTIVE`."

    Design: Corner/state_machines/activate_second_order_blocked_by_active_one
    """
    clinic = get_success_data(api.create_clinic({"name": "ActClinic"}, ADMIN))
    patient = get_success_data(api.create_patient(
        {"clinic_id": clinic["id"], "mrn": "AC1", "full_name": "Act One"}, SCHED))
    o1 = get_success_data(api.create_order(create_order_payload(patient["id"]), NEPH))
    api.activate_order(o1["id"], NEPH)
    o2 = get_success_data(api.create_order(
        create_order_payload(patient["id"], modality="PERITONEAL"), NEPH))
    res = api.activate_order(o2["id"], NEPH)
    validate_error(res, "ERR_ACTIVE_ORDER_EXISTS")


# ─── Corner: state_machines / lab_order_initial_state_scheduled ───────────
def test_new_lab_order_starts_scheduled(api):
    """PRD §3.9: "A lab order is created `SCHEDULED`"

    Design: Corner/state_machines/lab_order_initial_state_scheduled
    """
    clinic = get_success_data(api.create_clinic({"name": "LabClinic"}, ADMIN))
    patient = get_success_data(api.create_patient(
        {"clinic_id": clinic["id"], "mrn": "LB1", "full_name": "Lab One"}, SCHED))
    lab = validate_success(api.create_lab_order(
        create_lab_order_payload(patient["id"], panel="MONTHLY_CHEM",
                                 scheduled_date="2026-06-15"), NEPH), 201)
    assert lab["status"] == "SCHEDULED"


# ─── Corner: state_machines / collect_lab_terminal_lockdown ───────────────
def test_cancel_collected_lab_rejected(api):
    """PRD §3.9: "a `Scheduler` marks it collected, moving it
    `SCHEDULED → COLLECTED`; or either a `Scheduler` or a `Nephrologist` cancels
    it, moving it `SCHEDULED → CANCELLED`."
    PRD §2.9: "the target resource being in the correct state for the requested
    transition, else the relevant state error such as `ERR_INVALID_STATE`"

    Design: Corner/state_machines/collect_lab_terminal_lockdown
    """
    clinic = get_success_data(api.create_clinic({"name": "LabClinic2"}, ADMIN))
    patient = get_success_data(api.create_patient(
        {"clinic_id": clinic["id"], "mrn": "LB2", "full_name": "Lab Two"}, SCHED))
    lab = get_success_data(api.create_lab_order(
        create_lab_order_payload(patient["id"], panel="CBC", scheduled_date="2026-06-15"), SCHED))
    api.collect_lab_order(lab["id"], SCHED)
    res = api.cancel_lab_order(lab["id"], SCHED)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner: state_machines / check_in_idempotency_second_call_rejected ───
def test_double_check_in_rejected(api):
    """PRD §3.6: "Checking in moves the session `BOOKED → CHECKED_IN`"
    PRD §2.9: "the target resource being in the correct state for the requested
    transition, else the relevant state error such as `ERR_INVALID_STATE`"

    Design: Corner/state_machines/check_in_idempotency_second_call_rejected
    """
    scenario = setup_bookable_scenario(dialyzer_reuse_limit=99, coinsurance_pct=0.0)
    session = book_and_check_in(scenario)
    res = api.check_in_session(session["id"], SCHED)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner: state_machines / machine_maintenance_disinfect_resets_count ──
def test_complete_maintenance_with_disinfect_resets_reuse_count(api):
    """PRD §3.2: "Completing maintenance moves it `IN_MAINTENANCE → AVAILABLE`;
    the request may carry a `disinfect` flag, and when `disinfect` is true the
    machine's `dialyzer_reuse_count` is reset to 0, modeling a fresh dialyzer
    mount after disinfection."

    Design: Corner/state_machines/machine_maintenance_cycle_disinfect_resets_count
    """
    scenario = setup_bookable_scenario(dialyzer_reuse_limit=12, coinsurance_pct=0.0)
    book_and_complete(scenario)  # raises machine reuse count to 1
    machine_id = scenario["machine"]["id"]
    before = validate_success(api.get_machine(machine_id, ADMIN), 200)
    assert before["dialyzer_reuse_count"] == 1
    api.start_maintenance(machine_id, ADMIN)
    done = validate_success(api.complete_maintenance(machine_id, ADMIN, {"disinfect": True}), 200)
    assert done["dialyzer_reuse_count"] == 0
    assert done["status"] == "AVAILABLE"
