"""Controlled analgesic orders, the patient MME ledger and breakthrough dosing."""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    assert_medication_order,
    assert_mme_ledger,
    assert_same_instant,
    find_by_id,
)
from test_helpers import factories as f
from test_helpers.fixtures import (
    INTAKE,
    NURSE,
    PHYSICIAN,
    active_medication_order,
    enroll_patient,
    mme_review_medication_order,
    read_patient,
    set_clock,
    verify_medication_order,
    write_medication_order,
)


def _read_order(api, patient_id, order_id):
    rows, _ = validate_paginated(
        api.list_patient_medication_orders(patient_id, PHYSICIAN, params={"limit": 100})
    )
    order = find_by_id(rows, order_id)
    assert order is not None, f"medication order {order_id} not returned for the patient"
    return order


def _naive_patient_with_two_orders():
    """Opioid-naive patient carrying two ACTIVE orders, both breaking through on morphine."""
    patient, _ = enroll_patient(
        clock="2026-06-01T00:00:00Z",
        full_name="Cara Nwosu",
        opioid_status="OPIOID_NAIVE",
    )
    first = active_medication_order(
        patient["id"],
        drug="MORPHINE_PO",
        dose_amount=5,
        days_supply=30,
        breakthrough_drug="MORPHINE_PO",
    )
    second_draft = write_medication_order(
        patient["id"],
        drug="OXYCODONE_PO",
        dose_amount=55,
        days_supply=30,
        breakthrough_drug="MORPHINE_PO",
    )
    second = verify_medication_order(second_draft["id"], note="second clinician check")
    return patient, first, second


# ---------------------------------------------------------------------------
# Per-order rounding then summation
# ---------------------------------------------------------------------------
def test_each_order_is_rounded_before_the_patient_total_is_summed(api):
    """PRD 3.8: "Under `TOLERANT` the raw conversion is used unmodified and
    rounded half up to one decimal place to give `mme_daily`. Under `NAIVE` the
    raw conversion is first scaled by a safety factor of three quarters — 0.75 —
    and the result then rounded half up to one decimal place, so an identical drug
    and dose yields a strictly smaller `mme_daily` for an opioid-naive patient."
    PRD 3.8: "First, take each of the patient's medication orders whose `status`
    is exactly `ACTIVE` — orders in `PENDING_VERIFICATION`, `REVIEW_REQUIRED` or
    `DISCONTINUED` are excluded — and use each one's `mme_daily` as it was already
    rounded to one decimal place at order time. Second, sum those already-rounded
    values to get the patient's 24-hour total."

    Design: Difficulty/combinatorial_formula/breakthrough_dose_pins_round_per_order_then_sum
    """
    patient, first, second = _naive_patient_with_two_orders()

    assert_medication_order(first)
    assert_medication_order(second)
    assert first["mme_daily"] == pytest.approx(3.8, abs=1e-9), (
        f"5 mg morphine scaled by 0.75 is 3.75, rounded half up to 3.8, got {first['mme_daily']}"
    )
    assert second["mme_variant"] == "NAIVE"
    assert second["mme_daily"] == pytest.approx(61.9, abs=1e-9), (
        "55 mg oxycodone times 1.5 is 82.5, scaled by 0.75 is 61.875, rounded to 61.9, "
        f"got {second['mme_daily']}"
    )

    assert_mme_ledger(read_patient(patient["id"]), 65.7)


def test_breakthrough_dose_takes_fifteen_percent_of_the_rounded_sum(api):
    """PRD 3.8: "Third, take 15 percent of that **sum** — never 15 percent of each
    order separately. Fourth, convert the resulting milligram-equivalents into the
    breakthrough agent by dividing by that agent's conversion factor (1.0 for
    `MORPHINE_PO`, 1.5 for `OXYCODONE_PO`, 5.0 for `HYDROMORPHONE_PO`), and round
    half up to one decimal place — once, at this final step and nowhere else."
    PRD 3.8: "Summing unrounded conversions and rounding only at the end produces
    different milligrams for the same orders and is not what this system does."

    Design: Difficulty/combinatorial_formula/breakthrough_dose_pins_round_per_order_then_sum
    """
    patient, first, second = _naive_patient_with_two_orders()

    assert second["breakthrough_dose_mg"] == pytest.approx(9.9, abs=1e-9), (
        "15 per cent of the rounded 65.7 is 9.855, rounded half up to 9.9; summing the "
        f"unrounded 65.625 first would give 9.8. Got {second['breakthrough_dose_mg']}"
    )
    assert second["breakthrough_dose_mg"] != pytest.approx(9.8, abs=1e-9)

    refreshed_first = _read_order(api, patient["id"], first["id"])
    assert refreshed_first["breakthrough_dose_mg"] == pytest.approx(9.9, abs=1e-9), (
        "breakthrough_dose_mg is recomputed for every order of the patient whenever an "
        f"order enters ACTIVE, got {refreshed_first['breakthrough_dose_mg']}"
    )


# ---------------------------------------------------------------------------
# Request shape and defaults
# ---------------------------------------------------------------------------
def test_a_medication_order_without_a_drug_is_rejected_and_persists_nothing(api):
    """PRD 3.8: "A `PalliativePhysician` writes a controlled analgesic order
    carrying `patient_id`, a `drug` of `MORPHINE_PO`, `OXYCODONE_PO`,
    `HYDROMORPHONE_PO` or `FENTANYL_TD`, a `dose_amount` that must be greater than
    zero — milligrams per day for the three oral drugs, micrograms per hour for
    the transdermal fentanyl patch — a `days_supply` that is an integer from 1 to
    90 inclusive, and an optional `breakthrough_drug` naming the agent used for
    breakthrough dosing, which may be `MORPHINE_PO`, `OXYCODONE_PO` or
    `HYDROMORPHONE_PO` and is null when no breakthrough dose is ordered."
    PRD 2.5: "**Request shape.** Every required body field is present; every field
    holds a value of its declared type; every enum-typed field carries a declared
    member of that enum; every bounded numeric field lies inside its declared
    range; and every datetime pair satisfies its ordering rule, meaning
    `scheduled_end` is strictly after `scheduled_start` and `delivery_window_end`
    is strictly after `delivery_window_start`. Otherwise `ERR_VALIDATION` (400)."

    Design: Corner/entities/medication_order_missing_required_drug_returns_validation
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Cai Duarte")

    rejected = api.create_medication_order(
        {"patient_id": patient["id"], "dose_amount": 30, "days_supply": 14}, PHYSICIAN
    )
    validate_error(rejected, ApiErrorId.ERR_VALIDATION.value, 400)

    rows, meta = validate_paginated(
        api.list_patient_medication_orders(patient["id"], PHYSICIAN)
    )
    assert rows == [], f"no order may have been persisted, got {rows}"
    assert meta["total_count"] == 0


def test_omitting_opioid_status_defaults_the_patient_to_opioid_naive(api):
    """PRD 3.1: "An optional `opioid_status` may be supplied as `OPIOID_NAIVE` or
    `OPIOID_TOLERANT`; when omitted it defaults to `OPIOID_NAIVE`, and it later
    selects which conversion variant governs this patient's analgesic orders."
    PRD 3.8: "`breakthrough_dose_mg` is null whenever `breakthrough_drug` is
    null."

    Design: Corner/entities/patient_opioid_status_defaults_to_opioid_naive_when_omitted
    """
    set_clock("2026-06-01T00:00:00Z")
    payload = f.patient_payload(full_name="Dana Krol")
    payload.pop("opioid_status")

    patient = validate_success(api.create_patient(payload, INTAKE), 201)
    referral = validate_success(
        api.create_referral(f.referral_payload(patient["id"]), INTAKE), 201
    )
    validate_success(api.decide_referral(referral["id"], {"decision": "ACCEPT"}, INTAKE))

    assert patient["opioid_status"] == "OPIOID_NAIVE"

    order = write_medication_order(
        patient["id"], drug="MORPHINE_PO", dose_amount=40, days_supply=14
    )
    assert order["mme_variant"] == "NAIVE"
    assert order["mme_daily"] == pytest.approx(30.0, abs=1e-9), (
        f"40 mg morphine scaled by 0.75 is 30.0, got {order['mme_daily']}"
    )
    assert order["breakthrough_dose_mg"] is None


# ---------------------------------------------------------------------------
# The review threshold
# ---------------------------------------------------------------------------
def test_reaching_exactly_ninety_parks_the_order_until_a_physician_reviews_it(api):
    """PRD 3.8: "When the sum is **strictly below** 90, the order moves
    `PENDING_VERIFICATION → ACTIVE`: `verifier_user_id` is stamped from
    `X-User-ID`, `last_fill_at` is set to the current logical clock,
    `next_refill_allowed_at` becomes `last_fill_at` plus `days_supply` days minus
    2 days, the patient's `active_daily_mme` increases by this order's
    `mme_daily`, and `breakthrough_dose_mg` is recomputed. When the sum is **at or
    above** 90, the order moves `PENDING_VERIFICATION → REVIEW_REQUIRED` instead:
    `verifier_user_id` is still stamped, but the patient's `active_daily_mme` is
    deliberately **not** changed, because an order in review is not in force."
    PRD 3.8: "That moves the order `REVIEW_REQUIRED → ACTIVE`, increments
    `mme_review_count` by 1, sets `last_fill_at` to the current clock, recomputes
    `next_refill_allowed_at` by the same rule, and increases the patient's
    `active_daily_mme` by this order's `mme_daily`."

    Design: Corner/state_machines/medication_order_parks_in_review_required_then_physician_review_activates_it
    """
    patient, _ = enroll_patient(
        clock="2026-06-01T00:00:00Z", full_name="Kofi Mensah", opioid_status="OPIOID_TOLERANT"
    )
    first = active_medication_order(
        patient["id"], drug="MORPHINE_PO", dose_amount=89, days_supply=14
    )
    assert first["status"] == "ACTIVE"
    assert first["mme_daily"] == pytest.approx(89.0, abs=1e-9)

    second_draft = write_medication_order(
        patient["id"], drug="MORPHINE_PO", dose_amount=1, days_supply=14
    )
    parked = verify_medication_order(second_draft["id"])
    assert parked["status"] == "REVIEW_REQUIRED", (
        "89.0 + 1.0 reaches exactly the review threshold, which is inclusive"
    )
    assert_mme_ledger(read_patient(patient["id"]), 89.0)

    released = mme_review_medication_order(
        second_draft["id"], note="risk-benefit reviewed, naloxone co-prescribed"
    )
    assert released["status"] == "ACTIVE"
    assert released["mme_review_count"] == 1
    assert released["verifier_user_id"] == "u_nurse_1", (
        "verifier_user_id was stamped by the VERIFICATION attestation and is not restamped"
    )
    assert_mme_ledger(read_patient(patient["id"]), 90.0)


def test_the_same_dose_converts_differently_for_naive_and_tolerant_patients(api):
    """PRD 3.8: "Daily strength is expressed in **morphine milligram
    equivalents**. The conversion factor is 1.0 for `MORPHINE_PO`, 1.5 for
    `OXYCODONE_PO`, 5.0 for `HYDROMORPHONE_PO` and 2.4 for `FENTANYL_TD`; the raw
    conversion is `dose_amount` multiplied by that factor."
    PRD 3.8: "Which variant then applies is decided by the patient: `mme_variant`
    is `TOLERANT` when the patient's `opioid_status` is `OPIOID_TOLERANT` and
    `NAIVE` when it is `OPIOID_NAIVE`."

    Design: Corner/calculations/medication_daily_mme_naive_and_tolerant_variants_diverge_on_identical_dose
    """
    tolerant, _ = enroll_patient(
        clock="2026-06-01T00:00:00Z", full_name="Pia Toomas", opioid_status="OPIOID_TOLERANT"
    )
    naive, _ = enroll_patient(
        clock=None,
        full_name="Rex Ibarra",
        opioid_status="OPIOID_NAIVE",
        attending_clinician_user_id="u_attending_2",
    )

    tolerant_order = write_medication_order(
        tolerant["id"],
        drug="MORPHINE_PO",
        dose_amount=40,
        days_supply=14,
        breakthrough_drug="MORPHINE_PO",
    )
    naive_order = write_medication_order(
        naive["id"],
        drug="MORPHINE_PO",
        dose_amount=40,
        days_supply=14,
        breakthrough_drug="MORPHINE_PO",
    )

    assert tolerant_order["mme_variant"] == "TOLERANT"
    assert tolerant_order["mme_daily"] == pytest.approx(40.0, abs=1e-9)
    assert naive_order["mme_variant"] == "NAIVE"
    assert naive_order["mme_daily"] == pytest.approx(30.0, abs=1e-9)
    assert naive_order["mme_daily"] < tolerant_order["mme_daily"]


# ---------------------------------------------------------------------------
# The conserved opioid ledger
# ---------------------------------------------------------------------------
def test_discontinuing_an_order_returns_the_ledger_to_its_prior_value(api):
    """PRD 2.9: "**The patient opioid ledger.** `active_daily_mme` on the patient
    equals, at all times, the sum of `mme_daily` over that patient's medication
    orders whose `status` is exactly `ACTIVE`. Orders in `PENDING_VERIFICATION`,
    `REVIEW_REQUIRED` and `DISCONTINUED` contribute zero. Verifying an order into
    `ACTIVE` and then discontinuing it must return `active_daily_mme` to exactly
    its previous value."
    PRD 3.8: "Only the `ACTIVE` case moves the ledger: the patient's
    `active_daily_mme` decreases by exactly the `mme_daily` this order
    contributed, restoring the sum to precisely what it was before the order was
    verified, and `breakthrough_dose_mg` is recomputed for the patient's remaining
    active orders."

    Design: Corner/calculations/patient_active_daily_mme_ledger_matches_the_active_order_set
    """
    patient, _ = enroll_patient(
        clock="2026-06-01T00:00:00Z", full_name="Vera Okoye", opioid_status="OPIOID_TOLERANT"
    )
    first = active_medication_order(
        patient["id"],
        drug="MORPHINE_PO",
        dose_amount=30,
        days_supply=14,
        breakthrough_drug="MORPHINE_PO",
    )
    second = active_medication_order(
        patient["id"],
        drug="MORPHINE_PO",
        dose_amount=20,
        days_supply=14,
        breakthrough_drug="MORPHINE_PO",
    )

    assert_mme_ledger(read_patient(patient["id"]), 50.0)
    before = _read_order(api, patient["id"], first["id"])
    assert before["breakthrough_dose_mg"] == pytest.approx(7.5, abs=1e-9)

    discontinued = validate_success(
        api.discontinue_medication_order(
            second["id"], {"discontinue_reason": "rotation to a single agent"}, PHYSICIAN
        )
    )
    assert discontinued["status"] == "DISCONTINUED"

    assert_mme_ledger(read_patient(patient["id"]), 30.0)
    after = _read_order(api, patient["id"], first["id"])
    assert after["status"] == "ACTIVE"
    assert after["breakthrough_dose_mg"] == pytest.approx(4.5, abs=1e-9)


# ---------------------------------------------------------------------------
# Segregation of duties
# ---------------------------------------------------------------------------
def test_the_prescriber_may_not_verify_their_own_order(api):
    """PRD 3.8: "Verification is a second-clinician act carrying an
    `attestation_type` of `VERIFICATION` and an optional `attestation_note`.
    `X-User-ID` must differ from `prescriber_user_id`, or the request is refused
    with `ERR_SEGREGATION_OF_DUTIES`."
    PRD 3.8: "The acting user's `X-User-ID` is recorded as `prescriber_user_id`,
    and that user is thereby barred from verifying their own order."

    Design: Corner/validations/medication_verification_by_the_prescriber_returns_segregation_of_duties
    """
    patient, _ = enroll_patient(
        clock="2026-06-01T00:00:00Z", full_name="Elio Ferrand", opioid_status="OPIOID_TOLERANT"
    )
    order = write_medication_order(
        patient["id"], drug="OXYCODONE_PO", dose_amount=20, days_supply=14
    )
    assert order["prescriber_user_id"] == "u_physician_1"

    rejected = api.attest_medication_order(
        order["id"], {"attestation_type": "VERIFICATION"}, PHYSICIAN
    )
    validate_error(rejected, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 422)

    verified = validate_success(
        api.attest_medication_order(order["id"], {"attestation_type": "VERIFICATION"}, NURSE)
    )
    assert verified["status"] == "ACTIVE"
    assert verified["verifier_user_id"] == "u_nurse_1"
    assert verified["mme_daily"] == pytest.approx(30.0, abs=1e-9)
    assert_mme_ledger(read_patient(patient["id"]), 30.0)


# ---------------------------------------------------------------------------
# Refill gates
# ---------------------------------------------------------------------------
def test_a_refill_one_minute_early_is_refused_and_the_exact_instant_is_allowed(api):
    """PRD 3.8: "An order sitting in `REVIEW_REQUIRED` is admitted past the
    generic state check only so it can be refused with `ERR_MME_REVIEW_REQUIRED`;
    and a refill arriving before `next_refill_allowed_at` is refused with
    `ERR_EARLY_REFILL`, where the clock exactly at `next_refill_allowed_at` is
    permitted."
    PRD 3.8: "A refill that passes both gates always increments `refill_count` by
    1, re-stamps `last_fill_at` to the current logical clock, and recomputes
    `next_refill_allowed_at`."

    Design: Corner/validations/refill_before_the_window_returns_early_refill_and_succeeds_at_the_edge
    """
    patient, _ = enroll_patient(
        clock="2026-06-01T00:00:00Z", full_name="Gus Halloran", opioid_status="OPIOID_TOLERANT"
    )
    order = active_medication_order(
        patient["id"], drug="MORPHINE_PO", dose_amount=30, days_supply=14
    )
    assert_same_instant(
        order["next_refill_allowed_at"],
        "2026-06-13T00:00:00Z",
        "MedicationOrder.next_refill_allowed_at",
    )

    set_clock("2026-06-12T23:59:00Z")
    validate_error(
        api.refill_medication_order(order["id"], {}, NURSE),
        ApiErrorId.ERR_EARLY_REFILL.value,
        422,
    )

    set_clock("2026-06-13T00:00:00Z")
    refilled = validate_success(
        api.refill_medication_order(order["id"], {"refill_note": "on-window refill"}, NURSE)
    )

    assert refilled["status"] == "ACTIVE"
    assert refilled["refill_count"] == 1
    assert_same_instant(
        refilled["last_fill_at"], "2026-06-13T00:00:00Z", "MedicationOrder.last_fill_at"
    )
    assert_same_instant(
        refilled["next_refill_allowed_at"],
        "2026-06-25T00:00:00Z",
        "MedicationOrder.next_refill_allowed_at",
    )
    assert_mme_ledger(read_patient(patient["id"]), 30.0)


def test_the_review_gate_is_reported_before_the_early_refill_gate(api):
    """PRD 2.5: "**Review gate on refills.** A refill against an order whose
    `status` is `REVIEW_REQUIRED` is rejected until a physician's `MME_REVIEW`
    attestation has returned the order to `ACTIVE`. Otherwise
    `ERR_MME_REVIEW_REQUIRED` (422). Applies to the medication refill endpoint."
    PRD 3.8: "When the patient's `active_daily_mme` is at or above 90 the refill
    instead pushes the order back `ACTIVE → REVIEW_REQUIRED`, and because the
    order has left the active set the patient's `active_daily_mme` decreases by
    this order's `mme_daily` — the order must be re-reviewed by a physician before
    it counts again."

    Design: Corner/validations/mme_review_gate_outranks_early_refill_on_a_parked_order
    """
    patient, _ = enroll_patient(
        clock="2026-06-01T00:00:00Z", full_name="Hui Zhang", opioid_status="OPIOID_TOLERANT"
    )
    big = active_medication_order(
        patient["id"], drug="MORPHINE_PO", dose_amount=89, days_supply=14
    )
    small_draft = write_medication_order(
        patient["id"], drug="MORPHINE_PO", dose_amount=1, days_supply=30
    )
    verify_medication_order(small_draft["id"])
    mme_review_medication_order(small_draft["id"], note="risk reviewed")
    assert_mme_ledger(read_patient(patient["id"]), 90.0)

    set_clock("2026-06-13T00:00:00Z")
    pushed_back = validate_success(api.refill_medication_order(big["id"], {}, NURSE))
    assert pushed_back["status"] == "REVIEW_REQUIRED"
    assert pushed_back["refill_count"] == 1
    assert_mme_ledger(read_patient(patient["id"]), 1.0)

    rejected = api.refill_medication_order(big["id"], {}, NURSE)
    validate_error(rejected, ApiErrorId.ERR_MME_REVIEW_REQUIRED.value, 422)

    final = _read_order(api, patient["id"], big["id"])
    assert final["refill_count"] == 1
    assert_same_instant(
        final["next_refill_allowed_at"],
        "2026-06-25T00:00:00Z",
        "MedicationOrder.next_refill_allowed_at",
    )
