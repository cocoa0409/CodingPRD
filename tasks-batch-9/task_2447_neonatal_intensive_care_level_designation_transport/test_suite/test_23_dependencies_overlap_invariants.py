"""Cross-entity state preconditions, interval and calendar-day exclusion, and the
two conserved ledgers.

Covers PRD §2.8 (the bed ledger and census posture), §3.4 (acceptance, holds,
deferral and revocation), §3.5 (surge escalation windows), §3.6 (isolette
occupation intervals and departure), §3.7 (the infection dimension and the milk
volume ledger), §3.8 (discharge) and §3.9 (follow-up enrollment and the clinic
calendar day).
"""

from datetime import datetime

from test_helpers import (
    CLOCK_START,
    ApiErrorId,
    assert_bed_ledger_balanced,
    assert_close,
    assert_decimal_places,
    assert_milk_ledger_balanced,
    assert_unit_counts,
    assertions,
    factories,
    fixtures,
    make_bedside_nurse_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# Transport planning instants for the isolette occupation interval of PRD §3.6:
# a GROUND run planned 08:00 -> 12:00 occupies the isolette through 12:45.
RUN_DEPART_AT = "2026-08-02T08:00:00Z"
RUN_PLANNED_RETURN_AT = "2026-08-02T12:00:00Z"
INSIDE_BUFFER_DEPART_AT = "2026-08-02T12:30:00Z"
BUFFER_END_DEPART_AT = "2026-08-02T12:45:00Z"
SECOND_RUN_RETURN_AT = "2026-08-02T16:00:00Z"
GROUND_CREW = ["TRANSPORT_RN", "NNP"]

# Three back-to-back surge windows: the second starts at the instant the first
# ends, and the third starts at the instant the second ends.
WINDOW_1_FROM = "2026-08-02T00:00:00Z"
WINDOW_1_TO = "2026-08-03T00:00:00Z"
WINDOW_2_FROM = "2026-08-03T00:00:00Z"
WINDOW_2_TO = "2026-08-04T00:00:00Z"
WINDOW_3_FROM = "2026-08-04T00:00:00Z"
WINDOW_3_TO = "2026-08-05T00:00:00Z"

# Two follow-up appointments on the same UTC calendar date, and one on the next.
CLINIC_MORNING = "2026-09-01T09:00:00Z"
CLINIC_EVENING = "2026-09-01T17:00:00Z"
CLINIC_NEXT_DAY = "2026-09-02T09:00:00Z"


def _instant(value):
    """Read an ISO-8601 UTC instant so two renderings of one moment compare equal."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Shared preconditions, each built through documented endpoints only
# ---------------------------------------------------------------------------


def _stabilized_run():
    """Accept a LEVEL_III case at the regional unit and drive a GROUND run to
    STABILIZING with a complete bundle."""
    env = fixtures.setup_network(with_isolette=True)
    referral = fixtures.create_referral(
        env,
        case_reference="CASE-Y1",
        gestational_age_weeks=30.0,
        birth_weight_grams=1250,
        support_modality="HFOV",
    )
    accepted = fixtures.accept_referral(env, referral["id"])
    run = fixtures.create_run(
        env,
        accepted["reservation_id"],
        mode="GROUND",
        crew_composition=GROUND_CREW,
        depart_at=RUN_DEPART_AT,
        planned_return_at=RUN_PLANNED_RETURN_AT,
        weather_minimums_met=False,
    )
    fixtures.dispatch_run(env, run["id"])
    fixtures.run_on_scene(env, run["id"])
    fixtures.stabilize_run(
        env, run["id"], temp_c=36.8, glucose_mg_dl=60, mean_bp_mmhg=28, spo2_pct=92
    )
    return env, referral, accepted["reservation_id"], run


def _isolette_occupied_from_eight_to_twelve():
    """Two held beds at the regional unit, with the first hold's GROUND run
    already occupying the single transport isolette from 08:00 to 12:00."""
    env = fixtures.setup_network(with_isolette=True)
    first = fixtures.accept_referral(
        env,
        fixtures.create_referral(
            env,
            case_reference="CASE-I1",
            gestational_age_weeks=30.0,
            birth_weight_grams=1250,
            support_modality="HFOV",
        )["id"],
    )
    second = fixtures.accept_referral(
        env,
        fixtures.create_referral(
            env,
            case_reference="CASE-I2",
            gestational_age_weeks=30.0,
            birth_weight_grams=1250,
            support_modality="HFOV",
        )["id"],
    )
    fixtures.create_run(
        env,
        first["reservation_id"],
        mode="GROUND",
        crew_composition=GROUND_CREW,
        depart_at=RUN_DEPART_AT,
        planned_return_at=RUN_PLANNED_RETURN_AT,
        weather_minimums_met=False,
    )
    return env, second["reservation_id"]


def _unit_full_with_three_escalation_windows():
    """A two-bed regional unit with both beds occupied, one ACTIVE escalation over
    the first window and two REQUESTED escalations over the next two."""
    env = fixtures.setup_network()
    fixtures.patch_unit(env, staffed_bed_target=2)
    for case in ("CASE-O1", "CASE-O2"):
        fixtures.admit_case(
            env,
            case_reference=case,
            gestational_age_weeks=34.0,
            birth_weight_grams=2000,
            support_modality="ROOM_AIR",
        )
    first = fixtures.request_surge(
        env, requested_beds=6, effective_from=WINDOW_1_FROM, effective_to=WINDOW_1_TO
    )
    fixtures.authorize_surge(env, first["id"])
    second = fixtures.request_surge(
        env, requested_beds=6, effective_from=WINDOW_2_FROM, effective_to=WINDOW_2_TO
    )
    third = fixtures.request_surge(
        env, requested_beds=6, effective_from=WINDOW_3_FROM, effective_to=WINDOW_3_TO
    )
    return env, first, second, third


def _clinic_with_one_morning_booking():
    """Two discharged graduates enrolled at the one-slot community clinic, the
    first already scheduled for 09:00 on the shared calendar date."""
    env = fixtures.setup_network()
    enrollments = []
    for case in ("CASE-K1", "CASE-K2"):
        admission = fixtures.admit_case(
            env,
            case_reference=case,
            gestational_age_weeks=29.0,
            birth_weight_grams=1200,
            support_modality="ROOM_AIR",
        )
        fixtures.care_update(
            env, admission["id"], current_weight_grams=1900, support_modality="ROOM_AIR"
        )
        fixtures.discharge(env, admission["id"], "HOME")
        enrollments.append(
            fixtures.enroll_graduate(
                env,
                admission["id"],
                clinic_unit_id=env["unit_b_id"],
                target_appointment_date=CLINIC_MORNING,
            )
        )
    first = fixtures.schedule_enrollment(env, enrollments[0]["id"], CLINIC_MORNING)
    return env, first, enrollments[1]


# ---------------------------------------------------------------------------
# A departure reads the referral two hops behind the reservation
# ---------------------------------------------------------------------------


def test_depart_refused_when_the_referral_behind_the_reservation_was_withdrawn(api):
    """PRD §3.6: "It requires `stabilization_bundle_complete` to be true — otherwise `ERR_STABILIZATION_INCOMPLETE` — and it requires the referral behind the reservation still to be in `ACCEPTED`, otherwise `ERR_DEPENDENT_STATE_INVALID`; a crew must not set off toward a bed that has since been given away."

    PRD §3.6: "At 30.0 weeks gestation, values of 36.5, 45, 30 and 90 — every one of them exactly on its boundary — score 100 and the bundle is complete; 36.4, 44, 26 and 89 score 68 and it is not; 36.8, 60, 28 and 92 score 92 and the bundle is complete with only the mean pressure failing; and 37.6, 60, 31 and 96 score 84 and the bundle is incomplete, because temperature and saturation both overshoot."

    Design: Difficulty/cross_entity_state_dependency/departure_depends_on_referral_status
    """
    env, referral, _reservation_id, run = _stabilized_run()

    validate_success(api.withdraw_referral(referral["id"], {}, env["ref_b"]))

    refused = api.depart_transport_run(run["id"], {}, env["coord"])
    validate_error(refused, ApiErrorId.DEPENDENT_STATE_INVALID)

    after = validate_success(api.get_transport_run(run["id"], env["coord"]))
    assertions.assert_transport_run(after)
    assert after["status"] == "STABILIZING"
    assert after["stabilization_score"] == 92
    assert after["stabilization_bundle_complete"] is True


def test_withdrawal_releases_the_hold_that_the_stabilized_run_was_driving_toward(api):
    """PRD §3.3: "The referring side may withdraw, moving the referral to `WITHDRAWN` from `PENDING`, `INFO_REQUESTED`, `DEFERRED` or `ACCEPTED` with `decision_reason` `FAMILY_CHOICE`; if a `HELD` reservation exists it is moved to `RELEASED` with `released_reason` `REFERRAL_WITHDRAWN`, and the receiving unit's `version` advances by one in exactly that case."

    Design: Difficulty/cross_entity_state_dependency/departure_depends_on_referral_status
    """
    env, referral, reservation_id, _run = _stabilized_run()

    withdrawn = validate_success(api.withdraw_referral(referral["id"], {}, env["ref_b"]))
    assertions.assert_referral(withdrawn)
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["decision_reason"] == "FAMILY_CHOICE"

    reservation = validate_success(api.get_bed_reservation(reservation_id, env["admin"]))
    assertions.assert_bed_reservation(reservation)
    assert reservation["status"] == "RELEASED"
    assert reservation["released_reason"] == "REFERRAL_WITHDRAWN"

    unit = fixtures.read_unit(env)
    assert_unit_counts(unit, occupied=0, held=0, available=4)


# ---------------------------------------------------------------------------
# Follow-up enrollment reads the admission's care dimension
# ---------------------------------------------------------------------------


def test_enrollment_refused_while_the_admission_is_still_stabilized(api):
    """PRD §3.9: "The admission must be in `DISCHARGED` or `TRANSFERRED`, or the enrollment is refused with `ERR_DEPENDENT_STATE_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/enrollment_depends_on_admission_care_status
    """
    env = fixtures.setup_network()
    admission = fixtures.admit_case(
        env,
        case_reference="CASE-Q1",
        gestational_age_weeks=29.0,
        birth_weight_grams=1200,
        support_modality="ROOM_AIR",
    )
    fixtures.care_update(
        env, admission["id"], current_weight_grams=1900, support_modality="ROOM_AIR"
    )
    assert fixtures.read_admission(env, admission["id"])["care_status"] == "STABILIZED"

    refused = api.create_follow_up_enrollment(
        factories.follow_up_enrollment_payload(
            admission["id"], env["unit_a_id"], CLINIC_MORNING
        ),
        env["fu"],
    )
    validate_error(refused, ApiErrorId.DEPENDENT_STATE_INVALID)

    rows, meta = validate_paginated(
        api.list_follow_up_enrollments(env["fu"], {"admission_id": admission["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_the_same_enrollment_payload_is_accepted_once_the_admission_is_discharged(api):
    """PRD §3.8: "The discharge stamps `discharged_at` with the current clock instant, sets `discharge_disposition` to `HOME`, re-derives `high_risk_graduate` from the eligibility rules of §3.9, then re-derives the unit's counters, promotes its deferral queue, and advances its `version` by one."

    PRD §3.9: "`eligibility_basis` is the **first** match in a pinned order: `BW_UNDER_1500` when `birth_weight_grams` is below 1500; otherwise `GA_UNDER_32` when `gestational_age_weeks` is below 32.0; otherwise `HIE_COOLED` when the originating referral's `diagnoses` contain `HIE_MODERATE`; otherwise `SURGICAL_NEC` when those `diagnoses` contain `SURGICAL_NEC`; otherwise `VENT_OVER_7D` when `ventilator_days` is strictly greater than 7; and otherwise `NOT_ELIGIBLE`."

    PRD §3.9: "`high_risk_graduate` on the admission is true exactly when `eligibility_basis` is anything other than `NOT_ELIGIBLE`."

    Design: Difficulty/cross_entity_state_dependency/enrollment_depends_on_admission_care_status
    """
    env = fixtures.setup_network()
    admission = fixtures.admit_case(
        env,
        case_reference="CASE-Q1",
        gestational_age_weeks=29.0,
        birth_weight_grams=1200,
        support_modality="ROOM_AIR",
    )
    fixtures.care_update(
        env, admission["id"], current_weight_grams=1900, support_modality="ROOM_AIR"
    )
    payload = factories.follow_up_enrollment_payload(
        admission["id"], env["unit_a_id"], CLINIC_MORNING
    )
    validate_error(
        api.create_follow_up_enrollment(payload, env["fu"]),
        ApiErrorId.DEPENDENT_STATE_INVALID,
    )

    discharged = fixtures.discharge(env, admission["id"], "HOME")
    assertions.assert_admission(discharged)
    assert discharged["care_status"] == "DISCHARGED"
    assert discharged["discharge_disposition"] == "HOME"
    assert discharged["high_risk_graduate"] is True

    enrollment = validate_success(api.create_follow_up_enrollment(payload, env["fu"]), 201)
    assertions.assert_follow_up_enrollment(enrollment)
    assert enrollment["status"] == "ENROLLED"
    assert enrollment["eligibility_basis"] == "BW_UNDER_1500"


# ---------------------------------------------------------------------------
# A milk administration reads the admission's infection dimension
# ---------------------------------------------------------------------------


def test_administration_refused_while_the_infection_event_quarantines_the_batch(api):
    """PRD §3.7: "`SUSPECT` moves the admission `SURVEILLANCE_CLEAR → SUSPECTED` or `RESOLVED → SUSPECTED`, and quarantines the infant's feed: every milk batch for that admission whose status is `RECEIVED`, `VERIFIED` or `PARTIALLY_ADMINISTERED` is moved to `QUARANTINED`, with its previous status preserved in `pre_quarantine_status`."

    PRD §3.7: "The batch must be in `VERIFIED` or `PARTIALLY_ADMINISTERED`; a batch still `RECEIVED` and therefore unverified, or `QUARANTINED`, `DISCARDED` or already fully `ADMINISTERED`, is refused with `ERR_MILK_NOT_ADMINISTRABLE`."

    Design: Difficulty/cross_entity_state_dependency/milk_administration_depends_on_infection_dimension
    """
    env = fixtures.setup_network()
    admission = fixtures.admit_case(
        env,
        case_reference="CASE-Q2",
        gestational_age_weeks=29.0,
        birth_weight_grams=1200,
        support_modality="ROOM_AIR",
    )
    batch = fixtures.verified_milk_batch(
        env, admission["id"], label_code="LBL-Q2", volume_ml=120.0, expressed_at=CLOCK_START
    )

    fixtures.infection_event(env, admission["id"], "SUSPECT")
    quarantined = validate_success(api.get_milk_batch(batch["id"], env["nurse"]))
    assertions.assert_milk_batch(quarantined)
    assert quarantined["status"] == "QUARANTINED"
    assert quarantined["pre_quarantine_status"] == "VERIFIED"

    refused = api.administer_milk(
        batch["id"], factories.milk_volume_payload(40.0), make_bedside_nurse_headers("nurse-3")
    )
    validate_error(refused, ApiErrorId.MILK_NOT_ADMINISTRABLE)

    after = validate_success(api.get_milk_batch(batch["id"], env["nurse"]))
    assert_close(after["administered_ml"], 0.0)
    assert_close(after["remaining_ml"], 120.0)
    assert_milk_ledger_balanced(after)


def test_resolving_the_infection_replays_the_batch_and_admits_the_administration(api):
    """PRD §3.7: "`RESOLVE` moves the admission `SUSPECTED → RESOLVED` or `CONFIRMED_CLABSI → RESOLVED` and replays the quarantine: every `QUARANTINED` batch returns to the status recorded in its `pre_quarantine_status`, and `pre_quarantine_status` is then cleared back to null."

    PRD §3.7: "Any value of one dimension may coexist with any value of the other, and a transition on one dimension never moves the other."

    Design: Difficulty/cross_entity_state_dependency/milk_administration_depends_on_infection_dimension
    """
    env = fixtures.setup_network()
    admission = fixtures.admit_case(
        env,
        case_reference="CASE-Q2",
        gestational_age_weeks=29.0,
        birth_weight_grams=1200,
        support_modality="ROOM_AIR",
    )
    batch = fixtures.verified_milk_batch(
        env, admission["id"], label_code="LBL-Q2", volume_ml=120.0, expressed_at=CLOCK_START
    )
    nurse_3 = make_bedside_nurse_headers("nurse-3")
    fixtures.infection_event(env, admission["id"], "SUSPECT")
    validate_error(
        api.administer_milk(batch["id"], factories.milk_volume_payload(40.0), nurse_3),
        ApiErrorId.MILK_NOT_ADMINISTRABLE,
    )

    resolved = fixtures.infection_event(env, admission["id"], "RESOLVE")
    assert resolved["infection_status"] == "RESOLVED"
    assert resolved["care_status"] == "ADMITTED"

    replayed = validate_success(api.get_milk_batch(batch["id"], env["nurse"]))
    assert replayed["status"] == "VERIFIED"
    assert replayed["pre_quarantine_status"] is None

    administered = validate_success(
        api.administer_milk(batch["id"], factories.milk_volume_payload(40.0), nurse_3)
    )
    assertions.assert_milk_batch(administered)
    assert administered["status"] == "PARTIALLY_ADMINISTERED"
    assert_close(administered["administered_ml"], 40.0)
    assert_close(administered["remaining_ml"], 80.0)

    admission_after = fixtures.read_admission(env, admission["id"])
    assert_close(admission_after["milk_administered_ml"], 40.0)
    assert admission_after["care_status"] == "ADMITTED"


# ---------------------------------------------------------------------------
# The isolette occupation interval is half-open and carries the buffer
# ---------------------------------------------------------------------------


def test_activation_inside_the_decontamination_buffer_is_refused(api):
    """PRD §3.6: "**The isolette occupation interval** runs from `depart_at` up to `planned_return_at` advanced by the run's `decontamination_minutes`, and it is half-open: the start instant is inside the interval and the end instant is not, because the isolette is clean again at exactly that moment."

    PRD §3.6: "A ground run planned from 08:00 to 12:00 on a given day occupies the isolette through 12:45, so a new run departing at 12:30 conflicts while a new run departing at exactly 12:45 is allowed; a rotor-wing run over the same 08:00-to-12:00 window occupies through 13:30, so a new run departing at 13:00 conflicts."

    Design: Difficulty/resource_temporal_overlap/isolette_interval_half_open_with_decontamination_buffer
    """
    env, second_reservation_id = _isolette_occupied_from_eight_to_twelve()
    isolette_id = env["assets"]["TRANSPORT_ISOLETTE"]["id"]

    refused = api.create_transport_run(
        factories.transport_run_payload(
            second_reservation_id,
            isolette_id,
            mode="GROUND",
            crew_composition=GROUND_CREW,
            depart_at=INSIDE_BUFFER_DEPART_AT,
            planned_return_at=SECOND_RUN_RETURN_AT,
            weather_minimums_met=False,
        ),
        env["coord"],
    )
    validate_error(refused, ApiErrorId.ISOLETTE_UNAVAILABLE)

    _rows, meta = validate_paginated(
        api.list_transport_runs(env["coord"], {"isolette_asset_id": isolette_id})
    )
    assert meta["total_count"] == 1


def test_activation_at_the_exact_end_of_the_occupation_interval_is_allowed(api):
    """PRD §3.6: "A ground run planned from 08:00 to 12:00 on a given day occupies the isolette through 12:45, so a new run departing at 12:30 conflicts while a new run departing at exactly 12:45 is allowed; a rotor-wing run over the same 08:00-to-12:00 window occupies through 13:30, so a new run departing at 13:00 conflicts."

    PRD §3.6: "Its `decontamination_minutes` is derived from the mode: 45 minutes for a `GROUND` run, and 90 minutes — an hour and a half — for both `ROTOR_WING` and `FIXED_WING`, because an aircraft cabin takes longer to turn round than an ambulance."

    Design: Difficulty/resource_temporal_overlap/isolette_interval_half_open_with_decontamination_buffer
    """
    env, second_reservation_id = _isolette_occupied_from_eight_to_twelve()
    isolette_id = env["assets"]["TRANSPORT_ISOLETTE"]["id"]

    created = validate_success(
        api.create_transport_run(
            factories.transport_run_payload(
                second_reservation_id,
                isolette_id,
                mode="GROUND",
                crew_composition=GROUND_CREW,
                depart_at=BUFFER_END_DEPART_AT,
                planned_return_at=SECOND_RUN_RETURN_AT,
                weather_minimums_met=False,
            ),
            env["coord"],
        ),
        201,
    )
    assertions.assert_transport_run(created)
    assert created["status"] == "ACTIVATED"
    assert created["decontamination_minutes"] == 45

    _rows, meta = validate_paginated(
        api.list_transport_runs(env["coord"], {"isolette_asset_id": isolette_id})
    )
    assert meta["total_count"] == 2


# ---------------------------------------------------------------------------
# Surge escalation windows are closed at both ends and scoped to ACTIVE rows
# ---------------------------------------------------------------------------


def test_authorizing_a_window_that_touches_an_active_window_is_refused(api):
    """PRD §3.5: "A unit's escalation windows may not overlap."

    PRD §3.5: "If the requested `[effective_from, effective_to]` interval touches or overlaps — inclusively at both ends — the window of another escalation already `ACTIVE` at that unit, the authorization is refused with `ERR_ESCALATION_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/escalation_windows_conflict_when_endpoints_touch
    """
    env, first, second, _third = _unit_full_with_three_escalation_windows()

    refused = api.authorize_surge_escalation(second["id"], {}, env["admin"])
    validate_error(refused, ApiErrorId.ESCALATION_WINDOW_OVERLAP)

    unchanged = validate_success(api.get_surge_escalation(second["id"], env["admin"]))
    assertions.assert_surge_escalation(unchanged)
    assert unchanged["status"] == "REQUESTED"

    still_active = validate_success(api.get_surge_escalation(first["id"], env["admin"]))
    assert still_active["status"] == "ACTIVE"


def test_the_window_check_consults_active_escalations_only(api):
    """PRD §3.5: "Standing it down — available to both `NetworkAdmin` and the unit's own `UnitDirector` — moves it `ACTIVE → STOOD_DOWN` and re-derives the unit's `escalation_bed_count`, advancing the unit's `version` by one."

    PRD §3.5: "Second, the tier: a ratio at or above 1.00 is `TIER_3`, a ratio at or above 0.90 is `TIER_2`, a ratio at or above 0.80 is `TIER_1`, and a ratio strictly below 0.80 refuses the authorization with `ERR_SURGE_THRESHOLD_NOT_MET`."

    PRD §3.5: "`authorized_beds` is then the lowest of three quantities: the `requested_beds` asked for, that staffing headroom, and the tier's bed cap — floored at zero so it is never negative."

    Design: Difficulty/resource_temporal_overlap/escalation_windows_conflict_when_endpoints_touch
    """
    env, first, second, third = _unit_full_with_three_escalation_windows()
    validate_error(
        api.authorize_surge_escalation(second["id"], {}, env["admin"]),
        ApiErrorId.ESCALATION_WINDOW_OVERLAP,
    )

    stood_down = validate_success(
        api.stand_down_surge_escalation(first["id"], {}, env["admin"])
    )
    assert stood_down["status"] == "STOOD_DOWN"
    unit = fixtures.read_unit(env)
    assert_unit_counts(unit, occupied=2, held=0, available=0, escalation=0)

    authorized = validate_success(
        api.authorize_surge_escalation(third["id"], {}, env["admin"])
    )
    assertions.assert_surge_escalation(authorized)
    assert authorized["status"] == "ACTIVE"
    assert authorized["escalation_tier"] == "TIER_3"
    assert authorized["authorized_beds"] == 6
    assert_decimal_places(authorized["census_ratio_at_request"], 4)
    assert_close(authorized["census_ratio_at_request"], 1.0)


# ---------------------------------------------------------------------------
# Follow-up clinic capacity is an aggregate per UTC calendar day
# ---------------------------------------------------------------------------


def test_a_second_appointment_on_the_same_calendar_day_is_refused(api):
    """PRD §3.9: "Bookings are counted per UTC calendar date: the count for a clinic and a date is the number of that clinic's enrollments in status `SCHEDULED` or `ATTENDED` whose `confirmed_appointment_date` falls on that calendar date, and scheduling is permitted only while that count is strictly below the clinic unit's `followup_clinic_daily_capacity`."

    PRD §3.9: "The limit is an aggregate per calendar day rather than per hour: appointments at 09:00 and at 17:00 on the same date consume the same day's capacity even though they never overlap in time."

    Design: Difficulty/resource_temporal_overlap/clinic_calendar_day_capacity_is_aggregate_not_pointwise
    """
    env, first, second = _clinic_with_one_morning_booking()

    assertions.assert_follow_up_enrollment(first)
    assert first["status"] == "SCHEDULED"
    assert _instant(first["confirmed_appointment_date"]) == _instant(CLINIC_MORNING)

    refused = api.schedule_follow_up_enrollment(
        second["id"], factories.schedule_payload(CLINIC_EVENING), env["fu"]
    )
    validate_error(refused, ApiErrorId.CLINIC_DAY_FULL)

    unchanged = validate_success(api.get_follow_up_enrollment(second["id"], env["fu"]))
    assert unchanged["status"] == "ENROLLED"
    assert unchanged["confirmed_appointment_date"] is None


def test_moving_the_second_appointment_to_the_next_calendar_day_is_allowed(api):
    """PRD §3.9: "The limit is an aggregate per calendar day rather than per hour: appointments at 09:00 and at 17:00 on the same date consume the same day's capacity even though they never overlap in time."

    PRD §3.9: "A permitted scheduling moves the enrollment `ENROLLED → SCHEDULED` and records the confirmed instant."

    Design: Difficulty/resource_temporal_overlap/clinic_calendar_day_capacity_is_aggregate_not_pointwise
    """
    env, _first, second = _clinic_with_one_morning_booking()
    validate_error(
        api.schedule_follow_up_enrollment(
            second["id"], factories.schedule_payload(CLINIC_EVENING), env["fu"]
        ),
        ApiErrorId.CLINIC_DAY_FULL,
    )

    scheduled = validate_success(
        api.schedule_follow_up_enrollment(
            second["id"], factories.schedule_payload(CLINIC_NEXT_DAY), env["fu"]
        )
    )
    assertions.assert_follow_up_enrollment(scheduled)
    assert scheduled["status"] == "SCHEDULED"
    assert _instant(scheduled["confirmed_appointment_date"]) == _instant(CLINIC_NEXT_DAY)

    rows, meta = validate_paginated(
        api.list_follow_up_enrollments(
            env["fu"], {"clinic_unit_id": env["unit_b_id"], "status": "SCHEDULED"}
        )
    )
    assert meta["total_count"] == 2
    booked_dates = sorted(row["confirmed_appointment_date"][:10] for row in rows)
    assert booked_dates == ["2026-09-01", "2026-09-02"]


# ---------------------------------------------------------------------------
# The bed ledger is conserved across an acceptance and its compensation
# ---------------------------------------------------------------------------


def test_bed_ledger_balances_before_and_after_a_revoked_acceptance(api):
    """PRD §2.8: "The invariant that must hold after every single operation is that `staffed_bed_target` plus `escalation_bed_count` equals `occupied_bed_count` plus `held_bed_count` plus `available_bed_count`."

    PRD §3.4: "A permitted revocation moves the `HELD` reservation to `RELEASED` with `released_reason` `REVOKED`, aborts any run still sitting in `ACTIVATED` on that reservation with `abort_reason` `CAPABILITY_LOST`, and advances the unit's `version` by one."

    PRD §2.8: "When `available_bed_count` is at or below zero, the posture is `CLOSED`."

    Design: Difficulty/compensating_invariant/bed_ledger_conserved_across_accept_and_revoke
    """
    env = fixtures.setup_network()
    fixtures.patch_unit(env, staffed_bed_target=1)
    referral = fixtures.create_referral(
        env,
        case_reference="CASE-R1",
        gestational_age_weeks=34.0,
        birth_weight_grams=2000,
        support_modality="ROOM_AIR",
    )
    accepted = fixtures.accept_referral(env, referral["id"])

    before = fixtures.read_unit(env)
    assert_unit_counts(before, occupied=0, held=1, available=0, posture="CLOSED")

    revoked = validate_success(
        api.revoke_referral_acceptance(
            referral["id"], {"expected_unit_version": before["version"]}, env["intake_a"]
        )
    )
    assertions.assert_referral(revoked)
    assert revoked["status"] == "REVOKED"

    after = fixtures.read_unit(env)
    assert_unit_counts(after, occupied=0, held=0, available=1, posture="OPEN")
    assert_bed_ledger_balanced(after)
    assert after["version"] > before["version"]

    reservation = validate_success(
        api.get_bed_reservation(accepted["reservation_id"], env["admin"])
    )
    assertions.assert_bed_reservation(reservation)
    assert reservation["status"] == "RELEASED"
    assert reservation["released_reason"] == "REVOKED"


def test_revoking_an_acceptance_does_not_drain_the_deferral_queue(api):
    """PRD §3.4: "It deliberately does **not** fire from a transport abort or from a revocation of acceptance."

    PRD §3.4: "Deferral moves a referral `PENDING → DEFERRED`, is permitted only when the unit's `available_bed_count` is at or below zero, records `decision_reason` `NO_BED`, and causes the unit's `deferral_queue_depth` to be re-derived."

    Design: Difficulty/compensating_invariant/bed_ledger_conserved_across_accept_and_revoke
    """
    env = fixtures.setup_network()
    fixtures.patch_unit(env, staffed_bed_target=1)
    held = fixtures.create_referral(
        env,
        case_reference="CASE-R1",
        gestational_age_weeks=34.0,
        birth_weight_grams=2000,
        support_modality="ROOM_AIR",
    )
    fixtures.accept_referral(env, held["id"])
    parked = fixtures.create_referral(
        env,
        case_reference="CASE-R2",
        gestational_age_weeks=34.0,
        birth_weight_grams=1600,
        support_modality="ROOM_AIR",
    )
    validate_success(api.defer_referral(parked["id"], {}, env["intake_a"]))

    version = fixtures.read_unit_version(env)
    validate_success(
        api.revoke_referral_acceptance(
            held["id"], {"expected_unit_version": version}, env["intake_a"]
        )
    )

    still_parked = fixtures.read_referral(env, parked["id"])
    assert still_parked["status"] == "DEFERRED"
    assert still_parked["decision_reason"] == "NO_BED"

    unit = fixtures.read_unit(env)
    assert unit["deferral_queue_depth"] == 1
    assert_unit_counts(unit, occupied=0, held=0, available=1)


# ---------------------------------------------------------------------------
# The milk volume ledger is conserved across an administration and its reversal
# ---------------------------------------------------------------------------


def test_milk_ledger_balances_after_a_partial_administration(api):
    """PRD §3.7: "After every operation, including after a reversal, `volume_ml` must equal `administered_ml` plus `discarded_ml` plus `remaining_ml`."

    PRD §3.7: "A 120.0 ml batch with 40.0 ml administered reports 40.0 administered, 80.0 remaining, status `PARTIALLY_ADMINISTERED` and an admission total of 40.0; reversing that 40.0 ml returns 0.0 administered, 120.0 remaining, status `VERIFIED` and an admission total of 0.0; a subsequent discard of the remainder reports 120.0 discarded, 0.0 remaining and status `DISCARDED`."

    Design: Difficulty/compensating_invariant/milk_volume_ledger_conserved_across_administration_reversal
    """
    env = fixtures.setup_network()
    admission = fixtures.admit_case(
        env,
        case_reference="CASE-R3",
        gestational_age_weeks=29.0,
        birth_weight_grams=1200,
        support_modality="ROOM_AIR",
    )
    batch = fixtures.verified_milk_batch(
        env, admission["id"], label_code="LBL-R3", volume_ml=120.0, expressed_at=CLOCK_START
    )

    administered = validate_success(
        api.administer_milk(
            batch["id"],
            factories.milk_volume_payload(40.0),
            make_bedside_nurse_headers("nurse-3"),
        )
    )
    assertions.assert_milk_batch(administered)
    assert_close(administered["administered_ml"], 40.0)
    assert_close(administered["discarded_ml"], 0.0)
    assert_close(administered["remaining_ml"], 80.0)
    assert_milk_ledger_balanced(administered)
    assert administered["status"] == "PARTIALLY_ADMINISTERED"
    assert_close(fixtures.read_admission(env, admission["id"])["milk_administered_ml"], 40.0)


def test_reversal_restores_the_milk_ledger_and_walks_the_batch_status_back(api):
    """PRD §3.7: "A reversal that brings `administered_ml` back to zero restores the batch to `VERIFIED`, so the compensation leaves no drift."

    PRD §3.7: "Every administration and every reversal recomputes the batch's ledger and status, recomputes the admission's `milk_administered_ml` as the sum of `administered_ml` over that admission's batches at one decimal place, and advances the admission's `version` by one."

    PRD §3.7: "A successful verification records the caller as `verified_by_user_id` and moves the batch `RECEIVED → VERIFIED`."

    Design: Difficulty/compensating_invariant/milk_volume_ledger_conserved_across_administration_reversal
    """
    env = fixtures.setup_network()
    admission = fixtures.admit_case(
        env,
        case_reference="CASE-R3",
        gestational_age_weeks=29.0,
        birth_weight_grams=1200,
        support_modality="ROOM_AIR",
    )
    batch = fixtures.verified_milk_batch(
        env, admission["id"], label_code="LBL-R3", volume_ml=120.0, expressed_at=CLOCK_START
    )
    nurse_3 = make_bedside_nurse_headers("nurse-3")
    baseline_version = fixtures.read_admission(env, admission["id"])["version"]
    validate_success(
        api.administer_milk(batch["id"], factories.milk_volume_payload(40.0), nurse_3)
    )

    reversed_batch = validate_success(
        api.reverse_milk_administration(
            batch["id"], factories.milk_volume_payload(40.0), nurse_3
        )
    )
    assertions.assert_milk_batch(reversed_batch)
    assert_close(reversed_batch["administered_ml"], 0.0)
    assert_close(reversed_batch["discarded_ml"], 0.0)
    assert_close(reversed_batch["remaining_ml"], 120.0)
    assert_milk_ledger_balanced(reversed_batch)
    assert reversed_batch["status"] == "VERIFIED"
    assert reversed_batch["verified_by_user_id"] == "nurse-2"

    admission_after = fixtures.read_admission(env, admission["id"])
    assert_close(admission_after["milk_administered_ml"], 0.0)
    assert admission_after["version"] == baseline_version + 2
