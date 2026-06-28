"""Transitive cascades and conservation compensations: malignant biopsy sign-out
dismissing routine recalls, void-billing cascading to charges + deductible restoration,
and the deductible / wallet conservation invariants across post-then-void."""
import pytest
from test_helpers import (
    validate_success, validate_paginated, validate_error, get_success_data, api_client,
    set_clock, create_patient, create_provider, create_encounter,
    setup_encounter_in_progress, setup_biopsy_in_state,
    setup_provider_patient_encounter, setup_cosmetic_encounter_with_membership,
    redeem_treatment,
    TEST_USERS,
)
from test_helpers.test_users import make_provider_headers

BILLING = TEST_USERS["billing_specialist_headers"]
FRONT = TEST_USERS["front_desk_headers"]
PATHLAB = TEST_USERS["path_lab_headers"]
ADMIN = TEST_USERS["practice_admin_headers"]


def test_malignant_signout_dismisses_routine_recall_depth3(api):
    """PRD §3.5: "Furthermore, if the result was `MALIGNANT`, the newly spawned follow-up
    takes precedence over routine surveillance: every existing `ROUTINE_SKIN_CHECK` reminder
    for that patient that is still `PENDING` is transitioned `PENDING → DISMISSED` as
    superseded."
    PRD §3.5: "a `MALIGNANT` result a three-month horizon."

    Design: Difficulty/transitive_cascade/malignant_signout_cascade_depth3
    """
    set_clock("2026-02-01T00:00:00Z")
    provider = create_provider(full_name="Dr Mal")
    patient = create_patient(full_name="Mal Pat", date_of_birth="1968-08-08")
    routine = validate_success(api.create_recall_reminder({
        "patient_id": patient["id"], "reason": "ROUTINE_SKIN_CHECK",
        "due_at": "2027-02-01T00:00:00Z",
    }, FRONT), 201)

    enc = create_encounter(patient["id"], provider["id"], visit_type="MEDICAL",
                           scheduled_at="2026-02-01T09:00:00Z")
    prov_headers = make_provider_headers(provider["id"])
    validate_success(api.check_in_encounter(enc["id"], FRONT), 200)
    validate_success(api.start_encounter(enc["id"], prov_headers), 200)
    biopsy = validate_success(api.create_biopsy(
        {"encounter_id": enc["id"], "body_site": "left-cheek"}, prov_headers), 201)
    validate_success(api.send_biopsy_to_lab(biopsy["id"], prov_headers), 200)
    validate_success(api.result_biopsy(biopsy["id"], {"result": "MALIGNANT"}, PATHLAB), 200)

    signed = validate_success(api.sign_out_biopsy(biopsy["id"], prov_headers), 200)
    assert signed["recall_months"] == 3
    assert signed["status"] == "SIGNED_OUT"

    routine_after = validate_success(api.get_recall_reminder(routine["id"], FRONT), 200)
    assert routine_after["status"] == "DISMISSED"

    # A BIOPSY_FOLLOWUP reminder for this biopsy exists and is PENDING.
    data, _ = validate_paginated(
        api.list_recall_reminders(FRONT, params={"biopsy_id": biopsy["id"]}))
    followups = [r for r in data if r["reason"] == "BIOPSY_FOLLOWUP"]
    assert len(followups) == 1
    assert followups[0]["status"] == "PENDING"


def test_benign_signout_spawns_followup_does_not_dismiss_routine(api):
    """PRD §3.5: "Sign-out then spawns a follow-up recall: a `RecallReminder` is created with
    `reason` of `BIOPSY_FOLLOWUP`, its `biopsy_id` set to this biopsy, a `due_at` equal to the
    clock's current time plus `recall_months` months, and a `status` of `PENDING`; creating
    that reminder refreshes the patient's `updated_at`."
    PRD §3.5: "Furthermore, if the result was `MALIGNANT`, the newly spawned follow-up takes
    precedence over routine surveillance: every existing `ROUTINE_SKIN_CHECK` reminder for that
    patient that is still `PENDING` is transitioned `PENDING → DISMISSED` as superseded."

    Design: Difficulty/transitive_cascade/malignant_signout_cascade_depth3
    """
    set_clock("2026-02-01T00:00:00Z")
    provider = create_provider(full_name="Dr Ben")
    patient = create_patient(full_name="Ben Pat", date_of_birth="1969-08-08")
    routine = validate_success(api.create_recall_reminder({
        "patient_id": patient["id"], "reason": "ROUTINE_SKIN_CHECK",
        "due_at": "2027-02-01T00:00:00Z",
    }, FRONT), 201)
    enc = create_encounter(patient["id"], provider["id"], visit_type="MEDICAL",
                           scheduled_at="2026-02-01T09:00:00Z")
    prov_headers = make_provider_headers(provider["id"])
    validate_success(api.check_in_encounter(enc["id"], FRONT), 200)
    validate_success(api.start_encounter(enc["id"], prov_headers), 200)
    biopsy = validate_success(api.create_biopsy(
        {"encounter_id": enc["id"], "body_site": "back"}, prov_headers), 201)
    validate_success(api.send_biopsy_to_lab(biopsy["id"], prov_headers), 200)
    validate_success(api.result_biopsy(biopsy["id"], {"result": "BENIGN"}, PATHLAB), 200)
    validate_success(api.sign_out_biopsy(biopsy["id"], prov_headers), 200)

    # Benign sign-out must NOT dismiss the routine reminder (only MALIGNANT does).
    routine_after = validate_success(api.get_recall_reminder(routine["id"], FRONT), 200)
    assert routine_after["status"] == "PENDING"


def test_void_billing_cascade_charge_then_deductible_depth3(api):
    """PRD §3.8: "Void-billing cascades over every child charge of that encounter currently
    in `POSTED` status, transitioning each to `VOIDED` and reversing any deductible it
    consumed: for each such insurance charge the patient's
    `insurance_deductible_remaining_cents` is increased by that charge's
    `deductible_applied_cents`."
    PRD §3.3: "A `BillingSpecialist` may instead void billing, moving
    `BILLING_OPEN → BILLING_VOID`; this requires `billing_status` to be `BILLING_OPEN`
    (otherwise `ERR_ENCOUNTER_BAD_BILLING_STATE`) and requires the `clinical_status` to be
    `CANCELLED` — void-billing exists only for cancelled encounters (otherwise
    `ERR_ENCOUNTER_NOT_CANCELLED`)."

    Design: Difficulty/transitive_cascade/void_billing_cascade_charge_then_deductible_depth3
    """
    provider, patient, enc = setup_provider_patient_encounter(
        patient_overrides={"has_active_insurance": True,
                           "insurance_coinsurance_rate": 0.2,
                           "insurance_deductible_remaining_cents": 5000},
        encounter_overrides={"scheduled_at": "2026-01-07T09:00:00Z"},
    )
    ch = validate_success(api.create_charge({
        "patient_id": patient["id"], "encounter_id": enc["id"],
        "source_kind": "ENCOUNTER", "charge_kind": "OFFICE_VISIT",
        "billed_amount_cents": 20000, "insurer_allowed_cents": 20000,
    }, BILLING), 201)
    assert ch["deductible_applied_cents"] == 5000
    # Cancel the encounter so void-billing is permitted.
    validate_success(api.cancel_encounter(enc["id"], FRONT), 200)

    voided = validate_success(api.void_billing(enc["id"], BILLING), 200)
    assert voided["billing_status"] == "BILLING_VOID"

    ch_after = validate_success(api.get_charge(ch["id"], BILLING), 200)
    assert ch_after["status"] == "VOIDED"
    patient_after = validate_success(api.get_patient(patient["id"], BILLING), 200)
    assert patient_after["insurance_deductible_remaining_cents"] == 5000


def test_void_billing_requires_cancelled_encounter(api):
    """PRD §3.3: "A `BillingSpecialist` may instead void billing, moving
    `BILLING_OPEN → BILLING_VOID`; this requires `billing_status` to be `BILLING_OPEN`
    (otherwise `ERR_ENCOUNTER_BAD_BILLING_STATE`) and requires the `clinical_status` to be
    `CANCELLED` — void-billing exists only for cancelled encounters (otherwise
    `ERR_ENCOUNTER_NOT_CANCELLED`)."

    Design: Difficulty/transitive_cascade/void_billing_cascade_charge_then_deductible_depth3
    """
    # SCHEDULED (not cancelled) encounter -> void-billing rejected.
    provider, patient, enc = setup_provider_patient_encounter()
    res = api.void_billing(enc["id"], BILLING)
    validate_error(res, "ERR_ENCOUNTER_NOT_CANCELLED")


def test_deductible_conserved_across_post_then_void(api):
    """PRD §3.8: "Voiding increments the charge's `version` and runs two conservation
    compensations. First, if the charge's `pay_path` is `INSURANCE`, the patient's
    `insurance_deductible_remaining_cents` is increased by the charge's
    `deductible_applied_cents`, restoring whatever deductible the charge had consumed."

    Design: Difficulty/compensating_invariant/deductible_conserved_across_post_then_void
    """
    provider, patient, enc = setup_provider_patient_encounter(
        patient_overrides={"has_active_insurance": True,
                           "insurance_coinsurance_rate": 0.2,
                           "insurance_deductible_remaining_cents": 5000},
        encounter_overrides={"scheduled_at": "2026-01-16T09:00:00Z"},
    )
    ch = validate_success(api.create_charge({
        "patient_id": patient["id"], "encounter_id": enc["id"],
        "source_kind": "ENCOUNTER", "charge_kind": "OFFICE_VISIT",
        "billed_amount_cents": 20000, "insurer_allowed_cents": 20000,
    }, BILLING), 201)
    assert ch["deductible_applied_cents"] == 5000
    # full draw -> remaining 0
    p_mid = validate_success(api.get_patient(patient["id"], BILLING), 200)
    assert p_mid["insurance_deductible_remaining_cents"] == 0

    voided = validate_success(api.void_charge(ch["id"], BILLING), 200)
    assert voided["status"] == "VOIDED"
    assert voided["deductible_applied_cents"] == 5000
    p_after = validate_success(api.get_patient(patient["id"], BILLING), 200)
    assert p_after["insurance_deductible_remaining_cents"] == 5000


def test_deductible_restored_only_for_consumed_amount(api):
    """PRD §3.8: "First, if the charge's `pay_path` is `INSURANCE`, the patient's
    `insurance_deductible_remaining_cents` is increased by the charge's
    `deductible_applied_cents`, restoring whatever deductible the charge had consumed."

    Design: Difficulty/compensating_invariant/deductible_conserved_across_post_then_void
    """
    # deductible 8000, allowed 5000 -> ded applied 5000, remaining 3000; void restores to 8000
    provider, patient, enc = setup_provider_patient_encounter(
        patient_overrides={"has_active_insurance": True,
                           "insurance_coinsurance_rate": 0.2,
                           "insurance_deductible_remaining_cents": 8000},
        encounter_overrides={"scheduled_at": "2026-03-16T09:00:00Z"},
    )
    ch = validate_success(api.create_charge({
        "patient_id": patient["id"], "encounter_id": enc["id"],
        "source_kind": "ENCOUNTER", "charge_kind": "OFFICE_VISIT",
        "billed_amount_cents": 5000, "insurer_allowed_cents": 5000,
    }, BILLING), 201)
    assert ch["deductible_applied_cents"] == 5000
    validate_success(api.void_charge(ch["id"], BILLING), 200)
    p_after = validate_success(api.get_patient(patient["id"], BILLING), 200)
    assert p_after["insurance_deductible_remaining_cents"] == 8000


def test_membership_wallet_conserved_across_redeem_then_void(api):
    """PRD §3.8: "Second, if the charge's `source_kind` is `COSMETIC_TREATMENT`, the linked
    `CosmeticTreatment`'s `redeemed_cents` (found via the charge's `cosmetic_treatment_id`) is
    added back to that treatment's `CosmeticMembership` wallet `unit_balance_cents`; the
    membership's status is not auto-reverted from `EXHAUSTED` — only the wallet balance is
    restored."

    Design: Difficulty/compensating_invariant/membership_wallet_conserved_across_redeem_then_void
    """
    provider, patient, enc, mem = setup_cosmetic_encounter_with_membership(
        tier="GOLD", purchased_unit_cents=50000
    )
    # GOLD purchased 50000 -> wallet 55000.
    assert mem["unit_balance_cents"] == 55000
    t = redeem_treatment(enc["id"], mem["id"], mem["version"],
                         service_name="botox", list_price_cents=20000)
    # list 20000 -> disc round(20000*0.85)=17000, redeemed 17000, wallet -> 38000
    assert t["redeemed_cents"] == 17000
    ch = validate_success(api.create_charge({
        "patient_id": patient["id"], "encounter_id": enc["id"],
        "source_kind": "COSMETIC_TREATMENT", "charge_kind": "COSMETIC",
        "billed_amount_cents": 0, "cosmetic_treatment_id": t["id"],
    }, BILLING), 201)

    voided = validate_success(api.void_charge(ch["id"], BILLING), 200)
    assert voided["status"] == "VOIDED"
    t_after = validate_success(api.get_cosmetic_treatment(t["id"], BILLING), 200)
    assert t_after["redeemed_cents"] == 17000
    mem_after = validate_success(api.get_cosmetic_membership(mem["id"], BILLING), 200)
    assert mem_after["unit_balance_cents"] == 55000


def test_wallet_restored_after_void_full_drain(api):
    """PRD §3.8: "Second, if the charge's `source_kind` is `COSMETIC_TREATMENT`, the linked
    `CosmeticTreatment`'s `redeemed_cents` (found via the charge's `cosmetic_treatment_id`) is
    added back to that treatment's `CosmeticMembership` wallet `unit_balance_cents`; the
    membership's status is not auto-reverted from `EXHAUSTED` — only the wallet balance is
    restored."

    Design: Difficulty/compensating_invariant/membership_wallet_conserved_across_redeem_then_void
    """
    # SILVER purchased 9000 -> wallet 9000; list 10000 -> disc round(10000*0.95)=9500,
    # redeemed=min(9500,9000)=9000, wallet -> 0, membership EXHAUSTED.
    provider, patient, enc, mem = setup_cosmetic_encounter_with_membership(
        tier="SILVER", purchased_unit_cents=9000
    )
    assert mem["unit_balance_cents"] == 9000
    t = redeem_treatment(enc["id"], mem["id"], mem["version"],
                         service_name="peel", list_price_cents=10000)
    assert t["redeemed_cents"] == 9000
    mem_mid = validate_success(api.get_cosmetic_membership(mem["id"], BILLING), 200)
    assert mem_mid["unit_balance_cents"] == 0
    assert mem_mid["status"] == "EXHAUSTED"

    ch = validate_success(api.create_charge({
        "patient_id": patient["id"], "encounter_id": enc["id"],
        "source_kind": "COSMETIC_TREATMENT", "charge_kind": "COSMETIC",
        "billed_amount_cents": 0, "cosmetic_treatment_id": t["id"],
    }, BILLING), 201)
    validate_success(api.void_charge(ch["id"], BILLING), 200)
    mem_after = validate_success(api.get_cosmetic_membership(mem["id"], BILLING), 200)
    # wallet restored by redeemed 9000; status NOT auto-reverted from EXHAUSTED
    assert mem_after["unit_balance_cents"] == 9000
    assert mem_after["status"] == "EXHAUSTED"
