"""Visit workflow tests: the parallel clinical/billing dimensions, rooming and
charting cascades into clinic posture/occupancy, the discharge happy path, and
the settle valid transition (PRD §3.5, §3.7).
"""
from test_helpers import (
    api_client,
    validate_success,
    make_provider_headers,
    TEST_USERS,
    create_clinic,
    create_exam_room,
    create_provider,
    create_walk_in,
    triage,
    register_patient,
    attach_coverage,
    verify_coverage,
    mark_ready,
    setup_roomed_visit,
    setup_ready_entry,
    add_charge,
    post_charges,
    invoice_visit,
    room_visit,
    get_clinic_version,
)

_MGR = TEST_USERS["clinic_manager_headers"]
_CLERK = TEST_USERS["front_desk_headers"]
_NURSE = TEST_USERS["triage_nurse_headers"]
_ANON = TEST_USERS["anonymous_headers"]


# ─── non_linear_state_machine / visit_parallel_clinical_and_billing_dimensions ───

def test_billing_advances_independently_of_clinical_status():
    """PRD §3.7: "A visit's billing dimension runs in parallel with its clinical
    one and evolves independently."

    Design: Difficulty/non_linear_state_machine/visit_parallel_clinical_and_billing_dimensions
    """
    setup = setup_visit_with_one_charge(amount_cents=5000)
    visit_id, provider_id = setup["visit"]["id"], setup["provider"]["id"]
    posted = post_charges(visit_id, provider_id)
    assert posted["billing_status"] == "CHARGES_POSTED"
    assert posted["clinical_status"] == "IN_EXAM", (
        f"posting charges must not move clinical_status, got {posted['clinical_status']}")


def test_clinical_advances_without_disturbing_billing():
    """PRD §3.7: "The billing dimension continues independently of the clinical
    one." PRD §3.5: "A provider starts charting, advancing IN_EXAM → CHARTING."

    Design: Difficulty/non_linear_state_machine/visit_parallel_clinical_and_billing_dimensions
    """
    setup = setup_visit_with_one_charge(amount_cents=5000)
    visit_id, provider_id = setup["visit"]["id"], setup["provider"]["id"]
    post_charges(visit_id, provider_id)
    charting = validate_success(
        api_client.start_charting(visit_id, make_provider_headers(provider_id)), 200)
    assert charting["clinical_status"] == "CHARTING"
    assert charting["billing_status"] == "CHARGES_POSTED", (
        f"start-charting must not move billing_status, got {charting['billing_status']}")


# ─── transitive_cascade / rooming_cascade_depth_to_posture_demotion ───

def test_rooming_decrements_depth_and_demotes_posture():
    """PRD §2.9: "when the depth is at or above surge_threshold the posture is
    SURGE; otherwise it is OPEN." PRD §3.5: at rooming "the clinic's active queue
    depth is decremented and its posture, rooms_occupied, and the ranks and wait
    estimates of the remaining active entries are all recomputed".

    Design: Difficulty/transitive_cascade/rooming_cascade_depth_to_posture_demotion
    """
    clinic = create_clinic(name="SurgeClinic", exam_room_capacity=10,
                           surge_threshold=8, diversion_threshold=20)
    room = create_exam_room(clinic["id"], room_label="S1")
    provider = create_provider(clinic["id"], full_name="Dr S", credential="MD")
    qe = create_walk_in(clinic["id"], chief_complaint="front")
    triage(clinic["id"], qe["id"], esi_level=1)
    patient = register_patient(qe["id"], legal_name="Front Pat", date_of_birth="1970-01-01",
                               consent_signed=True)
    attach_coverage(patient["id"], coverage_type="SELF_PAY")
    mark_ready(clinic["id"], qe["id"])
    api_client.seed_queue_depth({"clinic_id": clinic["id"], "count": 7}, _ANON)

    before = validate_success(api_client.get_clinic(clinic["id"], _MGR), 200)
    assert before["active_queue_depth"] == 8 and before["posture"] == "SURGE"

    roomed = room_visit(clinic["id"], qe["id"], provider["id"], room["id"])
    after = validate_success(api_client.get_clinic(clinic["id"], _MGR), 200)
    assert after["active_queue_depth"] == 7, (
        f"rooming should decrement depth to 7, got {after['active_queue_depth']}")
    assert after["posture"] == "OPEN", (
        f"depth 7 below surge_threshold 8 should be OPEN, got {after['posture']}")
    fetched_qe = validate_success(api_client.get_queue_entry(qe["id"], _MGR), 200)
    assert fetched_qe["status"] == "ROOMED"


def test_rooming_occupies_room_as_first_cascade_link():
    """PRD §3.5: "the exam room goes AVAILABLE → OCCUPIED and its current_visit_id
    is set to point back at the new visit"; "the clinic's active queue depth is
    decremented and its posture, rooms_occupied, and the ranks and wait estimates of
    the remaining active entries are all recomputed". (Verifies the room-occupancy
    link of the same rooming cascade.)

    Design: Difficulty/transitive_cascade/rooming_cascade_depth_to_posture_demotion
    """
    setup = setup_roomed_visit(esi_level=1, clinic_overrides={"exam_room_capacity": 4})
    room = validate_success(api_client.get_exam_room(setup["room"]["id"], _MGR), 200)
    assert room["status"] == "OCCUPIED", (
        f"rooming should drive the room to OCCUPIED, got {room['status']}")
    clinic = validate_success(api_client.get_clinic(setup["clinic"]["id"], _MGR), 200)
    assert clinic["rooms_occupied"] == 1, (
        f"rooms_occupied should reconcile to 1 after rooming, got {clinic['rooms_occupied']}")


# ─── transitive_cascade / complete_charting_cascade_room_release_to_rooms_occupied ───

def test_complete_charting_releases_room_and_reconciles_occupancy():
    """PRD §3.5: completing charting "as a cascade releases the room OCCUPIED →
    CLEANING (clearing the room's current_visit_id), decrements the provider's
    active_visit_count, and recomputes the clinic's rooms_occupied."

    Design: Difficulty/transitive_cascade/complete_charting_cascade_room_release_to_rooms_occupied
    """
    setup = setup_roomed_visit(clinic_overrides={"exam_room_capacity": 1})
    visit_id, provider_id = setup["visit"]["id"], setup["provider"]["id"]
    api_client.start_charting(visit_id, make_provider_headers(provider_id))

    completed = validate_success(
        api_client.complete_charting(
            visit_id, {"chart_note": "URI, supportive care"},
            make_provider_headers(provider_id)), 200)
    assert completed["clinical_status"] == "PENDING_DISCHARGE"

    room = validate_success(api_client.get_exam_room(setup["room"]["id"], _MGR), 200)
    assert room["status"] == "CLEANING", (
        f"room should be released to CLEANING, got {room['status']}")
    clinic = validate_success(api_client.get_clinic(setup["clinic"]["id"], _MGR), 200)
    assert clinic["rooms_occupied"] == 0, (
        f"rooms_occupied should reconcile to 0, got {clinic['rooms_occupied']}")


def test_complete_charting_clears_room_back_pointer():
    """PRD §3.5: completing charting "as a cascade releases the room OCCUPIED →
    CLEANING (clearing the room's current_visit_id)". (Verifies the back-pointer
    clearing link of the same complete-charting cascade.)

    Design: Difficulty/transitive_cascade/complete_charting_cascade_room_release_to_rooms_occupied
    """
    setup = setup_roomed_visit(clinic_overrides={"exam_room_capacity": 1})
    visit_id, provider_id = setup["visit"]["id"], setup["provider"]["id"]
    phdr = make_provider_headers(provider_id)
    api_client.start_charting(visit_id, phdr)
    # Before completing, the room holds the back-pointer.
    room_before = validate_success(api_client.get_exam_room(setup["room"]["id"], _MGR), 200)
    assert room_before["current_visit_id"] == visit_id

    api_client.complete_charting(visit_id, {"chart_note": "URI"}, phdr)
    room_after = validate_success(api_client.get_exam_room(setup["room"]["id"], _MGR), 200)
    assert room_after["current_visit_id"] is None, (
        f"complete-charting should clear current_visit_id, got {room_after['current_visit_id']}")


# ─── state_machines / settle_with_correct_version_succeeds ───

def test_settle_with_correct_version_succeeds():
    """PRD §3.7: "Settling advances INVOICED → SETTLED; it is the
    concurrency-guarded write of §2.7, requiring expected_visit_version to match
    the visit's current version".

    Design: Corner/state_machines/settle_with_correct_version_succeeds
    """
    setup = setup_invoiced_visit_insured()
    invoiced = setup["invoiced_visit"]
    res = api_client.settle_visit(
        invoiced["id"], {"expected_visit_version": invoiced["version"]}, _CLERK)
    settled = validate_success(res, 200)
    assert settled["billing_status"] == "SETTLED", (
        f"settle with correct version should reach SETTLED, got {settled['billing_status']}")


# ─── endpoints / discharge_full_happy_path_sets_disposition_home ───

def test_discharge_happy_path_sets_disposition_home():
    """PRD §3.5: "From PENDING_DISCHARGE the provider discharges the patient home,
    advancing PENDING_DISCHARGE → DISCHARGED and setting disposition to HOME."

    Design: Corner/endpoints/discharge_full_happy_path_sets_disposition_home
    """
    setup = setup_roomed_visit()
    visit_id, provider_id = setup["visit"]["id"], setup["provider"]["id"]
    phdr = make_provider_headers(provider_id)
    add_charge(visit_id, provider_id, cpt_code="DC9", amount_cents=4000)
    post_charges(visit_id, provider_id)
    api_client.start_charting(visit_id, phdr)
    api_client.complete_charting(visit_id, {"chart_note": "ok to go home"}, phdr)
    api_client.create_discharge_instruction(visit_id, {"instructions_text": "Return if worse"}, phdr)

    discharged = validate_success(api_client.discharge_visit(visit_id, phdr), 200)
    assert discharged["clinical_status"] == "DISCHARGED"
    assert discharged["disposition"] == "HOME", (
        f"discharge should set disposition HOME, got {discharged['disposition']}")


# ─── consistency_model / rooming_side_effects_visible_in_same_response ───

def test_rooming_side_effects_immediately_visible():
    """PRD §3.5: "the new visit is created with clinical_status IN_EXAM"; "its
    current ESI is snapshotted into the visit's acuity_at_rooming"; "the exam room
    goes AVAILABLE → OCCUPIED and its current_visit_id is set to point back at the
    new visit".

    Design: Corner/consistency_model/rooming_side_effects_visible_in_same_response
    """
    clinic = create_clinic(name="ImmClinic", exam_room_capacity=2, self_pay_discount_pct=0.30)
    room = create_exam_room(clinic["id"], room_label="IM1")
    provider = create_provider(clinic["id"], full_name="Dr IM", credential="MD")
    ready = setup_ready_entry(clinic["id"], esi_level=3, coverage_type="SELF_PAY")
    cv = get_clinic_version(clinic["id"], make_provider_headers(provider["id"]))
    visit = validate_success(
        api_client.create_visit(
            {"queue_entry_id": ready["queue_entry"]["id"], "provider_id": provider["id"],
             "exam_room_id": room["id"], "expected_clinic_version": cv},
            make_provider_headers(provider["id"])), 201)
    assert visit["clinical_status"] == "IN_EXAM"
    assert visit["acuity_at_rooming"] == 3, (
        f"acuity_at_rooming should be the snapshotted ESI 3, got {visit['acuity_at_rooming']}")
    room_after = validate_success(api_client.get_exam_room(room["id"], _MGR), 200)
    assert room_after["status"] == "OCCUPIED"
    assert room_after["current_visit_id"] == visit["id"], (
        f"room current_visit_id should point at the new visit, "
        f"got {room_after['current_visit_id']}")


# ─── cross_cutting / rooms_occupied_derived_field_reconciles_after_mark_clean ───

def test_rooms_occupied_reconciles_after_mark_clean():
    """PRD §3.9: "The manager closes the loop by marking a CLEANING room clean,
    advancing CLEANING → AVAILABLE and recomputing the clinic's rooms_occupied."

    Design: Corner/cross_cutting_complexity_layers/rooms_occupied_derived_field_reconciles_after_mark_clean
    """
    setup = setup_roomed_visit(clinic_overrides={"exam_room_capacity": 1})
    visit_id, provider_id = setup["visit"]["id"], setup["provider"]["id"]
    phdr = make_provider_headers(provider_id)
    api_client.start_charting(visit_id, phdr)
    api_client.complete_charting(visit_id, {"chart_note": "done"}, phdr)  # room -> CLEANING

    cleaned = validate_success(
        api_client.mark_room_clean(setup["clinic"]["id"], setup["room"]["id"], _MGR), 200)
    assert cleaned["status"] == "AVAILABLE"
    clinic = validate_success(api_client.get_clinic(setup["clinic"]["id"], _MGR), 200)
    assert clinic["rooms_occupied"] == 0, (
        f"rooms_occupied should stay 0 after mark-clean, got {clinic['rooms_occupied']}")


# ─── local helpers (compose test_helpers fixtures) ───

def setup_visit_with_one_charge(amount_cents=5000):
    """Roomed SELF_PAY visit (billing OPEN) with one VISIT charge."""
    setup = setup_roomed_visit(coverage_type="SELF_PAY",
                               clinic_overrides={"self_pay_discount_pct": 0.30})
    add_charge(setup["visit"]["id"], setup["provider"]["id"], cpt_code="Z1",
               amount_cents=amount_cents)
    return setup


def setup_invoiced_visit_insured():
    """Roomed visit driven to billing INVOICED with verified-insurance (copay 1000)."""
    setup = setup_roomed_visit(
        coverage_type="INSURANCE",
        coverage_overrides={"payer_name": "Cigna", "member_id": "X9", "copay_cents": 1000},
        verify_outcome="ELIGIBLE", clinic_overrides={"self_pay_discount_pct": 0.30})
    add_charge(setup["visit"]["id"], setup["provider"]["id"], cpt_code="S1", amount_cents=9000)
    post_charges(setup["visit"]["id"], setup["provider"]["id"])
    setup["invoiced_visit"] = invoice_visit(setup["visit"]["id"])
    return setup
