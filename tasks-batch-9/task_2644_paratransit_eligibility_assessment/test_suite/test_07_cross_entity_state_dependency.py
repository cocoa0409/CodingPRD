"""Guards that read a second entity's live state, not their own snapshot."""
from test_helpers import factories, validate_error, validate_paginated, validate_success
from test_helpers.api_errors import (
    ERR_CATEGORY_NOT_TRAINABLE,
    ERR_DUE_PROCESS_INCOMPLETE,
    ERR_SUSPENSION_UNSUPPORTED,
)
from test_helpers.assertions import assert_conduct_mirrors
from test_helpers.fixtures import (
    create_applicant,
    issued_determination,
    rider_responded_proceeding,
    set_clock,
)
from test_helpers.test_users import (
    CLERK_HEADERS,
    CONDUCT_OFFICER_2_HEADERS,
    CONDUCT_OFFICER_HEADERS,
    TRAINER_HEADERS,
)


def _proceeding_undercut_by_an_excusal(api):
    """A RIDER_RESPONDED proceeding whose rider no longer meets the thresholds."""
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Delia Kwon",
        date_of_birth="1963-12-05",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )
    context = rider_responded_proceeding(api, applicant=rider)
    proceeding = context["proceeding"]

    assert proceeding["origin"] == "AUTO_THRESHOLD"
    assert proceeding["proposed_by_user_id"] is None
    assert proceeding["points_at_proposal"] == 6
    assert proceeding["status"] == "RIDER_RESPONDED"
    assert proceeding["response_deadline_date"] == "2026-08-15"

    excused = validate_success(
        api.excuse_trip_event(
            context["trip_events"][0]["id"],
            factories.excuse_payload(
                excuse_reason="Provider cancelled the dialysis appointment"
            ),
            CONDUCT_OFFICER_HEADERS,
        )
    )
    assert excused["excused"] is True
    assert excused["points_assessed"] == 0
    return context


def test_upholding_is_refused_once_an_excusal_drops_the_live_conduct_mirrors(api):
    """The uphold guard re-tests the rider now, ignoring points_at_proposal.

    "And only then is the conduct record re-tested: upholding requires that,
    recomputed at this very instant, `no_show_points_event_basis` is at least 6,
    `chargeable_miss_count_90d` is at least 3 and `no_show_ratio_pct` is strictly
    above 10.0; if any of the three has fallen below its threshold — because
    misses aged out of the rolling window, or because an officer excused one in
    the meantime — the uphold is refused with `ERR_SUSPENSION_UNSUPPORTED` (422)."

    "Excusing sets `excused` to true and `points_assessed` to 0, and increments
    the rider's `version`."

    Design: Difficulty/cross_entity_state_dependency/suspension_decide_blocked_by_recomputed_applicant_conduct_mirrors
    """
    context = _proceeding_undercut_by_an_excusal(api)
    proceeding_id = context["proceeding"]["id"]

    rider = validate_success(
        api.get_applicant(context["applicant"]["id"], CONDUCT_OFFICER_HEADERS)
    )
    assert_conduct_mirrors(
        rider,
        event_basis=4,
        miss_count=2,
        scheduled_count=3,
        ratio_pct=66.7,
    )

    error = validate_error(
        api.decide_suspension(
            proceeding_id,
            factories.suspension_decision_payload(
                decision="UPHELD", suspension_start_date="2026-09-01"
            ),
            CONDUCT_OFFICER_2_HEADERS,
        ),
        ERR_SUSPENSION_UNSUPPORTED,
        422,
    )
    assert error["error_id"] != ERR_DUE_PROCESS_INCOMPLETE

    proceeding = validate_success(
        api.get_suspension_proceeding(proceeding_id, CONDUCT_OFFICER_HEADERS)
    )
    assert proceeding["status"] == "RIDER_RESPONDED"
    assert proceeding["duration_days"] == 0
    assert proceeding["suspension_start_date"] is None
    assert proceeding["decided_by_user_id"] is None

    rider = validate_success(api.get_applicant(rider["id"], CLERK_HEADERS))
    assert rider["prior_upheld_suspension_count"] == 0
    assert rider["suspension_days_ledger_total"] == 0
    assert rider["service_status"] == "ACTIVE"


def test_rescinding_the_same_proceeding_closes_it_without_escalating_the_ladder(api):
    """The rescind branch has no conduct precondition and owes nothing.

    "A `RESCINDED` decision moves the proceeding to the terminal `RESCINDED` and
    closes it with nothing owed: `duration_days`, `days_served` and
    `days_forgiven` are all zero and `suspension_end_date` stays null."

    "a proceeding that was `RESCINDED`, and one voided while still merely
    `PROPOSED`, never count, so a rescinded first offence does not escalate the
    second."

    Design: Difficulty/cross_entity_state_dependency/suspension_decide_blocked_by_recomputed_applicant_conduct_mirrors
    """
    context = _proceeding_undercut_by_an_excusal(api)
    proceeding_id = context["proceeding"]["id"]

    validate_error(
        api.decide_suspension(
            proceeding_id,
            factories.suspension_decision_payload(
                decision="UPHELD", suspension_start_date="2026-09-01"
            ),
            CONDUCT_OFFICER_2_HEADERS,
        ),
        ERR_SUSPENSION_UNSUPPORTED,
        422,
    )

    rescinded = validate_success(
        api.decide_suspension(
            proceeding_id,
            factories.suspension_decision_payload(decision="RESCINDED"),
            CONDUCT_OFFICER_2_HEADERS,
        )
    )
    assert rescinded["status"] == "RESCINDED"
    assert rescinded["duration_days"] == 0
    assert rescinded["days_served"] == 0
    assert rescinded["days_forgiven"] == 0
    assert rescinded["suspension_end_date"] is None

    rider = validate_success(
        api.get_applicant(context["applicant"]["id"], CLERK_HEADERS)
    )
    assert rider["prior_upheld_suspension_count"] == 0


def _unconditional_grant_for_a_power_wheelchair_rider(api):
    """An ISSUED UNCONDITIONAL grant reached through the low-score branch."""
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Sam Iverson",
        date_of_birth="1947-05-12",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="POWER_WHEELCHAIR",
    )
    context = issued_determination(
        api,
        applicant=rider,
        functional_answers=factories.functional_answers(
            can_board_bus_steps=False,
            can_navigate_unfamiliar_route=True,
            max_walk_distance_meters=900,
            uses_mobility_aid_outdoors=True,
            has_cognitive_impairment=False,
        ),
        attests_permanent=True,
        score_overrides={
            "board_alight_score": 0,
            "wayfinding_score": 4,
            "distance_meters_walked": 900,
            "heat_sensitivity_flag": False,
        },
        booking_overrides={"requires_wheelchair_position": True},
        draft_overrides={
            "category": "UNCONDITIONAL",
            "effective_date": "2026-08-06",
            "rationale": "Cannot board any fixed-route vehicle",
        },
        attendance_at="2026-08-05T09:30:00Z",
    )
    return context


def test_an_unconditional_grant_cannot_be_referred_to_travel_training(api):
    """The referral guard reads the governing grant's category and status.

    "The rider must hold a determination in `ISSUED` whose category is
    `CONDITIONAL` or `TEMPORARY`; a rider whose issued grant is `UNCONDITIONAL`
    or `INELIGIBLE`, or who holds none at all, is refused with
    `ERR_CATEGORY_NOT_TRAINABLE` (422)."

    Design: Difficulty/cross_entity_state_dependency/travel_training_referral_requires_trainable_determination_category
    """
    context = _unconditional_grant_for_a_power_wheelchair_rider(api)
    determination = context["determination"]
    rider_id = context["applicant"]["id"]

    assert context["assessment"]["recommended_category"] == "UNCONDITIONAL"
    assert context["assessment"]["recommended_term_days"] == 1825
    assert determination["status"] == "ISSUED"
    assert determination["category"] == "UNCONDITIONAL"
    assert determination["term_days"] == 1825
    assert determination["expires_at"] == "2031-08-05"

    rider = validate_success(api.get_applicant(rider_id, CLERK_HEADERS))
    assert rider["current_eligibility_status"] == "ELIGIBLE"
    assert rider["eligibility_category"] == "UNCONDITIONAL"

    validate_error(
        api.create_travel_training_referral(
            rider_id,
            factories.referral_payload(
                referral_reason="STAFF_REFERRAL", determination_id=determination["id"]
            ),
            TRAINER_HEADERS,
        ),
        ERR_CATEGORY_NOT_TRAINABLE,
        422,
    )


def test_an_unconditional_issue_opens_no_referral_and_carries_no_conditions(api):
    """Only the conditional side effects exist, so both listings stay empty.

    "When the category is `CONDITIONAL` it creates a travel-training referral for
    the rider with `referral_reason` `CONDITIONAL_ELIGIBILITY_AUTO`,
    `determination_id` pointing at this determination, and `status` `REFERRED`."

    "Each entry in `trip_conditions` becomes one immutable trip condition
    attached to the determination, and the number created is recorded on the
    determination as `trip_condition_count`."

    Design: Difficulty/cross_entity_state_dependency/travel_training_referral_requires_trainable_determination_category
    """
    context = _unconditional_grant_for_a_power_wheelchair_rider(api)
    determination = context["determination"]
    rider_id = context["applicant"]["id"]

    assert determination["trip_condition_count"] == 0

    _referrals, referral_meta = validate_paginated(
        api.list_travel_training_referrals(
            TRAINER_HEADERS, params={"applicant_id": rider_id}
        )
    )
    assert referral_meta["total_count"] == 0

    _conditions, condition_meta = validate_paginated(
        api.list_trip_conditions(determination["id"], CLERK_HEADERS)
    )
    assert condition_meta["total_count"] == 0
