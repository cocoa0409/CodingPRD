"""Conservation, compensation, cascade, and numeric-boundary tests: charge void
conserving the subtotal, transfer-then-referral-cancel restoring the visit, the
transfer cascade cancelling occ orders, the inclusive surge boundary, the
optimistic-concurrency stale-version rejection, the minor 18th-birthday boundary,
and the follow-up due computation (PRD §2.7, §2.9, §3.4, §3.5, §3.6, §3.7).
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    make_provider_headers,
    TEST_USERS,
    create_clinic,
    create_walk_in,
    triage,
    set_clock,
    setup_roomed_visit,
    setup_invoiced_visit,
    add_charge,
    post_charges,
)

_ANON = TEST_USERS["anonymous_headers"]
_MGR = TEST_USERS["clinic_manager_headers"]
_CLERK = TEST_USERS["front_desk_headers"]
_NURSE = TEST_USERS["triage_nurse_headers"]


# ─── compensating_invariant / charge_post_then_void_conserves_subtotal ───

def test_void_charge_conserves_subtotal():
    """PRD §3.7: "A charge may be voided while billing is still open, which sets its
    voided flag to true and excludes it from the subtotal thereafter."

    Design: Difficulty/compensating_invariant/charge_post_then_void_conserves_subtotal
    """
    setup = setup_roomed_visit(clinic_overrides={"self_pay_discount_pct": 0.30})
    visit_id, provider_id = setup["visit"]["id"], setup["provider"]["id"]
    phdr = make_provider_headers(provider_id)
    add_charge(visit_id, provider_id, cpt_code="KEEP", amount_cents=7000)
    temp = add_charge(visit_id, provider_id, cpt_code="TEMP", amount_cents=3000)

    voided = validate_success(api_client.void_charge(temp["id"], phdr), 200)
    assert voided["voided"] is True
    posted = post_charges(visit_id, provider_id)
    assert posted["charges_subtotal_cents"] == 7000, (
        f"voided charge must be excluded, subtotal should be 7000, "
        f"got {posted['charges_subtotal_cents']}")


def test_void_charge_responsibility_reflects_surviving_charge():
    """PRD §3.7: the subtotal "is the sum of amount_cents over the visit's charges
    where voided is false"; self-pay responsibility is "the subtotal multiplied by
    one minus self_pay_discount_pct, rounded half-up to whole cents."

    Design: Difficulty/compensating_invariant/charge_post_then_void_conserves_subtotal
    """
    setup = setup_roomed_visit(clinic_overrides={"self_pay_discount_pct": 0.30})
    visit_id, provider_id = setup["visit"]["id"], setup["provider"]["id"]
    phdr = make_provider_headers(provider_id)
    add_charge(visit_id, provider_id, cpt_code="KEEP", amount_cents=7000)
    temp = add_charge(visit_id, provider_id, cpt_code="TEMP", amount_cents=3000)
    api_client.void_charge(temp["id"], phdr)

    posted = post_charges(visit_id, provider_id)
    # 7000 * 0.70 = 4900 (the voided 3000 leaves no drift).
    assert posted["patient_responsibility_cents"] == 4900, (
        f"responsibility should be 7000*0.70 = 4900, "
        f"got {posted['patient_responsibility_cents']}")


# ─── compensating_invariant / transfer_then_referral_cancel_restores_visit ───

def test_transfer_then_referral_cancel_restores_visit():
    """PRD §3.6: "Cancelling a referral advances INITIATED → CANCELLED ... The
    compensation reverts the source visit TRANSFERRED → CHARTING and clears its
    disposition back to null".

    Design: Difficulty/compensating_invariant/transfer_then_referral_cancel_restores_visit
    """
    setup = setup_roomed_visit(esi_level=3, clinic_overrides={"self_pay_discount_pct": 0.30})
    visit_id, provider_id = setup["visit"]["id"], setup["provider"]["id"]
    phdr = make_provider_headers(provider_id)
    validate_success(api_client.transfer_visit(
        visit_id,
        {"destination_facility": "County ER", "transfer_reason": "ACUITY_ESCALATION",
         "mode": "PRIVATE_VEHICLE"}, phdr), 200)
    referrals, _ = validate_paginated(api_client.list_visit_referrals(visit_id, phdr))
    ref_id = referrals[0]["id"]

    cancelled = validate_success(api_client.cancel_referral(ref_id, _MGR), 200)
    assert cancelled["status"] == "CANCELLED"
    visit = validate_success(api_client.get_visit(visit_id, phdr), 200)
    assert visit["clinical_status"] == "CHARTING", (
        f"compensation should revert clinical_status to CHARTING, got {visit['clinical_status']}")
    assert visit["disposition"] is None, (
        f"compensation should clear disposition to null, got {visit['disposition']}")


def test_transfer_sets_disposition_er_transfer_then_referral_cancel_clears_it():
    """PRD §3.6: "A successful transfer creates a referral in INITIATED status, sets
    the visit's disposition to ER_TRANSFER"; cancelling the referral "clears its
    disposition back to null".

    Design: Difficulty/compensating_invariant/transfer_then_referral_cancel_restores_visit
    """
    setup = setup_roomed_visit(esi_level=3, clinic_overrides={"self_pay_discount_pct": 0.30})
    visit_id, provider_id = setup["visit"]["id"], setup["provider"]["id"]
    phdr = make_provider_headers(provider_id)
    transferred = validate_success(api_client.transfer_visit(
        visit_id,
        {"destination_facility": "County ER", "transfer_reason": "ACUITY_ESCALATION",
         "mode": "PRIVATE_VEHICLE"}, phdr), 200)
    assert transferred["clinical_status"] == "TRANSFERRED"
    assert transferred["disposition"] == "ER_TRANSFER"
    referrals, _ = validate_paginated(api_client.list_visit_referrals(visit_id, phdr))
    api_client.cancel_referral(referrals[0]["id"], _MGR)
    visit = validate_success(api_client.get_visit(visit_id, phdr), 200)
    assert visit["disposition"] is None


# ─── cross_cutting / transfer_cancels_scheduled_occ_order_cascade ───

def test_transfer_cancels_scheduled_occ_order():
    """PRD §3.6: a successful transfer "further cascades to occupational health: any
    SCHEDULED occupational-health order on the same queue entry is cancelled."

    Design: Corner/cross_cutting_complexity_layers/transfer_cancels_scheduled_occ_order_cascade
    """
    set_clock("2026-06-08T09:00:00Z")
    setup = setup_roomed_visit(esi_level=3, clinic_overrides={"self_pay_discount_pct": 0.30})
    visit_id, provider = setup["visit"]["id"], setup["provider"]
    phdr = make_provider_headers(provider["id"])
    order = validate_success(api_client.create_occ_health_order(
        {"queue_entry_id": setup["queue_entry"]["id"], "order_type": "DRUG_SCREEN",
         "employer_name": "Cyberdyne", "scheduled_start": "2026-06-08T13:00:00Z",
         "collector_id": provider["id"], "duration_minutes": 20}, _CLERK), 201)

    validate_success(api_client.transfer_visit(
        visit_id,
        {"destination_facility": "Regional ER", "transfer_reason": "CAPABILITY_GAP",
         "mode": "PRIVATE_VEHICLE"}, phdr), 200)
    fetched = validate_success(api_client.get_occ_health_order(order["id"], phdr), 200)
    assert fetched["status"] == "CANCELLED", (
        f"transfer cascade should cancel the SCHEDULED occ order, got {fetched['status']}")


# ─── boundary_precision_check / posture_surge_threshold_inclusive_boundary ───

def test_posture_below_surge_threshold_is_open():
    """PRD §2.9: "when the depth is at or above surge_threshold the posture is
    SURGE; otherwise it is OPEN."

    Design: Difficulty/boundary_precision_check/posture_surge_threshold_inclusive_boundary
    """
    clinic = create_clinic(name="BoundClinic", exam_room_capacity=10,
                           surge_threshold=3, diversion_threshold=20)
    seeded = validate_success(
        api_client.seed_queue_depth({"clinic_id": clinic["id"], "count": 2}, _ANON), 201)
    assert seeded["active_queue_depth"] == 2 and seeded["posture"] == "OPEN", (
        f"depth 2 below surge_threshold 3 should be OPEN, got {seeded['posture']}")


def test_posture_at_surge_threshold_is_surge_inclusive():
    """PRD §2.9: "A depth exactly equal to surge_threshold is SURGE".

    Design: Difficulty/boundary_precision_check/posture_surge_threshold_inclusive_boundary
    """
    clinic = create_clinic(name="BoundClinic2", exam_room_capacity=10,
                           surge_threshold=3, diversion_threshold=20)
    api_client.seed_queue_depth({"clinic_id": clinic["id"], "count": 2}, _ANON)
    api_client.create_queue_entry(
        clinic["id"], {"arrival_channel": "WALK_IN", "chief_complaint": "third"}, _CLERK)
    clinic_after = validate_success(api_client.get_clinic(clinic["id"], _CLERK), 200)
    assert clinic_after["active_queue_depth"] == 3
    assert clinic_after["posture"] == "SURGE", (
        f"depth exactly at surge_threshold 3 should be SURGE, got {clinic_after['posture']}")


# ─── cross_cutting / occ_stale_visit_version_on_settle_returns_412 ───

def test_settle_with_stale_version_rejected():
    """PRD §2.7: "A settle request must carry expected_visit_version matching the
    target Visit's current version. If a prior settle or a cascaded billing
    recompute has advanced the visit's version since the client last read it, the
    echoed value is stale and the settle is rejected with ERR_STALE_VERSION".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_visit_version_on_settle_returns_412
    """
    setup = setup_invoiced_visit(amount_cents=7000, coverage_type="SELF_PAY")
    invoiced = setup["invoiced_visit"]
    stale_version = invoiced["version"] - 1
    res = api_client.settle_visit(invoiced["id"], {"expected_visit_version": stale_version}, _CLERK)
    validate_error(res, "ERR_STALE_VERSION")


# ─── calculations / minor_flag_exact_18th_birthday_not_minor_boundary ───

def test_minor_flag_exact_18th_birthday_not_minor():
    """PRD §3.4: "a patient whose eighteenth birthday is precisely the current clock
    date is not a minor (an age of exactly 18 means is_minor is false)".

    Design: Corner/calculations/minor_flag_exact_18th_birthday_not_minor_boundary
    """
    set_clock("2026-06-08T00:00:00Z")
    clinic = create_clinic(name="BdayClinic", exam_room_capacity=2)
    qe = create_walk_in(clinic["id"], chief_complaint="bday")
    triage(clinic["id"], qe["id"], esi_level=4)
    patient = validate_success(api_client.create_patient(
        {"queue_entry_id": qe["id"], "legal_name": "Adult Today",
         "date_of_birth": "2008-06-08", "consent_signed": True}, _CLERK), 201)
    assert patient["is_minor"] is False, (
        f"exact 18th birthday should be is_minor=false, got {patient['is_minor']}")


def test_minor_flag_under_18_is_minor():
    """PRD §3.4: "the patient is a minor when that age is below the majority age of
    18"; "one day before that birthday, at age 17, the patient still is a minor."

    Design: Corner/entities/patient_is_minor_computed_from_dob_ignores_client_value
    """
    set_clock("2026-06-08T12:00:00Z")
    clinic = create_clinic(name="MinorClinic", exam_room_capacity=2)
    qe = create_walk_in(clinic["id"], chief_complaint="minor")
    triage(clinic["id"], qe["id"], esi_level=4)
    patient = validate_success(api_client.create_patient(
        {"queue_entry_id": qe["id"], "legal_name": "Kid Pat", "date_of_birth": "2015-01-01",
         "guarantor_name": "Parent", "consent_signed": True}, _CLERK), 201)
    assert patient["is_minor"] is True, (
        f"DOB 2015-01-01 at clock 2026 should be is_minor=true, got {patient['is_minor']}")


# ─── calculations / follow_up_due_at_computed_from_clock_plus_days ───

def test_follow_up_due_at_computed_from_clock_plus_days():
    """PRD §3.5: "otherwise follow_up_due_at is set to the current clock plus that
    many days and follow_up_status becomes PENDING."

    Design: Corner/calculations/follow_up_due_at_computed_from_clock_plus_days
    """
    set_clock("2026-06-08T10:00:00Z")
    setup = setup_roomed_visit(esi_level=4, clinic_overrides={"self_pay_discount_pct": 0.30})
    visit_id, provider_id = setup["visit"]["id"], setup["provider"]["id"]
    phdr = make_provider_headers(provider_id)
    api_client.start_charting(visit_id, phdr)
    api_client.complete_charting(visit_id, {"chart_note": "f/u in 3 days"}, phdr)

    di = validate_success(api_client.create_discharge_instruction(
        visit_id, {"instructions_text": "Rest and fluids", "follow_up_within_days": 3}, phdr), 201)
    assert di["follow_up_due_at"] == "2026-06-11T10:00:00.000Z", (
        f"follow_up_due_at should be clock + 3 days, got {di['follow_up_due_at']}")
    assert di["follow_up_status"] == "PENDING", (
        f"follow_up_status should be PENDING at creation, got {di['follow_up_status']}")
