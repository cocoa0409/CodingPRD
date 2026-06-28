"""State-machine corner cases: precondition enforcement, invalid transitions,
initial state, terminal lockdown, guarded transitions, compensations, and
auto-transitions.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_field_tech_headers,
    create_active_contract_with_system,
    setup_active_system_with_tech,
    create_dispatched_emergency,
    create_quoted_install,
    create_equipment_on_system,
    create_completed_visit,
    TEST_USERS,
)
from test_helpers.fixtures import create_contract, create_technician
from test_helpers import factories as f

AM = TEST_USERS["account_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]


def test_activate_draft_contract_with_no_system_rejected(api):
    """PRD §3.1: "Activating a DRAFT contract requires that it already have at
    least one SystemProfile; an attempt to activate a contract that has no system
    is rejected with ERR_NO_SYSTEM_ON_CONTRACT".

    Design: Corner/state_machines/activate_draft_contract_with_no_system_returns_invalid
    """
    contract = create_contract(customer_user_id="owner-1")
    resp = api.activate_contract(contract["id"], AM)
    validate_error(resp, ApiErrorId.ERR_NO_SYSTEM_ON_CONTRACT)


def test_cancel_completed_visit_is_invalid_transition(api):
    """PRD §3.3: "A Dispatcher may cancel a SCHEDULED visit, moving it
    SCHEDULED → CANCELLED".
    PRD §3.12: "whether the target entity is in a state from which the requested
    transition is defined (ERR_INVALID_STATE)".

    Cancel is only defined from SCHEDULED; cancelling a COMPLETED visit is
    rejected with ERR_INVALID_STATE.

    Design: Corner/state_machines/cancel_completed_visit_invalid_transition
    """
    base = create_completed_visit(service_tier="BASIC", tech_user_id="tech-1",
                                  labor_minutes=30,
                                  scheduled_start="2026-02-21T09:00:00Z",
                                  scheduled_end="2026-02-21T10:00:00Z")
    resp = api.cancel_visit(base["visit"]["id"], DISP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_new_visit_initial_state_is_scheduled(api):
    """PRD §3.3: "A visit's status runs SCHEDULED, IN_PROGRESS, COMPLETED,
    DISPUTED, and CANCELLED ... A booked visit holds labor_minutes ..., a computed
    total_cents, and an invoice_id back-reference that is null until completion."

    Design: Corner/state_machines/new_visit_initial_state_scheduled
    """
    base = setup_active_system_with_tech(service_tier="BASIC", tech_user_id="tech-1",
                                         nominal_volume_l=200)
    resp = api.create_visit(
        f.create_visit_payload(base["system"]["id"], base["technician"]["id"],
                               base["system"]["version"],
                               scheduled_start="2026-02-22T09:00:00Z",
                               scheduled_end="2026-02-22T10:00:00Z"),
        DISP)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SCHEDULED"
    assert data["total_cents"] == 0
    assert data["invoice_id"] is None


def test_terminated_contract_rejects_further_transitions(api):
    """PRD §3.1: "A new contract starts in DRAFT with a status lifecycle of DRAFT,
    ACTIVE, SUSPENDED, and the terminal TERMINATED."
    PRD §3.12: "whether the target entity is in a state from which the requested
    transition is defined (ERR_INVALID_STATE)".

    Design: Corner/state_machines/terminated_contract_no_further_transitions
    """
    base = create_active_contract_with_system(service_tier="BASIC",
                                              customer_user_id="owner-1")
    contract_id = base["contract"]["id"]
    validate_success(api.terminate_contract(contract_id, AM))
    resp = api.suspend_contract(contract_id, AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_commission_blocked_by_open_install(api):
    """PRD §3.1: "It is additionally blocked if any InstallProject for this system
    is still open — that is, in QUOTED, APPROVED, or IN_BUILD — in which case the
    request is rejected with ERR_OPEN_INSTALL_BLOCKS_COMMISSION".

    Design: Corner/state_machines/commission_blocked_by_open_install
    """
    base = create_quoted_install(service_tier="PLUS", customer_user_id="owner-1",
                                 activate_contract=True)
    # The system is PROVISIONING with a QUOTED install; commissioning is blocked.
    resp = api.commission_system(base["system"]["id"], AM)
    validate_error(resp, ApiErrorId.ERR_OPEN_INSTALL_BLOCKS_COMMISSION)


def test_reactivate_suspended_with_balance_rejected(api):
    """PRD §3.1: "reactivation requires account_balance_cents to be exactly zero,
    and a non-zero balance is rejected with ERR_BALANCE_OUTSTANDING."

    Design: Corner/state_machines/reactivate_suspended_with_outstanding_balance_rejected
    """
    base = setup_active_system_with_tech(service_tier="BASIC", tech_user_id="tech-1",
                                         nominal_volume_l=200)
    contract_id = base["contract"]["id"]
    system_id = base["system"]["id"]
    tech_headers = make_field_tech_headers("tech-1")

    visit = validate_success(api.create_visit(
        f.create_visit_payload(system_id, base["technician"]["id"], base["system"]["version"],
                               scheduled_start="2026-02-23T09:00:00Z",
                               scheduled_end="2026-02-23T10:00:00Z"),
        DISP), expected_status=201)
    validate_success(api.start_visit(visit["id"], tech_headers))
    validate_success(api.complete_visit(visit["id"], {"labor_minutes": 30}, tech_headers))
    validate_success(api.suspend_contract(contract_id, AM))

    resp = api.activate_contract(contract_id, AM)
    validate_error(resp, ApiErrorId.ERR_BALANCE_OUTSTANDING)


def test_terminate_contract_blocked_by_in_flight_visit(api):
    """PRD §3.1: "Terminating a contract ... is blocked when any ServiceVisit on
    this contract's systems is SCHEDULED or IN_PROGRESS, in which case the request
    is rejected with ERR_VISIT_IN_FLIGHT."

    Design: Corner/state_machines/terminate_contract_blocked_by_in_flight_visit
    """
    base = setup_active_system_with_tech(service_tier="BASIC", tech_user_id="tech-1",
                                         nominal_volume_l=200)
    contract_id = base["contract"]["id"]
    validate_success(api.create_visit(
        f.create_visit_payload(base["system"]["id"], base["technician"]["id"],
                               base["system"]["version"],
                               scheduled_start="2026-02-24T09:00:00Z",
                               scheduled_end="2026-02-24T10:00:00Z"),
        DISP), expected_status=201)
    resp = api.terminate_contract(contract_id, AM)
    validate_error(resp, ApiErrorId.ERR_VISIT_IN_FLIGHT)


def test_cancel_emergency_visit_compensates_call_to_open(api):
    """PRD §3.3: "A Dispatcher may cancel a SCHEDULED visit, moving it
    SCHEDULED → CANCELLED; if the cancelled visit was an EMERGENCY visit whose
    linked EmergencyCall is in DISPATCHED, the call is compensated back to OPEN
    and its dispatched_visit_id is cleared."

    Design: Corner/state_machines/cancel_emergency_visit_compensates_call_to_open
    """
    em = create_dispatched_emergency(service_tier="BASIC", tech_user_id="tech-1",
                                     nominal_volume_l=200,
                                     reported_at="2026-02-25T08:00:00Z",
                                     scheduled_start="2026-02-25T09:00:00Z",
                                     scheduled_end="2026-02-25T10:00:00Z")
    validate_success(api.cancel_visit(em["dispatched_visit_id"], DISP))
    call = validate_success(api.get_emergency(em["emergency"]["id"], DISP))
    assert call["status"] == "OPEN", f"Expected OPEN after compensation, got {call['status']}"
    assert call["dispatched_visit_id"] is None, "dispatched_visit_id must be cleared"


def test_emergency_resolves_when_dispatched_visit_completes(api):
    """PRD §3.9: "When the dispatched emergency visit later completes, the call
    moves DISPATCHED → RESOLVED."

    Design: Corner/state_machines/emergency_resolves_when_dispatched_visit_completes
    """
    em = create_dispatched_emergency(service_tier="BASIC", tech_user_id="tech-1",
                                     certified_for_reef=False, nominal_volume_l=200,
                                     reported_at="2026-02-26T08:00:00Z",
                                     scheduled_start="2026-02-26T09:00:00Z",
                                     scheduled_end="2026-02-26T10:00:00Z")
    tech_headers = make_field_tech_headers("tech-1")
    validate_success(api.start_visit(em["dispatched_visit_id"], tech_headers))
    validate_success(api.complete_visit(em["dispatched_visit_id"], {"labor_minutes": 40}, tech_headers))
    call = validate_success(api.get_emergency(em["emergency"]["id"], DISP))
    assert call["status"] == "RESOLVED", f"Expected RESOLVED, got {call['status']}"


def test_repair_diagnose_degrades_equipment(api):
    """PRD §3.7: "A FieldTech diagnoses a REPORTED order, moving it
    REPORTED → DIAGNOSED and setting the target Equipment.status to DEGRADED."

    Design: Corner/state_machines/repair_diagnose_degrades_equipment_cross_entity
    """
    base = create_equipment_on_system(customer_user_id="owner-1", device_kind="PUMP",
                                       media_interval_days=60)
    create_technician(tech_user_id="tech-1")
    tech_headers = make_field_tech_headers("tech-1")
    repair = validate_success(api.create_repair(
        f.create_repair_payload(base["equipment"]["id"], reported_symptom="noise"),
        tech_headers), expected_status=201)
    validate_success(api.diagnose_repair(repair["id"], tech_headers))
    equipment = validate_success(api.get_equipment(base["equipment"]["id"], tech_headers))
    assert equipment["status"] == "DEGRADED", (
        f"Expected DEGRADED, got {equipment['status']}")
