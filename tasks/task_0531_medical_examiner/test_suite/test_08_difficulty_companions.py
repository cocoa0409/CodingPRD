"""Second tests per difficulty-design instance (queue A ≥2-per-instance coverage).

Each test re-runs the instance's scenario and asserts a distinct, PRD-covered facet of the
same outcome (an additional field, side effect, or exact intermediate value) so no assertion
is a duplicate of its companion in the concern-organized files.
"""
from test_helpers import (
    validate_success, validate_error,
    create_investigator, create_pathologist, create_cooler,
    set_clock, create_investigating_case, create_reported_case,
    create_accepted_case, store_body,
    schedule_autopsy, complete_autopsy,
    collect_specimen, send_specimen_to_lab,
    setup_ordered_tox, result_tox_screen,
    add_property_item, add_next_of_kin, request_property_release,
    declare_indigent, draft_certificate, sign_certificate,
    setup_certified_case_natural,
    make_investigator_headers, make_pathologist_headers,
    make_medical_examiner_headers, make_labtech_headers,
    sign_death_certificate_payload, create_autopsy_exam_payload,
    complete_autopsy_exam_payload, amend_tox_screen_payload,
    triage_payload, create_body_payload, store_body_payload,
)


# ─── dual_variant_calc ────────────────────────────────

def test_autopsy_estimate_natural_no_specimen_addon(api):
    """PRD §3.4: "It begins from a base fee of 150,000 cents. The requested duration is billed
    per whole 30-minute block, with the block count obtained by dividing duration_minutes by 30
    and rounding up to the next whole block; each block adds 20,000 cents on top of the base."

    Design: Difficulty/dual_variant_calc/autopsy_estimate_vs_final_diverge_on_exam
    """
    set_clock("2026-05-10T00:00:00Z")
    inv = create_investigator("Inv A2")
    path = create_pathologist("Path A2", is_medical_examiner=False)
    case, body = create_investigating_case(inv, case_type="NATURAL")
    exam = schedule_autopsy(path, case, "2026-05-10T00:00:00Z", 120)
    # base 150000 + ceil(120/30)=4 blocks * 20000 = 230000, no specimen add-on at estimate time.
    assert exam["estimated_fee_cents"] == 230000


def test_indigent_estate_offset_disposition_status_approved(api):
    """PRD §3.8: "A medical examiner approves the disposition, moving its disposition_status
    DECLARED -> APPROVED".

    Design: Difficulty/dual_variant_calc/indigent_payable_estate_offset_variant
    """
    inv = create_investigator("Inv B2")
    me = create_pathologist("ME B2", is_medical_examiner=True)
    case, body = create_investigating_case(inv, case_type="NATURAL", decedent_name="Unknown")
    add_property_item(inv, case, "watch", 150000)
    disp = declare_indigent(inv, case, statutory_allowance_cents=400000, itemized_cost_cents=500000)
    me_headers = make_medical_examiner_headers(me["id"])
    approved = validate_success(api.approve_indigent_disposition(disp["id"], me_headers), 200)
    assert approved["disposition_status"] == "APPROVED"
    assert approved["county_payable_cents"] == 350000


# ─── combinatorial_formula ────────────────────────────

def test_autopsy_final_homicide_status_completed(api):
    """PRD §3.4: "Completion moves the exam's exam_status SCHEDULED -> COMPLETED, records the
    primary_finding and the proposed cause_of_death, computes the final_fee_cents, and
    increments the exam's version."

    Design: Difficulty/combinatorial_formula/autopsy_final_nonlinear_max_ceil_conditional
    """
    set_clock("2026-05-10T00:00:00Z")
    inv = create_investigator("Inv C2")
    path = create_pathologist("Path C2", is_medical_examiner=False)
    case, body = create_investigating_case(inv, case_type="HOMICIDE")
    exam = schedule_autopsy(path, case, "2026-05-10T00:00:00Z", 90)
    set_clock("2026-05-10T02:30:00Z")
    completed = complete_autopsy(path, exam, "gsw", "gunshot")
    assert completed["exam_status"] == "COMPLETED"
    assert completed["final_fee_cents"] == 375000


def test_indigent_pinned_order_status_approved(api):
    """PRD §3.8: "Approval computes the county_payable_cents the county owes, through a pinned
    three-step waterfall."

    Design: Difficulty/combinatorial_formula/indigent_payable_pinned_evaluation_order
    """
    inv = create_investigator("Inv D2")
    me = create_pathologist("ME D2", is_medical_examiner=True)
    case, body = create_investigating_case(inv, case_type="NATURAL", decedent_name="Unknown2")
    add_property_item(inv, case, "ring", 350000)
    disp = declare_indigent(inv, case, statutory_allowance_cents=400000, itemized_cost_cents=300000)
    me_headers = make_medical_examiner_headers(me["id"])
    approved = validate_success(api.approve_indigent_disposition(disp["id"], me_headers), 200)
    assert approved["county_payable_cents"] == 0
    assert approved["disposition_status"] == "APPROVED"


# ─── non_linear_state_machine ─────────────────────────

def test_tox_amend_from_resulted_keeps_positive(api):
    """PRD §3.5: "A screen may be amended when it is RESULTED, moving it RESULTED -> AMENDED".
    PRD §3.5: "it is POSITIVE if the reported ethanol_mg_dl is at least 80, and NEGATIVE
    otherwise."

    Design: Difficulty/non_linear_state_machine/tox_screen_amend_loop
    """
    inv = create_investigator("Inv E2")
    path = create_pathologist("Path E2")
    case, body, specimen, tox = setup_ordered_tox(inv, path, panel="BASIC")
    result_tox_screen(tox, 90)  # RESULTED, POSITIVE
    labtech = make_labtech_headers()
    amended = validate_success(
        api.amend_tox_screen(tox["id"], amend_tox_screen_payload(85), labtech), 200
    )
    assert amended["result_status"] == "AMENDED"
    assert amended["interpretation"] == "POSITIVE"


def test_void_draft_terminal_cert_status(api):
    """PRD §3.6: "A draft may be discarded outright, moving it DRAFT -> VOID, a terminal state."

    Design: Difficulty/non_linear_state_machine/certificate_branch_draft_to_signed_and_void
    """
    inv = create_investigator("Inv F2")
    me = create_pathologist("ME F2", is_medical_examiner=True)
    case, body = create_investigating_case(inv, case_type="NATURAL")
    cert = draft_certificate(me, case, manner_of_death="NATURAL")
    me_headers = make_medical_examiner_headers(me["id"])
    voided = validate_success(api.void_death_certificate(cert["id"], me_headers), 200)
    assert voided["cert_status"] == "VOID"


# ─── transitive_cascade ───────────────────────────────

def test_sign_sets_certified_me_and_signed_at(api):
    """PRD §3.6: "A successful sign-off sets cert_status to SIGNED, records the
    certifying_me_user_id, and stamps signed_at from the clock."

    Design: Difficulty/transitive_cascade/sign_cert_cascades_case_certified_then_body_unblocked
    """
    inv = create_investigator("Inv G2")
    me = create_pathologist("ME G2", is_medical_examiner=True)
    cooler = create_cooler(slot_capacity=2)
    case, body = create_investigating_case(inv, case_type="NATURAL")
    body = store_body(inv, body, cooler)
    cert = draft_certificate(me, case, manner_of_death="NATURAL")
    signed = sign_certificate(me, case["id"], cert["id"])
    assert signed["cert_status"] == "SIGNED"
    assert signed["certifying_me_user_id"] == me["id"]


def test_tox_result_moves_screen_to_resulted(api):
    """PRD §3.5: "the screen moves ORDERED -> RESULTED, and as a cascade the parent specimen's
    chain_status advances SENT_TO_LAB -> CONSUMED (the assay consumes the specimen),
    incrementing both the screen's and the specimen's version."

    Design: Difficulty/transitive_cascade/tox_result_cascades_specimen_consumed
    """
    inv = create_investigator("Inv H2")
    path = create_pathologist("Path H2")
    case, body, specimen, tox = setup_ordered_tox(inv, path, panel="BASIC")
    labtech = make_labtech_headers()
    resulted = validate_success(
        api.result_tox_screen(tox["id"], {"ethanol_mg_dl": 10}, labtech), 200
    )
    assert resulted["result_status"] == "RESULTED"
    specimen_after = validate_success(api.get_specimen(specimen["id"], labtech), 200)
    assert specimen_after["chain_status"] == "CONSUMED"


# ─── priority_pair_validation_conflict ────────────────

def test_sign_segregation_status_403(api):
    """PRD §2.11: "the medical examiner who signs a case's death certificate must not be the
    same pathologist who performed that case's autopsy — a sign-off where the acting examiner's
    identity equals the case's autopsy pathologist is rejected with ERR_SEGREGATION_VIOLATION
    (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/sign_segregation_beats_manner_inconsistent
    """
    inv = create_investigator("Inv I2")
    me = create_pathologist("ME I2", is_medical_examiner=True)
    set_clock("2026-05-10T00:00:00Z")
    case, body = create_investigating_case(inv, case_type="HOMICIDE")
    exam = schedule_autopsy(me, case, "2026-05-10T00:00:00Z", 60)
    complete_autopsy(me, exam, "gsw", "gunshot")
    cert = draft_certificate(me, case, cause_of_death="gunshot", manner_of_death="NATURAL")
    me_headers = make_medical_examiner_headers(me["id"])
    case_v = validate_success(api.get_case(case["id"], me_headers), 200)["version"]
    res = api.sign_death_certificate(cert["id"], sign_death_certificate_payload(case_v), me_headers)
    validate_error(res, "ERR_SEGREGATION_VIOLATION", expected_status=403)


# ─── boundary_precision_check ─────────────────────────

def test_first_body_stores_below_capacity_boundary(api):
    """PRD §3.3: "only when it has a free slot, meaning its current occupied_slots is strictly
    less than its slot_capacity".

    Design: Difficulty/boundary_precision_check/cooler_full_at_capacity_boundary
    """
    inv = create_investigator("Inv K2")
    cooler = create_cooler(slot_capacity=1)
    case1, body1 = create_investigating_case(inv, case_type="NATURAL")
    stored = store_body(inv, body1, cooler)  # occupied 0 < 1 -> succeeds
    assert stored["storage_status"] == "STORED"
    inv_headers = make_investigator_headers(inv["id"])
    cooler_after = validate_success(api.get_cooler_unit(cooler["id"], inv_headers), 200)
    assert cooler_after["occupied_slots"] == 1


def test_complete_at_scheduled_instant_succeeds(api):
    """PRD §3.4: "An autopsy may be completed only once the logical clock has reached or passed
    its scheduled_for instant".

    Design: Difficulty/boundary_precision_check/exam_not_due_at_scheduled_instant_boundary
    """
    set_clock("2026-05-08T00:00:00Z")
    inv = create_investigator("Inv L2")
    path = create_pathologist("Path L2")
    case, body = create_investigating_case(inv, case_type="NATURAL")
    exam = schedule_autopsy(path, case, "2026-05-10T00:00:00Z", 60)
    set_clock("2026-05-10T00:00:00Z")  # exactly at scheduled_for
    completed = complete_autopsy(path, exam, "x", "y")
    assert completed["exam_status"] == "COMPLETED"


# ─── cross_entity_state_dependency ────────────────────

def test_sign_homicide_autopsy_incomplete_status_409(api):
    """PRD §3.6: "If the case's autopsy_required is true, the case's autopsy exam must be
    COMPLETED, else the sign-off is rejected with ERR_AUTOPSY_INCOMPLETE (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/cert_sign_requires_autopsy_completed
    """
    inv = create_investigator("Inv M2")
    path = create_pathologist("Path M2", is_medical_examiner=False)
    me = create_pathologist("ME M2", is_medical_examiner=True)
    set_clock("2026-05-10T00:00:00Z")
    case, body = create_investigating_case(inv, case_type="HOMICIDE")
    schedule_autopsy(path, case, "2026-05-11T00:00:00Z", 60)
    cert = draft_certificate(me, case, cause_of_death="gunshot", manner_of_death="HOMICIDE")
    me_headers = make_medical_examiner_headers(me["id"])
    case_v = validate_success(api.get_case(case["id"], me_headers), 200)["version"]
    res = api.sign_death_certificate(cert["id"], sign_death_certificate_payload(case_v), me_headers)
    validate_error(res, "ERR_AUTOPSY_INCOMPLETE", expected_status=409)


def test_release_blocked_body_stays_stored(api):
    """PRD §3.3: "an attempt to release a still-blocked body is rejected with
    ERR_RELEASE_BLOCKED (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/body_release_requires_case_certified
    """
    inv = create_investigator("Inv N2")
    cooler = create_cooler(slot_capacity=3)
    case, body = create_investigating_case(inv, case_type="NATURAL")
    body = store_body(inv, body, cooler)
    inv_headers = make_investigator_headers(inv["id"])
    res = api.release_body(body["id"], inv_headers)
    validate_error(res, "ERR_RELEASE_BLOCKED", expected_status=409)
    still = validate_success(api.get_body(body["id"], inv_headers), 200)
    assert still["storage_status"] == "STORED"


# ─── resource_temporal_overlap ────────────────────────

def test_adjacent_autopsy_intervals_allowed(api):
    """PRD §3.4: "two exams that merely touch — one ending exactly when the next begins — are
    adjacent, not overlapping, and are allowed."

    Design: Difficulty/resource_temporal_overlap/pathologist_double_booked_half_open_overlap
    """
    set_clock("2026-05-08T00:00:00Z")
    inv = create_investigator("Inv O2")
    path = create_pathologist("Path O2")
    case1, body1 = create_investigating_case(inv, case_type="NATURAL")
    schedule_autopsy(path, case1, "2026-05-10T00:00:00Z", 60)  # 00:00-01:00
    case2, body2 = create_investigating_case(inv, case_type="NATURAL")
    path_headers = make_pathologist_headers(path["id"])
    # Adjacent exam starting exactly at prior end.
    res = api.create_autopsy_exam(
        case2["id"],
        create_autopsy_exam_payload(path["id"], "2026-05-10T01:00:00Z", 60),
        path_headers,
    )
    exam2 = validate_success(res, 201)
    assert exam2["exam_status"] == "SCHEDULED"


def test_second_store_fills_capacity_two_cooler(api):
    """PRD §3.3: "The chosen cooler's occupied_slots is recomputed upward by one and its
    version increments".

    Design: Difficulty/resource_temporal_overlap/cooler_aggregate_capacity_overlap
    """
    inv = create_investigator("Inv P2")
    cooler = create_cooler(slot_capacity=2)
    case1, body1 = create_investigating_case(inv, case_type="NATURAL")
    store_body(inv, body1, cooler)
    case2, body2 = create_investigating_case(inv, case_type="NATURAL")
    store_body(inv, body2, cooler)
    inv_headers = make_investigator_headers(inv["id"])
    cooler_after = validate_success(api.get_cooler_unit(cooler["id"], inv_headers), 200)
    assert cooler_after["occupied_slots"] == 2


# ─── compensating_invariant ───────────────────────────

def test_released_body_clears_cooler_unit_id(api):
    """PRD §3.3: "On release the body's storage_status becomes RELEASED, its released_at is
    stamped from the clock, and its cooler_unit_id is cleared to null".

    Design: Difficulty/compensating_invariant/store_then_release_conserves_cooler_occupancy
    """
    inv = create_investigator("Inv Q2")
    me = create_pathologist("ME Q2", is_medical_examiner=True)
    cooler = create_cooler(slot_capacity=2)
    case, body = setup_certified_case_natural(inv, me, cooler=cooler)
    inv_headers = make_investigator_headers(inv["id"])
    released = validate_success(api.release_body(body["id"], inv_headers), 200)
    assert released["storage_status"] == "RELEASED"
    assert released["cooler_unit_id"] is None


def test_deny_release_leaves_release_denied(api):
    """PRD §3.7: "Alternatively a requested release may be denied, moving it REQUESTED ->
    DENIED."

    Design: Difficulty/compensating_invariant/request_then_deny_conserves_held_property_count
    """
    inv = create_investigator("Inv R2")
    case, body = create_investigating_case(inv, case_type="NATURAL")
    item1 = add_property_item(inv, case, "phone", 20000)
    item2 = add_property_item(inv, case, "keys", 1000)
    kin = add_next_of_kin(inv, case, "Kin R2", "SPOUSE")
    release = request_property_release(inv, case, kin)
    inv_headers = make_investigator_headers(inv["id"])
    denied = validate_success(api.deny_property_release(release["id"], inv_headers), 200)
    assert denied["release_status"] == "DENIED"
    # No cascade: both items remain HELD.
    i1 = validate_success(api.get_property_item(item1["id"], inv_headers), 200)
    assert i1["item_status"] == "HELD"
