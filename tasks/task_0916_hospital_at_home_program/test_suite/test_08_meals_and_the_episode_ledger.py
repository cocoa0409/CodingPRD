"""Meal credits, the computed ledger read and the amendment compensation."""

from test_helpers import (
    ApiErrorId,
    assert_day_ledger,
    assert_ledger_matches_episode,
    assert_meal_plan,
    assert_money,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import create_meal_plan_payload
from test_helpers.test_users import (
    BILLING_ANALYST,
    LOGISTICS_COORDINATOR,
    PROGRAM_ADMIN,
)


def test_meal_credit_is_zero_under_the_waiver_and_twenty_eight_under_fee_for_service(api):
    """PRD §3.7: "The money step then forks on the episode's `program_track`: on
    a `CMS_WAIVER` episode meals are bundled inside the per-diem, so
    `credited_day_count` is still tracked but `meal_credit_total_usd` is always
    0.00; on a `FEE_FOR_SERVICE` episode meals are separately billable at 28.00
    US dollars per credited day, so `meal_credit_total_usd` is
    `credited_day_count` multiplied by 28.00, rounded half up to two decimals,
    and that money later rolls into the claim."
    PRD §3.7: "A newly opened plan takes `status` of `ACTIVE`, stamps
    `activated_on_date` with the UTC calendar date of the logical clock at
    creation, and starts `suspension_day_count` at 0 before computing its
    credits."

    Design: Corner/calculations/meal_credit_is_zero_under_the_waiver_and_28_per_day_under_ffs
    """
    waiver = fx.setup_active_episode(
        program_track="CMS_WAIVER", mrn="MRN-MW", full_name="Mia MealWaiver"
    )
    ffs = fx.setup_active_episode(
        program_track="FEE_FOR_SERVICE",
        set_the_clock=False,
        mrn="MRN-MF",
        full_name="Moe MealFfs",
    )

    waiver_plan = validate_success(
        api.create_meal_plan(
            create_meal_plan_payload(
                waiver["episode"]["id"], diet_code="NONE", daily_delivery_count=3
            ),
            LOGISTICS_COORDINATOR,
        ),
        201,
    )
    ffs_plan = validate_success(
        api.create_meal_plan(
            create_meal_plan_payload(
                ffs["episode"]["id"], diet_code="NONE", daily_delivery_count=3
            ),
            LOGISTICS_COORDINATOR,
        ),
        201,
    )
    assert_meal_plan(waiver_plan)
    assert_meal_plan(ffs_plan)

    assert waiver_plan["activated_on_date"] == "2026-06-01"
    assert ffs_plan["activated_on_date"] == "2026-06-01"
    assert waiver_plan["credited_day_count"] == 1
    assert ffs_plan["credited_day_count"] == 1
    assert_money(waiver_plan["meal_credit_total_usd"], 0.00, "waiver meal credit")
    assert_money(ffs_plan["meal_credit_total_usd"], 28.00, "fee-for-service meal credit")

    assert_money(
        fx.read_episode(waiver["episode"]["id"])["meal_credit_total_usd"],
        0.00,
        "waiver episode meal_credit_total_usd",
    )
    assert_money(
        fx.read_episode(ffs["episode"]["id"])["meal_credit_total_usd"],
        28.00,
        "fee-for-service episode meal_credit_total_usd",
    )


def test_meal_plan_diet_code_must_match_a_non_none_patient_restriction(api):
    """PRD §3.7: "The diet compatibility rule is deliberately asymmetric: when
    the patient's `diet_restriction` is `NONE` any `diet_code` is accepted,
    because an unrestricted patient can eat anything; when the patient carries
    any other restriction the plan's `diet_code` must equal that restriction
    exactly, and a mismatch is refused with `ERR_DIET_INCOMPATIBLE` at HTTP 422."

    Design: Corner/validations/meal_plan_diet_code_must_match_a_non_none_patient_restriction
    """
    parts = fx.setup_active_episode(
        diet_restriction="RENAL", mrn="MRN-DT", full_name="Dot Diet"
    )
    episode_id = parts["episode"]["id"]

    validate_error(
        api.create_meal_plan(
            create_meal_plan_payload(
                episode_id, diet_code="LOW_SODIUM", daily_delivery_count=2
            ),
            LOGISTICS_COORDINATOR,
        ),
        ApiErrorId.ERR_DIET_INCOMPATIBLE.value,
    )

    accepted = validate_success(
        api.create_meal_plan(
            create_meal_plan_payload(
                episode_id, diet_code="RENAL", daily_delivery_count=2
            ),
            LOGISTICS_COORDINATOR,
        ),
        201,
    )
    assert accepted["status"] == "ACTIVE"

    _, meta = validate_paginated(
        api.list_episode_meal_plans(episode_id, PROGRAM_ADMIN)
    )
    assert meta["total_count"] == 1, "the rejected plan must not be persisted"


def test_episode_ledger_read_matches_the_stored_counters(api):
    """PRD §3.2: "a dedicated computed read returns exactly those seven numbers —
    `service_day_count`, `billable_day_count`, `carved_out_day_count`,
    `pending_day_count`, `reimbursement_amount_usd`, `meal_credit_total_usd` and
    `travel_reimbursement_total_usd` — for a `ProgramAdmin`,
    `AdmittingPhysician` or `BillingAnalyst`."
    PRD §3.9: "A `CMS_WAIVER` episode is paid a strictly linear per-diem of
    1850.00 US dollars for each billable day, the product rounded half up to two
    decimals; six billable days are therefore worth 11100.00."

    Design: Corner/endpoints/episode_ledger_computed_read_matches_the_stored_counters
    """
    parts = fx.setup_active_episode(
        program_track="CMS_WAIVER",
        home_distance_km=8.0,
        mrn="MRN-LG",
        full_name="Lou Ledger",
    )
    episode_id = parts["episode"]["id"]

    fx.make_waiver_day_compliant(
        episode_id, "2026-06-01", day_start_hour=9, distance_km=8.0
    )
    day = fx.compliance_day_for(episode_id, "2026-06-01")
    finalized = fx.finalize_day(day["id"])
    assert finalized["status"] == "COMPLIANT"

    ledger = validate_success(api.get_episode_ledger(episode_id, BILLING_ANALYST))
    assert ledger["service_day_count"] == 1
    assert ledger["billable_day_count"] == 1
    assert ledger["carved_out_day_count"] == 0
    assert ledger["pending_day_count"] == 0
    assert_money(ledger["reimbursement_amount_usd"], 1850.00, "reimbursement_amount_usd")
    assert_money(ledger["meal_credit_total_usd"], 0.00, "meal_credit_total_usd")
    assert_money(
        ledger["travel_reimbursement_total_usd"],
        24.00,
        "travel_reimbursement_total_usd",
    )

    assert_ledger_matches_episode(ledger, fx.read_episode(episode_id))


# ─── Amendment: the compensating move on the day ledger ────────────────────

def test_day_ledger_balances_before_the_compensating_amendment(api):
    """PRD §2.8: "Therefore an episode's `service_day_count` always equals the
    sum of its `billable_day_count`, its `carved_out_day_count` and its
    `pending_day_count`."
    PRD §3.4: "When the verdict is compliant, the record moves `PENDING →
    COMPLIANT`, `finalized_at` is stamped from the logical clock, the episode's
    `billable_day_count` is incremented and its `pending_day_count` decremented,
    the episode's `reimbursement_amount_usd` and `meal_credit_total_usd` are
    recomputed, and the record's `version` advances by 1."

    Design: Difficulty/compensating_invariant/episode_day_ledger_conserved_across_finalize_then_amendment_reopen
    """
    parts = fx.setup_active_episode(
        program_track="FEE_FOR_SERVICE",
        home_distance_km=3.0,
        primary_diagnosis_code="UTI_COMPLICATED",
        qualifying_condition_code="UTI_COMPLICATED",
        mrn="MRN-L1",
        full_name="Lea Ledger",
    )
    episode_id = parts["episode"]["id"]

    fx.perform_and_attest_visit(
        episode_id, "2026-06-01T09:00:00Z", "2026-06-01T09:45:00Z", distance_km=3.0
    )
    fx.set_clock("2026-06-02T08:00:00Z")
    fx.perform_and_attest_visit(
        episode_id, "2026-06-02T09:00:00Z", "2026-06-02T09:45:00Z", distance_km=3.0
    )

    fx.finalize_day(fx.compliance_day_for(episode_id, "2026-06-01")["id"])
    fx.finalize_day(fx.compliance_day_for(episode_id, "2026-06-02")["id"])

    episode = fx.read_episode(episode_id)
    assert_day_ledger(episode, service=2, billable=2, carved_out=0, pending=0)


def test_amendment_moves_a_day_from_billable_back_to_pending(api):
    """PRD §3.3: "Reopening from `COMPLIANT` clears `finalized_at` back to null,
    decrements the episode's `billable_day_count` and increments its
    `pending_day_count`, and advances the record's `version` by 1."
    PRD §2.8: "Therefore an episode's `service_day_count` always equals the sum
    of its `billable_day_count`, its `carved_out_day_count` and its
    `pending_day_count`."

    Design: Difficulty/compensating_invariant/episode_day_ledger_conserved_across_finalize_then_amendment_reopen
    """
    parts = fx.setup_active_episode(
        program_track="FEE_FOR_SERVICE",
        home_distance_km=3.0,
        primary_diagnosis_code="UTI_COMPLICATED",
        qualifying_condition_code="UTI_COMPLICATED",
        mrn="MRN-L2",
        full_name="Lea Ledger Two",
    )
    episode_id = parts["episode"]["id"]

    first_visit = fx.perform_and_attest_visit(
        episode_id, "2026-06-01T09:00:00Z", "2026-06-01T09:45:00Z", distance_km=3.0
    )
    fx.set_clock("2026-06-02T08:00:00Z")
    fx.perform_and_attest_visit(
        episode_id, "2026-06-02T09:00:00Z", "2026-06-02T09:45:00Z", distance_km=3.0
    )

    day_one = fx.finalize_day(fx.compliance_day_for(episode_id, "2026-06-01")["id"])
    day_two = fx.finalize_day(fx.compliance_day_for(episode_id, "2026-06-02")["id"])
    assert day_one["status"] == "COMPLIANT"
    assert day_two["status"] == "COMPLIANT"

    amended = fx.attest_visit(first_visit["id"], "RN_IN_PERSON", "rn-1")
    assert amended["attestation_status"] == "AMENDED"

    reopened = fx.compliance_day_for(episode_id, "2026-06-01")
    assert reopened["status"] == "PENDING"

    episode = fx.read_episode(episode_id)
    assert_day_ledger(episode, service=2, billable=1, carved_out=0, pending=1)

    untouched = fx.compliance_day_for(episode_id, "2026-06-02")
    assert untouched["status"] == "COMPLIANT", (
        "amending one day must not disturb a sibling day"
    )


def test_second_attestation_amends_the_visit_and_reopens_its_finalized_day(api):
    """PRD §3.3: "Attesting a second time is an **amendment**, and amendments are
    expensive. The axis moves `ATTESTED → AMENDED`, `attested_by_user_id` is
    overwritten with the amending clinician's identifier, the visit's `version`
    advances by 1, and the compliance record for that episode and `service_date`
    is reopened: if that record had already been finalized to `COMPLIANT` or to
    `CARVED_OUT`, and the owning episode is not yet `DISCHARGED`, it is driven
    back to `PENDING` before being recomputed."
    PRD §3.3: "Reopening from `COMPLIANT` clears `finalized_at` back to null,
    decrements the episode's `billable_day_count` and increments its
    `pending_day_count`, and advances the record's `version` by 1."

    Design: Difficulty/transitive_cascade/visit_amendment_cascades_reopen_into_episode_counters
    """
    parts = fx.setup_active_episode(
        program_track="FEE_FOR_SERVICE",
        home_distance_km=4.0,
        primary_diagnosis_code="COVID_MODERATE",
        qualifying_condition_code="COVID_MODERATE",
        mrn="MRN-A2",
        full_name="Amy Amend",
    )
    episode_id = parts["episode"]["id"]

    visit = fx.perform_and_attest_visit(
        episode_id, "2026-06-01T09:00:00Z", "2026-06-01T09:45:00Z", distance_km=4.0
    )
    fx.finalize_day(fx.compliance_day_for(episode_id, "2026-06-01")["id"])

    amended = validate_success(
        api.attest_visit(visit["id"], fx.headers_for_staff("RN_IN_PERSON", "rn-1"))
    )
    assert amended["attestation_status"] == "AMENDED"

    reopened = fx.compliance_day_for(episode_id, "2026-06-01")
    assert reopened["status"] == "PENDING"
    assert reopened["finalized_at"] is None, (
        "reopening clears finalized_at back to null"
    )


def test_amendment_pulls_the_episode_counters_and_money_back(api):
    """PRD §2.9: "**The attestation cascade.** Attesting a visit recomputes that
    service date's compliance record; a second attestation on the same visit
    amends it, which reopens an already-finalized compliance day back to
    `PENDING` and pulls the episode's day-ledger counters back with it."
    PRD §3.9: "An episode's `reimbursement_amount_usd` is driven entirely by
    `billable_day_count` — carved-out and pending days contribute nothing — and
    the arithmetic forks on `program_track`."

    Design: Difficulty/transitive_cascade/visit_amendment_cascades_reopen_into_episode_counters
    """
    parts = fx.setup_active_episode(
        program_track="FEE_FOR_SERVICE",
        home_distance_km=4.0,
        primary_diagnosis_code="COVID_MODERATE",
        qualifying_condition_code="COVID_MODERATE",
        mrn="MRN-A3",
        full_name="Amy Amend Two",
    )
    episode_id = parts["episode"]["id"]

    visit = fx.perform_and_attest_visit(
        episode_id, "2026-06-01T09:00:00Z", "2026-06-01T09:45:00Z", distance_km=4.0
    )
    fx.finalize_day(fx.compliance_day_for(episode_id, "2026-06-01")["id"])
    assert fx.read_episode(episode_id)["billable_day_count"] == 1

    fx.attest_visit(visit["id"], "RN_IN_PERSON", "rn-1")

    episode = fx.read_episode(episode_id)
    assert_day_ledger(episode, service=1, billable=0, carved_out=0, pending=1)
    assert_money(
        episode["reimbursement_amount_usd"], 0.00, "reimbursement_amount_usd"
    )
