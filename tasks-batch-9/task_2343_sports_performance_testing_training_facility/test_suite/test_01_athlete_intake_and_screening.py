"""Athlete intake, the movement screen, and the two parallel athlete state dimensions.

Every test builds its own world from an empty database through the documented
endpoints: a coach with a live certification, an athlete registered at the front
desk, and whatever screens, injuries or bookings the behaviour under test needs.
"""
import pytest

from test_helpers import (
    advance_clock,
    api_client,
    assert_athlete,
    assert_draft_test_session,
    assert_two_decimals,
    create_athlete_payload,
    create_compliant_coach,
    create_injury_record_payload,
    create_test_session_payload,
    enroll_athlete,
    fetch_athlete,
    fetch_enrollment,
    fetch_group_session,
    register_athlete,
    run_movement_screen,
    screen_results_payload,
    setup_cleared_athlete,
    setup_session_with_coach,
    validate_error,
    validate_paginated,
    validate_success,
)

# The five screen codes and the scores that put an athlete on each side of the
# 12.00 restriction threshold at intake.
SCORES_AT_THRESHOLD = {"OH_SQUAT": 1, "HURDLE_STEP": 1, "INLINE_LUNGE": 1,
                       "SL_HOP_L": 0, "SL_HOP_R": 0}
SCORES_BELOW_THRESHOLD = {"OH_SQUAT": 1, "HURDLE_STEP": 1, "INLINE_LUNGE": 2,
                          "SL_HOP_L": 0, "SL_HOP_R": 0}
# raw total 9, asymmetry 2 -> deficit (15 - 9) + 2.0 * 2 = 10
SCORES_WITH_ASYMMETRY = {"OH_SQUAT": 2, "HURDLE_STEP": 2, "INLINE_LUNGE": 1,
                         "SL_HOP_L": 3, "SL_HOP_R": 1}


def test_01_registration_returns_every_declared_field_with_its_system_default(
        api, front_desk_headers, performance_director_headers):
    """A newly registered athlete carries the documented parallel states and empty counters.

    "A new athlete arrives in two parallel states that evolve independently and
    gate participation separately." "Alongside them sit counters that all start
    empty: `screen_count` and `attended_count` and `no_show_count` and
    `no_show_strikes` at 0, and `injury_risk_score`, `last_composite_percentile`,
    `last_performance_test_at`, `next_test_due_on` and `team_contract_id` all null."

    Design: Corner/entities/athlete_creation_returns_all_declared_fields_with_system_defaults
    """
    advance_clock("2026-08-01T09:00:00Z", performance_director_headers)

    created = validate_success(api.create_athlete({
        "full_name": "Iris Nakamura",
        "date_of_birth": "2010-01-15",
        "sport": "BASKETBALL",
        "position": "GUARD",
        "guardian_email": "guardian.nakamura@example.com",
    }, front_desk_headers), expected_status=201)

    assert_athlete(created)
    assert created["full_name"] == "Iris Nakamura"
    assert created["membership_status"] == "PENDING_INTAKE"
    assert created["training_clearance"] == "SCREEN_PENDING"
    assert created["age_years"] == 16
    assert created["maturity_offset_months"] == 0
    assert created["screen_count"] == 0
    assert created["attended_count"] == 0
    assert created["no_show_count"] == 0
    assert created["no_show_strikes"] == 0
    assert created["injury_risk_score"] is None
    assert created["last_composite_percentile"] is None
    assert created["last_performance_test_at"] is None
    assert created["next_test_due_on"] is None
    assert created["team_contract_id"] is None
    assert created["readiness_index"] == pytest.approx(50.00, abs=0.01)
    assert created["version"] == 1


def test_02_client_supplied_computed_counters_are_ignored_at_registration(
        api, front_desk_headers):
    """The derived age, readiness and counters are server-owned, not client input.

    "`age_years` is never supplied by a client." "It is the number of days between
    `date_of_birth` and the current logical date, divided by 365.25, with any
    fraction discarded — that is, rounded down to a whole year."

    Design: Corner/entities/athlete_computed_counters_input_ignored_on_create
    """
    created = validate_success(api.create_athlete({
        "full_name": "Injected Fields",
        "date_of_birth": "2010-01-15",
        "sport": "BASKETBALL",
        "position": "GUARD",
        "guardian_email": "guardian.injected@example.com",
        "age_years": 99,
        "readiness_index": 100.00,
        "screen_count": 7,
        "no_show_strikes": 5,
        "injury_risk_score": 0.00,
    }, front_desk_headers), expected_status=201)

    assert created["age_years"] == 16, "age_years derives from the clock, not the body"
    assert created["readiness_index"] == pytest.approx(50.00, abs=0.01)
    assert created["screen_count"] == 0
    assert created["no_show_strikes"] == 0
    assert created["injury_risk_score"] is None


def test_03_guardian_email_stays_null_for_an_athlete_who_needs_none(
        api, front_desk_headers, coach_headers, performance_director_headers):
    """An adult athlete registered without a guardian contact reads back with it null.

    "`guardian_email` holds the parent or guardian contact and defaults to null,
    but it is **required** whenever the athlete's derived `age_years` is under 18
    at the moment of registration; omitting it for a minor is rejected as an
    invalid request."

    Design: Corner/entities/athlete_retrieval_returns_stored_entity
    """
    created = validate_success(api.create_athlete({
        "full_name": "Dana Whitfield",
        "date_of_birth": "2005-03-02",
        "sport": "SOCCER",
        "position": "MIDFIELDER",
    }, front_desk_headers), expected_status=201)
    assert created["guardian_email"] is None

    fetched = validate_success(api.get_athlete(created["id"], performance_director_headers))

    assert fetched["id"] == created["id"]
    assert fetched["full_name"] == "Dana Whitfield"
    assert fetched["date_of_birth"] == "2005-03-02"
    assert fetched["sport"] == "SOCCER"
    assert fetched["position"] == "MIDFIELDER"
    assert fetched["guardian_email"] is None
    assert fetched["membership_status"] == "PENDING_INTAKE"
    assert fetched["training_clearance"] == "SCREEN_PENDING"
    assert fetched["version"] == 1


def test_04_athlete_listing_filters_by_sport_and_paginates(api, performance_director_headers):
    """The sport filter narrows the collection and limit/offset page through it.

    "Athletes may be filtered by `sport`, `membership_status`, `training_clearance`,
    and `team_contract_id`." "The `limit` query parameter caps the number of rows
    returned; it defaults to 10, may not be smaller than 1, and may not be larger
    than 100."

    Design: Corner/entities/athlete_listing_filters_by_sport_and_paginates
    """
    hoop_one = register_athlete(full_name="Hoop One")
    hoop_two = register_athlete(full_name="Hoop Two")
    pitch_one = register_athlete(full_name="Pitch One", sport="SOCCER",
                                 position="MIDFIELDER")

    rows, meta = validate_paginated(api.list_athletes(
        performance_director_headers,
        params={"sport": "BASKETBALL", "limit": 1, "offset": 0}))

    assert len(rows) == 1, "a limit of 1 returns exactly one row"
    assert meta["total_count"] == 2, "only the two basketball athletes match the filter"
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert meta["has_more"] is True
    assert rows[0]["sport"] == "BASKETBALL"
    assert rows[0]["id"] in (hoop_one["id"], hoop_two["id"])
    assert pitch_one["id"] not in [row["id"] for row in rows]


def test_05_opening_a_test_session_without_a_battery_type_is_an_invalid_request(api):
    """`battery_type` is a required declared input on the session open.

    "Only a `Coach` may open a test session, supplying the target `athlete_id` and
    the `battery_type`, which is either `MOVEMENT_SCREEN` or `PERFORMANCE_BATTERY`
    and is immutable once the session exists."

    Design: Corner/entities/test_session_creation_missing_required_battery_type_returns_invalid_request
    """
    _staff, _certification, coach = create_compliant_coach(full_name="Coach Missing Field")
    athlete = register_athlete(full_name="Battery Type Athlete")

    validate_error(api.create_test_session({"athlete_id": athlete["id"]}, coach),
                   "ERR_INVALID_REQUEST", expected_status=422)


def test_06_the_acting_coach_identity_overrides_injected_session_system_fields(api):
    """A session opens DRAFT with `administered_by_staff_id` taken from the caller.

    "The server copies the acting coach's `X-User-ID` into
    `administered_by_staff_id`, which is why an opener whose `credential_status`
    is `LAPSED`, or whose `liability_insurance_expires_on` precedes the current
    logical date, is refused with `ERR_STAFF_CREDENTIAL_LAPSED`."

    Design: Corner/entities/test_session_system_fields_input_ignored_on_create
    """
    staff, _certification, coach = create_compliant_coach(
        full_name="Coach Sysfield", role_title="PERFORMANCE_COACH")
    other_staff, _other_cert, _other_coach = create_compliant_coach(
        full_name="Coach Bystander")
    athlete = register_athlete(full_name="System Field Athlete")

    created = validate_success(api.create_test_session({
        "athlete_id": athlete["id"],
        "battery_type": "MOVEMENT_SCREEN",
        "id": "11111111-1111-4111-8111-111111111111",
        "administered_by_staff_id": other_staff["id"],
        "status": "FINALIZED",
        "composite_percentile": 99.0,
    }, coach), expected_status=201)

    assert created["id"] != "11111111-1111-4111-8111-111111111111"
    assert created["administered_by_staff_id"] == staff["id"], \
        "the acting coach's own id is what is recorded"
    assert_draft_test_session(created)
    assert created["version"] == 1


def test_07_a_performance_battery_cannot_be_opened_while_the_screen_is_pending(api):
    """An unscreened athlete is inert for performance testing but may still be screened.

    "While `training_clearance` is `SCREEN_PENDING` the athlete is inert: they
    cannot be enrolled in any group session, and no `PERFORMANCE_BATTERY` test
    session may be opened for them."

    Design: Corner/errors/performance_battery_before_screen_returns_movement_screen_required
    """
    _staff, _certification, coach = create_compliant_coach(full_name="Coach Screen Gate")
    athlete = register_athlete(full_name="Unscreened Athlete")

    validate_error(
        api.create_test_session(
            create_test_session_payload(athlete["id"], "PERFORMANCE_BATTERY"), coach),
        "ERR_MOVEMENT_SCREEN_REQUIRED", expected_status=422)

    screen = validate_success(api.create_test_session(
        create_test_session_payload(athlete["id"], "MOVEMENT_SCREEN"), coach),
        expected_status=201)
    assert screen["battery_type"] == "MOVEMENT_SCREEN"

    _rows, meta = validate_paginated(api.list_test_sessions(
        coach, params={"athlete_id": athlete["id"]}))
    assert meta["total_count"] == 1, "the refused open must not have created a session"


def test_08_appending_results_to_a_finalized_session_is_already_terminal(api):
    """A finalized screen accepts no further measurement rows.

    "Measurements are appended while the session is `DRAFT`, and only then;
    appending to a session that has already been finalized returns
    `ERR_ALREADY_TERMINAL`."

    Design: Corner/errors/appending_results_to_a_finalized_test_session_returns_already_terminal
    """
    _staff, _certification, coach = create_compliant_coach(full_name="Coach Terminal")
    athlete = register_athlete(full_name="Terminal Screen Athlete")
    finalized = run_movement_screen(athlete["id"], coach)
    assert finalized["status"] == "FINALIZED"
    assert finalized["result_count"] == 5

    validate_error(
        api.submit_test_results(finalized["id"], screen_results_payload(), coach),
        "ERR_ALREADY_TERMINAL", expected_status=409)

    reread = validate_success(api.get_test_session(finalized["id"], coach))
    assert reread["result_count"] == 5
    assert reread["risk_score"] == pytest.approx(finalized["risk_score"], abs=0.01)


def test_09_a_risk_score_of_exactly_twelve_restricts_the_athlete(api):
    """The restriction threshold is inclusive, so exactly 12.00 lands RESTRICTED.

    "The restriction threshold is 12.00 and it is **inclusive on the restricted
    side**." "A `risk_score` of 12.00 or higher sets `training_clearance` to
    `RESTRICTED`; anything below 12.00 sets it to `CLEARED`."

    Design: Corner/calculations/movement_screen_risk_score_at_and_below_restriction_threshold
    """
    _staff, _certification, coach = create_compliant_coach(full_name="Coach Threshold")
    athlete = register_athlete(full_name="Threshold At")

    screen = run_movement_screen(athlete["id"], coach, SCORES_AT_THRESHOLD)

    assert screen["variant_applied"] == "INTAKE_SCREEN"
    assert screen["asymmetry_points"] == 0
    assert_two_decimals(screen["risk_score"], "risk_score")
    assert screen["risk_score"] == pytest.approx(12.00, abs=0.01)

    reread = fetch_athlete(athlete["id"])
    assert reread["injury_risk_score"] == pytest.approx(12.00, abs=0.01)
    assert reread["training_clearance"] == "RESTRICTED"
    assert reread["membership_status"] == "ACTIVE"
    assert reread["screen_count"] == 1


def test_10_a_risk_score_just_below_twelve_clears_the_athlete(api):
    """One extra point of movement quality drops the deficit below the threshold.

    "A **deficit** is then formed by subtracting the raw total from the maximum
    attainable screen score of 15 and adding twice the asymmetry points — the
    asymmetry weight is 2.0, so a single point of left-right imbalance costs as
    much as two points of lost movement quality."

    Design: Corner/calculations/movement_screen_risk_score_at_and_below_restriction_threshold
    """
    _staff, _certification, coach = create_compliant_coach(full_name="Coach Below")
    athlete = register_athlete(full_name="Threshold Below")

    screen = run_movement_screen(athlete["id"], coach, SCORES_BELOW_THRESHOLD)

    assert screen["variant_applied"] == "INTAKE_SCREEN"
    assert screen["risk_score"] == pytest.approx(11.00, abs=0.01)

    reread = fetch_athlete(athlete["id"])
    assert reread["injury_risk_score"] == pytest.approx(11.00, abs=0.01)
    assert reread["training_clearance"] == "CLEARED"
    assert reread["membership_status"] == "ACTIVE"
    assert reread["screen_count"] == 1


def test_11_the_intake_screen_forces_the_history_multiplier_to_one(api):
    """The first screen scores movement quality only, at a multiplier of exactly 1.00.

    "**Intake screen** (`INTAKE_SCREEN`), when the athlete's `screen_count` is
    still 0 at finalize time: the history multiplier is forced to exactly 1.00."

    Design: Difficulty/dual_variant_calc/movement_screen_intake_variant_scores_lower_than_reassessment_variant
    """
    _staff, _certification, coach = create_compliant_coach(full_name="Dana Reyes")
    athlete = register_athlete(**create_athlete_payload(
        full_name="Mia Okafor", date_of_birth="2010-01-15",
        sport="BASKETBALL", position="GUARD"))

    screen = run_movement_screen(athlete["id"], coach, SCORES_WITH_ASYMMETRY)

    assert screen["variant_applied"] == "INTAKE_SCREEN"
    assert screen["asymmetry_points"] == 2
    assert screen["risk_score"] == pytest.approx(10.00, abs=0.01)

    reread = fetch_athlete(athlete["id"])
    assert reread["injury_risk_score"] == pytest.approx(10.00, abs=0.01)
    assert reread["training_clearance"] == "CLEARED", "10.00 is below the threshold"
    assert reread["screen_count"] == 1


def test_12_the_reassessment_variant_scales_identical_scores_by_open_rehabilitation(
        api, medical_provider_headers):
    """Identical movement scores cross the threshold once two rehabs are open.

    "**Reassessment screen** (`REASSESSMENT_SCREEN`), when `screen_count` is 1 or
    more at finalize time: the history multiplier is the smaller of the
    injury-history cap of 1.45 and the quantity one plus 0.15 for each of the
    athlete's injury records whose `status` is `ACTIVE_REHAB` at finalize time."

    Design: Difficulty/dual_variant_calc/movement_screen_intake_variant_scores_lower_than_reassessment_variant
    """
    _staff, _certification, coach = create_compliant_coach(full_name="Dana Reyes")
    athlete = register_athlete(**create_athlete_payload(
        full_name="Mia Okafor", date_of_birth="2010-01-15",
        sport="BASKETBALL", position="GUARD"))

    first = run_movement_screen(athlete["id"], coach, SCORES_WITH_ASYMMETRY)
    assert first["variant_applied"] == "INTAKE_SCREEN"
    assert first["risk_score"] == pytest.approx(10.00, abs=0.01)

    for body_region, severity, occurred_on in (("ANKLE", "MODERATE", "2026-05-04"),
                                               ("HIP", "MILD", "2026-06-18")):
        injury = validate_success(api.create_injury_record(
            create_injury_record_payload(athlete["id"], body_region=body_region,
                                         severity=severity, occurred_on=occurred_on,
                                         rts_required=False),
            medical_provider_headers), expected_status=201)
        assert injury["status"] == "ACTIVE_REHAB"

    second = run_movement_screen(athlete["id"], coach, SCORES_WITH_ASYMMETRY)

    assert second["variant_applied"] == "REASSESSMENT_SCREEN"
    assert second["asymmetry_points"] == 2
    # 10.00 deficit x min(1.45, 1 + 0.15 + 0.15) = 10.00 x 1.30
    assert second["risk_score"] == pytest.approx(13.00, abs=0.01)
    assert second["risk_score"] > first["risk_score"]

    reread = fetch_athlete(athlete["id"])
    assert reread["injury_risk_score"] == pytest.approx(13.00, abs=0.01)
    assert reread["screen_count"] == 2
    assert reread["training_clearance"] == "RESTRICTED", \
        "the same scores that cleared at intake now restrict"
    assert reread["membership_status"] == "ACTIVE"


def test_13_suspension_leaves_the_clearance_dimension_free_to_move(
        api, performance_director_headers, medical_provider_headers):
    """Membership and clearance evolve independently, so a hold applies to a suspended athlete.

    "The transition is permitted from either `CLEARED` or `RESTRICTED` — both
    source states behave identically — and drives `training_clearance` to
    `MEDICAL_HOLD`."

    Design: Difficulty/non_linear_state_machine/athlete_membership_and_clearance_dimensions_evolve_independently
    """
    athlete, _staff, _coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "Tariq Bello"}, coach_name="Rae Sandoval")
    assert athlete["membership_status"] == "ACTIVE"
    assert athlete["training_clearance"] == "CLEARED"

    suspended = validate_success(api.suspend_athlete(
        athlete["id"], {"reason": "Unpaid balance review"}, performance_director_headers))
    assert suspended["membership_status"] == "SUSPENDED"
    assert suspended["training_clearance"] == "CLEARED", \
        "suspension is a membership event and does not touch clearance"

    held = validate_success(api.medical_hold_athlete(
        athlete["id"], {"hold_reason": "Concussion protocol"}, medical_provider_headers))

    assert held["training_clearance"] == "MEDICAL_HOLD"
    assert held["membership_status"] == "SUSPENDED", \
        "the medical hold leaves the membership dimension where it was"


def test_14_reinstatement_restores_membership_while_the_medical_hold_persists(
        api, performance_director_headers, medical_provider_headers):
    """Reinstatement zeroes the strike counter and moves only the membership dimension.

    "Reinstatement is the mirror: `membership_status` moves `SUSPENDED → ACTIVE`,
    `no_show_strikes` is reset to 0 so the next no-show is charged at the base
    multiplier again, and `readiness_index` is recomputed."

    Design: Difficulty/non_linear_state_machine/athlete_membership_and_clearance_dimensions_evolve_independently
    """
    athlete, _staff, _coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "Tariq Bello"}, coach_name="Rae Sandoval")
    validate_success(api.suspend_athlete(
        athlete["id"], {"reason": "Unpaid balance review"}, performance_director_headers))
    validate_success(api.medical_hold_athlete(
        athlete["id"], {"hold_reason": "Concussion protocol"}, medical_provider_headers))

    reinstated = validate_success(api.reinstate_athlete(
        athlete["id"], performance_director_headers))

    assert reinstated["membership_status"] == "ACTIVE"
    assert reinstated["training_clearance"] == "MEDICAL_HOLD", \
        "reinstatement never lifts a medical hold"
    assert reinstated["no_show_strikes"] == 0
    assert reinstated["screen_count"] == 1
    assert reinstated["injury_risk_score"] == pytest.approx(0.00, abs=0.01)


def test_15_suspension_cancels_the_forward_book_and_promotes_the_waitlist(
        api, performance_director_headers):
    """The suspension cascade frees a held slot and the waitlist takes it immediately.

    "`membership_status` moves `ACTIVE → SUSPENDED` and the forward book is
    cleared: every enrollment of that athlete sitting in `RESERVED` or
    `WAITLISTED` on a group session whose `start_at` is later than the current
    logical clock and whose `session_status` is `SCHEDULED` or `ROSTER_LOCKED`
    becomes `CANCELED` with `cancel_reason` set to `ATHLETE_SUSPENDED`, each
    cancellation refunds its funding source exactly as described in §2.10, each
    freed slot triggers waitlist promotion on its session, and each affected
    session recomputes its coaching requirement."

    Design: Corner/state_machines/athlete_suspension_cascades_to_future_reserved_enrollments
    """
    source, staff, _coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "Suspend Source"}, coach_name="Coach Cascade")
    target, _staff_b, _coach_b = setup_cleared_athlete(
        athlete_overrides={"full_name": "Waitlist Target"}, coach_name="Coach Cascade Two")

    session = setup_session_with_coach(
        staff["id"], start_at="2026-08-25T16:00:00Z", end_at="2026-08-25T17:00:00Z",
        station_count=3, max_athletes=1)
    held = enroll_athlete(source["id"], session["id"])
    assert held["status"] == "RESERVED"
    waitlisted = enroll_athlete(target["id"], session["id"], request_waitlist=True)
    assert waitlisted["status"] == "WAITLISTED"

    suspended = validate_success(api.suspend_athlete(
        source["id"], {"reason": "Outstanding balance"}, performance_director_headers))
    assert suspended["membership_status"] == "SUSPENDED"

    cancelled = fetch_enrollment(held["id"])
    assert cancelled["status"] == "CANCELED"
    assert cancelled["cancel_reason"] == "ATHLETE_SUSPENDED"

    promoted = fetch_enrollment(waitlisted["id"])
    assert promoted["status"] == "RESERVED"
    assert promoted["promoted_from_waitlist"] is True
    assert promoted["funding_source"] == "DROP_IN"
    assert promoted["charge_cents"] == 4500

    reread = fetch_group_session(session["id"])
    assert reread["reserved_count"] == 1
    assert reread["waitlisted_count"] == 0
