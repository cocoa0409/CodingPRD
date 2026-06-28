"""Corner coverage: calculation correctness (membership grant, biopsy recall horizon,
cosmetic summary), business validations (Mohs/credential/interval/allowed-amount/step-therapy/
billing-lock/membership-active), RBAC, FK reverse-lists, and the cross-cutting OCC layer."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, api_client,
    set_clock, create_patient, create_provider, create_encounter, create_room,
    setup_encounter_in_progress, setup_biopsy_in_state,
    setup_provider_patient_encounter, setup_active_membership,
    setup_cosmetic_encounter_with_membership, redeem_treatment, setup_prior_authorization,
    setup_encounter_billing_finalized,
    assert_same_instant,
    build_user_headers,
    TEST_USERS,
)
from test_helpers.test_users import make_provider_headers

FRONT = TEST_USERS["front_desk_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]
PATHLAB = TEST_USERS["path_lab_headers"]
ADMIN = TEST_USERS["practice_admin_headers"]


# ---- calculations section ----
def test_membership_grant_gold_bonus_applied(api):
    """PRD §3.6: "Activation grants the wallet: the `unit_balance_cents` is set to the prepaid
    amount plus a tier bonus, where the bonus is the prepaid amount multiplied by the tier's
    bonus rate — 0 percent for `SILVER` and 10 percent for `GOLD` — rounded half-up to whole
    cents. Thus a `SILVER` activation grants exactly the prepaid amount, while a `GOLD`
    activation grants the prepaid amount plus ten percent of it."

    Design: Corner/calculations/membership_grant_gold_bonus_applied
    """
    patient = create_patient(full_name="Grant Pat", date_of_birth="1982-11-11")
    _, mem_g = setup_active_membership(tier="GOLD", purchased_unit_cents=30000, patient=patient)
    _, mem_s = setup_active_membership(tier="SILVER", purchased_unit_cents=30000, patient=patient)
    assert mem_g["unit_balance_cents"] == 33000
    assert mem_s["unit_balance_cents"] == 30000


def test_biopsy_recall_horizon_benign_twelve_months(api):
    """PRD §3.5: "a `BENIGN` result yields a twelve-month horizon"
    PRD §3.5: "Sign-out then spawns a follow-up recall: a `RecallReminder` is created with
    `reason` of `BIOPSY_FOLLOWUP`, its `biopsy_id` set to this biopsy, a `due_at` equal to the
    clock's current time plus `recall_months` months, and a `status` of `PENDING`"

    Design: Corner/calculations/biopsy_recall_horizon_benign_twelve_months
    """
    set_clock("2026-03-01T00:00:00Z")
    provider, patient, enc, biopsy = setup_biopsy_in_state(
        "RESULTED", result="BENIGN",
        encounter_overrides={"scheduled_at": "2026-03-01T09:00:00Z"},
    )
    prov_headers = make_provider_headers(provider["id"])
    signed = validate_success(api.sign_out_biopsy(biopsy["id"], prov_headers), 200)
    assert signed["recall_months"] == 12

    data, _ = validate_paginated(
        api.list_recall_reminders(FRONT, params={"biopsy_id": biopsy["id"]}))
    followups = [r for r in data if r["reason"] == "BIOPSY_FOLLOWUP"]
    assert len(followups) == 1
    # due_at = "the clock's current time plus recall_months months" (instant pinned by
    # PRD §3.5; serialization is not pinned, so compare by instant not exact string).
    assert_same_instant(followups[0]["due_at"], "2027-03-01T00:00:00Z")
    assert followups[0]["status"] == "PENDING"


def test_cosmetic_summary_order_pinned_total_due(api):
    """PRD §3.6: "The total due is then the sum of `out_of_pocket_cents` over those
    treatments, expressed in whole cents; the read returns the `encounter_id`, the
    `total_due_cents`, and the `treatment_count`."

    Design: Corner/calculations/cosmetic_summary_order_pinned_total_due
    """
    # GOLD purchased 10000 -> wallet 11000; two list-8000 treatments:
    # disc each round(8000*0.85)=6800. t1: redeemed min(6800,11000)=6800, out 0, wallet 4200.
    # t2: redeemed min(6800,4200)=4200, out 2600. total_due 2600.
    provider, patient, enc, mem = setup_cosmetic_encounter_with_membership(
        tier="GOLD", purchased_unit_cents=10000
    )
    t1 = redeem_treatment(enc["id"], mem["id"], mem["version"],
                          service_name="t1", list_price_cents=8000)
    mem_after_t1 = validate_success(api.get_cosmetic_membership(mem["id"], BILLING), 200)
    t2 = redeem_treatment(enc["id"], mem["id"], mem_after_t1["version"],
                          service_name="t2", list_price_cents=8000)

    summary = validate_success(api.get_cosmetic_summary(enc["id"], BILLING), 200)
    assert summary["total_due_cents"] == 2600
    assert summary["treatment_count"] == 2
    assert t1["out_of_pocket_cents"] == 0
    assert t2["out_of_pocket_cents"] == 2600


# ---- validations section ----
def test_mohs_on_standard_room_rejected(api):
    """PRD §3.4: "First, if the procedure kind is `MOHS`, the room's `room_kind` must be
    `MOHS_SUITE`; otherwise the booking is rejected with `ERR_MOHS_REQUIRES_MOHS_SUITE`."

    Design: Corner/validations/mohs_on_standard_room_rejected
    """
    provider = create_provider(full_name="Dr MohsX", can_perform_mohs=True)
    patient = create_patient(full_name="MohsX Pat", date_of_birth="1959-02-14")
    enc = create_encounter(patient["id"], provider["id"], visit_type="MEDICAL",
                           scheduled_at="2026-01-24T09:00:00Z")
    room = create_room(name="Std X", room_kind="STANDARD", turnover_buffer_minutes=0)
    res = api.create_procedure_booking({
        "room_id": room["id"], "provider_id": provider["id"], "encounter_id": enc["id"],
        "procedure_kind": "MOHS", "start_at": "2026-01-24T10:00:00Z",
        "end_at": "2026-01-24T12:00:00Z", "expected_room_version": room["version"],
    }, FRONT)
    validate_error(res, "ERR_MOHS_REQUIRES_MOHS_SUITE")


def test_mohs_with_uncredentialed_provider_rejected(api):
    """PRD §3.4: "Second, if the procedure kind is `MOHS`, the booked provider's
    `can_perform_mohs` must be `true`; otherwise the booking is rejected with
    `ERR_PROVIDER_NOT_MOHS_CREDENTIALED`."

    Design: Corner/validations/mohs_with_uncredentialed_provider_rejected
    """
    provider = create_provider(full_name="Dr NoMohs", can_perform_mohs=False)
    patient = create_patient(full_name="NoMohs Pat", date_of_birth="1958-03-15")
    enc = create_encounter(patient["id"], provider["id"], visit_type="MEDICAL",
                           scheduled_at="2026-01-24T13:00:00Z")
    room = create_room(name="Mohs X", room_kind="MOHS_SUITE", turnover_buffer_minutes=0)
    res = api.create_procedure_booking({
        "room_id": room["id"], "provider_id": provider["id"], "encounter_id": enc["id"],
        "procedure_kind": "MOHS", "start_at": "2026-01-24T14:00:00Z",
        "end_at": "2026-01-24T16:00:00Z", "expected_room_version": room["version"],
    }, FRONT)
    validate_error(res, "ERR_PROVIDER_NOT_MOHS_CREDENTIALED")


def test_booking_inverted_interval_rejected(api):
    """PRD §3.4: "Third, `end_at` must be strictly after `start_at`; an interval whose end is
    not after its start is rejected with `ERR_INVALID_INTERVAL`."

    Design: Corner/validations/booking_inverted_interval_rejected
    """
    provider = create_provider(full_name="Dr Itv")
    patient = create_patient(full_name="Itv Pat", date_of_birth="1992-04-16")
    enc = create_encounter(patient["id"], provider["id"], visit_type="MEDICAL",
                           scheduled_at="2026-01-25T09:00:00Z")
    room = create_room(name="Std Itv", room_kind="STANDARD", turnover_buffer_minutes=0)
    res = api.create_procedure_booking({
        "room_id": room["id"], "provider_id": provider["id"], "encounter_id": enc["id"],
        "procedure_kind": "EXCISION", "start_at": "2026-01-25T10:00:00Z",
        "end_at": "2026-01-25T10:00:00Z", "expected_room_version": room["version"],
    }, FRONT)
    validate_error(res, "ERR_INVALID_INTERVAL")


def test_insurance_charge_missing_allowed_amount_rejected(api):
    """PRD §3.7: "On the `INSURANCE` path a non-null `insurer_allowed_cents` is required; on
    the `CASH` path it must be omitted or null. A violation of either rule is rejected with
    `ERR_ALLOWED_AMOUNT_REQUIRED`."

    Design: Corner/validations/insurance_charge_missing_allowed_amount_rejected
    """
    _, patient, enc = setup_provider_patient_encounter(
        patient_overrides={"has_active_insurance": True,
                           "insurance_coinsurance_rate": 0.2,
                           "insurance_deductible_remaining_cents": 0},
        encounter_overrides={"scheduled_at": "2026-01-26T09:00:00Z"},
    )
    res = api.create_charge({
        "patient_id": patient["id"], "encounter_id": enc["id"],
        "source_kind": "ENCOUNTER", "charge_kind": "OFFICE_VISIT",
        "billed_amount_cents": 10000,  # insurer_allowed_cents omitted on INSURANCE path
    }, BILLING)
    validate_error(res, "ERR_ALLOWED_AMOUNT_REQUIRED")


def test_step_therapy_not_met_blocks_submit(api):
    """PRD §3.9: "Submission requires the current status to be `DRAFT` (otherwise
    `ERR_PA_BAD_STATE`) and requires step therapy to be met, that is, `satisfied_step_count`
    at least `required_step_count` (otherwise `ERR_STEP_THERAPY_NOT_MET`)."
    PRD §3.9: "the prior authorization's `satisfied_step_count` is the count of its child
    trials whose `outcome` is `FAILED`"

    Design: Corner/validations/step_therapy_not_met_blocks_submit
    """
    patient = create_patient(full_name="Stp Pat", date_of_birth="1967-06-18")
    pa = validate_success(api.create_prior_authorization({
        "patient_id": patient["id"], "drug_name": "biologic-S",
        "required_step_count": 2, "list_price_cents": 80000,
    }, BILLING), 201)
    validate_success(api.create_step_therapy_trial(
        pa["id"], {"drug_name": "only-step", "outcome": "FAILED"}, BILLING), 201)
    res = api.submit_prior_authorization(pa["id"], BILLING)
    validate_error(res, "ERR_STEP_THERAPY_NOT_MET")
    pa_after = validate_success(api.get_prior_authorization(pa["id"], BILLING), 200)
    assert pa_after["satisfied_step_count"] == 1


def test_charge_on_finalized_encounter_billing_locked(api):
    """PRD §3.7: "No charge may be posted against an encounter whose `billing_status` is not
    `BILLING_OPEN`; such an attempt is rejected with `ERR_ENCOUNTER_BILLING_LOCKED`."

    Design: Corner/validations/charge_on_finalized_encounter_billing_locked
    """
    provider, patient, enc = setup_encounter_billing_finalized()
    assert enc["billing_status"] == "BILLING_FINALIZED"
    res = api.create_charge({
        "patient_id": patient["id"], "encounter_id": enc["id"],
        "source_kind": "ENCOUNTER", "charge_kind": "OFFICE_VISIT",
        "billed_amount_cents": 10000,
    }, BILLING)
    validate_error(res, "ERR_ENCOUNTER_BILLING_LOCKED")


def test_cosmetic_treatment_on_inactive_membership_rejected(api):
    """PRD §3.6: "The treatment is only permitted when its encounter's `visit_type` is
    `COSMETIC` and its membership's `status` is `ACTIVE`; if either condition fails, the
    redemption is rejected with `ERR_MEMBERSHIP_NOT_ACTIVE`."

    Design: Corner/validations/cosmetic_treatment_on_inactive_membership_rejected
    """
    provider = create_provider(full_name="Dr Pnd")
    patient = create_patient(full_name="Pnd Pat", date_of_birth="1989-08-20")
    enc = create_encounter(patient["id"], provider["id"], visit_type="COSMETIC",
                           scheduled_at="2026-01-28T09:00:00Z")
    mem = validate_success(api.create_cosmetic_membership({
        "patient_id": patient["id"], "tier": "GOLD", "purchased_unit_cents": 50000,
    }, BILLING), 201)  # PENDING, not activated
    res = api.create_cosmetic_treatment({
        "encounter_id": enc["id"], "membership_id": mem["id"],
        "service_name": "x", "list_price_cents": 10000,
        "expected_membership_version": mem["version"],
    }, BILLING)
    validate_error(res, "ERR_MEMBERSHIP_NOT_ACTIVE")


# ---- rbac section ----
def test_frontdesk_cannot_post_charges(api):
    """PRD §2.1: "If the headers are present but the declared role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §2.1: "`BillingSpecialist` owns the revenue cycle — charges, prior authorizations and
    step therapy, cosmetic memberships, and the billing finalize/void transitions."

    Design: Corner/rbac/frontdesk_cannot_post_charges
    """
    provider, patient, enc = setup_provider_patient_encounter(
        encounter_overrides={"scheduled_at": "2026-01-29T09:00:00Z"})
    res = api.create_charge({
        "patient_id": patient["id"], "encounter_id": enc["id"],
        "source_kind": "ENCOUNTER", "charge_kind": "OFFICE_VISIT",
        "billed_amount_cents": 5000,
    }, FRONT)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_pathlab_cannot_sign_out_biopsy(api):
    """PRD §2.1: "`PathLab` is a narrow role that posts biopsy pathology results and nothing
    else."
    PRD §3.5: "A `Provider` signs out a resulted biopsy, moving `RESULTED → SIGNED_OUT`,
    permitted only from `RESULTED` (otherwise `ERR_BIOPSY_BAD_STATE`)."

    Design: Corner/rbac/pathlab_cannot_sign_out_biopsy
    """
    provider, patient, enc, biopsy = setup_biopsy_in_state("RESULTED", result="BENIGN")
    res = api.sign_out_biopsy(biopsy["id"], PATHLAB)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "Every request to the API must carry two mandatory HTTP headers: `X-User-ID`,
    which identifies the acting operator, and `X-User-Role`, which declares the operational
    capacity under which the request is made. If either header is missing or malformed, the
    request is rejected with `ERR_MISSING_AUTH_CONTEXT`."

    Design: Corner/rbac/missing_auth_headers_rejected
    """
    res = api._request("GET", "/patients", headers={})
    validate_error(res, "ERR_MISSING_AUTH_CONTEXT")


# ---- endpoints section ----
def test_fk_reverse_list_biopsies_by_encounter(api):
    """PRD §2.8: "relationships are navigated through filtered list endpoints rather than
    nested URL paths."
    PRD §3.5: "the biopsy's `patient_id` is copied from that encounter at creation."

    Design: Corner/endpoints/fk_reverse_list_biopsies_by_encounter
    """
    provider, patient, enc, biopsy = setup_biopsy_in_state("COLLECTED")
    prov_headers = make_provider_headers(provider["id"])
    data, _ = validate_paginated(
        api.list_biopsies(prov_headers, params={"encounter_id": enc["id"]}))
    assert len(data) == 1
    assert data[0]["id"] == biopsy["id"]
    assert data[0]["patient_id"] == patient["id"]


def test_charge_post_nonexistent_patient_fk_not_found(api):
    """PRD §2.8: "when a write body carries a foreign-key reference such as `patient_id`,
    `encounter_id`, `room_id`, `provider_id`, `membership_id`, or `prior_auth_id` — the
    referenced rows must exist"
    PRD §2.8: "an unresolved patient yields `ERR_PATIENT_NOT_FOUND`"

    Design: Corner/endpoints/charge_post_nonexistent_patient_fk_not_found
    """
    provider, patient, enc = setup_provider_patient_encounter(
        encounter_overrides={"scheduled_at": "2026-01-31T09:00:00Z"})
    res = api.create_charge({
        "patient_id": "00000000-0000-4000-8000-000000000999",
        "encounter_id": enc["id"],
        "source_kind": "ENCOUNTER", "charge_kind": "OFFICE_VISIT",
        "billed_amount_cents": 5000,
    }, BILLING)
    validate_error(res, "ERR_PATIENT_NOT_FOUND")


# ---- cross_cutting_complexity_layers section ----
def test_occ_correct_room_version_succeeds_and_bumps(api):
    """PRD §3.4: "A new booking begins in `status` `BOOKED`, and a successful create
    increments the room's `version` by one to record that the room's interval set has
    changed."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_room_version_succeeds_and_bumps
    """
    provider = create_provider(full_name="Dr Occ")
    patient = create_patient(full_name="Occ Pat", date_of_birth="1994-01-25")
    enc = create_encounter(patient["id"], provider["id"], visit_type="MEDICAL",
                           scheduled_at="2026-02-02T09:00:00Z")
    room = create_room(name="Occ Room", room_kind="STANDARD", turnover_buffer_minutes=0)
    assert room["version"] == 1
    b = validate_success(api.create_procedure_booking({
        "room_id": room["id"], "provider_id": provider["id"], "encounter_id": enc["id"],
        "procedure_kind": "EXCISION", "start_at": "2026-02-02T10:00:00Z",
        "end_at": "2026-02-02T11:00:00Z", "expected_room_version": room["version"],
    }, FRONT), 201)
    assert b["status"] == "BOOKED"
    room_after = validate_success(api.get_room(room["id"], ADMIN), 200)
    assert room_after["version"] == 2


def test_occ_stale_membership_version_rejected(api):
    """PRD §2.7: "Before any balance arithmetic runs, the server compares
    `expected_membership_version` against the membership's current `version`. If a prior
    redemption has advanced the membership's version since the client last read it, the create
    is rejected with `ERR_STALE_MEMBERSHIP_VERSION` (HTTP 412), because the client's view of
    the wallet balance is stale and must not be drawn against."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_membership_version_rejected
    """
    provider, patient, enc, mem = setup_cosmetic_encounter_with_membership(
        tier="GOLD", purchased_unit_cents=100000
    )
    mem_v1 = mem["version"]
    # First redemption advances the membership version.
    t1 = redeem_treatment(enc["id"], mem["id"], mem_v1,
                          service_name="first", list_price_cents=10000)
    # Second redemption still carries the pre-redemption version (stale).
    res = api.create_cosmetic_treatment({
        "encounter_id": enc["id"], "membership_id": mem["id"],
        "service_name": "second-stale", "list_price_cents": 10000,
        "expected_membership_version": mem_v1,
    }, BILLING)
    validate_error(res, "ERR_STALE_MEMBERSHIP_VERSION", expected_status=412)


def test_booking_cancel_frees_room_interval(api):
    """PRD §3.4: "`FrontDesk` may cancel a booking, moving `BOOKED → CANCELLED`, permitted
    only from `BOOKED` (otherwise `ERR_BOOKING_BAD_STATE`); cancellation increments the
    booking's `version` and frees the room interval so a later booking on the same room may
    reuse the time window."

    Design: Corner/cross_cutting_complexity_layers/booking_cancel_frees_room_interval
    """
    provider = create_provider(full_name="Dr Free")
    patient = create_patient(full_name="Free Pat", date_of_birth="1990-03-27")
    enc = create_encounter(patient["id"], provider["id"], visit_type="MEDICAL",
                           scheduled_at="2026-02-04T09:00:00Z")
    room = create_room(name="Free Room", room_kind="STANDARD", turnover_buffer_minutes=0)
    b1 = validate_success(api.create_procedure_booking({
        "room_id": room["id"], "provider_id": provider["id"], "encounter_id": enc["id"],
        "procedure_kind": "EXCISION", "start_at": "2026-02-04T10:00:00Z",
        "end_at": "2026-02-04T11:00:00Z", "expected_room_version": room["version"],
    }, FRONT), 201)
    validate_success(api.cancel_procedure_booking(b1["id"], FRONT), 200)
    room_now = validate_success(api.get_room(room["id"], ADMIN), 200)
    # Re-book the exact same room+time window; freed interval should permit it.
    b2 = validate_success(api.create_procedure_booking({
        "room_id": room["id"], "provider_id": provider["id"], "encounter_id": enc["id"],
        "procedure_kind": "EXCISION", "start_at": "2026-02-04T10:00:00Z",
        "end_at": "2026-02-04T11:00:00Z", "expected_room_version": room_now["version"],
    }, FRONT), 201)
    assert b2["status"] == "BOOKED"
