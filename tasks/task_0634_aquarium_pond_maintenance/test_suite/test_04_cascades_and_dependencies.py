"""Transitive cascades (contract terminate -> system decommission -> livestock
decease; visit complete -> invoice -> balance) and cross-entity state
dependencies (visit start requires ACTIVE system; install approve requires
ACTIVE contract).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_field_tech_headers,
    make_customer_owner_headers,
    create_started_visit,
    create_dispatched_emergency,
    create_quoted_install,
    TEST_USERS,
)
from test_helpers.fixtures import create_active_contract_with_system
from test_helpers import factories as f

AM = TEST_USERS["account_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]


def test_terminate_contract_cascades_to_decommission_and_decease(api):
    """PRD §3.1: "On termination the contract moves to TERMINATED and cascades
    its non-decommissioned systems to DECOMMISSIONED, which in turn sweeps each
    system's ALIVE livestock to DECEASED."

    Design: Difficulty/transitive_cascade/terminate_contract_decommission_system_decease_livestock_depth3
    """
    base = create_active_contract_with_system(service_tier="BASIC",
                                              customer_user_id="owner-1",
                                              nominal_volume_l=300)
    contract_id = base["contract"]["id"]
    system_id = base["system"]["id"]

    # Add one ALIVE livestock (AccountManager may add livestock).
    livestock = validate_success(api.create_livestock(
        f.create_livestock_payload(system_id, common_name="Tetra",
                                   species_class="COMMUNITY", adult_length_cm=4),
        AM), expected_status=201)
    livestock_id = livestock["id"]

    terminated = validate_success(api.terminate_contract(contract_id, AM))
    assert terminated["status"] == "TERMINATED"

    system = validate_success(api.get_system(system_id, AM))
    assert system["status"] == "DECOMMISSIONED", (
        f"Expected system DECOMMISSIONED, got {system['status']}")

    animal = validate_success(api.get_livestock(livestock_id, AM))
    assert animal["status"] == "DECEASED", (
        f"Expected livestock DECEASED, got {animal['status']}")


def test_terminate_contract_flips_system_to_decommissioned(api):
    """PRD §3.1: "On termination the contract moves to TERMINATED and cascades
    its non-decommissioned systems to DECOMMISSIONED".

    The intermediate B-step of the depth-3 chain: the contract terminate flips
    its SystemProfile to DECOMMISSIONED.

    Design: Difficulty/transitive_cascade/terminate_contract_decommission_system_decease_livestock_depth3
    """
    base = create_active_contract_with_system(service_tier="BASIC",
                                              customer_user_id="owner-1",
                                              nominal_volume_l=300)
    contract_id = base["contract"]["id"]
    system_id = base["system"]["id"]

    validate_success(api.create_livestock(
        f.create_livestock_payload(system_id, common_name="Tetra",
                                   species_class="COMMUNITY", adult_length_cm=4),
        AM), expected_status=201)

    terminated = validate_success(api.terminate_contract(contract_id, AM))
    assert terminated["status"] == "TERMINATED"
    system = validate_success(api.get_system(system_id, AM))
    assert system["status"] == "DECOMMISSIONED", (
        f"Expected system DECOMMISSIONED, got {system['status']}")


def test_complete_visit_issues_invoice_and_recomputes_balance(api):
    """PRD §3.3: "An Invoice is created for the billed amount with status ISSUED
    ... and the visit's invoice_id is set to point at it; creating that invoice
    recomputes the contract's account_balance_cents."
    PRD §2.10: "It is the sum, over every Invoice whose contract_id is this
    contract and whose status is either ISSUED or OVERDUE, of that invoice's
    total_cents minus its amount_paid_cents".

    BASIC, labor 75 -> base 6000 + 3 ceil blocks (45 over) @2000 = 6000 ->
    total 12000; balance 12000.

    Design: Difficulty/transitive_cascade/complete_visit_issue_invoice_recompute_balance_depth2
    """
    base = create_started_visit(service_tier="BASIC", customer_user_id="owner-1",
                                tech_user_id="tech-1", nominal_volume_l=200,
                                scheduled_start="2026-02-07T09:00:00Z",
                                scheduled_end="2026-02-07T10:30:00Z")
    tech_headers = make_field_tech_headers("tech-1")
    visit = validate_success(
        api.complete_visit(base["visit"]["id"], {"labor_minutes": 75}, tech_headers))
    invoice_id = visit["invoice_id"]

    invoice = validate_success(api.get_invoice(invoice_id, AM))
    assert invoice["status"] == "ISSUED", f"Expected ISSUED, got {invoice['status']}"
    assert invoice["total_cents"] == 12000, (
        f"Expected invoice total 12000, got {invoice['total_cents']}")

    contract = validate_success(api.get_contract(base["contract"]["id"], AM))
    assert contract["account_balance_cents"] == 12000, (
        f"Expected balance 12000, got {contract['account_balance_cents']}")


def test_complete_visit_creates_issued_invoice_pointed_to_by_visit(api):
    """PRD §3.3: "An Invoice is created for the billed amount with status ISSUED
    ... and the visit's invoice_id is set to point at it".

    The B-step of the depth-2 chain: completion creates an ISSUED invoice and the
    visit's invoice_id back-reference is set to it.

    Design: Difficulty/transitive_cascade/complete_visit_issue_invoice_recompute_balance_depth2
    """
    base = create_started_visit(service_tier="BASIC", customer_user_id="owner-1",
                                tech_user_id="tech-1", nominal_volume_l=200,
                                scheduled_start="2026-02-18T09:00:00Z",
                                scheduled_end="2026-02-18T10:30:00Z")
    tech_headers = make_field_tech_headers("tech-1")
    visit = validate_success(
        api.complete_visit(base["visit"]["id"], {"labor_minutes": 75}, tech_headers))
    assert visit["invoice_id"] is not None, "Completed visit must carry an invoice_id"
    invoice = validate_success(api.get_invoice(visit["invoice_id"], AM))
    assert invoice["status"] == "ISSUED", f"Expected ISSUED, got {invoice['status']}"
    assert invoice["total_cents"] == 12000, (
        f"Expected invoice total 12000, got {invoice['total_cents']}")


def test_visit_start_blocked_when_system_suspended(api):
    """PRD §3.3: "A FieldTech starts a SCHEDULED visit, moving it
    SCHEDULED → IN_PROGRESS. Starting requires the target SystemProfile to be
    ACTIVE".
    PRD §2.5: "When a contract is suspended, every SystemProfile under it that is
    currently ACTIVE is cascaded to SUSPENDED".

    Suspending the contract (balance>0) cascades the system to SUSPENDED, so the
    SCHEDULED visit's start is rejected with ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/visit_start_requires_system_active
    """
    # Build the scenario: active system + tech + a SCHEDULED visit, plus a
    # completed emergency visit that produced a balance so suspend is allowed.
    em = create_dispatched_emergency(service_tier="BASIC", customer_user_id="owner-1",
                                     tech_user_id="tech-1", nominal_volume_l=200,
                                     reported_at="2026-02-12T08:00:00Z",
                                     scheduled_start="2026-02-12T11:00:00Z",
                                     scheduled_end="2026-02-12T12:00:00Z")
    contract_id = em["contract"]["id"]
    system_id = em["system"]["id"]
    tech_headers = make_field_tech_headers("tech-1")

    # Book the routine visit BEFORE completing the emergency, so the system is
    # still ACTIVE at booking time; capture current system version.
    system_now = validate_success(api.get_system(system_id, AM))
    routine = validate_success(api.create_visit(
        f.create_visit_payload(system_id, em["technician"]["id"], system_now["version"],
                               scheduled_start="2026-02-12T09:00:00Z",
                               scheduled_end="2026-02-12T10:00:00Z"),
        DISP), expected_status=201)
    routine_id = routine["id"]

    # Complete the emergency visit to create an outstanding balance.
    validate_success(api.start_visit(em["dispatched_visit_id"], tech_headers))
    validate_success(api.complete_visit(em["dispatched_visit_id"], {"labor_minutes": 30}, tech_headers))

    # Suspend the contract (balance > 0) -> system cascades to SUSPENDED.
    validate_success(api.suspend_contract(contract_id, AM))
    system = validate_success(api.get_system(system_id, AM))
    assert system["status"] == "SUSPENDED", (
        f"Expected system SUSPENDED after cascade, got {system['status']}")

    # Now starting the SCHEDULED routine visit is blocked.
    resp = api.start_visit(routine_id, tech_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_contract_suspend_cascades_system_to_suspended(api):
    """PRD §2.5: "When a contract is suspended, every SystemProfile under it that
    is currently ACTIVE is cascaded to SUSPENDED".

    The dependency precondition for the blocked start: suspending the contract
    (balance>0) leaves its ACTIVE system SUSPENDED.

    Design: Difficulty/cross_entity_state_dependency/visit_start_requires_system_active
    """
    em = create_dispatched_emergency(service_tier="BASIC", customer_user_id="owner-1",
                                     tech_user_id="tech-1", nominal_volume_l=200,
                                     reported_at="2026-02-19T08:00:00Z",
                                     scheduled_start="2026-02-19T11:00:00Z",
                                     scheduled_end="2026-02-19T12:00:00Z")
    contract_id = em["contract"]["id"]
    system_id = em["system"]["id"]
    tech_headers = make_field_tech_headers("tech-1")

    # Produce a balance so suspend is permitted.
    validate_success(api.start_visit(em["dispatched_visit_id"], tech_headers))
    validate_success(api.complete_visit(em["dispatched_visit_id"], {"labor_minutes": 30}, tech_headers))

    validate_success(api.suspend_contract(contract_id, AM))
    system = validate_success(api.get_system(system_id, AM))
    assert system["status"] == "SUSPENDED", (
        f"Expected system SUSPENDED via cascade, got {system['status']}")


def test_install_approve_blocked_when_contract_not_active(api):
    """PRD §3.8: "Approval requires the acting owner to own contract_id and
    requires the owning ServiceContract to be ACTIVE, otherwise
    ERR_CONTRACT_NOT_ACTIVE."

    A DRAFT (never-activated) contract's QUOTED install cannot be approved.

    Design: Difficulty/cross_entity_state_dependency/install_approve_requires_contract_active
    """
    base = create_quoted_install(service_tier="PLUS", customer_user_id="owner-1",
                                 activate_contract=False)
    assert base["contract"]["status"] == "DRAFT", (
        f"Expected DRAFT contract, got {base['contract']['status']}")
    owner_headers = make_customer_owner_headers("owner-1")
    resp = api.approve_install(base["install"]["id"], owner_headers)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)


def test_install_approve_succeeds_once_contract_is_active(api):
    """PRD §3.8: "The owning CustomerOwner approves a QUOTED project, moving it
    QUOTED → APPROVED. Approval requires the acting owner to own contract_id and
    requires the owning ServiceContract to be ACTIVE, otherwise
    ERR_CONTRACT_NOT_ACTIVE."

    The same install on an ACTIVE contract approves cleanly, confirming the gate
    is the contract-ACTIVE precondition (and nothing else blocks the transition).

    Design: Difficulty/cross_entity_state_dependency/install_approve_requires_contract_active
    """
    base = create_quoted_install(service_tier="PLUS", customer_user_id="owner-1",
                                 activate_contract=True)
    assert base["contract"]["status"] == "ACTIVE"
    owner_headers = make_customer_owner_headers("owner-1")
    install = validate_success(api.approve_install(base["install"]["id"], owner_headers))
    assert install["status"] == "APPROVED", (
        f"Expected APPROVED on an ACTIVE contract, got {install['status']}")
