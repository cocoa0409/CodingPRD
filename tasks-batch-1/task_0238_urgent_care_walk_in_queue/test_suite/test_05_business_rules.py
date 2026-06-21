"""Business-rule and validation tests: rooming gates (queue order, isolation,
room availability), registration completeness, the minor guarantor rule, the
ambulance rule, diversion, billing freeze, occ room requirement, and the
deterministic error chosen when a state check pre-empts a business rule
(PRD §2.6, §3.4, §3.5, §3.6, §3.7, §3.8).
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    make_provider_headers,
    TEST_USERS,
    create_clinic,
    create_exam_room,
    create_provider,
    create_walk_in,
    triage,
    register_patient,
    attach_coverage,
    mark_ready,
    set_clock,
    setup_roomed_visit,
    setup_ready_entry,
    add_charge,
    post_charges,
    invoice_visit,
    get_clinic_version,
)

_ANON = TEST_USERS["anonymous_headers"]
_MGR = TEST_USERS["clinic_manager_headers"]
_CLERK = TEST_USERS["front_desk_headers"]
_NURSE = TEST_USERS["triage_nurse_headers"]


def _room(clinic_id, qe_id, provider_id, room_id, headers, **overrides):
    cv = get_clinic_version(clinic_id, headers)
    return api_client.create_visit(
        {"queue_entry_id": qe_id, "provider_id": provider_id, "exam_room_id": room_id,
         "expected_clinic_version": cv, **overrides}, headers)


# ─── priority_pair_validation_conflict / queue_order_vs_isolation_priority_on_rooming ───

def test_queue_order_violation_wins_over_isolation_on_rooming():
    """PRD §3.5: "The entry must be the one with the lowest priority_rank among
    READY_FOR_PROVIDER entries; rooming a non-front entry without override set is
    rejected with ERR_QUEUE_ORDER_VIOLATION." (This precondition is listed before
    the isolation check in §3.5, so the queue-order error is the deterministic
    outcome when both would fire.)

    Design: Difficulty/priority_pair_validation_conflict/queue_order_vs_isolation_priority_on_rooming
    """
    clinic = create_clinic(name="PrioClinic", exam_room_capacity=4,
                           surge_threshold=9, diversion_threshold=20)
    room = create_exam_room(clinic["id"], room_label="STD1", room_type="STANDARD")
    provider = create_provider(clinic["id"], full_name="Dr Q", credential="MD")
    # Front-of-line entry F (ESI 1, created first).
    qf = create_walk_in(clinic["id"], chief_complaint="front")
    triage(clinic["id"], qf["id"], esi_level=1)
    pf = register_patient(qf["id"], legal_name="F Pat", date_of_birth="1972-02-02",
                          consent_signed=True)
    attach_coverage(pf["id"], coverage_type="SELF_PAY")
    mark_ready(clinic["id"], qf["id"])
    # Back entry B (ESI 1, created later) flagged airborne.
    qb = create_walk_in(clinic["id"], chief_complaint="airborne")
    triage(clinic["id"], qb["id"], esi_level=1, airborne_precaution=True)
    pb = register_patient(qb["id"], legal_name="B Pat", date_of_birth="1968-04-04",
                          consent_signed=True)
    attach_coverage(pb["id"], coverage_type="SELF_PAY")
    mark_ready(clinic["id"], qb["id"])

    res = _room(clinic["id"], qb["id"], provider["id"], room["id"],
                make_provider_headers(provider["id"]))
    validate_error(res, "ERR_QUEUE_ORDER_VIOLATION")


def test_out_of_order_rooming_with_override_clears_queue_gate():
    """PRD §3.5: "rooming a non-front entry without override set is rejected with
    ERR_QUEUE_ORDER_VIOLATION." With override set the queue-order gate no longer
    fires, so a back airborne entry then surfaces the next condition — the isolation
    requirement — rather than the queue-order error.

    Design: Difficulty/priority_pair_validation_conflict/queue_order_vs_isolation_priority_on_rooming
    """
    clinic = create_clinic(name="PrioClinic2", exam_room_capacity=4,
                           surge_threshold=9, diversion_threshold=20)
    room = create_exam_room(clinic["id"], room_label="STD2", room_type="STANDARD")
    provider = create_provider(clinic["id"], full_name="Dr Q2", credential="MD")
    qf = create_walk_in(clinic["id"], chief_complaint="front")
    triage(clinic["id"], qf["id"], esi_level=1)
    pf = register_patient(qf["id"], legal_name="F2 Pat", date_of_birth="1972-02-02",
                          consent_signed=True)
    attach_coverage(pf["id"], coverage_type="SELF_PAY")
    mark_ready(clinic["id"], qf["id"])
    qb = create_walk_in(clinic["id"], chief_complaint="airborne")
    triage(clinic["id"], qb["id"], esi_level=1, airborne_precaution=True)
    pb = register_patient(qb["id"], legal_name="B2 Pat", date_of_birth="1968-04-04",
                          consent_signed=True)
    attach_coverage(pb["id"], coverage_type="SELF_PAY")
    mark_ready(clinic["id"], qb["id"])

    res = _room(clinic["id"], qb["id"], provider["id"], room["id"],
                make_provider_headers(provider["id"]), override=True)
    # P40 (queue order) is satisfied by override; the airborne entry now fails P41
    # (isolation) against the STANDARD room — confirming P40 was the prior gate.
    validate_error(res, "ERR_ISOLATION_REQUIRED")


# ─── priority_pair_validation_conflict / invalid_state_vs_charges_not_finalized_on_discharge ───

def test_invalid_state_wins_over_charges_not_finalized_on_discharge():
    """PRD §2.6: "After the body is known to be well-formed, state-machine legality
    is checked: if the target resource is not in a state from which the requested
    transition is defined, the request fails with ERR_INVALID_STATE (HTTP 409)...
    Domain-specific business rules ... are evaluated last." A visit still IN_EXAM
    fails the state check before the charges-finalized rule.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_vs_charges_not_finalized_on_discharge
    """
    setup = setup_roomed_visit(clinic_overrides={"self_pay_discount_pct": 0.30})
    # Visit is clinical IN_EXAM, billing OPEN: discharge is not defined from IN_EXAM.
    res = api_client.discharge_visit(setup["visit"]["id"],
                                     make_provider_headers(setup["provider"]["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_charges_not_finalized_fires_only_once_state_legal():
    """PRD §3.5: discharge "is gated by two preconditions beyond the state itself:
    the visit's billing_status must already be one of CHARGES_POSTED, INVOICED, or
    SETTLED ... else ERR_CHARGES_NOT_FINALIZED". Once the visit is in
    PENDING_DISCHARGE (state check passes), the billing-finalized rule — evaluated
    after state legality per §2.6 — becomes the observed error.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_vs_charges_not_finalized_on_discharge
    """
    setup = setup_roomed_visit(clinic_overrides={"self_pay_discount_pct": 0.30})
    visit_id, provider_id = setup["visit"]["id"], setup["provider"]["id"]
    phdr = make_provider_headers(provider_id)
    # Advance clinical to PENDING_DISCHARGE while keeping billing OPEN.
    api_client.start_charting(visit_id, phdr)
    api_client.complete_charting(visit_id, {"chart_note": "done"}, phdr)
    api_client.create_discharge_instruction(visit_id, {"instructions_text": "Return if worse"}, phdr)
    res = api_client.discharge_visit(visit_id, phdr)
    validate_error(res, "ERR_CHARGES_NOT_FINALIZED")


# ─── cross_entity_state_dependency / rooming_blocked_by_room_not_available ───

def test_rooming_blocked_when_room_out_of_service():
    """PRD §3.5: "The target exam room must be AVAILABLE, else ERR_ROOM_UNAVAILABLE."

    Design: Difficulty/cross_entity_state_dependency/rooming_blocked_by_room_not_available
    """
    clinic = create_clinic(name="RoomGateClinic", exam_room_capacity=1)
    room = create_exam_room(clinic["id"], room_label="G1")
    provider = create_provider(clinic["id"], full_name="Dr G", credential="MD")
    ready = setup_ready_entry(clinic["id"], esi_level=3, coverage_type="SELF_PAY")
    api_client.take_room_offline(clinic["id"], room["id"], _MGR)  # room -> OUT_OF_SERVICE

    res = _room(clinic["id"], ready["queue_entry"]["id"], provider["id"], room["id"],
                make_provider_headers(provider["id"]))
    validate_error(res, "ERR_ROOM_UNAVAILABLE")


def test_rooming_blocked_when_room_in_cleaning():
    """PRD §3.5: "The target exam room must be AVAILABLE, else ERR_ROOM_UNAVAILABLE."
    A room left CLEANING after a prior encounter is likewise not AVAILABLE, so
    rooming into it is rejected — Visit creation gated by ExamRoom.status.

    Design: Difficulty/cross_entity_state_dependency/rooming_blocked_by_room_not_available
    """
    # First roomed visit on the clinic's only room, then complete-charting -> CLEANING.
    first = setup_roomed_visit(clinic_overrides={"exam_room_capacity": 1})
    clinic_id, room_id = first["clinic"]["id"], first["room"]["id"]
    fphdr = make_provider_headers(first["provider"]["id"])
    api_client.start_charting(first["visit"]["id"], fphdr)
    api_client.complete_charting(first["visit"]["id"], {"chart_note": "done"}, fphdr)
    # Now a second ready entry tries to room into the CLEANING room.
    ready = setup_ready_entry(clinic_id, esi_level=3, coverage_type="SELF_PAY")
    res = _room(clinic_id, ready["queue_entry"]["id"], first["provider"]["id"], room_id,
                make_provider_headers(first["provider"]["id"]))
    validate_error(res, "ERR_ROOM_UNAVAILABLE")


# ─── cross_entity_state_dependency / mark_ready_blocked_without_coverage ───

def test_mark_ready_blocked_without_coverage():
    """PRD §3.4: "Mark-ready is permitted only from IN_REGISTRATION, and only when
    registration is genuinely complete: there must exist a Patient for this queue
    entry whose consent_signed is true, and there must exist a Coverage for that
    patient of any coverage type. If either is missing, mark-ready is rejected with
    ERR_REGISTRATION_INCOMPLETE."

    Design: Difficulty/cross_entity_state_dependency/mark_ready_blocked_without_coverage
    """
    clinic = create_clinic(name="RegClinic", exam_room_capacity=2)
    qe = create_walk_in(clinic["id"], chief_complaint="reg")
    triage(clinic["id"], qe["id"], esi_level=3)
    register_patient(qe["id"], legal_name="Reg Pat", date_of_birth="1992-11-11",
                     consent_signed=True)  # IN_REGISTRATION, but no coverage attached
    res = api_client.mark_ready_queue_entry(clinic["id"], qe["id"], _CLERK)
    validate_error(res, "ERR_REGISTRATION_INCOMPLETE")


def test_mark_ready_without_coverage_leaves_entry_in_registration():
    """PRD §3.4: "A queue entry becomes roomable when the front desk marks it ready,
    advancing IN_REGISTRATION → READY_FOR_PROVIDER" — but only when a Coverage
    exists; a blocked mark-ready (ERR_REGISTRATION_INCOMPLETE) makes no transition,
    so the entry remains IN_REGISTRATION (QueueEntry gated by Patient/Coverage).

    Design: Difficulty/cross_entity_state_dependency/mark_ready_blocked_without_coverage
    """
    clinic = create_clinic(name="RegClinic2", exam_room_capacity=2)
    qe = create_walk_in(clinic["id"], chief_complaint="reg2")
    triage(clinic["id"], qe["id"], esi_level=3)
    register_patient(qe["id"], legal_name="Reg2 Pat", date_of_birth="1989-03-03",
                     consent_signed=True)  # IN_REGISTRATION, no coverage
    api_client.mark_ready_queue_entry(clinic["id"], qe["id"], _CLERK)  # blocked
    fetched = validate_success(api_client.get_queue_entry(qe["id"], _CLERK), 200)
    assert fetched["status"] == "IN_REGISTRATION", (
        f"blocked mark-ready should leave entry IN_REGISTRATION, got {fetched['status']}")


# ─── validations / minor_without_guarantor_returns_guarantor_required ───

def test_minor_without_guarantor_rejected():
    """PRD §3.4: "A minor must have a financial guarantor: when is_minor is true
    and no guarantor_name is supplied, registration is rejected with
    ERR_GUARANTOR_REQUIRED."

    Design: Corner/validations/minor_without_guarantor_returns_guarantor_required
    """
    set_clock("2026-06-08T00:00:00Z")
    clinic = create_clinic(name="GuarClinic", exam_room_capacity=2)
    qe = create_walk_in(clinic["id"], chief_complaint="minor-no-guar")
    triage(clinic["id"], qe["id"], esi_level=4)
    res = api_client.create_patient(
        {"queue_entry_id": qe["id"], "legal_name": "Kid NoGuar",
         "date_of_birth": "2015-01-01", "consent_signed": True}, _CLERK)
    validate_error(res, "ERR_GUARANTOR_REQUIRED")


# ─── validations / transfer_low_acuity_private_vehicle_returns_ambulance_required ───

def test_transfer_low_acuity_private_vehicle_rejected():
    """PRD §3.6: "when the visit's acuity_at_rooming is 2 or lower (a more acute
    ESI), the transfer must use mode AMBULANCE, and a transfer of such a visit with
    any other mode is rejected with ERR_AMBULANCE_REQUIRED."

    Design: Corner/validations/transfer_low_acuity_private_vehicle_returns_ambulance_required
    """
    setup = setup_roomed_visit(esi_level=2, clinic_overrides={"self_pay_discount_pct": 0.30})
    res = api_client.transfer_visit(
        setup["visit"]["id"],
        {"destination_facility": "Trauma Center", "transfer_reason": "ACUITY_ESCALATION",
         "mode": "PRIVATE_VEHICLE"},
        make_provider_headers(setup["provider"]["id"]))
    validate_error(res, "ERR_AMBULANCE_REQUIRED")


# ─── validations / create_queue_entry_on_diversion_returns_clinic_on_diversion ───

def test_create_queue_entry_on_diversion_rejected():
    """PRD §3.1: "when the clinic's posture is DIVERSION, any attempt to create a
    queue entry of either channel is rejected with ERR_CLINIC_ON_DIVERSION."

    Design: Corner/validations/create_queue_entry_on_diversion_returns_clinic_on_diversion
    """
    clinic = create_clinic(name="DivClinic", exam_room_capacity=10,
                           surge_threshold=1, diversion_threshold=2)
    seeded = validate_success(
        api_client.seed_queue_depth({"clinic_id": clinic["id"], "count": 2}, _ANON), 201)
    assert seeded["posture"] == "DIVERSION"
    res = api_client.create_queue_entry(
        clinic["id"], {"arrival_channel": "WALK_IN", "chief_complaint": "overflow"}, _CLERK)
    validate_error(res, "ERR_CLINIC_ON_DIVERSION")


# ─── validations / post_charges_after_invoiced_returns_billing_frozen ───

def test_post_charges_after_invoiced_returns_billing_frozen():
    """PRD §3.7: "An attempt to post charges after billing has advanced past
    CHARGES_POSTED — that is, while INVOICED or SETTLED — is rejected with
    ERR_BILLING_FROZEN."

    Design: Corner/validations/post_charges_after_invoiced_returns_billing_frozen
    """
    setup = setup_roomed_visit(clinic_overrides={"self_pay_discount_pct": 0.30})
    visit_id, provider_id = setup["visit"]["id"], setup["provider"]["id"]
    add_charge(visit_id, provider_id, cpt_code="FR9", amount_cents=6000)
    post_charges(visit_id, provider_id)
    invoice_visit(visit_id)  # billing -> INVOICED
    res = api_client.post_charges(visit_id, make_provider_headers(provider_id))
    validate_error(res, "ERR_BILLING_FROZEN")


# ─── validations / occ_physical_missing_room_returns_occ_room_required ───

def test_occ_physical_missing_room_rejected():
    """PRD §3.8: "a PHYSICAL or RESPIRATOR_FIT order must supply a room_id, while a
    DRUG_SCREEN must omit it; violating this rule is rejected with
    ERR_OCC_ROOM_REQUIRED."

    Design: Corner/validations/occ_physical_missing_room_returns_occ_room_required
    """
    set_clock("2026-06-08T09:00:00Z")
    clinic = create_clinic(name="PhysClinic", exam_room_capacity=2)
    collector = create_provider(clinic["id"], full_name="Examiner", credential="PA")
    qe = create_walk_in(clinic["id"], chief_complaint="phys")
    res = api_client.create_occ_health_order(
        {"queue_entry_id": qe["id"], "order_type": "PHYSICAL", "employer_name": "Wonka",
         "scheduled_start": "2026-06-08T11:00:00Z", "collector_id": collector["id"],
         "duration_minutes": 30}, _CLERK)
    validate_error(res, "ERR_OCC_ROOM_REQUIRED")


# ─── validations / verify_self_pay_coverage_returns_invalid_state ───

def test_verify_self_pay_coverage_returns_invalid_state():
    """PRD §3.4: "Verification is defined only from UNVERIFIED and only for
    INSURANCE; self-pay coverages skip verification entirely and remain
    UNVERIFIED."

    Design: Corner/validations/verify_self_pay_coverage_returns_invalid_state
    """
    clinic = create_clinic(name="VerSpClinic", exam_room_capacity=2)
    qe = create_walk_in(clinic["id"], chief_complaint="ver")
    triage(clinic["id"], qe["id"], esi_level=4)
    patient = register_patient(qe["id"], legal_name="Ver Pat", date_of_birth="1990-01-01",
                               consent_signed=True)
    coverage = attach_coverage(patient["id"], coverage_type="SELF_PAY")
    res = api_client.verify_coverage(coverage["id"], {"outcome": "ELIGIBLE"}, _CLERK)
    validate_error(res, "ERR_INVALID_STATE")
