"""The two independent visit axes, the turnaround buffer and travel money."""

from test_helpers import (
    ApiErrorId,
    assert_day_ledger,
    assert_money,
    assert_same_instant,
    assert_visit,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import create_visit_payload
from test_helpers.test_users import (
    ADMITTING_PHYSICIAN,
    FIELD_NURSE,
    PROGRAM_ADMIN,
)


# ─── The two axes advance independently ────────────────────────────────────

def test_attestation_axis_advances_while_scheduling_axis_is_en_route(api):
    """PRD §3.3: "The first attestation moves it `UNATTESTED → ATTESTED`, writes
    the attesting clinician's opaque identifier into `attested_by_user_id`,
    recomputes the compliance record's `qualified_in_person_visit_count` and
    `physician_eval_present` for that episode and `service_date`, and advances
    the visit's `version` by 1."
    PRD §3.3: "Its only precondition beyond the current axis value is that the
    visit's `scheduling_status` is not `CANCELLED`; a visit that is still
    `SCHEDULED` or still `EN_ROUTE` may perfectly well be attested — it simply
    contributes nothing to the day's requirement until the scheduling axis also
    reaches `COMPLETED`."

    Design: Difficulty/non_linear_state_machine/visit_scheduling_and_attestation_axes_advance_independently
    """
    parts = fx.setup_active_episode(mrn="MRN-P1", full_name="Pia Parallel")
    episode_id = parts["episode"]["id"]

    visit = fx.schedule_visit(
        episode_id,
        "2026-06-01T09:00:00Z",
        "2026-06-01T09:45:00Z",
        visit_type="RN_IN_PERSON",
        staff_user_id="rn-1",
        distance_km=7.0,
    )
    fx.depart_visit(visit["id"], "RN_IN_PERSON", "rn-1")

    attested = validate_success(
        api.attest_visit(visit["id"], fx.headers_for_staff("RN_IN_PERSON", "rn-1"))
    )
    assert_visit(attested)
    assert attested["scheduling_status"] == "EN_ROUTE", (
        "attesting must not move the scheduling axis"
    )
    assert attested["attestation_status"] == "ATTESTED"
    assert attested["attested_by_user_id"] == "rn-1", (
        "the attesting clinician's opaque identifier is recorded on the visit"
    )

    day = fx.compliance_day_for(episode_id, "2026-06-01")
    assert day["qualified_in_person_visit_count"] == 0, (
        "an EN_ROUTE visit contributes nothing to the day's requirement"
    )
    assert day["status"] == "PENDING"


def test_completing_after_attestation_makes_the_visit_count_for_the_day(api):
    """PRD §3.3: "`qualified_in_person_visit_count` is the number of that
    episode's visits on that `service_date` whose `visit_type` is `RN_IN_PERSON`
    or `PARAMEDIC_IN_PERSON`, whose `scheduling_status` is `COMPLETED`, and whose
    `attestation_status` is `ATTESTED` or `AMENDED`"
    PRD §3.3: "A visit may be `ATTESTED` while `SCHEDULED`, and may be
    `COMPLETED` while `UNATTESTED`; only the combination of `COMPLETED` on one
    axis and `ATTESTED` or `AMENDED` on the other counts toward anything."

    Design: Difficulty/non_linear_state_machine/visit_scheduling_and_attestation_axes_advance_independently
    """
    parts = fx.setup_active_episode(mrn="MRN-P2", full_name="Pia Parallel Two")
    episode_id = parts["episode"]["id"]

    visit = fx.schedule_visit(
        episode_id,
        "2026-06-01T09:00:00Z",
        "2026-06-01T09:45:00Z",
        distance_km=7.0,
    )
    fx.depart_visit(visit["id"], "RN_IN_PERSON", "rn-1")
    fx.attest_visit(visit["id"], "RN_IN_PERSON", "rn-1")

    completed = validate_success(
        api.complete_visit(visit["id"], fx.headers_for_staff("RN_IN_PERSON", "rn-1"))
    )
    assert completed["scheduling_status"] == "COMPLETED"
    assert completed["attestation_status"] == "ATTESTED", (
        "completing must not disturb the attestation axis"
    )

    day = fx.compliance_day_for(episode_id, "2026-06-01")
    assert day["qualified_in_person_visit_count"] == 1, (
        "once both axes line up the visit counts toward the day"
    )
    assert day["status"] == "PENDING"


# ─── Turnaround buffer ─────────────────────────────────────────────────────

def test_visit_fourteen_minutes_after_a_prior_visit_collides(api):
    """PRD §3.3: "The requested slot is accepted only if its
    `scheduled_start_at` falls at or after the existing visit's
    `scheduled_end_at` plus fifteen minutes, or its `scheduled_end_at` falls at
    or before the existing visit's `scheduled_start_at`."
    PRD §3.3: "Exactly fifteen minutes of separation after an existing visit is
    therefore accepted; fourteen minutes collides and is refused with
    `ERR_VISIT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/staff_visit_turnaround_buffer_is_inclusive_at_exactly_15_minutes
    """
    parts = fx.setup_active_episode(
        home_distance_km=9.0,
        primary_diagnosis_code="CAP_PNEUMONIA",
        qualifying_condition_code="CAP_PNEUMONIA",
        mrn="MRN-O1",
        full_name="Owen Overlap",
    )
    episode_id = parts["episode"]["id"]

    fx.schedule_visit(
        episode_id,
        "2026-06-01T09:00:00Z",
        "2026-06-01T09:45:00Z",
        staff_user_id="rn-1",
        distance_km=9.0,
    )

    colliding = create_visit_payload(
        episode_id,
        "2026-06-01",
        "2026-06-01T09:59:00Z",
        "2026-06-01T10:44:00Z",
        staff_user_id="rn-1",
        distance_km=9.0,
    )
    validate_error(
        api.create_visit(colliding, FIELD_NURSE), ApiErrorId.ERR_VISIT_OVERLAP.value
    )

    _, meta = validate_paginated(api.list_episode_visits(episode_id, PROGRAM_ADMIN))
    assert meta["total_count"] == 1, "the rejected slot must not be persisted"


def test_visit_exactly_fifteen_minutes_after_a_prior_visit_is_accepted(api):
    """PRD §3.3: "Exactly fifteen minutes of separation after an existing visit
    is therefore accepted; fourteen minutes collides and is refused with
    `ERR_VISIT_OVERLAP`."
    PRD §3.3: "The requested slot is accepted only if its `scheduled_start_at`
    falls at or after the existing visit's `scheduled_end_at` plus fifteen
    minutes, or its `scheduled_end_at` falls at or before the existing visit's
    `scheduled_start_at`."

    Design: Difficulty/resource_temporal_overlap/staff_visit_turnaround_buffer_is_inclusive_at_exactly_15_minutes
    """
    parts = fx.setup_active_episode(
        home_distance_km=9.0,
        primary_diagnosis_code="CAP_PNEUMONIA",
        qualifying_condition_code="CAP_PNEUMONIA",
        mrn="MRN-O2",
        full_name="Owen Overlap Two",
    )
    episode_id = parts["episode"]["id"]

    fx.schedule_visit(
        episode_id,
        "2026-06-01T09:00:00Z",
        "2026-06-01T09:45:00Z",
        staff_user_id="rn-1",
        distance_km=9.0,
    )

    adjacent = create_visit_payload(
        episode_id,
        "2026-06-01",
        "2026-06-01T10:00:00Z",
        "2026-06-01T10:45:00Z",
        staff_user_id="rn-1",
        distance_km=9.0,
    )
    accepted = validate_success(api.create_visit(adjacent, FIELD_NURSE), 201)
    assert accepted["scheduling_status"] == "SCHEDULED"
    assert_same_instant(
        accepted["scheduled_start_at"], "2026-06-01T10:00:00Z", "scheduled_start_at"
    )

    _, meta = validate_paginated(api.list_episode_visits(episode_id, PROGRAM_ADMIN))
    assert meta["total_count"] == 2


# ─── Travel money ──────────────────────────────────────────────────────────

def test_each_visit_rounds_its_own_travel_payment_before_the_episode_sums(api):
    """PRD §3.3: "A visit strictly beyond 25.0 kilometres is paid at 0.61 US
    dollars per kilometre. The distance is multiplied by the single selected rate
    and the product is rounded half up to two decimals; if that rounded figure is
    below the eight-dollar minimum per-visit payment, the visit pays 8.00
    instead."
    PRD §2.7: "Each completed, attested visit's travel payment is rounded to two
    decimals on its own, and the episode total is the sum of those
    already-rounded per-visit amounts, rounded once more to two decimals."

    Design: Difficulty/combinatorial_formula/travel_reimbursement_rounds_per_visit_before_summing_mode_b
    """
    parts = fx.setup_active_episode(
        home_distance_km=25.5,
        primary_diagnosis_code="CAP_PNEUMONIA",
        qualifying_condition_code="CAP_PNEUMONIA",
        mrn="MRN-T1",
        full_name="Trina Travel",
    )
    episode_id = parts["episode"]["id"]

    first = fx.perform_and_attest_visit(
        episode_id,
        "2026-06-01T09:00:00Z",
        "2026-06-01T09:45:00Z",
        visit_type="RN_IN_PERSON",
        staff_user_id="rn-1",
        distance_km=25.5,
    )
    second = fx.perform_and_attest_visit(
        episode_id,
        "2026-06-01T09:10:00Z",
        "2026-06-01T09:55:00Z",
        visit_type="PARAMEDIC_IN_PERSON",
        staff_user_id="medic-1",
        distance_km=25.5,
    )

    assert_money(first["travel_payment_usd"], 15.56, "first visit travel_payment_usd")
    assert_money(second["travel_payment_usd"], 15.56, "second visit travel_payment_usd")


def test_episode_travel_total_sums_already_rounded_visit_payments(api):
    """PRD §2.7: "Each completed, attested visit's travel payment is rounded to
    two decimals on its own, and the episode total is the sum of those
    already-rounded per-visit amounts, rounded once more to two decimals.
    Summing the raw unrounded products and rounding a single time at the end is
    explicitly *not* the rule."
    PRD §3.3: "The episode's `travel_reimbursement_total_usd` is then the sum of
    the already-rounded `travel_payment_usd` values of the episode's visits whose
    `scheduling_status` is `COMPLETED` **and** whose `attestation_status` is
    `ATTESTED` or `AMENDED`, rounded once more to two decimals."

    Design: Difficulty/combinatorial_formula/travel_reimbursement_rounds_per_visit_before_summing_mode_b
    """
    parts = fx.setup_active_episode(
        home_distance_km=25.5,
        primary_diagnosis_code="CAP_PNEUMONIA",
        qualifying_condition_code="CAP_PNEUMONIA",
        mrn="MRN-T2",
        full_name="Trina Travel Two",
    )
    episode_id = parts["episode"]["id"]

    fx.perform_and_attest_visit(
        episode_id,
        "2026-06-01T09:00:00Z",
        "2026-06-01T09:45:00Z",
        visit_type="RN_IN_PERSON",
        staff_user_id="rn-1",
        distance_km=25.5,
    )
    fx.perform_and_attest_visit(
        episode_id,
        "2026-06-01T09:10:00Z",
        "2026-06-01T09:55:00Z",
        visit_type="PARAMEDIC_IN_PERSON",
        staff_user_id="medic-1",
        distance_km=25.5,
    )

    ledger = validate_success(
        api.get_episode_ledger(episode_id, ADMITTING_PHYSICIAN)
    )
    assert_money(
        ledger["travel_reimbursement_total_usd"],
        31.12,
        "travel_reimbursement_total_usd",
    )
    assert ledger["travel_reimbursement_total_usd"] != 31.11, (
        "summing the raw products and rounding once at the end is not the rule"
    )


def test_travel_band_boundary_pays_more_at_ten_km_than_at_ten_point_one(api):
    """PRD §3.3: "A visit whose `distance_km` is at or below 10.0 kilometres is
    paid at 0.92 US dollars per kilometre. A visit strictly beyond 10.0
    kilometres but at or below 25.0 kilometres is paid at 0.74 US dollars per
    kilometre."
    PRD §3.3: "The distance is multiplied by the single selected rate and the
    product is rounded half up to two decimals; if that rounded figure is below
    the eight-dollar minimum per-visit payment, the visit pays 8.00 instead."

    Design: Corner/calculations/travel_band_boundary_pays_more_at_10km_than_at_10_1km
    """
    parts = fx.setup_active_episode(
        home_distance_km=10.0, mrn="MRN-BD", full_name="Bud Band"
    )
    episode_id = parts["episode"]["id"]

    in_band = fx.perform_and_attest_visit(
        episode_id,
        "2026-06-01T09:00:00Z",
        "2026-06-01T09:45:00Z",
        visit_type="RN_IN_PERSON",
        staff_user_id="rn-1",
        distance_km=10.0,
    )
    over_band = fx.perform_and_attest_visit(
        episode_id,
        "2026-06-01T09:10:00Z",
        "2026-06-01T09:55:00Z",
        visit_type="PARAMEDIC_IN_PERSON",
        staff_user_id="medic-1",
        distance_km=10.1,
    )

    assert_money(in_band["travel_payment_usd"], 9.20, "10.0 km travel_payment_usd")
    assert_money(over_band["travel_payment_usd"], 8.00, "10.1 km travel_payment_usd")

    ledger = validate_success(
        api.get_episode_ledger(episode_id, ADMITTING_PHYSICIAN)
    )
    assert_money(
        ledger["travel_reimbursement_total_usd"],
        17.20,
        "travel_reimbursement_total_usd",
    )


# ─── Scheduling-axis preconditions ─────────────────────────────────────────

def test_departing_a_completed_visit_is_rejected(api):
    """PRD §3.3: "Departing for the visit moves it `SCHEDULED → EN_ROUTE` and
    requires the parent episode to still be `ACTIVE`."
    PRD §2.5: "**Rung 7 — Target state precondition.** The target row's current
    state is one of the states the requested transition may legally leave from.
    Violation: `ERR_INVALID_STATE` (409). Applies to every state-transition
    endpoint."

    Design: Corner/state_machines/visit_depart_from_completed_is_rejected_as_invalid_state
    """
    parts = fx.setup_active_episode(mrn="MRN-IT", full_name="Ida Invalid")
    episode_id = parts["episode"]["id"]

    visit = fx.schedule_visit(
        episode_id, "2026-06-01T09:00:00Z", "2026-06-01T09:45:00Z"
    )
    fx.depart_visit(visit["id"], "RN_IN_PERSON", "rn-1")
    fx.complete_visit(visit["id"], "RN_IN_PERSON", "rn-1")

    validate_error(
        api.depart_visit(visit["id"], FIELD_NURSE), ApiErrorId.ERR_INVALID_STATE.value
    )

    rows = validate_success(api.list_episode_visits(episode_id, PROGRAM_ADMIN))
    unchanged = next(row for row in rows if row["id"] == visit["id"])
    assert unchanged["scheduling_status"] == "COMPLETED"
    assert unchanged["attestation_status"] == "UNATTESTED"


def test_no_show_visit_does_not_count_toward_the_daily_requirement(api):
    """PRD §3.4: "`qualified_in_person_visit_count` is the number of that
    episode's visits on that `service_date` whose `visit_type` is `RN_IN_PERSON`
    or `PARAMEDIC_IN_PERSON`, whose `scheduling_status` is `COMPLETED`, and whose
    `attestation_status` is `ATTESTED` or `AMENDED`"
    PRD §3.4: "Visits that are `SCHEDULED`, `EN_ROUTE`, `NO_SHOW` or `CANCELLED`
    are excluded no matter how they were attested."

    Design: Corner/validations/no_show_visit_does_not_count_toward_the_daily_in_person_requirement
    """
    parts = fx.setup_active_episode(
        program_track="FEE_FOR_SERVICE", mrn="MRN-NS", full_name="Nan NoShow"
    )
    episode_id = parts["episode"]["id"]

    visit = fx.schedule_visit(
        episode_id, "2026-06-01T09:00:00Z", "2026-06-01T09:45:00Z"
    )
    validate_success(
        api.close_unperformed_visit(visit["id"], {"outcome": "NO_SHOW"}, FIELD_NURSE)
    )
    attested = validate_success(api.attest_visit(visit["id"], FIELD_NURSE))
    assert attested["scheduling_status"] == "NO_SHOW"
    assert attested["attestation_status"] == "ATTESTED"

    day = fx.compliance_day_for(episode_id, "2026-06-01")
    finalized = validate_success(
        api.finalize_compliance_day(day["id"], PROGRAM_ADMIN)
    )
    assert finalized["qualified_in_person_visit_count"] == 0
    assert finalized["status"] == "CARVED_OUT"
    assert finalized["carve_out_reason"] == "INSUFFICIENT_IN_PERSON_VISITS"

    episode = fx.read_episode(episode_id)
    assert_day_ledger(episode, service=1, billable=0, carved_out=1, pending=0)
    assert_money(
        episode["travel_reimbursement_total_usd"],
        0.00,
        "travel_reimbursement_total_usd",
    )

    _, meta = validate_paginated(
        api.list_episode_visits(
            episode_id, PROGRAM_ADMIN, params={"service_date": "2026-06-01"}
        )
    )
    assert meta["total_count"] == 1
